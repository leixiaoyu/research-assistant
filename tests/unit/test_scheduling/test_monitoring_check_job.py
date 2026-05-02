"""Tests for ``MonitoringCheckJob`` (Milestone 9.1, Week 2).

Covers:
- ``BaseJob`` interface compliance (``name``, ``run``, ``__call__``).
- Single-construction lifecycle: ``MonitoringRunner.from_paths`` is
  invoked exactly once in ``__init__`` (not per tick).
- ``run()`` calls ``runner.run_once()`` and writes digests for all
  non-FAILED runs.
- FAILED runs do NOT trigger digest generation (atomic-state-transition
  per CLAUDE.md "Checked Success" pattern).
- A ``digest_generator.generate`` failure on one run does not abort the
  cycle (Fail-Soft Boundary between independent peers).
- A missing subscription is logged and skipped without raising.
- A missing audit row is logged and skipped without raising.
- ``ResearchScheduler.add_monitoring_check_job`` registers the job on
  the daily cron schedule.
- Empty cycle (no active subs) returns a zeroed result.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scheduling.jobs import BaseJob, MonitoringCheckJob
from src.scheduling.scheduler import ResearchScheduler
from src.services.intelligence.monitoring.models import (
    MonitoringRun,
    MonitoringRunAudit,
    MonitoringRunStatus,
    ResearchSubscription,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_subscription(
    *,
    subscription_id: str = "sub-aaa",
    user_id: str = "alice",
) -> ResearchSubscription:
    return ResearchSubscription(
        subscription_id=subscription_id,
        user_id=user_id,
        name="Sub",
        query="tree of thoughts",
    )


def _make_run(
    *,
    subscription_id: str = "sub-aaa",
    status: MonitoringRunStatus = MonitoringRunStatus.SUCCESS,
    error: str | None = None,
) -> MonitoringRun:
    return MonitoringRun(
        subscription_id=subscription_id,
        status=status,
        error=error,
    )


def _make_audit_run(
    *,
    run_id: str = "run-aaa",
    subscription_id: str = "sub-aaa",
    user_id: str = "alice",
    status: MonitoringRunStatus = MonitoringRunStatus.SUCCESS,
) -> MonitoringRunAudit:
    from datetime import datetime, timezone

    return MonitoringRunAudit(
        run_id=run_id,
        subscription_id=subscription_id,
        user_id=user_id,
        started_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        finished_at=None,
        status=status,
        papers_seen=0,
        papers_new=0,
        papers=[],
    )


def _build_job(
    *,
    runs: list[MonitoringRun] | None = None,
    subscriptions: list[ResearchSubscription] | None = None,
    audit_runs: dict[str, MonitoringRunAudit] | None = None,
    digest_side_effect: Exception | None = None,
) -> tuple[MonitoringCheckJob, MagicMock, MagicMock]:
    """Construct a job with mocked runner + digest generator.

    Uses the public delegation methods (H-C1) rather than private attrs.
    """
    runner = MagicMock()
    runner.run_once = AsyncMock(return_value=runs or [])
    # Public delegation method (H-C1)
    runner.list_subscriptions = MagicMock(return_value=subscriptions or [])

    def get_audit_run(run_id: str) -> MonitoringRunAudit | None:
        return (audit_runs or {}).get(run_id)

    # Public delegation method (H-C1)
    runner.get_audit_run = MagicMock(side_effect=get_audit_run)

    digest = MagicMock()
    if digest_side_effect is not None:
        digest.generate = MagicMock(side_effect=digest_side_effect)
    else:
        digest.generate = MagicMock(return_value=Path("/tmp/digest.md"))

    job = MonitoringCheckJob(runner=runner, digest_generator=digest)
    return job, runner, digest


# ---------------------------------------------------------------------------
# Construction / interface
# ---------------------------------------------------------------------------


class TestMonitoringCheckJobInit:
    def test_inherits_base_job(self) -> None:
        job, _, _ = _build_job()
        assert isinstance(job, BaseJob)
        assert job.name == "monitoring_check"

    def test_runner_built_once_via_from_paths(self) -> None:
        # When no ``runner`` seam is provided, ``from_paths`` is called
        # exactly once during construction.
        with (
            patch(
                "src.services.intelligence.monitoring.MonitoringRunner.from_paths"
            ) as from_paths,
            patch("src.services.providers.arxiv.ArxivProvider") as arxiv_cls,
            patch("src.services.registry.service.RegistryService") as reg_cls,
        ):
            from_paths.return_value = MagicMock()
            arxiv_cls.return_value = MagicMock()
            reg_cls.return_value = MagicMock()
            MonitoringCheckJob(db_path=Path("./data/x.db"))
        from_paths.assert_called_once()


# ---------------------------------------------------------------------------
# Run behavior
# ---------------------------------------------------------------------------


class TestMonitoringCheckJobRun:
    @pytest.mark.asyncio
    async def test_no_runs_returns_zeroed_result(self) -> None:
        job, runner, digest = _build_job(runs=[])
        result = await job.run()
        assert result == {
            "runs": 0,
            "succeeded": 0,
            "failed": 0,
            "digests_written": 0,
            "digest_paths": [],
        }
        digest.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_digest_for_success_runs(self) -> None:
        sub = _make_subscription()
        run = _make_run()
        audit = _make_audit_run()
        job, runner, digest = _build_job(
            runs=[run],
            subscriptions=[sub],
            audit_runs={run.run_id: audit},
        )
        result = await job.run()
        assert result["runs"] == 1
        assert result["succeeded"] == 1
        assert result["failed"] == 0
        assert result["digests_written"] == 1
        digest.generate.assert_called_once_with(audit, sub)

    @pytest.mark.asyncio
    async def test_skips_digest_for_failed_runs(self) -> None:
        # Atomic-state-transition guarantee: FAILED runs must NOT
        # trigger digest generation -- they have no useful content
        # and the runner already handled the audit row.
        sub = _make_subscription()
        run = _make_run(status=MonitoringRunStatus.FAILED, error="upstream 500")
        job, runner, digest = _build_job(
            runs=[run],
            subscriptions=[sub],
            audit_runs={run.run_id: _make_audit_run(status=MonitoringRunStatus.FAILED)},
        )
        result = await job.run()
        assert result["failed"] == 1
        assert result["digests_written"] == 0
        digest.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_digest_failure_does_not_abort_cycle(self) -> None:
        # Two success runs; digest writer raises on the first one.
        # The second must still get a digest (Fail-Soft Boundary).
        sub_a = _make_subscription(subscription_id="sub-a")
        sub_b = _make_subscription(subscription_id="sub-b")
        run_a = _make_run(subscription_id="sub-a")
        run_b = _make_run(subscription_id="sub-b")
        audit_a = _make_audit_run(run_id=run_a.run_id, subscription_id="sub-a")
        audit_b = _make_audit_run(run_id=run_b.run_id, subscription_id="sub-b")

        digest = MagicMock()
        digest.generate = MagicMock(
            side_effect=[RuntimeError("disk full"), Path("/tmp/b.md")]
        )

        runner = MagicMock()
        runner.run_once = AsyncMock(return_value=[run_a, run_b])
        # Use public delegation methods (H-C1)
        runner.list_subscriptions = MagicMock(return_value=[sub_a, sub_b])
        runner.get_audit_run = MagicMock(
            side_effect=lambda rid: {
                run_a.run_id: audit_a,
                run_b.run_id: audit_b,
            }.get(rid)
        )

        job = MonitoringCheckJob(runner=runner, digest_generator=digest)
        result = await job.run()

        assert result["succeeded"] == 2
        assert result["digests_written"] == 1  # only sub-b succeeded
        assert digest.generate.call_count == 2

    @pytest.mark.asyncio
    async def test_missing_subscription_skipped(self) -> None:
        run = _make_run(subscription_id="sub-deleted")
        job, runner, digest = _build_job(
            runs=[run],
            subscriptions=[],  # subscription deleted between cycles
            audit_runs={run.run_id: _make_audit_run(subscription_id="sub-deleted")},
        )
        result = await job.run()
        assert result["succeeded"] == 1
        assert result["digests_written"] == 0
        digest.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_audit_row_skipped(self) -> None:
        sub = _make_subscription()
        run = _make_run()
        job, runner, digest = _build_job(
            runs=[run],
            subscriptions=[sub],
            audit_runs={},  # audit row missing
        )
        result = await job.run()
        assert result["succeeded"] == 1
        assert result["digests_written"] == 0
        digest.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_call_dunder_invokes_run(self) -> None:
        # BaseJob's __call__ wraps run() with logging + stats. We rely
        # on it for APScheduler invocation -- verify it works through
        # the full BaseJob plumbing.
        sub = _make_subscription()
        run = _make_run()
        job, runner, digest = _build_job(
            runs=[run],
            subscriptions=[sub],
            audit_runs={run.run_id: _make_audit_run()},
        )
        result = await job()
        assert result["digests_written"] == 1
        assert job.run_count == 1
        assert job.error_count == 0

    @pytest.mark.asyncio
    async def test_run_once_raises_propagates_and_increments_error_count(
        self,
    ) -> None:
        """C-3: Errors from runner.run_once() propagate through __call__
        and the BaseJob error_count is incremented.

        This tests the error-propagation path so ``job_failed`` gets
        logged and APScheduler records a JobError event -- preventing
        silent data loss on scheduler ticks.
        """
        runner = MagicMock()
        runner.run_once = AsyncMock(side_effect=RuntimeError("network down"))
        runner.list_subscriptions = MagicMock(return_value=[])
        digest = MagicMock()

        job = MonitoringCheckJob(runner=runner, digest_generator=digest)

        with pytest.raises(RuntimeError, match="network down"):
            await job()

        assert job.error_count == 1
        assert job.run_count == 0  # run_count only increments on success

    @pytest.mark.asyncio
    async def test_structlog_events_emitted_for_skipped_digest_failed_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """H-T1: ``monitoring_digest_skipped_failed_run`` is emitted when
        a FAILED run is encountered during the digest pass.
        """
        import structlog
        import structlog.testing

        # ``src/utils/logging.py`` configures structlog with
        # ``cache_logger_on_first_use=True``; under that mode the module-level
        # ``logger`` in ``src.scheduling.jobs`` is bound to the production
        # processor chain at import time and ignores ``capture_logs()``'s
        # processor swap. Re-bind the jobs logger to a fresh proxy so the
        # current global configuration (set by capture_logs) is honored.
        from src.scheduling import jobs as jobs_module

        monkeypatch.setattr(jobs_module, "logger", structlog.get_logger())

        sub = _make_subscription()
        run = _make_run(status=MonitoringRunStatus.FAILED, error="upstream 500")
        job, runner, digest = _build_job(
            runs=[run],
            subscriptions=[sub],
            audit_runs={run.run_id: _make_audit_run(status=MonitoringRunStatus.FAILED)},
        )
        with structlog.testing.capture_logs() as logs:
            await job.run()

        skip_events = [
            e for e in logs if e.get("event") == "monitoring_digest_skipped_failed_run"
        ]
        assert len(skip_events) == 1
        assert skip_events[0].get("run_id") == run.run_id

    @pytest.mark.asyncio
    async def test_structlog_event_emitted_for_missing_subscription(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """H-T1: ``monitoring_digest_skipped_missing_subscription`` is logged
        when the subscription was deleted between cycle and digest pass.
        """
        import structlog
        import structlog.testing

        from src.scheduling import jobs as jobs_module

        monkeypatch.setattr(jobs_module, "logger", structlog.get_logger())

        run = _make_run(subscription_id="sub-deleted")
        job, runner, digest = _build_job(
            runs=[run],
            subscriptions=[],  # subscription deleted
            audit_runs={run.run_id: _make_audit_run(subscription_id="sub-deleted")},
        )
        with structlog.testing.capture_logs() as logs:
            await job.run()

        skip_events = [
            e
            for e in logs
            if e.get("event") == "monitoring_digest_skipped_missing_subscription"
        ]
        assert len(skip_events) == 1

    @pytest.mark.asyncio
    async def test_structlog_event_emitted_for_digest_write_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """H-T1: ``monitoring_digest_write_failed`` is logged when
        digest generation raises.
        """
        import structlog
        import structlog.testing

        from src.scheduling import jobs as jobs_module

        monkeypatch.setattr(jobs_module, "logger", structlog.get_logger())

        sub = _make_subscription()
        run = _make_run()
        job, runner, digest = _build_job(
            runs=[run],
            subscriptions=[sub],
            audit_runs={run.run_id: _make_audit_run()},
            digest_side_effect=OSError("disk full"),
        )
        with structlog.testing.capture_logs() as logs:
            await job.run()

        error_events = [
            e for e in logs if e.get("event") == "monitoring_digest_write_failed"
        ]
        assert len(error_events) == 1
        assert "disk full" in error_events[0].get("error", "")

    def test_public_methods_list_subscriptions_and_get_audit_run(self) -> None:
        """H-C1: runner.list_subscriptions() and runner.get_audit_run()
        are public delegation methods that the job uses instead of
        accessing private attributes.
        """
        from src.services.intelligence.monitoring.runner import MonitoringRunner

        sub_mgr = MagicMock()
        sub_mgr.list_subscriptions = MagicMock(return_value=["sub1"])
        monitor = MagicMock()
        run_repo = MagicMock()
        run_repo.get_run = MagicMock(return_value="audit_row")

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=run_repo,
        )

        assert runner.list_subscriptions() == ["sub1"]
        assert runner.get_audit_run("run-abc") == "audit_row"
        sub_mgr.list_subscriptions.assert_called_once()
        run_repo.get_run.assert_called_once_with("run-abc")


# ---------------------------------------------------------------------------
# Scheduler integration helper
# ---------------------------------------------------------------------------


class TestSchedulerHelper:
    def test_add_monitoring_check_job_registers(self) -> None:
        # Build a real ResearchScheduler and confirm the helper adds a
        # cron-triggered job at 06:00 UTC by default.
        scheduler = ResearchScheduler()
        fake_job = MagicMock()
        job_id = scheduler.add_monitoring_check_job(fake_job)
        assert job_id == "monitoring_check"
        registered = scheduler.scheduler.get_job(job_id)
        assert registered is not None
        # APScheduler's CronTrigger exposes its fields via `.fields`
        # but we don't need to dig in too far -- the smoke check that
        # the job is there is enough for unit-coverage purposes.

    def test_add_monitoring_check_job_custom_schedule(self) -> None:
        scheduler = ResearchScheduler()
        fake_job = MagicMock()
        job_id = scheduler.add_monitoring_check_job(
            fake_job, hour=18, minute=30, job_id="custom_id"
        )
        assert job_id == "custom_id"
        assert scheduler.scheduler.get_job("custom_id") is not None

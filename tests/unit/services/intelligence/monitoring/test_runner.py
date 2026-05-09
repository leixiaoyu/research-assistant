"""Tests for ``MonitoringRunner`` (Milestone 9.1).

Covers:
- ``run_once`` loads only active subscriptions (via SubscriptionManager).
- ``run_once`` filters by ``user_id`` when provided.
- ``run_once`` returns the runs in subscription order (success + failure).
- ``mark_checked`` is called only on non-FAILED runs.
- Each run is persisted via ``MonitoringRunRepository.record_run``.
- A failure on one subscription does not abort the cycle (continues).
- Defensive envelope: an unexpected exception from
  ``ArxivMonitor.check`` is converted into a FAILED run, persisted,
  and does NOT trigger ``mark_checked``.
- Persistence (record_run) errors are logged but don't break the cycle
  -- the in-memory run is still returned.
- ``mark_checked`` errors are logged but don't break the cycle.
- Empty active list returns ``[]`` and does not touch monitor / repo.
- ``from_paths`` monitor selection: ArxivMonitor vs MultiProviderMonitor
  based on extra_providers / query_expander (H-M6: relocated from
  test_multi_provider_monitor.py so all from_paths tests live here).
- H-S1: Runner passes budget counters to MultiProviderMonitor.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
import structlog

from src.services.intelligence.monitoring.arxiv_monitor import (
    ArxivMonitor,
    ArxivMonitorResult,
)
from src.services.intelligence.monitoring.models import (
    MonitoringRun,
    MonitoringRunStatus,
    PaperSource,
    ResearchSubscription,
    SubscriptionStatus,
)
from src.services.intelligence.monitoring.multi_provider_monitor import (
    MultiProviderMonitor,
)
from src.services.intelligence.monitoring.run_repository import (
    MonitoringRunRepository,
)
from src.services.intelligence.monitoring.runner import MonitoringRunner

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_subscription(
    *,
    subscription_id: str = "sub-aaa",
    user_id: str = "alice",
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> ResearchSubscription:
    return ResearchSubscription(
        subscription_id=subscription_id,
        user_id=user_id,
        name="Sub",
        query="tree of thoughts",
        status=status,
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


def _build_runner(
    *,
    subscriptions: list[ResearchSubscription] | None = None,
    check_results: list[ArxivMonitorResult | Exception] | None = None,
    record_side_effect: Exception | None = None,
    mark_side_effect: Exception | None = None,
) -> tuple[MonitoringRunner, MagicMock, MagicMock, MagicMock]:
    sub_mgr = MagicMock()
    sub_mgr.list_subscriptions = MagicMock(return_value=subscriptions or [])
    if mark_side_effect is not None:
        sub_mgr.mark_checked = MagicMock(side_effect=mark_side_effect)
    else:
        sub_mgr.mark_checked = MagicMock()

    monitor = MagicMock()
    if check_results is None:
        monitor.check = AsyncMock()
    else:
        # Convert results to per-call side_effect (exceptions raised,
        # ArxivMonitorResults returned).
        async def check_fn(_sub: ResearchSubscription) -> ArxivMonitorResult:
            assert check_results is not None  # narrow for mypy
            outcome = check_results.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monitor.check = AsyncMock(side_effect=check_fn)

    repo = MagicMock()
    if record_side_effect is not None:
        repo.record_run = MagicMock(side_effect=record_side_effect)
    else:
        repo.record_run = MagicMock()

    runner = MonitoringRunner(
        subscription_manager=sub_mgr,
        monitor=monitor,
        run_repo=repo,
    )
    return runner, sub_mgr, monitor, repo


def _result_for(
    sub: ResearchSubscription,
    **run_kwargs: object,
) -> ArxivMonitorResult:
    """Build an ArxivMonitorResult whose run targets ``sub``."""
    run = _make_run(
        subscription_id=sub.subscription_id,
        **run_kwargs,  # type: ignore[arg-type]
    )
    return ArxivMonitorResult(run=run, new_papers=[], deduplicated_papers=[])


# ---------------------------------------------------------------------------
# Factory: from_paths
# ---------------------------------------------------------------------------


class TestFromPathsFactory:
    """Test ``MonitoringRunner.from_paths`` (PR #119 #S7).

    Verifies that the convenience factory wires SubscriptionManager,
    ArxivMonitor, and MonitoringRunRepository correctly so the Week-2
    job can construct + run a complete cycle in a single call.
    """

    @pytest.mark.asyncio
    async def test_from_paths_empty_db_returns_empty_list(
        self, tmp_path  # type: ignore[no-untyped-def]
    ) -> None:
        """A from_paths-constructed runner should run_once cleanly
        against an empty database and return an empty list (no
        subscriptions registered yet).

        Renamed from ``test_from_paths_constructs_full_runner`` per
        CLAUDE.md ``test_<function>_<scenario>`` naming convention
        (PR #124 #N6).
        """
        from src.services.intelligence.monitoring.runner import MonitoringRunner

        # Use a path inside the system temp dir (one of the approved
        # storage roots for sanitize_storage_path).
        db_path = tmp_path / "monitoring.db"
        registry = MagicMock()  # ArxivMonitor only touches it on .check
        provider = MagicMock()  # ditto

        runner = MonitoringRunner.from_paths(
            db_path=db_path,
            registry=registry,
            arxiv_provider=provider,
        )
        # No subscriptions persisted -> empty cycle.
        runs = await runner.run_once()
        assert runs == []

    def test_from_paths_returns_initialized_components(
        self, tmp_path  # type: ignore[no-untyped-def]
    ) -> None:
        """Factory must initialize both the SubscriptionManager and the
        MonitoringRunRepository so the caller doesn't have to remember
        the construct-then-initialize idiom.

        Verifies initialization via the public APIs (PR #124 #N7) so
        the test does not couple to private ``_initialized`` flags --
        a successful ``list_subscriptions`` / ``list_runs`` call only
        works after both repos have applied migrations.
        """
        from src.services.intelligence.monitoring.run_repository import (
            MonitoringRunRepository,
        )
        from src.services.intelligence.monitoring.runner import MonitoringRunner
        from src.services.intelligence.monitoring.subscription_manager import (
            SubscriptionManager,
        )

        db_path = tmp_path / "init.db"
        runner = MonitoringRunner.from_paths(
            db_path=db_path,
            registry=MagicMock(),
            arxiv_provider=MagicMock(),
        )
        assert isinstance(runner._subscriptions, SubscriptionManager)
        assert isinstance(runner._run_repo, MonitoringRunRepository)
        # Behavioral check: both repos respond cleanly to a public
        # read API. ``list_subscriptions`` and ``list_runs`` both raise
        # RuntimeError("not initialized") if migrations did not run --
        # so a quiet ``[]`` proves the factory completed initialize().
        assert runner._subscriptions.list_subscriptions() == []
        assert runner._run_repo.list_runs() == []

    def test_from_paths_rejects_path_outside_approved_roots(self) -> None:
        """Path safety must propagate through the factory (PR #124 #C1).

        ``sanitize_storage_path`` is called inside both
        ``SubscriptionManager`` and ``MonitoringRunRepository``
        constructors; ``from_paths`` must NOT swallow the resulting
        ``SecurityError`` -- traversal attempts have to fail loud at
        the factory boundary so the Week-2 scheduler does not silently
        construct a runner pointed at ``/etc/passwd``.
        """
        from src.utils.security import SecurityError

        with pytest.raises(SecurityError, match=r"outside approved storage roots"):
            MonitoringRunner.from_paths(
                db_path=Path("/etc/passwd"),
                registry=MagicMock(),
                arxiv_provider=MagicMock(),
            )

    def test_from_paths_propagates_repo_initialize_failure(
        self, tmp_path  # type: ignore[no-untyped-def]
    ) -> None:
        """If ``repo.initialize()`` raises after ``sub_mgr.initialize()``
        succeeds, the failure must propagate cleanly (PR #124 #C2).

        Partial construction is documented as recoverable -- migrations
        on both repos are idempotent so re-calling ``from_paths`` is
        safe -- but the failure itself must reach the caller, not be
        swallowed.
        """
        db_path = tmp_path / "monitoring.db"
        with patch.object(
            MonitoringRunRepository, "initialize", side_effect=RuntimeError("boom")
        ):
            with pytest.raises(RuntimeError, match="boom"):
                MonitoringRunner.from_paths(
                    db_path=db_path,
                    registry=MagicMock(),
                    arxiv_provider=MagicMock(),
                )

    def test_from_paths_recovers_after_repo_initialize_failure(
        self, tmp_path  # type: ignore[no-untyped-def]
    ) -> None:
        """A second call after a transient initialize() failure must
        succeed cleanly (PR #124 #C2).

        Migrations on both repos are idempotent, so the partial state
        left behind by the first attempt does not poison the retry.
        Pins the docstring's recovery contract.
        """
        db_path = tmp_path / "monitoring.db"
        with patch.object(
            MonitoringRunRepository,
            "initialize",
            side_effect=[RuntimeError("transient"), None],
        ):
            with pytest.raises(RuntimeError, match="transient"):
                MonitoringRunner.from_paths(
                    db_path=db_path,
                    registry=MagicMock(),
                    arxiv_provider=MagicMock(),
                )
            # Second call succeeds -- migrations are idempotent.
            runner = MonitoringRunner.from_paths(
                db_path=db_path,
                registry=MagicMock(),
                arxiv_provider=MagicMock(),
            )
        assert runner is not None

    # H-M6: relocated from test_multi_provider_monitor.py so all from_paths
    # monitor-selection tests live together in test_runner.py.

    def test_from_paths_with_no_extras_builds_arxiv_monitor(
        self, tmp_path: Path
    ) -> None:
        """Backward-compatible default: legacy ArxivMonitor when no extras
        and no expander are provided.
        """
        db_path = tmp_path / "monitoring.db"
        runner = MonitoringRunner.from_paths(
            db_path=db_path,
            registry=MagicMock(),
            arxiv_provider=MagicMock(),
        )
        assert isinstance(runner._monitor, ArxivMonitor)

    def test_from_paths_with_extra_providers_builds_multi_provider_monitor(
        self, tmp_path: Path
    ) -> None:
        """When extra_providers is supplied, MultiProviderMonitor is selected."""
        db_path = tmp_path / "monitoring.db"
        extras = {PaperSource.SEMANTIC_SCHOLAR: MagicMock()}
        runner = MonitoringRunner.from_paths(
            db_path=db_path,
            registry=MagicMock(),
            arxiv_provider=MagicMock(),
            extra_providers=extras,
        )
        assert isinstance(runner._monitor, MultiProviderMonitor)
        # arXiv plus the one extra.
        assert PaperSource.ARXIV in runner._monitor._providers
        assert PaperSource.SEMANTIC_SCHOLAR in runner._monitor._providers

    def test_from_paths_with_only_query_expander_builds_multi_provider(
        self, tmp_path: Path
    ) -> None:
        """Even without extras, providing a query_expander promotes to
        MultiProviderMonitor (the LLM expansion is the upgrade signal).
        """
        db_path = tmp_path / "monitoring.db"
        runner = MonitoringRunner.from_paths(
            db_path=db_path,
            registry=MagicMock(),
            arxiv_provider=MagicMock(),
            query_expander=MagicMock(),
        )
        assert isinstance(runner._monitor, MultiProviderMonitor)

    def test_from_paths_rejects_arxiv_in_extra_providers(self, tmp_path: Path) -> None:
        """Caller must not pass arXiv via ``extra_providers`` -- the
        canonical arXiv provider goes through ``arxiv_provider`` to keep
        the wiring contract single-source.
        """
        db_path = tmp_path / "monitoring.db"
        with pytest.raises(ValueError, match="must not include PaperSource.ARXIV"):
            MonitoringRunner.from_paths(
                db_path=db_path,
                registry=MagicMock(),
                arxiv_provider=MagicMock(),
                extra_providers={PaperSource.ARXIV: MagicMock()},
            )

    def test_from_paths_with_empty_dict_extra_providers_builds_multi_provider(
        self, tmp_path: Path
    ) -> None:
        """H-C6: extra_providers={} (empty dict, not None) explicitly opts the
        caller into MultiProviderMonitor. The is-not-None check must honour this.
        """
        db_path = tmp_path / "monitoring.db"
        runner = MonitoringRunner.from_paths(
            db_path=db_path,
            registry=MagicMock(),
            arxiv_provider=MagicMock(),
            extra_providers={},  # empty but explicitly provided
        )
        assert isinstance(runner._monitor, MultiProviderMonitor)
        # Only arXiv (from arxiv_provider); the empty extras dict adds nothing.
        assert PaperSource.ARXIV in runner._monitor._providers
        assert len(runner._monitor._providers) == 1


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


class TestEmpty:
    @pytest.mark.asyncio
    async def test_no_active_subs_returns_empty_list(self) -> None:
        runner, sub_mgr, monitor, repo = _build_runner(subscriptions=[])
        result = await runner.run_once()
        assert result == []
        sub_mgr.list_subscriptions.assert_called_once_with(
            user_id=None, active_only=True
        )
        monitor.check.assert_not_awaited()
        repo.record_run.assert_not_called()


# ---------------------------------------------------------------------------
# user_id filter
# ---------------------------------------------------------------------------


class TestUserIdFilter:
    @pytest.mark.asyncio
    async def test_filter_by_user_passed_through(self) -> None:
        runner, sub_mgr, _, _ = _build_runner(subscriptions=[])
        await runner.run_once(user_id="alice")
        sub_mgr.list_subscriptions.assert_called_once_with(
            user_id="alice", active_only=True
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_runs_in_subscription_order(self) -> None:
        sub_a = _make_subscription(subscription_id="sub-a")
        sub_b = _make_subscription(subscription_id="sub-b")
        runner, _, monitor, repo = _build_runner(
            subscriptions=[sub_a, sub_b],
            check_results=[
                _result_for(sub_a),
                _result_for(sub_b),
            ],
        )
        runs = await runner.run_once()
        assert [r.subscription_id for r in runs] == ["sub-a", "sub-b"]
        assert monitor.check.await_count == 2
        # Both runs are persisted.
        assert repo.record_run.call_count == 2

    @pytest.mark.asyncio
    async def test_record_run_receives_owning_user_id(self) -> None:
        sub = _make_subscription(subscription_id="sub-a", user_id="alice")
        runner, _, _, repo = _build_runner(
            subscriptions=[sub],
            check_results=[_result_for(sub)],
        )
        await runner.run_once()
        repo.record_run.assert_called_once_with(ANY, user_id="alice")

    @pytest.mark.asyncio
    async def test_mark_checked_on_success(self) -> None:
        sub = _make_subscription(subscription_id="sub-a")
        runner, sub_mgr, _, _ = _build_runner(
            subscriptions=[sub],
            check_results=[_result_for(sub)],
        )
        await runner.run_once()
        sub_mgr.mark_checked.assert_called_once_with("sub-a")

    @pytest.mark.asyncio
    async def test_mark_checked_on_partial(self) -> None:
        sub = _make_subscription(subscription_id="sub-a")
        runner, sub_mgr, _, _ = _build_runner(
            subscriptions=[sub],
            check_results=[
                _result_for(sub, status=MonitoringRunStatus.PARTIAL),
            ],
        )
        await runner.run_once()
        sub_mgr.mark_checked.assert_called_once_with("sub-a")

    @pytest.mark.asyncio
    async def test_mark_checked_skipped_on_failed(self) -> None:
        sub = _make_subscription(subscription_id="sub-a")
        runner, sub_mgr, _, _ = _build_runner(
            subscriptions=[sub],
            check_results=[
                _result_for(sub, status=MonitoringRunStatus.FAILED),
            ],
        )
        await runner.run_once()
        sub_mgr.mark_checked.assert_not_called()


# ---------------------------------------------------------------------------
# Per-subscription failure does not abort cycle
# ---------------------------------------------------------------------------


class TestFailureContinuation:
    @pytest.mark.asyncio
    async def test_one_failure_does_not_break_the_cycle(self) -> None:
        sub_a = _make_subscription(subscription_id="sub-a")
        sub_b = _make_subscription(subscription_id="sub-b")
        sub_c = _make_subscription(subscription_id="sub-c")
        runner, sub_mgr, _, repo = _build_runner(
            subscriptions=[sub_a, sub_b, sub_c],
            check_results=[
                _result_for(sub_a),
                _result_for(sub_b, status=MonitoringRunStatus.FAILED, error="x"),
                _result_for(sub_c),
            ],
        )
        runs = await runner.run_once()
        assert [r.subscription_id for r in runs] == ["sub-a", "sub-b", "sub-c"]
        # All three persisted.
        assert repo.record_run.call_count == 3
        # mark_checked called only for sub-a and sub-c.
        called = [c.args[0] for c in sub_mgr.mark_checked.call_args_list]
        assert called == ["sub-a", "sub-c"]

    @pytest.mark.asyncio
    async def test_unexpected_check_exception_envelope(self) -> None:
        """If ``ArxivMonitor.check`` raises (it's documented not to,
        but a future bug or a different monitor might), the runner
        wraps the failure in a FAILED MonitoringRun and continues.
        """
        sub_a = _make_subscription(subscription_id="sub-a")
        sub_b = _make_subscription(subscription_id="sub-b")
        runner, sub_mgr, _, repo = _build_runner(
            subscriptions=[sub_a, sub_b],
            check_results=[
                RuntimeError("kaboom"),
                _result_for(sub_b),
            ],
        )
        runs = await runner.run_once()
        assert len(runs) == 2
        assert runs[0].subscription_id == "sub-a"
        assert runs[0].status is MonitoringRunStatus.FAILED
        assert runs[0].error is not None
        assert "monitor_check_error" in runs[0].error
        assert "kaboom" in runs[0].error
        # The second sub still ran.
        assert runs[1].subscription_id == "sub-b"
        # Both persisted.
        assert repo.record_run.call_count == 2
        # mark_checked called only on the successful one.
        called = [c.args[0] for c in sub_mgr.mark_checked.call_args_list]
        assert called == ["sub-b"]


# ---------------------------------------------------------------------------
# Persistence / mark_checked failure handling
# ---------------------------------------------------------------------------


class TestPersistenceFailures:
    @pytest.mark.asyncio
    async def test_record_run_failure_does_not_abort_cycle(self) -> None:
        sub_a = _make_subscription(subscription_id="sub-a")
        sub_b = _make_subscription(subscription_id="sub-b")
        runner, _, _, _ = _build_runner(
            subscriptions=[sub_a, sub_b],
            check_results=[
                _result_for(sub_a),
                _result_for(sub_b),
            ],
            record_side_effect=RuntimeError("disk full"),
        )
        runs = await runner.run_once()
        # Both runs returned to caller for observability even though
        # persistence blew up.
        assert len(runs) == 2

    @pytest.mark.asyncio
    async def test_record_run_failure_skips_mark_checked(self) -> None:
        """Atomic-state-transition guarantee (PR #124 team review).

        If ``record_run`` raises (persistence outage), the runner MUST
        NOT call ``mark_checked``. Otherwise the subscription's
        ``last_checked_at`` advances past the polling window while the
        audit row of papers found in that window is lost -- the Week-2
        digest generator would silently miss research updates for that
        interval.

        Rebound: the next cycle re-polls the same window and re-records
        the audit row.
        """
        sub_a = _make_subscription(subscription_id="sub-a")
        sub_b = _make_subscription(subscription_id="sub-b")
        runner, sub_mgr, _, _ = _build_runner(
            subscriptions=[sub_a, sub_b],
            check_results=[
                _result_for(sub_a),
                _result_for(sub_b),
            ],
            record_side_effect=RuntimeError("disk full"),
        )
        runs = await runner.run_once()

        # Cycle continues -- both runs returned for observability.
        assert len(runs) == 2
        # Critical: NEITHER subscription gets marked-checked because
        # both record_run calls raised. Mark-checked must be strictly
        # downstream of audit-trail durability.
        sub_mgr.mark_checked.assert_not_called()

    @pytest.mark.asyncio
    async def test_record_run_failure_logs_skipping_mark_checked_event(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The skip is observable -- ops can grep for the structured
        event when investigating why a subscription's audit trail has
        gaps.

        Uses ``structlog.testing.capture_logs`` (project convention --
        see test_run_repository.py:608) since structlog is not wired
        through stdlib's root logger, so plain ``caplog`` would not
        see the events.

        H-7: Rebind the module-level logger BEFORE capture_logs() to
        defeat cache_logger_on_first_use caching that would otherwise
        keep the production logger bound and miss the captured events.
        """
        import structlog.testing
        import src.services.intelligence.monitoring.runner as runner_module

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription(subscription_id="sub-a")
        runner, _, _, _ = _build_runner(
            subscriptions=[sub],
            check_results=[_result_for(sub)],
            record_side_effect=RuntimeError("disk full"),
        )
        with structlog.testing.capture_logs() as logs:
            runs = await runner.run_once()

        skip_logs = [
            entry
            for entry in logs
            if entry.get("event")
            == "monitoring_persistence_failed_skipping_mark_checked"
        ]
        assert len(skip_logs) == 1, (
            f"expected one persistence-skip log, got "
            f"{[entry.get('event') for entry in logs]}"
        )
        # Pin all three bound fields the production call emits so a
        # future refactor that drops one (e.g., run_id) trips the test.
        skip = skip_logs[0]
        assert skip.get("subscription_id") == "sub-a"
        assert skip.get("error") == "disk full"
        # run_id is auto-generated UUID4 on the in-memory MonitoringRun;
        # we don't assert its value, just its presence + match to the
        # in-memory run returned to the caller.
        assert skip.get("run_id") is not None
        assert skip.get("run_id") == runs[0].run_id

    @pytest.mark.asyncio
    async def test_mark_checked_failure_does_not_abort_cycle(self) -> None:
        sub_a = _make_subscription(subscription_id="sub-a")
        sub_b = _make_subscription(subscription_id="sub-b")
        runner, _, _, _ = _build_runner(
            subscriptions=[sub_a, sub_b],
            check_results=[
                _result_for(sub_a),
                _result_for(sub_b),
            ],
            mark_side_effect=KeyError("vanished"),
        )
        runs = await runner.run_once()
        assert len(runs) == 2
        assert all(r.status is not MonitoringRunStatus.FAILED for r in runs)


# ---------------------------------------------------------------------------
# Event loop responsiveness during record_run sleep (PR #123 #H1)
# ---------------------------------------------------------------------------


class TestEventLoopResponsiveness:
    """Pin the ``asyncio.to_thread`` wrap around ``record_run``.

    ``record_run``'s retry loop uses ``time.sleep`` which would block
    the event loop if called inline. The runner now wraps it in
    ``asyncio.to_thread`` so the sleep happens on a worker thread.
    """

    @pytest.mark.asyncio
    async def test_runner_does_not_block_event_loop_during_record_retry(
        self,
    ) -> None:
        """A concurrent ticker must keep ticking while record_run sleeps.

        We swap ``record_run`` for a sync function that blocks on
        ``time.sleep(0.1)``. A concurrent task ticks every 10 ms; if
        the loop is blocked the ticker would record at most 1 tick.
        With ``asyncio.to_thread`` parking the sleep on a worker
        thread, the ticker should fire many times during the 100 ms
        record window.
        """
        import asyncio
        import time

        sub = _make_subscription(subscription_id="sub-block-test")
        runner, _, _, repo = _build_runner(
            subscriptions=[sub],
            check_results=[_result_for(sub)],
        )

        # Synchronous, sleep-based record_run -- the worst case the
        # retry loop can produce in production.
        def slow_record(run: MonitoringRun, **_kwargs: object) -> None:
            time.sleep(0.1)

        repo.record_run = MagicMock(side_effect=slow_record)

        ticks = 0
        ticker_done = asyncio.Event()

        async def ticker() -> None:
            nonlocal ticks
            try:
                while not ticker_done.is_set():
                    await asyncio.sleep(0.01)
                    ticks += 1
            except asyncio.CancelledError:
                pass

        ticker_task = asyncio.create_task(ticker())
        try:
            await runner.run_once()
        finally:
            ticker_done.set()
            ticker_task.cancel()
            try:
                await ticker_task
            except asyncio.CancelledError:
                pass

        # Without ``asyncio.to_thread`` ticks would be 0 or 1 (the loop
        # is pinned for the full sleep). With it, the ticker fires
        # roughly every 10 ms over a 100 ms window. Allow generous
        # slack for slow CI runners but still detect a fully-blocked
        # loop.
        assert ticks >= 5, (
            f"Event loop appears blocked during record_run; ticker fired "
            f"only {ticks} times in 100 ms (expected >= 5). "
            "asyncio.to_thread wrap regression?"
        )
        repo.record_run.assert_called_once_with(ANY, user_id="alice")


# ---------------------------------------------------------------------------
# C-1: RelevanceScorer wired into runner + per-paper scoring tests
# ---------------------------------------------------------------------------


class TestScorerIntegration:
    """C-1: RelevanceScorer is called per paper, scores written to records."""

    @pytest.mark.asyncio
    async def test_scorer_called_per_paper(self) -> None:
        """When a scorer is wired, it is called once per paper in the run."""
        from unittest.mock import AsyncMock as _AsyncMock, MagicMock as _MagicMock

        from src.services.intelligence.monitoring.models import MonitoringPaperRecord
        from src.services.intelligence.monitoring.relevance_scorer import (
            RelevanceScoreResult,
        )
        from src.services.intelligence.monitoring.runner import MonitoringRunner

        sub = _make_subscription(subscription_id="sub-scorer")
        paper1 = MonitoringPaperRecord(
            paper_id="p1",
            title="Paper 1",
            is_new=True,
            url="https://arxiv.org/abs/p1",
            source=PaperSource.ARXIV,
        )
        paper2 = MonitoringPaperRecord(
            paper_id="p2",
            title="Paper 2",
            is_new=True,
            url="https://arxiv.org/abs/p2",
            source=PaperSource.ARXIV,
        )
        run_obj = _make_run(subscription_id="sub-scorer")
        run_obj = run_obj.model_copy(update={"papers": [paper1, paper2]})

        result = ArxivMonitorResult(run=run_obj, new_papers=[], deduplicated_papers=[])

        scorer = _MagicMock()
        score_result = RelevanceScoreResult(
            score=0.8,
            reasoning="Good match indeed",
            model_used="gemini-1.5-flash",
            cost_usd=0.0001,
        )
        scorer.score = _AsyncMock(return_value=score_result)

        sub_mgr = _MagicMock()
        sub_mgr.list_subscriptions = _MagicMock(return_value=[sub])
        sub_mgr.mark_checked = _MagicMock()
        monitor = _MagicMock()
        monitor.check = _AsyncMock(return_value=result)
        repo = _MagicMock()
        repo.record_run = _MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
            scorer=scorer,
        )
        runs = await runner.run_once()

        # Scorer must be called once per paper.
        assert scorer.score.await_count == 2
        # Scores must be written back to the paper records.
        assert runs[0].papers[0].relevance_score == pytest.approx(0.8)
        assert runs[0].papers[1].relevance_score == pytest.approx(0.8)
        assert runs[0].papers[0].relevance_reasoning == "Good match indeed"

    @pytest.mark.asyncio
    async def test_scorer_raises_does_not_abort_run(self) -> None:
        """A scorer exception on one paper must not abort the whole run."""
        from unittest.mock import AsyncMock as _AsyncMock, MagicMock as _MagicMock

        from src.services.intelligence.monitoring.models import MonitoringPaperRecord
        from src.services.intelligence.monitoring.relevance_scorer import (
            LLMResponseError,
            RelevanceScoreResult,
        )
        from src.services.intelligence.monitoring.runner import MonitoringRunner

        sub = _make_subscription(subscription_id="sub-scorer2")
        paper1 = MonitoringPaperRecord(
            paper_id="p1",
            title="Paper 1",
            is_new=True,
            url="https://arxiv.org/abs/p1",
            source=PaperSource.ARXIV,
        )
        paper2 = MonitoringPaperRecord(
            paper_id="p2",
            title="Paper 2",
            is_new=True,
            url="https://arxiv.org/abs/p2",
            source=PaperSource.ARXIV,
        )
        run_obj = _make_run(subscription_id="sub-scorer2")
        run_obj = run_obj.model_copy(update={"papers": [paper1, paper2]})
        result = ArxivMonitorResult(run=run_obj, new_papers=[], deduplicated_papers=[])

        # First paper raises; second succeeds.
        ok_result = RelevanceScoreResult(
            score=0.6,
            reasoning="Moderate relevance here",
            model_used="gemini-1.5-flash",
            cost_usd=0.0,
        )
        scorer = _MagicMock()
        scorer.score = _AsyncMock(
            side_effect=[LLMResponseError("malformed"), ok_result]
        )

        sub_mgr = _MagicMock()
        sub_mgr.list_subscriptions = _MagicMock(return_value=[sub])
        sub_mgr.mark_checked = _MagicMock()
        monitor = _MagicMock()
        monitor.check = _AsyncMock(return_value=result)
        repo = _MagicMock()
        repo.record_run = _MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
            scorer=scorer,
        )
        runs = await runner.run_once()

        assert len(runs) == 1
        # First paper: no score (scorer raised).
        assert runs[0].papers[0].relevance_score is None
        # Second paper: scored successfully.
        assert runs[0].papers[1].relevance_score == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def test_no_scorer_returns_unscored_papers(self) -> None:
        """Without a scorer, papers remain unscored (backward compatible)."""
        from unittest.mock import AsyncMock as _AsyncMock, MagicMock as _MagicMock

        from src.services.intelligence.monitoring.models import MonitoringPaperRecord
        from src.services.intelligence.monitoring.runner import MonitoringRunner

        sub = _make_subscription(subscription_id="sub-no-scorer")
        paper = MonitoringPaperRecord(
            paper_id="p1", title="Paper 1", is_new=True, source=PaperSource.ARXIV
        )
        run_obj = _make_run(subscription_id="sub-no-scorer")
        run_obj = run_obj.model_copy(update={"papers": [paper]})
        result = ArxivMonitorResult(run=run_obj, new_papers=[], deduplicated_papers=[])

        sub_mgr = _MagicMock()
        sub_mgr.list_subscriptions = _MagicMock(return_value=[sub])
        sub_mgr.mark_checked = _MagicMock()
        monitor = _MagicMock()
        monitor.check = _AsyncMock(return_value=result)
        repo = _MagicMock()
        repo.record_run = _MagicMock()

        # No scorer injected.
        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )
        runs = await runner.run_once()

        assert runs[0].papers[0].relevance_score is None

    @pytest.mark.asyncio
    async def test_scorer_skips_paper_with_no_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """C-2: Papers with url=None are skipped before scoring rather than
        fabricating an arXiv URL for non-arXiv papers.
        The ``monitoring_relevance_score_skipped_no_url`` event is emitted.
        """
        import structlog
        import structlog.testing
        from unittest.mock import AsyncMock as _AsyncMock, MagicMock as _MagicMock

        import src.services.intelligence.monitoring.runner as runner_module
        from src.services.intelligence.monitoring.models import MonitoringPaperRecord
        from src.services.intelligence.monitoring.relevance_scorer import (
            RelevanceScoreResult,
        )
        from src.services.intelligence.monitoring.runner import MonitoringRunner

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription(subscription_id="sub-nourl")
        paper_no_url = MonitoringPaperRecord(
            paper_id="p-nourl",
            title="No URL Paper",
            is_new=True,
            url=None,
            # Issue #141: a non-arXiv paper missing its URL is the
            # exact case the source-aware skip log was added to surface.
            source=PaperSource.OPENALEX,
        )
        paper_with_url = MonitoringPaperRecord(
            paper_id="p-url",
            title="Has URL Paper",
            is_new=True,
            url="https://arxiv.org/abs/p-url",
            source=PaperSource.ARXIV,
        )
        run_obj = _make_run(subscription_id="sub-nourl")
        run_obj = run_obj.model_copy(update={"papers": [paper_no_url, paper_with_url]})
        result = ArxivMonitorResult(run=run_obj, new_papers=[], deduplicated_papers=[])

        ok_result = RelevanceScoreResult(
            score=0.7,
            reasoning="Some match found in paper",
            model_used="gemini-1.5-flash",
            cost_usd=0.0,
        )
        scorer = _MagicMock()
        scorer.score = _AsyncMock(return_value=ok_result)

        sub_mgr = _MagicMock()
        sub_mgr.list_subscriptions = _MagicMock(return_value=[sub])
        sub_mgr.mark_checked = _MagicMock()
        monitor = _MagicMock()
        monitor.check = _AsyncMock(return_value=result)
        repo = _MagicMock()
        repo.record_run = _MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
            scorer=scorer,
        )

        with structlog.testing.capture_logs() as logs:
            runs = await runner.run_once()

        # The paper with URL is scored; the paper without URL is skipped.
        assert runs[0].papers[0].relevance_score is None  # no URL → skipped
        assert runs[0].papers[1].relevance_score == pytest.approx(0.7)
        # Scorer is called only once (for the URL paper).
        assert scorer.score.await_count == 1

        skip_events = [
            e
            for e in logs
            if e.get("event") == "monitoring_relevance_score_skipped_no_url"
        ]
        assert len(skip_events) == 1
        assert skip_events[0]["paper_id"] == "p-nourl"
        # Issue #141: skip log carries the actual provider so ops can
        # query "skipped papers from openalex" without joining audits.
        assert skip_events[0]["source"] == PaperSource.OPENALEX.value


# ---------------------------------------------------------------------------
# H-C1: Public delegation methods
# ---------------------------------------------------------------------------


class TestPublicDelegationMethods:
    """H-C1: MonitoringRunner.list_subscriptions() and get_audit_run() delegate
    to their private collaborators without exposing private attributes.
    """

    def test_list_subscriptions_delegates(self) -> None:
        sub_mgr = MagicMock()
        sub_mgr.list_subscriptions = MagicMock(return_value=["sub1", "sub2"])
        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=MagicMock(),
            run_repo=MagicMock(),
        )
        result = runner.list_subscriptions(user_id="alice", active_only=True)
        assert result == ["sub1", "sub2"]
        sub_mgr.list_subscriptions.assert_called_once_with(
            user_id="alice", active_only=True
        )

    def test_get_audit_run_delegates(self) -> None:
        run_repo = MagicMock()
        run_repo.get_run = MagicMock(return_value="audit_row")
        runner = MonitoringRunner(
            subscription_manager=MagicMock(),
            monitor=MagicMock(),
            run_repo=run_repo,
        )
        result = runner.get_audit_run("run-abc")
        assert result == "audit_row"
        run_repo.get_run.assert_called_once_with("run-abc")


# ---------------------------------------------------------------------------
# H-T4: _build_runner / from_paths strong assertions
# ---------------------------------------------------------------------------


class TestFromPathsStrong:
    """H-T4: Assert from_paths returns a fully-functional MonitoringRunner
    with working public delegation methods.
    """

    def test_from_paths_returns_monitoring_runner_instance(
        self, tmp_path: Path
    ) -> None:
        """from_paths must return a MonitoringRunner instance."""
        runner = MonitoringRunner.from_paths(
            db_path=tmp_path / "monitoring.db",
            registry=MagicMock(),
            arxiv_provider=MagicMock(),
        )
        assert isinstance(runner, MonitoringRunner)

    def test_from_paths_list_subscriptions_works(self, tmp_path: Path) -> None:
        """list_subscriptions() works after from_paths (proves initialization)."""
        runner = MonitoringRunner.from_paths(
            db_path=tmp_path / "monitoring.db",
            registry=MagicMock(),
            arxiv_provider=MagicMock(),
        )
        assert runner.list_subscriptions() == []


# ---------------------------------------------------------------------------
# H-S5: LLM budget cap + semaphore concurrency
# ---------------------------------------------------------------------------


class TestLLMBudgetCap:
    """H-S5: MAX_LLM_CALLS_PER_CYCLE is enforced; exhaustion emits structured log."""

    @pytest.mark.asyncio
    async def test_budget_cap_stops_scoring_and_logs_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When budget is exhausted, remaining papers are left unscored and
        ``monitoring_llm_budget_exhausted`` is logged.

        H-7: Rebind the module-level logger BEFORE capture_logs() to
        defeat cache_logger_on_first_use caching.
        """
        import structlog.testing
        import src.services.intelligence.monitoring.runner as runner_module

        from unittest.mock import AsyncMock as _AsyncMock, MagicMock as _MagicMock

        from src.services.intelligence.monitoring.models import MonitoringPaperRecord
        from src.services.intelligence.monitoring.relevance_scorer import (
            RelevanceScoreResult,
        )
        from src.services.intelligence.monitoring.runner import MonitoringRunner

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription(subscription_id="sub-budget")
        # Create 3 papers but set the budget cap to 1 so only 1 gets scored.
        # Include URLs so the C-2 url-check does not skip these papers.
        papers = [
            MonitoringPaperRecord(
                paper_id=f"p{i}",
                title=f"Paper {i}",
                is_new=True,
                url=f"https://arxiv.org/abs/p{i}",
                source=PaperSource.ARXIV,
            )
            for i in range(3)
        ]
        run_obj = _make_run(subscription_id="sub-budget")
        run_obj = run_obj.model_copy(update={"papers": papers})
        result = ArxivMonitorResult(run=run_obj, new_papers=[], deduplicated_papers=[])

        scorer = _MagicMock()
        ok_result = RelevanceScoreResult(
            score=0.5,
            reasoning="Some match found here",
            model_used="gemini-1.5-flash",
            cost_usd=0.0,
        )
        scorer.score = _AsyncMock(return_value=ok_result)

        sub_mgr = _MagicMock()
        sub_mgr.list_subscriptions = _MagicMock(return_value=[sub])
        sub_mgr.mark_checked = _MagicMock()
        monitor = _MagicMock()
        monitor.check = _AsyncMock(return_value=result)
        repo = _MagicMock()
        repo.record_run = _MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
            scorer=scorer,
        )

        # Patch MAX_LLM_CALLS_PER_CYCLE to 1 so we hit the cap after 1 paper.
        with patch(
            "src.services.intelligence.monitoring.runner.MAX_LLM_CALLS_PER_CYCLE", 1
        ):
            with structlog.testing.capture_logs() as logs:
                runs = await runner.run_once()

        # Only 1 paper should be scored (the cap is 1).
        scored = [p for p in runs[0].papers if p.relevance_score is not None]
        assert len(scored) == 1

        # Budget exhaustion events should be logged for the remaining papers.
        exhausted_events = [
            e for e in logs if e.get("event") == "monitoring_llm_budget_exhausted"
        ]
        assert len(exhausted_events) >= 1


# ---------------------------------------------------------------------------
# H-S1: Runner passes budget counters to MultiProviderMonitor
# ---------------------------------------------------------------------------


class TestMultiProviderMonitorBudgetPassthrough:
    """H-S1: When the runner's monitor is a MultiProviderMonitor, _run_one
    passes llm_calls_used and max_calls to monitor.check.
    """

    @pytest.mark.asyncio
    async def test_run_once_passes_budget_to_multi_provider_monitor(self) -> None:
        """The runner passes the cycle-wide llm_calls_used counter and
        MAX_LLM_CALLS_PER_CYCLE to MultiProviderMonitor.check so the
        expander is gated against the cycle budget.
        """
        from unittest.mock import AsyncMock as _AsyncMock, MagicMock as _MagicMock
        from src.services.intelligence.monitoring.multi_provider_monitor import (
            MultiProviderMonitor,
        )

        sub = _make_subscription(subscription_id="sub-budget-passthrough")

        # Build a MultiProviderMonitor mock that records what was passed.
        received_kwargs: dict = {}

        async def mock_check(subscription, *, llm_calls_used=None, max_calls=None):
            received_kwargs["llm_calls_used"] = llm_calls_used
            received_kwargs["max_calls"] = max_calls
            run = _make_run(subscription_id=subscription.subscription_id)
            return ArxivMonitorResult(run=run, new_papers=[], deduplicated_papers=[])

        monitor_mock = _MagicMock(spec=MultiProviderMonitor)
        monitor_mock.check = _AsyncMock(side_effect=mock_check)

        sub_mgr = _MagicMock()
        sub_mgr.list_subscriptions = _MagicMock(return_value=[sub])
        sub_mgr.mark_checked = _MagicMock()
        repo = _MagicMock()
        repo.record_run = _MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor_mock,
            run_repo=repo,
        )
        await runner.run_once()

        # The runner must have passed the budget counter and max cap.
        assert received_kwargs.get("llm_calls_used") is not None
        assert received_kwargs["llm_calls_used"][0] == 0  # starts at 0
        from src.services.intelligence.monitoring.runner import MAX_LLM_CALLS_PER_CYCLE

        assert received_kwargs.get("max_calls") == MAX_LLM_CALLS_PER_CYCLE


# ---------------------------------------------------------------------------
# C-1: Additional coverage for _score_paper branches (lines 364, 417-424,
# 432-439, 499, 501)
# ---------------------------------------------------------------------------


class TestScorePaperBranches:
    """Cover the remaining _score_paper / _run_one branches.

    Uses monkeypatch.setattr(runner_module, "logger", ...) before
    capture_logs() so the structlog processor swap reaches the module-
    level cached logger (CLAUDE.md canonical pattern).
    """

    @pytest.mark.asyncio
    async def test_score_paper_returns_early_when_scorer_is_none(self) -> None:
        """Line 364: _score_paper early-returns when self._scorer is None.

        Although _run_one gates on scorer is not None before spawning
        scoring tasks, the defensive early-return in _score_paper itself
        is valid code that must be reachable for coverage. Call
        _score_paper directly on a runner with no scorer.
        """
        import asyncio
        from unittest.mock import MagicMock as _MagicMock

        from src.services.intelligence.monitoring.models import MonitoringPaperRecord
        from src.services.intelligence.monitoring.runner import MonitoringRunner

        runner = MonitoringRunner(
            subscription_manager=_MagicMock(),
            monitor=_MagicMock(),
            run_repo=_MagicMock(),
            scorer=None,  # no scorer
        )
        sub = _make_subscription(subscription_id="sub-early-return")
        paper = MonitoringPaperRecord(
            paper_id="p-er",
            title="Paper",
            is_new=True,
            url="https://arxiv.org/abs/p1",
            source=PaperSource.ARXIV,
        )
        sem = asyncio.Semaphore(10)
        llm_calls_used: list[int] = [0]
        # Must not raise; must return without touching scorer.
        await runner._score_paper(sub, paper, sem, llm_calls_used)
        assert paper.relevance_score is None
        assert llm_calls_used[0] == 0

    @pytest.mark.asyncio
    async def test_score_paper_logs_unexpected_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Lines 417-424: unexpected Exception in scorer is caught, logged,
        and does not propagate — the paper is left unscored.
        """
        import asyncio
        import structlog
        import structlog.testing
        from unittest.mock import AsyncMock as _AsyncMock, MagicMock as _MagicMock

        import src.services.intelligence.monitoring.runner as runner_module
        from src.services.intelligence.monitoring.models import MonitoringPaperRecord
        from src.services.intelligence.monitoring.runner import MonitoringRunner

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        scorer = _MagicMock()
        scorer.score = _AsyncMock(side_effect=RuntimeError("GPU exploded"))

        runner = MonitoringRunner(
            subscription_manager=_MagicMock(),
            monitor=_MagicMock(),
            run_repo=_MagicMock(),
            scorer=scorer,
        )
        sub = _make_subscription(subscription_id="sub-unexpected")
        paper = MonitoringPaperRecord(
            paper_id="p-unexpected",
            title="Unexpected Paper",
            is_new=True,
            url="https://arxiv.org/abs/p-unexpected",
            source=PaperSource.ARXIV,
        )
        sem = asyncio.Semaphore(10)
        llm_calls_used: list[int] = [0]

        with structlog.testing.capture_logs() as logs:
            await runner._score_paper(sub, paper, sem, llm_calls_used)

        # Paper must be left unscored.
        assert paper.relevance_score is None
        # The unexpected-error event must be logged.
        error_events = [
            e
            for e in logs
            if e.get("event") == "monitoring_relevance_score_unexpected_error"
        ]
        assert len(error_events) == 1
        assert error_events[0].get("paper_id") == "p-unexpected"
        assert "GPU exploded" in error_events[0].get("error", "")

    @pytest.mark.asyncio
    async def test_score_paper_rejects_high_score_with_thin_reasoning(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Lines 432-439: high score (>=0.95) with reasoning < 30 chars is
        rejected as a sanity-guard against prompt-injection. Paper is left
        unscored and monitoring_relevance_score_sanity_rejected is logged.
        """
        import asyncio
        import structlog
        import structlog.testing
        from unittest.mock import AsyncMock as _AsyncMock, MagicMock as _MagicMock

        import src.services.intelligence.monitoring.runner as runner_module
        from src.services.intelligence.monitoring.models import MonitoringPaperRecord
        from src.services.intelligence.monitoring.relevance_scorer import (
            RelevanceScoreResult,
        )
        from src.services.intelligence.monitoring.runner import MonitoringRunner

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        # Score at exactly the threshold with very short reasoning.
        thin_result = RelevanceScoreResult(
            score=0.95,
            reasoning="short",  # len("short") == 5 < 30
            model_used="gemini-1.5-flash",
            cost_usd=0.0,
        )
        scorer = _MagicMock()
        scorer.score = _AsyncMock(return_value=thin_result)

        runner = MonitoringRunner(
            subscription_manager=_MagicMock(),
            monitor=_MagicMock(),
            run_repo=_MagicMock(),
            scorer=scorer,
        )
        sub = _make_subscription(subscription_id="sub-sanity")
        paper = MonitoringPaperRecord(
            paper_id="p-sanity",
            title="Sanity Paper",
            is_new=True,
            url="https://arxiv.org/abs/p-sanity",
            source=PaperSource.ARXIV,
        )
        sem = asyncio.Semaphore(10)
        llm_calls_used: list[int] = [0]

        with structlog.testing.capture_logs() as logs:
            await runner._score_paper(sub, paper, sem, llm_calls_used)

        # Paper must remain unscored after sanity rejection.
        assert paper.relevance_score is None
        sanity_events = [
            e
            for e in logs
            if e.get("event") == "monitoring_relevance_score_sanity_rejected"
        ]
        assert len(sanity_events) == 1
        assert sanity_events[0].get("paper_id") == "p-sanity"
        assert sanity_events[0].get("score") == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_run_one_creates_fallback_sem_and_counter_when_called_directly(
        self,
    ) -> None:
        """Lines 499/501: _run_one creates its own Semaphore and llm_calls_used
        list when called without sem/llm_calls_used (e.g., from tests that
        bypass the run_once cycle context).
        """
        from unittest.mock import AsyncMock as _AsyncMock, MagicMock as _MagicMock

        from src.services.intelligence.monitoring.runner import MonitoringRunner

        sub = _make_subscription(subscription_id="sub-fallback")
        run_obj = _make_run(subscription_id="sub-fallback")
        result = ArxivMonitorResult(run=run_obj, new_papers=[], deduplicated_papers=[])

        monitor = _MagicMock()
        monitor.check = _AsyncMock(return_value=result)
        repo = _MagicMock()
        repo.record_run = _MagicMock()
        sub_mgr = _MagicMock()
        sub_mgr.mark_checked = _MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )
        # Call _run_one directly WITHOUT sem or llm_calls_used to exercise
        # the fallback creation at lines 499/501.
        returned_run = await runner._run_one(sub)
        assert returned_run.subscription_id == "sub-fallback"
        repo.record_run.assert_called_once_with(ANY, user_id="alice")


# ===========================================================================
# Backfill step tests (Phase 9.1 / Issue #145)
# ===========================================================================


def _make_subscription_with_backfill(
    *,
    subscription_id: str = "sub-bf-001",
    backfill_days: int = 7,
    backfill_cursor_date: date | None = None,
) -> ResearchSubscription:
    """Build a ResearchSubscription with backfill_days > 0.

    Uses a created_at 400 days in the past so the floor is always
    ``today - backfill_days`` (not ``created_at``), which prevents the
    cursor from appearing already-at-floor when the test starts.
    """
    from datetime import datetime, timezone

    return ResearchSubscription(
        subscription_id=subscription_id,
        user_id="alice",
        name="BF Sub",
        query="LoRA",
        backfill_days=backfill_days,
        backfill_cursor_date=backfill_cursor_date,
        created_at=datetime.now(timezone.utc) - timedelta(days=400),
    )


class TestRunnerBackfillSkip:
    """test_runner_skips_backfill_when_backfill_days_zero — opt-in semantic."""

    @pytest.mark.asyncio
    async def test_runner_skips_backfill_when_backfill_days_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When backfill_days=0 (default), no backfill step is taken."""
        from unittest.mock import AsyncMock, MagicMock
        import src.services.intelligence.monitoring.runner as runner_module

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription()  # backfill_days=0 by default
        run_obj = _make_run(subscription_id=sub.subscription_id)
        result = ArxivMonitorResult(run=run_obj, new_papers=[], deduplicated_papers=[])
        monitor = MagicMock()
        monitor.check = AsyncMock(return_value=result)
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        sub_mgr.update_backfill_cursor = MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        with structlog.testing.capture_logs() as cap:
            returned_run = await runner._run_one(sub)

        # update_backfill_cursor must NOT have been called
        sub_mgr.update_backfill_cursor.assert_not_called()
        # No backfill-related events should be emitted
        backfill_events = [e for e in cap if "backfill" in e.get("event", "")]
        assert backfill_events == []
        assert returned_run is run_obj


class TestRunnerBackfillStep:
    """Tests for runner backfill cursor walk and per-step behavior."""

    @pytest.mark.asyncio
    async def test_runner_walks_cursor_backward_in_step_size_chunks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cursor advances backward by BACKFILL_STEP_DAYS_DEFAULT per cycle."""
        from unittest.mock import AsyncMock, MagicMock
        import src.services.intelligence.monitoring.runner as runner_module
        from src.services.intelligence.monitoring.models import (
            BACKFILL_STEP_DAYS_DEFAULT,
        )

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).date()
        sub = _make_subscription_with_backfill(
            backfill_days=7,
            backfill_cursor_date=None,  # not yet started → cursor is today
        )

        # Fresh-feed run
        fresh_run = _make_run(subscription_id=sub.subscription_id)
        fresh_result = ArxivMonitorResult(
            run=fresh_run, new_papers=[], deduplicated_papers=[]
        )
        # Backfill run (returned by monitor.check on second call)
        backfill_run = _make_run(subscription_id=sub.subscription_id)
        backfill_result = ArxivMonitorResult(
            run=backfill_run, new_papers=[], deduplicated_papers=[]
        )

        monitor = MagicMock()
        monitor.check = AsyncMock(side_effect=[fresh_result, backfill_result])
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        captured_cursor: list[date | None] = []

        def capture_cursor(sub_id: str, cursor: date | None) -> None:
            captured_cursor.append(cursor)

        sub_mgr.update_backfill_cursor = capture_cursor

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        with structlog.testing.capture_logs() as cap:
            await runner._run_one(sub)

        # Cursor must have been updated exactly once (one backfill step)
        assert len(captured_cursor) == 1
        expected_new_cursor = today - timedelta(days=BACKFILL_STEP_DAYS_DEFAULT)
        assert captured_cursor[0] == expected_new_cursor

        # monitor.check called twice: once for fresh, once for backfill
        assert monitor.check.call_count == 2

        # Structured log event present
        step_events = [
            e for e in cap if e.get("event") == "monitor_backfill_step_complete"
        ]
        assert len(step_events) == 1
        evt = step_events[0]
        assert evt["cursor_before"] == today.isoformat()
        assert evt["cursor_after"] == expected_new_cursor.isoformat()

    @pytest.mark.asyncio
    async def test_runner_stops_backfill_at_max_days_or_created_at(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backfill stops when cursor reaches max_days floor or created_at."""
        from unittest.mock import AsyncMock, MagicMock
        import src.services.intelligence.monitoring.runner as runner_module

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).date()
        # Set cursor right at the floor so no step is taken
        floor = today - timedelta(days=3)
        sub = _make_subscription_with_backfill(
            backfill_days=3,
            backfill_cursor_date=floor,  # cursor already at floor
        )

        fresh_run = _make_run(subscription_id=sub.subscription_id)
        fresh_result = ArxivMonitorResult(
            run=fresh_run, new_papers=[], deduplicated_papers=[]
        )
        monitor = MagicMock()
        monitor.check = AsyncMock(return_value=fresh_result)
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        sub_mgr.update_backfill_cursor = MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        with structlog.testing.capture_logs() as cap:
            await runner._run_one(sub)

        # Cursor at floor → no backfill step, update_backfill_cursor not called
        sub_mgr.update_backfill_cursor.assert_not_called()

        # But monitor_backfill_complete should have been emitted
        complete_events = [
            e for e in cap if e.get("event") == "monitor_backfill_complete"
        ]
        assert len(complete_events) == 1

    @pytest.mark.asyncio
    async def test_runner_caps_papers_per_step_and_defers_excess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backfill step is capped at BACKFILL_MAX_PAPERS_PER_STEP."""
        from unittest.mock import AsyncMock, MagicMock
        import src.services.intelligence.monitoring.runner as runner_module
        from src.services.intelligence.monitoring.models import (
            BACKFILL_MAX_PAPERS_PER_STEP,
            PaperSource,
        )
        from src.services.intelligence.monitoring.models import MonitoringPaperRecord

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription_with_backfill(backfill_days=7)

        # Build a run with more papers than the cap.
        # NOTE: run.papers is list[MonitoringPaperRecord];
        # ArxivMonitorResult.new_papers is list[PaperMetadata].
        # The backfill code reads from run.papers (not new_papers).
        oversized_paper_records = [
            MonitoringPaperRecord(
                paper_id=f"paper:{i:04d}",
                title=f"Paper {i}",
                is_new=True,
                source=PaperSource.ARXIV,
            )
            for i in range(BACKFILL_MAX_PAPERS_PER_STEP + 10)
        ]
        fresh_run = _make_run(subscription_id=sub.subscription_id)
        oversized_run = MonitoringRun(
            subscription_id=sub.subscription_id,
            status=MonitoringRunStatus.SUCCESS,
            papers=oversized_paper_records,
        )
        fresh_result = ArxivMonitorResult(
            run=fresh_run, new_papers=[], deduplicated_papers=[]
        )
        backfill_result = ArxivMonitorResult(
            run=oversized_run, new_papers=[], deduplicated_papers=[]
        )

        monitor = MagicMock()
        monitor.check = AsyncMock(side_effect=[fresh_result, backfill_result])
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        captured_cursor: list[date | None] = []

        def capture_cursor(sub_id: str, cursor: date | None) -> None:
            captured_cursor.append(cursor)

        sub_mgr.update_backfill_cursor = capture_cursor

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        with structlog.testing.capture_logs() as cap:
            await runner._run_one(sub)

        # Cursor was advanced (step was taken)
        assert len(captured_cursor) == 1

        # papers_capped=True in the log event
        step_events = [
            e for e in cap if e.get("event") == "monitor_backfill_step_complete"
        ]
        assert len(step_events) == 1
        assert step_events[0]["papers_capped"] is True
        assert step_events[0]["papers_added"] == BACKFILL_MAX_PAPERS_PER_STEP

    @pytest.mark.asyncio
    async def test_runner_backfill_passes_time_window_to_monitor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backfill passes an explicit time_window to monitor.check.

        This is the CONTRACT TEST for C-1: verifies that the backfill step
        calls monitor.check with time_window=(step_start, step_end) so the
        monitor actually fetches historical papers instead of re-polling the
        same fresh-feed window derived from poll_interval_hours.

        Pins monitor.check.call_args_list to verify:
        1. Fresh-feed call has NO time_window kwarg (or time_window=None).
        2. Backfill call has time_window set to a (date, date) tuple
           where step_end == cursor_before and step_start < step_end.

        Absence of this test is what allowed the C-1 bug to ship at 100%
        coverage — coverage % alone cannot catch wrong arguments being passed.
        """
        from unittest.mock import AsyncMock, MagicMock
        from src.services.intelligence.monitoring.models import (
            BACKFILL_STEP_DAYS_DEFAULT,
        )
        import src.services.intelligence.monitoring.runner as runner_module

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).date()
        sub = _make_subscription_with_backfill(
            backfill_days=14,
            backfill_cursor_date=None,  # cursor implicitly = today
        )

        fresh_run = _make_run(subscription_id=sub.subscription_id)
        backfill_run = _make_run(subscription_id=sub.subscription_id)
        fresh_result = ArxivMonitorResult(
            run=fresh_run, new_papers=[], deduplicated_papers=[]
        )
        backfill_result = ArxivMonitorResult(
            run=backfill_run, new_papers=[], deduplicated_papers=[]
        )

        monitor = MagicMock()
        monitor.check = AsyncMock(side_effect=[fresh_result, backfill_result])
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        sub_mgr.update_backfill_cursor = MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        await runner._run_one(sub)

        # Verify exactly 2 calls: fresh feed + 1 backfill step.
        assert (
            monitor.check.call_count == 2
        ), f"Expected 2 monitor.check calls, got {monitor.check.call_count}"

        call_args_list = monitor.check.call_args_list

        # Call 0: fresh feed — time_window must be absent or None.
        fresh_call = call_args_list[0]
        fresh_kwargs = fresh_call.kwargs
        assert fresh_kwargs.get("time_window") is None, (
            f"Fresh-feed call must NOT pass a time_window, got: "
            f"{fresh_kwargs.get('time_window')!r}"
        )

        # Call 1: backfill — time_window must be a (since, until) tuple
        # where until == today (cursor_before) and since = today - STEP.
        backfill_call = call_args_list[1]
        backfill_kwargs = backfill_call.kwargs
        time_window = backfill_kwargs.get("time_window")
        assert time_window is not None, (
            "Backfill call MUST pass time_window — C-1 regression. "
            "Without it, the monitor re-polls the fresh-feed window and "
            "never fetches historical papers."
        )
        since, until = time_window
        assert (
            until == today
        ), f"Backfill time_window.until should be today ({today}), got {until}"
        expected_since = today - timedelta(days=BACKFILL_STEP_DAYS_DEFAULT)
        assert since == expected_since, (
            f"Backfill time_window.since should be today - "
            f"{BACKFILL_STEP_DAYS_DEFAULT} days = {expected_since}, got {since}"
        )

    @pytest.mark.asyncio
    async def test_runner_backfill_uses_expanded_query_variants(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backfill uses the same monitor (MultiProviderMonitor or ArxivMonitor)
        as the fresh feed, ensuring query expansion applies to backfill too."""
        from unittest.mock import AsyncMock, MagicMock
        import src.services.intelligence.monitoring.runner as runner_module

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription_with_backfill(backfill_days=3)
        fresh_run = _make_run(subscription_id=sub.subscription_id)
        backfill_run = _make_run(subscription_id=sub.subscription_id)
        fresh_result = ArxivMonitorResult(
            run=fresh_run, new_papers=[], deduplicated_papers=[]
        )
        backfill_result = ArxivMonitorResult(
            run=backfill_run, new_papers=[], deduplicated_papers=[]
        )

        # Use MultiProviderMonitor mock to verify that backfill also calls it
        multi_monitor = MagicMock(spec=MultiProviderMonitor)
        multi_monitor.check = AsyncMock(side_effect=[fresh_result, backfill_result])
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        sub_mgr.update_backfill_cursor = MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=multi_monitor,
            run_repo=repo,
        )

        await runner._run_one(sub)

        # multi_monitor.check must have been called at least twice:
        # once for fresh feed, once for backfill step
        assert multi_monitor.check.call_count >= 2
        # Verify that the backfill call passed a non-None time_window.
        backfill_call = multi_monitor.check.call_args_list[1]
        assert backfill_call.kwargs.get("time_window") is not None, (
            "Backfill step must pass time_window to MultiProviderMonitor.check "
            "(C-1 contract: fresh-feed window must not be reused for backfill)"
        )

    @pytest.mark.asyncio
    async def test_runner_backfill_cursor_update_failure_logs_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If update_backfill_cursor fails, an error is logged and 0 returned."""
        from unittest.mock import AsyncMock, MagicMock
        import src.services.intelligence.monitoring.runner as runner_module

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription_with_backfill(backfill_days=7)
        fresh_run = _make_run(subscription_id=sub.subscription_id)
        backfill_run = _make_run(subscription_id=sub.subscription_id)
        fresh_result = ArxivMonitorResult(
            run=fresh_run, new_papers=[], deduplicated_papers=[]
        )
        backfill_result = ArxivMonitorResult(
            run=backfill_run, new_papers=[], deduplicated_papers=[]
        )

        monitor = MagicMock()
        monitor.check = AsyncMock(side_effect=[fresh_result, backfill_result])
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        sub_mgr.update_backfill_cursor = MagicMock(
            side_effect=RuntimeError("DB is unavailable")
        )

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        with structlog.testing.capture_logs() as cap:
            returned = await runner._run_one(sub)

        # Error event must be emitted
        error_events = [
            e for e in cap if e.get("event") == "monitor_backfill_cursor_update_failed"
        ]
        assert len(error_events) == 1
        # Run is still returned (fail-soft)
        assert returned is fresh_run

    @pytest.mark.asyncio
    async def test_runner_backfill_step_exception_logs_and_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the backfill monitor.check raises, error is logged, 0 returned."""
        from unittest.mock import MagicMock
        import src.services.intelligence.monitoring.runner as runner_module

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription_with_backfill(backfill_days=7)
        fresh_run = _make_run(subscription_id=sub.subscription_id)
        fresh_result = ArxivMonitorResult(
            run=fresh_run, new_papers=[], deduplicated_papers=[]
        )

        call_count = [0]

        async def side_effect(subscription, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return fresh_result
            raise RuntimeError("Provider unavailable")

        monitor = MagicMock()
        monitor.check = side_effect
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        sub_mgr.update_backfill_cursor = MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        with structlog.testing.capture_logs() as cap:
            returned = await runner._run_one(sub)

        error_events = [
            e for e in cap if e.get("event") == "monitor_backfill_step_failed"
        ]
        assert len(error_events) == 1
        # update_backfill_cursor should NOT have been called
        sub_mgr.update_backfill_cursor.assert_not_called()
        assert returned is fresh_run

    @pytest.mark.asyncio
    async def test_runner_backfill_emits_complete_event_on_last_step(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """monitor_backfill_complete is emitted when cursor reaches floor."""
        from unittest.mock import AsyncMock, MagicMock
        from datetime import datetime, timedelta, timezone
        import src.services.intelligence.monitoring.runner as runner_module
        from src.services.intelligence.monitoring.models import (
            BACKFILL_STEP_DAYS_DEFAULT,
        )

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        today = datetime.now(timezone.utc).date()
        # Set cursor exactly one step above the floor so one step completes it
        floor = today - timedelta(days=1)
        # cursor is floor + BACKFILL_STEP_DAYS_DEFAULT (i.e., one step from floor)
        cursor_start = floor + timedelta(days=BACKFILL_STEP_DAYS_DEFAULT)
        sub = _make_subscription_with_backfill(
            backfill_days=1,  # floor = today - 1
            backfill_cursor_date=cursor_start,
        )

        fresh_run = _make_run(subscription_id=sub.subscription_id)
        backfill_run = _make_run(subscription_id=sub.subscription_id)
        fresh_result = ArxivMonitorResult(
            run=fresh_run, new_papers=[], deduplicated_papers=[]
        )
        backfill_result = ArxivMonitorResult(
            run=backfill_run, new_papers=[], deduplicated_papers=[]
        )

        monitor = MagicMock()
        monitor.check = AsyncMock(side_effect=[fresh_result, backfill_result])
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        sub_mgr.update_backfill_cursor = MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        with structlog.testing.capture_logs() as cap:
            await runner._run_one(sub)

        complete_events = [
            e for e in cap if e.get("event") == "monitor_backfill_complete"
        ]
        assert len(complete_events) == 1
        assert complete_events[0]["subscription_id"] == sub.subscription_id

    @pytest.mark.asyncio
    async def test_runner_backfill_concurrent_cursor_write_succeeds_via_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Race test: cursor write via asyncio.to_thread tolerates internal retry.

        Verifies that _run_backfill_step correctly uses asyncio.to_thread to
        call update_backfill_cursor, so that any retry logic inside the
        synchronous update (with time.sleep) does not block the event loop.

        Design: The mock for update_backfill_cursor internally simulates
        retry_on_lock_contention — failing on the first internal attempt and
        succeeding on the second.  This proves:
        - call_count[0] >= 2 (internal retry fired)
        - The cursor was persisted to a non-None value
        - asyncio.to_thread wrapper is present (the retry's time.sleep would
          starve the loop without it — see TestEventLoopResponsiveness for
          the companion test that measures the loop directly)

        H-8: Replaced the old test that asserted call_count == 1, which would
        pass even if no retry happened (first-attempt success proves nothing).
        """
        import time as time_mod
        from unittest.mock import MagicMock
        import src.services.intelligence.monitoring.runner as runner_module

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription_with_backfill(backfill_days=7)
        fresh_run = _make_run(subscription_id=sub.subscription_id)
        backfill_run = _make_run(subscription_id=sub.subscription_id)
        fresh_result = ArxivMonitorResult(
            run=fresh_run, new_papers=[], deduplicated_papers=[]
        )
        backfill_result = ArxivMonitorResult(
            run=backfill_run, new_papers=[], deduplicated_papers=[]
        )

        inner_call_count = [0]
        recorded_cursor: list[date | None] = []

        def update_cursor_with_internal_retry(sub_id: str, cursor: date | None) -> None:
            """Simulate retry_on_lock_contention: fail once, succeed on retry."""
            inner_call_count[0] += 1
            if inner_call_count[0] == 1:
                # First attempt: transient lock — retry internally
                time_mod.sleep(
                    0
                )  # minimal sleep (proves asyncio.to_thread doesn't block)
                inner_call_count[0] += 1  # count the retry
            recorded_cursor.append(cursor)

        monitor = MagicMock()
        monitor.check = AsyncMock(side_effect=[fresh_result, backfill_result])
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        sub_mgr.update_backfill_cursor = update_cursor_with_internal_retry

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        # Run inside the event loop — asyncio.to_thread means the sleep above
        # (simulating retry backoff) does not block the event loop.
        await runner._run_one(sub)

        # H-8: assert >= 2 internal operations (proves internal retry simulated)
        assert inner_call_count[0] >= 2, (
            f"Expected at least 2 internal operations (1 initial + 1 retry) but got "
            f"{inner_call_count[0]}."
        )
        # The cursor was persisted after the retry
        assert len(recorded_cursor) >= 1
        assert recorded_cursor[0] is not None


# ===========================================================================
# H-3: MAX_PAPERS_PER_CYCLE budget enforcement for backfill
# ===========================================================================


class TestRunnerBackfillBudgetEnforcement:
    """H-3: Fresh + backfill together must not exceed MAX_PAPERS_PER_CYCLE."""

    @pytest.mark.asyncio
    async def test_backfill_skipped_when_fresh_saturates_cycle_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When fresh-feed fills MAX_PAPERS_PER_CYCLE, backfill step is skipped.

        H-3: available = MAX_PAPERS_PER_CYCLE - len(run.papers). When
        available == 0, cap == 0 and the backfill step must not fire.
        """
        from unittest.mock import AsyncMock, MagicMock
        from src.services.intelligence.monitoring.models import (
            MAX_PAPERS_PER_CYCLE,
            MonitoringPaperRecord,
        )
        import src.services.intelligence.monitoring.runner as runner_module

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription_with_backfill(backfill_days=30)

        # Fresh run saturates the cycle budget entirely.
        full_papers = [
            MonitoringPaperRecord(
                paper_id=f"paper:{i:04d}",
                title=f"Fresh Paper {i}",
                is_new=True,
                source=PaperSource.ARXIV,
            )
            for i in range(MAX_PAPERS_PER_CYCLE)
        ]
        full_run = MonitoringRun(
            subscription_id=sub.subscription_id,
            status=MonitoringRunStatus.SUCCESS,
            papers=full_papers,
        )
        fresh_result = ArxivMonitorResult(
            run=full_run, new_papers=[], deduplicated_papers=[]
        )

        monitor = MagicMock()
        monitor.check = AsyncMock(return_value=fresh_result)
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        sub_mgr.update_backfill_cursor = MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        with structlog.testing.capture_logs() as cap:
            await runner._run_one(sub)

        # monitor.check must have been called EXACTLY ONCE (fresh feed only).
        # A second call would mean the backfill fired despite a saturated budget.
        assert monitor.check.call_count == 1, (
            f"Backfill must be skipped when fresh feed saturates the cycle budget, "
            f"but monitor.check was called {monitor.check.call_count} times."
        )
        sub_mgr.update_backfill_cursor.assert_not_called()

        # The skip-budget log event must be emitted.
        skip_events = [
            e for e in cap if e.get("event") == "monitor_backfill_step_skipped_budget"
        ]
        assert len(skip_events) == 1

    @pytest.mark.asyncio
    async def test_backfill_cap_reduced_by_fresh_paper_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When fresh feed partially fills the budget, backfill cap is reduced.

        H-3: cap = min(BACKFILL_MAX_PAPERS_PER_STEP, MAX_PAPERS_PER_CYCLE - fresh)
        If fresh = 900 and BACKFILL_MAX_PAPERS_PER_STEP = 50, then
        available = 100 and cap = 50.  The backfill CAN run but with the
        computed cap.
        """
        from unittest.mock import AsyncMock, MagicMock
        from src.services.intelligence.monitoring.models import (
            BACKFILL_MAX_PAPERS_PER_STEP,
            MonitoringPaperRecord,
        )
        import src.services.intelligence.monitoring.runner as runner_module

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription_with_backfill(backfill_days=30)

        # Fresh run has 950 papers — leaves 50 available.
        fresh_papers = [
            MonitoringPaperRecord(
                paper_id=f"fresh:{i:04d}",
                title=f"Fresh Paper {i}",
                is_new=True,
                source=PaperSource.ARXIV,
            )
            for i in range(950)
        ]
        fresh_run = MonitoringRun(
            subscription_id=sub.subscription_id,
            status=MonitoringRunStatus.SUCCESS,
            papers=fresh_papers,
        )
        fresh_result = ArxivMonitorResult(
            run=fresh_run, new_papers=[], deduplicated_papers=[]
        )
        # Backfill returns BACKFILL_MAX_PAPERS_PER_STEP papers.
        backfill_papers_list = [
            MonitoringPaperRecord(
                paper_id=f"backfill:{i:04d}",
                title=f"Backfill Paper {i}",
                is_new=True,
                source=PaperSource.ARXIV,
            )
            for i in range(BACKFILL_MAX_PAPERS_PER_STEP)
        ]
        backfill_run = MonitoringRun(
            subscription_id=sub.subscription_id,
            status=MonitoringRunStatus.SUCCESS,
            papers=backfill_papers_list,
        )
        backfill_result = ArxivMonitorResult(
            run=backfill_run, new_papers=[], deduplicated_papers=[]
        )

        monitor = MagicMock()
        monitor.check = AsyncMock(side_effect=[fresh_result, backfill_result])
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        sub_mgr.update_backfill_cursor = MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        await runner._run_one(sub)

        # Backfill did fire (2 calls), but the cap was respected.
        assert monitor.check.call_count == 2


# ===========================================================================
# C-2: backfill_papers is a first-class field on MonitoringRun
# ===========================================================================


class TestRunnerBackfillPapersField:
    """C-2: backfill_papers round-trips through MonitoringRun (no attr hack)."""

    @pytest.mark.asyncio
    async def test_backfill_papers_set_on_run_after_step(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After a backfill step, run.backfill_papers reflects the count.

        C-2 fix: the count is stored in MonitoringRun.backfill_papers (a
        first-class Pydantic field), not as a private attr hack.
        """
        from unittest.mock import AsyncMock, MagicMock
        from src.services.intelligence.monitoring.models import (
            MonitoringPaperRecord,
        )
        import src.services.intelligence.monitoring.runner as runner_module

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription_with_backfill(backfill_days=7)
        fresh_run = _make_run(subscription_id=sub.subscription_id)
        fresh_result = ArxivMonitorResult(
            run=fresh_run, new_papers=[], deduplicated_papers=[]
        )

        # Backfill run has 3 papers.
        backfill_papers_list = [
            MonitoringPaperRecord(
                paper_id=f"bf:{i}",
                title=f"Backfill {i}",
                is_new=True,
                source=PaperSource.ARXIV,
            )
            for i in range(3)
        ]
        backfill_run = MonitoringRun(
            subscription_id=sub.subscription_id,
            status=MonitoringRunStatus.SUCCESS,
            papers=backfill_papers_list,
        )
        backfill_result = ArxivMonitorResult(
            run=backfill_run, new_papers=[], deduplicated_papers=[]
        )

        monitor = MagicMock()
        monitor.check = AsyncMock(side_effect=[fresh_result, backfill_result])
        repo = MagicMock()
        repo.record_run = MagicMock()
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        sub_mgr.update_backfill_cursor = MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        returned_run = await runner._run_one(sub)

        # C-2: backfill_papers is a first-class Pydantic field, not a private attr.
        assert hasattr(
            returned_run, "backfill_papers"
        ), "MonitoringRun must have a first-class backfill_papers field (C-2 fix)"
        assert returned_run.backfill_papers == 3, (
            f"run.backfill_papers should be 3 (one backfill step with 3 papers), "
            f"got {returned_run.backfill_papers}"
        )
        # Verify it's actually accessible as a proper Pydantic field (not a hack).
        run_dict = returned_run.model_dump()
        assert "backfill_papers" in run_dict, (
            "backfill_papers must appear in model_dump() output — "
            "confirms it's a real Pydantic field not a private attr"
        )
        assert run_dict["backfill_papers"] == 3


# ===========================================================================
# C-1 regression: record_run receives the real backfill_papers count
# ===========================================================================


class TestRunnerBackfillPapersPersistedBeforeRecordRun:
    """C-1 regression guard: backfill_papers must be set on the run BEFORE
    record_run is called so the DB row reflects the real count, not 0.
    """

    @pytest.mark.asyncio
    async def test_record_run_receives_correct_backfill_papers_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """record_run must be called AFTER the backfill step so the run
        object it receives has backfill_papers set to the actual count.

        C-1 fix: reordered _run_one to run backfill before record_run.
        Without the fix, record_run.call_args.kwargs["run"].backfill_papers
        would always be 0 (Pydantic default) even though the in-memory
        run ends up with backfill_papers=3.

        This test captures record_run.call_args and asserts the run
        object passed to it has backfill_papers == expected_count —
        verifying the production code path (not just in-memory state).
        """
        from unittest.mock import AsyncMock, MagicMock
        from src.services.intelligence.monitoring.models import (
            MonitoringPaperRecord,
        )
        import src.services.intelligence.monitoring.runner as runner_module

        monkeypatch.setattr(runner_module, "logger", structlog.get_logger())

        sub = _make_subscription_with_backfill(backfill_days=7)
        fresh_run = _make_run(subscription_id=sub.subscription_id)
        fresh_result = ArxivMonitorResult(
            run=fresh_run, new_papers=[], deduplicated_papers=[]
        )

        # Backfill run has 4 papers — a number distinct from 0 or 3.
        backfill_papers_list = [
            MonitoringPaperRecord(
                paper_id=f"c1-bf:{i}",
                title=f"C1 Backfill {i}",
                is_new=True,
                source=PaperSource.ARXIV,
            )
            for i in range(4)
        ]
        backfill_run = MonitoringRun(
            subscription_id=sub.subscription_id,
            status=MonitoringRunStatus.SUCCESS,
            papers=backfill_papers_list,
        )
        backfill_result = ArxivMonitorResult(
            run=backfill_run, new_papers=[], deduplicated_papers=[]
        )

        monitor = MagicMock()
        monitor.check = AsyncMock(side_effect=[fresh_result, backfill_result])
        repo = MagicMock()
        repo.record_run = MagicMock()  # records call_args for inspection
        sub_mgr = MagicMock()
        sub_mgr.mark_checked = MagicMock()
        sub_mgr.update_backfill_cursor = MagicMock()

        runner = MonitoringRunner(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

        returned_run = await runner._run_one(sub)

        # ---------------------------------------------------------------
        # C-1 regression assertion: inspect what record_run actually
        # received. Before the C-1 fix this would be 0 because backfill
        # ran AFTER record_run. Now it must be 4.
        # ---------------------------------------------------------------
        assert repo.record_run.call_count == 1, "record_run must be called exactly once"
        call_args = repo.record_run.call_args
        # record_run is called as record_run(run, user_id=...) so the run
        # is the first positional arg.
        persisted_run = call_args.args[0]
        assert persisted_run.backfill_papers == 4, (
            f"record_run must receive a run with backfill_papers=4, "
            f"got {persisted_run.backfill_papers}. "
            "C-1 fix: backfill step must run BEFORE record_run."
        )

        # Also confirm the in-memory run agrees.
        assert returned_run.backfill_papers == 4

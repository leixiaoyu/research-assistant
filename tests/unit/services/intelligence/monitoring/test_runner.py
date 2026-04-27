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
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.intelligence.monitoring.arxiv_monitor import ArxivMonitorResult
from src.services.intelligence.monitoring.models import (
    MonitoringRun,
    MonitoringRunStatus,
    ResearchSubscription,
    SubscriptionStatus,
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
        repo.record_run.assert_called_once()
        kwargs = repo.record_run.call_args.kwargs
        assert kwargs["user_id"] == "alice"

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

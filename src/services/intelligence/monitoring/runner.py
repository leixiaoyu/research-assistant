"""Orchestrates one monitoring cycle across many subscriptions.

Why this exists
---------------
Week 1 (PR #108) shipped the building blocks:

- ``SubscriptionManager``: load + persist ``ResearchSubscription`` rows.
- ``ArxivMonitor``: poll one subscription, return an ``ArxivMonitorResult``.
- ``MonitoringRunRepository``: persist the ``MonitoringRun`` audit row.

What's missing is a single seam that wires them together so the Week 2
APScheduler ``MonitoringCheckJob`` (issue #117) can fire one method and
get a deterministic outcome. ``MonitoringRunner`` is that seam.

Behavior contract
-----------------
``run_once(user_id=None)`` does the following, in order:

1. Load active subscriptions through ``SubscriptionManager``
   (filtered by ``user_id`` when provided).
2. For each subscription, call ``ArxivMonitor.check`` and capture the
   resulting ``MonitoringRun``. **Failures on individual subs do not
   abort the cycle** -- they're logged, captured as a ``FAILED`` run
   record, and the loop continues.
3. Persist every run (success + failure) through
   ``MonitoringRunRepository.record_run`` so the audit log is complete
   regardless of outcome.
4. Call ``SubscriptionManager.mark_checked`` only on **non-FAILED**
   runs. A FAILED run means the upstream provider was unavailable; we
   don't want the next cycle to skip the sub because we updated the
   timestamp on a failure.
5. Return the list of runs (in subscription order) so the caller can
   feed them into the digest generator (Week 2) or log per-cycle
   metrics.

The return type is intentionally ``list[MonitoringRun]`` (not
``ArxivMonitorResult``) because anything richer than the persisted
audit record is observability noise that the scheduler does not need
to act on -- the caller can pull paper details from the registry if
required.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import structlog

from src.services.intelligence.monitoring.arxiv_monitor import ArxivMonitor
from src.services.intelligence.monitoring.models import (
    MonitoringRun,
    MonitoringRunStatus,
    ResearchSubscription,
)
from src.services.intelligence.monitoring.run_repository import (
    MonitoringRunRepository,
)
from src.services.intelligence.monitoring.subscription_manager import (
    SubscriptionManager,
)

if TYPE_CHECKING:
    from src.services.providers.arxiv import ArxivProvider
    from src.services.registry.service import RegistryService

logger = structlog.get_logger()


class MonitoringRunner:
    """Orchestrates a single monitoring cycle.

    Single seam for the future APScheduler ``MonitoringCheckJob``
    (issue #117). Construction takes the three Week-1 collaborators;
    the Week-2 job will instantiate this once and call ``run_once()``
    on each tick.
    """

    def __init__(
        self,
        subscription_manager: SubscriptionManager,
        monitor: ArxivMonitor,
        run_repo: MonitoringRunRepository,
    ) -> None:
        """Initialize the runner.

        Args:
            subscription_manager: Source of active subscriptions and
                target for ``mark_checked`` updates.
            monitor: ArXiv monitor that performs the per-subscription
                poll. The runner does not care whether a future
                multi-source monitor wraps this -- the contract is
                ``check(subscription) -> ArxivMonitorResult``.
            run_repo: Repository for the per-cycle audit record.
        """
        self._subscriptions = subscription_manager
        self._monitor = monitor
        self._run_repo = run_repo

    @classmethod
    def from_paths(
        cls,
        *,
        db_path: Path | str,
        registry: "RegistryService",
        arxiv_provider: "ArxivProvider",
    ) -> "MonitoringRunner":
        """Convenience factory wiring the standard collaborators.

        The Week-2 ``MonitoringCheckJob`` (#117) and any CLI / REST
        surface that just has a ``db_path`` plus the shared
        infrastructure handles (registry, arxiv provider) shouldn't
        have to instantiate ``SubscriptionManager`` + ``ArxivMonitor`` +
        ``MonitoringRunRepository`` by hand -- the facade promises a
        one-liner. This classmethod is that one-liner.

        Both subscription manager and run repo are eagerly initialized
        so the caller doesn't have to remember the two-phase
        construct-then-initialize idiom.

        Args:
            db_path: SQLite database file path. Must lie under one of
                the approved storage roots (``data/``, ``cache/``, or
                the system temp dir) -- enforced by
                :func:`sanitize_storage_path` inside both
                ``SubscriptionManager`` and ``MonitoringRunRepository``.
                Accepts ``str`` or ``Path``; coerced to ``Path``
                upfront for downstream typing (matches
                ``SubscriptionManager.__init__``).
            registry: The shared global ``RegistryService`` used by the
                monitor for paper deduplication.
            arxiv_provider: The shared ``ArxivProvider`` used by the
                monitor to poll ArXiv.

        Returns:
            A fully-wired, initialized ``MonitoringRunner`` ready for
            ``run_once()``.

        Lifecycle note
        --------------
        Intended to be constructed ONCE per process (e.g., at scheduler
        startup) and reused across run cycles. Each construction calls
        ``MigrationManager.migrate()`` on both repos -- migrations are
        idempotent but still hit the DB. The future Week-2
        ``MonitoringCheckJob`` (#117) should hold the runner instance
        in ``__init__`` and call ``run_once()`` per tick.

        Failure recovery: if either ``initialize()`` raises, simply
        re-call ``from_paths()`` -- both subscription manager and run
        repository migrations are idempotent, so the partial
        construction left behind is safe to discard.
        """
        db_path = Path(db_path)  # accept str | Path; coerce for downstream typing
        sub_mgr = SubscriptionManager(db_path)
        sub_mgr.initialize()
        monitor = ArxivMonitor(provider=arxiv_provider, registry=registry)
        repo = MonitoringRunRepository(db_path)
        repo.initialize()
        return cls(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
        )

    async def run_once(self, user_id: Optional[str] = None) -> list[MonitoringRun]:
        """Run one monitoring cycle across all active subscriptions.

        Args:
            user_id: When provided, only that user's active
                subscriptions are polled. The default ``None`` polls
                every active subscription regardless of owner --
                matching the Week-2 job's "global tick" behavior.

        Returns:
            The ``MonitoringRun`` for each subscription processed,
            in the same order they were loaded. Both successful and
            failed runs are included so the caller has full visibility
            into the cycle.
        """
        active_subs = self._subscriptions.list_subscriptions(
            user_id=user_id, active_only=True
        )
        logger.info(
            "monitoring_runner_cycle_starting",
            subscription_count=len(active_subs),
            user_id=user_id,
        )

        runs: list[MonitoringRun] = []
        for sub in active_subs:
            run = await self._run_one(sub)
            runs.append(run)

        succeeded = sum(1 for r in runs if r.status is not MonitoringRunStatus.FAILED)
        failed = sum(1 for r in runs if r.status is MonitoringRunStatus.FAILED)
        logger.info(
            "monitoring_runner_cycle_complete",
            subscription_count=len(active_subs),
            succeeded=succeeded,
            failed=failed,
            user_id=user_id,
        )
        return runs

    async def _run_one(self, subscription: ResearchSubscription) -> MonitoringRun:
        """Run one cycle for ``subscription``, persist + mark, return run.

        Encapsulates the per-subscription error envelope so a single
        broken sub never aborts the broader cycle. ``ArxivMonitor.check``
        already converts upstream provider failures into a ``FAILED``
        ``MonitoringRun``; this layer additionally guards the persist
        + mark_checked steps so persistence outages don't propagate.
        """
        try:
            result = await self._monitor.check(subscription)
            run = result.run
        except Exception as exc:
            # Defensive envelope: ArxivMonitor.check is documented to
            # never raise, but a future monitor (or a bug) might. Keep
            # the cycle going and surface the failure as a FAILED run.
            logger.warning(
                "monitoring_runner_check_error",
                subscription_id=subscription.subscription_id,
                error=str(exc),
            )
            run = MonitoringRun(
                subscription_id=subscription.subscription_id,
                status=MonitoringRunStatus.FAILED,
                error=f"monitor_check_error: {exc}",
            )

        # Persist the audit row regardless of provider outcome (success,
        # partial, AND failed runs go to the audit log). We catch
        # persistence failures so a SQLite hiccup on one row doesn't
        # break the rest of the cycle -- the in-memory ``run`` is still
        # returned to the caller for observability.
        #
        # ``record_run`` is synchronous and -- on lock contention --
        # spends up to ``_RECORD_RUN_MAX_ATTEMPTS * backoff`` seconds
        # in ``time.sleep`` (PR #119 #S9 retry loop). Running that in
        # the event loop would starve every concurrent task in the
        # interim. ``asyncio.to_thread`` parks it on the default thread
        # executor so the loop stays responsive (PR #123 review #H1).
        #
        # Atomic-state-transition guarantee (PR #124 team review):
        # ``mark_checked`` MUST NOT be called if persistence failed.
        # Otherwise the subscription's ``last_checked_at`` advances
        # past the polling window while the audit row of papers found
        # in that window is lost -- the Week-2 digest generator would
        # silently miss research updates for that interval. We early-
        # return on persistence failure so the next cycle re-polls the
        # same window and re-records the audit row.
        try:
            await asyncio.to_thread(
                self._run_repo.record_run, run, user_id=subscription.user_id
            )
        except Exception as exc:
            logger.error(
                "monitoring_persistence_failed_skipping_mark_checked",
                subscription_id=subscription.subscription_id,
                run_id=run.run_id,
                error=str(exc),
            )
            # IMPORTANT: skip mark_checked so the next cycle retries
            # the window. Returning the in-memory ``run`` preserves
            # observability for the caller.
            return run

        # Persistence succeeded. Only mark the subscription as checked
        # on success / partial. A FAILED run means we never spoke to
        # the provider; updating last_checked would cause us to skip
        # the next cycle for the wrong reason.
        if run.status is not MonitoringRunStatus.FAILED:
            try:
                self._subscriptions.mark_checked(subscription.subscription_id)
            except Exception as exc:
                logger.error(
                    "monitoring_runner_mark_checked_failed",
                    subscription_id=subscription.subscription_id,
                    error=str(exc),
                )
        return run

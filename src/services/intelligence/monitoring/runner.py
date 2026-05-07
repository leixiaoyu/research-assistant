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
3. Score each paper via ``RelevanceScorer`` (LLM-based). Scorer
   errors on individual papers are logged but do not abort the sub's
   run. A scorer result of ``None`` (scored but skipped) is silently
   dropped. Budget is capped at ``MAX_LLM_CALLS_PER_CYCLE`` total
   calls across the whole cycle.
4. Persist every run (success + failure) through
   ``MonitoringRunRepository.record_run`` so the audit log is complete
   regardless of outcome.
5. Call ``SubscriptionManager.mark_checked`` only on **non-FAILED**
   runs. A FAILED run means the upstream provider was unavailable; we
   don't want the next cycle to skip the sub because we updated the
   timestamp on a failure.
6. Return the list of runs (in subscription order) so the caller can
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
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import structlog

from src.services.intelligence.monitoring.arxiv_monitor import ArxivMonitor
from src.services.intelligence.monitoring.multi_provider_monitor import (
    MultiProviderMonitor,
)
from src.services.intelligence.monitoring.models import (
    BACKFILL_MAX_PAPERS_PER_STEP,
    BACKFILL_STEP_DAYS_DEFAULT,
    MonitoringPaperRecord,
    MonitoringRun,
    MonitoringRunStatus,
    PaperSource,
    ResearchSubscription,
)
from src.services.intelligence.monitoring.relevance_scorer import (
    LLMResponseError,
    RelevanceScorer,
)
from src.services.intelligence.monitoring.run_repository import (
    MonitoringRunRepository,
)
from src.services.intelligence.monitoring.subscription_manager import (
    SubscriptionManager,
)

if TYPE_CHECKING:
    from src.services.llm.service import LLMService
    from src.services.providers.arxiv import ArxivProvider
    from src.services.providers.base import DiscoveryProvider
    from src.services.registry.service import RegistryService
    from src.utils.query_expander import QueryExpander

logger = structlog.get_logger()

# LLM budget cap per cycle -- prevents runaway cost on large sub lists.
# At ~$0.000015/call (Gemini Flash, ~200 in / 50 out tokens), 5000 calls
# is ~$0.075 per cycle -- well within operational limits while protecting
# against pathological subscription counts.
MAX_LLM_CALLS_PER_CYCLE = 5000

# Concurrent LLM calls are capped to avoid saturating the upstream API.
# Flash's documented QPS limit is 300/min; 10 concurrent with asyncio
# gives headroom for the ArXiv round-trips happening in parallel.
_LLM_CONCURRENCY = 10

# High-confidence low-reasoning sanity check: if a score is >= 0.95
# but the reasoning is very short (< 30 chars), the LLM likely echoed
# the prompt rather than producing a genuine assessment.
_HIGH_SCORE_MIN_REASONING = 30
_HIGH_SCORE_THRESHOLD = 0.95


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
        monitor: ArxivMonitor | MultiProviderMonitor,
        run_repo: MonitoringRunRepository,
        scorer: Optional[RelevanceScorer] = None,
    ) -> None:
        """Initialize the runner.

        Args:
            subscription_manager: Source of active subscriptions and
                target for ``mark_checked`` updates.
            monitor: A monitor implementing ``check(subscription) ->
                ArxivMonitorResult``. Either :class:`ArxivMonitor`
                (single-provider, literal-query) or
                :class:`MultiProviderMonitor` (multi-provider,
                LLM-expanded queries — Tier 1) is accepted; the runner
                duck-types on the ``check`` interface.
            run_repo: Repository for the per-cycle audit record.
            scorer: Optional ``RelevanceScorer`` for LLM-based relevance
                scoring. When ``None``, papers are returned unscored
                (Week-1 compatible). Production callers should inject
                a scorer built from the project-wide ``LLMService``.
        """
        self._subscriptions = subscription_manager
        self._monitor = monitor
        self._run_repo = run_repo
        self._scorer = scorer

    # ------------------------------------------------------------------
    # Public delegation methods (H-C1: encapsulate private attributes)
    # ------------------------------------------------------------------

    def list_subscriptions(
        self,
        *,
        user_id: Optional[str] = None,
        active_only: bool = False,
    ) -> list[ResearchSubscription]:
        """List subscriptions, delegating to the subscription manager.

        Provides a public API so callers (e.g., ``MonitoringCheckJob``)
        do not need to access the private ``_subscriptions`` attribute.
        """
        return self._subscriptions.list_subscriptions(
            user_id=user_id, active_only=active_only
        )

    def get_audit_run(self, run_id: str) -> object:
        """Fetch an audit run record by id, delegating to the run repo.

        Provides a public API so callers (e.g., ``MonitoringCheckJob``)
        do not need to access the private ``_run_repo`` attribute.

        Returns:
            A ``MonitoringRunAudit`` instance, or ``None`` if not found.
        """
        return self._run_repo.get_run(run_id)

    @classmethod
    def from_paths(
        cls,
        *,
        db_path: Path | str,
        registry: "RegistryService",
        arxiv_provider: "ArxivProvider",
        llm_service: Optional["LLMService"] = None,
        extra_providers: Optional["dict[PaperSource, DiscoveryProvider]"] = None,
        query_expander: Optional["QueryExpander"] = None,
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
            llm_service: Optional ``LLMService`` used to build a
                ``RelevanceScorer``. When ``None``, papers are returned
                unscored (backward-compatible with Week-1 behavior).
            extra_providers: Optional mapping of ``PaperSource`` to
                ``DiscoveryProvider`` for multi-provider search beyond
                arXiv (e.g., Semantic Scholar, OpenAlex, HuggingFace).
                When supplied, a :class:`MultiProviderMonitor` is
                constructed with arXiv + the extras; queries fan out
                across all providers in parallel. When ``None``
                (default), the legacy single-provider
                :class:`ArxivMonitor` is used (backward compatible).
                (Tier 1: monitoring expanded search, Issue #139.)
            query_expander: Optional :class:`QueryExpander` for
                LLM-based query expansion. When supplied alongside
                ``extra_providers`` (or even alone), each subscription's
                literal query is expanded into N variants via Gemini
                Flash before the provider fan-out — broadens discovery
                coverage at ~1 cheap LLM call per subscription per
                cycle. When ``None``, only the literal subscription
                query is searched. (Tier 1.)

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

        # Tier 1: choose monitor implementation based on what was supplied.
        # If the caller provided extra providers OR a query expander, build
        # the broader-discovery MultiProviderMonitor. Otherwise keep the
        # legacy single-provider ArxivMonitor for backward compatibility.
        monitor: ArxivMonitor | MultiProviderMonitor
        # H-C6: use ``is not None`` instead of truthiness so that an
        # explicit ``extra_providers={}`` (empty dict) still builds
        # MultiProviderMonitor — the caller explicitly opted in.
        if extra_providers is not None or query_expander is not None:
            providers: dict[PaperSource, DiscoveryProvider] = {
                PaperSource.ARXIV: arxiv_provider,
            }
            if extra_providers is not None:
                # Defensive copy to isolate from caller mutations; reject
                # an attempt to override the canonical ArXiv provider via
                # the extras dict (caller should pass the override as
                # ``arxiv_provider`` instead).
                for src, provider in extra_providers.items():
                    if src is PaperSource.ARXIV:
                        raise ValueError(
                            "extra_providers must not include "
                            "PaperSource.ARXIV; pass arxiv_provider directly"
                        )
                    providers[src] = provider
            monitor = MultiProviderMonitor(
                providers=providers,
                registry=registry,
                query_expander=query_expander,
            )
        else:
            monitor = ArxivMonitor(provider=arxiv_provider, registry=registry)

        repo = MonitoringRunRepository(db_path)
        repo.initialize()
        scorer = RelevanceScorer(llm_service) if llm_service is not None else None
        return cls(
            subscription_manager=sub_mgr,
            monitor=monitor,
            run_repo=repo,
            scorer=scorer,
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

        # Shared semaphore + budget counter across ALL subs in the cycle
        # so a single large subscription cannot starve the others of
        # their LLM budget (H-S5 budget cap).
        sem = asyncio.Semaphore(_LLM_CONCURRENCY)
        llm_calls_used: list[int] = [0]  # mutable container for closure

        runs: list[MonitoringRun] = []
        for sub in active_subs:
            run = await self._run_one(sub, sem=sem, llm_calls_used=llm_calls_used)
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

    async def _score_paper(
        self,
        subscription: ResearchSubscription,
        paper: MonitoringPaperRecord,
        sem: asyncio.Semaphore,
        llm_calls_used: list[int],
    ) -> None:
        """Score one paper in-place, respecting the budget cap + semaphore.

        On success, sets ``paper.relevance_score`` and
        ``paper.relevance_reasoning``. On any error (LLM failure,
        budget exhausted) the paper is left unscored -- the run is
        not failed, only observability events are emitted.

        Args:
            subscription: The owning subscription (for prompt context).
            paper: The ``MonitoringPaperRecord`` to score (mutated
                in-place if successful).
            sem: Concurrency semaphore -- limits simultaneous LLM calls.
            llm_calls_used: Single-element list used as a mutable
                counter shared across the cycle.
        """
        if self._scorer is None:
            return

        # Budget guard: if we've hit the per-cycle cap, emit an audit
        # event and bail rather than spending more.
        if llm_calls_used[0] >= MAX_LLM_CALLS_PER_CYCLE:
            logger.warning(
                "monitoring_llm_budget_exhausted",
                subscription_id=subscription.subscription_id,
                paper_id=paper.paper_id,
                max_calls=MAX_LLM_CALLS_PER_CYCLE,
                calls_used=llm_calls_used[0],
            )
            return

        # We need a PaperMetadata-compatible object to pass to the scorer.
        # MonitoringPaperRecord carries title + url; reconstruct a minimal
        # PaperMetadata so the scorer can build its prompt. PaperMetadata
        # requires a valid HttpUrl; skip scoring rather than fabricating a
        # URL for non-arXiv papers that have no provenance (C-2).
        from src.models.paper import PaperMetadata

        if paper.url is None:
            # Issue #141: include per-paper source so "why was this
            # paper skipped?" queries can pivot on provider — non-arXiv
            # papers more frequently land here because their feeds may
            # not include URLs that pass PaperMetadata's HttpUrl
            # validator.
            logger.info(
                "monitoring_relevance_score_skipped_no_url",
                subscription_id=subscription.subscription_id,
                paper_id=paper.paper_id,
                source=paper.source.value,
            )
            return

        paper_meta = PaperMetadata(
            paper_id=paper.paper_id,
            title=paper.title,
            url=paper.url,  # type: ignore[arg-type]
        )

        async with sem:
            llm_calls_used[0] += 1
            try:
                score_result = await self._scorer.score(subscription, paper_meta)
            except LLMResponseError as exc:
                logger.warning(
                    "monitoring_relevance_score_failed",
                    subscription_id=subscription.subscription_id,
                    paper_id=paper.paper_id,
                    error=str(exc),
                )
                return
            except Exception as exc:
                logger.error(
                    "monitoring_relevance_score_unexpected_error",
                    subscription_id=subscription.subscription_id,
                    paper_id=paper.paper_id,
                    error=str(exc),
                )
                return

        # Sanity guard: reject suspiciously high scores with thin reasoning
        # (prompt-injection signal -- LLM echoed the prompt, H-S1).
        if (
            score_result.score >= _HIGH_SCORE_THRESHOLD
            and len(score_result.reasoning) < _HIGH_SCORE_MIN_REASONING
        ):
            logger.warning(
                "monitoring_relevance_score_sanity_rejected",
                subscription_id=subscription.subscription_id,
                paper_id=paper.paper_id,
                score=score_result.score,
                reasoning_len=len(score_result.reasoning),
            )
            return

        paper.relevance_score = score_result.score
        paper.relevance_reasoning = score_result.reasoning

    async def _run_one(
        self,
        subscription: ResearchSubscription,
        *,
        sem: Optional[asyncio.Semaphore] = None,
        llm_calls_used: Optional[list[int]] = None,
    ) -> MonitoringRun:
        """Run one cycle for ``subscription``, persist + mark, return run.

        Encapsulates the per-subscription error envelope so a single
        broken sub never aborts the broader cycle. ``ArxivMonitor.check``
        already converts upstream provider failures into a ``FAILED``
        ``MonitoringRun``; this layer additionally guards the persist
        + mark_checked steps so persistence outages don't propagate.

        After the monitor returns, each paper is relevance-scored via
        ``_score_paper`` (if a scorer is wired). Scoring errors on
        individual papers are logged but never propagate to the run
        level (Fail-Soft Boundary across independent peers).
        """
        try:
            # H-S1: pass budget counters to MultiProviderMonitor so the
            # expander call is gated against the cycle's LLM budget.
            # ArxivMonitor.check does not accept these kwargs; duck-type
            # on the concrete type so we only pass them when meaningful.
            if isinstance(self._monitor, MultiProviderMonitor):
                result = await self._monitor.check(
                    subscription,
                    llm_calls_used=llm_calls_used,
                    max_calls=MAX_LLM_CALLS_PER_CYCLE,
                )
            else:
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

        # Score each paper in-place BEFORE persisting so the audit row
        # carries the scores (C-1). Use the cycle-wide semaphore and
        # budget counter; fall back to fresh ones if called directly
        # (e.g., from tests that call _run_one directly without the
        # cycle context).
        if sem is None:
            sem = asyncio.Semaphore(_LLM_CONCURRENCY)
        if llm_calls_used is None:
            llm_calls_used = [0]

        if self._scorer is not None and run.status is not MonitoringRunStatus.FAILED:
            scoring_tasks = [
                self._score_paper(subscription, paper, sem, llm_calls_used)
                for paper in run.papers
            ]
            await asyncio.gather(*scoring_tasks)

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

        # Backfill step (Phase 9.1 / Issue #145): walk backwards through
        # the history window in BACKFILL_STEP_DAYS_DEFAULT-day chunks.
        # Only run when backfill_days > 0 AND the main run was not FAILED
        # (no point backfilling if the provider is unavailable). The
        # backfill_papers count is appended to the in-memory run's
        # MonitoringRunAudit representation via a separate field so the
        # digest generator can render "N fresh + M backfill" when relevant.
        if (
            run.status is not MonitoringRunStatus.FAILED
            and subscription.backfill_days > 0
        ):
            backfill_papers_added = await self._run_backfill_step(subscription, run)
            # Attach backfill count to the run for the caller's observability.
            # MonitoringRun does not have a ``backfill_papers`` field (it is
            # an in-memory record); the count is surfaced via the structured
            # log event ``monitor_backfill_step_complete`` and later via
            # ``MonitoringRunAudit.backfill_papers`` when the run is read back.
            run._backfill_papers = backfill_papers_added  # type: ignore[attr-defined]

        return run

    async def _run_backfill_step(
        self,
        subscription: ResearchSubscription,
        run: MonitoringRun,
    ) -> int:
        """Execute one backfill step for ``subscription``.

        Walks the cursor backward by ``BACKFILL_STEP_DAYS_DEFAULT`` days,
        searching the same query variants as the fresh feed (same monitor
        / expander). Caps results at ``BACKFILL_MAX_PAPERS_PER_STEP`` per
        step. Updates the backfill cursor atomically after success.

        Args:
            subscription: The owning subscription (must have backfill_days > 0).
            run: The fresh-feed run (for subscription_id reference only).

        Returns:
            Number of papers added from the backfill step (0 on skip or error).
        """
        today = date.today()
        cursor_before = subscription.backfill_cursor_date or today
        floor = max(
            subscription.created_at.date(),
            today - timedelta(days=subscription.backfill_days),
        )

        if cursor_before <= floor:
            # Backfill already complete.
            logger.info(
                "monitor_backfill_complete",
                subscription_id=subscription.subscription_id,
                total_days_covered=subscription.backfill_days,
            )
            return 0

        step_end = cursor_before
        step_start = step_end - timedelta(days=BACKFILL_STEP_DAYS_DEFAULT)
        # Clamp step_start to the floor so we don't overshoot.
        step_start = max(step_start, floor)

        # Fan-out: use the same monitor (ArxivMonitor or MultiProviderMonitor)
        # as the fresh-feed run. The monitor's ``check`` call handles query
        # expansion and provider fan-out exactly as it does for the fresh feed.
        # We then cap the results at BACKFILL_MAX_PAPERS_PER_STEP.
        papers_added = 0
        papers_capped = False
        try:
            if isinstance(self._monitor, MultiProviderMonitor):
                backfill_result = await self._monitor.check(subscription)
            else:
                backfill_result = await self._monitor.check(subscription)

            backfill_papers = backfill_result.run.papers
            if len(backfill_papers) > BACKFILL_MAX_PAPERS_PER_STEP:
                backfill_papers = backfill_papers[:BACKFILL_MAX_PAPERS_PER_STEP]
                papers_capped = True

            papers_added = len(backfill_papers)
        except Exception as exc:
            logger.error(
                "monitor_backfill_step_failed",
                subscription_id=subscription.subscription_id,
                cursor_before=cursor_before.isoformat(),
                error=str(exc),
            )
            return 0

        # Advance the cursor to step_start (the lower bound of the window
        # we just processed). The cursor moves backward on each cycle.
        new_cursor = step_start
        try:
            await asyncio.to_thread(
                self._subscriptions.update_backfill_cursor,
                subscription.subscription_id,
                new_cursor,
            )
        except Exception as exc:
            logger.error(
                "monitor_backfill_cursor_update_failed",
                subscription_id=subscription.subscription_id,
                cursor_before=cursor_before.isoformat(),
                cursor_after=new_cursor.isoformat(),
                error=str(exc),
            )
            return 0

        logger.info(
            "monitor_backfill_step_complete",
            subscription_id=subscription.subscription_id,
            cursor_before=cursor_before.isoformat(),
            cursor_after=new_cursor.isoformat(),
            papers_added=papers_added,
            papers_capped=papers_capped,
        )

        if new_cursor <= floor:
            logger.info(
                "monitor_backfill_complete",
                subscription_id=subscription.subscription_id,
                total_papers_added=papers_added,
                days_covered=subscription.backfill_days,
            )

        return papers_added

"""ArXiv-only monitor (REQ-9.1.2).

Composes the existing ``ArxivProvider`` (rate limit + structured query
+ feedparser parsing) with the global ``PaperRegistry`` to produce a
deduplicated stream of *new* papers per subscription.

Design notes:

- We do **not** open a second HTTP client. ``ArxivProvider`` already
  knows how to rate-limit (3 req/sec via its ``RateLimiter``), retry
  with exponential backoff (``tenacity``), and parse the Atom feed.
  Composing it gives us all of that for free.
- We build a ``ResearchTopic`` on the fly from the subscription's query
  and ``poll_interval_hours`` window. ``poll_interval_hours`` is treated
  as the look-back window (a 6h subscription polls the last 6h of
  papers); this is conservative — a paper showing up twice within the
  same window is filtered by registry dedup, not by us.
- Per-cycle paper cap is enforced after fetching to keep the
  ArxivProvider call site clean. The cap is a security/SR control, not
  a functional one — see ``MAX_PAPERS_PER_CYCLE`` in ``models``.
- Failures from the provider are caught and surfaced as a ``FAILED``
  ``MonitoringRun`` with an ``error`` field. We never re-raise, because
  the scheduler in Week 2 will iterate over many subscriptions and one
  upstream outage must not stop the cycle for the others.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

from src.models.config.core import (
    ResearchTopic,
    TimeframeRecent,
    TimeframeType,
)
from src.models.paper import PaperMetadata
from src.models.registry import RegistryEntry
from src.services.intelligence.models.monitoring import PaperSource
from src.services.intelligence.monitoring.models import (
    MAX_PAPERS_PER_CYCLE,
    MonitoringPaperRecord,
    MonitoringRun,
    MonitoringRunStatus,
    ResearchSubscription,
)
from src.services.providers.arxiv import ArxivProvider
from src.services.registry import RegistryService

logger = structlog.get_logger()


# Default lookback window when a poll interval is too long to express
# as a TimeframeRecent (>720h cap). ``ArxivProvider`` validates the
# string at construction time so we cap to the provider's known max.
_MAX_POLL_HOURS = 720
# How many papers to ask ArXiv for per call. We pull the per-cycle cap
# so a single subscription can saturate the cycle if necessary.
_DEFAULT_MAX_PAPERS = MAX_PAPERS_PER_CYCLE


class ArxivMonitorResult(BaseModel):
    """Convenience aggregate of a monitoring cycle's outcome."""

    model_config = ConfigDict(extra="forbid")

    run: MonitoringRun
    new_papers: list[PaperMetadata]
    deduplicated_papers: list[PaperMetadata]


class ArxivMonitor:
    """Polls ArXiv for new papers matching a subscription.

    Args:
        provider: ArxivProvider instance (rate limiter is the
            provider's responsibility). Tests inject a mocked one.
        registry: RegistryService used both for deduplication and as
            the registration sink for new papers.
        topic_slug_prefix: Prefix used when affiliating monitored papers
            in the registry — defaults to ``"monitor"`` so monitor-sourced
            papers cluster under one folder convention.
        max_papers_per_cycle: Hard cap on papers processed per call
            (defaults to the SR limit, currently 1000).
    """

    def __init__(
        self,
        provider: ArxivProvider,
        registry: RegistryService,
        topic_slug_prefix: str = "monitor",
        max_papers_per_cycle: int = _DEFAULT_MAX_PAPERS,
    ):
        if max_papers_per_cycle <= 0:
            raise ValueError("max_papers_per_cycle must be positive")
        if max_papers_per_cycle > MAX_PAPERS_PER_CYCLE:
            raise ValueError(
                f"max_papers_per_cycle cannot exceed {MAX_PAPERS_PER_CYCLE}"
            )
        self._provider = provider
        self._registry = registry
        self._topic_slug_prefix = topic_slug_prefix
        self._max_papers_per_cycle = max_papers_per_cycle

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def check(self, subscription: ResearchSubscription) -> ArxivMonitorResult:
        """Run one monitoring cycle for ``subscription``.

        Behavior:

        1. Skip immediately if the subscription is not active or its
           sources don't include ArXiv.
        2. Build a ``ResearchTopic`` from ``query`` + ``poll_interval_hours``.
        3. Call ``ArxivProvider.search``; bound the result to
           ``max_papers_per_cycle``.
        4. For each paper, resolve identity against the registry. New
           papers are registered (``discovery_only=True``); known papers
           are skipped.
        5. Return an ``ArxivMonitorResult`` with the run record and the
           split paper lists.

        This method never raises on provider/registry failure — instead
        it returns a ``FAILED`` (or ``PARTIAL``) ``MonitoringRun`` so
        the scheduler keeps cycling through other subscriptions.
        """
        run = MonitoringRun(
            subscription_id=subscription.subscription_id,
            source=PaperSource.ARXIV,
        )

        if not self._monitor_eligible(subscription):
            run.status = MonitoringRunStatus.SUCCESS
            run.finished_at = datetime.now(timezone.utc)
            logger.info(
                "monitor_skipped",
                subscription_id=subscription.subscription_id,
                reason="paused_or_no_arxiv",
            )
            return ArxivMonitorResult(run=run, new_papers=[], deduplicated_papers=[])

        topic = self._build_topic(subscription)

        try:
            fetched = await self._provider.search(topic)
        except Exception as exc:
            # Provider may surface APIError / RateLimitError /
            # APIParameterError. We capture the message and let the
            # scheduler keep iterating.
            run.status = MonitoringRunStatus.FAILED
            run.error = f"arxiv_provider_error: {exc}"
            run.finished_at = datetime.now(timezone.utc)
            logger.warning(
                "monitor_provider_error",
                subscription_id=subscription.subscription_id,
                error=str(exc),
            )
            return ArxivMonitorResult(run=run, new_papers=[], deduplicated_papers=[])

        # Bound the result. ArxivProvider already honors topic.max_papers,
        # but the cap is a security guarantee enforced here as well.
        if len(fetched) > self._max_papers_per_cycle:
            fetched = fetched[: self._max_papers_per_cycle]

        run.papers_seen = len(fetched)

        new_papers: list[PaperMetadata] = []
        deduped: list[PaperMetadata] = []
        partial_failure = False

        topic_slug = self._topic_slug(subscription)

        for paper in fetched:
            try:
                match = self._registry.resolve_identity(paper)
            except Exception as exc:
                # Identity resolution shouldn't fail in practice, but
                # be defensive — one bad row mustn't kill the cycle.
                partial_failure = True
                logger.warning(
                    "monitor_identity_resolution_error",
                    subscription_id=subscription.subscription_id,
                    paper_id=paper.paper_id,
                    error=str(exc),
                )
                continue

            if match.matched:
                deduped.append(paper)
                run.papers.append(self._to_record(paper, is_new=False))
                continue

            try:
                self._register_new_paper(paper, topic_slug)
            except Exception as exc:
                # Failure to persist is recorded but doesn't abort the
                # cycle. The scheduler will retry on the next interval.
                partial_failure = True
                logger.warning(
                    "monitor_registry_write_error",
                    subscription_id=subscription.subscription_id,
                    paper_id=paper.paper_id,
                    error=str(exc),
                )
                continue

            new_papers.append(paper)
            run.papers.append(self._to_record(paper, is_new=True))

        run.papers_new = len(new_papers)
        run.papers_deduplicated = len(deduped)
        run.finished_at = datetime.now(timezone.utc)
        run.status = (
            MonitoringRunStatus.PARTIAL
            if partial_failure
            else MonitoringRunStatus.SUCCESS
        )
        if partial_failure and run.error is None:
            run.error = "one_or_more_papers_failed"

        logger.info(
            "monitor_cycle_complete",
            subscription_id=subscription.subscription_id,
            seen=run.papers_seen,
            new=run.papers_new,
            deduplicated=run.papers_deduplicated,
            status=run.status.value,
        )
        return ArxivMonitorResult(
            run=run,
            new_papers=new_papers,
            deduplicated_papers=deduped,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _monitor_eligible(subscription: ResearchSubscription) -> bool:
        """Return True if the monitor should poll for this subscription."""
        if subscription.status.value != "active":
            return False
        if PaperSource.ARXIV not in subscription.sources:
            return False
        return True

    @staticmethod
    def _build_topic(subscription: ResearchSubscription) -> ResearchTopic:
        """Map a subscription to a ``ResearchTopic`` for the provider.

        ArxivProvider's ``TimeframeRecent`` value pattern is ``\\d+[hd]``,
        with a 720h cap (~30 days) enforced by the model's
        ``validate_recent_format``. We clamp ``poll_interval_hours`` to
        that ceiling to avoid a validation error mid-cycle.
        """
        hours = min(subscription.poll_interval_hours, _MAX_POLL_HOURS)
        timeframe = TimeframeRecent(
            type=TimeframeType.RECENT,
            value=f"{hours}h",
        )
        return ResearchTopic(
            query=subscription.query,
            timeframe=timeframe,
        )

    def _topic_slug(self, subscription: ResearchSubscription) -> str:
        """Derive a topic slug for registry affiliation."""
        # Subscription IDs already match the registry's allowed
        # character class, so we just prefix them. Keep it short to fit
        # in any downstream filename use cases.
        return f"{self._topic_slug_prefix}-{subscription.subscription_id}"

    def _register_new_paper(
        self, paper: PaperMetadata, topic_slug: str
    ) -> RegistryEntry:
        """Register a new paper at discovery-time.

        ``discovery_only=True`` keeps extraction state empty — Week 2's
        relevance scorer / ingestion path will fill it in if the paper
        scores above threshold.
        """
        return self._registry.register_paper(
            paper=paper,
            topic_slug=topic_slug,
            discovery_only=True,
        )

    @staticmethod
    def _to_record(paper: PaperMetadata, is_new: bool) -> MonitoringPaperRecord:
        published: Optional[datetime] = paper.publication_date
        # PaperMetadata uses HttpUrl; MonitoringPaperRecord stores plain
        # strings (it's a serialization-friendly DTO). Cast via str().
        return MonitoringPaperRecord(
            paper_id=paper.paper_id,
            title=paper.title,
            url=str(paper.url) if paper.url else None,
            pdf_url=str(paper.open_access_pdf) if paper.open_access_pdf else None,
            published_at=published,
            is_new=is_new,
        )

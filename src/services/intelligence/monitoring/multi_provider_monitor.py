"""Multi-provider, query-expanded monitor for Phase 9.1 Tier 1.

Drop-in replacement for :class:`ArxivMonitor` that adds two
discovery-broadening capabilities the original monitor lacked:

1. **Query expansion** — uses :class:`QueryExpander` (Phase 7.2) to
   generate semantically-related variants of the subscription's query
   via a cheap Gemini Flash call. The original query is always
   included as the first variant.
2. **Multi-provider fan-out** — searches every configured provider
   (typically arXiv + Semantic Scholar + OpenAlex + HuggingFace), not
   just arXiv. Results are unioned and deduplicated by ``paper_id``
   before identity resolution against the registry.

Failure semantics mirror :class:`ArxivMonitor`:

- A provider raising for one query is logged and skipped (fail-soft
  across independent peers — one S2 timeout doesn't kill the cycle).
- A registry write failure on one paper is logged and the cycle
  continues with the remaining papers, ending in ``PARTIAL`` status.
- Identity resolution failure on one paper is similarly survivable.
- The whole cycle returns a :class:`MonitoringRun` with appropriate
  status — never raises to the caller.

Backward compatibility:

- Returns an :class:`ArxivMonitorResult` (same DTO as the legacy
  monitor) so :class:`MonitoringRunner._run_one` can consume either
  monitor implementation without branching.
- The ``source`` field on the produced :class:`MonitoringRun` remains
  ``PaperSource.ARXIV`` for now — Tier 1 keeps schema compat; a
  future iteration will add per-source provenance tracking.

Note on threshold-based ingestion: this monitor does the *discovery*
half (find candidate papers, register them with ``discovery_only=True``).
The relevance-scoring + threshold-gated full ingestion happens
downstream in :class:`MonitoringRunner._run_one` after this monitor
returns its result.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from src.models.config.core import ResearchTopic, TimeframeRecent, TimeframeType
from src.models.paper import PaperMetadata
from src.services.intelligence.monitoring.arxiv_monitor import (
    _MAX_POLL_HOURS,
    ArxivMonitorResult,
)
from src.services.intelligence.monitoring.models import (
    MAX_PAPERS_PER_CYCLE,
    MonitoringRun,
    MonitoringRunStatus,
    PaperSource,
    ResearchSubscription,
)
from src.services.providers.base import DiscoveryProvider
from src.services.registry import RegistryService

if TYPE_CHECKING:
    from src.utils.query_expander import QueryExpander


__all__ = ["MultiProviderMonitor", "MultiProviderMonitorConfig"]


logger = structlog.get_logger(__name__)


# Default cap on how many query variants the expander returns. The
# original query always counts as the first variant; this is the cap on
# the total result set including the original. Lower than the default
# in QueryExpander (5) because each variant fans out across N providers,
# multiplying the API call count.
_DEFAULT_MAX_QUERY_VARIANTS = 3


class MultiProviderMonitorConfig(BaseModel):
    """Validated knobs for a :class:`MultiProviderMonitor` instance.

    Wrapping the constructor params in a Pydantic model gives us strict
    validation at runtime (catching e.g. negative budget caps) and a
    single point to extend without breaking the constructor signature.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    max_papers_per_cycle: int = MAX_PAPERS_PER_CYCLE
    max_query_variants: int = _DEFAULT_MAX_QUERY_VARIANTS
    topic_slug_prefix: str = "monitor"

    @classmethod
    def with_defaults(cls) -> "MultiProviderMonitorConfig":
        return cls()


class MultiProviderMonitor:
    """Polls multiple discovery providers, optionally with query expansion.

    Args:
        providers: Mapping of :class:`PaperSource` to a configured
            :class:`DiscoveryProvider`. Must contain at least one entry.
            All providers are searched in parallel for every query
            variant; results are unioned and deduplicated by paper_id.
        registry: Shared :class:`RegistryService` used for paper
            identity resolution and discovery-time registration.
        query_expander: Optional :class:`QueryExpander`. When provided,
            the subscription's query is expanded into N variants via
            an LLM call before the provider fan-out. When ``None``, only
            the literal subscription query is searched (no LLM cost).
        config: Knobs (caps, prefix). Defaults via
            :meth:`MultiProviderMonitorConfig.with_defaults`.

    Raises:
        ValueError: If ``providers`` is empty or ``config`` rejects the
            input (e.g., negative cap).
    """

    def __init__(
        self,
        providers: dict[PaperSource, DiscoveryProvider],
        registry: RegistryService,
        *,
        query_expander: Optional["QueryExpander"] = None,
        config: Optional[MultiProviderMonitorConfig] = None,
    ) -> None:
        if not providers:
            raise ValueError(
                "MultiProviderMonitor requires at least one provider "
                "(empty providers dict was passed)"
            )
        self._providers = dict(providers)  # defensive copy
        self._registry = registry
        self._query_expander = query_expander
        self._config = config or MultiProviderMonitorConfig.with_defaults()

    # ------------------------------------------------------------------
    # Public API — same shape as ArxivMonitor.check()
    # ------------------------------------------------------------------
    async def check(self, subscription: ResearchSubscription) -> ArxivMonitorResult:
        """Run one expanded multi-provider monitoring cycle.

        Behavior:

        1. Skip immediately if the subscription is paused. (Per-source
           filtering is NOT applied here — multi-provider monitors
           consult every configured provider regardless of the
           subscription's ``sources`` list, since the whole point of
           Tier 1 is broader discovery. Sources filtering can be
           reintroduced in a follow-up if users want per-subscription
           provider opt-out.)
        2. Expand the query into N variants (or use only the literal
           query if no expander is configured).
        3. For each variant, search every configured provider. Provider
           failures on a single variant are logged and skipped — the
           cycle continues with whatever other providers/variants
           succeed.
        4. Union all returned papers, dedup by ``paper_id``.
        5. Apply the per-cycle paper cap.
        6. For each paper, resolve identity against the registry. New
           papers are registered ``discovery_only=True``; known papers
           are added to the deduped list.
        7. Return :class:`ArxivMonitorResult`. Status is ``PARTIAL`` if
           any provider/registry call surfaced an error during the
           cycle, ``SUCCESS`` otherwise.

        This method never raises — it always returns a result with a
        meaningful :class:`MonitoringRun` status.
        """
        run = MonitoringRun(
            subscription_id=subscription.subscription_id,
            # See Tier 1 schema-compat note in module docstring.
            source=PaperSource.ARXIV,
        )

        if subscription.status.value != "active":
            run.status = MonitoringRunStatus.SUCCESS
            run.finished_at = datetime.now(timezone.utc)
            logger.info(
                "monitor_skipped",
                subscription_id=subscription.subscription_id,
                reason="paused",
            )
            return ArxivMonitorResult(run=run, new_papers=[], deduplicated_papers=[])

        # Step 2: query expansion (or single-query fallback)
        queries = await self._build_query_variants(subscription)
        logger.info(
            "monitor_query_expansion_complete",
            subscription_id=subscription.subscription_id,
            variant_count=len(queries),
            had_expander=self._query_expander is not None,
        )

        # Step 3: fan-out across (variant × provider). One provider+variant
        # failure does NOT abort the cycle — each is independent.
        fetched: list[PaperMetadata] = []
        partial_failure = False
        for variant in queries:
            topic = self._build_topic_for_query(subscription, variant)
            for source, provider in self._providers.items():
                try:
                    results = await provider.search(topic)
                except Exception as exc:
                    partial_failure = True
                    logger.warning(
                        "monitor_provider_search_failed",
                        subscription_id=subscription.subscription_id,
                        source=source.value,
                        query=variant[:120],
                        error=str(exc),
                    )
                    continue
                fetched.extend(results)

        # Step 4: dedup by paper_id (preserving first-seen order so the
        # original-query results land first when relevance scoring caps
        # the per-subscription LLM budget downstream).
        deduped_fetch = self._dedup_by_paper_id(fetched)

        # Step 5: enforce per-cycle paper cap
        if len(deduped_fetch) > self._config.max_papers_per_cycle:
            deduped_fetch = deduped_fetch[: self._config.max_papers_per_cycle]

        run.papers_seen = len(deduped_fetch)

        # Step 6: identity-resolve + register-or-dedup against registry
        new_papers, deduplicated_papers, registry_partial = self._resolve_and_register(
            deduped_fetch, subscription, run
        )
        if registry_partial:
            partial_failure = True

        run.papers_new = len(new_papers)
        run.papers_deduplicated = len(deduplicated_papers)
        run.finished_at = datetime.now(timezone.utc)
        run.status = (
            MonitoringRunStatus.PARTIAL
            if partial_failure
            else MonitoringRunStatus.SUCCESS
        )
        if partial_failure and run.error is None:
            run.error = "one_or_more_providers_or_papers_failed"

        logger.info(
            "monitor_cycle_complete",
            subscription_id=subscription.subscription_id,
            seen=run.papers_seen,
            new=run.papers_new,
            deduplicated=run.papers_deduplicated,
            status=run.status.value,
            variants_searched=len(queries),
            providers_searched=len(self._providers),
        )
        return ArxivMonitorResult(
            run=run,
            new_papers=new_papers,
            deduplicated_papers=deduplicated_papers,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _build_query_variants(
        self, subscription: ResearchSubscription
    ) -> list[str]:
        """Expand the subscription's query if an expander is configured.

        Always returns a non-empty list — at minimum, the literal query.
        Expander failures are caught and logged; the literal query is
        used as a fail-soft fallback (matching ``QueryExpander.expand``'s
        own contract — see ``src/utils/query_expander.py:88``).
        """
        if self._query_expander is None:
            return [subscription.query]

        try:
            variants = await self._query_expander.expand(
                subscription.query,
                max_variants=self._config.max_query_variants - 1,
            )
        except Exception as exc:
            logger.warning(
                "monitor_query_expansion_failed",
                subscription_id=subscription.subscription_id,
                error=str(exc),
            )
            return [subscription.query]

        # Defensive: if the expander returned nothing usable, fall back
        # to the literal query so we never search with an empty list.
        if not variants:
            return [subscription.query]
        return variants

    def _build_topic_for_query(
        self, subscription: ResearchSubscription, query: str
    ) -> ResearchTopic:
        """Construct a :class:`ResearchTopic` for one query variant."""
        hours = min(subscription.poll_interval_hours, _MAX_POLL_HOURS)
        timeframe = TimeframeRecent(
            type=TimeframeType.RECENT,
            value=f"{hours}h",
        )
        return ResearchTopic(query=query, timeframe=timeframe)

    @staticmethod
    def _dedup_by_paper_id(papers: list[PaperMetadata]) -> list[PaperMetadata]:
        """Dedup a list of papers by ``paper_id`` while preserving order."""
        seen: set[str] = set()
        result: list[PaperMetadata] = []
        for paper in papers:
            if paper.paper_id in seen:
                continue
            seen.add(paper.paper_id)
            result.append(paper)
        return result

    def _resolve_and_register(
        self,
        papers: list[PaperMetadata],
        subscription: ResearchSubscription,
        run: MonitoringRun,
    ) -> tuple[list[PaperMetadata], list[PaperMetadata], bool]:
        """Resolve identity + register new papers; return (new, dup, partial).

        Mirrors :class:`ArxivMonitor`'s post-fetch logic but pulled out
        as a pure helper that mutates ``run.papers``. ``partial`` is
        True if any single paper triggered a registry / identity error
        — those are individually survivable but flag the overall cycle
        as PARTIAL.
        """
        from src.services.intelligence.monitoring.arxiv_monitor import ArxivMonitor

        new_papers: list[PaperMetadata] = []
        deduped: list[PaperMetadata] = []
        partial_failure = False
        topic_slug = f"{self._config.topic_slug_prefix}-{subscription.subscription_id}"

        for paper in papers:
            try:
                match = self._registry.resolve_identity(paper)
            except Exception as exc:
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
                run.papers.append(ArxivMonitor._to_record(paper, is_new=False))
                continue

            try:
                self._registry.register_paper(
                    paper=paper,
                    topic_slug=topic_slug,
                    discovery_only=True,
                )
            except Exception as exc:
                partial_failure = True
                logger.warning(
                    "monitor_registry_write_error",
                    subscription_id=subscription.subscription_id,
                    paper_id=paper.paper_id,
                    error=str(exc),
                )
                continue

            new_papers.append(paper)
            run.papers.append(ArxivMonitor._to_record(paper, is_new=True))

        return new_papers, deduped, partial_failure

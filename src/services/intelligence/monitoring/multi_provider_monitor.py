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
- The cycle-level ``source`` field on the produced :class:`MonitoringRun`
  remains ``PaperSource.ARXIV`` for backward compatibility — its
  semantics are now "primary / first-seen source" rather than "all
  sources". Per-paper provenance (issue #141) lives on each
  :class:`~MonitoringPaperRecord`'s ``source`` field which is the
  authoritative record of where each paper actually came from.

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
from pydantic import BaseModel, ConfigDict, Field

from src.models.config.core import ResearchTopic
from src.models.paper import PaperMetadata
from src.services.intelligence.monitoring._paper_records import (
    build_topic,
    to_paper_record,
)
from src.services.intelligence.monitoring.arxiv_monitor import ArxivMonitorResult
from src.services.intelligence.monitoring.models import (
    MAX_PAPERS_PER_CYCLE,
    MonitoringRun,
    MonitoringRunStatus,
    PaperSource,
    ResearchSubscription,
    SubscriptionStatus,
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

    H-M1: all numeric fields carry Pydantic ``Field(ge=..., le=...)``
    bounds so illegal values are caught at construction time rather than
    producing silent misuse at runtime.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    max_papers_per_cycle: int = Field(
        default=MAX_PAPERS_PER_CYCLE,
        ge=1,
        le=MAX_PAPERS_PER_CYCLE,
        description="Hard cap on papers processed per cycle.",
    )
    max_query_variants: int = Field(
        default=_DEFAULT_MAX_QUERY_VARIANTS,
        ge=1,
        le=10,
        description="Maximum number of query variants including the original.",
    )
    topic_slug_prefix: str = Field(
        default="monitor",
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Prefix used when affiliating monitored papers in the registry.",
    )


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
        config: Knobs (caps, prefix). Defaults to
            ``MultiProviderMonitorConfig()`` (all fields at their
            default values).

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
        self._config = config or MultiProviderMonitorConfig()

    # ------------------------------------------------------------------
    # Public API — same shape as ArxivMonitor.check()
    # ------------------------------------------------------------------
    async def check(
        self,
        subscription: ResearchSubscription,
        *,
        llm_calls_used: Optional[list[int]] = None,
        max_calls: Optional[int] = None,
    ) -> ArxivMonitorResult:
        """Run one expanded multi-provider monitoring cycle.

        Behavior:

        1. Skip immediately if the subscription is paused. Per-source
           filtering IS applied (H-S3): providers not in the
           subscription's ``sources`` allowlist are skipped so each
           subscription can opt out of specific providers.
        2. Expand the query into N variants (or use only the literal
           query if no expander is configured). H-S1: the expander call
           is gated against the ``llm_calls_used`` / ``max_calls``
           budget so the monitor cannot bypass ``MonitoringRunner``'s
           ``MAX_LLM_CALLS_PER_CYCLE`` cap.
        3. For each variant, search every provider the subscription has
           allowlisted. Provider failures on a single variant are logged
           and skipped — the cycle continues with whatever other
           providers/variants succeed.
           H-S5: ``_build_topic_for_query`` is called inside the
           per-provider try/except so a Pydantic validation failure on
           a bad variant does not abort the whole subscription cycle.
        4. Union all returned papers, dedup by ``paper_id``.
        5. Apply the per-cycle paper cap.
        6. For each paper, resolve identity against the registry. New
           papers are registered ``discovery_only=True``; known papers
           are added to the deduped list.
        7. Return :class:`ArxivMonitorResult`. Status is ``PARTIAL`` if
           any provider/registry call surfaced an error during the
           cycle, ``SUCCESS`` otherwise.

        Args:
            subscription: The subscription to check.
            llm_calls_used: Optional mutable single-element list acting
                as a shared counter for LLM calls consumed this cycle.
                When ``None``, budget enforcement is skipped (direct
                callers and tests that don't need the cap).
            max_calls: Maximum allowed LLM calls. Checked against
                ``llm_calls_used[0]`` before the expander is invoked.
                Ignored when ``llm_calls_used`` is ``None``.

        This method never raises — it always returns a result with a
        meaningful :class:`MonitoringRun` status.
        """
        run = MonitoringRun(
            subscription_id=subscription.subscription_id,
            # Cycle-level source is kept as ARXIV for backward
            # compatibility with the V1-V4 schema; per-paper provenance
            # (issue #141, V5) lives on each MonitoringPaperRecord.source
            # which is now the authoritative attribution.
            source=PaperSource.ARXIV,
        )

        if subscription.status is not SubscriptionStatus.ACTIVE:
            run.status = MonitoringRunStatus.SUCCESS
            run.finished_at = datetime.now(timezone.utc)
            logger.info(
                "monitor_skipped",
                subscription_id=subscription.subscription_id,
                reason="paused",
            )
            return ArxivMonitorResult(run=run, new_papers=[], deduplicated_papers=[])

        # Step 2: query expansion (or single-query fallback).
        # H-S1: pass budget counters so the expander call is gated.
        queries, expansion_degraded = await self._build_query_variants(
            subscription, llm_calls_used=llm_calls_used, max_calls=max_calls
        )
        logger.info(
            "monitor_query_expansion_complete",
            subscription_id=subscription.subscription_id,
            variant_count=len(queries),
            had_expander=self._query_expander is not None,
        )

        # Step 3: fan-out across (variant × provider). One provider+variant
        # failure does NOT abort the cycle — each is independent.
        # H-S3: Only search providers the subscription's allowlist permits.
        #
        # L-7: The nested loop is sequential by design. Fan-out is IO-bound
        # (arXiv, S2, OpenAlex each have their own rate limits), and the
        # provider SDKs are not guaranteed thread-safe. Async gather across
        # providers would also complicate partial-failure accounting without
        # meaningful latency gains at small provider counts (≤4). Change
        # only after profiling confirms fan-out latency is the bottleneck.
        # ``fetched`` carries (paper, source) tuples so each paper retains
        # the provenance of the provider it actually came from (issue #141).
        # When the same paper_id appears from two providers, the dedup
        # step below preserves the first-seen entry — including its
        # source — to keep behavior deterministic.
        fetched: list[tuple[PaperMetadata, PaperSource]] = []
        partial_failure = expansion_degraded  # H-C5: expander degradation → PARTIAL
        for variant in queries:
            for source, provider in self._providers.items():
                if source not in subscription.sources:
                    continue
                try:
                    # H-S5: build topic INSIDE try/except so a Pydantic
                    # validation error on a bad variant (e.g., containing
                    # characters rejected by ResearchTopic) does not abort
                    # the whole cycle — it's treated as a provider failure.
                    topic = self._build_topic_for_query(subscription, variant)
                    results = await provider.search(topic)
                except Exception as exc:
                    partial_failure = True
                    logger.warning(
                        "monitor_provider_search_failed",
                        subscription_id=subscription.subscription_id,
                        source=source.value,
                        query=variant[:120],
                        error=repr(str(exc)[:512]),
                    )
                    continue
                for paper in results:
                    fetched.append((paper, source))

        # Step 4: dedup by paper_id (preserving first-seen order so the
        # original-query results land first when relevance scoring caps
        # the per-subscription LLM budget downstream).
        deduped_fetch = self._dedup_by_paper_id(fetched)

        # Step 5: enforce per-cycle paper cap
        if len(deduped_fetch) > self._config.max_papers_per_cycle:
            logger.info(
                "monitor_per_cycle_cap_applied",
                subscription_id=subscription.subscription_id,
                papers_before_cap=len(deduped_fetch),
                cap=self._config.max_papers_per_cycle,
            )
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
        self,
        subscription: ResearchSubscription,
        *,
        llm_calls_used: Optional[list[int]] = None,
        max_calls: Optional[int] = None,
    ) -> tuple[list[str], bool]:
        """Expand the subscription's query if an expander is configured.

        Always returns ``(variants, degraded)`` where ``variants`` is a
        non-empty list (at minimum, the literal query) and ``degraded``
        is ``True`` when the expander was skipped, failed, or produced
        only invalid variants — so the caller can mark the run PARTIAL.

        H-S1 — Budget gate:
            If ``llm_calls_used`` and ``max_calls`` are both provided and
            ``llm_calls_used[0] >= max_calls``, the expander call is
            skipped entirely and ``monitor_expansion_budget_exhausted``
            is logged. ``degraded=True`` is returned so the run is PARTIAL.
            On successful expansion, ``llm_calls_used[0]`` is incremented
            by 1 to account for the expander's LLM call.

        H-S2 — Variant validation:
            Each variant is passed through
            ``InputValidation.validate_query``. Invalid variants are
            dropped with a ``monitor_expansion_variant_rejected`` log
            event. If all variants are rejected, the literal query is
            used as a fallback.

        ``max_query_variants`` is the final cap on the total result set
        including the original query. The expander is asked for that many
        variants; the result is clipped locally afterwards to enforce the
        cap regardless of what the expander returns.
        """
        if self._query_expander is None:
            return [subscription.query], False

        # H-S1: Budget guard — skip expander when the cycle's LLM budget
        # is already exhausted. Use ``degraded=True`` so the caller marks
        # the run PARTIAL and ops can grep for the audit event.
        if (
            llm_calls_used is not None
            and max_calls is not None
            and llm_calls_used[0] >= max_calls
        ):
            logger.warning(
                "monitor_expansion_budget_exhausted",
                subscription_id=subscription.subscription_id,
                max_calls=max_calls,
                calls_used=llm_calls_used[0],
            )
            return [subscription.query], True

        try:
            variants = await self._query_expander.expand(
                subscription.query,
                max_variants=self._config.max_query_variants,
            )
        except Exception as exc:
            logger.warning(
                "monitor_query_expansion_failed",
                subscription_id=subscription.subscription_id,
                error=repr(str(exc)[:512]),
            )
            return [subscription.query], True

        # H-S1: Increment budget counter on successful expander call.
        if llm_calls_used is not None:
            llm_calls_used[0] += 1

        # Defensive: if the expander returned nothing usable, fall back
        # to the literal query so we never search with an empty list.
        if not variants:
            return [subscription.query], True

        # Clip to the configured cap so callers are never surprised by an
        # oversized variant list even if the expander ignores max_variants.
        clipped = variants[: self._config.max_query_variants]

        # H-S2: Validate each variant through InputValidation to drop any
        # LLM-produced strings that contain injection-risk characters.
        from src.utils.security import InputValidation

        validated: list[str] = []
        for variant in clipped:
            try:
                InputValidation.validate_query(variant)
                validated.append(variant)
            except Exception:
                logger.warning(
                    "monitor_expansion_variant_rejected",
                    subscription_id=subscription.subscription_id,
                    variant=variant[:120],
                )

        if not validated:
            # All variants were rejected — fall back to the literal query.
            return [subscription.query], True

        return validated, False

    def _build_topic_for_query(
        self, subscription: ResearchSubscription, query: str
    ) -> ResearchTopic:
        """Construct a :class:`ResearchTopic` for one query variant.

        Delegates to the shared :func:`build_topic` helper (H-C3) so
        the look-back-window clamping logic lives in one place.
        """
        return build_topic(query, subscription.poll_interval_hours)

    @staticmethod
    def _dedup_by_paper_id(
        papers: list[tuple[PaperMetadata, PaperSource]],
    ) -> list[tuple[PaperMetadata, PaperSource]]:
        """Dedup ``(paper, source)`` tuples by ``paper_id``, preserving order.

        First-seen wins — both the paper metadata AND its source come
        from the earliest occurrence (issue #141). If arXiv and OpenAlex
        both return the same paper and the iteration visited arXiv
        first, the audit row records ``source=ARXIV``.
        """
        seen: set[str] = set()
        result: list[tuple[PaperMetadata, PaperSource]] = []
        for paper, source in papers:
            if paper.paper_id in seen:
                continue
            seen.add(paper.paper_id)
            result.append((paper, source))
        return result

    def _resolve_and_register(
        self,
        papers: list[tuple[PaperMetadata, PaperSource]],
        subscription: ResearchSubscription,
        run: MonitoringRun,
    ) -> tuple[list[PaperMetadata], list[PaperMetadata], bool]:
        """Resolve identity + register new papers; return (new, dup, partial).

        Mirrors :class:`ArxivMonitor`'s post-fetch logic but pulled out
        as a pure helper that mutates ``run.papers``. ``partial`` is
        True if any single paper triggered a registry / identity error
        — those are individually survivable but flag the overall cycle
        as PARTIAL.

        Issue #141: each :class:`MonitoringPaperRecord` appended to
        ``run.papers`` carries the actual discovery provider via the
        ``source=`` argument threaded through ``to_paper_record``.
        """
        new_papers: list[PaperMetadata] = []
        deduped: list[PaperMetadata] = []
        partial_failure = False
        topic_slug = f"{self._config.topic_slug_prefix}-{subscription.subscription_id}"

        for paper, source in papers:
            try:
                match = self._registry.resolve_identity(paper)
            except Exception as exc:
                partial_failure = True
                logger.warning(
                    "monitor_identity_resolution_error",
                    subscription_id=subscription.subscription_id,
                    paper_id=paper.paper_id,
                    source=source.value,
                    error=repr(str(exc)[:512]),
                )
                continue

            if match.matched:
                deduped.append(paper)
                run.papers.append(to_paper_record(paper, is_new=False, source=source))
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
                    source=source.value,
                    error=repr(str(exc)[:512]),
                )
                continue

            new_papers.append(paper)
            run.papers.append(to_paper_record(paper, is_new=True, source=source))

        return new_papers, deduped, partial_failure

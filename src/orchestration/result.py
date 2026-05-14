"""Pipeline result data structure.

Phase 5.2: Extracted from research_pipeline.py.
Phase 7.1: Added discovery statistics support.
Phase 9.5: Added abstract-fallback SLO tracking (REQ-9.5.1.4).
Phase 9.5 PR γ: Centralised SLO emission helpers (REQ-9.5.1.4 + REQ-9.5.2.4).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from src.models.cross_synthesis import CrossTopicSynthesisReport
from src.models.discovery import DiscoveryStats

_logger = structlog.get_logger()

# Phase 9.5 REQ-9.5.1.4: SLO threshold for abstract-only fallback rate.
# Daily-run rate exceeding this signals the pipeline is producing
# degraded output (abstract-only briefs instead of full PDF extractions).
ABSTRACT_FALLBACK_RATE_SLO_PCT: float = 20.0

# Phase 9.5 REQ-9.5.2.4: per-run SLO floor for citation breadth.
#
# Spec text: "Citation-expansion contribution SHALL be ≥ 20 net-new
# papers per run averaged over 7 days, once enabled."
#
# Interpretation (PR β): the spec target is *averaged* — typical run
# volume for the project is ~100 discovered papers per run × 8 topics
# = ~800 candidates pre-dedup, of which ~80-200 reach the post-dedup
# pool. 20 net-new from citations against that denominator is roughly
# 10-25% by rate. We pick 15% as the per-run floor: above the
# pessimistic end of the absolute target's implied rate (10%, when
# typical run is 200 candidates) and below the optimistic end (25%,
# when typical run is 80 candidates). That gives the rolling 7-day
# average headroom to clear "≥ 20 net-new per run" even on an
# off-day. A single per-run rate dipping below this floor is *not*
# itself an SLO breach — ops aggregates over 7 days — but it is the
# distinct, greppable signal that citation expansion is not
# contributing as expected (typically: registry has too few
# qualifying seeds in the first week post-activation, or Semantic
# Scholar is rate-limiting the citation walk).
#
# Reviewer note: the rate vs. absolute interpretation of the spec was
# explicitly flagged in the PR β self-review and accepted as a
# judgment call appropriate for an SLO building-block emitted per
# run. If a future reviewer prefers the absolute interpretation, swap
# `breadth_metric_within_slo` to check `papers_from_citations >= 20`
# directly instead of (or in addition to) the rate threshold.
BREADTH_METRIC_SLO_MIN_PCT: float = 15.0


@dataclass
class PipelineResult:
    """Result of a pipeline run.

    Aggregates statistics and output from all pipeline phases.

    Phase 7.1: Added discovery_stats for observability.
    Phase 9.5: Added papers_with_pdf / papers_with_abstract_fallback so
    the daily-run job can compute and emit the abstract-fallback SLO
    rate (REQ-9.5.1.4).
    """

    topics_processed: int = 0
    topics_failed: int = 0
    papers_discovered: int = 0
    papers_processed: int = 0
    papers_with_extraction: int = 0
    # Phase 9.5 REQ-9.5.1.4: provenance counts for SLO computation.
    # papers_with_pdf counts ExtractedPaper instances whose pdf_available
    # is True (full-text extraction path); papers_with_abstract_fallback
    # counts those whose extraction succeeded but used abstract-only
    # markdown because the PDF was unavailable, download failed, or
    # backend extraction failed. Together they sum to papers_with_extraction
    # under normal operation; if they don't, papers_processed includes
    # papers that produced no extraction at all (and are not part of the
    # SLO denominator).
    papers_with_pdf: int = 0
    papers_with_abstract_fallback: int = 0
    # Phase 9.5 REQ-9.5.2.4: breadth metric provenance counts.
    # papers_from_providers is the number of post-dedup papers whose
    # discovery_source is a provider name ("arxiv", "semantic_scholar",
    # "huggingface", ...); papers_from_citations counts those whose
    # source is the citation walk ("citation_expansion" / values like
    # "forward_citations" / "backward_citations" in the source breakdown
    # dict). source_breakdown carries the per-source totals so the SLO
    # event payload can publish it without re-aggregating.
    papers_from_providers: int = 0
    papers_from_citations: int = 0
    source_breakdown: Dict[str, int] = field(default_factory=dict)
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0
    output_files: List[str] = field(default_factory=list)
    errors: List[Dict[str, str]] = field(default_factory=list)
    # Phase 3.7: Cross-topic synthesis report
    cross_synthesis_report: Optional[CrossTopicSynthesisReport] = None
    # Phase 7.1: Discovery statistics (aggregated across all topics)
    discovery_stats: Optional[DiscoveryStats] = None

    @property
    def abstract_fallback_rate_pct(self) -> float:
        """Phase 9.5 REQ-9.5.1.4 — abstract-fallback rate as a percentage.

        Computed as ``papers_with_abstract_fallback / papers_with_extraction
        * 100``. Returns 0.0 when no extractions ran (denominator zero is
        not informative — there is no SLO violation when nothing was
        attempted).

        SLO target: <= ``ABSTRACT_FALLBACK_RATE_SLO_PCT`` (20%) on a
        7-day rolling window. Per-run rate is the building block ops
        aggregates over the window.
        """
        if self.papers_with_extraction <= 0:
            return 0.0
        return round(
            self.papers_with_abstract_fallback / self.papers_with_extraction * 100.0,
            2,
        )

    @property
    def abstract_fallback_within_slo(self) -> bool:
        """Phase 9.5 REQ-9.5.1.4 — convenience guard for SLO compliance.

        True when this single run's rate is within budget, False when it
        exceeds the threshold. Note that the SLO is defined on a rolling
        7-day window (per spec §3.1 REQ-9.5.1.4); a single run breaching
        the threshold does NOT necessarily mean the SLO is breached, but
        does warrant attention.
        """
        return self.abstract_fallback_rate_pct <= ABSTRACT_FALLBACK_RATE_SLO_PCT

    @property
    def breadth_metric_rate_pct(self) -> float:
        """Phase 9.5 REQ-9.5.2.4 — citation contribution rate (percent).

        Computed as ``papers_from_citations / papers_discovered * 100``.
        Returns 0.0 when no papers were discovered — there is no SLO
        violation when nothing was attempted (mirrors the
        abstract-fallback convention for the empty-denominator case).

        SLO floor: ``BREADTH_METRIC_SLO_MIN_PCT`` (15%) on the 7-day
        rolling window. The per-run rate is the building block ops
        aggregates.
        """
        if self.papers_discovered <= 0:
            return 0.0
        return round(
            self.papers_from_citations / self.papers_discovered * 100.0,
            2,
        )

    @property
    def breadth_metric_within_slo(self) -> bool:
        """Phase 9.5 REQ-9.5.2.4 — convenience guard for breadth SLO.

        True when the per-run rate meets or exceeds the floor, False
        when citation expansion under-contributed. As with the
        abstract-fallback SLO, the per-run signal is a building block
        of the 7-day rolling SLO, not a hard gate.
        """
        # Zero-denominator case (no papers discovered): treat as
        # within-SLO. There is nothing to broaden if nothing was found.
        if self.papers_discovered <= 0:
            return True
        return self.breadth_metric_rate_pct >= BREADTH_METRIC_SLO_MIN_PCT

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization.

        Phase 7.1: Added discovery_stats to output.
        Phase 9.5: Added papers_with_pdf / papers_with_abstract_fallback /
        abstract_fallback_rate_pct (REQ-9.5.1.4) and
        papers_from_providers / papers_from_citations /
        breadth_metric_rate_pct / source_breakdown (REQ-9.5.2.4).
        """
        result = {
            "topics_processed": self.topics_processed,
            "topics_failed": self.topics_failed,
            "papers_discovered": self.papers_discovered,
            "papers_processed": self.papers_processed,
            "papers_with_extraction": self.papers_with_extraction,
            "papers_with_pdf": self.papers_with_pdf,
            "papers_with_abstract_fallback": self.papers_with_abstract_fallback,
            "abstract_fallback_rate_pct": self.abstract_fallback_rate_pct,
            "papers_from_providers": self.papers_from_providers,
            "papers_from_citations": self.papers_from_citations,
            "source_breakdown": dict(self.source_breakdown),
            "breadth_metric_rate_pct": self.breadth_metric_rate_pct,
            "total_tokens_used": self.total_tokens_used,
            "total_cost_usd": self.total_cost_usd,
            "output_files": self.output_files,
            "errors": self.errors,
        }
        # Include cross-synthesis info if available
        if self.cross_synthesis_report:
            result["cross_synthesis"] = {
                "questions_answered": self.cross_synthesis_report.questions_answered,
                "synthesis_cost_usd": self.cross_synthesis_report.total_cost_usd,
                "synthesis_tokens": self.cross_synthesis_report.total_tokens_used,
            }
        # Include discovery stats if available (Phase 7.1)
        if self.discovery_stats:
            result["discovery_stats"] = {
                "total_discovered": self.discovery_stats.total_discovered,
                "new_count": self.discovery_stats.new_count,
                "filtered_count": self.discovery_stats.filtered_count,
                "filter_breakdown": self.discovery_stats.filter_breakdown,
                "incremental_query": self.discovery_stats.incremental_query,
            }
        return result

    def merge_topic_result(self, topic_result: Dict[str, Any]) -> None:
        """Merge topic result into pipeline result.

        Args:
            topic_result: Topic processing result dictionary
        """
        if topic_result.get("success", False):
            self.topics_processed += 1
        else:
            self.topics_failed += 1
            error_msg = topic_result.get("error")
            if error_msg:
                topic_name = topic_result.get("topic", "unknown")
                self.errors.append({"topic": topic_name, "error": error_msg})

        self.papers_discovered += topic_result.get("papers_discovered", 0)
        self.papers_processed += topic_result.get("papers_processed", 0)
        self.papers_with_extraction += topic_result.get("papers_with_extraction", 0)
        # Phase 9.5 REQ-9.5.1.4: aggregate per-topic provenance counts.
        self.papers_with_pdf += topic_result.get("papers_with_pdf", 0)
        self.papers_with_abstract_fallback += topic_result.get(
            "papers_with_abstract_fallback", 0
        )
        self.total_tokens_used += topic_result.get("tokens_used", 0)
        self.total_cost_usd += topic_result.get("cost_usd", 0.0)

        output_file = topic_result.get("output_file")
        if output_file:
            self.output_files.append(output_file)


def emit_pipeline_health_slo_events(result: PipelineResult) -> None:
    """Emit the Phase 9.5 SLO observability events for ``result``.

    Centralised emission helper called from
    :meth:`src.orchestration.pipeline.ResearchPipeline.run` so the
    events fire regardless of pipeline entry point — the production
    daily cron invokes ``python -m src.cli run`` (which goes through
    ``ResearchPipeline.run`` directly), bypassing
    ``src.scheduling.jobs.DailyResearchJob.run``. Putting emission
    here closes the gap PRs #157 and #159 had where the events were
    only fired from the scheduler entry point and were therefore
    dead code in production.

    Emits two events:

    - ``pipeline_health_abstract_fallback_rate`` (REQ-9.5.1.4) —
      per-run building block of the 7-day rolling SLO for "what
      fraction of papers fell back to abstract-only extraction".
    - ``pipeline_health_breadth_metric`` (REQ-9.5.2.4) — per-run
      building block of the 7-day rolling SLO for "what fraction of
      discovered papers came from citation expansion".

    Side-effect-free with respect to ``result``: this is observability
    only; the function does not mutate the result or raise.
    """
    _logger.info(
        "pipeline_health_abstract_fallback_rate",
        rate_pct=result.abstract_fallback_rate_pct,
        papers_with_extraction=result.papers_with_extraction,
        papers_with_pdf=result.papers_with_pdf,
        papers_with_abstract_fallback=result.papers_with_abstract_fallback,
        slo_target_pct=ABSTRACT_FALLBACK_RATE_SLO_PCT,
        within_slo=result.abstract_fallback_within_slo,
    )
    _logger.info(
        "pipeline_health_breadth_metric",
        rate_pct=result.breadth_metric_rate_pct,
        papers_discovered=result.papers_discovered,
        papers_from_providers=result.papers_from_providers,
        papers_from_citations=result.papers_from_citations,
        source_breakdown=dict(result.source_breakdown),
        slo_target_pct=BREADTH_METRIC_SLO_MIN_PCT,
        within_slo=result.breadth_metric_within_slo,
    )

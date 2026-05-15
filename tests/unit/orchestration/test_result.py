"""Tests for PipelineResult.

Phase 7.1: Added discovery_stats tests.
"""

from unittest.mock import MagicMock

from src.models.discovery import DiscoveryStats
from src.orchestration.result import PipelineResult


class TestPipelineResult:
    """Tests for PipelineResult."""

    def test_default_values(self):
        """Test default values."""
        result = PipelineResult()
        assert result.topics_processed == 0
        assert result.topics_failed == 0
        assert result.papers_discovered == 0
        assert result.papers_processed == 0
        assert result.papers_with_extraction == 0
        assert result.total_tokens_used == 0
        assert result.total_cost_usd == 0.0
        assert result.output_files == []
        assert result.errors == []
        assert result.cross_synthesis_report is None

    def test_custom_values(self):
        """Test with custom values."""
        result = PipelineResult(
            topics_processed=5,
            topics_failed=1,
            papers_discovered=100,
            papers_processed=80,
            papers_with_extraction=70,
            total_tokens_used=50000,
            total_cost_usd=1.50,
            output_files=["file1.md", "file2.md"],
            errors=[{"phase": "test", "error": "test error"}],
        )
        assert result.topics_processed == 5
        assert result.topics_failed == 1
        assert result.papers_discovered == 100
        assert result.papers_processed == 80
        assert result.papers_with_extraction == 70
        assert result.total_tokens_used == 50000
        assert result.total_cost_usd == 1.50
        assert len(result.output_files) == 2
        assert len(result.errors) == 1

    def test_to_dict_basic(self):
        """Test to_dict without cross_synthesis."""
        result = PipelineResult(
            topics_processed=2,
            papers_discovered=10,
        )
        d = result.to_dict()
        assert d["topics_processed"] == 2
        assert d["papers_discovered"] == 10
        assert "cross_synthesis" not in d

    def test_to_dict_with_cross_synthesis(self):
        """Test to_dict with cross_synthesis report."""
        report = MagicMock()
        report.questions_answered = 5
        report.total_cost_usd = 0.25
        report.total_tokens_used = 1000
        report.results = []

        result = PipelineResult(
            topics_processed=2,
            cross_synthesis_report=report,
        )
        d = result.to_dict()
        assert "cross_synthesis" in d
        assert d["cross_synthesis"]["questions_answered"] == 5
        assert d["cross_synthesis"]["synthesis_cost_usd"] == 0.25
        assert d["cross_synthesis"]["synthesis_tokens"] == 1000

    def test_to_dict_all_fields(self):
        """Test to_dict includes all fields."""
        result = PipelineResult(
            topics_processed=3,
            topics_failed=1,
            papers_discovered=50,
            papers_processed=40,
            papers_with_extraction=35,
            total_tokens_used=10000,
            total_cost_usd=0.50,
            output_files=["a.md"],
            errors=[{"phase": "x", "error": "y"}],
        )
        d = result.to_dict()
        assert "topics_processed" in d
        assert "topics_failed" in d
        assert "papers_discovered" in d
        assert "papers_processed" in d
        assert "papers_with_extraction" in d
        assert "total_tokens_used" in d
        assert "total_cost_usd" in d
        assert "output_files" in d
        assert "errors" in d

    def test_merge_topic_result_success(self):
        """Test merge_topic_result with successful topic."""
        result = PipelineResult()
        topic_result = {
            "success": True,
            "topic": "test-topic",
            "papers_discovered": 10,
            "papers_processed": 8,
            "papers_with_extraction": 6,
            "tokens_used": 1000,
            "cost_usd": 0.05,
            "output_file": "test.md",
        }

        result.merge_topic_result(topic_result)

        assert result.topics_processed == 1
        assert result.topics_failed == 0
        assert result.papers_discovered == 10
        assert result.papers_processed == 8
        assert result.papers_with_extraction == 6
        assert result.total_tokens_used == 1000
        assert result.total_cost_usd == 0.05
        assert "test.md" in result.output_files

    def test_merge_topic_result_failure(self):
        """Test merge_topic_result with failed topic."""
        result = PipelineResult()
        topic_result = {
            "success": False,
            "topic": "test-topic",
            "papers_discovered": 0,
            "papers_processed": 0,
            "papers_with_extraction": 0,
            "tokens_used": 0,
            "cost_usd": 0.0,
            "output_file": None,
            "error": "Test error",
        }

        result.merge_topic_result(topic_result)

        assert result.topics_processed == 0
        assert result.topics_failed == 1
        assert len(result.errors) == 1

    def test_merge_topic_result_multiple(self):
        """Test merging multiple topic results."""
        result = PipelineResult()

        result.merge_topic_result(
            {
                "success": True,
                "topic": "topic1",
                "papers_discovered": 10,
                "papers_processed": 8,
                "papers_with_extraction": 6,
                "tokens_used": 1000,
                "cost_usd": 0.05,
                "output_file": "file1.md",
            }
        )

        result.merge_topic_result(
            {
                "success": True,
                "topic": "topic2",
                "papers_discovered": 5,
                "papers_processed": 4,
                "papers_with_extraction": 3,
                "tokens_used": 500,
                "cost_usd": 0.03,
                "output_file": "file2.md",
            }
        )

        assert result.topics_processed == 2
        assert result.papers_discovered == 15
        assert result.papers_processed == 12
        assert result.total_tokens_used == 1500
        assert result.total_cost_usd == 0.08
        assert len(result.output_files) == 2

    def test_merge_topic_result_no_output_file(self):
        """Test merge_topic_result when output_file is None."""
        result = PipelineResult()
        topic_result = {
            "success": True,
            "topic": "test-topic",
            "papers_discovered": 0,
            "papers_processed": 0,
            "papers_with_extraction": 0,
            "tokens_used": 0,
            "cost_usd": 0.0,
            "output_file": None,
        }

        result.merge_topic_result(topic_result)

        assert len(result.output_files) == 0

    def test_with_discovery_stats(self):
        """Test PipelineResult with discovery stats (Phase 7.1)."""
        stats = DiscoveryStats(
            total_discovered=25,
            new_count=18,
            filtered_count=7,
            filter_breakdown={"doi": 5, "arxiv": 2},
            incremental_query=True,
        )

        result = PipelineResult(
            topics_processed=1,
            papers_discovered=18,
            discovery_stats=stats,
        )

        assert result.discovery_stats == stats
        assert result.discovery_stats.total_discovered == 25
        assert result.discovery_stats.new_count == 18
        assert result.discovery_stats.filtered_count == 7

    def test_to_dict_with_discovery_stats(self):
        """Test to_dict includes discovery stats (Phase 7.1)."""
        stats = DiscoveryStats(
            total_discovered=25,
            new_count=18,
            filtered_count=7,
            filter_breakdown={"doi": 5, "arxiv": 2},
            incremental_query=True,
        )

        result = PipelineResult(
            topics_processed=1,
            papers_discovered=18,
            discovery_stats=stats,
        )

        d = result.to_dict()

        assert "discovery_stats" in d
        assert d["discovery_stats"]["total_discovered"] == 25
        assert d["discovery_stats"]["new_count"] == 18
        assert d["discovery_stats"]["filtered_count"] == 7
        assert d["discovery_stats"]["filter_breakdown"] == {"doi": 5, "arxiv": 2}
        assert d["discovery_stats"]["incremental_query"] is True

    def test_to_dict_without_discovery_stats(self):
        """Test to_dict when discovery_stats is None."""
        result = PipelineResult(topics_processed=1)

        d = result.to_dict()

        assert "discovery_stats" not in d


class TestAbstractFallbackSLO:
    """Phase 9.5 REQ-9.5.1.4 — abstract-fallback rate computation.

    The rate is the per-run building block of a 7-day rolling SLO. The
    spec defines: rate = papers_with_abstract_fallback /
    papers_with_extraction (zero when denominator is zero, no SLO breach
    when nothing was attempted).
    """

    def test_rate_zero_when_no_extractions_attempted(self):
        """No extractions → rate is 0.0 (not NaN/division-by-zero).

        The SLO does not signal a breach when the pipeline made no
        attempt at all (e.g., all topics failed at discovery).
        """
        result = PipelineResult(papers_with_extraction=0)
        assert result.abstract_fallback_rate_pct == 0.0
        assert result.abstract_fallback_within_slo is True

    def test_rate_zero_when_all_pdf_extractions(self):
        """All PDF extractions → 0% fallback rate."""
        result = PipelineResult(
            papers_with_extraction=10,
            papers_with_pdf=10,
            papers_with_abstract_fallback=0,
        )
        assert result.abstract_fallback_rate_pct == 0.0
        assert result.abstract_fallback_within_slo is True

    def test_rate_one_hundred_when_all_abstract_fallback(self):
        """All abstract-only fallbacks → 100% (well above SLO)."""
        result = PipelineResult(
            papers_with_extraction=10,
            papers_with_pdf=0,
            papers_with_abstract_fallback=10,
        )
        assert result.abstract_fallback_rate_pct == 100.0
        assert result.abstract_fallback_within_slo is False

    def test_rate_at_slo_boundary(self):
        """Exactly 20% is within SLO (inclusive boundary)."""
        result = PipelineResult(
            papers_with_extraction=10,
            papers_with_pdf=8,
            papers_with_abstract_fallback=2,
        )
        assert result.abstract_fallback_rate_pct == 20.0
        assert result.abstract_fallback_within_slo is True

    def test_rate_just_over_slo(self):
        """21% is OUT of SLO."""
        result = PipelineResult(
            papers_with_extraction=100,
            papers_with_pdf=79,
            papers_with_abstract_fallback=21,
        )
        assert result.abstract_fallback_rate_pct == 21.0
        assert result.abstract_fallback_within_slo is False

    def test_rate_rounds_to_two_decimals(self):
        """Rate is rounded for log-event readability (1/3 → 33.33%)."""
        result = PipelineResult(
            papers_with_extraction=3,
            papers_with_pdf=2,
            papers_with_abstract_fallback=1,
        )
        assert result.abstract_fallback_rate_pct == 33.33

    def test_to_dict_includes_slo_fields(self):
        """to_dict() exposes counts + computed rate for log emission."""
        result = PipelineResult(
            papers_with_extraction=10,
            papers_with_pdf=7,
            papers_with_abstract_fallback=3,
        )
        d = result.to_dict()
        assert d["papers_with_pdf"] == 7
        assert d["papers_with_abstract_fallback"] == 3
        assert d["abstract_fallback_rate_pct"] == 30.0

    def test_merge_topic_result_aggregates_provenance_counts(self):
        """merge_topic_result accumulates per-topic provenance counts."""
        result = PipelineResult()
        result.merge_topic_result(
            {
                "success": True,
                "papers_processed": 5,
                "papers_with_extraction": 5,
                "papers_with_pdf": 4,
                "papers_with_abstract_fallback": 1,
            }
        )
        result.merge_topic_result(
            {
                "success": True,
                "papers_processed": 3,
                "papers_with_extraction": 3,
                "papers_with_pdf": 1,
                "papers_with_abstract_fallback": 2,
            }
        )
        assert result.papers_with_pdf == 5
        assert result.papers_with_abstract_fallback == 3
        assert result.abstract_fallback_rate_pct == 37.5


class TestBreadthMetricSLO:
    """Phase 9.5 REQ-9.5.2.4 — breadth metric rate computation.

    The rate is the per-run building block of a 7-day rolling SLO. The
    spec defines: rate = papers_from_citations / papers_discovered (zero
    when denominator is zero, treated as "no SLO breach" since there's
    nothing to broaden if nothing was discovered).
    """

    def test_rate_zero_when_no_papers_discovered(self):
        """No discovery → rate is 0.0 and within_slo=True (no breach)."""
        result = PipelineResult(papers_discovered=0)
        assert result.breadth_metric_rate_pct == 0.0
        assert result.breadth_metric_within_slo is True

    def test_rate_zero_when_all_from_providers(self):
        """All from providers, none from citations → 0% rate, OUT of SLO."""
        result = PipelineResult(
            papers_discovered=10,
            papers_from_providers=10,
            papers_from_citations=0,
        )
        assert result.breadth_metric_rate_pct == 0.0
        assert result.breadth_metric_within_slo is False

    def test_rate_one_hundred_when_all_from_citations(self):
        """All from citations → 100% (well above SLO floor)."""
        result = PipelineResult(
            papers_discovered=10,
            papers_from_providers=0,
            papers_from_citations=10,
        )
        assert result.breadth_metric_rate_pct == 100.0
        assert result.breadth_metric_within_slo is True

    def test_rate_at_slo_boundary(self):
        """Exactly 15% is within SLO (inclusive boundary)."""
        result = PipelineResult(
            papers_discovered=100,
            papers_from_providers=85,
            papers_from_citations=15,
        )
        assert result.breadth_metric_rate_pct == 15.0
        assert result.breadth_metric_within_slo is True

    def test_rate_just_under_slo(self):
        """14% is OUT of SLO (citations under-contributing)."""
        result = PipelineResult(
            papers_discovered=100,
            papers_from_providers=86,
            papers_from_citations=14,
        )
        assert result.breadth_metric_rate_pct == 14.0
        assert result.breadth_metric_within_slo is False

    def test_rate_rounds_to_two_decimals(self):
        """Rate is rounded for log-event readability (1/3 → 33.33%)."""
        result = PipelineResult(
            papers_discovered=3,
            papers_from_providers=2,
            papers_from_citations=1,
        )
        assert result.breadth_metric_rate_pct == 33.33

    def test_to_dict_includes_breadth_fields(self):
        """to_dict() exposes counts + computed rate + source_breakdown."""
        result = PipelineResult(
            papers_discovered=10,
            papers_from_providers=7,
            papers_from_citations=3,
            source_breakdown={"arxiv": 7, "forward_citations": 3},
        )
        d = result.to_dict()
        assert d["papers_from_providers"] == 7
        assert d["papers_from_citations"] == 3
        assert d["breadth_metric_rate_pct"] == 30.0
        assert d["source_breakdown"] == {"arxiv": 7, "forward_citations": 3}

    def test_source_breakdown_default_is_independent_per_instance(self):
        """Default-factory dict must not be shared across PipelineResult instances."""
        a = PipelineResult()
        b = PipelineResult()
        a.source_breakdown["arxiv"] = 5
        assert "arxiv" not in b.source_breakdown


class TestEmitPipelineHealthSloEvents:
    """Phase 9.5 PR γ — centralised SLO emission helper.

    Replaces the prior ``TestAbstractFallbackSLOEvent`` and
    ``TestBreadthMetricSLOEvent`` classes that exercised emission
    through DailyResearchJob.run(). Those tests had to mock the entire
    ResearchPipeline, which made them silently dead when the
    emission was moved out of the scheduler entry point. Testing the
    helper directly is more honest and resilient: the helper is a
    pure function over PipelineResult, and a separate wiring test in
    test_research_pipeline.py confirms ResearchPipeline.run() calls
    it at end-of-pipeline.
    """

    @staticmethod
    def _capture_events(result: PipelineResult, target_event: str) -> list:
        """Run the helper and return only the matching captured events."""
        import structlog
        from unittest.mock import patch as _patch

        from src.orchestration import result as result_module

        # Rebind the module-level _logger before capture_logs() so
        # cache_logger_on_first_use=True doesn't bypass the test
        # processor chain (documented pattern in CLAUDE.md test
        # conventions).
        new_logger = structlog.get_logger()
        with _patch.object(result_module, "_logger", new_logger):
            with structlog.testing.capture_logs() as logs:
                result_module.emit_pipeline_health_slo_events(result)
        return [e for e in logs if e["event"] == target_event]

    def test_emits_abstract_fallback_event_with_rate_and_counts(self):
        """abstract_fallback event MUST include rate, counts, threshold, within_slo."""
        result = PipelineResult(
            topics_processed=1,
            papers_processed=10,
            papers_with_extraction=10,
            papers_with_pdf=8,
            papers_with_abstract_fallback=2,
        )
        events = self._capture_events(result, "pipeline_health_abstract_fallback_rate")
        assert len(events) == 1
        evt = events[0]
        assert evt["rate_pct"] == 20.0
        assert evt["papers_with_extraction"] == 10
        assert evt["papers_with_pdf"] == 8
        assert evt["papers_with_abstract_fallback"] == 2
        assert evt["slo_target_pct"] == 20.0
        assert evt["within_slo"] is True

    def test_emits_abstract_fallback_event_when_slo_breached(self):
        result = PipelineResult(
            topics_processed=1,
            papers_processed=10,
            papers_with_extraction=10,
            papers_with_pdf=3,
            papers_with_abstract_fallback=7,
        )
        events = self._capture_events(result, "pipeline_health_abstract_fallback_rate")
        assert len(events) == 1
        assert events[0]["rate_pct"] == 70.0
        assert events[0]["within_slo"] is False

    def test_emits_abstract_fallback_event_with_zero_extractions(self):
        events = self._capture_events(
            PipelineResult(), "pipeline_health_abstract_fallback_rate"
        )
        assert len(events) == 1
        assert events[0]["rate_pct"] == 0.0
        assert events[0]["within_slo"] is True

    def test_emits_breadth_event_with_rate_counts_and_breakdown(self):
        """breadth event MUST include rate, counts, breakdown, threshold, within_slo."""
        result = PipelineResult(
            topics_processed=2,
            papers_discovered=100,
            papers_from_providers=80,
            papers_from_citations=20,
            source_breakdown={
                "arxiv": 50,
                "semantic_scholar": 30,
                "forward_citations": 12,
                "backward_citations": 8,
            },
        )
        events = self._capture_events(result, "pipeline_health_breadth_metric")
        assert len(events) == 1
        evt = events[0]
        assert evt["rate_pct"] == 20.0
        assert evt["papers_discovered"] == 100
        assert evt["papers_from_providers"] == 80
        assert evt["papers_from_citations"] == 20
        assert evt["source_breakdown"]["arxiv"] == 50
        assert evt["source_breakdown"]["forward_citations"] == 12
        assert evt["slo_target_pct"] == 15.0
        assert evt["within_slo"] is True

    def test_emits_breadth_event_when_slo_breached(self):
        result = PipelineResult(
            topics_processed=1,
            papers_discovered=100,
            papers_from_providers=95,
            papers_from_citations=5,
            source_breakdown={"arxiv": 95, "forward_citations": 5},
        )
        events = self._capture_events(result, "pipeline_health_breadth_metric")
        assert len(events) == 1
        assert events[0]["rate_pct"] == 5.0
        assert events[0]["within_slo"] is False

    def test_emits_breadth_event_with_zero_papers_discovered(self):
        events = self._capture_events(
            PipelineResult(), "pipeline_health_breadth_metric"
        )
        assert len(events) == 1
        assert events[0]["rate_pct"] == 0.0
        assert events[0]["within_slo"] is True

    def test_helper_emits_both_events_in_one_call(self):
        """One invocation MUST fire both SLO events for the same result."""
        import structlog
        from unittest.mock import patch as _patch

        from src.orchestration import result as result_module

        result = PipelineResult(
            papers_discovered=10,
            papers_from_providers=8,
            papers_from_citations=2,
            papers_with_extraction=5,
            papers_with_pdf=4,
            papers_with_abstract_fallback=1,
        )
        with _patch.object(result_module, "_logger", structlog.get_logger()):
            with structlog.testing.capture_logs() as logs:
                result_module.emit_pipeline_health_slo_events(result)

        event_names = [e["event"] for e in logs]
        assert "pipeline_health_abstract_fallback_rate" in event_names
        assert "pipeline_health_breadth_metric" in event_names

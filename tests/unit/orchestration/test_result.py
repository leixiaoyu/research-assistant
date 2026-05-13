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

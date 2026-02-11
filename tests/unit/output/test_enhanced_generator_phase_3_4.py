"""Tests for EnhancedMarkdownGenerator Phase 3.4 features."""

import pytest

from src.output.enhanced_generator import EnhancedMarkdownGenerator
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    NoPDFAction,
)
from src.models.paper import PaperMetadata
from src.models.extraction import ExtractedPaper


@pytest.fixture
def generator():
    """Create generator instance."""
    return EnhancedMarkdownGenerator()


@pytest.fixture
def topic_include_metadata():
    """Topic with INCLUDE_METADATA action."""
    return ResearchTopic(
        query="test query",
        timeframe=TimeframeRecent(value="48h"),
        no_pdf_action=NoPDFAction.INCLUDE_METADATA,
    )


@pytest.fixture
def topic_skip():
    """Topic with SKIP action."""
    return ResearchTopic(
        query="test query",
        timeframe=TimeframeRecent(value="48h"),
        no_pdf_action=NoPDFAction.SKIP,
    )


@pytest.fixture
def topic_flag_manual():
    """Topic with FLAG_FOR_MANUAL action."""
    return ResearchTopic(
        query="test query",
        timeframe=TimeframeRecent(value="48h"),
        no_pdf_action=NoPDFAction.FLAG_FOR_MANUAL,
    )


@pytest.fixture
def extracted_paper_with_pdf():
    """Paper with PDF available."""
    return ExtractedPaper(
        metadata=PaperMetadata(
            paper_id="paper1",
            title="Paper With PDF",
            url="https://example.com/paper1",
            open_access_pdf="https://example.com/paper1.pdf",
            citation_count=100,
            venue="NeurIPS",
            abstract="Test abstract",
            quality_score=75.0,
            pdf_available=True,
        ),
        pdf_available=True,
        extraction=None,
    )


@pytest.fixture
def extracted_paper_without_pdf():
    """Paper without PDF."""
    return ExtractedPaper(
        metadata=PaperMetadata(
            paper_id="paper2",
            title="Paper Without PDF",
            url="https://example.com/paper2",
            citation_count=50,
            doi="10.1234/test",
            abstract="Test abstract",
            quality_score=45.0,
            pdf_available=False,
        ),
        pdf_available=False,
        extraction=None,
    )


class TestQualityBadge:
    """Tests for quality badge generation."""

    def test_excellent_badge(self, generator):
        """Test excellent badge for score >= 80."""
        badge = generator._quality_badge(85.0)
        assert "⭐⭐⭐" in badge
        assert "Excellent" in badge
        assert "85" in badge

    def test_good_badge(self, generator):
        """Test good badge for score 60-79."""
        badge = generator._quality_badge(70.0)
        assert "⭐⭐" in badge
        assert "Good" in badge
        assert "70" in badge

    def test_fair_badge(self, generator):
        """Test fair badge for score 40-59."""
        badge = generator._quality_badge(50.0)
        assert "⭐" in badge
        assert "Fair" in badge
        assert "50" in badge

    def test_low_badge(self, generator):
        """Test low badge for score < 40."""
        badge = generator._quality_badge(25.0)
        assert "○" in badge
        assert "Low" in badge
        assert "25" in badge

    def test_boundary_excellent(self, generator):
        """Test boundary at 80 (excellent)."""
        badge = generator._quality_badge(80.0)
        assert "Excellent" in badge

    def test_boundary_good(self, generator):
        """Test boundary at 60 (good)."""
        badge = generator._quality_badge(60.0)
        assert "Good" in badge

    def test_boundary_fair(self, generator):
        """Test boundary at 40 (fair)."""
        badge = generator._quality_badge(40.0)
        assert "Fair" in badge


class TestPDFBadge:
    """Tests for PDF badge generation."""

    def test_pdf_available_badge(self, generator):
        """Test badge when PDF is available."""
        badge = generator._pdf_badge(True)
        assert "📄" in badge
        assert "PDF Available" in badge

    def test_pdf_unavailable_badge(self, generator):
        """Test badge when PDF is not available."""
        badge = generator._pdf_badge(False)
        assert "📋" in badge
        assert "Abstract Only" in badge


class TestNoPDFActionIncludeMetadata:
    """Tests for INCLUDE_METADATA action."""

    def test_papers_without_pdf_included(
        self,
        generator,
        topic_include_metadata,
        extracted_paper_with_pdf,
        extracted_paper_without_pdf,
    ):
        """Test that papers without PDF are included."""
        papers = [extracted_paper_with_pdf, extracted_paper_without_pdf]

        markdown = generator.generate_enhanced(
            extracted_papers=papers,
            topic=topic_include_metadata,
            run_id="test-run",
        )

        # Both papers should be in output
        assert "Paper With PDF" in markdown
        assert "Paper Without PDF" in markdown


class TestNoPDFActionSkip:
    """Tests for SKIP action."""

    def test_papers_without_pdf_skipped(
        self,
        generator,
        topic_skip,
        extracted_paper_with_pdf,
        extracted_paper_without_pdf,
    ):
        """Test that papers without PDF are skipped."""
        papers = [extracted_paper_with_pdf, extracted_paper_without_pdf]

        markdown = generator.generate_enhanced(
            extracted_papers=papers,
            topic=topic_skip,
            run_id="test-run",
        )

        # Only paper with PDF should be in output
        assert "Paper With PDF" in markdown
        assert "Paper Without PDF" not in markdown

    def test_skip_message_shown(
        self,
        generator,
        topic_skip,
        extracted_paper_without_pdf,
    ):
        """Test that skip message is shown."""
        papers = [extracted_paper_without_pdf]

        markdown = generator.generate_enhanced(
            extracted_papers=papers,
            topic=topic_skip,
            run_id="test-run",
        )

        # Should show skip message
        assert "papers skipped" in markdown


class TestNoPDFActionFlagForManual:
    """Tests for FLAG_FOR_MANUAL action."""

    def test_papers_flagged_for_manual(
        self,
        generator,
        topic_flag_manual,
        extracted_paper_with_pdf,
        extracted_paper_without_pdf,
    ):
        """Test that papers are flagged for manual acquisition."""
        papers = [extracted_paper_with_pdf, extracted_paper_without_pdf]

        markdown = generator.generate_enhanced(
            extracted_papers=papers,
            topic=topic_flag_manual,
            run_id="test-run",
        )

        # Both papers should be included
        assert "Paper With PDF" in markdown
        assert "Paper Without PDF" in markdown

        # Should have manual acquisition section
        assert "Papers Requiring Manual PDF Acquisition" in markdown

    def test_action_required_message(
        self,
        generator,
        topic_flag_manual,
        extracted_paper_without_pdf,
    ):
        """Test that ACTION REQUIRED message is shown."""
        papers = [extracted_paper_without_pdf]

        markdown = generator.generate_enhanced(
            extracted_papers=papers,
            topic=topic_flag_manual,
            run_id="test-run",
        )

        # Should show action required message
        assert "ACTION REQUIRED" in markdown

    def test_doi_included_in_manual_list(
        self,
        generator,
        topic_flag_manual,
        extracted_paper_without_pdf,
    ):
        """Test that DOI is included in manual acquisition list."""
        papers = [extracted_paper_without_pdf]

        markdown = generator.generate_enhanced(
            extracted_papers=papers,
            topic=topic_flag_manual,
            run_id="test-run",
        )

        # Should include DOI in manual list
        assert "10.1234/test" in markdown


class TestQualityStatistics:
    """Tests for quality statistics in output."""

    def test_quality_stats_shown(
        self,
        generator,
        topic_include_metadata,
        extracted_paper_with_pdf,
    ):
        """Test that quality statistics are shown."""
        # Need papers with quality scores
        paper = extracted_paper_with_pdf
        paper.metadata.quality_score = 80.0
        papers = [paper]

        markdown = generator.generate_enhanced(
            extracted_papers=papers,
            topic=topic_include_metadata,
            run_id="test-run",
        )

        assert "Avg Quality Score" in markdown
        assert "Top Quality" in markdown

    def test_quality_badge_in_paper_entry(
        self,
        generator,
        topic_include_metadata,
        extracted_paper_with_pdf,
    ):
        """Test that quality badge appears in paper entry."""
        papers = [extracted_paper_with_pdf]

        markdown = generator.generate_enhanced(
            extracted_papers=papers,
            topic=topic_include_metadata,
            run_id="test-run",
        )

        # Quality badge should be present
        assert "**Quality:**" in markdown
        assert "**Status:**" in markdown

    def test_no_quality_stats_for_zero_scores(
        self,
        generator,
        topic_include_metadata,
    ):
        """Test that quality stats section handles zero scores."""
        paper = ExtractedPaper(
            metadata=PaperMetadata(
                paper_id="paper1",
                title="Paper",
                url="https://example.com/paper",
                quality_score=0.0,
            ),
            pdf_available=True,
            extraction=None,
        )

        markdown = generator.generate_enhanced(
            extracted_papers=[paper],
            topic=topic_include_metadata,
            run_id="test-run",
        )

        # Should not crash, stats section might be empty
        assert "## Research Statistics" in markdown


class TestPDFStatusDisplay:
    """Tests for PDF status display in paper entries."""

    def test_pdf_download_link_shown(
        self,
        generator,
        topic_include_metadata,
        extracted_paper_with_pdf,
    ):
        """Test that PDF download link is shown for available PDFs."""
        papers = [extracted_paper_with_pdf]

        markdown = generator.generate_enhanced(
            extracted_papers=papers,
            topic=topic_include_metadata,
            run_id="test-run",
        )

        assert "**PDF:** ✅" in markdown
        assert "Download" in markdown

    def test_pdf_unavailable_message(
        self,
        generator,
        topic_include_metadata,
        extracted_paper_without_pdf,
    ):
        """Test that unavailable message is shown for missing PDFs."""
        papers = [extracted_paper_without_pdf]

        markdown = generator.generate_enhanced(
            extracted_papers=papers,
            topic=topic_include_metadata,
            run_id="test-run",
        )

        assert "**PDF:** ❌" in markdown
        assert "Not available via open access" in markdown

    def test_doi_shown_for_unavailable_pdf(
        self,
        generator,
        topic_include_metadata,
        extracted_paper_without_pdf,
    ):
        """Test that DOI is shown when PDF is unavailable."""
        papers = [extracted_paper_without_pdf]

        markdown = generator.generate_enhanced(
            extracted_papers=papers,
            topic=topic_include_metadata,
            run_id="test-run",
        )

        # DOI should be shown to help with manual lookup
        assert "10.1234/test" in markdown

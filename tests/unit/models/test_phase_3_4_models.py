"""Tests for Phase 3.4 model additions."""

import pytest

from src.models.config import (
    PDFStrategy,
    NoPDFAction,
    ResearchTopic,
    TimeframeRecent,
)
from src.models.paper import PaperMetadata


class TestPDFStrategyEnum:
    """Tests for PDFStrategy enum."""

    def test_quality_first_value(self):
        """Test QUALITY_FIRST enum value."""
        assert PDFStrategy.QUALITY_FIRST.value == "quality_first"

    def test_pdf_required_value(self):
        """Test PDF_REQUIRED enum value."""
        assert PDFStrategy.PDF_REQUIRED.value == "pdf_required"

    def test_arxiv_supplement_value(self):
        """Test ARXIV_SUPPLEMENT enum value."""
        assert PDFStrategy.ARXIV_SUPPLEMENT.value == "arxiv_supplement"

    def test_enum_from_string(self):
        """Test creating enum from string value."""
        assert PDFStrategy("quality_first") == PDFStrategy.QUALITY_FIRST
        assert PDFStrategy("pdf_required") == PDFStrategy.PDF_REQUIRED
        assert PDFStrategy("arxiv_supplement") == PDFStrategy.ARXIV_SUPPLEMENT

    def test_invalid_value(self):
        """Test that invalid value raises error."""
        with pytest.raises(ValueError):
            PDFStrategy("invalid_strategy")


class TestNoPDFActionEnum:
    """Tests for NoPDFAction enum."""

    def test_include_metadata_value(self):
        """Test INCLUDE_METADATA enum value."""
        assert NoPDFAction.INCLUDE_METADATA.value == "include_metadata"

    def test_skip_value(self):
        """Test SKIP enum value."""
        assert NoPDFAction.SKIP.value == "skip"

    def test_flag_for_manual_value(self):
        """Test FLAG_FOR_MANUAL enum value."""
        assert NoPDFAction.FLAG_FOR_MANUAL.value == "flag_for_manual"

    def test_enum_from_string(self):
        """Test creating enum from string value."""
        assert NoPDFAction("include_metadata") == NoPDFAction.INCLUDE_METADATA
        assert NoPDFAction("skip") == NoPDFAction.SKIP
        assert NoPDFAction("flag_for_manual") == NoPDFAction.FLAG_FOR_MANUAL


class TestResearchTopicPhase34Fields:
    """Tests for Phase 3.4 fields in ResearchTopic."""

    def test_default_quality_ranking(self):
        """Test default quality_ranking is True."""
        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="48h"),
        )
        assert topic.quality_ranking is True

    def test_default_min_quality_score(self):
        """Test default min_quality_score is 0."""
        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="48h"),
        )
        assert topic.min_quality_score == 0.0

    def test_default_pdf_strategy(self):
        """Test default pdf_strategy is QUALITY_FIRST."""
        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="48h"),
        )
        assert topic.pdf_strategy == PDFStrategy.QUALITY_FIRST

    def test_default_no_pdf_action(self):
        """Test default no_pdf_action is INCLUDE_METADATA."""
        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="48h"),
        )
        assert topic.no_pdf_action == NoPDFAction.INCLUDE_METADATA

    def test_default_arxiv_supplement_threshold(self):
        """Test default arxiv_supplement_threshold is 0.5."""
        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="48h"),
        )
        assert topic.arxiv_supplement_threshold == 0.5

    def test_custom_quality_ranking(self):
        """Test setting quality_ranking to False."""
        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="48h"),
            quality_ranking=False,
        )
        assert topic.quality_ranking is False

    def test_custom_min_quality_score(self):
        """Test setting custom min_quality_score."""
        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="48h"),
            min_quality_score=50.0,
        )
        assert topic.min_quality_score == 50.0

    def test_min_quality_score_validation_min(self):
        """Test min_quality_score minimum validation."""
        with pytest.raises(ValueError):
            ResearchTopic(
                query="test query",
                timeframe=TimeframeRecent(value="48h"),
                min_quality_score=-1.0,
            )

    def test_min_quality_score_validation_max(self):
        """Test min_quality_score maximum validation."""
        with pytest.raises(ValueError):
            ResearchTopic(
                query="test query",
                timeframe=TimeframeRecent(value="48h"),
                min_quality_score=101.0,
            )

    def test_custom_pdf_strategy(self):
        """Test setting custom pdf_strategy."""
        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="48h"),
            pdf_strategy=PDFStrategy.PDF_REQUIRED,
        )
        assert topic.pdf_strategy == PDFStrategy.PDF_REQUIRED

    def test_custom_no_pdf_action(self):
        """Test setting custom no_pdf_action."""
        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="48h"),
            no_pdf_action=NoPDFAction.SKIP,
        )
        assert topic.no_pdf_action == NoPDFAction.SKIP

    def test_custom_arxiv_supplement_threshold(self):
        """Test setting custom arxiv_supplement_threshold."""
        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="48h"),
            arxiv_supplement_threshold=0.7,
        )
        assert topic.arxiv_supplement_threshold == 0.7

    def test_arxiv_threshold_validation_min(self):
        """Test arxiv_supplement_threshold minimum validation."""
        with pytest.raises(ValueError):
            ResearchTopic(
                query="test query",
                timeframe=TimeframeRecent(value="48h"),
                arxiv_supplement_threshold=-0.1,
            )

    def test_arxiv_threshold_validation_max(self):
        """Test arxiv_supplement_threshold maximum validation."""
        with pytest.raises(ValueError):
            ResearchTopic(
                query="test query",
                timeframe=TimeframeRecent(value="48h"),
                arxiv_supplement_threshold=1.5,
            )


class TestPaperMetadataPhase34Fields:
    """Tests for Phase 3.4 fields in PaperMetadata."""

    def test_default_quality_score(self):
        """Test default quality_score is 0.0."""
        paper = PaperMetadata(
            paper_id="test123",
            title="Test Paper",
            url="https://example.com/paper",
        )
        assert paper.quality_score == 0.0

    def test_default_pdf_available(self):
        """Test default pdf_available is False."""
        paper = PaperMetadata(
            paper_id="test123",
            title="Test Paper",
            url="https://example.com/paper",
        )
        assert paper.pdf_available is False

    def test_default_pdf_source(self):
        """Test default pdf_source is None."""
        paper = PaperMetadata(
            paper_id="test123",
            title="Test Paper",
            url="https://example.com/paper",
        )
        assert paper.pdf_source is None

    def test_custom_quality_score(self):
        """Test setting custom quality_score."""
        paper = PaperMetadata(
            paper_id="test123",
            title="Test Paper",
            url="https://example.com/paper",
            quality_score=75.5,
        )
        assert paper.quality_score == 75.5

    def test_quality_score_validation_min(self):
        """Test quality_score minimum validation."""
        with pytest.raises(ValueError):
            PaperMetadata(
                paper_id="test123",
                title="Test Paper",
                url="https://example.com/paper",
                quality_score=-1.0,
            )

    def test_quality_score_validation_max(self):
        """Test quality_score maximum validation."""
        with pytest.raises(ValueError):
            PaperMetadata(
                paper_id="test123",
                title="Test Paper",
                url="https://example.com/paper",
                quality_score=101.0,
            )

    def test_custom_pdf_available(self):
        """Test setting pdf_available to True."""
        paper = PaperMetadata(
            paper_id="test123",
            title="Test Paper",
            url="https://example.com/paper",
            pdf_available=True,
        )
        assert paper.pdf_available is True

    def test_custom_pdf_source(self):
        """Test setting pdf_source."""
        paper = PaperMetadata(
            paper_id="test123",
            title="Test Paper",
            url="https://example.com/paper",
            pdf_source="open_access",
        )
        assert paper.pdf_source == "open_access"

    def test_complete_phase_34_paper(self):
        """Test paper with all Phase 3.4 fields set."""
        paper = PaperMetadata(
            paper_id="test123",
            title="Test Paper",
            url="https://example.com/paper",
            quality_score=85.0,
            pdf_available=True,
            pdf_source="arxiv",
        )
        assert paper.quality_score == 85.0
        assert paper.pdf_available is True
        assert paper.pdf_source == "arxiv"

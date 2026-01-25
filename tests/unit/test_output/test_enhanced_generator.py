import pytest

from src.output.enhanced_generator import EnhancedMarkdownGenerator
from src.models.extraction import (
    ExtractionResult,
    PaperExtraction,
    ExtractedPaper,
)
from src.models.paper import PaperMetadata, Author
from src.models.config import ResearchTopic, TimeframeRecent


@pytest.fixture
def generator():
    return EnhancedMarkdownGenerator()


@pytest.fixture
def mock_topic():
    return ResearchTopic(
        query="machine learning", timeframe=TimeframeRecent(type="recent", value="7d")
    )


@pytest.fixture
def mock_paper():
    return PaperMetadata(
        paper_id="2301.12345",
        title="Test Paper",
        abstract="Test abstract",
        authors=[Author(name="Author 1"), Author(name="Author 2")],
        url="https://arxiv.org/abs/2301.12345",
        open_access_pdf="https://arxiv.org/pdf/2301.12345.pdf",
        year=2023,
        citation_count=10,
    )


class TestEnhancedMarkdownGenerator:
    def test_generate_enhanced_basic(self, generator, mock_paper, mock_topic):
        """Test basic generation with one paper"""
        extraction = PaperExtraction(
            paper_id=mock_paper.paper_id,
            extraction_results=[
                ExtractionResult(
                    target_name="summary",
                    success=True,
                    content="A good summary",
                    confidence=0.9,
                )
            ],
            tokens_used=1000,
            cost_usd=0.01,
        )

        extracted = ExtractedPaper(
            metadata=mock_paper, pdf_available=True, extraction=extraction
        )

        markdown = generator.generate_enhanced(
            extracted_papers=[extracted], topic=mock_topic, run_id="run-123"
        )

        assert "# Research Brief: machine learning" in markdown
        assert "Run ID: run-123" in markdown
        assert "Total Tokens Used: 1,000" in markdown
        assert "### 1. [Test Paper]" in markdown
        assert "A good summary" in markdown

    def test_format_extraction_result_list(self, generator):
        """Test formatting list content"""
        result = ExtractionResult(
            target_name="targets",
            success=True,
            content=["item 1", "item 2"],
            confidence=0.8,
        )
        formatted = generator._format_extraction_result(result)
        assert "- item 1" in formatted
        assert "- item 2" in formatted

    def test_format_extraction_result_dict(self, generator):
        """Test formatting dict content"""
        result = ExtractionResult(
            target_name="metrics",
            success=True,
            content={"acc": 0.95, "f1": 0.92},
            confidence=0.8,
        )
        formatted = generator._format_extraction_result(result)
        assert "acc: 0.95" in formatted
        assert "f1: 0.92" in formatted

    def test_format_extraction_result_code(self, generator):
        """Test formatting code content"""
        result = ExtractionResult(
            target_name="code", success=True, content="print('hello')", confidence=0.9
        )
        # Use target with 'code' in name to trigger code block
        formatted = generator._format_extraction_result(result)
        assert "```python" in formatted
        assert "print('hello')" in formatted

    def test_generate_enhanced_no_papers(self, generator, mock_topic):
        """Test generation with no papers"""
        markdown = generator.generate_enhanced([], mock_topic, "run-empty")
        assert "No papers processed" in markdown

    def test_author_formatting_long_list(self, generator, mock_paper, mock_topic):
        """Test author list truncation with et al."""
        mock_paper.authors = [
            Author(name="A1"),
            Author(name="A2"),
            Author(name="A3"),
            Author(name="A4"),
            Author(name="A5"),
        ]
        extracted = ExtractedPaper(metadata=mock_paper, pdf_available=False)
        markdown = generator.generate_enhanced([extracted], mock_topic, "run-long")
        assert "A1, A2, A3, et al." in markdown

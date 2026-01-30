import pytest

from src.output.enhanced_generator import EnhancedMarkdownGenerator
from src.models.extraction import (
    ExtractionResult,
    PaperExtraction,
    ExtractedPaper,
)
from src.models.paper import PaperMetadata, Author
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    TimeframeDateRange,
)
from datetime import date


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
        assert "run_id: run-123" in markdown
        assert "**Total Tokens Used:** 1,000" in markdown
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
        # Dict is formatted as a markdown table
        assert "| Metric | Value |" in formatted
        assert "| acc | 0.95 |" in formatted
        assert "| f1 | 0.92 |" in formatted

    def test_format_extraction_result_code(self, generator):
        """Test formatting code content"""
        result = ExtractionResult(
            target_name="code",
            success=True,
            content="def hello():\n    print('hello')",
            confidence=0.9,
        )
        # Use target with 'code' in name to trigger code block
        formatted = generator._format_extraction_result(result)
        assert "```python" in formatted
        assert "def hello():" in formatted

    def test_generate_enhanced_no_papers(self, generator, mock_topic):
        """Test generation with no papers"""
        markdown = generator.generate_enhanced([], mock_topic, "run-empty")
        assert "**Papers Processed:** 0" in markdown
        assert "**Papers Found:** 0" in markdown

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

    def test_timeframe_without_value_attribute(self, generator, mock_paper):
        """Test timeframe handling when object doesn't have value attribute (line 53)"""
        # TimeframeDateRange doesn't have a value attribute
        topic = ResearchTopic(
            query="test",
            timeframe=TimeframeDateRange(
                type="date_range",
                start_date=date(2023, 1, 1),
                end_date=date(2023, 12, 31),
            ),
        )
        extracted = ExtractedPaper(metadata=mock_paper, pdf_available=True)
        markdown = generator.generate_enhanced([extracted], topic, "run-custom")
        # Should use "custom" as fallback when no value attribute
        assert "timeframe: custom" in markdown

    def test_paper_with_venue(self, generator, mock_topic):
        """Test paper formatting with venue field (line 168)"""
        paper = PaperMetadata(
            paper_id="123",
            title="Test",
            abstract="Abstract",
            authors=[Author(name="Author")],
            url="https://test.com",
            year=2023,
            citation_count=5,
            venue="NeurIPS 2023",  # Add venue
        )
        extracted = ExtractedPaper(metadata=paper, pdf_available=True)
        markdown = generator.generate_enhanced([extracted], mock_topic, "run-venue")
        assert "**Venue:** NeurIPS 2023" in markdown

    def test_format_extraction_result_complex_dict(self, generator):
        """Test formatting complex nested dict as JSON (lines 240-242)"""
        result = ExtractionResult(
            target_name="config",
            success=True,
            content={
                "model": {"name": "GPT-4", "params": {"temp": 0.7}},
                "layers": [1, 2, 3],
            },
            confidence=0.9,
        )
        formatted = generator._format_extraction_result(result)
        # Complex dict should be JSON-formatted
        assert "```json" in formatted
        assert '"model"' in formatted

    def test_format_extraction_result_javascript_code(self, generator):
        """Test JavaScript language detection (line 262)"""
        result = ExtractionResult(
            target_name="code",
            success=True,
            content="function hello() { const x = 5; }",
            confidence=0.9,
        )
        formatted = generator._format_extraction_result(result)
        assert "```javascript" in formatted

    def test_format_extraction_result_java_code(self, generator):
        """Test Java language detection (line 264)"""
        result = ExtractionResult(
            target_name="code",
            success=True,
            content="public class HelloWorld { private int x; }",
            confidence=0.9,
        )
        formatted = generator._format_extraction_result(result)
        assert "```java" in formatted

    def test_format_extraction_result_fallback_type(self, generator):
        """Test fallback formatting for non-dict/list/str types (lines 276-277)"""
        # Test with a number
        result = ExtractionResult(
            target_name="score", success=True, content=42, confidence=0.9
        )
        formatted = generator._format_extraction_result(result)
        assert "42" in formatted

        # Test with a boolean
        result2 = ExtractionResult(
            target_name="flag", success=True, content=True, confidence=0.9
        )
        formatted2 = generator._format_extraction_result(result2)
        assert "True" in formatted2

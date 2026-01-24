"""Unit tests for Enhanced Markdown Generator (Phase 2)

Tests for:
- Enhanced markdown generation with extraction results
- Frontmatter with Phase 2 metadata
- Extraction result formatting (text, list, dict, code)
- Summary statistics
- Paper formatting with PDFs and extractions
"""

import pytest
from datetime import datetime
import json

from src.output.enhanced_generator import EnhancedMarkdownGenerator
from src.models.config import ResearchTopic, TimeframeType, Timeframe
from src.models.paper import PaperMetadata, Author
from src.models.extraction import (
    ExtractionTarget,
    ExtractionResult,
    PaperExtraction,
    ExtractedPaper
)


@pytest.fixture
def generator():
    """Create EnhancedMarkdownGenerator instance"""
    return EnhancedMarkdownGenerator()


@pytest.fixture
def research_topic():
    """Create research topic"""
    return ResearchTopic(
        query="Tree of Thoughts AND machine translation",
        timeframe=Timeframe(type=TimeframeType.RECENT, value="48h"),
        max_papers=50
    )


@pytest.fixture
def paper_metadata():
    """Create paper metadata"""
    return PaperMetadata(
        paper_id="2301.12345",
        title="Tree of Thoughts for Machine Translation",
        abstract="This paper explores ToT methods for MT tasks.",
        url="https://arxiv.org/abs/2301.12345",
        open_access_pdf="https://arxiv.org/pdf/2301.12345.pdf",
        authors=[
            Author(name="John Doe"),
            Author(name="Jane Smith"),
            Author(name="Bob Johnson")
        ],
        year=2023,
        citation_count=42,
        venue="NeurIPS 2023"
    )


@pytest.fixture
def extraction_result_list():
    """Create extraction result with list content"""
    return ExtractionResult(
        target_name="system_prompts",
        success=True,
        content=["You are an expert translator.", "Translate the following text."],
        confidence=0.95
    )


@pytest.fixture
def extraction_result_code():
    """Create extraction result with code content"""
    return ExtractionResult(
        target_name="code_snippets",
        success=True,
        content="def translate(text, model):\n    return model.generate(text)",
        confidence=0.88
    )


@pytest.fixture
def extraction_result_dict():
    """Create extraction result with dict content"""
    return ExtractionResult(
        target_name="metrics",
        success=True,
        content={"BLEU": 35.2, "accuracy": 0.92, "f1_score": 0.89},
        confidence=0.90
    )


@pytest.fixture
def extraction_result_text():
    """Create extraction result with text content"""
    return ExtractionResult(
        target_name="summary",
        success=True,
        content="This paper achieves state-of-the-art results on WMT benchmark.",
        confidence=0.85
    )


@pytest.fixture
def paper_extraction(extraction_result_list, extraction_result_code):
    """Create paper extraction with multiple results"""
    return PaperExtraction(
        paper_id="2301.12345",
        extraction_results=[extraction_result_list, extraction_result_code],
        tokens_used=50000,
        cost_usd=0.20,
        extraction_timestamp=datetime(2025, 1, 24, 12, 0, 0)
    )


@pytest.fixture
def extracted_paper_with_pdf(paper_metadata, paper_extraction):
    """Create extracted paper with PDF and extraction"""
    return ExtractedPaper(
        metadata=paper_metadata,
        pdf_available=True,
        pdf_path="/temp/pdfs/2301.12345.pdf",
        markdown_path="/temp/markdown/2301.12345.md",
        extraction=paper_extraction
    )


@pytest.fixture
def extracted_paper_without_pdf(paper_metadata):
    """Create extracted paper without PDF (abstract only)"""
    paper_metadata_copy = paper_metadata.model_copy(deep=True)
    paper_metadata_copy.paper_id = "2301.67890"
    paper_metadata_copy.title = "Abstract Only Paper"
    paper_metadata_copy.open_access_pdf = None

    return ExtractedPaper(
        metadata=paper_metadata_copy,
        pdf_available=False,
        pdf_path=None,
        markdown_path=None,
        extraction=None
    )


def test_generate_enhanced_basic_structure(
    generator,
    research_topic,
    extracted_paper_with_pdf
):
    """Test enhanced markdown generation has correct structure"""
    markdown = generator.generate_enhanced(
        extracted_papers=[extracted_paper_with_pdf],
        topic=research_topic,
        run_id="test-run-001"
    )

    # Check for YAML frontmatter
    assert markdown.startswith("---")
    assert "topic: Tree of Thoughts AND machine translation" in markdown
    assert "tags:" in markdown
    assert "phase-2" in markdown

    # Check for main sections
    assert "# Research Brief:" in markdown
    assert "## Pipeline Summary" in markdown
    assert "## Research Statistics" in markdown
    assert "## Papers" in markdown


def test_generate_enhanced_frontmatter(
    generator,
    research_topic,
    extracted_paper_with_pdf
):
    """Test frontmatter contains correct Phase 2 metadata"""
    markdown = generator.generate_enhanced(
        extracted_papers=[extracted_paper_with_pdf],
        topic=research_topic,
        run_id="test-run-123"
    )

    # Parse frontmatter
    lines = markdown.split('\n')
    frontmatter_end = lines[1:].index('---') + 1
    frontmatter = '\n'.join(lines[1:frontmatter_end])

    # Check Phase 2 fields
    assert "papers_processed: 1" in frontmatter
    assert "papers_with_pdfs: 1" in frontmatter
    assert "papers_with_extractions: 1" in frontmatter
    assert "total_tokens_used: 50000" in frontmatter
    assert "total_cost_usd: 0.2" in frontmatter
    assert "run_id: test-run-123" in frontmatter
    assert "timeframe: 48h" in frontmatter


def test_generate_enhanced_pipeline_summary(
    generator,
    research_topic,
    extracted_paper_with_pdf,
    extracted_paper_without_pdf
):
    """Test pipeline summary section"""
    markdown = generator.generate_enhanced(
        extracted_papers=[extracted_paper_with_pdf, extracted_paper_without_pdf],
        topic=research_topic,
        run_id="test-run"
    )

    # Check pipeline summary stats
    assert "Papers Processed:** 2" in markdown
    assert "With Full PDF:** 1 (50.0%)" in markdown
    assert "With Extractions:** 1 (50.0%)" in markdown
    assert "Total Tokens Used:** 50,000" in markdown
    assert "Total Cost:** $0.20" in markdown


def test_generate_enhanced_with_summary_stats(
    generator,
    research_topic,
    extracted_paper_with_pdf
):
    """Test enhanced generation with optional summary stats"""
    summary_stats = {
        "pdf_success_rate": 75.5,
        "avg_tokens_per_paper": 45000,
        "avg_cost_per_paper": 0.180
    }

    markdown = generator.generate_enhanced(
        extracted_papers=[extracted_paper_with_pdf],
        topic=research_topic,
        run_id="test-run",
        summary_stats=summary_stats
    )

    # Check extraction statistics section
    assert "### Extraction Statistics" in markdown
    assert "PDF Success Rate:** 75.5%" in markdown
    assert "Avg Tokens/Paper:** 45,000" in markdown
    assert "Avg Cost/Paper:** $0.180" in markdown


def test_generate_enhanced_research_statistics(
    generator,
    research_topic,
    extracted_paper_with_pdf
):
    """Test research statistics section"""
    # Create second paper with different metrics
    paper2_metadata = PaperMetadata(
        paper_id="2301.99999",
        title="Another Paper",
        url="https://example.com",
        authors=[],
        citation_count=100,
        year=2024
    )
    paper2 = ExtractedPaper(metadata=paper2_metadata, pdf_available=False)

    markdown = generator.generate_enhanced(
        extracted_papers=[extracted_paper_with_pdf, paper2],
        topic=research_topic,
        run_id="test-run"
    )

    # Check research statistics
    assert "## Research Statistics" in markdown
    assert "Avg Citations:** 71.0" in markdown  # (42 + 100) / 2
    assert "Year Range:** 2023-2024" in markdown


def test_format_extracted_paper_with_pdf(
    generator,
    extracted_paper_with_pdf
):
    """Test paper formatting with PDF and extractions"""
    markdown = generator._format_extracted_paper(extracted_paper_with_pdf, 1)

    # Check paper header
    assert "### 1. [Tree of Thoughts for Machine Translation]" in markdown
    assert "https://arxiv.org/abs/2301.12345" in markdown

    # Check metadata
    assert "**Authors:** John Doe, Jane Smith, Bob Johnson" in markdown
    assert "**Published:** 2023" in markdown
    assert "**Citations:** 42" in markdown
    assert "**Venue:** NeurIPS 2023" in markdown

    # Check PDF status
    assert "**PDF Available:** ✅" in markdown
    assert "https://arxiv.org/pdf/2301.12345.pdf" in markdown

    # Check extraction info
    assert "**Tokens Used:** 50,000" in markdown
    assert "**Cost:** $0.200" in markdown

    # Check abstract
    assert "> This paper explores ToT methods for MT tasks." in markdown

    # Check extraction results section
    assert "#### Extraction Results" in markdown


def test_format_extracted_paper_without_pdf(
    generator,
    extracted_paper_without_pdf
):
    """Test paper formatting without PDF"""
    markdown = generator._format_extracted_paper(extracted_paper_without_pdf, 2)

    # Check PDF status
    assert "**PDF Available:** ❌ (Abstract only)" in markdown

    # Check no extraction results section
    assert "#### Extraction Results" not in markdown


def test_format_extracted_paper_with_many_authors(generator, paper_metadata):
    """Test author formatting with >3 authors"""
    # Add more authors
    paper_metadata.authors = [
        Author(name="Author 1"),
        Author(name="Author 2"),
        Author(name="Author 3"),
        Author(name="Author 4"),
        Author(name="Author 5")
    ]

    extracted = ExtractedPaper(metadata=paper_metadata, pdf_available=False)
    markdown = generator._format_extracted_paper(extracted, 1)

    # Check et al. is used
    assert "Author 1, Author 2, Author 3, et al." in markdown


def test_format_extraction_result_list(generator, extraction_result_list):
    """Test formatting of list-type extraction result"""
    markdown = generator._format_extraction_result(extraction_result_list)

    # Check header
    assert "**System Prompts** (confidence: 95%)" in markdown

    # Check list items
    assert "- You are an expert translator." in markdown
    assert "- Translate the following text." in markdown


def test_format_extraction_result_code(generator, extraction_result_code):
    """Test formatting of code-type extraction result"""
    markdown = generator._format_extraction_result(extraction_result_code)

    # Check header
    assert "**Code Snippets** (confidence: 88%)" in markdown

    # Check code block
    assert "```python" in markdown
    assert "def translate(text, model):" in markdown
    assert "return model.generate(text)" in markdown
    assert "```" in markdown


def test_format_extraction_result_dict_simple(generator, extraction_result_dict):
    """Test formatting of dict-type extraction result (simple key-value pairs)"""
    markdown = generator._format_extraction_result(extraction_result_dict)

    # Check header
    assert "**Metrics** (confidence: 90%)" in markdown

    # Check table formatting
    assert "| Metric | Value |" in markdown
    assert "|--------|-------|" in markdown
    assert "| BLEU | 35.2 |" in markdown
    assert "| accuracy | 0.92 |" in markdown
    assert "| f1_score | 0.89 |" in markdown


def test_format_extraction_result_dict_complex(generator):
    """Test formatting of complex dict with nested structures"""
    result = ExtractionResult(
        target_name="complex_data",
        success=True,
        content={
            "nested": {"key": "value"},
            "list": [1, 2, 3]
        },
        confidence=0.8
    )

    markdown = generator._format_extraction_result(result)

    # Check JSON formatting for complex dict
    assert "```json" in markdown
    assert '"nested"' in markdown
    assert '"key": "value"' in markdown
    assert "```" in markdown


def test_format_extraction_result_text(generator, extraction_result_text):
    """Test formatting of text-type extraction result"""
    markdown = generator._format_extraction_result(extraction_result_text)

    # Check header
    assert "**Summary** (confidence: 85%)" in markdown

    # Check text content
    assert "This paper achieves state-of-the-art results on WMT benchmark." in markdown


def test_format_extraction_result_empty_content(generator):
    """Test formatting of extraction result with no content"""
    result = ExtractionResult(
        target_name="missing_data",
        success=False,
        content=None,
        confidence=0.0
    )

    markdown = generator._format_extraction_result(result)

    assert "_No content extracted_" in markdown


def test_format_extraction_result_javascript_code(generator):
    """Test code detection for JavaScript"""
    result = ExtractionResult(
        target_name="js_code",
        success=True,
        content="const translate = function(text) { return text; }",
        confidence=0.9
    )

    markdown = generator._format_extraction_result(result)

    # Check JavaScript code block
    assert "```javascript" in markdown
    assert "const translate" in markdown


def test_format_extraction_result_java_code(generator):
    """Test code detection for Java"""
    result = ExtractionResult(
        target_name="java_code",
        success=True,
        content="public class Translator { private String text; }",
        confidence=0.9
    )

    markdown = generator._format_extraction_result(result)

    # Check Java code block
    assert "```java" in markdown
    assert "public class Translator" in markdown


def test_generate_enhanced_multiple_papers(
    generator,
    research_topic,
    extracted_paper_with_pdf,
    extracted_paper_without_pdf
):
    """Test generating markdown with multiple papers"""
    markdown = generator.generate_enhanced(
        extracted_papers=[extracted_paper_with_pdf, extracted_paper_without_pdf],
        topic=research_topic,
        run_id="test-run"
    )

    # Check both papers are present
    assert "Tree of Thoughts for Machine Translation" in markdown
    assert "Abstract Only Paper" in markdown

    # Check separation
    assert markdown.count("---") >= 3  # Frontmatter + separators


def test_generate_enhanced_empty_papers_list(generator, research_topic):
    """Test generating markdown with no papers"""
    markdown = generator.generate_enhanced(
        extracted_papers=[],
        topic=research_topic,
        run_id="test-run"
    )

    # Check structure is still valid
    assert "# Research Brief:" in markdown
    assert "Papers Found:** 0" in markdown
    assert "Papers Processed:** 0" in markdown


def test_generate_enhanced_handles_missing_venue(generator, research_topic, paper_metadata):
    """Test paper formatting when venue is missing"""
    paper_metadata.venue = None
    extracted = ExtractedPaper(metadata=paper_metadata, pdf_available=False)

    markdown = generator._format_extracted_paper(extracted, 1)

    # Venue line should not be present
    assert "**Venue:**" not in markdown


def test_generate_enhanced_handles_missing_year(generator, research_topic, paper_metadata):
    """Test paper formatting when year is missing"""
    paper_metadata.year = None
    extracted = ExtractedPaper(metadata=paper_metadata, pdf_available=False)

    markdown = generator._format_extracted_paper(extracted, 1)

    # Should show "Unknown"
    assert "**Published:** Unknown" in markdown


def test_generate_enhanced_handles_no_authors(generator, research_topic, paper_metadata):
    """Test paper formatting when authors list is empty"""
    paper_metadata.authors = []
    extracted = ExtractedPaper(metadata=paper_metadata, pdf_available=False)

    markdown = generator._format_extracted_paper(extracted, 1)

    # Should show empty string or handle gracefully
    assert "**Authors:**" in markdown

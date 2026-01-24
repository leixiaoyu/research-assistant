"""Unit tests for extraction data models (Phase 2)

Tests for:
- ExtractionTarget
- ExtractionResult
- PaperExtraction
- ExtractedPaper
"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from src.models.extraction import (
    ExtractionTarget,
    ExtractionResult,
    PaperExtraction,
    ExtractedPaper
)
from src.models.paper import PaperMetadata, Author


def test_extraction_target_valid():
    """Test valid ExtractionTarget creation"""
    target = ExtractionTarget(
        name="system_prompts",
        description="Extract all system prompts",
        output_format="list",
        required=True,
        examples=["Example prompt 1", "Example prompt 2"]
    )

    assert target.name == "system_prompts"
    assert target.description == "Extract all system prompts"
    assert target.output_format == "list"
    assert target.required is True
    assert len(target.examples) == 2


def test_extraction_target_defaults():
    """Test ExtractionTarget with defaults"""
    target = ExtractionTarget(
        name="code",
        description="Extract code"
    )

    assert target.output_format == "text"
    assert target.required is False
    assert target.examples is None


def test_extraction_target_invalid_format():
    """Test ExtractionTarget with invalid output_format"""
    with pytest.raises(ValidationError):
        ExtractionTarget(
            name="test",
            description="Test",
            output_format="invalid"  # Not in allowed values
        )


def test_extraction_target_empty_name():
    """Test ExtractionTarget with empty name"""
    with pytest.raises(ValidationError):
        ExtractionTarget(
            name="",
            description="Test"
        )


def test_extraction_result_success():
    """Test successful ExtractionResult"""
    result = ExtractionResult(
        target_name="system_prompts",
        success=True,
        content=["Prompt 1", "Prompt 2"],
        confidence=0.95
    )

    assert result.target_name == "system_prompts"
    assert result.success is True
    assert len(result.content) == 2
    assert result.confidence == 0.95
    assert result.error is None


def test_extraction_result_failure():
    """Test failed ExtractionResult"""
    result = ExtractionResult(
        target_name="code",
        success=False,
        content=None,
        confidence=0.0,
        error="No code found"
    )

    assert result.success is False
    assert result.content is None
    assert result.error == "No code found"


def test_extraction_result_confidence_validation():
    """Test confidence must be between 0 and 1"""
    # Valid confidences
    ExtractionResult(target_name="test", success=True, confidence=0.0)
    ExtractionResult(target_name="test", success=True, confidence=1.0)
    ExtractionResult(target_name="test", success=True, confidence=0.5)

    # Invalid confidences
    with pytest.raises(ValidationError):
        ExtractionResult(target_name="test", success=True, confidence=-0.1)

    with pytest.raises(ValidationError):
        ExtractionResult(target_name="test", success=True, confidence=1.1)


def test_paper_extraction_valid():
    """Test valid PaperExtraction"""
    results = [
        ExtractionResult(
            target_name="system_prompts",
            success=True,
            content=["Prompt 1"],
            confidence=0.9
        ),
        ExtractionResult(
            target_name="code",
            success=True,
            content="def example(): pass",
            confidence=0.85
        )
    ]

    extraction = PaperExtraction(
        paper_id="2301.12345",
        extraction_results=results,
        tokens_used=45000,
        cost_usd=0.15
    )

    assert extraction.paper_id == "2301.12345"
    assert len(extraction.extraction_results) == 2
    assert extraction.tokens_used == 45000
    assert extraction.cost_usd == 0.15
    assert isinstance(extraction.extraction_timestamp, datetime)


def test_paper_extraction_defaults():
    """Test PaperExtraction with defaults"""
    extraction = PaperExtraction(paper_id="test")

    assert extraction.extraction_results == []
    assert extraction.tokens_used == 0
    assert extraction.cost_usd == 0.0
    assert isinstance(extraction.extraction_timestamp, datetime)


def test_paper_extraction_negative_tokens():
    """Test PaperExtraction rejects negative tokens"""
    with pytest.raises(ValidationError):
        PaperExtraction(
            paper_id="test",
            tokens_used=-100
        )


def test_paper_extraction_negative_cost():
    """Test PaperExtraction rejects negative cost"""
    with pytest.raises(ValidationError):
        PaperExtraction(
            paper_id="test",
            cost_usd=-0.01
        )


def test_extracted_paper_with_pdf():
    """Test ExtractedPaper with PDF and extraction"""
    metadata = PaperMetadata(
        paper_id="2301.12345",
        title="Test Paper",
        abstract="Test abstract",
        url="https://example.com/paper",
        authors=[Author(name="John Doe")],
        year=2023,
        citation_count=10,
        venue="ArXiv"
    )

    extraction = PaperExtraction(
        paper_id="2301.12345",
        tokens_used=50000,
        cost_usd=0.20
    )

    extracted = ExtractedPaper(
        metadata=metadata,
        pdf_available=True,
        pdf_path="/temp/pdfs/2301.12345.pdf",
        markdown_path="/temp/markdown/2301.12345.md",
        extraction=extraction
    )

    assert extracted.metadata.paper_id == "2301.12345"
    assert extracted.pdf_available is True
    assert extracted.pdf_path == "/temp/pdfs/2301.12345.pdf"
    assert extracted.markdown_path == "/temp/markdown/2301.12345.md"
    assert extracted.extraction.tokens_used == 50000


def test_extracted_paper_without_pdf():
    """Test ExtractedPaper without PDF (abstract only)"""
    metadata = PaperMetadata(
        paper_id="test",
        title="Test",
        url="https://example.com",
        authors=[],
        citation_count=0
    )

    extracted = ExtractedPaper(
        metadata=metadata,
        pdf_available=False
    )

    assert extracted.pdf_available is False
    assert extracted.pdf_path is None
    assert extracted.markdown_path is None
    assert extracted.extraction is None


def test_extracted_paper_defaults():
    """Test ExtractedPaper with minimal metadata"""
    metadata = PaperMetadata(
        paper_id="test",
        title="Test",
        url="https://example.com",
        authors=[],
        citation_count=0
    )

    extracted = ExtractedPaper(metadata=metadata)

    assert extracted.pdf_available is False
    assert extracted.pdf_path is None
    assert extracted.markdown_path is None
    assert extracted.extraction is None

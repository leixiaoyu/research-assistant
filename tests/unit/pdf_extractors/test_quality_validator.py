"""Unit tests for quality validator."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.services.pdf_extractors.validators.quality_validator import QualityValidator


@pytest.fixture
def validator():
    return QualityValidator()


def test_score_extraction_empty(validator):
    """Empty or very short markdown should score 0.0."""
    assert validator.score_extraction("", Path("dummy.pdf")) == 0.0
    assert validator.score_extraction("Short", Path("dummy.pdf")) == 0.0


def test_score_extraction_high_quality(validator):
    """A well-structured document should score reasonably high."""
    # ~3000 chars, 2 pages -> 1500 chars/page (Ideal)
    # 5 headers/lists -> 10 per 1k chars (Ideal)
    # 1 code block, 1 table -> Good
    markdown = """# Introduction

This is a paper about something complex.

## Methodology
- Item 1
- Item 2
- Item 3
- Item 4
- Item 5

```python
def code():
    pass
```

| Metric | Value |
|--------|-------|
| Score  | 0.95  |

""" + (
        "Text content. " * 300
    )

    score = validator.score_extraction(markdown, Path("dummy.pdf"), page_count=2)
    # With 5+ headers/lists and good density, it should be above 0.65
    assert score >= 0.65


def test_calculate_text_density_score(validator):
    """Test text density scoring logic."""
    # Ideal range (500-2000)
    assert validator._calculate_text_density_score("A" * 1000, 1) == 1.0

    # Very short
    assert validator._calculate_text_density_score("A" * 50, 1) == 0.0

    # Outside range (decay)
    # 2500 chars / 1 page = 2500 chars/page.
    # 1.0 - abs(2500 - 1250) / 2500 = 1.0 - 0.5 = 0.5
    score_outside = validator._calculate_text_density_score("A" * 2500, 1)
    assert 0.4 < score_outside < 0.6


def test_calculate_structure_score(validator):
    """Test structural element scoring."""
    # Ideal range (~10 per 1k)
    markdown = "# H1\n# H2\n- L1\n- L2\n- L3\n" + (
        "A" * 400
    )  # 5 structures per ~500 chars
    assert validator._calculate_structure_score(markdown) == 1.0

    # Low structure
    # 0 structures / 1k chars -> 1.0 - abs(0-10)/20 = 0.5
    assert validator._calculate_structure_score("A" * 1000) <= 0.5


def test_calculate_code_detection_score(validator):
    """Test code detection scoring."""
    # No code
    assert validator._calculate_code_detection_score("Plain text") == 0.5

    # With code
    markdown = "```python\nprint(1)\n```\n"
    assert validator._calculate_code_detection_score(markdown) > 0.5


def test_calculate_table_detection_score(validator):
    """Test table detection scoring."""
    # No tables
    assert validator._calculate_table_detection_score("Plain text") == 0.5

    # With table
    markdown = """
| A | B |
|---|---|
| 1 | 2 |
"""
    assert validator._calculate_table_detection_score(markdown) > 0.5


def test_calculate_text_density_score_extremes(validator):
    """Test density score with extreme values."""
    # Unknown page count
    assert validator._calculate_text_density_score("Some text", 0) == 0.5

    # Very long text
    assert validator._calculate_text_density_score("A" * 10000, 1) == 0.0


def test_calculate_structure_score_extremes(validator):
    """Test structure score with extreme values."""
    # Very short text (division by zero safety)
    assert validator._calculate_structure_score("A") == 0.5

    # Too many structures (decay)
    markdown = ("# H\n" * 100) + "A"
    assert validator._calculate_structure_score(markdown) < 1.0


def test_get_page_count_mock(validator):
    """Test page count helper with mocks."""
    # Mock fitz module before it's imported
    mock_fitz = MagicMock()
    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 5
    mock_fitz.open.return_value = mock_doc

    with patch.dict("sys.modules", {"fitz": mock_fitz}):
        assert validator._get_page_count(Path("test.pdf")) == 5
        mock_doc.close.assert_called_once()

    # Test failure
    mock_fitz_error = MagicMock()
    mock_fitz_error.open.side_effect = Exception("Failed")

    with patch.dict("sys.modules", {"fitz": mock_fitz_error}):
        assert validator._get_page_count(Path("test.pdf")) == 0


def test_score_extraction_page_count_lookup(validator):
    """Test score_extraction triggers page count lookup if not provided."""
    with patch.object(validator, "_get_page_count", return_value=3) as mock_get:
        markdown = "Text content. " * 300
        validator.score_extraction(markdown, Path("test.pdf"))
        mock_get.assert_called_once_with(Path("test.pdf"))

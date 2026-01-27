"""Unit tests for PDFPlumber Extractor."""

import pytest
import sys
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from src.services.pdf_extractors.pdfplumber_extractor import PDFPlumberExtractor
from src.models.pdf_extraction import PDFBackend


@pytest.fixture
def extractor():
    return PDFPlumberExtractor()


def test_name(extractor):
    assert extractor.name == PDFBackend.PDFPLUMBER


def test_validate_setup_success(extractor):
    with patch.dict("sys.modules", {"pdfplumber": Mock()}):
        assert extractor.validate_setup() is True


def test_validate_setup_failure(extractor):
    # Mock import failure for pdfplumber ONLY
    orig_import = __import__

    def mock_import(name, *args, **kwargs):
        if name == "pdfplumber":
            raise ImportError
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        with patch.dict("sys.modules"):
            if "pdfplumber" in sys.modules:
                del sys.modules["pdfplumber"]
            assert extractor.validate_setup() is False


@pytest.mark.asyncio
async def test_extract_not_installed(extractor):
    with patch.object(extractor, "validate_setup", return_value=False):
        result = await extractor.extract(Path("test.pdf"))
        assert result.success is False
        assert "not installed" in result.error


@pytest.mark.asyncio
async def test_extract_success(extractor):
    # Mock pdfplumber
    mock_pdf = MagicMock()
    mock_page = Mock()
    mock_page.extract_text.return_value = "Page text"
    mock_page.extract_tables.return_value = []

    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__.return_value = mock_pdf

    with patch.dict(
        "sys.modules", {"pdfplumber": Mock(open=Mock(return_value=mock_pdf))}
    ):
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = 1024

                result = await extractor.extract(Path("test.pdf"))

                assert result.success is True
                assert "Page text" in result.markdown
                assert result.metadata.page_count == 1


@pytest.mark.asyncio
async def test_extract_with_table(extractor):
    mock_pdf = MagicMock()
    mock_page = Mock()
    mock_page.extract_text.return_value = ""
    # Table: 2 rows, 2 cols
    mock_page.extract_tables.return_value = [[["Header1", "Header2"], ["Val1", "Val2"]]]

    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__.return_value = mock_pdf

    with patch.dict(
        "sys.modules", {"pdfplumber": Mock(open=Mock(return_value=mock_pdf))}
    ):
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = 1024

                result = await extractor.extract(Path("test.pdf"))

                assert result.success is True
                assert "| Header1 | Header2 |" in result.markdown
                assert "| Val1 | Val2 |" in result.markdown
                assert result.metadata.tables_found == 1


@pytest.mark.asyncio
async def test_extract_file_not_found(extractor):
    """Test extraction when PDF file doesn't exist"""
    with patch.object(extractor, "validate_setup", return_value=True):
        with patch.object(Path, "exists", return_value=False):
            result = await extractor.extract(Path("nonexistent.pdf"))
            assert result.success is False
            assert "not found" in result.error


@pytest.mark.asyncio
async def test_extract_general_exception(extractor):
    """Test handling of unexpected exceptions during extraction"""
    with patch.object(Path, "exists", return_value=True):
        with patch.dict(
            "sys.modules",
            {
                "pdfplumber": Mock(
                    open=Mock(side_effect=RuntimeError("Unexpected error"))
                )
            },
        ):
            result = await extractor.extract(Path("test.pdf"))
            assert result.success is False
            assert "Unexpected error" in result.error


@pytest.mark.asyncio
async def test_extract_empty_table(extractor):
    """Test handling of empty tables"""
    mock_pdf = MagicMock()
    mock_page = Mock()
    mock_page.extract_text.return_value = "Text"
    # Empty table (less than 2 rows)
    mock_page.extract_tables.return_value = [[["Header1"]]]

    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__.return_value = mock_pdf

    with patch.dict(
        "sys.modules", {"pdfplumber": Mock(open=Mock(return_value=mock_pdf))}
    ):
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = 1024

                result = await extractor.extract(Path("test.pdf"))

                # Should succeed but skip the invalid table
                assert result.success is True
                assert "Text" in result.markdown


@pytest.mark.asyncio
async def test_extract_malformed_table(extractor):
    """Test handling of malformed tables that raise exceptions during conversion"""
    mock_pdf = MagicMock()
    mock_page = Mock()
    mock_page.extract_text.return_value = "Text"
    # Malformed table that will cause exception in _table_to_markdown
    mock_page.extract_tables.return_value = [[None, None]]

    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__.return_value = mock_pdf

    with patch.dict(
        "sys.modules", {"pdfplumber": Mock(open=Mock(return_value=mock_pdf))}
    ):
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = 1024

                result = await extractor.extract(Path("test.pdf"))

                # Should succeed, table conversion error is caught
                assert result.success is True

"""Unit tests for PyMuPDF Extractor."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from src.services.pdf_extractors.pymupdf_extractor import PyMuPDFExtractor
from src.models.pdf_extraction import PDFBackend


@pytest.fixture
def extractor():
    return PyMuPDFExtractor()


def test_name(extractor):
    assert extractor.name == PDFBackend.PYMUPDF


def test_validate_setup_success(extractor):
    with patch.dict("sys.modules", {"fitz": Mock()}):
        assert extractor.validate_setup() is True


def test_validate_setup_failure(extractor):
    with patch.dict("sys.modules", {"fitz": None}):
        # Mock import to fail only for fitz
        orig_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == "fitz":
                raise ImportError
            return orig_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            assert extractor.validate_setup() is False


@pytest.mark.asyncio
async def test_extract_not_installed(extractor):
    with patch.object(extractor, "validate_setup", return_value=False):
        result = await extractor.extract(Path("test.pdf"))
        assert result.success is False
        assert "not installed" in result.error


@pytest.mark.asyncio
async def test_extract_success(extractor):
    # Mock fitz
    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 1

    mock_page = Mock()
    # (x0, y0, x1, y1, text, block_no, block_type)
    mock_page.get_text.return_value = [
        (0, 0, 0, 0, "Hello World", 0, 0),
        (0, 0, 0, 0, "    def code():\n        pass", 1, 0),
    ]

    mock_tabs = Mock()
    mock_tabs.tables = []
    mock_page.find_tables.return_value = mock_tabs

    mock_doc.__iter__.return_value = iter([mock_page])

    with patch.dict("sys.modules", {"fitz": Mock(open=Mock(return_value=mock_doc))}):
        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 1024

            result = await extractor.extract(Path("test.pdf"))

            assert result.success is True
            assert "Hello World" in result.markdown
            assert "```" in result.markdown
            assert result.metadata.page_count == 1
            assert result.metadata.code_blocks_found == 1


@pytest.mark.asyncio
async def test_extract_with_table(extractor):
    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 1

    mock_page = Mock()
    mock_page.get_text.return_value = []

    mock_table = Mock()
    mock_table.extract.return_value = [["Col1", "Col2"], ["Val1", "Val2"]]

    mock_tabs = Mock()
    mock_tabs.tables = [mock_table]
    mock_page.find_tables.return_value = mock_tabs

    mock_doc.__iter__.return_value = iter([mock_page])

    with patch.dict("sys.modules", {"fitz": Mock(open=Mock(return_value=mock_doc))}):
        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 1024

            result = await extractor.extract(Path("test.pdf"))

            assert result.success is True
            assert "| Col1 | Col2 |" in result.markdown
            assert result.metadata.tables_found == 1

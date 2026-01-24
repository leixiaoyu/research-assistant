"""Unit tests for PDF Service (Phase 2)

Tests for:
- PDF download with retry logic
- PDF validation
- PDF to markdown conversion
- Temporary file management
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock
import aiohttp

from src.services.pdf_service import PDFService
from src.utils.exceptions import (
    PDFDownloadError,
    FileSizeError,
    PDFValidationError,
    ConversionError
)


@pytest.fixture
def temp_dir(tmp_path):
    """Create temporary directory for tests"""
    return tmp_path / "test_temp"


@pytest.fixture
def pdf_service(temp_dir):
    """Create PDFService instance"""
    return PDFService(
        temp_dir=temp_dir,
        max_size_mb=50,
        timeout_seconds=300
    )


def test_pdf_service_initialization(pdf_service, temp_dir):
    """Test PDFService initializes correctly"""
    assert pdf_service.temp_dir == temp_dir
    assert pdf_service.max_size_bytes == 50 * 1024 * 1024
    assert pdf_service.pdf_dir.exists()
    assert pdf_service.markdown_dir.exists()


def test_validate_pdf_valid(pdf_service, temp_dir):
    """Test validate_pdf with valid PDF"""
    # Create a valid PDF file (with PDF magic bytes)
    pdf_path = temp_dir / "test.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b'%PDF-1.4\nTest content')

    assert pdf_service.validate_pdf(pdf_path) is True


def test_validate_pdf_empty_file(pdf_service, temp_dir):
    """Test validate_pdf with empty file"""
    pdf_path = temp_dir / "empty.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b'')

    assert pdf_service.validate_pdf(pdf_path) is False


def test_validate_pdf_invalid_magic_bytes(pdf_service, temp_dir):
    """Test validate_pdf with wrong magic bytes"""
    pdf_path = temp_dir / "invalid.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b'NOT A PDF FILE')

    assert pdf_service.validate_pdf(pdf_path) is False


def test_validate_pdf_missing_file(pdf_service, temp_dir):
    """Test validate_pdf with non-existent file"""
    pdf_path = temp_dir / "missing.pdf"
    assert pdf_service.validate_pdf(pdf_path) is False


@pytest.mark.asyncio
async def test_download_pdf_rejects_http(pdf_service):
    """Test download_pdf rejects HTTP URLs"""
    with pytest.raises(PDFDownloadError) as exc_info:
        await pdf_service.download_pdf(
            url="http://example.com/paper.pdf",
            paper_id="test"
        )
    assert "Only HTTPS URLs allowed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_download_pdf_success(pdf_service):
    """Test successful PDF download"""
    pdf_content = b'%PDF-1.4\nTest PDF content here'

    # Mock aiohttp response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {'content-length': str(len(pdf_content))}
    mock_response.content.iter_chunked = AsyncMock(
        return_value=[pdf_content]
    )

    # Mock session
    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None
    mock_session.get = AsyncMock()
    mock_session.get.return_value.__aenter__.return_value = mock_response
    mock_session.get.return_value.__aexit__.return_value = None

    with patch('aiohttp.ClientSession', return_value=mock_session):
        pdf_path = await pdf_service.download_pdf(
            url="https://example.com/paper.pdf",
            paper_id="test123"
        )

    assert pdf_path.exists()
    assert pdf_path.name == "test123.pdf"
    assert pdf_path.read_bytes() == pdf_content


@pytest.mark.asyncio
async def test_download_pdf_file_too_large(pdf_service):
    """Test download_pdf rejects oversized files"""
    # Mock response with size > max_size_bytes
    large_size = pdf_service.max_size_bytes + 1000

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {'content-length': str(large_size)}

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None
    mock_session.get = AsyncMock()
    mock_session.get.return_value.__aenter__.return_value = mock_response
    mock_session.get.return_value.__aexit__.return_value = None

    with patch('aiohttp.ClientSession', return_value=mock_session):
        with pytest.raises(FileSizeError) as exc_info:
            await pdf_service.download_pdf(
                url="https://example.com/large.pdf",
                paper_id="test"
            )
    assert "PDF too large" in str(exc_info.value)


@pytest.mark.asyncio
async def test_download_pdf_http_error(pdf_service):
    """Test download_pdf handles HTTP errors"""
    mock_response = AsyncMock()
    mock_response.status = 404

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None
    mock_session.get = AsyncMock()
    mock_session.get.return_value.__aenter__.return_value = mock_response
    mock_session.get.return_value.__aexit__.return_value = None

    with patch('aiohttp.ClientSession', return_value=mock_session):
        with pytest.raises(PDFDownloadError) as exc_info:
            await pdf_service.download_pdf(
                url="https://example.com/missing.pdf",
                paper_id="test"
            )
    assert "HTTP 404" in str(exc_info.value)


def test_convert_to_markdown_pdf_not_found(pdf_service):
    """Test convert_to_markdown with missing PDF"""
    missing_path = Path("/nonexistent/paper.pdf")

    with pytest.raises(ConversionError) as exc_info:
        pdf_service.convert_to_markdown(missing_path, "test")
    assert "PDF file not found" in str(exc_info.value)


def test_convert_to_markdown_success(pdf_service, temp_dir):
    """Test successful PDF to markdown conversion"""
    # Create a test PDF
    pdf_path = pdf_service.pdf_dir / "test.pdf"
    pdf_path.write_bytes(b'%PDF-1.4\nTest')

    # Create expected markdown output
    expected_md = pdf_service.markdown_dir / "test.md"

    # Mock subprocess.run to simulate marker-pdf
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch('subprocess.run', return_value=mock_result):
        # Create the markdown file that marker would create
        expected_md.write_text("# Test Markdown\n\nContent here")

        md_path = pdf_service.convert_to_markdown(pdf_path, "test")

    assert md_path.exists()
    assert md_path.suffix == ".md"


def test_convert_to_markdown_timeout(pdf_service, temp_dir):
    """Test convert_to_markdown handles timeout"""
    import subprocess

    pdf_path = pdf_service.pdf_dir / "test.pdf"
    pdf_path.write_bytes(b'%PDF-1.4\nTest')

    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired("marker_single", 300)):
        with pytest.raises(ConversionError) as exc_info:
            pdf_service.convert_to_markdown(pdf_path, "test")
    assert "timeout" in str(exc_info.value).lower()


def test_cleanup_temp_files(pdf_service, temp_dir):
    """Test cleanup_temp_files removes files"""
    # Create test files
    pdf_file = pdf_service.pdf_dir / "test123.pdf"
    md_file = pdf_service.markdown_dir / "test123.md"

    pdf_file.write_bytes(b'%PDF')
    md_file.write_text("# Test")

    # Cleanup without keeping PDFs
    pdf_service.cleanup_temp_files("test123", keep_pdfs=False)

    assert not pdf_file.exists()
    assert not md_file.exists()


def test_cleanup_temp_files_keep_pdfs(pdf_service, temp_dir):
    """Test cleanup_temp_files keeps PDFs when requested"""
    # Create test files
    pdf_file = pdf_service.pdf_dir / "test456.pdf"
    md_file = pdf_service.markdown_dir / "test456.md"

    pdf_file.write_bytes(b'%PDF')
    md_file.write_text("# Test")

    # Cleanup keeping PDFs
    pdf_service.cleanup_temp_files("test456", keep_pdfs=True)

    assert pdf_file.exists()  # PDF should remain
    assert not md_file.exists()  # Markdown should be deleted

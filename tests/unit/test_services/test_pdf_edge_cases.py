"""PDF Service Edge Case Tests

Additional tests for PDF service validation and sanitization.
"""

import pytest
from pathlib import Path
import tempfile

from src.services.pdf_service import PDFService
from src.utils.exceptions import PDFDownloadError


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def pdf_service(temp_dir):
    """Create PDF service instance"""
    return PDFService(temp_dir=temp_dir, max_size_mb=10, timeout_seconds=30)


@pytest.fixture
def valid_pdf_bytes():
    """Create valid PDF magic bytes"""
    return b"%PDF-1.4\n%test content\n%%EOF"


class TestPDFValidation:
    """Tests for PDF validation functionality"""

    def test_validate_pdf_with_valid_file(self, pdf_service, temp_dir, valid_pdf_bytes):
        """Test validation passes for valid PDF"""
        pdf_path = temp_dir / "valid.pdf"
        pdf_path.write_bytes(valid_pdf_bytes)

        result = pdf_service.validate_pdf(pdf_path)
        assert result is True

    def test_validate_pdf_with_empty_file(self, pdf_service, temp_dir):
        """Test validation fails for empty file"""
        pdf_path = temp_dir / "empty.pdf"
        pdf_path.write_bytes(b"")

        result = pdf_service.validate_pdf(pdf_path)
        assert result is False

    def test_validate_pdf_with_non_pdf_content(self, pdf_service, temp_dir):
        """Test validation fails for non-PDF content"""
        pdf_path = temp_dir / "not_pdf.pdf"
        pdf_path.write_bytes(b"This is not a PDF file")

        result = pdf_service.validate_pdf(pdf_path)
        assert result is False

    def test_validate_pdf_with_html_content(self, pdf_service, temp_dir):
        """Test validation fails for HTML content"""
        pdf_path = temp_dir / "fake.pdf"
        pdf_path.write_bytes(b"<!DOCTYPE html><html><body>Not a PDF</body></html>")

        result = pdf_service.validate_pdf(pdf_path)
        assert result is False

    def test_validate_pdf_nonexistent_file(self, pdf_service, temp_dir):
        """Test validation handles nonexistent file"""
        pdf_path = temp_dir / "nonexistent.pdf"

        result = pdf_service.validate_pdf(pdf_path)
        assert result is False


class TestFilenameSanitization:
    """Tests for filename sanitization functionality"""

    def test_sanitize_removes_path_traversal(self, pdf_service):
        """Test sanitization removes path traversal attempts"""
        dangerous_name = "../../../etc/passwd"
        sanitized = pdf_service._sanitize_filename(dangerous_name)

        assert "/" not in sanitized
        assert ".." not in sanitized

    def test_sanitize_removes_null_bytes(self, pdf_service):
        """Test sanitization removes null bytes"""
        dangerous_name = "file\x00name.pdf"
        sanitized = pdf_service._sanitize_filename(dangerous_name)

        assert "\x00" not in sanitized

    def test_sanitize_preserves_extension(self, pdf_service):
        """Test sanitization preserves file extension"""
        name = "paper_v2.0_(final).pdf"
        sanitized = pdf_service._sanitize_filename(name)

        assert sanitized.endswith(".pdf")

    def test_sanitize_handles_hidden_files(self, pdf_service):
        """Test sanitization makes hidden files visible"""
        hidden_name = ".hidden_file.pdf"
        sanitized = pdf_service._sanitize_filename(hidden_name)

        assert not sanitized.startswith(".")


class TestDownloadErrors:
    """Tests for download error handling"""

    @pytest.mark.asyncio
    async def test_download_non_https_url_rejected(self, pdf_service):
        """Test that non-HTTPS URLs are rejected"""
        with pytest.raises(PDFDownloadError) as exc_info:
            await pdf_service.download_pdf(
                url="http://example.com/paper.pdf", paper_id="test123"
            )

        assert "HTTPS" in str(exc_info.value)


class TestServiceInitialization:
    """Tests for service initialization"""

    def test_creates_temp_directories(self, temp_dir):
        """Test that service creates required temp directories"""
        service = PDFService(temp_dir=temp_dir)

        assert service.pdf_dir.exists()
        assert service.markdown_dir.exists()

    def test_resolves_temp_dir_to_absolute(self, temp_dir):
        """Test that temp_dir is resolved to absolute path"""
        service = PDFService(temp_dir=temp_dir)

        assert service.temp_dir.is_absolute()

    def test_custom_size_limit(self, temp_dir):
        """Test custom file size limit"""
        service = PDFService(temp_dir=temp_dir, max_size_mb=5)

        expected_bytes = 5 * 1024 * 1024
        assert service.max_size_bytes == expected_bytes

    def test_custom_timeout(self, temp_dir):
        """Test custom timeout setting"""
        service = PDFService(temp_dir=temp_dir, timeout_seconds=600)

        assert service.timeout_seconds == 600

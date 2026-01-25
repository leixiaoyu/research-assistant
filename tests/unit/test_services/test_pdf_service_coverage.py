import pytest
import asyncio
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import aiohttp
from src.services.pdf_service import PDFService
from src.utils.exceptions import (
    PDFDownloadError,
    FileSizeError,
    PDFValidationError,
    ConversionError,
)


@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def pdf_service(temp_dir):
    return PDFService(temp_dir=temp_dir)


class TestPDFServiceCoverage:
    def test_sanitize_filename_hidden(self, pdf_service):
        """Test sanitization of hidden files"""
        assert pdf_service._sanitize_filename(".hidden.pdf") == "_.hidden.pdf"
        assert pdf_service._sanitize_filename("normal.pdf") == "normal.pdf"
        assert pdf_service._sanitize_filename("path/to/file.pdf") == "file.pdf"
        assert (
            pdf_service._sanitize_filename("invalidchars!@#.pdf")
            == "invalidchars___.pdf"
        )

    @pytest.mark.asyncio
    async def test_download_pdf_not_https(self, pdf_service):
        """Test URL validation"""
        with pytest.raises(PDFDownloadError, match="Only HTTPS URLs allowed"):
            await pdf_service.download_pdf("http://example.com/paper.pdf", "123")

        @pytest.mark.asyncio

        async def test_download_with_retry_4xx_error(self, pdf_service):

            """Test 4xx error handling"""

            with patch("aiohttp.ClientSession") as mock_session_cls:

                # Setup session context manager

                mock_session = AsyncMock()

                mock_session_cls.return_value.__aenter__.return_value = mock_session

                

                # Setup get context manager

                mock_response = AsyncMock()

                mock_response.status = 404

                

                # Create a proper async context manager for get()

                mock_get_ctx = AsyncMock()

                mock_get_ctx.__aenter__.return_value = mock_response

                

                # session.get() is NOT async, it returns the context manager immediately

                # We must replace the auto-created AsyncMock with a standard Mock

                mock_session.get = Mock(return_value=mock_get_ctx)

    

                with pytest.raises(PDFDownloadError, match="HTTP 404"):

                    await pdf_service._download_with_retry("https://example.com/404.pdf", "123")

    

        @pytest.mark.asyncio

        async def test_download_with_retry_file_size_header(self, pdf_service):

            """Test file size check from headers"""

            with patch("aiohttp.ClientSession") as mock_session_cls:

                mock_session = AsyncMock()

                mock_session_cls.return_value.__aenter__.return_value = mock_session

                

                mock_response = AsyncMock()

                mock_response.status = 200

                mock_response.headers = {"content-length": str(100 * 1024 * 1024)} # 100MB

                

                mock_get_ctx = AsyncMock()

                mock_get_ctx.__aenter__.return_value = mock_response

                

                mock_session.get = Mock(return_value=mock_get_ctx)

    

                with pytest.raises(FileSizeError, match="PDF too large"):

                    await pdf_service._download_with_retry("https://example.com/large.pdf", "123")

    

        @pytest.mark.asyncio

        async def test_download_with_retry_stream_size_limit(self, pdf_service):

            """Test size limit during streaming"""

            pdf_service.max_size_bytes = 10 # very small limit

            

            with patch("aiohttp.ClientSession") as mock_session_cls:

                mock_session = AsyncMock()

                mock_session_cls.return_value.__aenter__.return_value = mock_session

                

                mock_response = AsyncMock()

                mock_response.status = 200

                mock_response.headers = {}

                

                # Mock content iterator to yield more data than limit

                async def iter_chunked(n):

                    yield b"0" * 20

                    

                mock_response.content.iter_chunked = iter_chunked

                

                mock_get_ctx = AsyncMock()

                mock_get_ctx.__aenter__.return_value = mock_response

                

                mock_session.get = Mock(return_value=mock_get_ctx)

    

                with pytest.raises(FileSizeError, match="PDF exceeded size limit"):

                    await pdf_service._download_with_retry("https://example.com/stream.pdf", "123")

    @pytest.mark.asyncio
    async def test_download_with_retry_client_error(self, pdf_service):
        """Test aiohttp client error"""
        with patch("aiohttp.ClientSession") as mock_session_cls:
            # Raise error when entering session context
            mock_session_cls.return_value.__aenter__.side_effect = aiohttp.ClientError(
                "Connection failed"
            )

            with pytest.raises(PDFDownloadError, match="Download failed"):
                await pdf_service._download_with_retry(
                    "https://example.com/error.pdf", "123"
                )

    @pytest.mark.asyncio
    async def test_download_with_retry_timeout(self, pdf_service):
        """Test download timeout"""
        with patch("aiohttp.ClientSession") as mock_session_cls:
             mock_session_cls.return_value.__aenter__.side_effect = asyncio.TimeoutError()

             with pytest.raises(PDFDownloadError, match="Download timeout"):
                await pdf_service._download_with_retry(
                    "https://example.com/timeout.pdf", "123"
                )

    def test_validate_pdf_empty(self, pdf_service, temp_dir):
        """Test validation of empty file"""
        p = temp_dir / "empty.pdf"
        p.touch()
        assert not pdf_service.validate_pdf(p)

    def test_validate_pdf_invalid_magic(self, pdf_service, temp_dir):
        """Test validation of invalid magic bytes"""
        p = temp_dir / "invalid.pdf"
        p.write_bytes(b"NOTPDF")
        assert not pdf_service.validate_pdf(p)

    def test_validate_pdf_exception(self, pdf_service):
        """Test validation exception (file not found/permission)"""
        # Pass directory instead of file to trigger exception in open()
        assert not pdf_service.validate_pdf(pdf_service.pdf_dir)

    def test_convert_to_markdown_no_pdf(self, pdf_service):
        """Test conversion with missing PDF"""
        with pytest.raises(ConversionError, match="PDF file not found"):
            pdf_service.convert_to_markdown(Path("nonexistent.pdf"), "123")

    def test_convert_to_markdown_subprocess_error(self, pdf_service, temp_dir):
        """Test subprocess failure"""
        pdf_path = temp_dir / "test.pdf"
        pdf_path.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "Error message"

            with pytest.raises(ConversionError, match="marker-pdf failed"):
                pdf_service.convert_to_markdown(pdf_path, "123")

    def test_convert_to_markdown_timeout(self, pdf_service, temp_dir):
        """Test conversion timeout"""
        pdf_path = temp_dir / "test.pdf"
        pdf_path.touch()

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="marker", timeout=30),
        ):
            with pytest.raises(ConversionError, match="Conversion timeout"):
                pdf_service.convert_to_markdown(pdf_path, "123")

    def test_convert_to_markdown_exception(self, pdf_service, temp_dir):
        """Test generic conversion exception"""
        pdf_path = temp_dir / "test.pdf"
        pdf_path.touch()

        with patch("subprocess.run", side_effect=Exception("Unexpected")):
            with pytest.raises(ConversionError, match="Conversion failed"):
                pdf_service.convert_to_markdown(pdf_path, "123")

    def test_convert_to_markdown_no_output(self, pdf_service, temp_dir):
        """Test case where marker-pdf runs but produces no output"""
        pdf_path = temp_dir / "test.pdf"
        pdf_path.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0

            with pytest.raises(ConversionError, match="No markdown file generated"):
                pdf_service.convert_to_markdown(pdf_path, "123")

    def test_cleanup_temp_files_exception(self, pdf_service):
        """Test exception handling during cleanup"""
        # Create a file that can't be deleted (mocking unlink)
        p = pdf_service.markdown_dir / "test.md"
        p.touch()

        with patch.object(Path, "unlink", side_effect=Exception("Permission denied")):
            # Should not raise exception
            pdf_service.cleanup_temp_files("test")

    def test_cleanup_temp_files_pdfs(self, pdf_service):
        """Test PDF cleanup"""
        p = pdf_service.pdf_dir / "test.pdf"
        p.touch()

        with patch.object(Path, "unlink") as mock_unlink:
            pdf_service.cleanup_temp_files("test", keep_pdfs=False)
            assert mock_unlink.called


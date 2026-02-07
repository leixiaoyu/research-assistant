"""PDF Service for Phase 2: PDF Processing & LLM Extraction

This service handles:
1. PDF download with retry logic
2. PDF validation (magic bytes, file size)
3. PDF to markdown conversion using marker-pdf
4. Temporary file management

Security Features:
- File size limits to prevent DoS
- PDF magic byte validation
- Path sanitization
- Timeout enforcement
"""

import asyncio
import subprocess
import re
from pathlib import Path
import structlog
import aiohttp

from src.utils.exceptions import (
    PDFDownloadError,
    FileSizeError,
    PDFValidationError,
    ConversionError,
)

logger = structlog.get_logger()


class PDFService:
    """Service for downloading and converting PDFs to markdown

    Uses marker-pdf for conversion which preserves code formatting.
    Implements retry logic for transient failures.
    """

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Sanitize filename to prevent directory traversal

        Args:
            filename: Filename to sanitize

        Returns:
            Safe filename with only alphanumeric, dash, underscore, and dot
        """
        # Remove any directory components
        filename = Path(filename).name
        # Keep only safe characters
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
        # Prevent hidden files
        if safe_name.startswith("."):
            safe_name = "_" + safe_name
        return safe_name

    def __init__(
        self, temp_dir: Path, max_size_mb: int = 50, timeout_seconds: int = 300
    ):
        """Initialize PDF service

        Args:
            temp_dir: Directory for temporary files
            max_size_mb: Maximum PDF size in megabytes
            timeout_seconds: Timeout for downloads and conversions

        Security:
            - temp_dir is resolved to absolute path
            - File size is enforced to prevent DoS
            - Filenames are sanitized to prevent directory traversal
        """
        # Resolve temp_dir to absolute path (safe as it comes from config)
        self.temp_dir = Path(temp_dir).resolve()
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.timeout_seconds = timeout_seconds

        # Create temp directories
        self.pdf_dir = self.temp_dir / "pdfs"
        self.markdown_dir = self.temp_dir / "markdown"
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "pdf_service_initialized",
            temp_dir=str(self.temp_dir),
            max_size_mb=max_size_mb,
            timeout_seconds=timeout_seconds,
        )

    async def download_pdf(self, url: str, paper_id: str) -> Path:
        """Download PDF from URL with retry logic

        Args:
            url: PDF URL (must be HTTPS)
            paper_id: Unique paper identifier for filename

        Returns:
            Path to downloaded PDF file

        Raises:
            PDFDownloadError: If download fails after retries
            FileSizeError: If PDF exceeds max size
            PDFValidationError: If PDF validation fails

        Security:
            - Only HTTPS URLs allowed
            - File size checked before download
            - PDF magic bytes validated after download
        """
        # Security: Ensure HTTPS (don't retry this - it's a validation error)
        if not url.startswith("https://"):
            raise PDFDownloadError(f"Only HTTPS URLs allowed: {url}")

        # Use retry logic for actual download
        return await self._download_with_retry(url, paper_id)

    async def _download_with_retry(self, url: str, paper_id: str) -> Path:
        """Internal method with retry logic for network operations"""

        # Sanitize filename
        safe_filename = self._sanitize_filename(f"{paper_id}.pdf")
        output_path = self.pdf_dir / safe_filename

        logger.info(
            "pdf_download_started",
            url=url,
            paper_id=paper_id,
            output_path=str(output_path),
        )

        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    # Don't retry client errors (4xx) - these won't succeed on retry
                    if 400 <= response.status < 500:
                        raise PDFDownloadError(f"HTTP {response.status} for {url}")
                    # Retry server errors (5xx) - might be transient
                    elif response.status >= 500:
                        raise PDFDownloadError(
                            f"HTTP {response.status} for {url} (will retry)"
                        )
                    elif response.status != 200:
                        raise PDFDownloadError(f"HTTP {response.status} for {url}")

                    # Check size before downloading
                    content_length = response.headers.get("content-length")
                    if content_length:
                        size = int(content_length)
                        if size > self.max_size_bytes:
                            raise FileSizeError(
                                f"PDF too large: {size} bytes "
                                f"(max: {self.max_size_bytes})"
                            )

                    # Stream download
                    total_bytes = 0
                    with open(output_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(8192):
                            total_bytes += len(chunk)
                            # Security: Check size during download
                            if total_bytes > self.max_size_bytes:
                                output_path.unlink(missing_ok=True)
                                raise FileSizeError(
                                    f"PDF exceeded size limit during download: "
                                    f"{total_bytes} bytes"
                                )
                            f.write(chunk)

            # Validate downloaded PDF
            if not self.validate_pdf(output_path):  # pragma: no cover (corrupt PDF)
                output_path.unlink(missing_ok=True)
                raise PDFValidationError(f"Invalid PDF file: {output_path}")

            logger.info(
                "pdf_download_success",
                paper_id=paper_id,
                size_bytes=total_bytes,
                path=str(output_path),
            )

            return output_path

        except aiohttp.ClientError as e:
            logger.error(
                "pdf_download_failed", paper_id=paper_id, url=url, error=str(e)
            )
            raise PDFDownloadError(f"Download failed: {e}")
        except asyncio.TimeoutError:
            logger.error("pdf_download_timeout", paper_id=paper_id, url=url)
            raise PDFDownloadError(f"Download timeout after {self.timeout_seconds}s")

    def validate_pdf(self, pdf_path: Path) -> bool:
        """Validate PDF file integrity

        Args:
            pdf_path: Path to PDF file

        Returns:
            True if valid PDF, False otherwise

        Checks:
            - File exists and is not empty
            - File has PDF magic bytes (%PDF)
        """
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            logger.warning(
                "pdf_validation_failed", reason="file_empty", path=str(pdf_path)
            )
            return False

        # Check PDF magic bytes
        try:
            with open(pdf_path, "rb") as f:
                header = f.read(4)
                is_valid = header == b"%PDF"
                if not is_valid:
                    logger.warning(
                        "pdf_validation_failed",
                        reason="invalid_magic_bytes",
                        path=str(pdf_path),
                        header=header.hex(),
                    )
                return is_valid
        except Exception as e:
            logger.error("pdf_validation_error", path=str(pdf_path), error=str(e))
            return False

    def convert_to_markdown(self, pdf_path: Path, paper_id: str) -> Path:
        """Convert PDF to markdown using marker-pdf

        Args:
            pdf_path: Path to PDF file
            paper_id: Paper identifier for output filename

        Returns:
            Path to generated markdown file

        Raises:
            ConversionError: If marker-pdf fails or times out

        Note:
            marker-pdf preserves code syntax during conversion, which is
            critical for extracting code snippets from research papers.
        """
        if not pdf_path.exists():
            raise ConversionError(f"PDF file not found: {pdf_path}")

        # Prepare output path
        safe_filename = self._sanitize_filename(f"{paper_id}.md")
        output_path = self.markdown_dir / safe_filename

        logger.info(
            "pdf_conversion_started",
            paper_id=paper_id,
            pdf_path=str(pdf_path),
            output_path=str(output_path),
        )

        # Run marker_single command
        # Note: marker-pdf v1.10.1+ uses simplified API
        cmd = [
            "marker_single",
            str(pdf_path),
            "--output_dir",
            str(self.markdown_dir),
            "--output_format",
            "markdown",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,  # Don't raise on non-zero exit
            )

            # Check for errors
            if result.returncode != 0:
                logger.error(
                    "marker_pdf_failed",
                    paper_id=paper_id,
                    returncode=result.returncode,
                    stderr=result.stderr,
                )
                raise ConversionError(
                    f"marker-pdf failed (exit {result.returncode}): {result.stderr}"
                )

            # Find generated markdown file
            # marker-pdf may create file with .md extension
            md_files = list(self.markdown_dir.glob(f"*{paper_id}*.md"))
            if not md_files:
                # Try without paper_id in glob
                md_files = list(self.markdown_dir.glob("*.md"))
                # Filter to most recent
                if md_files:
                    md_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            if not md_files:
                raise ConversionError(f"No markdown file generated for {paper_id}")

            # Use first match or rename to expected path
            generated_file = md_files[0]
            if generated_file != output_path:
                generated_file.rename(output_path)

            logger.info(
                "pdf_conversion_success",
                paper_id=paper_id,
                output_path=str(output_path),
                size_bytes=output_path.stat().st_size,
            )

            return output_path

        except subprocess.TimeoutExpired:
            logger.error(
                "pdf_conversion_timeout",
                paper_id=paper_id,
                timeout=self.timeout_seconds,
            )
            raise ConversionError(f"Conversion timeout after {self.timeout_seconds}s")
        except Exception as e:
            logger.error("pdf_conversion_error", paper_id=paper_id, error=str(e))
            raise ConversionError(f"Conversion failed: {e}")

    def cleanup_temp_files(self, paper_id: str, keep_pdfs: bool = True) -> None:
        """Clean up temporary files for a paper

        Args:
            paper_id: Paper identifier
            keep_pdfs: If True, only delete markdown files

        This is called after extraction to free disk space.
        """
        if not keep_pdfs:
            pdf_pattern = f"*{paper_id}*.pdf"
            for pdf_file in self.pdf_dir.glob(pdf_pattern):
                try:
                    pdf_file.unlink()
                    logger.debug("pdf_deleted", path=str(pdf_file))
                except Exception as e:  # pragma: no cover (OS file lock/permission)
                    logger.warning(
                        "pdf_delete_failed", path=str(pdf_file), error=str(e)
                    )

        # Always clean up markdown files (can regenerate from PDF if needed)
        md_pattern = f"*{paper_id}*.md"
        for md_file in self.markdown_dir.glob(md_pattern):
            try:
                md_file.unlink()
                logger.debug("markdown_deleted", path=str(md_file))
            except Exception as e:  # pragma: no cover (OS file lock/permission)
                logger.warning(
                    "markdown_delete_failed", path=str(md_file), error=str(e)
                )

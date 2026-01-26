"""Pandoc extractor backend.

This extractor uses the pandoc system utility to convert PDF to markdown.
It serves as a robust fallback when Python-based extractors fail.
"""

import time
import shutil
import subprocess
import tempfile
import structlog
from pathlib import Path

from src.models.pdf_extraction import (
    PDFExtractionResult,
    PDFBackend,
    ExtractionMetadata,
)
from src.services.pdf_extractors.base import PDFExtractor

logger = structlog.get_logger()


class PandocExtractor(PDFExtractor):
    """PDF extractor using pandoc system utility."""

    @property
    def name(self) -> PDFBackend:
        """Return the backend identifier."""
        return PDFBackend.PANDOC

    def validate_setup(self) -> bool:
        """Check if pandoc is installed and available in PATH."""
        return shutil.which("pandoc") is not None

    async def extract(self, pdf_path: Path) -> PDFExtractionResult:
        """
        Extract markdown from PDF using pandoc.

        Strategy:
        1. Validate pandoc availability
        2. Execute pandoc subprocess securely (no shell=True)
        3. Capture output
        """
        start_time = time.time()
        metadata = ExtractionMetadata(backend=self.name)

        if not self.validate_setup():
            return PDFExtractionResult(
                success=False,
                metadata=metadata,
                error="pandoc not found in PATH",
            )

        if not pdf_path.exists():
            return PDFExtractionResult(
                success=False,
                metadata=metadata,
                error=f"PDF file not found: {pdf_path}",
            )

        try:
            # Create a temporary file for output to avoid pipe issues
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp_file:
                output_path = Path(tmp_file.name)

            try:
                # Secure subprocess call:
                # 1. Use list of arguments (no shell=True)
                # 2. Use full paths
                # 3. Set timeout
                cmd = [
                    "pandoc",
                    str(pdf_path.resolve()),
                    "-f", "pdf",  # Force input format (though pandoc usually detects)
                    "-t", "markdown",
                    "-o", str(output_path.resolve())
                ]

                # Run pandoc
                # Note: pandoc might use pdftotext internally for PDF input
                subprocess.run(
                    cmd,
                    check=True,
                    timeout=60,
                    capture_output=True
                )

                # Read result
                markdown = output_path.read_text(encoding="utf-8")
                
                metadata.text_length = len(markdown)
                metadata.file_size_bytes = pdf_path.stat().st_size
                # Note: pandoc doesn't give us page count easily without parsing

                duration = time.time() - start_time

                return PDFExtractionResult(
                    success=True,
                    markdown=markdown,
                    metadata=metadata,
                    quality_score=0.0,
                    duration_seconds=duration,
                )

            finally:
                # Cleanup temp file
                if output_path.exists():
                    output_path.unlink()

        except subprocess.TimeoutExpired:
            return PDFExtractionResult(
                success=False,
                metadata=metadata,
                error="Pandoc execution timed out (60s)",
                duration_seconds=time.time() - start_time,
            )
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            return PDFExtractionResult(
                success=False,
                metadata=metadata,
                error=f"Pandoc failed: {error_msg}",
                duration_seconds=time.time() - start_time,
            )
        except Exception as e:
            logger.error("pandoc_extraction_failed", error=str(e), pdf_path=str(pdf_path))
            return PDFExtractionResult(
                success=False,
                metadata=metadata,
                error=str(e),
                duration_seconds=time.time() - start_time,
            )

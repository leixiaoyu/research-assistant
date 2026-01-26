"""PDFPlumber extractor backend.

This extractor uses pdfplumber to extract text and tables. It is slower than
PyMuPDF but offers superior table extraction capabilities.
"""

import time
from pathlib import Path
import structlog

from src.models.pdf_extraction import (
    PDFExtractionResult,
    PDFBackend,
    ExtractionMetadata,
)
from src.services.pdf_extractors.base import PDFExtractor

logger = structlog.get_logger()


class PDFPlumberExtractor(PDFExtractor):
    """PDF extractor using pdfplumber library."""

    @property
    def name(self) -> PDFBackend:
        """Return the backend identifier."""
        return PDFBackend.PDFPLUMBER

    def validate_setup(self) -> bool:
        """Check if pdfplumber is installed."""
        try:
            import pdfplumber  # noqa: F401

            return True
        except ImportError:
            logger.warning("pdfplumber_not_installed")
            return False

    async def extract(self, pdf_path: Path) -> PDFExtractionResult:
        """
        Extract markdown from PDF using pdfplumber.

        Strategy:
        1. Open document with pdfplumber
        2. Iterate through pages
        3. Extract text
        4. Extract tables with high precision
        """
        start_time = time.time()
        metadata = ExtractionMetadata(backend=self.name)

        if not self.validate_setup():
            return PDFExtractionResult(
                success=False,
                metadata=metadata,
                error="pdfplumber not installed",
            )

        if not pdf_path.exists():
            return PDFExtractionResult(
                success=False,
                metadata=metadata,
                error=f"PDF file not found: {pdf_path}",
            )

        try:
            import pdfplumber

            markdown_content = []
            
            with pdfplumber.open(pdf_path) as pdf:
                metadata.page_count = len(pdf.pages)
                metadata.file_size_bytes = pdf_path.stat().st_size

                for page in pdf.pages:
                    # Extract text
                    text = page.extract_text()
                    if text:
                        markdown_content.append(text + "\n")

                    # Extract tables
                    tables = page.extract_tables()
                    if tables:
                        metadata.tables_found += len(tables)
                        for table in tables:
                            md_table = self._table_to_markdown(table)
                            if md_table:
                                markdown_content.append(md_table + "\n")

            full_text = "\n".join(markdown_content)
            metadata.text_length = len(full_text)
            metadata.duration_seconds = time.time() - start_time

            return PDFExtractionResult(
                success=True,
                markdown=full_text,
                metadata=metadata,
                quality_score=0.0,  # Calculated by validator later
                duration_seconds=metadata.duration_seconds,
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                "pdfplumber_extraction_failed",
                error=str(e),
                pdf_path=str(pdf_path)
            )
            return PDFExtractionResult(
                success=False,
                metadata=metadata,
                error=str(e),
                duration_seconds=duration,
            )

    def _table_to_markdown(self, table: list) -> str:
        """Convert list-of-lists table to markdown."""
        if not table or len(table) < 2:
            return ""

        try:
            lines = []
            
            # Header
            header = [str(c).replace("\n", " ") if c is not None else "" for c in table[0]]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("| " + " | ".join(["---"] * len(header)) + " |")

            # Rows
            for row in table[1:]:
                clean_row = [str(c).replace("\n", " ") if c is not None else "" for c in row]
                lines.append("| " + " | ".join(clean_row) + " |")

            return "\n".join(lines) + "\n"
        except Exception:
            return ""

"""PyMuPDF (fitz) PDF extractor backend.

This extractor uses the PyMuPDF library (import fitz) to extract text and
basic tables from PDFs. It is fast, reliable, and lightweight.
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


class PyMuPDFExtractor(PDFExtractor):
    """PDF extractor using PyMuPDF (fitz) library."""

    @property
    def name(self) -> PDFBackend:
        """Return the backend identifier."""
        return PDFBackend.PYMUPDF

    def validate_setup(self) -> bool:
        """Check if PyMuPDF is installed."""
        try:
            import fitz  # noqa: F401

            return True
        except ImportError:
            logger.warning("pymupdf_not_installed")
            return False

    async def extract(self, pdf_path: Path) -> PDFExtractionResult:
        """
        Extract markdown from PDF using PyMuPDF.

        Strategy:
        1. Open document with fitz
        2. Iterate through pages
        3. Extract text blocks and detect code blocks
        4. Extract tables using built-in table finder
        """
        start_time = time.time()
        metadata = ExtractionMetadata(backend=self.name)

        if not self.validate_setup():
            return PDFExtractionResult(
                success=False,
                metadata=metadata,
                error="PyMuPDF (fitz) not installed",
            )

        try:
            import fitz

            doc = fitz.open(pdf_path)
            metadata.page_count = len(doc)
            metadata.file_size_bytes = pdf_path.stat().st_size

            markdown_content = []

            for page in doc:
                # Extract text blocks
                blocks = page.get_text("blocks")
                for block in blocks:
                    # block format: (x0, y0, x1, y1, text, block_no, block_type)
                    text = block[4]
                    if not text.strip():
                        continue

                    if self._looks_like_code(text):
                        markdown_content.append(f"```\n{text}```\n")
                        metadata.code_blocks_found += 1
                    else:
                        markdown_content.append(text + "\n")

                # Extract tables
                tabs = page.find_tables()
                if tabs.tables:
                    metadata.tables_found += len(tabs.tables)
                    for table in tabs.tables:
                        markdown_content.append(self._table_to_markdown(table))

            full_text = "\n".join(markdown_content)
            metadata.text_length = len(full_text)
            metadata.duration_seconds = time.time() - start_time

            return PDFExtractionResult(
                success=True,
                markdown=full_text,
                metadata=metadata,
                quality_score=0.0,  # Calculated by validator later
            )

        except Exception as e:
            logger.error(
                "pymupdf_extraction_failed", error=str(e), pdf_path=str(pdf_path)
            )
            return PDFExtractionResult(
                success=False,
                metadata=metadata,
                error=str(e),
                duration_seconds=time.time() - start_time,
            )

    def _looks_like_code(self, text: str) -> bool:
        """Heuristic to detect code blocks."""
        # Simple heuristics: indentation, special chars
        lines = text.splitlines()
        code_lines = 0
        for line in lines:
            if line.startswith("    ") or line.startswith("\t"):
                code_lines += 1
            if any(c in line for c in ["{", "}", ";", "def ", "class ", "import "]):
                code_lines += 1

        return code_lines > len(lines) * 0.5 and len(lines) > 1

    def _table_to_markdown(self, table) -> str:
        """Convert PyMuPDF table to markdown."""
        try:
            data = table.extract()
            if not data:
                return ""

            lines = []
            # Header
            header = [str(c).replace("\n", " ") for c in data[0]]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("| " + " | ".join(["---"] * len(header)) + " |")

            # Rows
            for row in data[1:]:
                clean_row = [
                    str(c).replace("\n", " ") if c is not None else "" for c in row
                ]
                lines.append("| " + " | ".join(clean_row) + " |")

            return "\n".join(lines) + "\n\n"
        except Exception:
            return ""

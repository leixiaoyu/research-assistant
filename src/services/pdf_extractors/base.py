"""Abstract base class for PDF extraction backends.

All PDF extractors must inherit from PDFExtractor and implement
the extract() and validate_setup() methods.
"""

from abc import ABC, abstractmethod
from pathlib import Path
import structlog

from src.models.pdf_extraction import (
    PDFExtractionResult,
    PDFBackend,
)

logger = structlog.get_logger()


class PDFExtractor(ABC):
    """
    Abstract base class for PDF extraction backends.

    All concrete extractors must implement:
    - extract(): Convert PDF to markdown
    - validate_setup(): Check if backend is available
    - name property: Return backend identifier
    """

    @abstractmethod
    async def extract(self, pdf_path: Path) -> PDFExtractionResult:
        """
        Extract markdown from PDF file.

        Args:
            pdf_path: Path to PDF file

        Returns:
            PDFExtractionResult with success status and markdown content

        Raises:
            Should NOT raise exceptions - catch and return error in result
        """
        raise NotImplementedError("Subclasses must implement extract()")

    @abstractmethod
    def validate_setup(self) -> bool:
        """
        Check if this backend is properly configured and available.

        Returns:
            True if backend can be used, False otherwise
        """
        raise NotImplementedError("Subclasses must implement validate_setup()")

    @property
    @abstractmethod
    def name(self) -> PDFBackend:
        """Return the backend identifier."""
        raise NotImplementedError("Subclasses must implement name property")

    def _get_page_count(self, pdf_path: Path) -> int:
        """
        Helper: Get page count from PDF using PyMuPDF if available.

        This is a lightweight utility used for quality scoring.
        """
        try:
            import fitz

            doc = fitz.open(pdf_path)
            count = len(doc)
            doc.close()
            return count
        except Exception as e:
            logger.debug("page_count_failed", pdf_path=str(pdf_path), error=str(e))
            return 0

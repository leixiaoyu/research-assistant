"""PDF Extraction Data Models for Phase 2.5: Reliability Improvements.

This module defines the data structures for tracking multiple PDF extraction
attempts, including backend identifiers, metadata, and quality scores.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class PDFBackend(str, Enum):
    """PDF extraction backend identifier."""

    PYMUPDF = "pymupdf"
    PDFPLUMBER = "pdfplumber"
    MARKER = "marker"
    PANDOC = "pandoc"
    ABSTRACT_FALLBACK = "abstract"
    TEXT_ONLY = "text_only"


class ExtractionMetadata(BaseModel):
    """Metadata about the PDF extraction process."""

    backend: PDFBackend
    duration_seconds: float = Field(default=0.0, ge=0.0)
    page_count: int = Field(default=0, ge=0)
    file_size_bytes: int = Field(default=0, ge=0)
    attempt_number: int = Field(default=1, ge=1)

    # Quality indicators
    text_length: int = Field(default=0, ge=0)
    code_blocks_found: int = Field(default=0, ge=0)
    tables_found: int = Field(default=0, ge=0)
    headers_found: int = Field(default=0, ge=0)


class PDFExtractionResult(BaseModel):
    """Result of PDF extraction with quality metrics."""

    success: bool
    markdown: Optional[str] = None
    metadata: ExtractionMetadata
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    duration_seconds: float = Field(default=0.0, ge=0.0)
    error: Optional[str] = None

    @property
    def backend(self) -> PDFBackend:
        """Convenience property to access the backend identifier."""
        return self.metadata.backend

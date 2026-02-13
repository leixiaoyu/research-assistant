"""Synthesis data models for Phase 3.6: Cumulative Knowledge Synthesis.

This module defines the data structures for:
- Processing results with status tracking (NEW, BACKFILLED, SKIPPED)
- Knowledge Base paper entries with quality ranking
- Delta brief generation
"""

import re
from enum import Enum
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator


class ProcessingStatus(str, Enum):
    """Status of paper processing in current run.

    Used by DeltaGenerator to categorize papers for delta briefs.
    """

    NEW = "new"  # Paper processed for the first time
    BACKFILLED = "backfilled"  # Existing paper updated with new extraction targets
    SKIPPED = "skipped"  # Already processed, no changes needed
    MAPPED = "mapped"  # Added to topic affiliation only (no processing)
    FAILED = "failed"  # Processing failed


class ProcessingResult(BaseModel):
    """Result of processing a single paper in the pipeline.

    Captures the processing status, quality score, and any extraction
    results for use in delta generation and synthesis.
    """

    paper_id: str = Field(..., description="Canonical paper UUID from registry")
    title: str = Field(..., description="Paper title for display")
    status: ProcessingStatus = Field(..., description="Processing status")
    quality_score: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Quality score (0-100)"
    )
    pdf_available: bool = Field(default=False, description="Whether PDF was available")
    extraction_success: bool = Field(
        default=False, description="Whether extraction succeeded"
    )
    topic_slug: str = Field(..., description="Topic this result belongs to")
    processed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When processing completed",
    )
    error_message: Optional[str] = Field(
        default=None, description="Error message if processing failed"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional metadata from extraction"
    )


class KnowledgeBaseEntry(BaseModel):
    """A paper entry for the Knowledge Base document.

    Represents a single paper with all relevant information for
    rendering in the cumulative Knowledge_Base.md file.
    """

    paper_id: str = Field(..., description="Canonical paper UUID")
    title: str = Field(..., description="Paper title")
    authors: List[str] = Field(default_factory=list, description="Paper authors")
    abstract: Optional[str] = Field(default=None, description="Paper abstract")
    url: Optional[str] = Field(default=None, description="Paper URL")
    doi: Optional[str] = Field(default=None, description="DOI if available")
    arxiv_id: Optional[str] = Field(default=None, description="ArXiv ID if available")
    publication_date: Optional[str] = Field(
        default=None, description="Publication date"
    )
    quality_score: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Quality score for ranking"
    )
    pdf_available: bool = Field(default=False, description="Whether PDF is available")
    pdf_path: Optional[str] = Field(default=None, description="Path to PDF file")
    extraction_results: Optional[Dict[str, Any]] = Field(
        default=None, description="LLM extraction results"
    )
    topic_affiliations: List[str] = Field(
        default_factory=list, description="Topics this paper belongs to"
    )
    first_discovered: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When first added to registry",
    )
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When last updated in registry",
    )
    user_notes: Optional[str] = Field(
        default=None, description="User-added notes (preserved across synthesis)"
    )


class DeltaBrief(BaseModel):
    """Delta brief for a single pipeline run.

    Contains papers that are new or backfilled in this run,
    along with summary statistics.
    """

    topic_slug: str = Field(..., description="Topic this delta belongs to")
    run_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this run was executed",
    )
    new_papers: List[ProcessingResult] = Field(
        default_factory=list, description="Papers processed for the first time"
    )
    backfilled_papers: List[ProcessingResult] = Field(
        default_factory=list, description="Existing papers updated with new extractions"
    )
    skipped_count: int = Field(
        default=0, description="Number of papers skipped (already processed)"
    )
    failed_count: int = Field(
        default=0, description="Number of papers that failed processing"
    )

    @property
    def total_new(self) -> int:
        """Total number of new papers."""
        return len(self.new_papers)

    @property
    def total_backfilled(self) -> int:
        """Total number of backfilled papers."""
        return len(self.backfilled_papers)

    @property
    def has_changes(self) -> bool:
        """Whether this run has any changes."""
        return self.total_new > 0 or self.total_backfilled > 0


class UserNoteAnchor(BaseModel):
    """Represents a user note anchor in the Knowledge Base.

    Used to preserve manual annotations during re-synthesis.
    """

    paper_id: str = Field(..., description="Paper ID this note belongs to")
    content: str = Field(..., description="User note content")
    start_line: int = Field(default=0, description="Line number where anchor starts")
    end_line: int = Field(default=0, description="Line number where anchor ends")

    # Anchor tag patterns
    START_TAG: str = "<!-- USER_NOTES_START:{paper_id} -->"
    END_TAG: str = "<!-- USER_NOTES_END:{paper_id} -->"

    @classmethod
    def create_start_tag(cls, paper_id: str) -> str:
        """Create a start anchor tag for a paper."""
        return f"<!-- USER_NOTES_START:{paper_id} -->"

    @classmethod
    def create_end_tag(cls, paper_id: str) -> str:
        """Create an end anchor tag for a paper."""
        return f"<!-- USER_NOTES_END:{paper_id} -->"

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate content doesn't contain script injection."""
        # Block script tags
        if re.search(r"<script", v, re.IGNORECASE):
            raise ValueError("Script tags are not allowed in user notes")
        return v


class SynthesisStats(BaseModel):
    """Statistics from a synthesis operation."""

    topic_slug: str = Field(..., description="Topic that was synthesized")
    total_papers: int = Field(default=0, description="Total papers in Knowledge Base")
    papers_with_pdf: int = Field(default=0, description="Papers with PDF available")
    papers_with_extraction: int = Field(
        default=0, description="Papers with successful extraction"
    )
    average_quality: float = Field(default=0.0, description="Average quality score")
    top_quality_score: float = Field(
        default=0.0, description="Highest quality score in KB"
    )
    user_notes_preserved: int = Field(
        default=0, description="Number of user notes preserved"
    )
    synthesis_duration_ms: int = Field(
        default=0, description="Time taken for synthesis in milliseconds"
    )
    synthesized_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When synthesis completed",
    )

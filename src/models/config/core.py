"""Core configuration models: timeframes, topics, and enums.

This module contains fundamental configuration types used across the pipeline:
- Timeframe specifications (recent, since_year, date_range)
- Research topic definitions
- Core enums (ProviderType, PDFStrategy, NoPDFAction)
"""

from enum import Enum
from typing import Literal, Union, List, Optional
from datetime import date
from pydantic import BaseModel, Field, field_validator

from src.utils.security import InputValidation
from src.models.extraction import ExtractionTarget


class TimeframeType(str, Enum):
    RECENT = "recent"
    SINCE_YEAR = "since_year"
    DATE_RANGE = "date_range"


class TimeframeRecent(BaseModel):
    """Recent timeframe (e.g., last 48 hours)"""

    type: Literal[TimeframeType.RECENT] = TimeframeType.RECENT
    value: str = Field(..., pattern=r"^\d+[hd]$", description="Format: '48h' or '7d'")

    @field_validator("value")
    @classmethod
    def validate_recent_format(cls, v: str) -> str:
        unit = v[-1]
        amount = int(v[:-1])
        if unit == "h" and amount > 720:  # Max 30 days
            raise ValueError("Hour-based timeframe cannot exceed 720h (30 days)")
        if unit == "d" and amount > 365:
            raise ValueError("Day-based timeframe cannot exceed 365d (1 year)")
        return v


class TimeframeSinceYear(BaseModel):
    """Papers since a specific year"""

    type: Literal[TimeframeType.SINCE_YEAR] = TimeframeType.SINCE_YEAR
    value: int = Field(..., ge=1900, le=2100)


class TimeframeDateRange(BaseModel):
    """Custom date range"""

    type: Literal[TimeframeType.DATE_RANGE] = TimeframeType.DATE_RANGE
    start_date: date
    end_date: date

    @field_validator("end_date")
    @classmethod
    def validate_date_range(cls, v: date, info) -> date:
        # Pydantic V2 validation context access
        values = info.data
        if "start_date" in values and v < values["start_date"]:
            raise ValueError("end_date must be after start_date")
        return v


Timeframe = Union[TimeframeRecent, TimeframeSinceYear, TimeframeDateRange]


class ProviderType(str, Enum):
    ARXIV = "arxiv"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    HUGGINGFACE = "huggingface"
    OPENALEX = "openalex"  # Phase 6: OpenAlex provider


class PDFStrategy(str, Enum):
    """Strategy for handling PDF availability in discovery (Phase 3.4)."""

    QUALITY_FIRST = "quality_first"  # Default: rank by quality, track PDF availability
    PDF_REQUIRED = "pdf_required"  # Only include papers with PDFs (may reduce quality)
    ARXIV_SUPPLEMENT = "arxiv_supplement"  # Fill PDF gaps with ArXiv results


class NoPDFAction(str, Enum):
    """What to do with papers that don't have PDFs (Phase 3.4)."""

    INCLUDE_METADATA = "include_metadata"  # Include with abstract only (default)
    SKIP = "skip"  # Exclude from brief entirely
    FLAG_FOR_MANUAL = "flag_for_manual"  # Mark for manual PDF acquisition


class ResearchTopic(BaseModel):
    """A single research topic configuration"""

    query: str = Field(..., min_length=1, max_length=500)
    provider: ProviderType = Field(ProviderType.ARXIV, description="Discovery provider")
    timeframe: Timeframe
    max_papers: int = Field(50, ge=1, le=1000)
    # Phase 2: Extraction targets (optional for backward compatibility)
    extraction_targets: Optional[List[ExtractionTarget]] = Field(
        default=None, description="List of extraction targets for this topic (Phase 2)"
    )
    # Phase 3.2: Provider selection enhancements
    min_citations: Optional[int] = Field(
        default=None,
        ge=0,
        description="Minimum citation count (requires Semantic Scholar)",
    )
    benchmark: bool = Field(
        default=False,
        description="Enable provider comparison mode for this topic",
    )
    auto_select_provider: bool = Field(
        default=True,
        description="Allow automatic provider selection when not explicitly set",
    )

    # Phase 3.4: Quality-first discovery settings
    quality_ranking: bool = Field(
        default=True,
        description="Enable quality-based ranking of papers",
    )
    min_quality_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Minimum quality score threshold (0-100)",
    )
    pdf_strategy: PDFStrategy = Field(
        default=PDFStrategy.QUALITY_FIRST,
        description="Strategy for handling PDF availability",
    )
    no_pdf_action: NoPDFAction = Field(
        default=NoPDFAction.INCLUDE_METADATA,
        description="How to handle papers without PDFs in output",
    )
    arxiv_supplement_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="PDF rate threshold to trigger ArXiv supplement (0-1)",
    )

    # Phase 7.1: Incremental discovery
    force_full_timeframe: bool = Field(
        default=False,
        description="Override incremental discovery (always use full timeframe)",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        # Delegate to centralized security utility
        return InputValidation.validate_query(v)

    @property
    def slug(self) -> str:
        """Generate a filesystem-safe slug from the query.

        Phase 3.5: Used for topic affiliation tracking in the registry.

        Returns:
            Lowercase alphanumeric + hyphen slug.
        """
        from src.utils.hash import generate_topic_slug

        return generate_topic_slug(self.query)

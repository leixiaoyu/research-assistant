from enum import Enum
from typing import Literal, Union, List, Optional
from datetime import date
from pydantic import BaseModel, Field, field_validator, ConfigDict

from src.utils.security import InputValidation
from src.models.extraction import ExtractionTarget
from src.models.concurrency import ConcurrencyConfig


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


class PDFBackendConfig(BaseModel):
    """Configuration for a single PDF extraction backend"""

    backend: str = Field(
        ..., description="Backend identifier (pymupdf, pdfplumber, etc)"
    )
    timeout_seconds: int = Field(60, ge=1, le=600)
    min_quality: float = Field(0.5, ge=0.0, le=1.0)
    enabled: bool = Field(True)


class PDFSettings(BaseModel):
    """PDF processing settings (Phase 2 & 2.5)"""

    temp_dir: str = Field(
        "./temp", description="Temporary directory for PDFs and markdown"
    )
    keep_pdfs: bool = Field(True, description="Keep PDFs after processing")
    max_file_size_mb: int = Field(
        50, ge=1, le=500, description="Maximum PDF size in MB"
    )
    timeout_seconds: int = Field(
        300, ge=60, le=600, description="Global timeout for download/conversion"
    )

    # Phase 2.5: Fallback Chain
    fallback_chain: List[PDFBackendConfig] = Field(
        default_factory=lambda: [
            PDFBackendConfig(
                backend="pymupdf", timeout_seconds=30, min_quality=0.5, enabled=True
            ),
            PDFBackendConfig(
                backend="pdfplumber", timeout_seconds=45, min_quality=0.5, enabled=True
            ),
            PDFBackendConfig(
                backend="marker", timeout_seconds=300, min_quality=0.7, enabled=False
            ),
            PDFBackendConfig(
                backend="pandoc", timeout_seconds=60, min_quality=0.3, enabled=True
            ),
        ],
        description="Ordered list of extraction backends to attempt",
    )
    stop_on_success: bool = Field(
        True, description="Stop after first success meeting min_quality"
    )


class LLMSettings(BaseModel):
    """LLM configuration (Phase 2)"""

    provider: Literal["anthropic", "google"] = Field(
        "anthropic", description="LLM provider"
    )
    model: str = Field("claude-3-5-sonnet-20250122", description="Model identifier")
    api_key: Optional[str] = Field(
        None, min_length=10, description="LLM API key (from environment)"
    )
    max_tokens: int = Field(
        100000, gt=0, le=200000, description="Max tokens per request"
    )
    temperature: float = Field(0.0, ge=0.0, le=1.0, description="Sampling temperature")
    timeout: int = Field(300, gt=0, le=600, description="Request timeout in seconds")


class CostLimitSettings(BaseModel):
    """Cost control settings (Phase 2)"""

    max_tokens_per_paper: int = Field(
        100000, gt=0, le=200000, description="Max tokens per paper"
    )
    max_daily_spend_usd: float = Field(
        50.0, gt=0.0, le=1000.0, description="Max daily spending"
    )
    max_total_spend_usd: float = Field(
        500.0, gt=0.0, le=10000.0, description="Max total spending"
    )


class ProviderSelectionConfig(BaseModel):
    """Configuration for intelligent provider selection (Phase 3.2)"""

    auto_select: bool = Field(
        default=True,
        description="Automatically select optimal provider based on query",
    )
    fallback_enabled: bool = Field(
        default=True,
        description="Enable automatic fallback to alternate providers on failure",
    )
    benchmark_mode: bool = Field(
        default=False,
        description="Query all providers for comparison",
    )
    preference_order: List[ProviderType] = Field(
        default_factory=lambda: [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR],
        description="Provider preference order for auto-selection",
    )
    fallback_timeout_seconds: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        description="Timeout before triggering fallback",
    )


class GlobalSettings(BaseModel):
    """Global pipeline settings"""

    output_base_dir: str = Field("./output", description="Base output directory")
    enable_duplicate_detection: bool = Field(
        True, description="Enable topic deduplication"
    )
    semantic_scholar_api_key: Optional[str] = Field(
        None, min_length=10, description="Semantic Scholar API key (optional)"
    )
    # Phase 2: PDF and LLM settings (optional for backward compatibility)
    pdf_settings: Optional[PDFSettings] = Field(
        default=None, description="PDF processing settings (Phase 2)"
    )
    llm_settings: Optional[LLMSettings] = Field(
        default=None, description="LLM configuration (Phase 2)"
    )
    cost_limits: Optional[CostLimitSettings] = Field(
        default=None, description="Cost control settings (Phase 2)"
    )
    # Phase 3.1: Concurrency configuration
    concurrency: ConcurrencyConfig = Field(
        default_factory=lambda: ConcurrencyConfig(),
        description="Concurrent processing settings (Phase 3.1)",
    )
    # Phase 3.2: Provider selection configuration
    provider_selection: ProviderSelectionConfig = Field(
        default_factory=lambda: ProviderSelectionConfig(),
        description="Provider selection settings (Phase 3.2)",
    )


class ResearchConfig(BaseModel):
    """Root configuration model"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    research_topics: List[ResearchTopic] = Field(..., min_length=1, max_length=100)
    settings: GlobalSettings

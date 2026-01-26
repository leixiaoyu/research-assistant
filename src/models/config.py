from enum import Enum
from typing import Literal, Union, List, Optional
from datetime import date
from pydantic import BaseModel, Field, field_validator, ConfigDict

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

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        # Delegate to centralized security utility
        return InputValidation.validate_query(v)


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


class ResearchConfig(BaseModel):
    """Root configuration model"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    research_topics: List[ResearchTopic] = Field(..., min_length=1, max_length=100)
    settings: GlobalSettings

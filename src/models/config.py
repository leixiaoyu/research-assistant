from enum import Enum
from pathlib import Path
from typing import Literal, Union, List, Optional
from datetime import date
from pydantic import BaseModel, Field, field_validator, ConfigDict

from src.utils.security import InputValidation

class TimeframeType(str, Enum):
    RECENT = "recent"
    SINCE_YEAR = "since_year"
    DATE_RANGE = "date_range"

class TimeframeRecent(BaseModel):
    """Recent timeframe (e.g., last 48 hours)"""
    type: Literal[TimeframeType.RECENT] = TimeframeType.RECENT
    value: str = Field(..., pattern=r'^\d+[hd]$', description="Format: '48h' or '7d'")

    @field_validator("value")
    @classmethod
    def validate_recent_format(cls, v: str) -> str:
        unit = v[-1]
        amount = int(v[:-1])
        if unit == 'h' and amount > 720:  # Max 30 days
            raise ValueError("Hour-based timeframe cannot exceed 720h (30 days)")
        if unit == 'd' and amount > 365:
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

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        # Delegate to centralized security utility
        return InputValidation.validate_query(v)

class GlobalSettings(BaseModel):
    """Global pipeline settings"""
    output_base_dir: str = Field("./output", description="Base output directory")
    enable_duplicate_detection: bool = Field(True, description="Enable topic deduplication")
    semantic_scholar_api_key: str = Field(..., min_length=10, description="Semantic Scholar API key")

class ResearchConfig(BaseModel):
    """Root configuration model"""
    model_config = ConfigDict(extra="forbid", use_enum_values=True)
    
    research_topics: List[ResearchTopic] = Field(..., min_length=1, max_length=100)
    settings: GlobalSettings

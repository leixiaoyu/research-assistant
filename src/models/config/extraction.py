"""Extraction configuration models: PDF and LLM settings.

This module contains configuration for PDF processing and LLM extraction:
- PDF backend configuration and fallback chains
- LLM provider settings
- Cost limit controls
"""

from typing import Literal, List, Optional
from pydantic import BaseModel, Field


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

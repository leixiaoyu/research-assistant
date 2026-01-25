"""LLM service data models for Phase 2: PDF Processing & LLM Extraction

This module defines the data structures for:
- LLM provider configuration (Claude/Gemini)
- Cost limits and budget controls
- Usage statistics and tracking
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Literal
from datetime import datetime


class LLMConfig(BaseModel):
    """LLM provider configuration

    Supports both Anthropic (Claude) and Google (Gemini) providers.

    Security Note:
    - API keys must be loaded from environment variables
    - Never hardcode API keys in configuration files
    """

    provider: Literal["anthropic", "google"] = Field(
        default="anthropic", description="LLM provider to use"
    )
    model: str = Field(
        default="claude-3-5-sonnet-20250122", description="Model identifier"
    )
    api_key: str = Field(
        ..., description="API key (from environment variable)", min_length=1
    )
    max_tokens: int = Field(
        default=100000, gt=0, le=200000, description="Maximum tokens per request"
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Sampling temperature (0.0 = deterministic)",
    )
    timeout: int = Field(
        default=300, gt=0, le=600, description="Request timeout in seconds"
    )

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Security: Ensure API key is not placeholder"""
        if v in ["YOUR_API_KEY", "PLACEHOLDER", "", "None"]:
            raise ValueError(
                "API key must be a valid credential from environment variable"
            )
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str, info) -> str:
        """Validate model name matches provider"""
        provider = info.data.get("provider")
        if provider == "anthropic" and not v.startswith("claude"):
            raise ValueError(f"Anthropic provider requires Claude model, got: {v}")
        if provider == "google" and v.startswith("claude"):
            raise ValueError(f"Google provider cannot use Claude model: {v}")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "provider": "anthropic",
                "model": "claude-3-5-sonnet-20250122",
                "api_key": "sk-ant-...",
                "max_tokens": 100000,
                "temperature": 0.0,
                "timeout": 300,
            }
        }
    )


class CostLimits(BaseModel):
    """Cost control configuration for LLM usage

    Implements budget limits at multiple levels:
    - Per-paper token limit (prevents runaway costs on single paper)
    - Daily spending limit (controls daily budget)
    - Total spending limit (lifetime budget cap)
    """

    max_tokens_per_paper: int = Field(
        default=100000, gt=0, le=200000, description="Maximum tokens to use per paper"
    )
    max_daily_spend_usd: float = Field(
        default=50.0, gt=0.0, le=1000.0, description="Maximum daily spending in USD"
    )
    max_total_spend_usd: float = Field(
        default=500.0, gt=0.0, le=10000.0, description="Maximum total spending in USD"
    )

    @field_validator("max_total_spend_usd")
    @classmethod
    def validate_total_exceeds_daily(cls, v: float, info) -> float:
        """Ensure total limit is greater than daily limit"""
        daily = info.data.get("max_daily_spend_usd")
        if daily and v < daily:
            raise ValueError(
                f"max_total_spend_usd ({v}) must be >= max_daily_spend_usd ({daily})"
            )
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "max_tokens_per_paper": 100000,
                "max_daily_spend_usd": 50.0,
                "max_total_spend_usd": 500.0,
            }
        }
    )


class UsageStats(BaseModel):
    """Track LLM usage statistics

    Maintains running totals of:
    - Token consumption
    - Cost in USD
    - Papers processed
    - Last reset timestamp (for daily limits)
    """

    total_tokens: int = Field(default=0, ge=0, description="Total tokens consumed")
    total_cost_usd: float = Field(default=0.0, ge=0.0, description="Total cost in USD")
    papers_processed: int = Field(default=0, ge=0, description="Total papers processed")
    last_reset: datetime = Field(
        default_factory=datetime.utcnow, description="Last time daily stats were reset"
    )

    def reset_daily_stats(self) -> None:
        """Reset daily counters (call at start of new day)"""
        self.total_tokens = 0
        self.total_cost_usd = 0.0
        self.papers_processed = 0
        self.last_reset = datetime.utcnow()

    def should_reset_daily(self) -> bool:
        """Check if daily stats should be reset (new day)"""
        now = datetime.utcnow()
        return now.date() > self.last_reset.date()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_tokens": 450000,
                "total_cost_usd": 15.50,
                "papers_processed": 12,
                "last_reset": "2025-01-24T00:00:00Z",
            }
        }
    )

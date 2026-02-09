"""LLM service data models for Phase 2 & 3.3: Extraction & Resilience

This module defines the data structures for:
- LLM provider configuration (Claude/Gemini)
- Cost limits and budget controls
- Usage statistics and tracking
- Phase 3.3: Retry, circuit breaker, and fallback configuration
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Literal, Optional, Dict
from datetime import datetime


class RetryConfig(BaseModel):
    """Configuration for retry logic with exponential backoff

    Controls retry behavior for transient failures:
    - Number of attempts before giving up
    - Delay calculation parameters
    - Jitter for request spreading
    """

    max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts (1 initial + N-1 retries)",
    )
    base_delay_seconds: float = Field(
        default=1.0,
        gt=0.0,
        le=60.0,
        description="Base delay for exponential backoff",
    )
    max_delay_seconds: float = Field(
        default=60.0,
        gt=0.0,
        le=300.0,
        description="Maximum delay cap",
    )
    jitter_factor: float = Field(
        default=0.1,
        ge=0.0,
        le=0.5,
        description="Jitter factor for randomization",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "max_attempts": 3,
                "base_delay_seconds": 1.0,
                "max_delay_seconds": 60.0,
                "jitter_factor": 0.1,
            }
        }
    )


class CircuitBreakerConfig(BaseModel):
    """Configuration for circuit breaker pattern

    Implements the circuit breaker pattern to prevent cascading failures:
    - CLOSED: Normal operation, requests allowed
    - OPEN: After failure threshold, requests blocked
    - HALF_OPEN: After cooldown, testing with limited requests
    """

    enabled: bool = Field(
        default=True, description="Whether circuit breaker is enabled"
    )
    failure_threshold: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Consecutive failures to open circuit",
    )
    success_threshold: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Consecutive successes to close from half-open",
    )
    cooldown_seconds: float = Field(
        default=300.0,
        gt=0.0,
        le=3600.0,
        description="Seconds before transitioning from OPEN to HALF_OPEN",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "enabled": True,
                "failure_threshold": 5,
                "success_threshold": 2,
                "cooldown_seconds": 300.0,
            }
        }
    )


class FallbackProviderConfig(BaseModel):
    """Configuration for fallback LLM provider

    Configures a secondary provider to use when the primary fails.
    Supports switching between Anthropic and Google providers.
    """

    enabled: bool = Field(default=False, description="Whether fallback is enabled")
    provider: Literal["anthropic", "google"] = Field(
        description="Fallback provider type"
    )
    model: str = Field(description="Fallback model name")
    api_key: Optional[str] = Field(
        default=None,
        description="Separate API key for fallback (uses env var if None)",
        min_length=1,
    )

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: Optional[str]) -> Optional[str]:
        """Security: Ensure API key is not placeholder if provided"""
        if v is not None and v in ["YOUR_API_KEY", "PLACEHOLDER", "", "None"]:
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
                "enabled": True,
                "provider": "anthropic",
                "model": "claude-3-5-sonnet-20250122",
                "api_key": None,
            }
        }
    )


class LLMConfig(BaseModel):
    """LLM provider configuration

    Supports both Anthropic (Claude) and Google (Gemini) providers.
    Phase 3.3 adds retry, circuit breaker, and fallback configuration.

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

    # Phase 3.3: Retry, circuit breaker, and fallback configuration
    retry: RetryConfig = Field(
        default_factory=RetryConfig, description="Retry configuration"
    )
    circuit_breaker: CircuitBreakerConfig = Field(
        default_factory=CircuitBreakerConfig,
        description="Circuit breaker configuration",
    )
    fallback: Optional[FallbackProviderConfig] = Field(
        default=None, description="Fallback provider configuration"
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


# Phase 3.3: Per-Provider Usage Statistics


class ProviderUsageStats(BaseModel):
    """Per-provider usage statistics for Phase 3.3

    Tracks usage and errors for each individual provider:
    - Token consumption and cost
    - Success/failure counts
    - Retry and fallback activations
    """

    provider: str = Field(description="Provider name")
    total_tokens: int = Field(default=0, ge=0, description="Tokens consumed")
    total_cost_usd: float = Field(default=0.0, ge=0.0, description="Cost in USD")
    successful_requests: int = Field(default=0, ge=0, description="Successful requests")
    failed_requests: int = Field(default=0, ge=0, description="Failed requests")
    retry_requests: int = Field(
        default=0, ge=0, description="Requests that were retries"
    )
    fallback_requests: int = Field(
        default=0, ge=0, description="Requests handled as fallback"
    )

    def record_success(self, tokens: int, cost: float, was_retry: bool = False) -> None:
        """Record a successful request."""
        self.total_tokens += tokens
        self.total_cost_usd += cost
        self.successful_requests += 1
        if was_retry:
            self.retry_requests += 1

    def record_failure(self) -> None:
        """Record a failed request."""
        self.failed_requests += 1

    def record_fallback(self, tokens: int, cost: float) -> None:
        """Record a fallback request that succeeded."""
        self.total_tokens += tokens
        self.total_cost_usd += cost
        self.fallback_requests += 1
        self.successful_requests += 1


class EnhancedUsageStats(UsageStats):
    """Enhanced usage stats with per-provider tracking for Phase 3.3

    Extends base UsageStats with:
    - Per-provider breakdown
    - Retry attempt tracking
    - Fallback activation counting
    """

    by_provider: Dict[str, ProviderUsageStats] = Field(
        default_factory=dict, description="Per-provider usage stats"
    )
    total_retry_attempts: int = Field(
        default=0, ge=0, description="Total retry attempts across all providers"
    )
    total_fallback_activations: int = Field(
        default=0, ge=0, description="Total times fallback was activated"
    )

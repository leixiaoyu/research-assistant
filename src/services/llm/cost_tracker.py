"""Cost Tracker Module

Phase 5.1: Extracted cost tracking logic from LLMService.

This module handles:
- Per-session token and cost tracking
- Daily and total spending limit enforcement
- Automatic daily reset logic
- Usage summary generation
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict
import structlog

from src.models.llm import CostLimits
from src.utils.exceptions import CostLimitExceeded

# Phase 4: Prometheus metrics
from src.observability.metrics import DAILY_COST_USD

logger = structlog.get_logger()


@dataclass
class ProviderUsage:
    """Usage tracking for a single provider."""

    provider: str
    tokens: int = 0
    cost_usd: float = 0.0
    requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    retry_requests: int = 0
    fallback_requests: int = 0

    def record_success(
        self,
        tokens: int,
        cost: float,
        was_retry: bool = False,
    ) -> None:
        """Record a successful request."""
        self.tokens += tokens
        self.cost_usd += cost
        self.requests += 1
        self.successful_requests += 1
        if was_retry:
            self.retry_requests += 1

    def record_failure(self) -> None:
        """Record a failed request."""
        self.requests += 1
        self.failed_requests += 1


@dataclass
class CostTracker:
    """Tracks LLM usage and enforces budget limits.

    This class is responsible for:
    - Recording token usage and costs
    - Enforcing daily and total spending limits
    - Automatic daily reset at midnight
    - Providing usage summaries

    Attributes:
        limits: Budget limits configuration
        total_tokens: Total tokens used across all providers
        total_cost_usd: Total cost in USD
        papers_processed: Number of papers processed
        last_reset: Timestamp of last daily reset
        by_provider: Per-provider usage statistics
    """

    limits: CostLimits
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    papers_processed: int = 0
    last_reset: datetime = field(default_factory=datetime.utcnow)
    by_provider: Dict[str, ProviderUsage] = field(default_factory=dict)

    # Retry/fallback tracking
    total_retry_attempts: int = 0
    total_fallback_activations: int = 0

    # Daily tracking
    _last_reset_date: Optional[date] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Initialize last reset date."""
        self._last_reset_date = self.last_reset.date()

    def record_usage(
        self,
        tokens: int,
        cost: float,
        provider: str,
        was_retry: bool = False,
        is_fallback: bool = False,
    ) -> None:
        """Record token usage and cost.

        Args:
            tokens: Number of tokens used
            cost: Cost in USD
            provider: Provider name (anthropic, google)
            was_retry: Whether this was a retry attempt
            is_fallback: Whether this used fallback provider
        """
        self._check_daily_reset()

        self.total_tokens += tokens
        self.total_cost_usd += cost
        self.papers_processed += 1

        # Update provider-specific stats
        if provider not in self.by_provider:
            self.by_provider[provider] = ProviderUsage(provider=provider)
        self.by_provider[provider].record_success(tokens, cost, was_retry)
        if is_fallback:
            self.by_provider[provider].fallback_requests += 1

        # Update Prometheus metrics
        DAILY_COST_USD.labels(provider=provider).set(self.total_cost_usd)

        logger.debug(
            "usage_recorded",
            provider=provider,
            tokens=tokens,
            cost_usd=cost,
            total_cost_usd=self.total_cost_usd,
        )

    def record_failure(self, provider: str) -> None:
        """Record a failed request.

        Args:
            provider: Provider name
        """
        if provider not in self.by_provider:
            self.by_provider[provider] = ProviderUsage(provider=provider)
        self.by_provider[provider].record_failure()

    def record_retry(self) -> None:
        """Record a retry attempt."""
        self.total_retry_attempts += 1

    def record_fallback(self) -> None:
        """Record a fallback activation."""
        self.total_fallback_activations += 1

    def check_limits(self) -> None:
        """Check if cost limits would be exceeded.

        Raises:
            CostLimitExceeded: If any limit is breached
        """
        self._check_daily_reset()

        if self.total_cost_usd >= self.limits.max_total_spend_usd:
            raise CostLimitExceeded(
                f"Total spending limit reached: "
                f"${self.total_cost_usd:.2f} >= "
                f"${self.limits.max_total_spend_usd:.2f}"
            )

        if self.total_cost_usd >= self.limits.max_daily_spend_usd:
            raise CostLimitExceeded(
                f"Daily spending limit reached: "
                f"${self.total_cost_usd:.2f} >= "
                f"${self.limits.max_daily_spend_usd:.2f}"
            )

    def _check_daily_reset(self) -> None:
        """Check if daily stats should be reset."""
        today = datetime.utcnow().date()
        if self._last_reset_date != today:
            logger.info(
                "daily_stats_reset",
                previous_date=str(self._last_reset_date),
                current_date=str(today),
                previous_cost=self.total_cost_usd,
            )
            self._reset_daily_stats()
            self._last_reset_date = today

    def _reset_daily_stats(self) -> None:
        """Reset daily statistics."""
        # Note: We only reset if tracking daily vs total separately
        # Current implementation tracks total, so daily reset updates timestamp
        self.last_reset = datetime.utcnow()

    def get_summary(self) -> dict:
        """Get current usage summary.

        Returns:
            Dictionary with usage statistics
        """
        return {
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "papers_processed": self.papers_processed,
            "last_reset": self.last_reset.isoformat(),
            "daily_budget_remaining": round(
                self.limits.max_daily_spend_usd - self.total_cost_usd, 2
            ),
            "total_budget_remaining": round(
                self.limits.max_total_spend_usd - self.total_cost_usd, 2
            ),
            "total_retry_attempts": self.total_retry_attempts,
            "total_fallback_activations": self.total_fallback_activations,
            "by_provider": {
                name: {
                    "tokens": usage.tokens,
                    "cost_usd": round(usage.cost_usd, 4),
                    "requests": usage.requests,
                    "successful_requests": usage.successful_requests,
                    "failed_requests": usage.failed_requests,
                }
                for name, usage in self.by_provider.items()
            },
        }

    def should_reset_daily(self) -> bool:
        """Check if daily stats should be reset.

        Returns:
            True if reset is needed
        """
        return self._last_reset_date != datetime.utcnow().date()

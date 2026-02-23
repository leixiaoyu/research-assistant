"""Tests for CostTracker module.

Phase 5.1: Tests for cost tracking and budget enforcement.
"""

import pytest
from datetime import date
from unittest.mock import patch

from src.services.llm.cost_tracker import CostTracker, ProviderUsage
from src.models.llm import CostLimits
from src.utils.exceptions import CostLimitExceeded


class TestProviderUsage:
    """Tests for ProviderUsage dataclass."""

    def test_initial_values(self) -> None:
        """Test initial values are zero."""
        usage = ProviderUsage(provider="anthropic")
        assert usage.tokens == 0
        assert usage.cost_usd == 0.0
        assert usage.requests == 0
        assert usage.successful_requests == 0
        assert usage.failed_requests == 0

    def test_record_success(self) -> None:
        """Test recording a successful request."""
        usage = ProviderUsage(provider="anthropic")
        usage.record_success(tokens=1000, cost=0.05, was_retry=False)

        assert usage.tokens == 1000
        assert usage.cost_usd == 0.05
        assert usage.requests == 1
        assert usage.successful_requests == 1
        assert usage.retry_requests == 0

    def test_record_success_with_retry(self) -> None:
        """Test recording success after retry."""
        usage = ProviderUsage(provider="google")
        usage.record_success(tokens=500, cost=0.02, was_retry=True)

        assert usage.retry_requests == 1

    def test_record_failure(self) -> None:
        """Test recording a failed request."""
        usage = ProviderUsage(provider="anthropic")
        usage.record_failure()

        assert usage.requests == 1
        assert usage.failed_requests == 1
        assert usage.successful_requests == 0

    def test_multiple_operations(self) -> None:
        """Test multiple success and failure operations."""
        usage = ProviderUsage(provider="anthropic")
        usage.record_success(tokens=1000, cost=0.05, was_retry=False)
        usage.record_success(tokens=2000, cost=0.10, was_retry=False)
        usage.record_failure()

        assert usage.tokens == 3000
        assert abs(usage.cost_usd - 0.15) < 1e-10  # Float comparison
        assert usage.requests == 3
        assert usage.successful_requests == 2
        assert usage.failed_requests == 1


class TestCostTracker:
    """Tests for CostTracker class."""

    @pytest.fixture
    def limits(self) -> CostLimits:
        """Create test cost limits."""
        return CostLimits(
            max_daily_spend_usd=10.0,
            max_total_spend_usd=100.0,
        )

    @pytest.fixture
    def tracker(self, limits: CostLimits) -> CostTracker:
        """Create test cost tracker."""
        return CostTracker(limits=limits)

    def test_initial_state(self, tracker: CostTracker) -> None:
        """Test initial tracker state."""
        assert tracker.total_tokens == 0
        assert tracker.total_cost_usd == 0.0
        assert tracker.papers_processed == 0

    def test_record_usage(self, tracker: CostTracker) -> None:
        """Test recording usage."""
        tracker.record_usage(
            tokens=1000,
            cost=0.05,
            provider="anthropic",
        )

        assert tracker.total_tokens == 1000
        assert tracker.total_cost_usd == 0.05
        assert tracker.papers_processed == 1

    def test_record_usage_updates_provider_stats(self, tracker: CostTracker) -> None:
        """Test provider-specific stats are updated."""
        tracker.record_usage(tokens=1000, cost=0.05, provider="anthropic")
        tracker.record_usage(tokens=500, cost=0.02, provider="google")

        assert "anthropic" in tracker.by_provider
        assert "google" in tracker.by_provider
        assert tracker.by_provider["anthropic"].tokens == 1000
        assert tracker.by_provider["google"].tokens == 500

    def test_record_failure(self, tracker: CostTracker) -> None:
        """Test recording a failure."""
        tracker.record_failure("anthropic")

        assert "anthropic" in tracker.by_provider
        assert tracker.by_provider["anthropic"].failed_requests == 1

    def test_record_retry(self, tracker: CostTracker) -> None:
        """Test recording retry attempts."""
        tracker.record_retry()
        tracker.record_retry()

        assert tracker.total_retry_attempts == 2

    def test_record_fallback(self, tracker: CostTracker) -> None:
        """Test recording fallback activations."""
        tracker.record_fallback()

        assert tracker.total_fallback_activations == 1

    def test_check_limits_passes_under_budget(self, tracker: CostTracker) -> None:
        """Test check_limits passes when under budget."""
        tracker.record_usage(tokens=1000, cost=5.0, provider="anthropic")
        # Should not raise
        tracker.check_limits()

    def test_check_limits_raises_on_daily_exceed(self, tracker: CostTracker) -> None:
        """Test check_limits raises when daily limit exceeded."""
        tracker.record_usage(tokens=10000, cost=15.0, provider="anthropic")

        with pytest.raises(CostLimitExceeded) as exc_info:
            tracker.check_limits()

        assert "Daily" in str(exc_info.value) or "daily" in str(exc_info.value)

    def test_check_limits_raises_on_total_exceed(self, limits: CostLimits) -> None:
        """Test check_limits raises when total limit exceeded."""
        # Create tracker with lower total limit
        limits.max_total_spend_usd = 5.0
        tracker = CostTracker(limits=limits)
        tracker.record_usage(tokens=10000, cost=6.0, provider="anthropic")

        with pytest.raises(CostLimitExceeded) as exc_info:
            tracker.check_limits()

        assert "Total" in str(exc_info.value) or "total" in str(exc_info.value)

    def test_get_summary(self, tracker: CostTracker) -> None:
        """Test getting usage summary."""
        tracker.record_usage(tokens=1000, cost=1.0, provider="anthropic")

        summary = tracker.get_summary()

        assert summary["total_tokens"] == 1000
        assert summary["total_cost_usd"] == 1.0
        assert summary["papers_processed"] == 1
        assert "daily_budget_remaining" in summary
        assert "total_budget_remaining" in summary
        assert "last_reset" in summary

    def test_get_summary_provider_breakdown(self, tracker: CostTracker) -> None:
        """Test summary includes provider breakdown."""
        tracker.record_usage(tokens=1000, cost=0.05, provider="anthropic")
        tracker.record_usage(tokens=500, cost=0.02, provider="google")

        summary = tracker.get_summary()

        assert "by_provider" in summary
        assert "anthropic" in summary["by_provider"]
        assert "google" in summary["by_provider"]

    def test_should_reset_daily(self, tracker: CostTracker) -> None:
        """Test daily reset detection."""
        # Same day - should not reset
        assert not tracker.should_reset_daily()

        # Mock different date
        with patch.object(tracker, "_last_reset_date", date(2020, 1, 1)):
            assert tracker.should_reset_daily()


class TestCostTrackerDailyReset:
    """Tests for daily reset functionality."""

    def test_check_daily_reset_same_day(self) -> None:
        """Test no reset on same day."""
        limits = CostLimits(max_daily_spend_usd=100.0, max_total_spend_usd=1000.0)
        tracker = CostTracker(limits=limits)

        tracker.record_usage(tokens=1000, cost=5.0, provider="anthropic")

        # Should not reset on same day
        tracker._check_daily_reset()

        assert tracker.total_cost_usd == 5.0

    def test_check_daily_reset_different_day(self) -> None:
        """Test reset on different day."""
        from datetime import datetime

        limits = CostLimits(max_daily_spend_usd=100.0, max_total_spend_usd=1000.0)
        tracker = CostTracker(limits=limits)

        tracker.record_usage(tokens=1000, cost=5.0, provider="anthropic")

        # Simulate day change
        with patch.object(tracker, "_last_reset_date", date(2020, 1, 1)):
            tracker._check_daily_reset()

        # Reset should have updated last_reset to current UTC date
        assert tracker._last_reset_date == datetime.utcnow().date()

    def test_reset_daily_stats(self) -> None:
        """Test _reset_daily_stats updates timestamp."""
        limits = CostLimits(max_daily_spend_usd=100.0, max_total_spend_usd=1000.0)
        tracker = CostTracker(limits=limits)

        old_reset = tracker.last_reset
        tracker._reset_daily_stats()

        assert tracker.last_reset >= old_reset


class TestCostTrackerFallbackTracking:
    """Tests for fallback request tracking."""

    def test_record_usage_with_fallback(self) -> None:
        """Test recording usage with fallback flag."""
        limits = CostLimits(max_daily_spend_usd=100.0, max_total_spend_usd=1000.0)
        tracker = CostTracker(limits=limits)

        tracker.record_usage(
            tokens=1000,
            cost=0.05,
            provider="google",
            is_fallback=True,
        )

        assert tracker.by_provider["google"].fallback_requests == 1

    def test_record_usage_without_fallback(self) -> None:
        """Test recording usage without fallback flag."""
        limits = CostLimits(max_daily_spend_usd=100.0, max_total_spend_usd=1000.0)
        tracker = CostTracker(limits=limits)

        tracker.record_usage(
            tokens=1000,
            cost=0.05,
            provider="anthropic",
            is_fallback=False,
        )

        assert tracker.by_provider["anthropic"].fallback_requests == 0


class TestCostTrackerBehavioralEquivalence:
    """Behavioral equivalence tests for cost calculation.

    These tests verify that cost calculations in the new CostTracker
    match the original LLMService calculations exactly.
    """

    def test_cost_tracking_accumulation(self) -> None:
        """Test cost accumulation matches expected behavior."""
        limits = CostLimits(max_daily_spend_usd=100.0, max_total_spend_usd=1000.0)
        tracker = CostTracker(limits=limits)

        # Simulate multiple paper extractions
        costs = [0.05, 0.10, 0.03, 0.15, 0.08]
        tokens = [1000, 2000, 500, 3000, 1500]

        for t, c in zip(tokens, costs):
            tracker.record_usage(tokens=t, cost=c, provider="anthropic")

        # Verify totals
        assert tracker.total_tokens == sum(tokens)
        assert abs(tracker.total_cost_usd - sum(costs)) < 1e-10
        assert tracker.papers_processed == len(costs)

    def test_budget_remaining_calculation(self) -> None:
        """Test budget remaining is calculated correctly."""
        limits = CostLimits(max_daily_spend_usd=10.0, max_total_spend_usd=100.0)
        tracker = CostTracker(limits=limits)

        tracker.record_usage(tokens=1000, cost=3.5, provider="anthropic")

        summary = tracker.get_summary()
        assert abs(summary["daily_budget_remaining"] - 6.5) < 0.01
        assert abs(summary["total_budget_remaining"] - 96.5) < 0.01

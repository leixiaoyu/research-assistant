"""Unit tests for Phase 3.3 LLM models coverage.

Tests for:
- FallbackProviderConfig validation
- ProviderUsageStats methods
- EnhancedUsageStats methods
"""

import pytest
from pydantic import ValidationError

from src.models.llm import (
    FallbackProviderConfig,
    ProviderUsageStats,
    EnhancedUsageStats,
)


class TestFallbackProviderConfigValidation:
    """Tests for FallbackProviderConfig validation."""

    def test_placeholder_api_key_your_api_key(self):
        """Test rejection of YOUR_API_KEY placeholder."""
        with pytest.raises(ValidationError, match="valid credential"):
            FallbackProviderConfig(
                enabled=True,
                provider="anthropic",
                model="claude-3-5-sonnet-20250122",
                api_key="YOUR_API_KEY",
            )

    def test_placeholder_api_key_placeholder(self):
        """Test rejection of PLACEHOLDER."""
        with pytest.raises(ValidationError, match="valid credential"):
            FallbackProviderConfig(
                enabled=True,
                provider="anthropic",
                model="claude-3-5-sonnet-20250122",
                api_key="PLACEHOLDER",
            )

    def test_placeholder_api_key_empty_string(self):
        """Test rejection of empty string API key."""
        # Empty string is caught by Pydantic's min_length=1 constraint
        with pytest.raises(ValidationError, match="string_too_short"):
            FallbackProviderConfig(
                enabled=True,
                provider="anthropic",
                model="claude-3-5-sonnet-20250122",
                api_key="",
            )

    def test_placeholder_api_key_none_string(self):
        """Test rejection of 'None' string API key."""
        with pytest.raises(ValidationError, match="valid credential"):
            FallbackProviderConfig(
                enabled=True,
                provider="anthropic",
                model="claude-3-5-sonnet-20250122",
                api_key="None",
            )

    def test_valid_api_key_accepted(self):
        """Test valid API key is accepted."""
        config = FallbackProviderConfig(
            enabled=True,
            provider="anthropic",
            model="claude-3-5-sonnet-20250122",
            api_key="sk-ant-valid-key-12345",
        )
        assert config.api_key == "sk-ant-valid-key-12345"

    def test_none_api_key_accepted(self):
        """Test None API key is accepted (will use env var)."""
        config = FallbackProviderConfig(
            enabled=True,
            provider="anthropic",
            model="claude-3-5-sonnet-20250122",
            api_key=None,
        )
        assert config.api_key is None

    def test_anthropic_provider_requires_claude_model(self):
        """Test Anthropic provider requires Claude model."""
        with pytest.raises(ValidationError, match="Claude model"):
            FallbackProviderConfig(
                enabled=True,
                provider="anthropic",
                model="gemini-1.5-pro",
                api_key="valid-key",
            )

    def test_google_provider_rejects_claude_model(self):
        """Test Google provider rejects Claude model."""
        with pytest.raises(ValidationError, match="cannot use Claude"):
            FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="claude-3-5-sonnet-20250122",
                api_key="valid-key",
            )

    def test_google_provider_accepts_gemini_model(self):
        """Test Google provider accepts Gemini model."""
        config = FallbackProviderConfig(
            enabled=True,
            provider="google",
            model="gemini-1.5-pro",
            api_key="valid-key",
        )
        assert config.model == "gemini-1.5-pro"


class TestProviderUsageStatsExtended:
    """Extended tests for ProviderUsageStats."""

    def test_record_success_with_retry(self):
        """Test recording success that was a retry."""
        stats = ProviderUsageStats(provider="anthropic")
        stats.record_success(tokens=1000, cost=0.05, was_retry=True)

        assert stats.total_tokens == 1000
        assert stats.total_cost_usd == 0.05
        assert stats.successful_requests == 1
        assert stats.retry_requests == 1

    def test_record_success_without_retry(self):
        """Test recording success that was not a retry."""
        stats = ProviderUsageStats(provider="anthropic")
        stats.record_success(tokens=1000, cost=0.05, was_retry=False)

        assert stats.retry_requests == 0
        assert stats.successful_requests == 1

    def test_record_fallback(self):
        """Test recording a fallback request."""
        stats = ProviderUsageStats(provider="google")
        stats.record_fallback(tokens=2000, cost=0.10)

        assert stats.total_tokens == 2000
        assert stats.total_cost_usd == 0.10
        assert stats.fallback_requests == 1
        assert stats.successful_requests == 1

    def test_multiple_operations(self):
        """Test accumulating multiple operations."""
        stats = ProviderUsageStats(provider="anthropic")

        stats.record_success(tokens=1000, cost=0.05, was_retry=False)
        stats.record_success(tokens=2000, cost=0.10, was_retry=True)
        stats.record_failure()
        stats.record_fallback(tokens=1500, cost=0.08)

        assert stats.total_tokens == 4500  # 1000 + 2000 + 1500
        # Use approximate comparison for floating point
        assert abs(stats.total_cost_usd - 0.23) < 0.001  # 0.05 + 0.10 + 0.08
        assert stats.successful_requests == 3  # 2 success + 1 fallback
        assert stats.failed_requests == 1
        assert stats.retry_requests == 1
        assert stats.fallback_requests == 1


class TestEnhancedUsageStatsExtended:
    """Extended tests for EnhancedUsageStats."""

    def test_initial_values(self):
        """Test EnhancedUsageStats initial values."""
        stats = EnhancedUsageStats()

        assert stats.total_retry_attempts == 0
        assert stats.total_fallback_activations == 0
        assert stats.by_provider == {}

    def test_tracking_multiple_providers(self):
        """Test tracking stats for multiple providers."""
        stats = EnhancedUsageStats()

        # Add Anthropic provider
        stats.by_provider["anthropic"] = ProviderUsageStats(provider="anthropic")
        stats.by_provider["anthropic"].record_success(tokens=1000, cost=0.05)

        # Add Google provider
        stats.by_provider["google"] = ProviderUsageStats(provider="google")
        stats.by_provider["google"].record_fallback(tokens=2000, cost=0.10)

        assert len(stats.by_provider) == 2
        assert stats.by_provider["anthropic"].total_tokens == 1000
        assert stats.by_provider["google"].total_tokens == 2000
        assert stats.by_provider["google"].fallback_requests == 1

    def test_retry_and_fallback_counters(self):
        """Test global retry and fallback counters."""
        stats = EnhancedUsageStats()

        stats.total_retry_attempts = 5
        stats.total_fallback_activations = 2

        assert stats.total_retry_attempts == 5
        assert stats.total_fallback_activations == 2

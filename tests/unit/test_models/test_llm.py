"""Unit tests for LLM data models (Phase 2)

Tests for:
- LLMConfig
- CostLimits
- UsageStats
"""

import pytest
from datetime import datetime, timedelta
from pydantic import ValidationError

from src.models.llm import LLMConfig, CostLimits, UsageStats


def test_llm_config_anthropic():
    """Test valid Anthropic LLMConfig"""
    config = LLMConfig(
        provider="anthropic",
        model="claude-3-5-sonnet-20250122",
        api_key="sk-ant-test12345",
        max_tokens=100000,
        temperature=0.0,
        timeout=300
    )

    assert config.provider == "anthropic"
    assert config.model == "claude-3-5-sonnet-20250122"
    assert config.max_tokens == 100000
    assert config.temperature == 0.0


def test_llm_config_google():
    """Test valid Google LLMConfig"""
    config = LLMConfig(
        provider="google",
        model="gemini-1.5-pro",
        api_key="test-google-key"
    )

    assert config.provider == "google"
    assert config.model == "gemini-1.5-pro"


def test_llm_config_invalid_api_key():
    """Test LLMConfig rejects invalid API keys"""
    # Test placeholder keys that should trigger custom validator
    placeholder_keys = ["YOUR_API_KEY", "PLACEHOLDER", "None"]
    for key in placeholder_keys:
        with pytest.raises(ValidationError) as exc_info:
            LLMConfig(
                provider="anthropic",
                model="claude-3-5-sonnet-20250122",
                api_key=key
            )
        assert "API key must be a valid credential" in str(exc_info.value)

    # Test empty string which triggers Pydantic's min_length validation
    with pytest.raises(ValidationError) as exc_info:
        LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20250122",
            api_key=""
        )
    assert "String should have at least" in str(exc_info.value)


def test_llm_config_model_provider_mismatch():
    """Test LLMConfig validates model matches provider"""
    # Anthropic with Gemini model
    with pytest.raises(ValidationError) as exc_info:
        LLMConfig(
            provider="anthropic",
            model="gemini-1.5-pro",
            api_key="sk-ant-test"
        )
    assert "Anthropic provider requires Claude model" in str(exc_info.value)

    # Google with Claude model
    with pytest.raises(ValidationError) as exc_info:
        LLMConfig(
            provider="google",
            model="claude-3-5-sonnet-20250122",
            api_key="google-test"
        )
    assert "Google provider cannot use Claude model" in str(exc_info.value)


def test_llm_config_temperature_range():
    """Test temperature must be between 0 and 1"""
    # Valid temperatures
    LLMConfig(provider="anthropic", model="claude-3-5-sonnet-20250122", api_key="test", temperature=0.0)
    LLMConfig(provider="anthropic", model="claude-3-5-sonnet-20250122", api_key="test", temperature=1.0)
    LLMConfig(provider="anthropic", model="claude-3-5-sonnet-20250122", api_key="test", temperature=0.5)

    # Invalid temperatures
    with pytest.raises(ValidationError):
        LLMConfig(provider="anthropic", model="claude-3-5-sonnet-20250122", api_key="test", temperature=-0.1)

    with pytest.raises(ValidationError):
        LLMConfig(provider="anthropic", model="claude-3-5-sonnet-20250122", api_key="test", temperature=1.1)


def test_llm_config_max_tokens_range():
    """Test max_tokens validation"""
    # Valid
    LLMConfig(provider="anthropic", model="claude-3-5-sonnet-20250122", api_key="test", max_tokens=1000)
    LLMConfig(provider="anthropic", model="claude-3-5-sonnet-20250122", api_key="test", max_tokens=200000)

    # Invalid - too small
    with pytest.raises(ValidationError):
        LLMConfig(provider="anthropic", model="claude-3-5-sonnet-20250122", api_key="test", max_tokens=0)

    # Invalid - too large
    with pytest.raises(ValidationError):
        LLMConfig(provider="anthropic", model="claude-3-5-sonnet-20250122", api_key="test", max_tokens=300000)


def test_cost_limits_valid():
    """Test valid CostLimits"""
    limits = CostLimits(
        max_tokens_per_paper=100000,
        max_daily_spend_usd=50.0,
        max_total_spend_usd=500.0
    )

    assert limits.max_tokens_per_paper == 100000
    assert limits.max_daily_spend_usd == 50.0
    assert limits.max_total_spend_usd == 500.0


def test_cost_limits_total_exceeds_daily():
    """Test total spending must be >= daily spending"""
    # Valid - total > daily
    CostLimits(
        max_tokens_per_paper=100000,
        max_daily_spend_usd=50.0,
        max_total_spend_usd=500.0
    )

    # Valid - total == daily
    CostLimits(
        max_tokens_per_paper=100000,
        max_daily_spend_usd=100.0,
        max_total_spend_usd=100.0
    )

    # Invalid - total < daily
    with pytest.raises(ValidationError) as exc_info:
        CostLimits(
            max_tokens_per_paper=100000,
            max_daily_spend_usd=100.0,
            max_total_spend_usd=50.0
        )
    assert "must be >=" in str(exc_info.value)


def test_cost_limits_ranges():
    """Test CostLimits validates ranges"""
    # Invalid - negative values
    with pytest.raises(ValidationError):
        CostLimits(
            max_tokens_per_paper=-1000,
            max_daily_spend_usd=50.0,
            max_total_spend_usd=500.0
        )

    with pytest.raises(ValidationError):
        CostLimits(
            max_tokens_per_paper=100000,
            max_daily_spend_usd=-10.0,
            max_total_spend_usd=500.0
        )


def test_usage_stats_defaults():
    """Test UsageStats with defaults"""
    stats = UsageStats()

    assert stats.total_tokens == 0
    assert stats.total_cost_usd == 0.0
    assert stats.papers_processed == 0
    assert isinstance(stats.last_reset, datetime)


def test_usage_stats_with_values():
    """Test UsageStats with custom values"""
    now = datetime.utcnow()
    stats = UsageStats(
        total_tokens=50000,
        total_cost_usd=2.5,
        papers_processed=10,
        last_reset=now
    )

    assert stats.total_tokens == 50000
    assert stats.total_cost_usd == 2.5
    assert stats.papers_processed == 10
    assert stats.last_reset == now


def test_usage_stats_reset_daily():
    """Test reset_daily_stats()"""
    stats = UsageStats(
        total_tokens=100000,
        total_cost_usd=5.0,
        papers_processed=20
    )

    old_reset_time = stats.last_reset

    # Reset stats
    stats.reset_daily_stats()

    assert stats.total_tokens == 0
    assert stats.total_cost_usd == 0.0
    assert stats.papers_processed == 0
    assert stats.last_reset > old_reset_time


def test_usage_stats_should_reset_daily():
    """Test should_reset_daily()"""
    # Same day - should not reset
    now = datetime.utcnow()
    stats = UsageStats(last_reset=now)
    assert not stats.should_reset_daily()

    # Yesterday - should reset
    yesterday = now - timedelta(days=1)
    stats = UsageStats(last_reset=yesterday)
    assert stats.should_reset_daily()

    # Two days ago - should reset
    two_days_ago = now - timedelta(days=2)
    stats = UsageStats(last_reset=two_days_ago)
    assert stats.should_reset_daily()


def test_usage_stats_negative_values():
    """Test UsageStats rejects negative values"""
    with pytest.raises(ValidationError):
        UsageStats(total_tokens=-100)

    with pytest.raises(ValidationError):
        UsageStats(total_cost_usd=-1.0)

    with pytest.raises(ValidationError):
        UsageStats(papers_processed=-5)

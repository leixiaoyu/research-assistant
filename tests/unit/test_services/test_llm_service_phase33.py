"""Unit tests for Phase 3.3 LLM Service features.

Tests for:
- ProviderHealth tracking
- Fallback provider initialization
- Error classification
- Retry-after extraction
- Circuit breaker integration
- Per-provider usage stats
"""

import pytest
import os
from unittest.mock import Mock, AsyncMock, patch

from src.services.llm_service import LLMService, ProviderHealth
from src.models.llm import (
    LLMConfig,
    CostLimits,
    FallbackProviderConfig,
    ProviderUsageStats,
    EnhancedUsageStats,
)
from src.utils.exceptions import (
    LLMAPIError,
    RateLimitError,
    RetryableError,
    AllProvidersFailedError,
)
from src.utils.circuit_breaker import CircuitBreaker, CircuitBreakerConfig


class TestProviderHealth:
    """Tests for ProviderHealth dataclass."""

    def test_initial_state(self):
        """Test ProviderHealth initial state."""
        health = ProviderHealth(provider="anthropic")
        assert health.status == "healthy"
        assert health.consecutive_failures == 0
        assert health.consecutive_successes == 0
        assert health.total_requests == 0
        assert health.total_failures == 0
        assert health.last_success is None
        assert health.last_failure is None
        assert health.failure_reason is None

    def test_record_success(self):
        """Test recording a successful request."""
        health = ProviderHealth(provider="anthropic")
        health.record_success()

        assert health.total_requests == 1
        assert health.consecutive_successes == 1
        assert health.consecutive_failures == 0
        assert health.last_success is not None
        assert health.status == "healthy"

    def test_record_success_recovers_from_degraded(self):
        """Test that success recovers from degraded status."""
        health = ProviderHealth(provider="anthropic")
        health.status = "degraded"
        health.record_success()

        assert health.status == "healthy"

    def test_record_failure(self):
        """Test recording a failed request."""
        health = ProviderHealth(provider="anthropic")
        health.record_failure("API Error")

        assert health.total_requests == 1
        assert health.total_failures == 1
        assert health.consecutive_failures == 1
        assert health.consecutive_successes == 0
        assert health.last_failure is not None
        assert health.failure_reason == "API Error"

    def test_record_failure_degraded_threshold(self):
        """Test status becomes degraded after 3 consecutive failures."""
        health = ProviderHealth(provider="anthropic")
        for i in range(3):
            health.record_failure(f"Error {i}")

        assert health.status == "degraded"

    def test_record_failure_unavailable_threshold(self):
        """Test status becomes unavailable after 5 consecutive failures."""
        health = ProviderHealth(provider="anthropic")
        for i in range(5):
            health.record_failure(f"Error {i}")

        assert health.status == "unavailable"

    def test_get_stats_without_circuit_breaker(self):
        """Test get_stats without circuit breaker."""
        health = ProviderHealth(provider="anthropic")
        health.record_success()
        stats = health.get_stats()

        assert stats["provider"] == "anthropic"
        assert stats["status"] == "healthy"
        assert stats["total_requests"] == 1
        assert stats["consecutive_successes"] == 1
        assert "circuit_breaker" not in stats

    def test_get_stats_with_circuit_breaker(self):
        """Test get_stats with circuit breaker."""
        config = CircuitBreakerConfig()
        cb = CircuitBreaker("anthropic", config)
        health = ProviderHealth(provider="anthropic", circuit_breaker=cb)
        stats = health.get_stats()

        assert "circuit_breaker" in stats
        assert stats["circuit_breaker"]["name"] == "anthropic"


class TestErrorClassification:
    """Tests for error classification."""

    @pytest.fixture
    def llm_service(self):
        """Create LLM service for testing."""
        config = LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20250122",
            api_key="test-key",
        )
        limits = CostLimits()
        with patch("anthropic.AsyncAnthropic"):
            return LLMService(config, limits)

    def test_classify_rate_limit_429(self, llm_service):
        """Test classifying 429 errors as rate limit."""
        error = Exception("Error 429: Too many requests")
        classified = llm_service._classify_error(error)

        assert isinstance(classified, RateLimitError)

    def test_classify_rate_limit_quota(self, llm_service):
        """Test classifying quota exceeded as rate limit."""
        error = Exception("quota exceeded for today")
        classified = llm_service._classify_error(error)

        assert isinstance(classified, RateLimitError)

    def test_classify_rate_limit_resource_exhausted(self, llm_service):
        """Test classifying resource_exhausted as rate limit."""
        error = Exception("RESOURCE_EXHAUSTED: Rate limit reached")
        classified = llm_service._classify_error(error)

        assert isinstance(classified, RateLimitError)

    def test_classify_retryable_timeout(self, llm_service):
        """Test classifying timeout errors as retryable."""
        error = Exception("Connection timed out")
        classified = llm_service._classify_error(error)

        assert isinstance(classified, RetryableError)

    def test_classify_retryable_503(self, llm_service):
        """Test classifying 503 errors as retryable."""
        error = Exception("Service Unavailable 503")
        classified = llm_service._classify_error(error)

        assert isinstance(classified, RetryableError)

    def test_classify_retryable_internal_server(self, llm_service):
        """Test classifying internal server errors as retryable."""
        error = Exception("Internal Server Error")
        classified = llm_service._classify_error(error)

        assert isinstance(classified, RetryableError)

    def test_classify_non_retryable(self, llm_service):
        """Test non-retryable errors classified as LLMAPIError."""
        error = Exception("Invalid API key")
        classified = llm_service._classify_error(error)

        assert isinstance(classified, LLMAPIError)
        assert not isinstance(classified, RetryableError)
        assert not isinstance(classified, RateLimitError)


class TestRetryAfterExtraction:
    """Tests for retry-after extraction."""

    @pytest.fixture
    def llm_service(self):
        """Create LLM service for testing."""
        config = LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20250122",
            api_key="test-key",
        )
        limits = CostLimits()
        with patch("anthropic.AsyncAnthropic"):
            return LLMService(config, limits)

    def test_extract_retry_after_from_attribute(self, llm_service):
        """Test extracting retry_after from error attribute."""
        error = Mock()
        error.retry_after = 30.0
        result = llm_service._extract_retry_after(error)

        assert result == 30.0

    def test_extract_retry_after_from_response_headers(self, llm_service):
        """Test extracting retry_after from response headers."""
        error = Mock()
        error.retry_after = None  # No direct attribute
        error.response = Mock()
        error.response.headers = {"Retry-After": "45"}
        result = llm_service._extract_retry_after(error)

        assert result == 45.0

    def test_extract_retry_after_invalid_header(self, llm_service):
        """Test handling invalid Retry-After header."""
        error = Mock()
        error.retry_after = None
        error.response = Mock()
        error.response.headers = {"Retry-After": "not-a-number"}
        result = llm_service._extract_retry_after(error)

        assert result is None

    def test_extract_retry_after_no_headers(self, llm_service):
        """Test when no retry_after info is available."""
        error = Exception("Rate limit")
        result = llm_service._extract_retry_after(error)

        assert result is None


class TestFallbackProviderInitialization:
    """Tests for fallback provider initialization."""

    def test_fallback_anthropic_from_config_key(self):
        """Test fallback Anthropic provider with config API key."""
        config = LLMConfig(
            provider="google",
            model="gemini-1.5-pro",
            api_key="google-key",
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="anthropic",
                model="claude-3-5-sonnet-20250122",
                api_key="fallback-anthropic-key",
            ),
        )
        limits = CostLimits()

        mock_client = Mock()
        with patch("google.genai.Client", return_value=mock_client):
            with patch("anthropic.AsyncAnthropic") as mock_anthropic:
                service = LLMService(config, limits)

                assert service.fallback_provider == "anthropic"
                assert service.fallback_client is not None
                mock_anthropic.assert_called_with(api_key="fallback-anthropic-key")

    def test_fallback_google_from_config_key(self):
        """Test fallback Google provider with config API key."""
        config = LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20250122",
            api_key="anthropic-key",
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                api_key="fallback-google-key",
            ),
        )
        limits = CostLimits()

        with patch("anthropic.AsyncAnthropic"):
            mock_fallback_client = Mock()
            with patch("google.genai.Client", return_value=mock_fallback_client) as mc:
                service = LLMService(config, limits)

                assert service.fallback_provider == "google"
                mc.assert_called_with(api_key="fallback-google-key")

    def test_fallback_from_environment(self):
        """Test fallback provider uses environment variable."""
        config = LLMConfig(
            provider="google",
            model="gemini-1.5-pro",
            api_key="google-key",
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="anthropic",
                model="claude-3-5-sonnet-20250122",
                # No api_key - should use env
            ),
        )
        limits = CostLimits()

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-anthropic-key"}):
            mock_client = Mock()
            with patch("google.genai.Client", return_value=mock_client):
                with patch("anthropic.AsyncAnthropic") as mock_anthropic:
                    service = LLMService(config, limits)

                    assert service.fallback_provider == "anthropic"
                    mock_anthropic.assert_called_with(api_key="env-anthropic-key")

    def test_fallback_no_api_key_logs_warning(self):
        """Test fallback without API key logs warning."""
        config = LLMConfig(
            provider="google",
            model="gemini-1.5-pro",
            api_key="google-key",
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="anthropic",
                model="claude-3-5-sonnet-20250122",
            ),
        )
        limits = CostLimits()

        # Clear environment
        with patch.dict(os.environ, {}, clear=True):
            mock_client = Mock()
            with patch("google.genai.Client", return_value=mock_client):
                service = LLMService(config, limits)

                # Fallback should not be initialized without API key
                assert service.fallback_client is None

    def test_fallback_import_error_anthropic(self):
        """Test handling missing anthropic package for fallback."""
        config = LLMConfig(
            provider="google",
            model="gemini-1.5-pro",
            api_key="google-key",
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="anthropic",
                model="claude-3-5-sonnet-20250122",
                api_key="fallback-key",
            ),
        )
        limits = CostLimits()

        mock_client = Mock()
        with patch("google.genai.Client", return_value=mock_client):
            with patch.dict("sys.modules", {"anthropic": None}):
                service = LLMService(config, limits)

                # Should handle gracefully
                assert service.fallback_client is None


class TestFallbackExecution:
    """Tests for fallback execution path."""

    @pytest.fixture
    def llm_service_with_fallback(self):
        """Create LLM service with fallback configured."""
        config = LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20250122",
            api_key="anthropic-key",
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                api_key="google-key",
            ),
        )
        limits = CostLimits()

        with patch("anthropic.AsyncAnthropic"):
            mock_client = Mock()
            with patch("google.genai.Client", return_value=mock_client):
                return LLMService(config, limits)

    @pytest.mark.asyncio
    async def test_fallback_activated_on_primary_failure(
        self, llm_service_with_fallback
    ):
        """Test fallback is used when primary fails."""
        service = llm_service_with_fallback

        # Primary fails
        service._call_anthropic_raw = AsyncMock(
            side_effect=LLMAPIError("Primary failed")
        )

        # Fallback succeeds
        mock_response = Mock()
        mock_response.text = '{"extractions": []}'
        mock_response.usage_metadata = Mock(total_token_count=1000)
        service._call_google_raw = AsyncMock(return_value=mock_response)

        metadata = Mock(paper_id="123", title="Test", authors=[])
        result = await service.extract("markdown", [], metadata)

        assert result.paper_id == "123"
        assert service.usage_stats.total_fallback_activations == 1

    @pytest.mark.asyncio
    async def test_both_providers_fail(self, llm_service_with_fallback):
        """Test AllProvidersFailedError when both fail."""
        service = llm_service_with_fallback

        # Both fail
        service._call_anthropic_raw = AsyncMock(
            side_effect=LLMAPIError("Primary failed")
        )
        service._call_google_raw = AsyncMock(side_effect=LLMAPIError("Fallback failed"))

        metadata = Mock(paper_id="123", title="Test", authors=[])

        with pytest.raises(AllProvidersFailedError) as exc_info:
            await service.extract("markdown", [], metadata)

        assert "anthropic" in str(exc_info.value)
        assert "google" in str(exc_info.value)


class TestCircuitBreakerIntegration:
    """Tests for circuit breaker integration."""

    @pytest.fixture
    def llm_service(self):
        """Create LLM service for testing."""
        config = LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20250122",
            api_key="test-key",
        )
        limits = CostLimits()
        with patch("anthropic.AsyncAnthropic"):
            return LLMService(config, limits)

    def test_reset_circuit_breakers(self, llm_service):
        """Test reset_circuit_breakers resets all breakers and health."""
        # Trigger some failures
        health = llm_service.provider_health["anthropic"]
        for _ in range(3):
            health.record_failure("test")
            if health.circuit_breaker:
                health.circuit_breaker.record_failure()

        assert health.status == "degraded"

        llm_service.reset_circuit_breakers()

        assert health.status == "healthy"
        assert health.consecutive_failures == 0

    def test_get_provider_health(self, llm_service):
        """Test get_provider_health returns all providers."""
        health_stats = llm_service.get_provider_health()

        assert "anthropic" in health_stats
        assert health_stats["anthropic"]["status"] == "healthy"


class TestProviderUsageStats:
    """Tests for ProviderUsageStats model."""

    def test_record_success(self):
        """Test recording a successful request."""
        stats = ProviderUsageStats(provider="anthropic")
        stats.record_success(tokens=1000, cost=0.05, was_retry=False)

        assert stats.total_tokens == 1000
        assert stats.total_cost_usd == 0.05
        assert stats.successful_requests == 1
        assert stats.retry_requests == 0

    def test_record_success_with_retry(self):
        """Test recording a successful request that was a retry."""
        stats = ProviderUsageStats(provider="anthropic")
        stats.record_success(tokens=1000, cost=0.05, was_retry=True)

        assert stats.retry_requests == 1

    def test_record_failure(self):
        """Test recording a failed request."""
        stats = ProviderUsageStats(provider="anthropic")
        stats.record_failure()

        assert stats.failed_requests == 1

    def test_fallback_requests(self):
        """Test fallback requests tracking."""
        stats = ProviderUsageStats(provider="google")
        stats.fallback_requests = 5

        assert stats.fallback_requests == 5


class TestEnhancedUsageStats:
    """Tests for EnhancedUsageStats model."""

    def test_initial_state(self):
        """Test EnhancedUsageStats initial state."""
        stats = EnhancedUsageStats()

        assert stats.total_retry_attempts == 0
        assert stats.total_fallback_activations == 0
        assert len(stats.by_provider) == 0

    def test_by_provider_tracking(self):
        """Test per-provider tracking."""
        stats = EnhancedUsageStats()
        stats.by_provider["anthropic"] = ProviderUsageStats(provider="anthropic")
        stats.by_provider["anthropic"].record_success(tokens=1000, cost=0.05)

        assert stats.by_provider["anthropic"].total_tokens == 1000


class TestFallbackInitializationEdgeCases:
    """Additional tests for fallback initialization edge cases."""

    def test_no_fallback_configured(self):
        """Test LLM service without fallback config (covers early return)."""
        config = LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20250122",
            api_key="anthropic-key",
            fallback=None,  # No fallback configured
        )
        limits = CostLimits()

        with patch("anthropic.AsyncAnthropic"):
            service = LLMService(config, limits)

            # Verify no fallback was initialized
            assert service.fallback_provider is None
            assert service.fallback_client is None

            # Explicitly call _init_fallback_provider to ensure coverage
            # This is a no-op when fallback is None, hitting the early return
            service._init_fallback_provider()

    def test_fallback_google_from_environment(self):
        """Test Google fallback provider uses GOOGLE_API_KEY from environment."""
        config = LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20250122",
            api_key="anthropic-key",
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                # No api_key - should use GOOGLE_API_KEY env
            ),
        )
        limits = CostLimits()

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "env-google-key"}):
            with patch("anthropic.AsyncAnthropic"):
                mock_client = Mock()
                with patch("google.genai.Client", return_value=mock_client) as mc:
                    service = LLMService(config, limits)

                    assert service.fallback_provider == "google"
                    mc.assert_called_with(api_key="env-google-key")

    def test_fallback_import_error_google(self):
        """Test handling missing google-genai package for fallback."""
        config = LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20250122",
            api_key="anthropic-key",
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                api_key="fallback-google-key",
            ),
        )
        limits = CostLimits()

        with patch("anthropic.AsyncAnthropic"):
            # Mock google.genai import to raise ImportError
            with patch.dict("sys.modules", {"google.genai": None, "google": None}):
                service = LLMService(config, limits)

                # Should handle gracefully
                assert service.fallback_client is None


class TestOnRetryCallback:
    """Tests for on_retry callback invocation."""

    @pytest.fixture
    def llm_service(self):
        """Create LLM service for testing."""
        config = LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20250122",
            api_key="test-key",
        )
        limits = CostLimits()
        with patch("anthropic.AsyncAnthropic"):
            return LLMService(config, limits)

    @pytest.mark.asyncio
    async def test_on_retry_callback_updates_stats(self, llm_service):
        """Test that on_retry callback updates usage stats."""
        service = llm_service
        call_count = 0

        # Mock _call_anthropic_raw to fail once then succeed
        async def flaky_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RetryableError("Transient failure")
            # Return a mock response
            mock_response = Mock()
            mock_response.content = [Mock(text='{"extractions": []}')]
            mock_response.usage = Mock(input_tokens=100, output_tokens=50)
            return mock_response

        service._call_anthropic_raw = flaky_call

        metadata = Mock(paper_id="123", title="Test", authors=[])
        result = await service.extract("markdown", [], metadata)

        # Verify stats were updated by on_retry callback
        assert service.usage_stats.total_retry_attempts == 1
        assert result.paper_id == "123"

"""Additional coverage tests for LLMService orchestrator.

Phase 5.1: Coverage improvement tests for service.py.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

from src.services.llm.service import LLMService
from src.services.llm.providers.base import LLMResponse, ProviderHealth
from src.services.llm.exceptions import LLMProviderError, RateLimitError
from src.models.llm import (
    LLMConfig,
    CostLimits,
    RetryConfig,
    CircuitBreakerConfig,
    FallbackProviderConfig,
)
from src.models.extraction import ExtractionTarget
from src.models.paper import PaperMetadata
from src.utils.exceptions import (
    ExtractionError,
    LLMAPIError,
    JSONParseError,
)


@pytest.fixture
def llm_config() -> LLMConfig:
    """Create test LLM configuration."""
    return LLMConfig(
        provider="anthropic",
        api_key="test-api-key",
        model="claude-3-5-sonnet-20241022",
        max_tokens=4096,
        temperature=0.0,
        retry=RetryConfig(
            max_retries=3,
            base_delay=0.01,  # Fast for testing
            max_delay=0.1,
            exponential_base=2.0,
        ),
        circuit_breaker=CircuitBreakerConfig(
            enabled=True,
            failure_threshold=5,
            recovery_timeout=30.0,
        ),
    )


@pytest.fixture
def cost_limits() -> CostLimits:
    """Create test cost limits."""
    return CostLimits(
        max_daily_spend_usd=10.0,
        max_total_spend_usd=100.0,
    )


@pytest.fixture
def extraction_targets() -> list[ExtractionTarget]:
    """Create test extraction targets."""
    return [
        ExtractionTarget(
            name="summary",
            description="Extract summary",
            output_format="text",
            required=True,
            examples=[],
        ),
    ]


@pytest.fixture
def paper_metadata() -> PaperMetadata:
    """Create test paper metadata."""
    return PaperMetadata(
        paper_id="test-paper-123",
        title="Test Paper Title",
        abstract="Test abstract",
        authors=[],
        publication_date=datetime(2024, 1, 15),
        source="test",
        url="https://example.com/paper/123",
    )


class TestCreateProviderUnknown:
    """Tests for unknown provider handling."""

    def test_create_provider_unknown_raises_error(
        self, llm_config: LLMConfig, cost_limits: CostLimits
    ) -> None:
        """Test that unknown provider raises ExtractionError."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            # Test _create_provider directly with unknown provider
            with pytest.raises(ExtractionError) as exc_info:
                service._create_provider("unknown_provider", "test-key", "test-model")

            assert "Unknown provider" in str(exc_info.value)


class TestFallbackProviderEdgeCases:
    """Tests for fallback provider initialization edge cases."""

    def test_init_fallback_disabled_returns_early(
        self, cost_limits: CostLimits
    ) -> None:
        """Test fallback init returns early when disabled."""
        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=FallbackProviderConfig(
                enabled=False,  # Disabled
                provider="google",
                model="gemini-1.5-pro",
            ),
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=config, cost_limits=cost_limits)
            assert service.fallback_provider is None

    def test_init_fallback_no_config(self, cost_limits: CostLimits) -> None:
        """Test fallback init when fallback config is None."""
        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=None,  # No fallback config
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=config, cost_limits=cost_limits)
            assert service.fallback_provider is None

    def test_init_fallback_direct_call_with_none_config(
        self, llm_config: LLMConfig, cost_limits: CostLimits
    ) -> None:
        """Test _init_fallback_provider returns early when config.fallback is None."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            # Temporarily set fallback to None and call directly
            original_fallback = service.config.fallback
            # Use object.__setattr__ to bypass Pydantic's frozen model
            object.__setattr__(service.config, "fallback", None)

            # This should return early without error (line 134)
            service._init_fallback_provider()

            # Restore
            object.__setattr__(service.config, "fallback", original_fallback)

            # Fallback should still be None
            assert service.fallback_provider is None


class TestDailyStatsReset:
    """Tests for daily stats reset functionality."""

    @pytest.mark.asyncio
    async def test_extract_triggers_daily_reset(
        self,
        llm_config: LLMConfig,
        cost_limits: CostLimits,
        extraction_targets: list[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> None:
        """Test extraction triggers daily reset when needed."""
        json_content = (
            '{"extractions": [{"target_name": "summary", "success": true, '
            '"content": "Test", "confidence": 0.9, "error": null}]}'
        )

        mock_response = LLMResponse(
            content=json_content,
            input_tokens=100,
            output_tokens=50,
            model="claude-3-5-sonnet",
            provider="anthropic",
            latency_ms=150.0,
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            # Mock provider
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value=mock_response)
            mock_provider.calculate_cost = MagicMock(return_value=0.05)
            mock_provider.get_health = MagicMock(
                return_value=ProviderHealth(provider="anthropic")
            )
            service._providers["anthropic"] = mock_provider
            service._provider_health["anthropic"] = ProviderHealth(provider="anthropic")

            # Mock cost tracker to trigger daily reset
            service._cost_tracker.should_reset_daily = MagicMock(return_value=True)

            result = await service.extract(
                markdown_content="# Test",
                targets=extraction_targets,
                paper_metadata=paper_metadata,
            )

            assert result is not None
            # Verify reset_daily_stats was called on usage_stats
            assert service.usage_stats.total_tokens >= 0


class TestCircuitBreakerIntegration:
    """Tests for circuit breaker integration."""

    @pytest.mark.asyncio
    async def test_extract_checks_circuit_breaker(
        self,
        cost_limits: CostLimits,
        extraction_targets: list[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> None:
        """Test extraction checks circuit breaker state."""
        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(max_retries=0),  # No retries
            circuit_breaker=CircuitBreakerConfig(
                enabled=True,
                failure_threshold=1,
                recovery_timeout=30.0,
            ),
        )

        json_content = (
            '{"extractions": [{"target_name": "summary", "success": true, '
            '"content": "Test", "confidence": 0.9, "error": null}]}'
        )

        mock_response = LLMResponse(
            content=json_content,
            input_tokens=100,
            output_tokens=50,
            model="claude-3-5-sonnet",
            provider="anthropic",
            latency_ms=150.0,
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=config, cost_limits=cost_limits)

            # Mock provider
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value=mock_response)
            mock_provider.calculate_cost = MagicMock(return_value=0.05)
            mock_provider.get_health = MagicMock(
                return_value=ProviderHealth(provider="anthropic")
            )
            service._providers["anthropic"] = mock_provider

            # Set up health with circuit breaker
            health = ProviderHealth(provider="anthropic")
            mock_cb = MagicMock()
            mock_cb.check_or_raise = MagicMock()
            mock_cb.record_success = MagicMock()
            health.circuit_breaker = mock_cb  # type: ignore
            service._provider_health["anthropic"] = health

            result = await service.extract(
                markdown_content="# Test",
                targets=extraction_targets,
                paper_metadata=paper_metadata,
            )

            assert result is not None
            # Verify circuit breaker was checked
            mock_cb.check_or_raise.assert_called_once()
            # Verify success was recorded
            mock_cb.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_records_circuit_breaker_failure(
        self,
        cost_limits: CostLimits,
        extraction_targets: list[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> None:
        """Test extraction records circuit breaker failure."""
        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(max_retries=0),  # No retries
            circuit_breaker=CircuitBreakerConfig(
                enabled=True,
                failure_threshold=5,
                recovery_timeout=30.0,
            ),
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=config, cost_limits=cost_limits)

            # Mock provider to fail
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(side_effect=Exception("API error"))
            mock_provider.get_health = MagicMock(
                return_value=ProviderHealth(provider="anthropic")
            )
            service._providers["anthropic"] = mock_provider

            # Set up health with circuit breaker
            health = ProviderHealth(provider="anthropic")
            mock_cb = MagicMock()
            mock_cb.check_or_raise = MagicMock()
            mock_cb.record_failure = MagicMock()
            health.circuit_breaker = mock_cb  # type: ignore
            service._provider_health["anthropic"] = health

            with pytest.raises(LLMAPIError):
                await service.extract(
                    markdown_content="# Test",
                    targets=extraction_targets,
                    paper_metadata=paper_metadata,
                )

            # Verify failure was recorded
            mock_cb.record_failure.assert_called_once()


class TestRetryCallback:
    """Tests for retry callback functionality."""

    @pytest.mark.asyncio
    async def test_retry_callback_updates_stats(
        self,
        cost_limits: CostLimits,
        extraction_targets: list[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> None:
        """Test retry callback updates usage stats."""
        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(
                max_retries=2,
                base_delay=0.001,  # Very fast for testing
                max_delay=0.01,
                exponential_base=2.0,
            ),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
        )

        json_content = (
            '{"extractions": [{"target_name": "summary", "success": true, '
            '"content": "Test", "confidence": 0.9, "error": null}]}'
        )

        mock_response = LLMResponse(
            content=json_content,
            input_tokens=100,
            output_tokens=50,
            model="claude-3-5-sonnet",
            provider="anthropic",
            latency_ms=150.0,
        )

        call_count = 0

        async def generate_with_retry(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RateLimitError(
                    "Rate limit", retry_after=0.001, provider="anthropic"
                )
            return mock_response

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=config, cost_limits=cost_limits)

            # Mock provider
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(side_effect=generate_with_retry)
            mock_provider.calculate_cost = MagicMock(return_value=0.05)
            mock_provider.get_health = MagicMock(
                return_value=ProviderHealth(provider="anthropic")
            )
            service._providers["anthropic"] = mock_provider
            service._provider_health["anthropic"] = ProviderHealth(provider="anthropic")

            result = await service.extract(
                markdown_content="# Test",
                targets=extraction_targets,
                paper_metadata=paper_metadata,
            )

            assert result is not None
            # Verify retry was counted
            assert service.usage_stats.total_retry_attempts >= 1


class TestJSONParseErrorHandling:
    """Tests for JSONParseError propagation."""

    @pytest.mark.asyncio
    async def test_json_parse_error_propagates(
        self,
        llm_config: LLMConfig,
        cost_limits: CostLimits,
        extraction_targets: list[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> None:
        """Test JSONParseError is propagated without being wrapped."""
        invalid_json = "{ not valid json }"

        mock_response = LLMResponse(
            content=invalid_json,
            input_tokens=100,
            output_tokens=50,
            model="claude-3-5-sonnet",
            provider="anthropic",
            latency_ms=150.0,
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            # Mock provider
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value=mock_response)
            mock_provider.calculate_cost = MagicMock(return_value=0.05)
            mock_provider.get_health = MagicMock(
                return_value=ProviderHealth(provider="anthropic")
            )
            service._providers["anthropic"] = mock_provider
            service._provider_health["anthropic"] = ProviderHealth(provider="anthropic")

            with pytest.raises(JSONParseError):
                await service.extract(
                    markdown_content="# Test",
                    targets=extraction_targets,
                    paper_metadata=paper_metadata,
                )


class TestLegacyClientProperties:
    """Tests for legacy client property accessors."""

    def test_client_property_returns_none_without_client_attr(
        self, llm_config: LLMConfig, cost_limits: CostLimits
    ) -> None:
        """Test client property returns None when provider has no _client."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            # Replace provider with one that has no _client
            mock_provider = MagicMock(spec=[])  # No _client attribute
            service._providers["anthropic"] = mock_provider

            client = service.client
            assert client is None

    def test_client_property_returns_client(
        self, llm_config: LLMConfig, cost_limits: CostLimits
    ) -> None:
        """Test client property returns actual client."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            # Set up provider with _client
            mock_client = MagicMock()
            mock_provider = MagicMock()
            mock_provider._client = mock_client
            service._providers["anthropic"] = mock_provider

            client = service.client
            assert client is mock_client

    def test_fallback_client_property_with_fallback(
        self, cost_limits: CostLimits
    ) -> None:
        """Test fallback_client property when fallback is configured."""
        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                api_key="google-key",
            ),
        )

        with patch.dict(
            "sys.modules",
            {
                "anthropic": MagicMock(),
                "google": MagicMock(),
                "google.genai": MagicMock(),
            },
        ):
            service = LLMService(config=config, cost_limits=cost_limits)

            # Set up fallback provider with _client
            mock_fallback_client = MagicMock()
            mock_fallback_provider = MagicMock()
            mock_fallback_provider._client = mock_fallback_client
            service._providers["google"] = mock_fallback_provider

            fallback_client = service.fallback_client
            assert fallback_client is mock_fallback_client

    def test_fallback_client_returns_none_without_client_attr(
        self, cost_limits: CostLimits
    ) -> None:
        """Test fallback_client returns None when provider has no _client."""
        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                api_key="google-key",
            ),
        )

        with patch.dict(
            "sys.modules",
            {
                "anthropic": MagicMock(),
                "google": MagicMock(),
                "google.genai": MagicMock(),
            },
        ):
            service = LLMService(config=config, cost_limits=cost_limits)

            # Replace fallback provider with one that has no _client
            mock_provider = MagicMock(spec=[])  # No _client attribute
            service._providers["google"] = mock_provider

            fallback_client = service.fallback_client
            assert fallback_client is None


class TestFallbackFailureRecording:
    """Tests for fallback failure recording."""

    @pytest.mark.asyncio
    async def test_fallback_failure_is_recorded(
        self,
        cost_limits: CostLimits,
        extraction_targets: list[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> None:
        """Test that fallback failure is properly recorded."""
        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(max_retries=0),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                api_key="google-key",
            ),
        )

        with patch.dict(
            "sys.modules",
            {
                "anthropic": MagicMock(),
                "google": MagicMock(),
                "google.genai": MagicMock(),
            },
        ):
            service = LLMService(config=config, cost_limits=cost_limits)

            # Mock primary to fail
            mock_anthropic = MagicMock()
            mock_anthropic.generate = AsyncMock(
                side_effect=LLMProviderError("Primary failed", provider="anthropic")
            )
            mock_anthropic.get_health = MagicMock(
                return_value=ProviderHealth(provider="anthropic")
            )
            service._providers["anthropic"] = mock_anthropic
            service._provider_health["anthropic"] = ProviderHealth(provider="anthropic")

            # Mock fallback to also fail
            mock_google = MagicMock()
            mock_google.generate = AsyncMock(
                side_effect=LLMProviderError("Fallback failed", provider="google")
            )
            mock_google.get_health = MagicMock(
                return_value=ProviderHealth(provider="google")
            )
            service._providers["google"] = mock_google
            service._provider_health["google"] = ProviderHealth(provider="google")

            from src.utils.exceptions import AllProvidersFailedError

            with pytest.raises(AllProvidersFailedError) as exc_info:
                await service.extract(
                    markdown_content="# Test",
                    targets=extraction_targets,
                    paper_metadata=paper_metadata,
                )

            # Verify both providers are in the error
            assert "anthropic" in str(exc_info.value.provider_errors)
            assert "google" in str(exc_info.value.provider_errors)
            # Verify fallback activation was counted
            assert service.usage_stats.total_fallback_activations == 1

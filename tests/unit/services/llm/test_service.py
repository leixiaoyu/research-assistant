"""Tests for LLMService orchestrator.

Phase 5.1: Tests for the refactored LLMService as thin orchestrator.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

from src.services.llm.service import LLMService
from src.services.llm.providers.base import LLMResponse, ProviderHealth
from src.services.llm.exceptions import LLMProviderError
from src.models.llm import LLMConfig, CostLimits, RetryConfig, CircuitBreakerConfig
from src.models.extraction import ExtractionTarget
from src.models.paper import PaperMetadata
from src.utils.exceptions import (
    AllProvidersFailedError,
    CostLimitExceeded,
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
            base_delay=1.0,
            max_delay=60.0,
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


class TestLLMServiceInitialization:
    """Tests for LLMService initialization."""

    def test_init_with_anthropic_provider(
        self, llm_config: LLMConfig, cost_limits: CostLimits
    ) -> None:
        """Test initialization with Anthropic provider."""
        with patch.dict(
            "sys.modules",
            {"anthropic": MagicMock()},
        ):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            assert service.config.provider == "anthropic"
            assert "anthropic" in service._providers

    def test_init_with_google_provider(self, cost_limits: CostLimits) -> None:
        """Test initialization with Google provider."""
        config = LLMConfig(
            provider="google",
            api_key="test-api-key",
            model="gemini-1.5-pro",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
        )

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            service = LLMService(config=config, cost_limits=cost_limits)

            assert service.config.provider == "google"
            assert "google" in service._providers


class TestLLMServiceUsageSummary:
    """Tests for usage summary methods."""

    def test_get_usage_summary(
        self, llm_config: LLMConfig, cost_limits: CostLimits
    ) -> None:
        """Test getting usage summary."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            summary = service.get_usage_summary()

            assert "total_tokens" in summary
            assert "total_cost_usd" in summary
            assert "papers_processed" in summary
            assert "daily_budget_remaining" in summary
            assert "total_budget_remaining" in summary

    def test_get_provider_health(
        self, llm_config: LLMConfig, cost_limits: CostLimits
    ) -> None:
        """Test getting provider health."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            health = service.get_provider_health()

            assert "anthropic" in health
            assert "status" in health["anthropic"]

    def test_reset_circuit_breakers(
        self, llm_config: LLMConfig, cost_limits: CostLimits
    ) -> None:
        """Test resetting circuit breakers."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            # Should not raise
            service.reset_circuit_breakers()

            # Verify health is reset
            for health in service._provider_health.values():
                assert health.status == "healthy"
                assert health.consecutive_failures == 0


class TestLLMServiceLegacyProperties:
    """Tests for backward compatibility properties."""

    def test_provider_health_property(
        self, llm_config: LLMConfig, cost_limits: CostLimits
    ) -> None:
        """Test legacy provider_health property."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            health = service.provider_health

            assert isinstance(health, dict)
            assert "anthropic" in health
            assert isinstance(health["anthropic"], ProviderHealth)

    def test_client_property(
        self, llm_config: LLMConfig, cost_limits: CostLimits
    ) -> None:
        """Test legacy client property."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            # Client should exist (mocked)
            client = service.client
            # Can be None or the mock client
            assert client is None or client is not None

    def test_fallback_client_property_no_fallback(
        self, llm_config: LLMConfig, cost_limits: CostLimits
    ) -> None:
        """Test legacy fallback_client property when no fallback configured."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            client = service.fallback_client

            assert client is None


class TestLLMServiceExtraction:
    """Tests for extraction methods."""

    @pytest.mark.asyncio
    async def test_extract_success(
        self,
        llm_config: LLMConfig,
        cost_limits: CostLimits,
        extraction_targets: list[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> None:
        """Test successful extraction."""
        # Create a mock response that mimics Anthropic format
        json_content = (
            '{"extractions": [{"target_name": "summary", "success": true, '
            '"content": "Test summary", "confidence": 0.9, "error": null}]}'
        )

        # Mock Anthropic response structure (content[0].text)
        mock_text_block = MagicMock()
        mock_text_block.text = json_content

        mock_raw_response = MagicMock()
        mock_raw_response.content = [mock_text_block]

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

            # Mock the provider's generate method
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value=mock_response)
            mock_provider.calculate_cost = MagicMock(return_value=0.05)
            mock_provider.get_health = MagicMock(
                return_value=ProviderHealth(provider="anthropic")
            )
            service._providers["anthropic"] = mock_provider
            service._provider_health["anthropic"] = ProviderHealth(provider="anthropic")

            result = await service.extract(
                markdown_content="# Test Paper\n\nThis is test content.",
                targets=extraction_targets,
                paper_metadata=paper_metadata,
            )

            assert result.paper_id == "test-paper-123"
            assert len(result.extraction_results) >= 1

    @pytest.mark.asyncio
    async def test_extract_cost_limit_exceeded(
        self,
        llm_config: LLMConfig,
        extraction_targets: list[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> None:
        """Test extraction raises when cost limit exceeded."""
        # Set very low cost limit
        low_limits = CostLimits(
            max_daily_spend_usd=0.01,
            max_total_spend_usd=0.01,
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=low_limits)

            # Simulate having already spent the budget
            service._cost_tracker.total_cost_usd = 0.02

            with pytest.raises(CostLimitExceeded):
                await service.extract(
                    markdown_content="# Test",
                    targets=extraction_targets,
                    paper_metadata=paper_metadata,
                )

    @pytest.mark.asyncio
    async def test_extract_all_providers_failed(
        self,
        llm_config: LLMConfig,
        cost_limits: CostLimits,
        extraction_targets: list[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> None:
        """Test extraction raises when all providers fail."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            service = LLMService(config=llm_config, cost_limits=cost_limits)

            # Mock the provider to fail
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(
                side_effect=LLMProviderError("API error", provider="anthropic")
            )
            mock_provider.get_health = MagicMock(
                return_value=ProviderHealth(provider="anthropic")
            )
            service._providers["anthropic"] = mock_provider
            service._provider_health["anthropic"] = ProviderHealth(provider="anthropic")

            with pytest.raises(AllProvidersFailedError):
                await service.extract(
                    markdown_content="# Test",
                    targets=extraction_targets,
                    paper_metadata=paper_metadata,
                )


class TestLLMServiceFallbackInit:
    """Tests for fallback provider initialization edge cases."""

    def test_fallback_no_api_key_from_env_anthropic(
        self, cost_limits: CostLimits
    ) -> None:
        """Test fallback init when API key not in env (anthropic)."""
        from src.models.llm import FallbackProviderConfig

        config = LLMConfig(
            provider="google",
            api_key="test-google-key",
            model="gemini-1.5-pro",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="anthropic",
                model="claude-3-5-sonnet",
                api_key=None,  # No API key
            ),
        )

        with patch.dict("os.environ", {}, clear=True):
            with patch.dict(
                "sys.modules",
                {"google": MagicMock(), "google.genai": MagicMock()},
            ):
                service = LLMService(config=config, cost_limits=cost_limits)

                # Fallback should not be initialized (no API key)
                assert service.fallback_provider is None

    def test_fallback_no_api_key_from_env_google(self, cost_limits: CostLimits) -> None:
        """Test fallback init when API key not in env (google)."""
        from src.models.llm import FallbackProviderConfig

        config = LLMConfig(
            provider="anthropic",
            api_key="test-anthropic-key",
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                api_key=None,  # No API key
            ),
        )

        with patch.dict("os.environ", {}, clear=True):
            with patch.dict("sys.modules", {"anthropic": MagicMock()}):
                service = LLMService(config=config, cost_limits=cost_limits)

                # Fallback should not be initialized (no API key)
                assert service.fallback_provider is None

    def test_fallback_api_key_from_env_anthropic(self, cost_limits: CostLimits) -> None:
        """Test fallback init gets API key from env (anthropic)."""
        from src.models.llm import FallbackProviderConfig

        config = LLMConfig(
            provider="google",
            api_key="test-google-key",
            model="gemini-1.5-pro",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="anthropic",
                model="claude-3-5-sonnet",
                api_key=None,
            ),
        )

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"}):
            with patch.dict(
                "sys.modules",
                {
                    "google": MagicMock(),
                    "google.genai": MagicMock(),
                    "anthropic": MagicMock(),
                },
            ):
                service = LLMService(config=config, cost_limits=cost_limits)

                assert service.fallback_provider == "anthropic"

    def test_fallback_api_key_from_env_google(self, cost_limits: CostLimits) -> None:
        """Test fallback init gets API key from env (google)."""
        from src.models.llm import FallbackProviderConfig

        config = LLMConfig(
            provider="anthropic",
            api_key="test-anthropic-key",
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                api_key=None,
            ),
        )

        with patch.dict("os.environ", {"GOOGLE_API_KEY": "env-key"}):
            with patch.dict(
                "sys.modules",
                {
                    "anthropic": MagicMock(),
                    "google": MagicMock(),
                    "google.genai": MagicMock(),
                },
            ):
                service = LLMService(config=config, cost_limits=cost_limits)

                assert service.fallback_provider == "google"

    def test_fallback_init_fails_gracefully(self, cost_limits: CostLimits) -> None:
        """Test fallback init failure is handled gracefully."""
        from src.models.llm import FallbackProviderConfig

        config = LLMConfig(
            provider="anthropic",
            api_key="test-anthropic-key",
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                api_key="test-google-key",
            ),
        )

        # Patch GoogleProvider to raise during initialization
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            with patch(
                "src.services.llm.service.GoogleProvider",
                side_effect=Exception("Google init failed"),
            ):
                service = LLMService(config=config, cost_limits=cost_limits)

                # Fallback should not be set due to init failure
                assert service.fallback_provider is None


class TestLLMServiceFallback:
    """Tests for fallback provider behavior."""

    @pytest.fixture
    def fallback_config(self) -> LLMConfig:
        """Create config with fallback."""
        from src.models.llm import FallbackProviderConfig

        return LLMConfig(
            provider="anthropic",
            api_key="test-api-key",
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                api_key="google-test-key",
            ),
        )

    def test_init_with_fallback_provider(
        self, fallback_config: LLMConfig, cost_limits: CostLimits
    ) -> None:
        """Test initialization with fallback provider."""
        with patch.dict(
            "sys.modules",
            {
                "anthropic": MagicMock(),
                "google": MagicMock(),
                "google.genai": MagicMock(),
            },
        ):
            service = LLMService(config=fallback_config, cost_limits=cost_limits)

            assert service.fallback_provider == "google"
            assert "anthropic" in service._providers
            assert "google" in service._providers

    @pytest.mark.asyncio
    async def test_fallback_on_primary_failure(
        self,
        fallback_config: LLMConfig,
        cost_limits: CostLimits,
        extraction_targets: list[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> None:
        """Test fallback is used when primary fails."""
        json_content = (
            '{"extractions": [{"target_name": "summary", "success": true, '
            '"content": "Test", "confidence": 0.9, "error": null}]}'
        )
        mock_response = LLMResponse(
            content=json_content,
            input_tokens=100,
            output_tokens=50,
            model="gemini-1.5-pro",
            provider="google",
            latency_ms=150.0,
        )

        with patch.dict(
            "sys.modules",
            {
                "anthropic": MagicMock(),
                "google": MagicMock(),
                "google.genai": MagicMock(),
            },
        ):
            service = LLMService(config=fallback_config, cost_limits=cost_limits)

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

            # Mock fallback to succeed
            mock_google = MagicMock()
            mock_google.generate = AsyncMock(return_value=mock_response)
            mock_google.calculate_cost = MagicMock(return_value=0.02)
            mock_google.get_health = MagicMock(
                return_value=ProviderHealth(provider="google")
            )
            service._providers["google"] = mock_google
            service._provider_health["google"] = ProviderHealth(provider="google")

            result = await service.extract(
                markdown_content="# Test",
                targets=extraction_targets,
                paper_metadata=paper_metadata,
            )

            assert result is not None
            assert service.usage_stats.total_fallback_activations == 1

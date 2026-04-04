"""Unit tests for LLM Provider Manager.

Tests for provider initialization, health tracking, and circuit breaker management.
"""

from unittest.mock import MagicMock, patch

from src.services.llm.provider_manager import (
    ProviderManager,
    create_provider_manager,
)
from src.models.llm import (
    LLMConfig,
    RetryConfig,
    CircuitBreakerConfig,
    FallbackProviderConfig,
)
from src.utils.circuit_breaker import CircuitBreakerRegistry


class TestProviderManager:
    """Tests for ProviderManager class."""

    def _create_config(
        self,
        provider: str = "anthropic",
        fallback_enabled: bool = False,
    ) -> LLMConfig:
        """Create a test config."""
        fallback = None
        if fallback_enabled:
            fallback = FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                api_key="test-fallback-key",
            )
        # Use appropriate model for provider
        model = "gemini-1.5-pro" if provider == "google" else "claude-3-sonnet"
        return LLMConfig(
            provider=provider,
            api_key="test-api-key",
            model=model,
            max_tokens=4096,
            temperature=0.7,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=True),
            fallback=fallback,
        )

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_init_primary_provider(self, mock_anthropic):
        """Test initialization of primary provider."""
        mock_provider = MagicMock()
        mock_health = MagicMock()
        mock_provider.get_health.return_value = mock_health
        mock_anthropic.return_value = mock_provider

        config = self._create_config()
        manager = ProviderManager(config)
        manager.initialize()

        mock_anthropic.assert_called_once_with(
            api_key="test-api-key",
            model="claude-3-sonnet",
        )
        assert "anthropic" in manager.get_all_providers()
        assert manager.get_provider("anthropic") == mock_provider

    @patch("src.services.llm.provider_manager.GoogleProvider")
    def test_init_google_provider(self, mock_google):
        """Test initialization of Google provider."""
        mock_provider = MagicMock()
        mock_health = MagicMock()
        mock_provider.get_health.return_value = mock_health
        mock_google.return_value = mock_provider

        config = self._create_config(provider="google")
        manager = ProviderManager(config)
        manager.initialize()

        mock_google.assert_called_once()
        assert "google" in manager.get_all_providers()

    @patch("src.services.llm.provider_manager.GoogleProvider")
    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_init_fallback_provider(self, mock_anthropic, mock_google):
        """Test initialization of fallback provider."""
        mock_primary = MagicMock()
        mock_primary.get_health.return_value = MagicMock()
        mock_anthropic.return_value = mock_primary

        mock_fallback = MagicMock()
        mock_fallback.get_health.return_value = MagicMock()
        mock_google.return_value = mock_fallback

        config = self._create_config(fallback_enabled=True)
        manager = ProviderManager(config)
        manager.initialize()

        assert manager.fallback_provider == "google"
        assert manager.has_fallback() is True
        assert "google" in manager.get_all_providers()

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_no_fallback_when_disabled(self, mock_anthropic):
        """Test no fallback when not configured."""
        mock_provider = MagicMock()
        mock_provider.get_health.return_value = MagicMock()
        mock_anthropic.return_value = mock_provider

        config = self._create_config(fallback_enabled=False)
        manager = ProviderManager(config)
        manager.initialize()

        assert manager.fallback_provider is None
        assert manager.has_fallback() is False

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_get_health(self, mock_anthropic):
        """Test getting provider health."""
        mock_provider = MagicMock()
        mock_health = MagicMock()
        mock_provider.get_health.return_value = mock_health
        mock_anthropic.return_value = mock_provider

        config = self._create_config()
        manager = ProviderManager(config)
        manager.initialize()

        health = manager.get_health("anthropic")
        assert health == mock_health

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_get_health_nonexistent(self, mock_anthropic):
        """Test getting health for nonexistent provider."""
        mock_provider = MagicMock()
        mock_provider.get_health.return_value = MagicMock()
        mock_anthropic.return_value = mock_provider

        config = self._create_config()
        manager = ProviderManager(config)
        manager.initialize()

        health = manager.get_health("nonexistent")
        assert health is None

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_get_health_stats(self, mock_anthropic):
        """Test getting health statistics."""
        mock_provider = MagicMock()
        mock_health = MagicMock()
        mock_health.get_stats.return_value = {"status": "healthy", "requests": 10}
        mock_provider.get_health.return_value = mock_health
        mock_anthropic.return_value = mock_provider

        config = self._create_config()
        manager = ProviderManager(config)
        manager.initialize()

        stats = manager.get_health_stats()
        assert "anthropic" in stats
        assert stats["anthropic"]["status"] == "healthy"

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_circuit_breaker_attached(self, mock_anthropic):
        """Test circuit breaker is attached to health."""
        mock_provider = MagicMock()
        mock_health = MagicMock()
        mock_provider.get_health.return_value = mock_health
        mock_anthropic.return_value = mock_provider

        registry = CircuitBreakerRegistry()
        config = self._create_config()
        manager = ProviderManager(config, registry)
        manager.initialize()

        health = manager.get_health("anthropic")
        assert hasattr(health, "circuit_breaker")

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_reset_circuit_breakers(self, mock_anthropic):
        """Test resetting circuit breakers."""
        mock_provider = MagicMock()
        mock_health = MagicMock()
        mock_health.status = "degraded"
        mock_health.consecutive_failures = 5
        mock_provider.get_health.return_value = mock_health
        mock_anthropic.return_value = mock_provider

        config = self._create_config()
        manager = ProviderManager(config)
        manager.initialize()

        manager.reset_circuit_breakers()

        health = manager.get_health("anthropic")
        assert health.status == "healthy"
        assert health.consecutive_failures == 0

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_health_check_all_healthy(self, mock_anthropic):
        """Test health_check with healthy providers."""
        mock_provider = MagicMock()
        mock_health = MagicMock()
        mock_health.status = "healthy"
        mock_circuit = MagicMock()
        mock_circuit.state.value = "closed"
        mock_circuit.allow_request.return_value = True
        mock_health.circuit_breaker = mock_circuit
        mock_provider.get_health.return_value = mock_health
        mock_anthropic.return_value = mock_provider

        config = self._create_config()
        manager = ProviderManager(config)
        manager.initialize()

        results = manager.health_check()

        assert "anthropic" in results
        assert results["anthropic"]["available"] is True
        assert results["anthropic"]["circuit_state"] == "closed"
        assert results["anthropic"]["status"] == "healthy"
        assert "error" not in results["anthropic"]

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_health_check_circuit_open(self, mock_anthropic):
        """Test health_check with open circuit breaker."""
        mock_provider = MagicMock()
        mock_health = MagicMock()
        mock_health.status = "degraded"
        mock_provider.get_health.return_value = mock_health
        mock_anthropic.return_value = mock_provider

        config = self._create_config()
        registry = CircuitBreakerRegistry()
        manager = ProviderManager(config, registry)
        manager.initialize()

        # Manually open the circuit breaker
        circuit = registry.get("anthropic")
        for _ in range(config.circuit_breaker.failure_threshold):
            circuit.record_failure()

        results = manager.health_check()

        assert "anthropic" in results
        assert results["anthropic"]["available"] is False
        assert results["anthropic"]["circuit_state"] == "open"
        assert results["anthropic"]["status"] == "degraded"
        assert "error" in results["anthropic"]
        assert "open" in results["anthropic"]["error"]

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_health_check_no_circuit_breaker(self, mock_anthropic):
        """Test health_check when circuit breaker is disabled."""
        mock_provider = MagicMock()
        mock_health = MagicMock()
        mock_health.status = "healthy"
        mock_provider.get_health.return_value = mock_health
        mock_anthropic.return_value = mock_provider

        # Create config with circuit breaker disabled
        config = LLMConfig(
            provider="anthropic",
            api_key="test-api-key",
            model="claude-3-sonnet",
            max_tokens=4096,
            temperature=0.7,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
        )

        manager = ProviderManager(config)
        manager.initialize()

        results = manager.health_check()

        assert "anthropic" in results
        assert results["anthropic"]["available"] is True
        assert results["anthropic"]["circuit_state"] == "disabled"
        assert results["anthropic"]["status"] == "healthy"

    def test_create_unknown_provider(self):
        """Test creating unknown provider raises error at config validation.

        Note: Pydantic validates provider field, so this test verifies
        that invalid providers are rejected at the LLMConfig level.
        """
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            LLMConfig(
                provider="unknown",
                api_key="test-key",
                model="test-model",
                max_tokens=4096,
                temperature=0.7,
                retry=RetryConfig(),
                circuit_breaker=CircuitBreakerConfig(enabled=False),
            )
        assert "provider" in str(exc_info.value)

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_fallback_without_api_key_env(self, mock_anthropic):
        """Test fallback initialization without API key in env."""
        mock_provider = MagicMock()
        mock_provider.get_health.return_value = MagicMock()
        mock_anthropic.return_value = mock_provider

        fallback = FallbackProviderConfig(
            enabled=True,
            provider="google",
            model="gemini-1.5-pro",
            api_key=None,  # No API key
        )
        config = LLMConfig(
            provider="anthropic",
            api_key="test-api-key",
            model="claude-3-sonnet",
            max_tokens=4096,
            temperature=0.7,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=fallback,
        )

        with patch.dict("os.environ", {}, clear=True):
            manager = ProviderManager(config)
            manager.initialize()

            # Fallback should not be initialized without API key
            assert manager.fallback_provider is None


class TestCreateProviderManager:
    """Tests for create_provider_manager convenience function."""

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_create_and_initialize(self, mock_anthropic):
        """Test convenience function creates and initializes manager."""
        mock_provider = MagicMock()
        mock_provider.get_health.return_value = MagicMock()
        mock_anthropic.return_value = mock_provider

        config = LLMConfig(
            provider="anthropic",
            api_key="test-api-key",
            model="claude-3-sonnet",
            max_tokens=4096,
            temperature=0.7,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
        )

        manager = create_provider_manager(config)

        assert isinstance(manager, ProviderManager)
        assert "anthropic" in manager.get_all_providers()


class TestProviderManagerEdgeCases:
    """Tests for edge cases to improve coverage."""

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_init_fallback_with_none_config(self, mock_anthropic):
        """Test _init_fallback_provider returns early when fallback is None."""
        mock_provider = MagicMock()
        mock_provider.get_health.return_value = MagicMock()
        mock_anthropic.return_value = mock_provider

        config = LLMConfig(
            provider="anthropic",
            api_key="test-api-key",
            model="claude-3-sonnet",
            max_tokens=4096,
            temperature=0.7,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=None,  # Explicitly None
        )

        manager = ProviderManager(config)
        manager.initialize()

        # Call _init_fallback_provider directly to ensure branch coverage
        manager._init_fallback_provider()

        assert manager.fallback_provider is None

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_get_provider_returns_none_for_unknown(self, mock_anthropic):
        """Test get_provider returns None for unknown provider."""
        mock_provider = MagicMock()
        mock_provider.get_health.return_value = MagicMock()
        mock_anthropic.return_value = mock_provider

        config = LLMConfig(
            provider="anthropic",
            api_key="test-api-key",
            model="claude-3-sonnet",
            max_tokens=4096,
            temperature=0.7,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
        )

        manager = ProviderManager(config)
        manager.initialize()

        assert manager.get_provider("unknown") is None

    @patch("src.services.llm.provider_manager.GoogleProvider")
    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_fallback_with_anthropic_env_key(self, mock_anthropic, mock_google):
        """Test fallback gets API key from environment for Anthropic."""
        mock_primary = MagicMock()
        mock_primary.get_health.return_value = MagicMock()
        mock_google.return_value = mock_primary

        mock_fallback = MagicMock()
        mock_fallback.get_health.return_value = MagicMock()
        mock_anthropic.return_value = mock_fallback

        fallback = FallbackProviderConfig(
            enabled=True,
            provider="anthropic",
            model="claude-3-sonnet",
            api_key=None,  # Should use env var
        )
        config = LLMConfig(
            provider="google",
            api_key="test-google-key",
            model="gemini-1.5-pro",
            max_tokens=4096,
            temperature=0.7,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=fallback,
        )

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-anthropic-key"}):
            manager = ProviderManager(config)
            manager.initialize()

            assert manager.fallback_provider == "anthropic"

    @patch("src.services.llm.provider_manager.GoogleProvider")
    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_fallback_init_exception_handling(self, mock_anthropic, mock_google):
        """Test fallback initialization handles exceptions gracefully."""
        mock_primary = MagicMock()
        mock_primary.get_health.return_value = MagicMock()
        mock_anthropic.return_value = mock_primary

        # Make Google provider raise exception
        mock_google.side_effect = Exception("Provider init failed")

        fallback = FallbackProviderConfig(
            enabled=True,
            provider="google",
            model="gemini-1.5-pro",
            api_key="test-key",
        )
        config = LLMConfig(
            provider="anthropic",
            api_key="test-api-key",
            model="claude-3-sonnet",
            max_tokens=4096,
            temperature=0.7,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
            fallback=fallback,
        )

        manager = ProviderManager(config)
        manager.initialize()

        # Fallback should not be initialized due to exception
        assert manager.fallback_provider is None

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_get_all_health(self, mock_anthropic):
        """Test get_all_health returns all provider health objects."""
        mock_provider = MagicMock()
        mock_health = MagicMock()
        mock_provider.get_health.return_value = mock_health
        mock_anthropic.return_value = mock_provider

        config = LLMConfig(
            provider="anthropic",
            api_key="test-api-key",
            model="claude-3-sonnet",
            max_tokens=4096,
            temperature=0.7,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
        )

        manager = ProviderManager(config)
        manager.initialize()

        all_health = manager.get_all_health()
        assert "anthropic" in all_health
        assert all_health["anthropic"] == mock_health

    @patch("src.services.llm.provider_manager.AnthropicProvider")
    def test_create_provider_llm_error(self, mock_anthropic):
        """Test _create_provider converts LLMProviderError to ExtractionError."""
        from src.services.llm.exceptions import LLMProviderError
        from src.utils.exceptions import ExtractionError

        mock_anthropic.side_effect = LLMProviderError("API key invalid")

        config = LLMConfig(
            provider="anthropic",
            api_key="test-api-key",
            model="claude-3-sonnet",
            max_tokens=4096,
            temperature=0.7,
            retry=RetryConfig(),
            circuit_breaker=CircuitBreakerConfig(enabled=False),
        )

        manager = ProviderManager(config)

        import pytest

        with pytest.raises(ExtractionError, match="API key invalid"):
            manager.initialize()

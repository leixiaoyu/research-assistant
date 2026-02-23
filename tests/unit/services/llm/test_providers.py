"""Tests for LLM provider implementations.

Phase 5.1: Tests for provider abstraction and implementations.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.services.llm.providers.base import LLMResponse, ProviderHealth
from src.services.llm.providers.anthropic import AnthropicProvider
from src.services.llm.providers.google import GoogleProvider


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_creation(self) -> None:
        """Test creating LLMResponse."""
        response = LLMResponse(
            content="Test content",
            input_tokens=100,
            output_tokens=50,
            model="test-model",
            provider="test-provider",
            latency_ms=150.5,
        )

        assert response.content == "Test content"
        assert response.input_tokens == 100
        assert response.output_tokens == 50
        assert response.model == "test-model"
        assert response.provider == "test-provider"
        assert response.latency_ms == 150.5

    def test_total_tokens(self) -> None:
        """Test total_tokens property."""
        response = LLMResponse(
            content="Test",
            input_tokens=100,
            output_tokens=50,
            model="test",
            provider="test",
            latency_ms=100.0,
        )

        assert response.total_tokens == 150

    def test_optional_fields(self) -> None:
        """Test optional fields default to None."""
        response = LLMResponse(
            content="Test",
            input_tokens=100,
            output_tokens=50,
            model="test",
            provider="test",
            latency_ms=100.0,
        )

        assert response.finish_reason is None
        assert response.timestamp is None


class TestProviderHealth:
    """Tests for ProviderHealth dataclass."""

    def test_initial_state(self) -> None:
        """Test initial health state."""
        health = ProviderHealth(provider="test")

        assert health.status == "healthy"
        assert health.consecutive_failures == 0
        assert health.consecutive_successes == 0
        assert health.total_requests == 0

    def test_record_success(self) -> None:
        """Test recording success."""
        health = ProviderHealth(provider="test")
        health.record_success()

        assert health.total_requests == 1
        assert health.consecutive_successes == 1
        assert health.last_success is not None

    def test_record_success_resets_failures(self) -> None:
        """Test success resets failure count."""
        health = ProviderHealth(provider="test")
        health.consecutive_failures = 3
        health.status = "degraded"

        health.record_success()

        assert health.consecutive_failures == 0
        assert health.status == "healthy"

    def test_record_failure(self) -> None:
        """Test recording failure."""
        health = ProviderHealth(provider="test")
        health.record_failure("Test error")

        assert health.total_failures == 1
        assert health.consecutive_failures == 1
        assert health.failure_reason == "Test error"
        assert health.last_failure is not None

    def test_degraded_after_three_failures(self) -> None:
        """Test status becomes degraded after 3 failures."""
        health = ProviderHealth(provider="test")

        for i in range(3):
            health.record_failure(f"Error {i}")

        assert health.status == "degraded"

    def test_unavailable_after_five_failures(self) -> None:
        """Test status becomes unavailable after 5 failures."""
        health = ProviderHealth(provider="test")

        for i in range(5):
            health.record_failure(f"Error {i}")

        assert health.status == "unavailable"

    def test_get_stats(self) -> None:
        """Test get_stats returns correct data."""
        health = ProviderHealth(provider="test")
        health.record_success()
        health.record_failure("Error")

        stats = health.get_stats()

        assert stats["provider"] == "test"
        assert stats["status"] == "healthy"
        assert stats["total_requests"] == 2
        assert stats["total_failures"] == 1
        assert stats["consecutive_failures"] == 1
        assert stats["consecutive_successes"] == 0


class TestAnthropicProvider:
    """Tests for AnthropicProvider."""

    @pytest.fixture
    def mock_anthropic(self) -> MagicMock:
        """Create mock for Anthropic client."""
        with patch.dict(
            "sys.modules",
            {"anthropic": MagicMock()},
        ):
            yield

    def test_name_property(self, mock_anthropic: MagicMock) -> None:
        """Test provider name."""
        provider = AnthropicProvider(api_key="test-key")
        assert provider.name == "anthropic"

    def test_model_property(self, mock_anthropic: MagicMock) -> None:
        """Test model property."""
        provider = AnthropicProvider(api_key="test-key", model="claude-3-opus")
        assert provider.model == "claude-3-opus"

    def test_default_model(self, mock_anthropic: MagicMock) -> None:
        """Test default model."""
        provider = AnthropicProvider(api_key="test-key")
        assert "claude-3-5-sonnet" in provider.model

    def test_calculate_cost(self, mock_anthropic: MagicMock) -> None:
        """Test cost calculation."""
        provider = AnthropicProvider(api_key="test-key")

        # Claude pricing: $3/MTok input, $15/MTok output
        cost = provider.calculate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

        # Expected: $3 + $15 = $18
        assert cost == 18.0

    def test_calculate_cost_small_usage(self, mock_anthropic: MagicMock) -> None:
        """Test cost calculation for small usage."""
        provider = AnthropicProvider(api_key="test-key")

        cost = provider.calculate_cost(
            input_tokens=1000,
            output_tokens=500,
        )

        # Input: 1000/1M * $3 = $0.003
        # Output: 500/1M * $15 = $0.0075
        # Total: $0.0105
        expected = (1000 / 1_000_000) * 3.0 + (500 / 1_000_000) * 15.0
        assert abs(cost - expected) < 1e-10

    def test_get_health(self, mock_anthropic: MagicMock) -> None:
        """Test get_health returns ProviderHealth."""
        provider = AnthropicProvider(api_key="test-key")
        health = provider.get_health()

        assert isinstance(health, ProviderHealth)
        assert health.provider == "anthropic"


class TestGoogleProvider:
    """Tests for GoogleProvider."""

    @pytest.fixture
    def mock_google(self) -> MagicMock:
        """Create mock for Google client."""
        mock_genai = MagicMock()
        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": mock_genai},
        ):
            yield

    def test_name_property(self, mock_google: MagicMock) -> None:
        """Test provider name."""
        provider = GoogleProvider(api_key="test-key")
        assert provider.name == "google"

    def test_model_property(self, mock_google: MagicMock) -> None:
        """Test model property."""
        provider = GoogleProvider(api_key="test-key", model="gemini-2.0-pro")
        assert provider.model == "gemini-2.0-pro"

    def test_default_model(self, mock_google: MagicMock) -> None:
        """Test default model."""
        provider = GoogleProvider(api_key="test-key")
        assert "gemini" in provider.model.lower()

    def test_calculate_cost(self, mock_google: MagicMock) -> None:
        """Test cost calculation."""
        provider = GoogleProvider(api_key="test-key")

        # Gemini pricing: $1.25/MTok input, $5/MTok output
        cost = provider.calculate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

        # Expected: $1.25 + $5 = $6.25
        assert cost == 6.25

    def test_calculate_cost_small_usage(self, mock_google: MagicMock) -> None:
        """Test cost calculation for small usage."""
        provider = GoogleProvider(api_key="test-key")

        cost = provider.calculate_cost(
            input_tokens=1000,
            output_tokens=500,
        )

        # Input: 1000/1M * $1.25 = $0.00125
        # Output: 500/1M * $5 = $0.0025
        # Total: $0.00375
        expected = (1000 / 1_000_000) * 1.25 + (500 / 1_000_000) * 5.0
        assert abs(cost - expected) < 1e-10

    def test_get_health(self, mock_google: MagicMock) -> None:
        """Test get_health returns ProviderHealth."""
        provider = GoogleProvider(api_key="test-key")
        health = provider.get_health()

        assert isinstance(health, ProviderHealth)
        assert health.provider == "google"


class TestCostCalculationEquivalence:
    """Behavioral equivalence tests for cost calculations.

    These tests verify that the provider cost calculations match
    the original LLMService calculations exactly.
    """

    # Original pricing constants from LLMService
    ORIGINAL_CLAUDE_INPUT = 3.00
    ORIGINAL_CLAUDE_OUTPUT = 15.00
    ORIGINAL_GEMINI_INPUT = 1.25
    ORIGINAL_GEMINI_OUTPUT = 5.00

    @pytest.fixture
    def mock_providers(self) -> None:
        """Mock both provider dependencies."""
        with patch.dict(
            "sys.modules",
            {
                "anthropic": MagicMock(),
                "google": MagicMock(),
                "google.genai": MagicMock(),
            },
        ):
            yield

    def test_anthropic_cost_matches_original_formula(
        self, mock_providers: None
    ) -> None:
        """Test Anthropic cost matches original calculation."""
        provider = AnthropicProvider(api_key="test-key")

        # Test with random-ish values
        test_cases = [
            (1000, 500),
            (50000, 25000),
            (100000, 50000),
            (1, 1),
            (1000000, 500000),
        ]

        for input_tokens, output_tokens in test_cases:
            new_cost = provider.calculate_cost(input_tokens, output_tokens)

            # Original formula
            original_cost = (input_tokens / 1_000_000) * self.ORIGINAL_CLAUDE_INPUT + (
                output_tokens / 1_000_000
            ) * self.ORIGINAL_CLAUDE_OUTPUT

            # Must match to 10 decimal places
            assert abs(new_cost - original_cost) < 1e-10, (
                f"Mismatch for ({input_tokens}, {output_tokens}): "
                f"new={new_cost}, original={original_cost}"
            )

    def test_google_cost_matches_original_formula(self, mock_providers: None) -> None:
        """Test Google cost matches original calculation."""
        provider = GoogleProvider(api_key="test-key")

        test_cases = [
            (1000, 500),
            (50000, 25000),
            (100000, 50000),
            (1, 1),
            (1000000, 500000),
        ]

        for input_tokens, output_tokens in test_cases:
            new_cost = provider.calculate_cost(input_tokens, output_tokens)

            # Original formula
            original_cost = (input_tokens / 1_000_000) * self.ORIGINAL_GEMINI_INPUT + (
                output_tokens / 1_000_000
            ) * self.ORIGINAL_GEMINI_OUTPUT

            # Must match to 10 decimal places
            assert abs(new_cost - original_cost) < 1e-10, (
                f"Mismatch for ({input_tokens}, {output_tokens}): "
                f"new={new_cost}, original={original_cost}"
            )

    def test_random_cost_calculations(self, mock_providers: None) -> None:
        """Test with 1000 random token values (as per spec)."""
        import random

        random.seed(42)  # Reproducible

        anthropic = AnthropicProvider(api_key="test-key")
        google = GoogleProvider(api_key="test-key")

        for _ in range(1000):
            input_tokens = random.randint(1, 100000)
            output_tokens = random.randint(1, 50000)

            # Anthropic
            new_anthropic = anthropic.calculate_cost(input_tokens, output_tokens)
            original_anthropic = (
                input_tokens / 1_000_000
            ) * self.ORIGINAL_CLAUDE_INPUT + (
                output_tokens / 1_000_000
            ) * self.ORIGINAL_CLAUDE_OUTPUT
            assert abs(new_anthropic - original_anthropic) < 1e-10

            # Google
            new_google = google.calculate_cost(input_tokens, output_tokens)
            original_google = (
                input_tokens / 1_000_000
            ) * self.ORIGINAL_GEMINI_INPUT + (
                output_tokens / 1_000_000
            ) * self.ORIGINAL_GEMINI_OUTPUT
            assert abs(new_google - original_google) < 1e-10

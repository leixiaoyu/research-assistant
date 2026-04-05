"""Unit tests for Google (Gemini) Provider

Tests for Issue #82: Handle None token counts from Gemini 2.5 Flash

The Google Gemini 2.5 Flash provider can return None for token counts
in usage_metadata. This test suite verifies that None values are properly
handled and converted to 0.

Coverage:
- None candidates_token_count (output tokens)
- None prompt_token_count (input tokens)
- None total_token_count (fallback case)
- LLMResponse.total_tokens calculation with zero tokens
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.llm.providers.google import GoogleProvider
from src.services.llm.providers.base import LLMResponse
from src.services.llm.exceptions import (
    RateLimitError,
    AuthenticationError,
    ContentFilterError,
    ProviderUnavailableError,
    ContextLengthExceededError,
    LLMProviderError,
)


@pytest.fixture
def google_provider():
    """Create GoogleProvider instance with mocked genai."""
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        provider = GoogleProvider(api_key="test-api-key", model="gemini-2.5-flash")
        provider._mock_client = mock_client  # Store for test access
        yield provider


def _create_mock_response(
    text="Test response",
    prompt_tokens=100,
    candidates_tokens=50,
    total_tokens=150,
    finish_reason="STOP",
):
    """Helper to create mock Gemini API response."""
    mock_response = MagicMock()
    mock_response.text = text
    mock_response.usage_metadata = MagicMock()
    mock_response.usage_metadata.prompt_token_count = prompt_tokens
    mock_response.usage_metadata.candidates_token_count = candidates_tokens
    mock_response.usage_metadata.total_token_count = total_tokens
    mock_response.candidates = [MagicMock(finish_reason=finish_reason)]
    return mock_response


class TestNoneTokenCounts:
    """Test handling of None token counts from Gemini 2.5 Flash.

    Issue #82: Gemini 2.5 Flash can return None for candidates_token_count,
    prompt_token_count, and total_token_count. These must be converted to 0
    to prevent TypeError in LLMResponse.total_tokens.
    """

    @pytest.mark.asyncio
    async def test_none_candidates_token_count(self, google_provider):
        """Test that None candidates_token_count is converted to 0.

        This is the primary issue from #82: Gemini 2.5 Flash returns
        candidates_token_count = None (not missing, explicitly None).
        """
        mock_response = _create_mock_response(
            prompt_tokens=100, candidates_tokens=None, total_tokens=100  # The bug!
        )

        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        with patch("google.genai.types"):
            result = await google_provider.generate("test prompt")

        assert isinstance(result, LLMResponse)
        assert result.output_tokens == 0  # None converted to 0
        assert result.input_tokens == 100
        assert result.total_tokens == 100  # Must not raise TypeError
        assert result.content == "Test response"

    @pytest.mark.asyncio
    async def test_none_prompt_token_count(self, google_provider):
        """Test that None prompt_token_count is converted to 0."""
        mock_response = _create_mock_response(
            prompt_tokens=None, candidates_tokens=50, total_tokens=50  # Test this
        )

        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        with patch("google.genai.types"):
            result = await google_provider.generate("test prompt")

        assert result.input_tokens == 0  # None converted to 0
        assert result.output_tokens == 50
        assert result.total_tokens == 50  # Must not raise TypeError

    @pytest.mark.asyncio
    async def test_none_total_token_count_fallback(self, google_provider):
        """Test that None total_token_count in fallback path is handled."""
        mock_response = _create_mock_response(
            prompt_tokens=None,
            candidates_tokens=None,
            total_tokens=None,  # Fallback is None too
        )

        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        with patch("google.genai.types"):
            result = await google_provider.generate("test prompt")

        # All should default to 0
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.total_tokens == 0  # Must not raise TypeError

    @pytest.mark.asyncio
    async def test_all_none_token_counts(self, google_provider):
        """Test that all None token counts are handled gracefully."""
        mock_response = _create_mock_response(
            prompt_tokens=None, candidates_tokens=None, total_tokens=None
        )

        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        with patch("google.genai.types"):
            result = await google_provider.generate("test prompt")

        # All should be 0 and total_tokens should not crash
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.total_tokens == 0
        assert isinstance(result.total_tokens, int)

    @pytest.mark.asyncio
    async def test_missing_usage_metadata(self, google_provider):
        """Test that missing usage_metadata is handled (no usage field at all)."""
        mock_response = MagicMock()
        mock_response.text = "Test response"
        # Don't set usage_metadata attribute at all
        mock_response.usage_metadata = None
        mock_response.candidates = [MagicMock(finish_reason="STOP")]

        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        with patch("google.genai.types"):
            result = await google_provider.generate("test prompt")

        # Should default to 0 when usage_metadata is missing
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.total_tokens == 0


class TestLLMResponseTotalTokens:
    """Test LLMResponse.total_tokens calculation.

    Ensures the property works correctly with zero tokens,
    which is what we get when None values are converted to 0.
    """

    def test_total_tokens_with_zero_output(self):
        """Test total_tokens when output_tokens is 0."""
        response = LLMResponse(
            content="test",
            input_tokens=100,
            output_tokens=0,  # This is what we get from None conversion
            model="gemini-2.5-flash",
            provider="google",
            latency_ms=100.0,
        )

        assert response.total_tokens == 100
        assert isinstance(response.total_tokens, int)

    def test_total_tokens_with_zero_input(self):
        """Test total_tokens when input_tokens is 0."""
        response = LLMResponse(
            content="test",
            input_tokens=0,  # This is what we get from None conversion
            output_tokens=50,
            model="gemini-2.5-flash",
            provider="google",
            latency_ms=100.0,
        )

        assert response.total_tokens == 50
        assert isinstance(response.total_tokens, int)

    def test_total_tokens_with_both_zero(self):
        """Test total_tokens when both input and output are 0."""
        response = LLMResponse(
            content="test",
            input_tokens=0,
            output_tokens=0,
            model="gemini-2.5-flash",
            provider="google",
            latency_ms=100.0,
        )

        assert response.total_tokens == 0
        assert isinstance(response.total_tokens, int)

    def test_total_tokens_normal_values(self):
        """Test total_tokens with normal non-zero values."""
        response = LLMResponse(
            content="test",
            input_tokens=100,
            output_tokens=50,
            model="gemini-2.5-flash",
            provider="google",
            latency_ms=100.0,
        )

        assert response.total_tokens == 150
        assert isinstance(response.total_tokens, int)


class TestGoogleProviderBasics:
    """Test basic GoogleProvider functionality."""

    def test_provider_initialization(self):
        """Test GoogleProvider initializes correctly."""
        with patch("google.genai.Client") as mock_client_cls:
            mock_client_cls.return_value = MagicMock()

            provider = GoogleProvider(api_key="test-key", model="gemini-1.5-pro")

            assert provider.name == "google"
            assert provider.model == "gemini-1.5-pro"
            mock_client_cls.assert_called_once_with(api_key="test-key")

    def test_provider_default_model(self):
        """Test GoogleProvider uses default model."""
        with patch("google.genai.Client") as mock_client_cls:
            mock_client_cls.return_value = MagicMock()

            provider = GoogleProvider(api_key="test-key")

            assert provider.model == "gemini-1.5-pro"

    @pytest.mark.asyncio
    async def test_successful_generation(self, google_provider):
        """Test successful text generation."""
        mock_response = _create_mock_response(
            text="Generated text",
            prompt_tokens=100,
            candidates_tokens=50,
            total_tokens=150,
        )

        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        with patch("google.genai.types"):
            result = await google_provider.generate("test prompt")

        assert result.content == "Generated text"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.total_tokens == 150
        assert result.model == "gemini-2.5-flash"
        assert result.provider == "google"
        assert result.finish_reason == "STOP"
        assert result.latency_ms > 0

    def test_calculate_cost(self, google_provider):
        """Test cost calculation."""
        cost = google_provider.calculate_cost(
            input_tokens=1_000_000, output_tokens=1_000_000
        )

        # $1.25 per MTok input + $5 per MTok output = $6.25
        assert cost == pytest.approx(6.25, rel=0.01)

    def test_get_health(self, google_provider):
        """Test health status retrieval."""
        health = google_provider.get_health()

        assert health.provider == "google"
        assert health.status == "healthy"


class TestGoogleProviderErrorHandling:
    """Test error classification and handling."""

    @pytest.mark.asyncio
    async def test_authentication_error(self, google_provider):
        """Test authentication error classification."""
        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("401 authentication failed")
        )

        with patch("google.genai.types"):
            with pytest.raises(AuthenticationError) as exc_info:
                await google_provider.generate("test")

        assert exc_info.value.provider == "google"

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, google_provider):
        """Test rate limit error classification."""
        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("429 rate limit exceeded")
        )

        with patch("google.genai.types"):
            with pytest.raises(RateLimitError) as exc_info:
                await google_provider.generate("test")

        assert exc_info.value.provider == "google"

    @pytest.mark.asyncio
    async def test_content_filter_error(self, google_provider):
        """Test content filter error classification."""
        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("content blocked by safety filters")
        )

        with patch("google.genai.types"):
            with pytest.raises(ContentFilterError) as exc_info:
                await google_provider.generate("test")

        assert exc_info.value.provider == "google"

    @pytest.mark.asyncio
    async def test_context_length_error(self, google_provider):
        """Test context length exceeded error classification."""
        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("token limit exceeded")
        )

        with patch("google.genai.types"):
            with pytest.raises(ContextLengthExceededError) as exc_info:
                await google_provider.generate("test")

        assert exc_info.value.provider == "google"

    @pytest.mark.asyncio
    async def test_provider_unavailable_error(self, google_provider):
        """Test provider unavailable error classification."""
        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("503 service unavailable")
        )

        with patch("google.genai.types"):
            with pytest.raises(ProviderUnavailableError) as exc_info:
                await google_provider.generate("test")

        assert exc_info.value.provider == "google"

    @pytest.mark.asyncio
    async def test_generic_error(self, google_provider):
        """Test generic error classification."""
        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("unknown error")
        )

        with patch("google.genai.types"):
            with pytest.raises(LLMProviderError) as exc_info:
                await google_provider.generate("test")

        assert exc_info.value.provider == "google"


class TestFallbackTokenCounting:
    """Test fallback token counting when individual counts are 0.

    When both prompt_token_count and candidates_token_count are 0,
    the provider falls back to total_token_count and estimates the split.
    """

    @pytest.mark.asyncio
    async def test_fallback_to_total_count(self, google_provider):
        """Test fallback when individual counts are 0 but total exists."""
        mock_response = _create_mock_response(
            prompt_tokens=0, candidates_tokens=0, total_tokens=100
        )

        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        with patch("google.genai.types"):
            result = await google_provider.generate("test prompt")

        # Verify fallback estimation (70% input, 30% output)
        assert result.input_tokens == 70  # 100 * 0.7
        assert result.output_tokens == 30  # 100 - 70
        assert result.total_tokens == 100

    @pytest.mark.asyncio
    async def test_no_fallback_when_counts_present(self, google_provider):
        """Test that fallback is NOT used when individual counts are present."""
        mock_response = _create_mock_response(
            prompt_tokens=80, candidates_tokens=20, total_tokens=100
        )

        google_provider._mock_client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        with patch("google.genai.types"):
            result = await google_provider.generate("test prompt")

        # Verify individual counts are used, not fallback
        assert result.input_tokens == 80
        assert result.output_tokens == 20
        assert result.total_tokens == 100

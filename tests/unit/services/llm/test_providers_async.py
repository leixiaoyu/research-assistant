"""Tests for LLM provider async generate methods.

Phase 5.1: Tests for provider async API calls.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.services.llm.providers.base import LLMResponse, ProviderHealth
from src.services.llm.exceptions import (
    LLMProviderError,
    RateLimitError,
    AuthenticationError,
    ContentFilterError,
    ProviderUnavailableError,
    ContextLengthExceededError,
)


class TestAnthropicProviderGenerate:
    """Tests for AnthropicProvider.generate() method."""

    @pytest.mark.asyncio
    async def test_generate_success(self) -> None:
        """Test successful generation."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        # Mock the response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Generated response")]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_response.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")
            provider._client = mock_client

            result = await provider.generate(
                prompt="Test prompt",
                max_tokens=1024,
                temperature=0.0,
            )

            assert isinstance(result, LLMResponse)
            assert result.content == "Generated response"
            assert result.input_tokens == 100
            assert result.output_tokens == 50
            assert result.provider == "anthropic"

    @pytest.mark.asyncio
    async def test_generate_rate_limit_error(self) -> None:
        """Test rate limit error handling."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=Exception("429 rate limit exceeded")
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")
            provider._client = mock_client

            with pytest.raises(RateLimitError):
                await provider.generate(prompt="Test", max_tokens=100)

    @pytest.mark.asyncio
    async def test_generate_auth_error(self) -> None:
        """Test authentication error handling."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=Exception("401 authentication failed")
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")
            provider._client = mock_client

            with pytest.raises(AuthenticationError):
                await provider.generate(prompt="Test", max_tokens=100)

    @pytest.mark.asyncio
    async def test_generate_content_filter_error(self) -> None:
        """Test content filter error handling."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=Exception("content blocked by filter policy")
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")
            provider._client = mock_client

            with pytest.raises(ContentFilterError):
                await provider.generate(prompt="Test", max_tokens=100)

    @pytest.mark.asyncio
    async def test_generate_context_length_error(self) -> None:
        """Test context length error handling."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=Exception("context length exceeded")
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")
            provider._client = mock_client

            with pytest.raises(ContextLengthExceededError):
                await provider.generate(prompt="Test", max_tokens=100)

    @pytest.mark.asyncio
    async def test_generate_unavailable_error(self) -> None:
        """Test provider unavailable error handling."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=Exception("503 service unavailable")
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")
            provider._client = mock_client

            with pytest.raises(ProviderUnavailableError):
                await provider.generate(prompt="Test", max_tokens=100)

    @pytest.mark.asyncio
    async def test_generate_generic_error(self) -> None:
        """Test generic error handling."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=Exception("Some unknown error")
        )

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")
            provider._client = mock_client

            with pytest.raises(LLMProviderError):
                await provider.generate(prompt="Test", max_tokens=100)

    @pytest.mark.asyncio
    async def test_generate_empty_content(self) -> None:
        """Test handling empty content response."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        mock_response = MagicMock()
        mock_response.content = []
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=0)
        mock_response.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")
            provider._client = mock_client

            result = await provider.generate(prompt="Test", max_tokens=100)

            assert result.content == ""

    def test_extract_retry_after_from_error(self) -> None:
        """Test extracting retry_after from error."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")

            # Error with retry_after attribute
            error_with_retry = MagicMock()
            error_with_retry.retry_after = 30.0

            result = provider._extract_retry_after(error_with_retry)
            assert result == 30.0

    def test_extract_retry_after_from_headers(self) -> None:
        """Test extracting retry_after from response headers."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")

            # Error with response headers
            error_with_headers = MagicMock()
            error_with_headers.retry_after = None
            error_with_headers.response = MagicMock()
            error_with_headers.response.headers = {"Retry-After": "45"}

            result = provider._extract_retry_after(error_with_headers)
            assert result == 45.0

    def test_extract_retry_after_none(self) -> None:
        """Test retry_after is None when not available."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")

            error = Exception("No retry info")
            result = provider._extract_retry_after(error)
            assert result is None


class TestGoogleProviderGenerate:
    """Tests for GoogleProvider.generate() method."""

    @pytest.mark.asyncio
    async def test_generate_success(self) -> None:
        """Test successful generation."""
        from src.services.llm.providers.google import GoogleProvider

        mock_response = MagicMock()
        mock_response.text = "Generated response"
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=100,
            candidates_token_count=50,
            total_token_count=150,
        )
        mock_response.candidates = [MagicMock(finish_reason="STOP")]

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")
            provider._client = mock_client

            # Call generate directly with mocked client
            result = await provider.generate(
                prompt="Test prompt",
                max_tokens=1024,
                temperature=0.0,
            )

            assert isinstance(result, LLMResponse)
            assert result.content == "Generated response"
            assert result.input_tokens == 100
            assert result.output_tokens == 50
            assert result.provider == "google"

    @pytest.mark.asyncio
    async def test_generate_with_fallback_token_counts(self) -> None:
        """Test generate with fallback to total token count."""
        from src.services.llm.providers.google import GoogleProvider

        mock_response = MagicMock()
        mock_response.text = "Response"
        # Only total_token_count provided, individual counts are 0
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=0,
            candidates_token_count=0,
            total_token_count=100,
        )
        mock_response.candidates = []

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")
            provider._client = mock_client

            result = await provider.generate(prompt="Test", max_tokens=100)

            # Should use fallback: 70/30 split
            assert result.input_tokens == 70
            assert result.output_tokens == 30

    @pytest.mark.asyncio
    async def test_generate_no_usage_metadata(self) -> None:
        """Test generate when no usage metadata available."""
        from src.services.llm.providers.google import GoogleProvider

        mock_response = MagicMock()
        mock_response.text = "Response"
        mock_response.usage_metadata = None
        mock_response.candidates = []

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")
            provider._client = mock_client

            result = await provider.generate(prompt="Test", max_tokens=100)

            assert result.input_tokens == 0
            assert result.output_tokens == 0

    @pytest.mark.asyncio
    async def test_generate_no_text_attribute(self) -> None:
        """Test generate when response has no text attribute."""
        from src.services.llm.providers.google import GoogleProvider

        mock_response = MagicMock(spec=[])  # No attributes
        mock_response.usage_metadata = None
        mock_response.candidates = []

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")
            provider._client = mock_client

            result = await provider.generate(prompt="Test", max_tokens=100)

            assert result.content == ""

    @pytest.mark.asyncio
    async def test_generate_error_updates_health(self) -> None:
        """Test generate updates health on error."""
        from src.services.llm.providers.google import GoogleProvider

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("API error")
        )

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")
            provider._client = mock_client

            with pytest.raises(LLMProviderError):
                await provider.generate(prompt="Test", max_tokens=100)

            health = provider.get_health()
            assert health.total_failures == 1
            assert health.consecutive_failures == 1

    def test_classify_rate_limit_error(self) -> None:
        """Test rate limit error classification."""
        from src.services.llm.providers.google import GoogleProvider

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")

            error = Exception("429 quota exceeded")
            result = provider._classify_error(error)
            assert isinstance(result, RateLimitError)

    def test_classify_auth_error(self) -> None:
        """Test authentication error classification."""
        from src.services.llm.providers.google import GoogleProvider

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")

            error = Exception("401 api_key invalid authentication")
            result = provider._classify_error(error)
            assert isinstance(result, AuthenticationError)

    def test_classify_safety_error(self) -> None:
        """Test safety filter error classification."""
        from src.services.llm.providers.google import GoogleProvider

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")

            error = Exception("safety blocked content")
            result = provider._classify_error(error)
            assert isinstance(result, ContentFilterError)

    def test_classify_token_limit_error(self) -> None:
        """Test token limit error classification."""
        from src.services.llm.providers.google import GoogleProvider

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")

            error = Exception("token limit exceeded")
            result = provider._classify_error(error)
            assert isinstance(result, ContextLengthExceededError)

    def test_classify_unavailable_error(self) -> None:
        """Test unavailable error classification."""
        from src.services.llm.providers.google import GoogleProvider

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")

            error = Exception("503 temporarily unavailable")
            result = provider._classify_error(error)
            assert isinstance(result, ProviderUnavailableError)

    def test_classify_generic_error(self) -> None:
        """Test generic error classification."""
        from src.services.llm.providers.google import GoogleProvider

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")

            error = Exception("Some unknown error")
            result = provider._classify_error(error)
            assert isinstance(result, LLMProviderError)

    def test_get_finish_reason(self) -> None:
        """Test extracting finish reason from response."""
        from src.services.llm.providers.google import GoogleProvider

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")

            # Response with finish reason
            mock_response = MagicMock()
            mock_response.candidates = [MagicMock(finish_reason="STOP")]

            result = provider._get_finish_reason(mock_response)
            assert result == "STOP"

    def test_get_finish_reason_no_candidates(self) -> None:
        """Test finish reason when no candidates."""
        from src.services.llm.providers.google import GoogleProvider

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")

            mock_response = MagicMock()
            mock_response.candidates = []

            result = provider._get_finish_reason(mock_response)
            assert result is None

    def test_extract_retry_after(self) -> None:
        """Test extracting retry_after from error."""
        from src.services.llm.providers.google import GoogleProvider

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")

            # Error with retry_after
            error_with_retry = MagicMock()
            error_with_retry.retry_after = 60.0

            result = provider._extract_retry_after(error_with_retry)
            assert result == 60.0

    def test_extract_retry_after_none(self) -> None:
        """Test retry_after is None when not available."""
        from src.services.llm.providers.google import GoogleProvider

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")

            error = Exception("No retry info")
            result = provider._extract_retry_after(error)
            assert result is None


class TestProviderHealthTracking:
    """Tests for provider health tracking during generation."""

    @pytest.mark.asyncio
    async def test_anthropic_health_updated_on_success(self) -> None:
        """Test health is updated on successful generation."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Response")]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_response.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")
            provider._client = mock_client

            await provider.generate(prompt="Test", max_tokens=100)

            health = provider.get_health()
            assert health.total_requests == 1
            assert health.consecutive_successes == 1
            assert health.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_anthropic_health_updated_on_failure(self) -> None:
        """Test health is updated on failed generation."""
        from src.services.llm.providers.anthropic import AnthropicProvider

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            provider = AnthropicProvider(api_key="test-key")
            provider._client = mock_client

            with pytest.raises(LLMProviderError):
                await provider.generate(prompt="Test", max_tokens=100)

            health = provider.get_health()
            assert health.total_failures == 1
            assert health.consecutive_failures == 1

    def test_google_health_tracking(self) -> None:
        """Test Google provider health tracking."""
        from src.services.llm.providers.google import GoogleProvider

        with patch.dict(
            "sys.modules",
            {"google": MagicMock(), "google.genai": MagicMock()},
        ):
            provider = GoogleProvider(api_key="test-key")

            health = provider.get_health()
            assert isinstance(health, ProviderHealth)
            assert health.provider == "google"
            assert health.status == "healthy"

"""Tests for LLM provider exceptions.

Phase 5.1: Tests for the exception hierarchy.
"""

from src.services.llm.exceptions import (
    LLMProviderError,
    RateLimitError,
    AuthenticationError,
    ContentFilterError,
    ProviderUnavailableError,
    ModelNotFoundError,
    ContextLengthExceededError,
)


class TestLLMProviderError:
    """Tests for base LLMProviderError."""

    def test_basic_message(self) -> None:
        """Test basic error message."""
        error = LLMProviderError("Test error")
        assert str(error) == "Test error"
        assert error.provider is None

    def test_with_provider(self) -> None:
        """Test error with provider context."""
        error = LLMProviderError("Test error", provider="anthropic")
        assert error.provider == "anthropic"

    def test_inheritance(self) -> None:
        """Test error inherits from Exception."""
        error = LLMProviderError("Test")
        assert isinstance(error, Exception)


class TestRateLimitError:
    """Tests for RateLimitError."""

    def test_basic_message(self) -> None:
        """Test basic rate limit error."""
        error = RateLimitError()
        assert "Rate limit exceeded" in str(error)
        assert error.retry_after is None

    def test_with_retry_after(self) -> None:
        """Test rate limit error with retry_after."""
        error = RateLimitError(retry_after=30.0)
        assert error.retry_after == 30.0
        assert "30.0s" in str(error)

    def test_with_custom_message(self) -> None:
        """Test custom message."""
        error = RateLimitError(message="Custom rate limit", retry_after=15.0)
        assert "Custom rate limit" in str(error)
        assert error.retry_after == 15.0

    def test_with_provider(self) -> None:
        """Test with provider context."""
        error = RateLimitError(provider="google", retry_after=60.0)
        assert error.provider == "google"

    def test_inheritance(self) -> None:
        """Test inherits from LLMProviderError."""
        error = RateLimitError()
        assert isinstance(error, LLMProviderError)


class TestAuthenticationError:
    """Tests for AuthenticationError."""

    def test_default_message(self) -> None:
        """Test default error message."""
        error = AuthenticationError()
        assert "authentication failed" in str(error).lower()

    def test_custom_message(self) -> None:
        """Test custom message."""
        error = AuthenticationError(message="Invalid API key")
        assert "Invalid API key" in str(error)

    def test_with_provider(self) -> None:
        """Test with provider context."""
        error = AuthenticationError(provider="anthropic")
        assert error.provider == "anthropic"

    def test_inheritance(self) -> None:
        """Test inherits from LLMProviderError."""
        error = AuthenticationError()
        assert isinstance(error, LLMProviderError)


class TestContentFilterError:
    """Tests for ContentFilterError."""

    def test_default_message(self) -> None:
        """Test default error message."""
        error = ContentFilterError()
        assert "safety" in str(error).lower() or "filter" in str(error).lower()

    def test_custom_message(self) -> None:
        """Test custom message."""
        error = ContentFilterError(message="Blocked by policy")
        assert "Blocked by policy" in str(error)

    def test_inheritance(self) -> None:
        """Test inherits from LLMProviderError."""
        error = ContentFilterError()
        assert isinstance(error, LLMProviderError)


class TestProviderUnavailableError:
    """Tests for ProviderUnavailableError."""

    def test_default_message(self) -> None:
        """Test default error message."""
        error = ProviderUnavailableError()
        assert "unavailable" in str(error).lower()

    def test_custom_message(self) -> None:
        """Test custom message."""
        error = ProviderUnavailableError(message="503 Service Unavailable")
        assert "503" in str(error)

    def test_inheritance(self) -> None:
        """Test inherits from LLMProviderError."""
        error = ProviderUnavailableError()
        assert isinstance(error, LLMProviderError)


class TestModelNotFoundError:
    """Tests for ModelNotFoundError."""

    def test_default_message(self) -> None:
        """Test default error message."""
        error = ModelNotFoundError()
        assert "not found" in str(error).lower()
        assert error.model is None

    def test_with_model(self) -> None:
        """Test error with model name."""
        error = ModelNotFoundError(model="claude-99-turbo")
        assert error.model == "claude-99-turbo"
        assert "claude-99-turbo" in str(error)

    def test_inheritance(self) -> None:
        """Test inherits from LLMProviderError."""
        error = ModelNotFoundError()
        assert isinstance(error, LLMProviderError)


class TestContextLengthExceededError:
    """Tests for ContextLengthExceededError."""

    def test_default_message(self) -> None:
        """Test default error message."""
        error = ContextLengthExceededError()
        assert "context" in str(error).lower()
        assert error.max_tokens is None
        assert error.actual_tokens is None

    def test_with_token_counts(self) -> None:
        """Test error with token counts."""
        error = ContextLengthExceededError(max_tokens=100000, actual_tokens=150000)
        assert error.max_tokens == 100000
        assert error.actual_tokens == 150000
        assert "100000" in str(error)
        assert "150000" in str(error)

    def test_inheritance(self) -> None:
        """Test inherits from LLMProviderError."""
        error = ContextLengthExceededError()
        assert isinstance(error, LLMProviderError)

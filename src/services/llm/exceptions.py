"""LLM Provider Exception Hierarchy

Phase 5.1: Structured exception types for LLM provider errors.

This module defines a clear hierarchy of exceptions for LLM providers:
- LLMProviderError: Base class for all provider errors
- RateLimitError: Rate limit exceeded (retryable with backoff)
- AuthenticationError: Invalid API credentials
- ContentFilterError: Content blocked by safety filters
- ProviderUnavailableError: Provider temporarily unavailable
"""

from typing import Optional


class LLMProviderError(Exception):
    """Base exception for all LLM provider errors.

    All provider-specific errors inherit from this class,
    enabling consistent error handling across providers.
    """

    def __init__(self, message: str, provider: Optional[str] = None):
        self.provider = provider
        super().__init__(message)


class RateLimitError(LLMProviderError):
    """Raised when provider rate limit is exceeded.

    This is a retryable error - the caller should wait for
    retry_after seconds before retrying.

    Attributes:
        retry_after: Seconds to wait before retrying (if provided by API)
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[float] = None,
        provider: Optional[str] = None,
    ):
        self.retry_after = retry_after
        super().__init__(
            f"{message}. Retry after: {retry_after}s" if retry_after else message,
            provider=provider,
        )


class AuthenticationError(LLMProviderError):
    """Raised when API authentication fails.

    This is NOT retryable - the API key is invalid or revoked.
    """

    def __init__(
        self,
        message: str = "API authentication failed",
        provider: Optional[str] = None,
    ):
        super().__init__(message, provider=provider)


class ContentFilterError(LLMProviderError):
    """Raised when content is blocked by safety filters.

    This is NOT retryable with the same content.
    """

    def __init__(
        self,
        message: str = "Content blocked by safety filters",
        provider: Optional[str] = None,
    ):
        super().__init__(message, provider=provider)


class ProviderUnavailableError(LLMProviderError):
    """Raised when provider is temporarily unavailable.

    This is a retryable error - the provider may recover.
    Includes server errors (500, 502, 503, 504).
    """

    def __init__(
        self,
        message: str = "Provider temporarily unavailable",
        provider: Optional[str] = None,
    ):
        super().__init__(message, provider=provider)


class ModelNotFoundError(LLMProviderError):
    """Raised when the specified model is not available.

    This is NOT retryable - the model name is incorrect
    or the model is not available in the region.
    """

    def __init__(
        self,
        message: str = "Model not found",
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        self.model = model
        super().__init__(
            f"{message}: {model}" if model else message,
            provider=provider,
        )


class ContextLengthExceededError(LLMProviderError):
    """Raised when the input exceeds the model's context window.

    This is NOT retryable with the same input - must reduce
    input size or use a model with larger context.
    """

    def __init__(
        self,
        message: str = "Context length exceeded",
        max_tokens: Optional[int] = None,
        actual_tokens: Optional[int] = None,
        provider: Optional[str] = None,
    ):
        self.max_tokens = max_tokens
        self.actual_tokens = actual_tokens
        detail = ""
        if max_tokens and actual_tokens:
            detail = f" (max: {max_tokens}, actual: {actual_tokens})"
        super().__init__(f"{message}{detail}", provider=provider)

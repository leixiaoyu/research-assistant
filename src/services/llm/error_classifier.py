"""LLM Error Classification and Retry Logic.

This module provides error classification for LLM API errors,
determining which errors are retryable and extracting retry delays.
"""

from typing import Optional

from src.utils.exceptions import (
    RateLimitError,
    RetryableError,
    LLMAPIError,
)


class ErrorClassifier:
    """Classifies LLM errors for retry and fallback decisions.

    Categorizes errors into:
    - RateLimitError: Rate limit or quota exceeded (retryable with backoff)
    - RetryableError: Transient errors like timeouts (retryable)
    - LLMAPIError: Non-retryable errors
    """

    # Keywords indicating rate limit errors
    RATE_LIMIT_KEYWORDS = frozenset(
        [
            "429",
            "rate limit",
            "rate_limit",
            "quota",
            "resource_exhausted",
            "too many requests",
        ]
    )

    # Keywords indicating retryable errors
    RETRYABLE_KEYWORDS = frozenset(
        [
            "timeout",
            "timed out",
            "503",
            "service unavailable",
            "internal server",
            "temporarily unavailable",
            "connection reset",
            "connection refused",
        ]
    )

    @classmethod
    def classify(cls, error: Exception) -> Exception:
        """Classify an error for retry/fallback decisions.

        Args:
            error: The exception to classify

        Returns:
            Classified exception:
            - RateLimitError for rate limit/quota errors
            - RetryableError for transient errors
            - LLMAPIError for non-retryable errors
        """
        error_str = str(error).lower()

        # Check for rate limit errors
        if cls._is_rate_limit_error(error_str):
            return RateLimitError(str(error))

        # Check for retryable errors
        if cls._is_retryable_error(error_str):
            return RetryableError(str(error))

        # Non-retryable
        return LLMAPIError(str(error))

    @classmethod
    def _is_rate_limit_error(cls, error_str: str) -> bool:
        """Check if error string indicates rate limiting."""
        return any(keyword in error_str for keyword in cls.RATE_LIMIT_KEYWORDS)

    @classmethod
    def _is_retryable_error(cls, error_str: str) -> bool:
        """Check if error string indicates a retryable error."""
        return any(keyword in error_str for keyword in cls.RETRYABLE_KEYWORDS)

    @classmethod
    def is_retryable(cls, error: Exception) -> bool:
        """Check if an error is retryable.

        Args:
            error: The exception to check

        Returns:
            True if the error is retryable (RateLimitError or RetryableError)
        """
        classified = cls.classify(error)
        return isinstance(classified, (RateLimitError, RetryableError))

    @classmethod
    def extract_retry_after(cls, error: Exception) -> Optional[float]:
        """Extract retry-after value from an error.

        Checks for:
        - `retry_after` attribute on the error
        - `Retry-After` header in response

        Args:
            error: The exception to extract retry delay from

        Returns:
            Retry delay in seconds, or None if not available
        """
        # Check for retry_after attribute
        if hasattr(error, "retry_after"):
            retry_after = error.retry_after
            if retry_after is not None:
                try:
                    return float(retry_after)
                except (ValueError, TypeError):
                    pass

        # Check for response headers
        if hasattr(error, "response") and hasattr(error.response, "headers"):
            headers = error.response.headers
            retry_after = headers.get("retry-after") or headers.get("Retry-After")
            if retry_after is not None:
                try:
                    return float(retry_after)
                except (ValueError, TypeError):
                    return None

        return None

    @classmethod
    def get_default_retry_delay(cls, error: Exception, attempt: int = 1) -> float:
        """Get default retry delay for an error.

        Uses exponential backoff with longer delays for rate limit errors.

        Args:
            error: The exception
            attempt: Retry attempt number (1-based)

        Returns:
            Delay in seconds
        """
        # Try to extract from error first
        explicit_delay = cls.extract_retry_after(error)
        if explicit_delay is not None:
            return explicit_delay

        # Use exponential backoff
        base_delay = 1.0
        max_delay = 60.0

        # Rate limit errors get longer delays
        error_str = str(error).lower()
        if cls._is_rate_limit_error(error_str):
            base_delay = 5.0
            max_delay = 120.0

        delay: float = min(base_delay * (2 ** (attempt - 1)), max_delay)
        return delay


# Module-level convenience functions for backward compatibility
def classify_error(error: Exception) -> Exception:
    """Classify an error for retry/fallback decisions."""
    return ErrorClassifier.classify(error)


def extract_retry_after(error: Exception) -> Optional[float]:
    """Extract retry-after value from an error."""
    return ErrorClassifier.extract_retry_after(error)


def is_retryable(error: Exception) -> bool:
    """Check if an error is retryable."""
    return ErrorClassifier.is_retryable(error)

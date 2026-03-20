"""Unit tests for LLM Error Classifier.

Tests for error classification and retry logic extraction.
"""

from src.services.llm.error_classifier import (
    ErrorClassifier,
    classify_error,
    extract_retry_after,
    is_retryable,
)
from src.utils.exceptions import RateLimitError, RetryableError, LLMAPIError


class TestErrorClassifier:
    """Tests for ErrorClassifier class."""

    def test_classify_rate_limit_429(self):
        """Test classification of 429 errors as RateLimitError."""
        error = Exception("Error 429: Too many requests")
        result = ErrorClassifier.classify(error)
        assert isinstance(result, RateLimitError)

    def test_classify_rate_limit_quota(self):
        """Test classification of quota errors as RateLimitError."""
        error = Exception("Quota exceeded for this API")
        result = ErrorClassifier.classify(error)
        assert isinstance(result, RateLimitError)

    def test_classify_rate_limit_resource_exhausted(self):
        """Test classification of resource exhausted errors."""
        error = Exception("RESOURCE_EXHAUSTED: Rate limit reached")
        result = ErrorClassifier.classify(error)
        assert isinstance(result, RateLimitError)

    def test_classify_timeout(self):
        """Test classification of timeout errors as RetryableError."""
        error = Exception("Request timed out after 30s")
        result = ErrorClassifier.classify(error)
        assert isinstance(result, RetryableError)

    def test_classify_service_unavailable(self):
        """Test classification of 503 errors as RetryableError."""
        error = Exception("503 Service Unavailable")
        result = ErrorClassifier.classify(error)
        assert isinstance(result, RetryableError)

    def test_classify_internal_server_error(self):
        """Test classification of internal server errors as RetryableError."""
        error = Exception("Internal server error occurred")
        result = ErrorClassifier.classify(error)
        assert isinstance(result, RetryableError)

    def test_classify_non_retryable(self):
        """Test classification of non-retryable errors as LLMAPIError."""
        error = Exception("Invalid API key")
        result = ErrorClassifier.classify(error)
        assert isinstance(result, LLMAPIError)

    def test_classify_authentication_error(self):
        """Test authentication errors are not retryable."""
        error = Exception("401 Unauthorized: Invalid credentials")
        result = ErrorClassifier.classify(error)
        assert isinstance(result, LLMAPIError)

    def test_is_retryable_rate_limit(self):
        """Test is_retryable returns True for rate limit errors."""
        error = Exception("Rate limit exceeded")
        assert ErrorClassifier.is_retryable(error) is True

    def test_is_retryable_timeout(self):
        """Test is_retryable returns True for timeout errors."""
        error = Exception("Connection timed out")
        assert ErrorClassifier.is_retryable(error) is True

    def test_is_retryable_non_retryable(self):
        """Test is_retryable returns False for non-retryable errors."""
        error = Exception("Invalid request format")
        assert ErrorClassifier.is_retryable(error) is False


class TestExtractRetryAfter:
    """Tests for retry-after extraction."""

    def test_extract_from_attribute(self):
        """Test extraction from retry_after attribute."""

        class ErrorWithRetryAfter(Exception):
            retry_after = 30.0

        error = ErrorWithRetryAfter("Rate limited")
        result = ErrorClassifier.extract_retry_after(error)
        assert result == 30.0

    def test_extract_from_headers(self):
        """Test extraction from response headers."""

        class MockResponse:
            headers = {"Retry-After": "60"}

        class ErrorWithResponse(Exception):
            response = MockResponse()

        error = ErrorWithResponse("Rate limited")
        result = ErrorClassifier.extract_retry_after(error)
        assert result == 60.0

    def test_extract_from_lowercase_header(self):
        """Test extraction from lowercase header."""

        class MockResponse:
            headers = {"retry-after": "45"}

        class ErrorWithResponse(Exception):
            response = MockResponse()

        error = ErrorWithResponse("Rate limited")
        result = ErrorClassifier.extract_retry_after(error)
        assert result == 45.0

    def test_extract_none_when_missing(self):
        """Test returns None when no retry info available."""
        error = Exception("Some error")
        result = ErrorClassifier.extract_retry_after(error)
        assert result is None

    def test_extract_none_for_invalid_value(self):
        """Test returns None for invalid retry-after value."""

        class ErrorWithInvalidRetry(Exception):
            retry_after = "not-a-number"

        error = ErrorWithInvalidRetry("Rate limited")
        result = ErrorClassifier.extract_retry_after(error)
        assert result is None


class TestGetDefaultRetryDelay:
    """Tests for default retry delay calculation."""

    def test_default_delay_first_attempt(self):
        """Test default delay for first attempt."""
        error = Exception("Generic error")
        delay = ErrorClassifier.get_default_retry_delay(error, attempt=1)
        assert delay == 1.0

    def test_exponential_backoff(self):
        """Test exponential backoff for subsequent attempts."""
        error = Exception("Generic error")
        delays = [
            ErrorClassifier.get_default_retry_delay(error, attempt=i)
            for i in range(1, 5)
        ]
        assert delays == [1.0, 2.0, 4.0, 8.0]

    def test_rate_limit_longer_delay(self):
        """Test rate limit errors get longer delays."""
        error = Exception("Rate limit exceeded")
        delay = ErrorClassifier.get_default_retry_delay(error, attempt=1)
        assert delay == 5.0  # Higher base for rate limits

    def test_max_delay_cap(self):
        """Test delay is capped at max value."""
        error = Exception("Generic error")
        delay = ErrorClassifier.get_default_retry_delay(error, attempt=10)
        assert delay == 60.0  # Max delay

    def test_explicit_retry_after_used(self):
        """Test explicit retry-after value takes precedence."""

        class ErrorWithRetryAfter(Exception):
            retry_after = 120.0

        error = ErrorWithRetryAfter("Rate limited")
        delay = ErrorClassifier.get_default_retry_delay(error, attempt=1)
        assert delay == 120.0


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_classify_error_function(self):
        """Test module-level classify_error function."""
        error = Exception("429 rate limited")
        result = classify_error(error)
        assert isinstance(result, RateLimitError)

    def test_extract_retry_after_function(self):
        """Test module-level extract_retry_after function."""
        error = Exception("No retry info")
        result = extract_retry_after(error)
        assert result is None

    def test_is_retryable_function(self):
        """Test module-level is_retryable function."""
        error = Exception("Timeout occurred")
        assert is_retryable(error) is True

        error = Exception("Invalid API key")
        assert is_retryable(error) is False

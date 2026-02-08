"""Additional unit tests for Phase 3.3 Retry Handler coverage.

Tests for:
- Retry execution with success after failures
- Retry with rate limit error using retry_after
- Retry callback invocation
- Exhausting all retry attempts
"""

import pytest

from src.utils.retry import RetryHandler, RetryContext
from src.models.llm import RetryConfig
from src.utils.exceptions import RateLimitError, RetryableError


@pytest.fixture
def retry_config():
    """Create test retry configuration with short delays."""
    return RetryConfig(
        max_attempts=3,
        base_delay_seconds=0.001,  # Very short for fast tests
        max_delay_seconds=0.01,
        jitter_factor=0.0,  # No jitter for predictable tests
    )


@pytest.fixture
def retry_handler(retry_config):
    """Create retry handler instance."""
    return RetryHandler(retry_config)


class TestRetryExecution:
    """Tests for retry execution scenarios."""

    @pytest.mark.asyncio
    async def test_success_after_one_retry(self, retry_handler):
        """Test successful execution after one failure."""
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RetryableError("Transient failure")
            return "success"

        result = await retry_handler.execute(
            flaky_func, retryable_exceptions={RetryableError}
        )

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_success_after_two_retries(self, retry_handler):
        """Test successful execution after two failures."""
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RetryableError("Transient failure")
            return "success"

        result = await retry_handler.execute(
            flaky_func, retryable_exceptions={RetryableError}
        )

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausts_all_retries(self, retry_handler):
        """Test exception raised when all retries exhausted."""

        async def always_fails():
            raise RetryableError("Always fails")

        with pytest.raises(RetryableError, match="Always fails"):
            await retry_handler.execute(
                always_fails, retryable_exceptions={RetryableError}
            )

    @pytest.mark.asyncio
    async def test_retry_with_rate_limit_error(self, retry_handler):
        """Test retry uses retry_after from RateLimitError."""
        call_count = 0
        delays_used = []

        async def rate_limited_func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError("Rate limited", retry_after=0.001)
            return "success"

        def on_retry(attempt, error, delay):
            delays_used.append(delay)

        result = await retry_handler.execute(
            rate_limited_func,
            retryable_exceptions={RateLimitError},
            on_retry=on_retry,
        )

        assert result == "success"
        assert call_count == 2
        # Delay should be close to retry_after value (0.001)
        assert len(delays_used) == 1
        assert delays_used[0] <= 0.01  # Within max_delay

    @pytest.mark.asyncio
    async def test_on_retry_callback_called(self, retry_handler):
        """Test on_retry callback is called with correct args."""
        callback_calls = []

        async def flaky_func():
            if len(callback_calls) < 2:
                raise RetryableError("Failing")
            return "success"

        def on_retry(attempt, error, delay):
            callback_calls.append(
                {
                    "attempt": attempt,
                    "error_type": type(error).__name__,
                    "delay": delay,
                }
            )

        await retry_handler.execute(
            flaky_func,
            retryable_exceptions={RetryableError},
            on_retry=on_retry,
        )

        assert len(callback_calls) == 2
        assert callback_calls[0]["attempt"] == 1
        assert callback_calls[0]["error_type"] == "RetryableError"
        assert callback_calls[1]["attempt"] == 2

    @pytest.mark.asyncio
    async def test_rate_limit_no_retry_after(self, retry_handler):
        """Test RateLimitError without retry_after uses exponential backoff."""
        call_count = 0

        async def rate_limited_func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError("Rate limited", retry_after=None)
            return "success"

        result = await retry_handler.execute(
            rate_limited_func, retryable_exceptions={RateLimitError}
        )

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_multiple_retryable_exceptions(self, retry_handler):
        """Test retrying with multiple exception types."""
        call_count = 0

        async def multi_error_func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError("Rate limited")
            if call_count == 2:
                raise RetryableError("Transient")
            return "success"

        result = await retry_handler.execute(
            multi_error_func, retryable_exceptions={RateLimitError, RetryableError}
        )

        assert result == "success"
        assert call_count == 3


class TestRetryContextExtended:
    """Extended tests for RetryContext."""

    def test_multiple_retries_accumulate(self):
        """Test that multiple retries accumulate correctly."""
        ctx = RetryContext()

        ctx.record_attempt()
        ctx.record_retry(delay=1.0, error=RetryableError("err1"))
        ctx.record_attempt()
        ctx.record_retry(delay=2.0, error=RetryableError("err2"))
        ctx.record_attempt()

        assert ctx.total_attempts == 3
        assert ctx.total_retries == 2
        assert ctx.total_delay_seconds == 3.0
        assert ctx.last_error is not None

    def test_reset_clears_last_error(self):
        """Test reset clears all state including last_error."""
        ctx = RetryContext()
        ctx.record_retry(delay=1.0, error=RetryableError("error"))

        assert ctx.last_error is not None

        ctx.reset()

        assert ctx.last_error is None
        assert ctx.total_delay_seconds == 0.0


class TestCalculateDelay:
    """Tests for delay calculation."""

    def test_exponential_backoff_progression(self):
        """Test delay increases exponentially."""
        config = RetryConfig(
            max_attempts=5,
            base_delay_seconds=1.0,
            max_delay_seconds=60.0,
            jitter_factor=0.0,
        )
        handler = RetryHandler(config)

        assert handler.calculate_delay(0) == 1.0  # 1 * 2^0
        assert handler.calculate_delay(1) == 2.0  # 1 * 2^1
        assert handler.calculate_delay(2) == 4.0  # 1 * 2^2
        assert handler.calculate_delay(3) == 8.0  # 1 * 2^3

    def test_max_delay_cap(self):
        """Test delay is capped at max_delay."""
        config = RetryConfig(
            max_attempts=10,
            base_delay_seconds=1.0,
            max_delay_seconds=10.0,
            jitter_factor=0.0,
        )
        handler = RetryHandler(config)

        # 1 * 2^5 = 32, but should be capped at 10
        assert handler.calculate_delay(5) == 10.0

    def test_retry_after_overrides_backoff(self):
        """Test retry_after value is used instead of backoff."""
        config = RetryConfig(
            max_attempts=3,
            base_delay_seconds=1.0,
            max_delay_seconds=60.0,
            jitter_factor=0.0,
        )
        handler = RetryHandler(config)

        # Even at attempt 0 (normally 1s), retry_after should be used
        assert handler.calculate_delay(0, retry_after=5.0) == 5.0

    def test_retry_after_zero_uses_backoff(self):
        """Test retry_after=0 falls back to exponential backoff."""
        config = RetryConfig(
            max_attempts=3,
            base_delay_seconds=2.0,
            max_delay_seconds=60.0,
            jitter_factor=0.0,
        )
        handler = RetryHandler(config)

        # retry_after=0 should use exponential backoff
        assert handler.calculate_delay(0, retry_after=0) == 2.0
        assert handler.calculate_delay(1, retry_after=0) == 4.0

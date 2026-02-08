"""Unit tests for Phase 3.3 Retry Handler Utility"""

import pytest
from unittest.mock import AsyncMock

from src.utils.retry import RetryHandler, RetryContext
from src.models.llm import RetryConfig
from src.utils.exceptions import LLMAPIError


@pytest.fixture
def retry_config():
    """Create test retry configuration."""
    return RetryConfig(
        max_attempts=3,
        base_delay_seconds=0.01,
        max_delay_seconds=0.1,
        jitter_factor=0.1,
    )


@pytest.fixture
def retry_handler(retry_config):
    """Create retry handler instance."""
    return RetryHandler(retry_config)


class TestRetryHandlerInit:
    """Tests for RetryHandler initialization."""

    def test_init_with_config(self, retry_config):
        """Test handler initializes with config."""
        handler = RetryHandler(retry_config)
        assert handler.config == retry_config


class TestCalculateDelay:
    """Tests for delay calculation."""

    def test_calculate_delay_first_attempt(self, retry_handler):
        """Test delay for first attempt."""
        delay = retry_handler.calculate_delay(0)
        assert 0.009 <= delay <= 0.011

    def test_calculate_delay_with_retry_after(self, retry_handler):
        """Test delay uses retry_after when provided."""
        delay = retry_handler.calculate_delay(0, retry_after=0.05)
        assert 0.045 <= delay <= 0.055

    def test_calculate_delay_retry_after_zero_ignored(self, retry_handler):
        """Test retry_after=0 falls back to exponential backoff."""
        delay = retry_handler.calculate_delay(0, retry_after=0)
        assert 0.009 <= delay <= 0.011


class TestExecute:
    """Tests for retry execution."""

    @pytest.mark.asyncio
    async def test_execute_success_first_attempt(self, retry_handler):
        """Test successful execution on first attempt."""
        mock_func = AsyncMock(return_value="success")

        result = await retry_handler.execute(
            mock_func, retryable_exceptions={LLMAPIError}
        )

        assert result == "success"
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_execute_non_retryable_raises_immediately(self, retry_handler):
        """Test non-retryable exception is not retried."""
        mock_func = AsyncMock(side_effect=ValueError("not retryable"))

        with pytest.raises(ValueError, match="not retryable"):
            await retry_handler.execute(mock_func, retryable_exceptions={LLMAPIError})

        assert mock_func.call_count == 1


class TestRetryContext:
    """Tests for RetryContext tracking."""

    def test_init(self):
        """Test context initializes with zero values."""
        ctx = RetryContext()
        assert ctx.total_attempts == 0
        assert ctx.total_retries == 0

    def test_record_attempt(self):
        """Test recording an attempt."""
        ctx = RetryContext()
        ctx.record_attempt()
        assert ctx.total_attempts == 1

    def test_record_retry(self):
        """Test recording a retry."""
        ctx = RetryContext()
        error = LLMAPIError("test")
        ctx.record_retry(delay=1.0, error=error)
        assert ctx.total_retries == 1
        assert ctx.total_delay_seconds == 1.0

    def test_reset(self):
        """Test reset clears all values."""
        ctx = RetryContext()
        ctx.record_attempt()
        ctx.record_retry(delay=1.0, error=LLMAPIError("test"))
        ctx.reset()
        assert ctx.total_attempts == 0
        assert ctx.total_retries == 0

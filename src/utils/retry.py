"""Phase 3.3: Retry Handler Utility

Implements exponential backoff with jitter for retrying transient failures.

Features:
- Configurable retry attempts and delays
- Exponential backoff with jitter for request spreading
- Respects retry-after headers from rate limit errors
- Callback support for retry notifications
- Built-in structured logging for observability
"""

import asyncio
import random
from typing import TypeVar, Callable, Awaitable, Set, Type, Optional

import structlog

from src.models.llm import RetryConfig
from src.utils.exceptions import RateLimitError

logger = structlog.get_logger(__name__)


T = TypeVar("T")


class RetryHandler:
    """Async retry handler with exponential backoff and jitter.

    Provides automatic retry logic for transient failures with:
    - Exponential backoff: delay = base * 2^attempt
    - Jitter: ±jitter_factor randomization
    - Max delay cap: prevents excessive wait times
    - Retry-after support: respects rate limit headers
    """

    def __init__(self, config: RetryConfig) -> None:
        """Initialize retry handler with configuration.

        Args:
            config: Retry configuration with max_attempts, delays, and jitter
        """
        self.config = config

    def calculate_delay(
        self, attempt: int, retry_after: Optional[float] = None
    ) -> float:
        """Calculate delay for a retry attempt.

        Uses exponential backoff with jitter:
        - Base delay: config.base_delay_seconds * 2^attempt
        - Jitter: ±config.jitter_factor of base delay
        - Cap: config.max_delay_seconds

        If retry_after is provided (e.g., from rate limit headers),
        it is used as the base delay instead.

        Args:
            attempt: Current attempt number (0-indexed)
            retry_after: Optional retry-after value from error

        Returns:
            Delay in seconds to wait before next attempt
        """
        # Use retry-after if provided, otherwise calculate exponential backoff
        if retry_after is not None and retry_after > 0:
            base_delay = retry_after
        else:
            base_delay = self.config.base_delay_seconds * (2**attempt)

        # Apply jitter
        jitter = base_delay * self.config.jitter_factor
        delay = base_delay + random.uniform(-jitter, jitter)

        # Cap at max delay
        return min(delay, self.config.max_delay_seconds)

    async def execute(
        self,
        func: Callable[[], Awaitable[T]],
        retryable_exceptions: Set[Type[Exception]],
        on_retry: Optional[Callable[[int, Exception, float], None]] = None,
    ) -> T:
        """Execute function with retry logic.

        Attempts to execute the function, retrying on specified exceptions
        with exponential backoff.

        Args:
            func: Async function to execute
            retryable_exceptions: Set of exception types that should trigger retry
            on_retry: Optional callback called before each retry with
                     (attempt_number, exception, delay_seconds)

        Returns:
            Result of successful function execution

        Raises:
            Exception: The last exception if all retries are exhausted
        """
        last_exception: Optional[Exception] = None

        for attempt in range(self.config.max_attempts):
            try:
                return await func()
            except Exception as e:
                # Check if this exception should be retried
                should_retry = any(
                    isinstance(e, exc_type) for exc_type in retryable_exceptions
                )

                if not should_retry:
                    raise

                last_exception = e

                # Check if we have more attempts
                if attempt + 1 >= self.config.max_attempts:
                    raise

                # Calculate delay, using retry_after if available
                retry_after = None
                if isinstance(e, RateLimitError) and e.retry_after is not None:
                    retry_after = e.retry_after

                delay = self.calculate_delay(attempt, retry_after)

                # Log retry attempt for observability
                logger.warning(
                    "retry_attempt",
                    attempt=attempt + 1,
                    max_attempts=self.config.max_attempts,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    delay_seconds=delay,
                    retry_after=retry_after,
                )

                # Call retry callback if provided
                if on_retry is not None:
                    on_retry(attempt + 1, e, delay)

                # Wait before retry
                await asyncio.sleep(delay)

        # Defensive code to satisfy type checker - logically unreachable
        # since the loop either returns successfully or raises on exhaustion
        if last_exception is not None:  # pragma: no cover
            raise last_exception
        raise RuntimeError(  # pragma: no cover
            "Retry loop completed without result or exception"
        )


class RetryContext:
    """Context manager for tracking retry state.

    Useful for tracking retry metrics across multiple operations.
    """

    def __init__(self) -> None:
        """Initialize retry context."""
        self.total_attempts: int = 0
        self.total_retries: int = 0
        self.total_delay_seconds: float = 0.0
        self.last_error: Optional[Exception] = None

    def record_attempt(self) -> None:
        """Record a new attempt."""
        self.total_attempts += 1

    def record_retry(self, delay: float, error: Exception) -> None:
        """Record a retry with delay.

        Args:
            delay: Delay before retry in seconds
            error: Exception that triggered the retry
        """
        self.total_retries += 1
        self.total_delay_seconds += delay
        self.last_error = error

    def reset(self) -> None:
        """Reset the context for reuse."""
        self.total_attempts = 0
        self.total_retries = 0
        self.total_delay_seconds = 0.0
        self.last_error = None

"""Anthropic (Claude) Provider Implementation

Phase 5.1: Provider implementation for Anthropic Claude models.
"""

import time
from typing import Any, Optional
from datetime import datetime
import structlog

from src.services.llm.providers.base import LLMProvider, LLMResponse, ProviderHealth
from src.services.llm.exceptions import (
    LLMProviderError,
    RateLimitError,
    AuthenticationError,
    ContentFilterError,
    ProviderUnavailableError,
    ContextLengthExceededError,
)

logger = structlog.get_logger()


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider implementation.

    Supports Claude 3.5 Sonnet and other Claude models.

    Pricing (as of Jan 2025):
    - Claude 3.5 Sonnet: $3/MTok input, $15/MTok output
    """

    # Pricing per million tokens
    INPUT_COST_PER_MTOK = 3.00  # $3 per million input tokens
    OUTPUT_COST_PER_MTOK = 15.00  # $15 per million output tokens

    # Error patterns for classification
    RATE_LIMIT_PATTERNS = [
        "429",
        "rate limit",
        "rate_limit",
        "ratelimit",
        "too many requests",
        "quota exceeded",
    ]

    RETRYABLE_PATTERNS = [
        "timeout",
        "timed out",
        "connection",
        "temporary",
        "internal server",
        "502",
        "503",
        "504",
        "overloaded",
    ]

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
    ):
        """Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key
            model: Model identifier (default: claude-3-5-sonnet-20241022)

        Raises:
            LLMProviderError: If anthropic package is not installed
        """
        self._model = model
        self._health = ProviderHealth(provider="anthropic")
        self._client: Any = None

        try:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=api_key)
        except ImportError:
            raise LLMProviderError(
                "anthropic package not installed. Run: pip install anthropic",
                provider="anthropic",
            )

    @property
    def name(self) -> str:
        """Provider name."""
        return "anthropic"

    @property
    def model(self) -> str:
        """Current model identifier."""
        return self._model

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate text using Claude.

        Args:
            prompt: The input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            LLMResponse with generated content

        Raises:
            RateLimitError: When rate limit is exceeded
            AuthenticationError: When API key is invalid
            ContentFilterError: When content is blocked
            ProviderUnavailableError: When service is down
        """
        start_time = time.time()

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )

            latency_ms = (time.time() - start_time) * 1000

            # Extract content
            content = response.content[0].text if response.content else ""

            # Build standardized response
            llm_response = LLMResponse(
                content=content,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=self._model,
                provider=self.name,
                latency_ms=latency_ms,
                finish_reason=response.stop_reason,
                timestamp=datetime.utcnow(),
            )

            # Record success
            self._health.record_success()

            logger.debug(
                "anthropic_generate_success",
                model=self._model,
                input_tokens=llm_response.input_tokens,
                output_tokens=llm_response.output_tokens,
                latency_ms=latency_ms,
            )

            return llm_response

        except Exception as e:
            self._health.record_failure(str(e))
            raise self._classify_error(e)

    def _classify_error(self, error: Exception) -> LLMProviderError:
        """Classify exception into appropriate error type."""
        error_str = str(error).lower()

        # Check for authentication errors
        if (
            "authentication" in error_str
            or "401" in error_str
            or "invalid" in error_str
        ):
            return AuthenticationError(str(error), provider=self.name)

        # Check for content filter
        if "content" in error_str and ("filter" in error_str or "policy" in error_str):
            return ContentFilterError(str(error), provider=self.name)

        # Check for context length
        if "context" in error_str and "length" in error_str:
            return ContextLengthExceededError(str(error), provider=self.name)

        # Check for rate limits
        if any(pattern in error_str for pattern in self.RATE_LIMIT_PATTERNS):
            retry_after = self._extract_retry_after(error)
            return RateLimitError(
                str(error), retry_after=retry_after, provider=self.name
            )

        # Check for retryable errors
        if any(pattern in error_str for pattern in self.RETRYABLE_PATTERNS):
            return ProviderUnavailableError(str(error), provider=self.name)

        # Default to generic provider error
        return LLMProviderError(str(error), provider=self.name)

    def _extract_retry_after(self, error: Exception) -> Optional[float]:
        """Extract retry-after value from error if available."""
        if hasattr(error, "retry_after") and error.retry_after is not None:
            return float(error.retry_after)
        if hasattr(error, "response") and hasattr(error.response, "headers"):
            retry_after = error.response.headers.get("Retry-After")
            if retry_after:
                try:
                    return float(retry_after)
                except ValueError:
                    pass
        return None

    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Calculate cost in USD for token usage.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD
        """
        input_cost = (input_tokens / 1_000_000) * self.INPUT_COST_PER_MTOK
        output_cost = (output_tokens / 1_000_000) * self.OUTPUT_COST_PER_MTOK
        return input_cost + output_cost

    def get_health(self) -> ProviderHealth:
        """Get current provider health status."""
        return self._health

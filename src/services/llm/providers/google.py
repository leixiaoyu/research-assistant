"""Google (Gemini) Provider Implementation

Phase 5.1: Provider implementation for Google Gemini models.
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


class GoogleProvider(LLMProvider):
    """Google Gemini provider implementation.

    Supports Gemini 1.5 Pro and other Gemini models.

    Pricing (as of Jan 2025):
    - Gemini 1.5 Pro: $1.25/MTok input, $5/MTok output
    """

    # Pricing per million tokens
    INPUT_COST_PER_MTOK = 1.25  # $1.25 per million input tokens
    OUTPUT_COST_PER_MTOK = 5.00  # $5 per million output tokens

    # Error patterns for classification
    RATE_LIMIT_PATTERNS = [
        "429",
        "rate limit",
        "rate_limit",
        "ratelimit",
        "quota exceeded",
        "resource_exhausted",
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
        "unavailable",
    ]

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-1.5-pro",
    ):
        """Initialize Google provider.

        Args:
            api_key: Google API key
            model: Model identifier (default: gemini-1.5-pro)

        Raises:
            LLMProviderError: If google-genai package is not installed
        """
        self._model = model
        self._health = ProviderHealth(provider="google")
        self._client: Any = None

        try:
            from google import genai

            self._client = genai.Client(api_key=api_key)
        except ImportError:
            raise LLMProviderError(
                "google-genai package not installed. Run: pip install google-genai",
                provider="google",
            )

    @property
    def name(self) -> str:
        """Provider name."""
        return "google"

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
        """Generate text using Gemini.

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
            from google.genai import types

            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )

            latency_ms = (time.time() - start_time) * 1000

            # Extract content
            content = response.text if hasattr(response, "text") else ""

            # Extract token counts from usage_metadata
            usage = getattr(response, "usage_metadata", None)
            if usage:
                input_tokens = getattr(usage, "prompt_token_count", 0)
                output_tokens = getattr(usage, "candidates_token_count", 0)
                # Fallback to total if individual counts not available
                if input_tokens == 0 and output_tokens == 0:
                    total = getattr(usage, "total_token_count", 0)
                    # Estimate split (rough approximation)
                    input_tokens = int(total * 0.7)
                    output_tokens = total - input_tokens
            else:
                input_tokens = 0
                output_tokens = 0

            # Build standardized response
            llm_response = LLMResponse(
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=self._model,
                provider=self.name,
                latency_ms=latency_ms,
                finish_reason=self._get_finish_reason(response),
                timestamp=datetime.utcnow(),
            )

            # Record success
            self._health.record_success()

            logger.debug(
                "google_generate_success",
                model=self._model,
                input_tokens=llm_response.input_tokens,
                output_tokens=llm_response.output_tokens,
                latency_ms=latency_ms,
            )

            return llm_response

        except Exception as e:
            self._health.record_failure(str(e))
            raise self._classify_error(e)

    def _get_finish_reason(self, response: Any) -> Optional[str]:
        """Extract finish reason from response."""
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "finish_reason"):
                return str(candidate.finish_reason)
        return None

    def _classify_error(self, error: Exception) -> LLMProviderError:
        """Classify exception into appropriate error type."""
        error_str = str(error).lower()

        # Check for authentication errors
        if (
            "authentication" in error_str
            or "401" in error_str
            or "api_key" in error_str
        ):
            return AuthenticationError(str(error), provider=self.name)

        # Check for content filter
        if "safety" in error_str or "blocked" in error_str:
            return ContentFilterError(str(error), provider=self.name)

        # Check for context length
        if "token" in error_str and ("limit" in error_str or "exceed" in error_str):
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
        if hasattr(error, "retry_after"):
            return float(error.retry_after)
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

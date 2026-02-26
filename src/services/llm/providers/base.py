"""Abstract LLM Provider Interface

Phase 5.1: Provider abstraction for LLM services.

This module defines:
- LLMResponse: Standardized response dataclass
- LLMProvider: Abstract base class for all providers
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Literal
from datetime import datetime


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider.

    This dataclass normalizes responses across different providers,
    enabling consistent handling regardless of the underlying API.

    Attributes:
        content: The generated text content
        input_tokens: Number of input tokens consumed
        output_tokens: Number of output tokens generated
        model: The model identifier used
        provider: The provider name (anthropic, google)
        latency_ms: Request latency in milliseconds
        finish_reason: Why generation stopped (stop, length, etc.)
        timestamp: When the response was received
    """

    content: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str
    latency_ms: float
    finish_reason: Optional[str] = None
    timestamp: Optional[datetime] = None

    @property
    def total_tokens(self) -> int:
        """Total tokens used (input + output)."""
        return self.input_tokens + self.output_tokens


@dataclass
class ProviderHealth:
    """Health tracking for a single LLM provider.

    Tracks request success/failure patterns and integrates
    with circuit breaker for failure isolation.
    """

    provider: str
    status: Literal["healthy", "degraded", "unavailable"] = "healthy"
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_requests: int = 0
    total_failures: int = 0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    failure_reason: Optional[str] = None
    circuit_breaker: Optional[Any] = None  # CircuitBreaker instance

    def record_success(self) -> None:
        """Record a successful request."""
        self.total_requests += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success = datetime.utcnow()
        if self.status == "degraded":
            self.status = "healthy"

    def record_failure(self, reason: str) -> None:
        """Record a failed request."""
        self.total_requests += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure = datetime.utcnow()
        self.failure_reason = reason
        if self.consecutive_failures >= 3:
            self.status = "degraded"
        if self.consecutive_failures >= 5:
            self.status = "unavailable"

    def get_stats(self) -> dict:
        """Get health statistics as dictionary."""
        stats = {
            "provider": self.provider,
            "status": self.status,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "last_success": (
                self.last_success.isoformat() if self.last_success else None
            ),
            "last_failure": (
                self.last_failure.isoformat() if self.last_failure else None
            ),
            "failure_reason": self.failure_reason,
        }
        # Include circuit breaker stats if present
        if self.circuit_breaker is not None:
            stats["circuit_breaker"] = self.circuit_breaker.get_stats()
        return stats


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    Defines the contract that all provider implementations must follow.
    Each provider handles its own API communication, error handling,
    and response normalization.

    Implementations:
        - AnthropicProvider: Claude models
        - GoogleProvider: Gemini models
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'anthropic', 'google')."""
        pass  # pragma: no cover - abstract method, always overridden

    @property
    @abstractmethod
    def model(self) -> str:
        """Current model identifier."""
        pass  # pragma: no cover - abstract method, always overridden

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate text from prompt.

        Args:
            prompt: The input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0 = deterministic)

        Returns:
            LLMResponse with generated content and metadata

        Raises:
            LLMProviderError: Base class for all provider errors
            RateLimitError: When rate limit is exceeded
            AuthenticationError: When API key is invalid
            ContentFilterError: When content is blocked by safety filters
            ProviderUnavailableError: When provider is temporarily down
        """
        pass  # pragma: no cover - abstract method, always overridden

    @abstractmethod
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
            Cost in USD (float)
        """
        pass  # pragma: no cover - abstract method, always overridden

    def get_health(self) -> ProviderHealth:
        """Get current provider health status.

        Override in implementations to return actual health tracking.
        Default returns a healthy status.
        """
        return ProviderHealth(provider=self.name, status="healthy")

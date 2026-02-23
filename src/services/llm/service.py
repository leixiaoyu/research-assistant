"""LLM Service - Main Orchestrator

Phase 5.1: Refactored LLMService as thin orchestrator.

This service orchestrates LLM extraction by delegating to:
- LLMProvider implementations (Anthropic, Google)
- CostTracker for budget enforcement
- PromptBuilder for prompt construction
- ResponseParser for JSON parsing
- RetryHandler for retry logic
- CircuitBreaker for failure isolation

The service maintains backward compatibility with the original API.
"""

import os
import time
from typing import List, Any, Optional, Dict
from datetime import datetime
import structlog

from src.models.llm import LLMConfig, CostLimits, EnhancedUsageStats, ProviderUsageStats
from src.models.extraction import ExtractionTarget, PaperExtraction
from src.models.paper import PaperMetadata
from src.services.llm.cost_tracker import CostTracker
from src.services.llm.prompt_builder import PromptBuilder
from src.services.llm.response_parser import ResponseParser
from src.services.llm.providers.base import LLMProvider, LLMResponse, ProviderHealth
from src.services.llm.providers.anthropic import AnthropicProvider
from src.services.llm.providers.google import GoogleProvider
from src.services.llm.exceptions import LLMProviderError, RateLimitError
from src.utils.exceptions import (
    ExtractionError,
    LLMAPIError,
    JSONParseError,
    RetryableError,
    AllProvidersFailedError,
)
from src.utils.retry import RetryHandler
from src.utils.circuit_breaker import CircuitBreakerRegistry

# Phase 4: Prometheus metrics
from src.observability.metrics import (
    LLM_TOKENS_TOTAL,
    LLM_COST_USD_TOTAL,
    LLM_REQUESTS_TOTAL,
    LLM_REQUEST_DURATION,
    EXTRACTION_ERRORS,
    EXTRACTION_CONFIDENCE,
    DAILY_COST_USD,
)

logger = structlog.get_logger()


class LLMService:
    """Service for extracting information from papers using LLMs.

    This is a thin orchestrator that delegates to specialized components:
    - Providers handle API communication
    - CostTracker handles budget enforcement
    - PromptBuilder handles prompt construction
    - ResponseParser handles response parsing

    Supports Anthropic (Claude) and Google (Gemini) providers with
    automatic fallback, retry logic, and circuit breaker protection.
    """

    def __init__(
        self,
        config: LLMConfig,
        cost_limits: CostLimits,
        usage_stats: Optional[EnhancedUsageStats] = None,
    ):
        """Initialize LLM service.

        Args:
            config: LLM configuration (provider, model, API key)
            cost_limits: Budget limits
            usage_stats: Usage statistics (optional, creates new if None)

        Raises:
            ExtractionError: If provider cannot be initialized
        """
        self.config = config
        self.cost_limits = cost_limits
        self.usage_stats = usage_stats or EnhancedUsageStats()

        # Initialize components
        self._cost_tracker = CostTracker(limits=cost_limits)
        self._prompt_builder = PromptBuilder()
        self._response_parser = ResponseParser()

        # Initialize retry handler
        self.retry_handler = RetryHandler(config.retry)

        # Initialize circuit breaker registry
        self.circuit_registry = CircuitBreakerRegistry()

        # Initialize providers
        self._providers: Dict[str, LLMProvider] = {}
        self._provider_health: Dict[str, ProviderHealth] = {}
        self._init_primary_provider()

        # Initialize fallback provider if configured
        self.fallback_provider: Optional[str] = None
        if config.fallback and config.fallback.enabled:
            self._init_fallback_provider()

        logger.info(
            "llm_service_initialized",
            provider=config.provider,
            model=config.model,
            max_tokens=config.max_tokens,
            retry_enabled=True,
            fallback_enabled=bool(config.fallback and config.fallback.enabled),
            circuit_breaker_enabled=config.circuit_breaker.enabled,
        )

    def _init_primary_provider(self) -> None:
        """Initialize the primary provider."""
        provider = self._create_provider(
            self.config.provider,
            self.config.api_key,
            self.config.model,
        )
        self._providers[self.config.provider] = provider
        self._init_provider_health(self.config.provider, provider)

    def _init_fallback_provider(self) -> None:
        """Initialize fallback provider if configured."""
        fallback_config = self.config.fallback
        if not fallback_config:
            return

        # Get API key from config or environment
        api_key = fallback_config.api_key
        if not api_key:
            if fallback_config.provider == "anthropic":
                api_key = os.environ.get("ANTHROPIC_API_KEY")
            else:
                api_key = os.environ.get("GOOGLE_API_KEY")

        if not api_key:
            logger.warning(
                "fallback_api_key_not_found",
                provider=fallback_config.provider,
            )
            return

        try:
            provider = self._create_provider(
                fallback_config.provider,
                api_key,
                fallback_config.model,
            )
            self._providers[fallback_config.provider] = provider
            self._init_provider_health(fallback_config.provider, provider)
            self.fallback_provider = fallback_config.provider

            logger.info(
                "fallback_provider_initialized",
                provider=fallback_config.provider,
                model=fallback_config.model,
            )
        except Exception as e:
            logger.warning(
                "fallback_provider_init_failed",
                provider=fallback_config.provider,
                error=str(e),
            )

    def _create_provider(
        self,
        provider_name: str,
        api_key: str,
        model: str,
    ) -> LLMProvider:
        """Create a provider instance.

        Args:
            provider_name: Provider name (anthropic, google)
            api_key: API key
            model: Model identifier

        Returns:
            LLMProvider instance

        Raises:
            ExtractionError: If provider is unknown
        """
        if provider_name == "anthropic":
            return AnthropicProvider(api_key=api_key, model=model)
        elif provider_name == "google":
            return GoogleProvider(api_key=api_key, model=model)
        else:
            raise ExtractionError(f"Unknown provider: {provider_name}")

    def _init_provider_health(self, name: str, provider: LLMProvider) -> None:
        """Initialize health tracking for a provider."""
        health = provider.get_health()

        # Attach circuit breaker if enabled
        if self.config.circuit_breaker.enabled:
            circuit_breaker = self.circuit_registry.get_or_create(
                name, self.config.circuit_breaker
            )
            # Store circuit breaker reference for later use
            health.circuit_breaker = circuit_breaker  # type: ignore

        self._provider_health[name] = health

    async def extract(
        self,
        markdown_content: str,
        targets: List[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> PaperExtraction:
        """Extract information from markdown using LLM.

        Implements retry logic and provider fallback.

        Args:
            markdown_content: Full paper in markdown format
            targets: List of extraction targets
            paper_metadata: Paper metadata for context

        Returns:
            PaperExtraction with results

        Raises:
            CostLimitExceeded: If cost limits would be exceeded
            AllProvidersFailedError: If all providers fail
            JSONParseError: If response parsing fails
        """
        # Check for daily reset
        if self._cost_tracker.should_reset_daily():
            logger.info("daily_stats_reset")
            self.usage_stats.reset_daily_stats()

        # Check cost limits BEFORE calling LLM
        self._cost_tracker.check_limits()

        # Build extraction prompt
        prompt = self._prompt_builder.build(markdown_content, targets, paper_metadata)

        logger.info(
            "extraction_started",
            paper_id=paper_metadata.paper_id,
            targets=len(targets),
            provider=self.config.provider,
        )

        provider_errors: Dict[str, str] = {}

        # Try primary provider
        try:
            return await self._extract_with_provider(
                provider_name=self.config.provider,
                prompt=prompt,
                targets=targets,
                paper_metadata=paper_metadata,
            )
        except (LLMAPIError, LLMProviderError) as e:
            provider_errors[self.config.provider] = str(e)
            logger.warning(
                "primary_provider_failed",
                provider=self.config.provider,
                error=str(e),
            )

        # Try fallback provider if configured
        if self.fallback_provider and self.fallback_provider in self._providers:
            logger.info(
                "attempting_fallback",
                fallback_provider=self.fallback_provider,
            )
            self.usage_stats.total_fallback_activations += 1
            self._cost_tracker.record_fallback()

            try:
                return await self._extract_with_provider(
                    provider_name=self.fallback_provider,
                    prompt=prompt,
                    targets=targets,
                    paper_metadata=paper_metadata,
                    is_fallback=True,
                )
            except (LLMAPIError, LLMProviderError) as e:
                provider_errors[self.fallback_provider] = str(e)
                logger.warning(
                    "fallback_provider_failed",
                    provider=self.fallback_provider,
                    error=str(e),
                )

        # All providers failed
        raise AllProvidersFailedError(
            "All LLM providers failed", provider_errors=provider_errors
        )

    async def _extract_with_provider(
        self,
        provider_name: str,
        prompt: str,
        targets: List[ExtractionTarget],
        paper_metadata: PaperMetadata,
        is_fallback: bool = False,
    ) -> PaperExtraction:
        """Extract using a specific provider with retry logic."""
        provider = self._providers[provider_name]
        health = self._provider_health.get(provider_name)

        # Check circuit breaker
        if health and hasattr(health, "circuit_breaker") and health.circuit_breaker:
            health.circuit_breaker.check_or_raise()

        start_time = time.time()
        retry_attempts = 0

        try:
            # Define the API call function
            async def call_provider() -> LLMResponse:
                return await provider.generate(
                    prompt=prompt,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                )

            def on_retry(attempt: int, error: Exception, delay: float) -> None:
                nonlocal retry_attempts
                retry_attempts = attempt
                self.usage_stats.total_retry_attempts += 1
                self._cost_tracker.record_retry()
                logger.warning(
                    "llm_retry_attempt",
                    provider=provider_name,
                    attempt=attempt,
                    error=str(error),
                    delay=delay,
                )

            # Execute with retry
            response = await self.retry_handler.execute(
                call_provider,
                retryable_exceptions={RetryableError, RateLimitError},
                on_retry=on_retry,
            )

            # Record metrics
            duration = time.time() - start_time
            LLM_REQUEST_DURATION.labels(provider=provider_name).observe(duration)
            LLM_TOKENS_TOTAL.labels(provider=provider_name, type="input").inc(
                response.input_tokens
            )
            LLM_TOKENS_TOTAL.labels(provider=provider_name, type="output").inc(
                response.output_tokens
            )

            # Calculate cost
            cost = provider.calculate_cost(
                response.input_tokens, response.output_tokens
            )
            LLM_COST_USD_TOTAL.labels(provider=provider_name).inc(cost)
            DAILY_COST_USD.labels(provider=provider_name).set(
                self.usage_stats.total_cost_usd + cost
            )
            LLM_REQUESTS_TOTAL.labels(provider=provider_name, status="success").inc()

            # Update health tracking
            if health:
                health.record_success()
                if hasattr(health, "circuit_breaker") and health.circuit_breaker:
                    health.circuit_breaker.record_success()

            # Parse response
            results = self._response_parser.parse(response, targets, provider_name)

            for result in results:
                if result.success and result.confidence is not None:
                    EXTRACTION_CONFIDENCE.observe(result.confidence)

            # Update usage stats
            self._update_usage(
                response.total_tokens, cost, provider_name, retry_attempts, is_fallback
            )

            logger.info(
                "extraction_completed",
                paper_id=paper_metadata.paper_id,
                provider=provider_name,
                tokens_used=response.total_tokens,
                cost_usd=cost,
                retry_attempts=retry_attempts,
                is_fallback=is_fallback,
                successful_extractions=sum(1 for r in results if r.success),
            )

            return PaperExtraction(
                paper_id=paper_metadata.paper_id,
                extraction_results=results,
                tokens_used=response.total_tokens,
                cost_usd=cost,
                extraction_timestamp=datetime.utcnow(),
            )

        except JSONParseError:
            # JSONParseError is not a provider issue - let it propagate
            raise

        except Exception as e:
            # Update health tracking on failure
            if health:
                health.record_failure(str(e))
                if hasattr(health, "circuit_breaker") and health.circuit_breaker:
                    health.circuit_breaker.record_failure()

            # Update provider-specific stats
            self._cost_tracker.record_failure(provider_name)
            if provider_name not in self.usage_stats.by_provider:
                self.usage_stats.by_provider[provider_name] = ProviderUsageStats(
                    provider=provider_name
                )
            self.usage_stats.by_provider[provider_name].record_failure()

            LLM_REQUESTS_TOTAL.labels(provider=provider_name, status="failed").inc()
            EXTRACTION_ERRORS.labels(error_type="llm").inc()

            logger.error(
                "llm_api_call_failed",
                paper_id=paper_metadata.paper_id,
                provider=provider_name,
                retry_attempts=retry_attempts,
                error=str(e),
            )
            raise LLMAPIError(f"{provider_name}: {e}")

    def _update_usage(
        self,
        tokens: int,
        cost: float,
        provider: str,
        retry_attempts: int,
        is_fallback: bool,
    ) -> None:
        """Update usage statistics."""
        # Update cost tracker
        self._cost_tracker.record_usage(
            tokens=tokens,
            cost=cost,
            provider=provider,
            was_retry=retry_attempts > 0,
            is_fallback=is_fallback,
        )

        # Update legacy usage stats
        self.usage_stats.total_tokens += tokens
        self.usage_stats.total_cost_usd += cost
        self.usage_stats.papers_processed += 1

        # Update provider-specific stats
        if provider not in self.usage_stats.by_provider:
            self.usage_stats.by_provider[provider] = ProviderUsageStats(
                provider=provider
            )
        self.usage_stats.by_provider[provider].record_success(
            tokens=tokens,
            cost=cost,
            was_retry=retry_attempts > 0,
        )
        if is_fallback:
            self.usage_stats.by_provider[provider].fallback_requests += 1

    def get_usage_summary(self) -> dict:
        """Get current usage statistics."""
        return {
            "total_tokens": self.usage_stats.total_tokens,
            "total_cost_usd": round(self.usage_stats.total_cost_usd, 2),
            "papers_processed": self.usage_stats.papers_processed,
            "last_reset": self.usage_stats.last_reset.isoformat(),
            "daily_budget_remaining": round(
                self.cost_limits.max_daily_spend_usd - self.usage_stats.total_cost_usd,
                2,
            ),
            "total_budget_remaining": round(
                self.cost_limits.max_total_spend_usd - self.usage_stats.total_cost_usd,
                2,
            ),
        }

    def get_provider_health(self) -> Dict[str, dict]:
        """Get health status for all providers."""
        return {
            name: health.get_stats() for name, health in self._provider_health.items()
        }

    def reset_circuit_breakers(self) -> None:
        """Reset all circuit breakers to CLOSED state."""
        self.circuit_registry.reset_all()
        for health in self._provider_health.values():
            health.status = "healthy"
            health.consecutive_failures = 0

    # Legacy property for backward compatibility
    @property
    def provider_health(self) -> Dict[str, ProviderHealth]:
        """Legacy property for backward compatibility."""
        return self._provider_health

    # Legacy property for backward compatibility
    @property
    def client(self) -> Any:
        """Legacy property - returns primary provider's client."""
        provider = self._providers.get(self.config.provider)
        if provider and hasattr(provider, "_client"):
            return provider._client
        return None

    # Legacy property for backward compatibility
    @property
    def fallback_client(self) -> Any:
        """Legacy property - returns fallback provider's client."""
        if self.fallback_provider:
            provider = self._providers.get(self.fallback_provider)
            if provider and hasattr(provider, "_client"):
                return provider._client
        return None

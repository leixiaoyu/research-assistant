"""LLM Service for Phase 2 & 3.3: PDF Processing, LLM Extraction & Resilience

This service handles:
1. LLM provider abstraction (Anthropic Claude / Google Gemini)
2. Building structured extraction prompts
3. Parsing LLM JSON responses
4. Cost tracking and budget enforcement
5. Usage statistics
6. Prometheus metrics export (Phase 4)
7. Phase 3.3: Retry with exponential backoff
8. Phase 3.3: Provider fallback (Gemini <-> Claude)
9. Phase 3.3: Circuit breaker pattern
10. Phase 3.3: Per-provider health tracking

Cost Control Features:
- Per-paper token limits
- Daily spending limits
- Total spending limits
- Automatic daily reset

Security Features:
- API key from environment only
- No hardcoded credentials
- Input validation via Pydantic
"""

import json
import os
import time
from dataclasses import dataclass
from typing import List, Any, Optional, Literal
from datetime import datetime
import structlog

from src.models.llm import (
    LLMConfig,
    CostLimits,
    EnhancedUsageStats,
    ProviderUsageStats,
)
from src.models.extraction import ExtractionTarget, ExtractionResult, PaperExtraction
from src.models.paper import PaperMetadata
from src.utils.exceptions import (
    ExtractionError,
    CostLimitExceeded,
    LLMAPIError,
    JSONParseError,
    RetryableError,
    RateLimitError,
    ProviderUnavailableError,
    AllProvidersFailedError,
)
from src.utils.retry import RetryHandler
from src.utils.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry

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


@dataclass
class ProviderHealth:
    """Health tracking for a single LLM provider."""

    provider: str
    status: Literal["healthy", "degraded", "unavailable"] = "healthy"
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_requests: int = 0
    total_failures: int = 0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    failure_reason: Optional[str] = None
    circuit_breaker: Optional[CircuitBreaker] = None

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
        """Get health statistics."""
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

        if self.circuit_breaker:
            stats["circuit_breaker"] = self.circuit_breaker.get_stats()

        return stats


class LLMService:
    """Service for extracting information from papers using LLMs

    Supports both Anthropic (Claude) and Google (Gemini) providers.
    Implements cost tracking, budget enforcement, retry logic, and fallback.
    """

    # Claude 3.5 Sonnet pricing (as of Jan 2025)
    CLAUDE_INPUT_COST_PER_MTOK = 3.00  # $3 per million tokens
    CLAUDE_OUTPUT_COST_PER_MTOK = 15.00  # $15 per million tokens

    # Gemini 1.5 Pro pricing (as of Jan 2025)
    GEMINI_INPUT_COST_PER_MTOK = 1.25  # $1.25 per million tokens
    GEMINI_OUTPUT_COST_PER_MTOK = 5.00  # $5 per million tokens

    # Rate limit detection patterns
    RATE_LIMIT_PATTERNS = [
        "429",
        "rate limit",
        "rate_limit",
        "ratelimit",
        "too many requests",
        "quota exceeded",
        "resource_exhausted",
    ]

    # Retryable error patterns
    RETRYABLE_PATTERNS = [
        "timeout",
        "timed out",
        "connection",
        "temporary",
        "internal server",
        "502",
        "503",
        "504",
    ]

    def __init__(
        self,
        config: LLMConfig,
        cost_limits: CostLimits,
        usage_stats: Optional[EnhancedUsageStats] = None,
    ):
        """Initialize LLM service

        Args:
            config: LLM configuration (provider, model, API key)
            cost_limits: Budget limits
            usage_stats: Usage statistics (optional, creates new if None)

        Raises:
            ValueError: If API key is invalid
        """
        self.config = config
        self.cost_limits = cost_limits
        self.usage_stats = usage_stats or EnhancedUsageStats()

        # Initialize provider-specific client
        self.client: Any = None
        self._google_model: Optional[str] = None  # For new Google GenAI SDK
        self._fallback_google_model: Optional[str] = None
        self._init_provider_client(config.provider, config.api_key, config.model)

        # Phase 3.3: Initialize retry handler
        self.retry_handler = RetryHandler(config.retry)

        # Phase 3.3: Initialize circuit breaker registry
        self.circuit_registry = CircuitBreakerRegistry()

        # Phase 3.3: Initialize provider health tracking
        self.provider_health: dict[str, ProviderHealth] = {}
        self._init_provider_health(config.provider)

        # Phase 3.3: Initialize fallback provider if configured
        self.fallback_client: Any = None
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

    def _init_provider_client(self, provider: str, api_key: str, model: str) -> None:
        """Initialize a provider client."""
        if provider == "anthropic":
            try:
                from anthropic import AsyncAnthropic

                self.client = AsyncAnthropic(api_key=api_key)
            except ImportError:
                raise ExtractionError(
                    "anthropic package not installed. Run: pip install anthropic"
                )
        elif provider == "google":
            try:
                from google import genai

                self.client = genai.Client(api_key=api_key)
                self._google_model = model  # Store model name for API calls
            except ImportError:
                raise ExtractionError(
                    "google-genai package not installed. "
                    "Run: pip install google-genai"
                )

    def _init_provider_health(self, provider: str) -> None:
        """Initialize health tracking for a provider."""
        circuit_breaker = None
        if self.config.circuit_breaker.enabled:
            circuit_breaker = self.circuit_registry.get_or_create(
                provider, self.config.circuit_breaker
            )

        self.provider_health[provider] = ProviderHealth(
            provider=provider,
            circuit_breaker=circuit_breaker,
        )

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

        self.fallback_provider = fallback_config.provider

        if fallback_config.provider == "anthropic":
            try:
                from anthropic import AsyncAnthropic

                self.fallback_client = AsyncAnthropic(api_key=api_key)
            except ImportError:
                logger.warning("anthropic_not_installed_for_fallback")
                return
        elif fallback_config.provider == "google":
            try:
                from google import genai

                self.fallback_client = genai.Client(api_key=api_key)
                self._fallback_google_model = fallback_config.model
            except ImportError:
                logger.warning("google_genai_not_installed_for_fallback")
                return

        # Initialize health tracking for fallback
        self._init_provider_health(fallback_config.provider)

        logger.info(
            "fallback_provider_initialized",
            provider=fallback_config.provider,
            model=fallback_config.model,
        )

    async def extract(
        self,
        markdown_content: str,
        targets: List[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> PaperExtraction:
        """Extract information from markdown using LLM

        Phase 3.3: Implements retry logic and provider fallback.

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
        # Check if daily stats should be reset
        if self.usage_stats.should_reset_daily():
            logger.info("daily_stats_reset")
            self.usage_stats.reset_daily_stats()

        # Check cost limits BEFORE calling LLM
        self._check_cost_limits()

        # Build extraction prompt
        prompt = self._build_extraction_prompt(
            markdown_content, targets, paper_metadata
        )

        logger.info(
            "extraction_started",
            paper_id=paper_metadata.paper_id,
            targets=len(targets),
            provider=self.config.provider,
        )

        provider_errors: dict[str, str] = {}

        # Try primary provider
        try:
            return await self._extract_with_provider(
                provider=self.config.provider,
                client=self.client,
                prompt=prompt,
                targets=targets,
                paper_metadata=paper_metadata,
            )
        except (LLMAPIError, ProviderUnavailableError) as e:
            provider_errors[self.config.provider] = str(e)
            logger.warning(
                "primary_provider_failed",
                provider=self.config.provider,
                error=str(e),
            )

        # Try fallback provider if configured
        if self.fallback_client and self.fallback_provider:
            logger.info(
                "attempting_fallback",
                fallback_provider=self.fallback_provider,
            )
            self.usage_stats.total_fallback_activations += 1

            try:
                return await self._extract_with_provider(
                    provider=self.fallback_provider,
                    client=self.fallback_client,
                    prompt=prompt,
                    targets=targets,
                    paper_metadata=paper_metadata,
                    is_fallback=True,
                )
            except (LLMAPIError, ProviderUnavailableError) as e:
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
        provider: str,
        client: Any,
        prompt: str,
        targets: List[ExtractionTarget],
        paper_metadata: PaperMetadata,
        is_fallback: bool = False,
    ) -> PaperExtraction:
        """Extract using a specific provider with retry logic."""
        health = self.provider_health.get(provider)
        if health and health.circuit_breaker:
            health.circuit_breaker.check_or_raise()

        start_time = time.time()
        retry_attempts = 0

        try:
            # Use retry handler for the API call
            async def call_anthropic() -> Any:
                return await self._call_anthropic_raw(client, prompt)

            async def call_google() -> Any:
                return await self._call_google_raw(client, prompt)

            call_func = call_anthropic if provider == "anthropic" else call_google

            def on_retry(attempt: int, error: Exception, delay: float) -> None:
                nonlocal retry_attempts
                retry_attempts = attempt
                self.usage_stats.total_retry_attempts += 1
                logger.warning(
                    "llm_retry_attempt",
                    provider=provider,
                    attempt=attempt,
                    error=str(error),
                    delay=delay,
                )

            response = await self.retry_handler.execute(
                call_func,
                retryable_exceptions={RetryableError, RateLimitError},
                on_retry=on_retry,
            )

            # Calculate tokens and cost
            if provider == "anthropic":
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                tokens_used = input_tokens + output_tokens
                cost = self._calculate_cost_anthropic(response.usage)
                LLM_TOKENS_TOTAL.labels(provider="anthropic", type="input").inc(
                    input_tokens
                )
                LLM_TOKENS_TOTAL.labels(provider="anthropic", type="output").inc(
                    output_tokens
                )
            else:
                # New google-genai SDK: usage_metadata has token counts
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    tokens_used = getattr(usage, "total_token_count", 0)
                else:
                    tokens_used = 0
                cost = self._calculate_cost_google(tokens_used)
                LLM_TOKENS_TOTAL.labels(provider="google", type="total").inc(
                    tokens_used
                )

            # Record metrics
            duration = time.time() - start_time
            LLM_REQUEST_DURATION.labels(provider=provider).observe(duration)
            LLM_COST_USD_TOTAL.labels(provider=provider).inc(cost)
            DAILY_COST_USD.labels(provider=provider).set(
                self.usage_stats.total_cost_usd + cost
            )
            LLM_REQUESTS_TOTAL.labels(provider=provider, status="success").inc()

            # Update health tracking
            if health:
                health.record_success()
                if health.circuit_breaker:
                    health.circuit_breaker.record_success()

            # Parse response - pass provider for correct format handling
            results = self._parse_response(response, targets, provider)

            for result in results:
                if result.success and result.confidence is not None:
                    EXTRACTION_CONFIDENCE.observe(result.confidence)

            # Update usage stats
            self._update_usage(tokens_used, cost)

            # Update provider-specific stats
            if provider not in self.usage_stats.by_provider:
                self.usage_stats.by_provider[provider] = ProviderUsageStats(
                    provider=provider
                )
            self.usage_stats.by_provider[provider].record_success(
                tokens=tokens_used,
                cost=cost,
                was_retry=retry_attempts > 0,
            )
            if is_fallback:
                self.usage_stats.by_provider[provider].fallback_requests += 1

            logger.info(
                "extraction_completed",
                paper_id=paper_metadata.paper_id,
                provider=provider,
                tokens_used=tokens_used,
                cost_usd=cost,
                retry_attempts=retry_attempts,
                is_fallback=is_fallback,
                successful_extractions=sum(1 for r in results if r.success),
            )

            return PaperExtraction(
                paper_id=paper_metadata.paper_id,
                extraction_results=results,
                tokens_used=tokens_used,
                cost_usd=cost,
                extraction_timestamp=datetime.utcnow(),
            )

        except JSONParseError:
            # JSONParseError is not a provider issue - let it propagate
            # Both providers would likely return similar unparseable responses
            raise

        except Exception as e:
            # Update health tracking on failure
            if health:
                health.record_failure(str(e))
                if health.circuit_breaker:
                    health.circuit_breaker.record_failure()

            # Update provider-specific stats
            if provider not in self.usage_stats.by_provider:
                self.usage_stats.by_provider[provider] = ProviderUsageStats(
                    provider=provider
                )
            self.usage_stats.by_provider[provider].record_failure()

            LLM_REQUESTS_TOTAL.labels(provider=provider, status="failed").inc()
            EXTRACTION_ERRORS.labels(error_type="llm").inc()

            logger.error(
                "llm_api_call_failed",
                paper_id=paper_metadata.paper_id,
                provider=provider,
                retry_attempts=retry_attempts,
                error=str(e),
            )
            raise LLMAPIError(f"{provider}: {e}")

    async def _call_anthropic_raw(self, client: Any, prompt: str) -> Any:
        """Raw API call to Anthropic without retry wrapper."""
        try:
            response = await client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return response
        except Exception as e:
            classified = self._classify_error(e)
            raise classified

    async def _call_google_raw(self, client: Any, prompt: str) -> Any:
        """Raw API call to Google without retry wrapper."""
        try:
            # Determine model name based on whether this is primary or fallback
            model_name = getattr(self, "_google_model", None)
            if client == self.fallback_client:
                model_name = getattr(self, "_fallback_google_model", model_name)
            if not model_name:
                model_name = self.config.model

            from google.genai import types

            response = await client.aio.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=self.config.temperature,
                    max_output_tokens=self.config.max_tokens,
                ),
            )
            return response
        except Exception as e:
            classified = self._classify_error(e)
            raise classified

    def _classify_error(self, error: Exception) -> Exception:
        """Classify an error as retryable or not."""
        error_str = str(error).lower()

        if self._is_rate_limit_error(error_str):
            retry_after = self._extract_retry_after(error)
            return RateLimitError(str(error), retry_after=retry_after)

        if any(pattern in error_str for pattern in self.RETRYABLE_PATTERNS):
            return RetryableError(str(error))

        return LLMAPIError(str(error))

    def _is_rate_limit_error(self, error_str: str) -> bool:
        """Check if error is a rate limit error."""
        return any(pattern in error_str for pattern in self.RATE_LIMIT_PATTERNS)

    def _extract_retry_after(self, error: Exception) -> Optional[float]:
        """Try to extract retry-after value from error."""
        # Try common attribute patterns
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

    def _build_extraction_prompt(
        self, markdown: str, targets: List[ExtractionTarget], metadata: PaperMetadata
    ) -> str:
        """Build structured extraction prompt for LLM."""
        targets_json = [
            {
                "name": t.name,
                "description": t.description,
                "output_format": t.output_format,
                "required": t.required,
                "examples": t.examples,
            }
            for t in targets
        ]

        author_names = ", ".join(a.name for a in (metadata.authors or []))

        prompt = f"""You are a research paper analyst specialized in
extracting structured information from academic papers.

**Paper Metadata:**
- Title: {metadata.title}
- Authors: {author_names or 'Unknown'}
- Year: {metadata.year or 'Unknown'}
- Paper ID: {metadata.paper_id}

**Extraction Targets:**
{json.dumps(targets_json, indent=2)}

**Instructions:**
1. Read the paper content carefully
2. For each extraction target, extract the requested information
3. Follow the specified output_format for each target (text, code, json, list)
4. If a target cannot be found and is NOT required, return null for content
5. If a target is required and not found, set success=false with an error message
6. Provide a confidence score (0.0-1.0) for each extraction
7. Return ONLY valid JSON with NO additional text before or after

**Required JSON Structure:**
{{
  "extractions": [
    {{
      "target_name": "string",
      "success": boolean,
      "content": any,
      "confidence": float,
      "error": "string or null"
    }}
  ]
}}

**Paper Content:**

{markdown}

**Now extract the information and return ONLY the JSON response:**"""

        return prompt

    def _parse_response(
        self,
        response: Any,
        targets: List[ExtractionTarget],
        provider: Optional[str] = None,
    ) -> List[ExtractionResult]:
        """Parse LLM response into structured results."""
        # Use provided provider or fall back to config provider
        actual_provider = provider or self.config.provider
        if actual_provider == "anthropic":
            content = response.content[0].text
        else:
            content = response.text

        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise JSONParseError(
                f"Invalid JSON in LLM response: {e}\nContent: {content[:500]}"
            )

        if "extractions" not in data:
            raise JSONParseError("Missing 'extractions' key in response")

        extractions = data["extractions"]
        if not isinstance(extractions, list):
            raise JSONParseError("'extractions' must be a list")

        results = []
        target_names = {t.name for t in targets}

        for ext in extractions:
            if "target_name" not in ext:
                logger.warning("extraction_missing_target_name", extraction=ext)
                continue

            target_name = ext["target_name"]
            if target_name not in target_names:
                logger.warning("extraction_unknown_target", target_name=target_name)
                continue

            results.append(
                ExtractionResult(
                    target_name=target_name,
                    success=ext.get("success", True),
                    content=ext.get("content"),
                    confidence=ext.get("confidence", 0.0),
                    error=ext.get("error"),
                )
            )

        extracted_names = {r.target_name for r in results}
        for target in targets:
            if target.required and target.name not in extracted_names:
                logger.error("required_target_missing", target_name=target.name)
                results.append(
                    ExtractionResult(
                        target_name=target.name,
                        success=False,
                        content=None,
                        confidence=0.0,
                        error="Required target not found in LLM response",
                    )
                )

        return results

    def _calculate_cost_anthropic(self, usage: Any) -> float:
        """Calculate cost for Anthropic Claude."""
        input_cost: float = (
            usage.input_tokens / 1_000_000
        ) * self.CLAUDE_INPUT_COST_PER_MTOK
        output_cost: float = (
            usage.output_tokens / 1_000_000
        ) * self.CLAUDE_OUTPUT_COST_PER_MTOK
        return input_cost + output_cost

    def _calculate_cost_google(self, total_tokens: int) -> float:
        """Calculate cost for Google Gemini."""
        avg_cost_per_mtok = (
            self.GEMINI_INPUT_COST_PER_MTOK + self.GEMINI_OUTPUT_COST_PER_MTOK
        ) / 2
        return (total_tokens / 1_000_000) * avg_cost_per_mtok

    def _check_cost_limits(self) -> None:
        """Check if cost limits would be exceeded."""
        if self.usage_stats.total_cost_usd >= self.cost_limits.max_total_spend_usd:
            EXTRACTION_ERRORS.labels(error_type="cost_limit").inc()
            raise CostLimitExceeded(
                f"Total spending limit reached: "
                f"${self.usage_stats.total_cost_usd:.2f} >= "
                f"${self.cost_limits.max_total_spend_usd:.2f}"
            )

        if self.usage_stats.total_cost_usd >= self.cost_limits.max_daily_spend_usd:
            EXTRACTION_ERRORS.labels(error_type="cost_limit").inc()
            raise CostLimitExceeded(
                f"Daily spending limit reached: "
                f"${self.usage_stats.total_cost_usd:.2f} >= "
                f"${self.cost_limits.max_daily_spend_usd:.2f}"
            )

    def _update_usage(self, tokens: int, cost: float) -> None:
        """Update usage statistics."""
        self.usage_stats.total_tokens += tokens
        self.usage_stats.total_cost_usd += cost
        self.usage_stats.papers_processed += 1

        logger.debug(
            "usage_updated",
            total_tokens=self.usage_stats.total_tokens,
            total_cost_usd=self.usage_stats.total_cost_usd,
            papers_processed=self.usage_stats.papers_processed,
        )

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

    def get_provider_health(self) -> dict[str, dict]:
        """Get health status for all providers."""
        return {
            provider: health.get_stats()
            for provider, health in self.provider_health.items()
        }

    def reset_circuit_breakers(self) -> None:
        """Reset all circuit breakers to CLOSED state."""
        self.circuit_registry.reset_all()
        for health in self.provider_health.values():
            health.status = "healthy"
            health.consecutive_failures = 0

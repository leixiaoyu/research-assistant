# Phase 3.3: LLM Provider Fallback & Rate Limit Resilience
**Version:** 1.0
**Status:** 📋 Planning
**Timeline:** 1-2 weeks
**Dependencies:**
- Phase 2 Complete (LLM extraction service)
- Phase 3.1 Complete (Concurrent processing)
- At least one LLM API key available (Gemini or Claude)

---

## Architecture Reference

This phase extends the LLM service as defined in [SYSTEM_ARCHITECTURE.md §5.4 Extraction Service](../SYSTEM_ARCHITECTURE.md#core-components).

**Architectural Gaps Addressed:**
- ❌ Gap: No retry logic for transient LLM failures
- ❌ Gap: No fallback provider when primary LLM fails
- ❌ Gap: No rate limit detection and recovery (429 errors)
- ❌ Gap: Single provider dependency for extraction

**Components Modified:**
- LLM Service (`src/services/llm_service.py`)
- Exception Hierarchy (`src/utils/exceptions.py`)
- Configuration Models (`src/models/llm.py`, `src/models/config.py`)
- Extraction Service (`src/services/extraction_service.py`)

**Coverage Targets:**
- Retry logic: 100%
- Fallback scenarios: 100%
- Rate limit handling: 100%
- Cost tracking with retries: 100%

---

## 1. Executive Summary

Phase 3.3 adds **LLM provider resilience** to handle rate limits, transient failures, and provider outages through intelligent retry logic and automatic fallback to alternative providers.

**Key Achievement:** Transform from single-provider fragile LLM calls to resilient multi-provider system with automatic recovery.

**What This Phase Is:**
- ✅ Exponential backoff retry for transient failures
- ✅ Rate limit detection and intelligent waiting
- ✅ Automatic fallback to secondary LLM provider
- ✅ Circuit breaker pattern for repeated failures
- ✅ Per-provider cost tracking with retry accounting

**What This Phase Is NOT:**
- ❌ Adding new LLM providers (use existing Anthropic/Google)
- ❌ Changing extraction prompt format
- ❌ Modifying concurrent pipeline architecture

---

## 2. Problem Statement

### 2.1 Current State

**Working:**
- Anthropic Claude extraction functional
- Google Gemini extraction functional
- Cost tracking and limits enforced
- Concurrent processing with semaphore throttling

**Limitations:**
- **No retry logic:** Single failed API call fails the entire extraction
- **No rate limit handling:** 429 errors cause immediate failure
- **Single provider:** If configured provider fails, no fallback
- **Cost blindness:** Failed retries not tracked in cost accounting
- **Fragile pipeline:** One provider outage stops all extractions

### 2.2 Business Impact

**Current Problem (observed 2026-02-05):**
- Gemini free tier: 20 requests/day limit
- 72 papers found → all extractions failed after first 20
- No fallback to Claude when Gemini quota exhausted
- Daily automation produced empty research briefs

**With LLM Provider Fallback:**
- ✅ Automatic retry with backoff for transient errors
- ✅ Rate limit detection → wait or switch provider
- ✅ Gemini fails → automatic fallback to Claude
- ✅ Circuit breaker prevents cascading failures
- ✅ Accurate cost tracking including retry attempts

---

## 3. Requirements

### 3.1 Retry with Exponential Backoff

#### REQ-3.3.1: Transient Error Retry
The LLM service SHALL implement exponential backoff retry for transient errors.

**Scenario: Transient API Error**
**Given** an LLM API call fails with a retryable error (timeout, 5xx, connection error)
**When** retry attempts remain
**Then** the service SHALL:
- Wait with exponential backoff: `base_delay * (2 ^ attempt)` seconds
- Add random jitter (±10%) to prevent thundering herd
- Log retry attempt at WARNING level
- Retry the same provider
- Track retry costs in usage statistics

**Scenario: Max Retries Exceeded**
**Given** an LLM API call fails repeatedly
**When** max retry attempts (default: 3) are exhausted
**Then** the service SHALL:
- Log failure at ERROR level with all attempt details
- Trigger fallback provider if configured
- Raise `LLMAPIError` if no fallback available

#### REQ-3.3.2: Retry Configuration
The retry behavior SHALL be configurable per provider.

```yaml
llm_settings:
  provider: "google"
  retry:
    max_attempts: 3          # Total attempts (1 initial + 2 retries)
    base_delay_seconds: 1.0  # Initial backoff delay
    max_delay_seconds: 60.0  # Cap on backoff delay
    jitter_factor: 0.1       # ±10% randomization
    retryable_errors:        # Error types to retry
      - timeout
      - rate_limit
      - server_error
```

---

### 3.2 Rate Limit Detection & Recovery

#### REQ-3.3.3: Rate Limit Detection
The LLM service SHALL detect rate limit responses from all providers.

**Scenario: Rate Limit Response (429)**
**Given** an LLM API returns HTTP 429 or rate limit error
**When** the response includes retry-after information
**Then** the service SHALL:
- Parse `Retry-After` header or response body for wait time
- Log rate limit event at WARNING level
- Wait for the specified duration (or default: 60s)
- Retry the request if within retry budget
- Switch to fallback provider if wait time exceeds threshold

**Scenario: Quota Exhausted**
**Given** an LLM provider returns quota exhausted error
**When** the error indicates daily/monthly limit reached
**Then** the service SHALL:
- Log quota exhausted at ERROR level
- Mark provider as unavailable for configured cooldown period
- Immediately switch to fallback provider
- NOT retry the same provider

#### REQ-3.3.4: Rate Limit Thresholds
```yaml
llm_settings:
  rate_limit:
    max_wait_seconds: 120     # Max time to wait for rate limit
    quota_cooldown_hours: 24  # Cooldown after quota exhaustion
    switch_on_rate_limit: true # Auto-switch to fallback on rate limit
```

---

### 3.3 Provider Fallback

#### REQ-3.3.5: Fallback Provider Configuration
The system SHALL support configuring a fallback LLM provider.

```yaml
llm_settings:
  provider: "google"           # Primary provider
  model: "gemini-2.0-flash"
  api_key: "${LLM_API_KEY}"

  fallback:
    enabled: true
    provider: "anthropic"      # Fallback provider
    model: "claude-3-5-haiku-20250110"
    api_key: "${ANTHROPIC_API_KEY}"
```

#### REQ-3.3.6: Automatic Fallback Triggering
The LLM service SHALL automatically switch to fallback provider on specific conditions.

**Scenario: Primary Provider Failure**
**Given** the primary LLM provider fails after all retry attempts
**When** a fallback provider is configured and available
**Then** the service SHALL:
- Log provider switch at INFO level
- Initialize fallback provider if not already initialized
- Retry the extraction with fallback provider
- Track fallback usage in metrics
- NOT switch back mid-extraction

**Scenario: Fallback Also Fails**
**Given** both primary and fallback providers fail
**When** no more providers are available
**Then** the service SHALL:
- Log complete failure at ERROR level
- Raise `LLMAPIError` with details of all attempts
- Include provider chain in error message
- NOT block the pipeline (continue with other papers)

#### REQ-3.3.7: Provider Health Tracking
The service SHALL track provider health status.

```python
class ProviderHealth:
    provider: str
    status: Literal["healthy", "degraded", "unavailable"]
    consecutive_failures: int
    last_success: datetime
    last_failure: datetime
    failure_reason: Optional[str]
```

---

### 3.4 Circuit Breaker Pattern

#### REQ-3.3.8: Circuit Breaker Implementation
The LLM service SHALL implement circuit breaker pattern to prevent cascading failures.

**States:**
- **CLOSED:** Normal operation, requests pass through
- **OPEN:** Provider marked failed, requests immediately fail/fallback
- **HALF-OPEN:** Test requests allowed to probe recovery

**Scenario: Circuit Opens**
**Given** a provider experiences N consecutive failures (default: 5)
**When** the failure threshold is exceeded
**Then** the service SHALL:
- Open the circuit for that provider
- Log circuit open at WARNING level
- Redirect all requests to fallback provider
- Start cooldown timer

**Scenario: Circuit Half-Open**
**Given** a circuit has been open for the cooldown period
**When** a new request arrives
**Then** the service SHALL:
- Allow one test request through
- If successful: close circuit, restore normal operation
- If failed: reopen circuit, restart cooldown

#### REQ-3.3.9: Circuit Breaker Configuration
```yaml
llm_settings:
  circuit_breaker:
    enabled: true
    failure_threshold: 5        # Failures to open circuit
    success_threshold: 2        # Successes to close circuit
    cooldown_seconds: 300       # Time before half-open (5 min)
    half_open_max_requests: 3   # Max test requests in half-open
```

---

### 3.5 Cost Tracking Enhancements

#### REQ-3.3.10: Per-Provider Cost Tracking
The cost tracking system SHALL track usage per provider separately.

```python
class ProviderUsageStats:
    provider: str
    total_tokens: int
    total_cost_usd: float
    successful_requests: int
    failed_requests: int
    retry_requests: int
    fallback_requests: int
    last_request: datetime
```

#### REQ-3.3.11: Retry Cost Accounting
All retry attempts SHALL be included in cost calculations.

**Scenario: Retry with Partial Token Usage**
**Given** an LLM request fails after processing some tokens
**When** the failure occurs mid-response
**Then** the service SHALL:
- Estimate tokens used before failure
- Add estimated cost to usage statistics
- Include in daily/total spend calculations
- Log cost impact of failed request

---

### 3.6 Observability

#### REQ-3.3.12: Structured Logging
All retry, fallback, and circuit breaker events SHALL be logged with structured data.

```python
# Retry event
logger.warning("llm_retry_attempt",
    provider="google",
    attempt=2,
    max_attempts=3,
    error="timeout",
    delay_seconds=4.0)

# Fallback event
logger.info("llm_provider_fallback",
    from_provider="google",
    to_provider="anthropic",
    reason="rate_limit_exceeded")

# Circuit breaker event
logger.warning("llm_circuit_opened",
    provider="google",
    consecutive_failures=5,
    cooldown_seconds=300)
```

#### REQ-3.3.13: Metrics Collection
The service SHALL expose metrics for monitoring.

```python
class LLMMetrics:
    requests_total: Counter  # by provider, status
    retries_total: Counter   # by provider, reason
    fallbacks_total: Counter # by from_provider, to_provider
    circuit_state: Gauge     # by provider (0=closed, 1=open, 2=half-open)
    request_duration: Histogram  # by provider
```

---

## 4. Non-Functional Requirements

### 4.1 Performance
- Retry delay SHALL NOT exceed 60 seconds per attempt
- Total retry time SHALL NOT exceed 180 seconds per paper
- Circuit breaker state changes SHALL be O(1)
- No additional latency for healthy providers

### 4.2 Reliability
- Provider failure SHALL NOT crash the pipeline
- Cost tracking SHALL be accurate within 5%
- Circuit breaker state SHALL persist across requests (not restarts)

### 4.3 Backward Compatibility
- Existing config without `fallback` section SHALL work unchanged
- Existing config without `retry` section SHALL use sensible defaults
- No breaking changes to `LLMService` public interface

---

## 5. Out of Scope

- Adding new LLM providers beyond Anthropic/Google
- Changing extraction prompt engineering
- Load balancing across providers (always prefer primary)
- Persistent circuit breaker state across restarts
- Provider cost optimization (cheapest-first routing)

---

## 6. Success Criteria

### 6.1 Functional
- [ ] Retry logic handles transient failures with exponential backoff
- [ ] Rate limits trigger appropriate wait or provider switch
- [ ] Fallback provider activates when primary fails
- [ ] Circuit breaker prevents cascading failures
- [ ] Cost tracking includes all retry attempts

### 6.2 Quality Gates
- [ ] 100% test coverage for new code
- [ ] All existing tests pass (508+ tests)
- [ ] Mypy strict mode passes
- [ ] Black/Flake8 clean

### 6.3 Verification
- [ ] E2E test: Primary provider rate limited → successful fallback
- [ ] E2E test: Both providers fail → graceful degradation
- [ ] Load test: Circuit breaker opens under sustained failures
- [ ] Cost test: Retry costs accurately tracked

---

## 7. Technical Design Overview

### 7.1 Component Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    LLMService                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ RetryHandler │  │CircuitBreaker│  │ProviderPool  │  │
│  │              │  │              │  │              │  │
│  │ - backoff    │  │ - state      │  │ - primary    │  │
│  │ - jitter     │  │ - threshold  │  │ - fallback   │  │
│  │ - max_retry  │  │ - cooldown   │  │ - health     │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│                           │                             │
│  ┌────────────────────────┴────────────────────────┐   │
│  │              CostTracker (enhanced)              │   │
│  │  - per_provider_stats                           │   │
│  │  - retry_costs                                  │   │
│  │  - fallback_tracking                            │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 7.2 File Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `src/services/llm_service.py` | Modify | Add retry, fallback, circuit breaker |
| `src/models/llm.py` | Modify | Add retry/fallback config models |
| `src/models/config.py` | Modify | Add LLM retry settings to config |
| `src/utils/exceptions.py` | Modify | Add rate limit specific exceptions |
| `src/utils/retry.py` | New | Reusable retry handler with backoff |
| `src/utils/circuit_breaker.py` | New | Circuit breaker implementation |
| `tests/unit/test_llm_retry.py` | New | Retry logic tests |
| `tests/unit/test_circuit_breaker.py` | New | Circuit breaker tests |
| `tests/integration/test_llm_fallback.py` | New | E2E fallback tests |

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Retry amplifies costs | High | Track retry costs, enforce limits |
| Both providers fail simultaneously | Medium | Graceful degradation to abstract-only |
| Circuit breaker too aggressive | Medium | Configurable thresholds, manual reset |
| Race conditions in state | Low | Thread-safe state management |

---

## Appendix A: Error Classification

### Retryable Errors
- HTTP 429 (Rate Limit)
- HTTP 500, 502, 503, 504 (Server Errors)
- Connection timeout
- Network errors

### Non-Retryable Errors
- HTTP 400 (Bad Request) - prompt issue
- HTTP 401, 403 (Auth) - invalid API key
- HTTP 404 (Not Found) - invalid model
- JSON parse error - response format issue
- Content policy violation

---

## 9. Implementation Task Breakdown

This section provides a detailed task breakdown for implementation. Each task is designed to be atomic (1-3 files), independently testable, and includes guidance for AI-assisted implementation.

### Task Overview

| Task | Description | Files | Dependencies | Effort |
|------|-------------|-------|--------------|--------|
| 1 | Exception hierarchy for retry/fallback | 1 | None | S |
| 2 | Configuration models | 2 | Task 1 | S |
| 3 | Retry handler utility | 1 | Task 1 | M |
| 4 | Circuit breaker utility | 1 | Task 1 | M |
| 5 | Provider health tracker | 1 | Task 1, 4 | S |
| 6 | LLM service retry integration | 1 | Task 2, 3 | L |
| 7 | LLM service fallback integration | 1 | Task 2, 5, 6 | L |
| 8 | Cost tracking enhancements | 1 | Task 6, 7 | M |
| 9 | Unit tests for utilities | 2 | Task 3, 4 | M |
| 10 | Integration tests | 1 | Task 6, 7, 8 | M |
| 11 | Documentation update | 2 | All | S |

**Effort:** S = Small (1-2 hours), M = Medium (2-4 hours), L = Large (4-8 hours)

---

### Task 1: Exception Hierarchy Enhancement
**Status:** `[ ]` Pending

**Objective:** Add retry and rate-limit specific exceptions to the exception hierarchy.

**Files to Modify:**
- `src/utils/exceptions.py`

**Requirements Implemented:** REQ-3.3.1, REQ-3.3.3

**Changes:**
```python
# Add to src/utils/exceptions.py

class RetryableError(PipelineError):
    """Base class for errors that can be retried."""
    pass

class RateLimitError(RetryableError):
    """Rate limit exceeded - may include retry-after info."""
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after

class QuotaExhaustedError(LLMAPIError):
    """Daily/monthly quota exhausted - do not retry same provider."""
    pass

class ProviderUnavailableError(LLMAPIError):
    """Provider marked unavailable by circuit breaker."""
    pass

class AllProvidersFailedError(LLMAPIError):
    """All configured providers (primary + fallback) have failed."""
    def __init__(self, message: str, provider_errors: Dict[str, str]):
        super().__init__(message)
        self.provider_errors = provider_errors
```

**Tests:**
- Exception inheritance hierarchy correct
- Custom attributes accessible
- String representation includes details

**Acceptance Criteria:**
- [ ] All new exceptions inherit from appropriate base class
- [ ] RateLimitError stores retry_after value
- [ ] AllProvidersFailedError stores per-provider error details
- [ ] Existing tests pass unchanged

---

### Task 2: Configuration Models
**Status:** `[ ]` Pending

**Objective:** Add Pydantic models for retry, fallback, and circuit breaker configuration.

**Files to Modify:**
- `src/models/llm.py`
- `src/models/config.py`

**Requirements Implemented:** REQ-3.3.2, REQ-3.3.4, REQ-3.3.5, REQ-3.3.9

**Changes to `src/models/llm.py`:**
```python
class RetryConfig(BaseModel):
    """Configuration for retry behavior."""
    max_attempts: int = Field(default=3, ge=1, le=10)
    base_delay_seconds: float = Field(default=1.0, ge=0.1, le=30.0)
    max_delay_seconds: float = Field(default=60.0, ge=1.0, le=300.0)
    jitter_factor: float = Field(default=0.1, ge=0.0, le=0.5)

class CircuitBreakerConfig(BaseModel):
    """Configuration for circuit breaker."""
    enabled: bool = Field(default=True)
    failure_threshold: int = Field(default=5, ge=1, le=20)
    success_threshold: int = Field(default=2, ge=1, le=10)
    cooldown_seconds: float = Field(default=300.0, ge=30.0, le=3600.0)

class FallbackProviderConfig(BaseModel):
    """Configuration for fallback LLM provider."""
    enabled: bool = Field(default=False)
    provider: Literal["anthropic", "google"] = "anthropic"
    model: str = "claude-3-5-haiku-20250110"
    api_key: Optional[str] = Field(default=None, min_length=10)

class LLMConfig(BaseModel):
    """Enhanced LLM configuration with retry and fallback."""
    # Existing fields...
    provider: Literal["anthropic", "google"]
    model: str
    api_key: str
    max_tokens: int
    temperature: float
    timeout: int
    # New fields
    retry: RetryConfig = Field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    fallback: Optional[FallbackProviderConfig] = None
```

**Acceptance Criteria:**
- [ ] All config models have sensible defaults
- [ ] Validation ranges prevent invalid configurations
- [ ] Backward compatible (existing configs work without new fields)
- [ ] Config loads from YAML correctly

---

### Task 3: Retry Handler Utility
**Status:** `[ ]` Pending

**Objective:** Create a reusable async retry handler with exponential backoff.

**Files to Create:**
- `src/utils/retry.py`

**Requirements Implemented:** REQ-3.3.1, REQ-3.3.2

**Implementation:**
```python
# src/utils/retry.py
"""Async retry handler with exponential backoff and jitter."""

import asyncio
import random
from typing import TypeVar, Callable, Awaitable, Set, Type
from functools import wraps
import structlog

from src.models.llm import RetryConfig
from src.utils.exceptions import RetryableError, RateLimitError

logger = structlog.get_logger()
T = TypeVar("T")

class RetryHandler:
    """Handles retry logic with exponential backoff."""

    def __init__(self, config: RetryConfig):
        self.config = config

    def calculate_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculate delay with exponential backoff and jitter."""
        if retry_after:
            return min(retry_after, self.config.max_delay_seconds)

        base_delay = self.config.base_delay_seconds * (2 ** attempt)
        capped_delay = min(base_delay, self.config.max_delay_seconds)
        jitter = capped_delay * self.config.jitter_factor * random.uniform(-1, 1)
        return max(0.1, capped_delay + jitter)

    async def execute(
        self,
        func: Callable[[], Awaitable[T]],
        retryable_exceptions: Set[Type[Exception]] = None,
        on_retry: Optional[Callable[[int, Exception, float], None]] = None,
    ) -> T:
        """Execute function with retry logic."""
        retryable = retryable_exceptions or {RetryableError}
        last_exception = None

        for attempt in range(self.config.max_attempts):
            try:
                return await func()
            except tuple(retryable) as e:
                last_exception = e
                if attempt + 1 >= self.config.max_attempts:
                    break

                retry_after = getattr(e, 'retry_after', None)
                delay = self.calculate_delay(attempt, retry_after)

                logger.warning(
                    "retry_attempt",
                    attempt=attempt + 1,
                    max_attempts=self.config.max_attempts,
                    delay_seconds=delay,
                    error=str(e),
                )

                if on_retry:
                    on_retry(attempt + 1, e, delay)

                await asyncio.sleep(delay)

        raise last_exception
```

**Acceptance Criteria:**
- [ ] Exponential backoff calculated correctly
- [ ] Jitter applied within configured range
- [ ] Respects retry_after from RateLimitError
- [ ] Stops after max_attempts
- [ ] Logs each retry attempt
- [ ] Generic and reusable for any async function

---

### Task 4: Circuit Breaker Utility
**Status:** `[ ]` Pending

**Objective:** Implement circuit breaker pattern for provider health management.

**Files to Create:**
- `src/utils/circuit_breaker.py`

**Requirements Implemented:** REQ-3.3.8, REQ-3.3.9

**Implementation:**
```python
# src/utils/circuit_breaker.py
"""Circuit breaker pattern implementation."""

import asyncio
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
import structlog

from src.models.llm import CircuitBreakerConfig
from src.utils.exceptions import ProviderUnavailableError

logger = structlog.get_logger()

class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery

class CircuitBreaker:
    """Circuit breaker for LLM provider health management."""

    def __init__(self, name: str, config: CircuitBreakerConfig):
        self.name = name
        self.config = config
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._half_open_requests = 0

    @property
    def state(self) -> CircuitState:
        """Get current state, auto-transitioning if needed."""
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._transition_to(CircuitState.HALF_OPEN)
        return self._state

    def _should_attempt_reset(self) -> bool:
        """Check if cooldown period has passed."""
        if not self._last_failure_time:
            return True
        elapsed = datetime.now() - self._last_failure_time
        return elapsed >= timedelta(seconds=self.config.cooldown_seconds)

    def _transition_to(self, new_state: CircuitState):
        """Transition to new state with logging."""
        old_state = self._state
        self._state = new_state
        logger.info(
            "circuit_state_change",
            circuit=self.name,
            from_state=old_state.value,
            to_state=new_state.value,
        )
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_requests = 0
            self._success_count = 0

    def record_success(self):
        """Record successful request."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)
                self._failure_count = 0
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self):
        """Record failed request."""
        self._failure_count += 1
        self._last_failure_time = datetime.now()

        if self._state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)
                logger.warning(
                    "circuit_opened",
                    circuit=self.name,
                    failures=self._failure_count,
                    cooldown_seconds=self.config.cooldown_seconds,
                )

    def allow_request(self) -> bool:
        """Check if request should be allowed."""
        state = self.state  # Triggers auto-transition check
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.OPEN:
            return False
        # HALF_OPEN: allow limited test requests
        if self._half_open_requests < 3:
            self._half_open_requests += 1
            return True
        return False

    def check_or_raise(self):
        """Raise if circuit is open."""
        if not self.allow_request():
            raise ProviderUnavailableError(
                f"Circuit breaker open for {self.name}"
            )
```

**Acceptance Criteria:**
- [ ] Three states: CLOSED, OPEN, HALF_OPEN
- [ ] Opens after failure_threshold consecutive failures
- [ ] Transitions to HALF_OPEN after cooldown
- [ ] Closes after success_threshold successes in HALF_OPEN
- [ ] Thread-safe state management
- [ ] Logs all state transitions

---

### Task 5: Provider Health Tracker
**Status:** `[ ]` Pending

**Objective:** Create centralized provider health tracking.

**Files to Modify:**
- `src/services/llm_service.py` (add ProviderHealth class)

**Requirements Implemented:** REQ-3.3.7

**Implementation:**
```python
# Add to src/services/llm_service.py

@dataclass
class ProviderHealth:
    """Tracks health status of an LLM provider."""
    provider: str
    status: Literal["healthy", "degraded", "unavailable"] = "healthy"
    consecutive_failures: int = 0
    total_requests: int = 0
    total_failures: int = 0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    failure_reason: Optional[str] = None
    circuit_breaker: Optional[CircuitBreaker] = None

    def record_success(self):
        self.consecutive_failures = 0
        self.total_requests += 1
        self.last_success = datetime.now()
        self.status = "healthy"
        if self.circuit_breaker:
            self.circuit_breaker.record_success()

    def record_failure(self, reason: str):
        self.consecutive_failures += 1
        self.total_requests += 1
        self.total_failures += 1
        self.last_failure = datetime.now()
        self.failure_reason = reason
        self.status = "degraded" if self.consecutive_failures < 3 else "unavailable"
        if self.circuit_breaker:
            self.circuit_breaker.record_failure()
```

**Acceptance Criteria:**
- [ ] Tracks per-provider statistics
- [ ] Integrates with circuit breaker
- [ ] Status reflects recent health
- [ ] Accessible for monitoring/metrics

---

### Task 6: LLM Service Retry Integration
**Status:** `[ ]` Pending

**Objective:** Integrate retry handler into LLM service API calls.

**Files to Modify:**
- `src/services/llm_service.py`

**Requirements Implemented:** REQ-3.3.1, REQ-3.3.3, REQ-3.3.11

**Changes:**
1. Add RetryHandler as instance variable
2. Wrap `_call_anthropic` and `_call_google` with retry logic
3. Detect and convert rate limit responses to RateLimitError
4. Track retry costs in usage statistics

**Key Code Changes:**
```python
class LLMService:
    def __init__(self, config: LLMConfig, cost_limits: CostLimits):
        # ... existing init ...
        self._retry_handler = RetryHandler(config.retry)
        self._provider_health: Dict[str, ProviderHealth] = {}

    async def _call_with_retry(
        self,
        provider: str,
        call_func: Callable[[], Awaitable[str]],
    ) -> str:
        """Execute LLM call with retry logic."""

        async def wrapped():
            try:
                return await call_func()
            except Exception as e:
                # Convert provider-specific rate limits to RateLimitError
                if self._is_rate_limit_error(e):
                    retry_after = self._extract_retry_after(e)
                    raise RateLimitError(str(e), retry_after)
                if self._is_retryable_error(e):
                    raise RetryableError(str(e))
                raise

        return await self._retry_handler.execute(
            wrapped,
            retryable_exceptions={RetryableError, RateLimitError},
            on_retry=lambda attempt, err, delay: self._on_retry(provider, attempt, err, delay),
        )

    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if error is a rate limit response."""
        error_str = str(error).lower()
        return "429" in error_str or "rate limit" in error_str or "quota" in error_str

    def _extract_retry_after(self, error: Exception) -> Optional[float]:
        """Extract retry-after value from error if available."""
        # Parse from error message or response headers
        # Return None if not found
        pass
```

**Acceptance Criteria:**
- [ ] Retries on transient errors with backoff
- [ ] Rate limit errors trigger appropriate delay
- [ ] Quota errors marked as non-retryable
- [ ] Retry costs tracked in usage stats
- [ ] Provider health updated on success/failure
- [ ] All existing tests still pass

---

### Task 7: LLM Service Fallback Integration
**Status:** `[ ]` Pending

**Objective:** Add automatic fallback to secondary provider when primary fails.

**Files to Modify:**
- `src/services/llm_service.py`

**Requirements Implemented:** REQ-3.3.5, REQ-3.3.6, REQ-3.3.7

**Changes:**
1. Initialize fallback provider if configured
2. Implement provider switching logic
3. Track which provider was used for each extraction

**Key Code Changes:**
```python
class LLMService:
    def __init__(self, config: LLMConfig, cost_limits: CostLimits):
        # ... existing init ...
        self._primary_provider = config.provider
        self._fallback_config = config.fallback
        self._fallback_client = None

        if self._fallback_config and self._fallback_config.enabled:
            self._init_fallback_provider()

    async def extract(
        self,
        content: str,
        targets: List[ExtractionTarget],
        metadata: Optional[PaperMetadata] = None,
    ) -> ExtractionResult:
        """Extract with fallback support."""
        providers_tried = []
        last_error = None

        # Try primary provider
        try:
            providers_tried.append(self._primary_provider)
            return await self._extract_with_provider(
                self._primary_provider, content, targets, metadata
            )
        except (LLMAPIError, RetryableError) as e:
            last_error = e
            logger.warning(
                "primary_provider_failed",
                provider=self._primary_provider,
                error=str(e),
            )

        # Try fallback if available
        if self._fallback_config and self._fallback_config.enabled:
            try:
                fallback = self._fallback_config.provider
                providers_tried.append(fallback)
                logger.info(
                    "llm_provider_fallback",
                    from_provider=self._primary_provider,
                    to_provider=fallback,
                    reason=str(last_error),
                )
                return await self._extract_with_provider(
                    fallback, content, targets, metadata
                )
            except (LLMAPIError, RetryableError) as e:
                last_error = e

        # All providers failed
        raise AllProvidersFailedError(
            f"All LLM providers failed: {providers_tried}",
            provider_errors={p: str(last_error) for p in providers_tried},
        )
```

**Acceptance Criteria:**
- [ ] Fallback provider initialized if configured
- [ ] Automatic switch when primary fails after retries
- [ ] Fallback usage logged and tracked
- [ ] AllProvidersFailedError raised when both fail
- [ ] Extraction result includes which provider was used

---

### Task 8: Cost Tracking Enhancements
**Status:** `[ ]` Pending

**Objective:** Enhance cost tracking to support per-provider stats and retry accounting.

**Files to Modify:**
- `src/services/llm_service.py`
- `src/models/llm.py`

**Requirements Implemented:** REQ-3.3.10, REQ-3.3.11

**Changes:**
```python
# Add to src/models/llm.py

class ProviderUsageStats(BaseModel):
    """Usage statistics for a single provider."""
    provider: str
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    successful_requests: int = 0
    failed_requests: int = 0
    retry_requests: int = 0
    fallback_requests: int = 0

class EnhancedUsageStats(BaseModel):
    """Aggregate usage statistics with per-provider breakdown."""
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    papers_processed: int = 0
    last_reset: datetime = Field(default_factory=datetime.now)
    by_provider: Dict[str, ProviderUsageStats] = Field(default_factory=dict)
```

**Acceptance Criteria:**
- [ ] Per-provider token/cost tracking
- [ ] Retry attempts counted separately
- [ ] Fallback usage tracked
- [ ] Failed request costs estimated and included
- [ ] Stats accessible for reporting

---

### Task 9: Unit Tests for Utilities
**Status:** `[ ]` Pending

**Objective:** Comprehensive unit tests for retry handler and circuit breaker.

**Files to Create:**
- `tests/unit/test_utils/test_retry.py`
- `tests/unit/test_utils/test_circuit_breaker.py`

**Test Cases for Retry Handler:**
- `test_retry_succeeds_first_attempt`
- `test_retry_succeeds_after_failures`
- `test_retry_exhausts_attempts`
- `test_exponential_backoff_calculation`
- `test_jitter_within_bounds`
- `test_respects_retry_after`
- `test_non_retryable_error_not_retried`
- `test_on_retry_callback_called`

**Test Cases for Circuit Breaker:**
- `test_initial_state_closed`
- `test_opens_after_threshold_failures`
- `test_stays_open_during_cooldown`
- `test_transitions_to_half_open`
- `test_closes_after_success_threshold`
- `test_reopens_on_half_open_failure`
- `test_allows_limited_half_open_requests`

**Acceptance Criteria:**
- [ ] 100% coverage for retry.py
- [ ] 100% coverage for circuit_breaker.py
- [ ] Edge cases tested (zero delay, max delay, boundary conditions)
- [ ] Async behavior tested correctly

---

### Task 10: Integration Tests
**Status:** `[ ]` Pending

**Objective:** End-to-end tests for retry and fallback scenarios.

**Files to Create:**
- `tests/integration/test_llm_fallback.py`

**Test Scenarios:**
```python
class TestLLMFallback:
    """Integration tests for LLM provider fallback."""

    async def test_primary_succeeds_no_fallback(self):
        """Verify primary provider used when healthy."""
        pass

    async def test_retry_then_succeed(self):
        """Verify retry succeeds after transient failure."""
        pass

    async def test_primary_fails_fallback_succeeds(self):
        """Verify fallback activates when primary exhausts retries."""
        pass

    async def test_both_providers_fail_gracefully(self):
        """Verify AllProvidersFailedError raised when both fail."""
        pass

    async def test_rate_limit_triggers_wait(self):
        """Verify rate limit response triggers appropriate delay."""
        pass

    async def test_circuit_breaker_opens(self):
        """Verify circuit opens after repeated failures."""
        pass

    async def test_cost_tracking_includes_retries(self):
        """Verify retry attempts included in cost calculations."""
        pass
```

**Acceptance Criteria:**
- [ ] All scenarios pass with mocked providers
- [ ] Real provider test (optional, requires API key)
- [ ] Cost assertions accurate
- [ ] Timing assertions for backoff delays

---

### Task 11: Documentation Update
**Status:** `[ ]` Pending

**Objective:** Update user documentation and configuration guides.

**Files to Modify:**
- `docs/operations/DAILY_AUTOMATION_GUIDE.md`
- `README.md` (optional)
- `.env.template`

**Changes:**
1. Add fallback configuration examples
2. Document retry behavior
3. Add troubleshooting for rate limits
4. Update .env.template with ANTHROPIC_API_KEY

**Acceptance Criteria:**
- [ ] Configuration examples clear and complete
- [ ] Troubleshooting section for common errors
- [ ] .env.template includes all API keys

---

## 10. Implementation Order

```
Phase 1: Foundation (Tasks 1-2)
├── Task 1: Exception hierarchy
└── Task 2: Configuration models

Phase 2: Utilities (Tasks 3-5) [Can parallelize]
├── Task 3: Retry handler
├── Task 4: Circuit breaker
└── Task 5: Provider health tracker

Phase 3: Integration (Tasks 6-8) [Sequential]
├── Task 6: Retry integration
├── Task 7: Fallback integration
└── Task 8: Cost tracking

Phase 4: Verification (Tasks 9-11) [Can parallelize]
├── Task 9: Unit tests
├── Task 10: Integration tests
└── Task 11: Documentation
```

**Estimated Total Effort:** 3-5 days for experienced developer

---

## 11. AI Implementation Prompts

Each task includes a prompt template for AI-assisted implementation. Use these when implementing tasks in separate sessions.

### Example Prompt for Task 3:
```
Implement Task 3 (Retry Handler) for the LLM Provider Fallback feature (Phase 3.3).

Context:
- Spec: docs/specs/PHASE_3.3_LLM_FALLBACK_SPEC.md
- Target file: src/utils/retry.py (new file)
- Dependencies: Task 1 (exceptions) should be complete

Requirements:
- REQ-3.3.1: Exponential backoff with jitter
- REQ-3.3.2: Configurable via RetryConfig

Implementation notes:
- Use async/await throughout
- Generic handler usable for any async function
- Log retry attempts with structlog
- Respect retry_after from RateLimitError

After implementation:
1. Run: pytest tests/unit/test_utils/test_retry.py -v
2. Run: ./verify.sh
3. Mark task complete in spec if all tests pass
```

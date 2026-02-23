# Phase 5.1: LLMService Decomposition
**Version:** 1.0
**Status:** 📋 Planning
**Timeline:** 3-4 days
**Dependencies:**
- Phase 3.3 Complete (LLM Fallback & Resilience)
- All existing LLM tests passing

---

## Architecture Reference

This phase refactors the LLM service layer as defined in [SYSTEM_ARCHITECTURE.md §4 Service Layer](../SYSTEM_ARCHITECTURE.md#service-layer).

**Architectural Gaps Addressed:**
- ❌ Gap: Single 838-line file violates Single Responsibility Principle
- ❌ Gap: Provider-specific logic mixed with orchestration logic
- ❌ Gap: Cost tracking tightly coupled with extraction logic
- ❌ Gap: Difficult to add new LLM providers (e.g., OpenAI)

**Components Modified:**
- Service Layer: LLMService (src/services/llm_service.py) → New package
- Utils: New prompt and parsing utilities

**Coverage Targets:**
- All new modules: ≥99%
- Overall coverage: Maintain ≥99%

---

## 1. Executive Summary

Phase 5.1 decomposes the monolithic `LLMService` (838 lines, 26 functions) into a cohesive package of focused modules. The refactoring follows Single Responsibility Principle, separating concerns like provider abstraction, cost tracking, prompt building, and response parsing into independent, testable units.

**What This Phase Is:**
- ✅ Structural decomposition of LLMService into focused modules.
- ✅ Extraction of reusable utilities (cost calculation, prompt building).
- ✅ Clear provider abstraction for future extensibility.
- ✅ Maintained backward compatibility with existing callers.

**What This Phase Is NOT:**
- ❌ Adding new LLM providers (OpenAI, etc.).
- ❌ Changing extraction prompt logic or response parsing behavior.
- ❌ Modifying cost calculation formulas.
- ❌ Altering retry/fallback/circuit-breaker behavior.

**Key Achievement:** Transform 838-line monolith into 6-7 focused modules, each <150 lines.

---

## 2. Problem Statement

### 2.1 The God Class Problem
`LLMService` currently handles 10 distinct responsibilities:
1. Provider abstraction (Anthropic/Google)
2. Client initialization
3. Retry logic with exponential backoff
4. Circuit breaker integration
5. Provider fallback orchestration
6. Cost tracking and budget enforcement
7. Prompt building
8. Response parsing (JSON extraction)
9. Health monitoring
10. Metrics export

This violates the Single Responsibility Principle and makes the class difficult to test, understand, and extend.

### 2.2 The Extensibility Problem
Adding a new LLM provider (e.g., OpenAI GPT-4) would require modifying the core `LLMService` class in multiple places, increasing risk of regression.

### 2.3 The Testing Problem
Testing individual responsibilities requires mocking the entire 838-line class. Unit tests are tightly coupled to implementation details.

---

## 3. Requirements

### 3.1 Module Decomposition

#### REQ-5.1.1: Provider Abstraction
The system SHALL define an abstract `LLMProvider` interface.

**Required Methods:**
- `async extract(prompt: str, max_tokens: int) -> LLMResponse`
- `calculate_cost(input_tokens: int, output_tokens: int) -> float`
- `get_health() -> ProviderHealth`

#### REQ-5.1.2: Provider Implementations
Each LLM provider SHALL have a dedicated implementation class.
- `AnthropicProvider` for Claude models
- `GoogleProvider` for Gemini models

#### REQ-5.1.3: Cost Tracker Extraction
Cost tracking logic SHALL be extracted to a standalone `CostTracker` class.

**Responsibilities:**
- Track per-session usage (tokens, cost)
- Enforce daily and total spending limits
- Provide usage summaries
- Handle daily reset logic

#### REQ-5.1.4: Prompt Builder Extraction
Prompt construction logic SHALL be extracted to a `PromptBuilder` class.

**Responsibilities:**
- Build structured extraction prompts from targets
- Format paper metadata for context
- Generate JSON schema instructions

#### REQ-5.1.5: Response Parser Extraction
JSON response parsing SHALL be extracted to a `ResponseParser` class.

**Responsibilities:**
- Parse LLM JSON responses
- Validate against expected schema
- Handle malformed responses gracefully
- Calculate confidence scores

### 3.2 Backward Compatibility

#### REQ-5.1.6: API Preservation
The refactored `LLMService` SHALL maintain its existing public API.

**Preserved Methods:**
- `async extract(paper, markdown_content, targets, run_id) -> PaperExtraction`
- `get_usage_summary() -> dict`
- `get_provider_health() -> dict`
- `reset_circuit_breakers() -> None`

#### REQ-5.1.7: Import Compatibility
Existing imports SHALL continue to work.

```python
# This MUST continue to work:
from src.services.llm_service import LLMService
```

### 3.3 Package Structure

#### REQ-5.1.8: Module Organization
The LLM service SHALL be organized as a package.

```
src/services/llm/
├── __init__.py           # Re-export LLMService for backward compat
├── service.py            # Main LLMService (orchestrator, <200 lines)
├── providers/
│   ├── __init__.py
│   ├── base.py           # Abstract LLMProvider
│   ├── anthropic.py      # AnthropicProvider
│   └── google.py         # GoogleProvider
├── cost_tracker.py       # CostTracker class
├── prompt_builder.py     # PromptBuilder class
├── response_parser.py    # ResponseParser class
└── health.py             # ProviderHealth dataclass (moved)
```

---

## 4. Technical Design

### 4.1 Abstract Provider Interface

```python
# src/services/llm/providers/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: float

class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'anthropic', 'google')."""
        pass

    @abstractmethod
    async def extract(
        self,
        prompt: str,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Execute extraction and return standardized response."""
        pass

    @abstractmethod
    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Calculate cost in USD for token usage."""
        pass
```

### 4.2 Cost Tracker Design

```python
# src/services/llm/cost_tracker.py
class CostTracker:
    """Tracks LLM usage and enforces budget limits."""

    def __init__(self, limits: CostLimits):
        self._limits = limits
        self._daily_tokens = 0
        self._daily_cost = 0.0
        self._total_tokens = 0
        self._total_cost = 0.0
        self._last_reset_date: Optional[date] = None

    def record_usage(self, tokens: int, cost: float) -> None:
        """Record token usage and cost."""
        self._check_daily_reset()
        self._daily_tokens += tokens
        self._daily_cost += cost
        self._total_tokens += tokens
        self._total_cost += cost
        self._update_metrics(tokens, cost)

    def check_limits(self) -> None:
        """Raise CostLimitExceeded if limits breached."""
        self._check_daily_reset()
        if self._daily_cost > self._limits.max_daily_spend_usd:
            raise CostLimitExceeded("daily", self._daily_cost)
        if self._total_cost > self._limits.max_total_spend_usd:
            raise CostLimitExceeded("total", self._total_cost)

    def get_summary(self) -> dict:
        """Return usage summary."""
        return {
            "daily_tokens": self._daily_tokens,
            "daily_cost_usd": self._daily_cost,
            "total_tokens": self._total_tokens,
            "total_cost_usd": self._total_cost,
        }
```

### 4.3 Refactored LLMService

```python
# src/services/llm/service.py
class LLMService:
    """Orchestrates LLM extraction with fallback and resilience.

    This is a thin orchestrator that delegates to:
    - LLMProvider implementations (Anthropic, Google)
    - CostTracker for budget enforcement
    - PromptBuilder for prompt construction
    - ResponseParser for JSON parsing
    - RetryHandler for retry logic
    - CircuitBreaker for failure isolation
    """

    def __init__(self, config: LLMConfig, cost_limits: CostLimits):
        self._config = config
        self._cost_tracker = CostTracker(cost_limits)
        self._prompt_builder = PromptBuilder()
        self._response_parser = ResponseParser()
        self._providers: Dict[str, LLMProvider] = {}
        self._health: Dict[str, ProviderHealth] = {}
        self._init_providers()

    async def extract(
        self,
        paper: PaperMetadata,
        markdown_content: str,
        targets: List[ExtractionTarget],
        run_id: str,
    ) -> PaperExtraction:
        """Extract information from paper using LLM."""
        # 1. Check cost limits
        self._cost_tracker.check_limits()

        # 2. Build prompt
        prompt = self._prompt_builder.build(paper, markdown_content, targets)

        # 3. Execute with fallback
        response = await self._extract_with_fallback(prompt)

        # 4. Parse response
        results = self._response_parser.parse(response.content, targets)

        # 5. Record usage
        cost = self._providers[response.provider].calculate_cost(
            response.input_tokens, response.output_tokens
        )
        self._cost_tracker.record_usage(
            response.input_tokens + response.output_tokens, cost
        )

        return PaperExtraction(
            paper_id=paper.paper_id,
            results=results,
            tokens_used=response.input_tokens + response.output_tokens,
            cost_usd=cost,
            model=response.model,
        )
```

---

## 5. Security Requirements (MANDATORY) 🔒

### SR-5.1.1: API Key Handling
- [ ] API keys MUST NOT be stored in any new module.
- [ ] API keys MUST be passed from environment only.
- [ ] API keys MUST NOT appear in logs or error messages.

### SR-5.1.2: Cost Tracker Security
- [ ] Cost limits enforced before any API call.
- [ ] No bypass mechanism for cost limits.
- [ ] Daily reset logic cannot be manipulated externally.

### SR-5.1.3: Input Validation
- [ ] PromptBuilder validates paper metadata before inclusion.
- [ ] ResponseParser validates JSON structure before processing.
- [ ] All user-provided content sanitized in prompts.

### SR-5.1.4: Error Handling
- [ ] Provider errors do not leak API keys or internal details.
- [ ] Parsing errors do not expose raw LLM responses in logs.
- [ ] All exceptions properly typed and documented.

---

## 6. Implementation Tasks

### Task 1: Create Package Structure (0.5 day)
**Files:** src/services/llm/__init__.py, src/services/llm/providers/__init__.py

1. Create directory structure.
2. Set up __init__.py files with proper exports.
3. Ensure `from src.services.llm_service import LLMService` still works.

### Task 2: Extract Provider Abstraction (1 day)
**Files:** src/services/llm/providers/base.py, anthropic.py, google.py

1. Define `LLMProvider` abstract base class.
2. Extract `AnthropicProvider` from existing code (lines 418-554, 556-569, 761-770).
3. Extract `GoogleProvider` from existing code (lines 421-425, 570-594, 771-777).
4. Add comprehensive tests for each provider.

### Task 3: Extract Cost Tracker (0.5 day)
**Files:** src/services/llm/cost_tracker.py

1. Extract cost tracking logic (lines 778-808).
2. Extract daily reset logic.
3. Extract metrics updates.
4. Add unit tests for all cost scenarios.

### Task 4: Extract Prompt Builder (0.5 day)
**Files:** src/services/llm/prompt_builder.py

1. Extract prompt building logic (lines 626-684).
2. Ensure identical prompt output.
3. Add unit tests for prompt formatting.

### Task 5: Extract Response Parser (0.5 day)
**Files:** src/services/llm/response_parser.py

1. Extract JSON parsing logic (lines 685-760).
2. Extract confidence calculation.
3. Add unit tests for valid/invalid responses.

### Task 6: Refactor LLMService (1 day)
**Files:** src/services/llm/service.py

1. Refactor main class to use new components.
2. Maintain all existing public methods.
3. Update all existing tests to work with refactored code.
4. Verify all integration tests pass.

### Task 7: Backward Compatibility (0.5 day)
**Files:** src/services/llm_service.py (legacy), src/services/llm/__init__.py

1. Create `src/services/llm_service.py` that re-exports from package.
2. Add deprecation warning for direct imports.
3. Verify all existing callers work unchanged.

---

## 7. Verification Criteria

### 7.1 Unit Tests (New)
- `test_anthropic_provider_extract`: Test Claude API call and response parsing.
- `test_google_provider_extract`: Test Gemini API call and response parsing.
- `test_cost_tracker_daily_limit`: Verify daily limit enforcement.
- `test_cost_tracker_total_limit`: Verify total limit enforcement.
- `test_cost_tracker_daily_reset`: Verify reset at midnight.
- `test_prompt_builder_format`: Verify prompt structure matches original.
- `test_response_parser_valid_json`: Parse well-formed responses.
- `test_response_parser_invalid_json`: Handle malformed responses gracefully.

### 7.2 Regression Tests
- All 1,468 existing tests MUST pass unchanged.
- Coverage MUST remain ≥99%.

### 7.3 Integration Tests
- `test_llm_service_backward_compat`: Verify existing callers work.
- `test_provider_fallback_still_works`: Verify fallback logic preserved.
- `test_circuit_breaker_still_works`: Verify circuit breaker preserved.

### 7.4 Security Verification
- [ ] Verify no API keys in new module files.
- [ ] Verify error messages don't leak sensitive data.
- [ ] Verify cost limits cannot be bypassed.

---

## 8. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Breaking extraction behavior | High | Low | Exact same logic, comprehensive tests |
| Import errors | Medium | Low | Backward-compat re-exports |
| Cost tracking drift | Medium | Low | Identical formulas, verify with live test |
| Circular imports | Medium | Medium | Careful dependency ordering |

---

## 9. Rollback Plan

If critical issues are discovered post-merge:
1. Revert the PR entirely (single commit revert).
2. Original `llm_service.py` is preserved in git history.
3. No data migration required—purely code structure change.

---

## 10. File Size Targets

| File | Current | Target |
|------|---------|--------|
| llm_service.py | 838 lines | Deprecated (re-export only) |
| llm/service.py | N/A | <200 lines |
| llm/providers/anthropic.py | N/A | <150 lines |
| llm/providers/google.py | N/A | <150 lines |
| llm/cost_tracker.py | N/A | <100 lines |
| llm/prompt_builder.py | N/A | <100 lines |
| llm/response_parser.py | N/A | <120 lines |

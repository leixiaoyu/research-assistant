# Codebase Refactoring Opportunities

**Generated:** 2026-02-22
**Last Updated:** 2026-03-20
**Codebase Size:** ~19,000+ lines of Python code
**Classes:** 160+ classes across 95+ source files
**Test Coverage:** 99.03% (2,470 tests)

---

## Executive Summary

The codebase has grown significantly with the addition of Phase 2 (PDF/LLM extraction), Phase 3 (concurrent processing, synthesis), Phase 4 (observability), and Phase 5 (architectural refactoring). Test coverage remains excellent (99.03%), and multiple refactoring phases have been completed.

**Completed Phases:**
- ✅ **Phase R1**: Config model decomposition (`config.py` → 6 modules)
- ✅ **Phase R2**: LLM Service decomposition (`error_classifier.py`, `provider_manager.py`)
- ✅ **Phase R3**: Pipeline decomposition (`paper_processor.py`)
- ✅ **Phase R4.1**: Cross-synthesis service decomposition (`synthesis/` package)
- ✅ **Phase 5.1**: LLMService decomposition to `llm/` package
- ✅ **Phase 5.2**: ResearchPipeline phase-based architecture

**Remaining Priority Areas:**
1. **High Priority**: Discovery service decomposition (831 lines) - *Phase R4.2*
2. **High Priority**: Notification service refactor (627 lines) - *Phase R4.4*
3. **Medium Priority**: Registry service split (622 lines) - *Phase R4.3*
4. **Medium Priority**: CLI package split (474+ lines) - *Phase R5.1*
5. **Medium Priority**: Output generator consolidation - *Phase R5.2*
6. **Lower Priority**: Provider pattern improvements - *Phase R5.3*
7. **Lower Priority**: Dependency injection adoption - *Phase R6*

---

## Completed Refactoring

### Phase R1: Config Model Decomposition ✅

**Original File:** `src/models/config.py` (570 lines, 22 classes)
**Status:** Decomposed to `src/models/config/` package (Mar 2026)

**Result:**
```
src/models/config/
├── __init__.py      # Re-exports all 22 classes
├── core.py          # ~100 lines - Core research config
├── discovery.py     # ~100 lines - Discovery settings
├── extraction.py    # ~100 lines - Extraction settings
├── phase7.py        # ~100 lines - Phase 7 settings
└── settings.py      # ~100 lines - Global settings
```

**Benefits Achieved:**
- Each module ~100 lines (down from 570)
- Single Responsibility per module
- Full backward compatibility maintained

---

### Phase R2: LLM Service Decomposition ✅

**Original File:** `src/services/llm/service.py` (1,022 lines)
**Status:** Partially decomposed (Mar 2026)

**Result:**
```
src/services/llm/
├── service.py           # 906 lines (reduced from 1,022)
├── error_classifier.py  # 180 lines - Error classification
└── provider_manager.py  # 227 lines - Provider lifecycle
```

**Benefits Achieved:**
- Error classification logic isolated and testable
- Provider management separated with circuit breaker support
- Clear responsibility boundaries

---

### Phase R3: Pipeline Decomposition ✅

**Original File:** `src/orchestration/concurrent_pipeline.py` (745 lines)
**Status:** Decomposed (Mar 2026)

**Result:**
```
src/orchestration/
├── concurrent_pipeline.py  # 632 lines (reduced from 745)
└── paper_processor.py      # 248 lines - Single paper processing
```

**Benefits Achieved:**
- Paper processing logic isolated
- Cache checking, PDF extraction, LLM extraction separated
- Easier to test individual processing steps

---

### Phase R4.1: Cross-Synthesis Service Decomposition ✅

**Original File:** `src/services/cross_synthesis_service.py` (731 lines)
**Status:** Fully decomposed to `synthesis/` package (Mar 2026)

**Result:**
```
src/services/synthesis/
├── __init__.py            # 39 lines - Package exports
├── cross_synthesis.py     # 367 lines - Main orchestration
├── paper_selector.py      # 237 lines - Quality-weighted selection
├── answer_synthesizer.py  # 235 lines - LLM synthesis
├── state_manager.py       # 160 lines - Config & state
└── prompt_builder.py      # 110 lines - Template prompts

src/services/cross_synthesis_service.py  # 35 lines - Backward compat wrapper
```

**Benefits Achieved:**
- 731 lines → 35 line wrapper + 5 focused modules
- Each module <250 lines with single responsibility
- 100% test coverage on all new modules
- Full backward compatibility via re-exports

---

## Remaining Refactoring Opportunities

### Phase R4.2: Discovery Service Decomposition (HIGH PRIORITY)

**File:** `src/services/discovery_service.py` (831 lines)

**Current Responsibilities:**
- Semantic Scholar API integration
- arXiv API integration
- Query building with timeframes
- Rate limiting and retry logic
- Result normalization
- Provider health tracking

**Proposed Decomposition:**
```
src/services/discovery/
├── __init__.py           # Re-export public API
├── discovery_service.py  # ~200 lines - Orchestrator
├── semantic_scholar.py   # ~200 lines - SS provider
├── arxiv_provider.py     # ~200 lines - arXiv provider
├── query_builder.py      # ~100 lines - Query construction
├── result_normalizer.py  # ~100 lines - Result normalization
└── rate_limiter.py       # ~100 lines - Shared rate limiting
```

**Benefits:**
- Clear provider separation
- Independent provider testing
- Easy to add new discovery sources (OpenAlex, etc.)
- Reusable rate limiting

---

### Phase R4.3: Registry Service Split (MEDIUM PRIORITY)

**File:** `src/services/registry_service.py` (622 lines)

**Current Responsibilities:**
- Paper registration
- Metadata snapshots
- Deduplication logic
- State persistence (JSON I/O)
- Query operations

**Proposed Decomposition:**
```
src/services/registry/
├── __init__.py           # Re-export public API
├── registry_service.py   # ~200 lines - Orchestrator
├── paper_registry.py     # ~150 lines - Core registration
├── persistence.py        # ~150 lines - JSON file I/O
└── queries.py            # ~100 lines - Search/filter operations
```

**Benefits:**
- Separated persistence logic
- Independent query testing
- Cleaner deduplication implementation

---

### Phase R4.4: Notification Service Refactor (HIGH PRIORITY)

**File:** `src/services/notification_service.py` (627 lines)

**Current Responsibilities:**
- Email notifications
- Slack notifications
- Discord notifications
- Template rendering
- Message formatting
- Delivery tracking

**Proposed Decomposition:**
```
src/services/notifications/
├── __init__.py           # Re-export public API
├── service.py            # ~150 lines - Orchestrator
├── providers/
│   ├── email.py          # ~100 lines - Email provider
│   ├── slack.py          # ~100 lines - Slack provider
│   └── discord.py        # ~100 lines - Discord provider
├── templates.py          # ~100 lines - Template rendering
└── tracking.py           # ~80 lines - Delivery tracking
```

**Benefits:**
- Provider pattern consistency
- Easy to add new notification channels
- Independent template testing
- Separated delivery tracking

---

### Phase R5.1: CLI Package Split (MEDIUM PRIORITY)

**File:** `src/orchestration/pipeline.py` (474 lines) + CLI commands scattered

**Current State:**
- Main pipeline orchestration in single file
- CLI commands mixed with business logic
- Validation logic embedded in commands

**Proposed Decomposition:**
```
src/cli/
├── __init__.py           # Main Typer app
├── run.py                # run command
├── schedule.py           # schedule command
├── catalog.py            # catalog commands
├── synthesize.py         # synthesize command
├── health.py             # health command
└── utils.py              # Shared CLI utilities
```

**Benefits:**
- Each command module <150 lines
- Easier command-specific testing
- Clearer command organization
- Simpler addition of new commands

---

### Phase R5.2: Output Generator Consolidation (MEDIUM PRIORITY)

**Current State:**
- `src/output/cross_synthesis_generator.py` (534 lines)
- Similar markdown generation patterns across generators
- YAML frontmatter duplication

**Proposed Consolidation:**
```
src/output/
├── __init__.py
├── base.py               # Abstract generator interface
├── markdown_builder.py   # Shared markdown utilities
├── frontmatter.py        # YAML frontmatter helper
├── generators/
│   ├── research.py       # Research output
│   ├── synthesis.py      # Synthesis output
│   └── cross_topic.py    # Cross-topic output
└── formatters/
    ├── paper.py          # Paper formatting
    └── summary.py        # Summary formatting
```

**Benefits:**
- DRY markdown generation
- Consistent output formatting
- Easier template customization

---

### Phase R5.3: Provider Pattern Improvements (LOWER PRIORITY)

**Current State:**
Multiple services implement provider patterns differently:
- `LLMService` - Anthropic/Google providers
- `DiscoveryService` - Semantic Scholar/arXiv providers
- `NotificationService` - Email/Slack/Discord providers

**Proposed Unification:**
```python
# src/services/base/provider.py
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar('T')

class Provider(ABC, Generic[T]):
    """Base provider interface."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""
        pass

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Check provider health."""
        pass

    @abstractmethod
    async def execute(self, request: T) -> Any:
        """Execute provider-specific operation."""
        pass
```

**Benefits:**
- Consistent provider implementation
- Unified health checking
- Standardized error handling
- Easier provider addition

---

### Phase R6: Dependency Injection Adoption (LOWER PRIORITY)

**Current Pattern:**
Many services instantiate dependencies directly:
```python
# Current pattern (in extraction_service.py)
self._pdf_service = PDFService(config)
self._llm_service = LLMService(config)
```

**Recommended Pattern:**
```python
# Dependency injection pattern
class ExtractionService:
    def __init__(
        self,
        pdf_service: PDFService,
        llm_service: LLMService,
        config: ExtractionConfig,
    ):
        self._pdf_service = pdf_service
        self._llm_service = llm_service
```

**Benefits:**
- Easier testing with mock dependencies
- Clearer service boundaries
- Configuration flexibility
- Simplified integration testing

---

### Phase R7: Service Base Class (LOWER PRIORITY)

**Proposed Base Class:**
```python
# src/services/base/service.py
from abc import ABC, abstractmethod
import structlog

class AsyncService(ABC):
    """Base for async services with lifecycle management."""

    def __init__(self):
        self._logger = structlog.get_logger(self.__class__.__name__)
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize service resources."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up service resources."""
        pass

    @property
    def is_initialized(self) -> bool:
        return self._initialized
```

**Services to Refactor:**
- `DiscoveryService`
- `ExtractionService`
- `SynthesisEngine`
- `CrossTopicSynthesisService`
- `RegistryService`
- `NotificationService`

---

## Implementation Priority Matrix

| Refactoring | Impact | Effort | Priority | Status |
|-------------|--------|--------|----------|--------|
| Config model decomposition | High | Medium | P1 | ✅ Done |
| LLM Service decomposition | High | Medium | P1 | ✅ Done |
| Pipeline decomposition | High | Medium | P1 | ✅ Done |
| Cross-synthesis decomposition | High | Medium | P1 | ✅ Done |
| Discovery service decomposition | High | Medium | P1 | 🔜 Next |
| Notification service refactor | High | Medium | P1 | Planned |
| Registry service split | Medium | Low | P2 | Planned |
| CLI package split | Medium | Low | P2 | Planned |
| Output generator consolidation | Medium | Medium | P2 | Planned |
| Provider pattern improvements | Medium | Medium | P3 | Planned |
| Service base class | Medium | Medium | P3 | Planned |
| DI pattern adoption | Medium | High | P3 | Planned |

---

## Testing Improvements

### Current Coverage: 99.03% (2,470 tests)

### Recommendations

1. **Integration Test Consolidation**
   - Multiple integration test files with similar setup
   - Create shared fixtures module

2. **Test Data Factories**
   - Create `tests/factories/` for model instances
   - Reduce test setup duplication

3. **Performance Tests**
   - Add benchmark tests for concurrent pipeline
   - Track regression in processing speed

---

## Refactoring Guidelines

### Before Starting
1. Ensure all tests pass (`./verify.sh`)
2. Create feature branch per refactoring
3. Document breaking changes

### During Refactoring
1. Maintain test coverage ≥99%
2. Update imports incrementally
3. Keep backward compatibility where possible
4. Add deprecation warnings for moved APIs

### After Refactoring
1. Update CLAUDE.md if structure changes
2. Update SYSTEM_ARCHITECTURE.md
3. Run full verification suite
4. Create PR with detailed description

---

## Appendix: Current File Size Reference

| File | Lines | Status |
|------|-------|--------|
| llm/service.py | 906 | Partially decomposed (R2) |
| discovery_service.py | 831 | 🔜 Next (R4.2) |
| concurrent_pipeline.py | 632 | ✅ Decomposed (R3) |
| notification_service.py | 627 | Planned (R4.4) |
| registry_service.py | 622 | Planned (R4.3) |
| cross_synthesis_generator.py | 534 | Planned (R5.2) |
| extraction_service.py | 504 | Monitor |
| orchestration/pipeline.py | 474 | Planned (R5.1) |
| synthesis/cross_synthesis.py | 367 | ✅ New (R4.1) |
| paper_processor.py | 248 | ✅ New (R3) |
| cross_synthesis_service.py | 35 | ✅ Wrapper (R4.1) |

---

*This document should be reviewed and updated after each refactoring phase.*
*Last verified: 2026-03-20 with PR #68 (Phases R1-R4.1)*

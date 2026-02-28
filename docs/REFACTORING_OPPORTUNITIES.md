# Codebase Refactoring Opportunities

**Generated:** 2026-02-22
**Last Updated:** 2026-02-27
**Codebase Size:** ~18,500+ lines of Python code
**Classes:** 150+ classes across 90+ source files
**Test Coverage:** 99.92%

---

## Executive Summary

The codebase has grown significantly with the addition of Phase 2 (PDF/LLM extraction), Phase 3 (concurrent processing, synthesis), and Phase 4 (observability). Test coverage remains excellent (99.92%), and Phase 5 architectural refactoring is in progress.

**Priority Areas:**
1. ~~**High Priority**: LLMService decomposition (838 lines)~~ ✅ **COMPLETED** (Phase 5.1)
2. ~~**High Priority**: ResearchPipeline simplification (824 lines)~~ ✅ **COMPLETED** (Phase 5.2)
3. **Medium Priority**: CLI command splitting (716 lines) - *Next: Phase 5.3*
4. **Medium Priority**: Duplicate pattern extraction - *Planned: Phase 5.4*
5. **Lower Priority**: Model consolidation - *Planned: Phase 5.5*

---

## 1. LLMService Decomposition ✅ COMPLETED (Phase 5.1)

**Original File:** `src/services/llm_service.py` (838 lines, 26 functions)
**Status:** Decomposed to `src/services/llm/` package (Feb 24, 2026)

### Original State (Before Phase 5.1)
The `LLMService` class violated Single Responsibility Principle by handling:
- Provider abstraction (Anthropic/Google)
- Retry logic with exponential backoff
- Circuit breaker integration
- Cost tracking and budget enforcement
- Prompt building
- Response parsing
- Health monitoring
- Metrics export

### Proposed Refactoring

```
src/services/llm/
├── __init__.py           # Re-export public API
├── base.py               # Abstract LLMProvider interface
├── providers/
│   ├── anthropic.py      # Claude-specific implementation
│   └── google.py         # Gemini-specific implementation
├── cost_tracker.py       # Cost tracking & budget enforcement
├── prompt_builder.py     # Extraction prompt construction
├── response_parser.py    # JSON response parsing
└── service.py            # Orchestration (thin wrapper)
```

### Benefits
- Each module <150 lines
- Easier to test individual components
- Simpler provider addition (OpenAI, etc.)
- Clearer cost tracking logic

### Migration Strategy
1. Extract `CostTracker` class (lines 778-808)
2. Extract `PromptBuilder` class (lines 626-684)
3. Extract `ResponseParser` class (lines 685-760)
4. Create provider-specific classes
5. Slim down `LLMService` to orchestrator role

---

## 2. ResearchPipeline Simplification ✅ COMPLETED (Phase 5.2)

**Original File:** `src/orchestration/research_pipeline.py` (824 lines, 14 functions)
**Status:** Decomposed to phase-based architecture (Feb 25, 2026)

### Original State (Before Phase 5.2)
The `ResearchPipeline` class managed:
- Service initialization (12+ services)
- Topic processing workflow
- Phase 2 extraction integration
- Phase 3.6 synthesis orchestration
- Phase 3.7 cross-topic synthesis
- Error handling and aggregation

### Proposed Refactoring

```
src/orchestration/
├── __init__.py
├── pipeline.py           # Main orchestrator (<200 lines)
├── phases/
│   ├── discovery.py      # Phase 1: Paper discovery
│   ├── extraction.py     # Phase 2: PDF/LLM extraction
│   ├── synthesis.py      # Phase 3.6: Per-topic synthesis
│   └── cross_synthesis.py # Phase 3.7: Cross-topic synthesis
├── context.py            # Shared pipeline context/state
└── result.py             # PipelineResult class
```

### Benefits
- Clear phase separation
- Independent phase testing
- Easier to add new phases
- Simplified main orchestrator

### Migration Strategy
1. Extract `PipelineResult` to separate file
2. Create `PipelineContext` for shared state
3. Extract each phase to dedicated module
4. Slim down `ResearchPipeline` to coordinator

---

## 3. CLI Command Splitting (MEDIUM PRIORITY)

**File:** `src/cli.py` (716 lines)

### Current State
Single file contains all CLI commands:
- `run` command (full pipeline)
- `validate` command
- `catalog` command
- `schedule` command
- `health` command
- `synthesize` command
- `_send_notifications` helper

### Proposed Refactoring

```
src/cli/
├── __init__.py           # Main app, combines command groups
├── run.py                # run command
├── schedule.py           # schedule command
├── catalog.py            # catalog commands
├── synthesize.py         # synthesize command
├── health.py             # health command
└── utils.py              # Shared CLI utilities
```

### Benefits
- Each command module <150 lines
- Easier command-specific testing
- Clearer command organization
- Simpler addition of new commands

---

## 4. Duplicate Pattern Extraction (MEDIUM PRIORITY)

### 4.1 Author Normalization Pattern
**Already addressed** in recent PR #38 with `src/utils/author_utils.py`.

### 4.2 Retry Logic Duplication
Multiple services implement similar retry patterns:
- `LLMService._extract_with_provider` (lines 399-554)
- `PDFService.download_pdf` (retry decorator)
- `DiscoveryService._search_with_provider`

**Recommendation:** Ensure all services use unified `RetryHandler` from `src/utils/retry.py`

### 4.3 Cost Calculation Duplication
Cost calculation appears in multiple places:
- `LLMService._calculate_cost_anthropic` (lines 761-770)
- `LLMService._calculate_cost_google` (lines 771-777)
- `CostReportJob._calculate_cumulative_cost`

**Recommendation:** Extract `CostCalculator` utility class

### 4.4 Markdown Generation Patterns
Similar YAML frontmatter generation in:
- `MarkdownGenerator.generate`
- `EnhancedMarkdownGenerator.generate_enhanced`
- `SynthesisEngine._format_kb_entry_as_markdown`
- `CrossSynthesisGenerator._build_synthesis_section`

**Recommendation:** Create `MarkdownBuilder` utility with common patterns

---

## 5. Model Consolidation (LOWER PRIORITY)

### Current State
16 model files with some overlap:
- `models/llm.py` (378 lines) - LLM configuration
- `models/config.py` (305 lines) - Research configuration
- `models/cross_synthesis.py` (350 lines) - Synthesis models
- `models/synthesis.py` (201 lines) - Knowledge base models

### Recommendation
Consider logical grouping:

```
src/models/
├── __init__.py
├── core/                 # Core domain models
│   ├── paper.py
│   ├── author.py
│   └── topic.py
├── config/               # All configuration models
│   ├── research.py
│   ├── llm.py
│   └── pipeline.py
├── processing/           # Processing-related models
│   ├── extraction.py
│   ├── synthesis.py
│   └── registry.py
└── observability/        # Metrics/health models
    ├── notification.py
    └── metrics.py
```

---

## 6. Service Layer Improvements

### 6.1 Service Interface Abstraction

Several services could benefit from abstract base classes:

```python
# src/services/base.py
from abc import ABC, abstractmethod

class AsyncService(ABC):
    """Base for async services with lifecycle management."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize service resources."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up service resources."""
        pass
```

Services to refactor:
- `DiscoveryService`
- `ExtractionService`
- `SynthesisEngine`
- `CrossTopicSynthesisService`

### 6.2 Registry Service Complexity

**File:** `src/services/registry_service.py` (602 lines)

The `RegistryService` handles:
- Paper registration
- Metadata snapshots
- Deduplication
- State persistence
- Query operations

**Recommendation:** Split into:
- `PaperRegistry` - Core registration logic
- `RegistryPersistence` - JSON file I/O
- `RegistryQueries` - Search/filter operations

---

## 7. Testing Improvements

### Current Coverage: 99.92% (~1840 tests)

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

## 8. Dependency Injection Pattern

### Current State
Many services instantiate dependencies directly:

```python
# Current pattern (in extraction_service.py)
self._pdf_service = PDFService(config)
self._llm_service = LLMService(config)
```

### Recommended Pattern

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

### Benefits
- Easier testing with mock dependencies
- Clearer service boundaries
- Configuration flexibility

---

## 9. Implementation Priority Matrix

| Refactoring | Impact | Effort | Priority | Phase |
|-------------|--------|--------|----------|-------|
| LLMService decomposition | High | Medium | P1 | 1 |
| ResearchPipeline phases | High | Medium | P1 | 1 |
| CLI command splitting | Medium | Low | P2 | 2 |
| Cost calculator extraction | Medium | Low | P2 | 2 |
| Markdown builder utility | Medium | Low | P2 | 2 |
| Model consolidation | Low | High | P3 | 3 |
| Service base class | Medium | Medium | P3 | 3 |
| DI pattern adoption | Medium | High | P3 | 3 |

---

## 10. Refactoring Guidelines

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

## Appendix: File Size Reference

| File | Lines | Functions | Classes |
|------|-------|-----------|---------|
| llm_service.py | 838 | 26 | 2 |
| research_pipeline.py | 824 | 14 | 2 |
| cross_synthesis_service.py | 731 | 17 | 1 |
| cli.py | 716 | 8 | 0 |
| concurrent_pipeline.py | 713 | 16 | 1 |
| registry_service.py | 602 | 21 | 1 |
| discovery_service.py | 551 | 14 | 1 |
| synthesis_engine.py | 543 | 15 | 1 |
| cross_synthesis_generator.py | 534 | 14 | 1 |
| extraction_service.py | 504 | 13 | 1 |

---

*This document should be reviewed and updated quarterly as the codebase evolves.*

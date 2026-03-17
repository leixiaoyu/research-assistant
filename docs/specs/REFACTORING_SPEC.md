# Codebase Refactoring Specification
**Version:** 1.0
**Status:** 📋 Planning
**Timeline:** 2-3 weeks (phased implementation)
**Last Updated:** 2026-03-15
**Dependencies:**
- Existing Phase 5.1/5.2 decomposition patterns
- Test coverage ≥99%
- No regressions in functionality

---

## Architecture Reference

This specification defines refactoring priorities to maintain codebase quality as the project has grown significantly. Following patterns established in Phase 5.1 (LLM Service Decomposition) and Phase 5.2 (Orchestration Extraction).

**Current Codebase Metrics:**
- **Total Python Files:** 116
- **Total Lines of Code:** ~27,000
- **Files >500 lines:** 15 (refactoring candidates)
- **Files >700 lines:** 3 (critical priority)
- **Service Layer:** 22 files, 8,567 lines

**Refactoring Goals:**
- ✅ No file exceeds 500 lines
- ✅ No class exceeds 200 lines
- ✅ No method exceeds 30 lines
- ✅ Clear single responsibility per module
- ✅ Maintained ≥99% test coverage
- ✅ Zero regressions

---

## 1. Executive Summary

The codebase has evolved rapidly through Phases 1-7, accumulating technical debt in the form of large monolithic services and bloated model files. This specification prioritizes refactoring to maintain engineering rigor while preserving all functionality.

**Critical Files Requiring Immediate Attention:**

| File | Lines | Classes/Methods | Issue |
|------|-------|-----------------|-------|
| `llm/service.py` | 1,022 | 29 methods | Monolithic orchestrator |
| `concurrent_pipeline.py` | 745 | 9 methods | Complex async + 13 imports |
| `cross_synthesis_service.py` | 731 | 15 methods | Multi-responsibility |
| `discovery_service.py` | 673 | 12 methods | Provider + ranking mixed |
| `notification_service.py` | 627 | Multiple | Formatting + API mixed |
| `registry_service.py` | 622 | Multiple | Identity + persistence mixed |
| `config.py` | 570 | **22 classes** | Domain mixing |

---

## 2. Requirements

### 2.1 Code Quality Requirements

#### REQ-REF-1.1: Maximum File Size
All Python source files SHALL NOT exceed 500 lines.

**Acceptance Criteria:**
- WHEN a file exceeds 500 lines THEN it SHALL be split into focused modules
- WHEN splitting THEN each module SHALL have single responsibility
- WHEN splitting THEN backward compatibility SHALL be maintained via re-exports

#### REQ-REF-1.2: Maximum Class Size
All classes SHALL NOT exceed 200 lines.

**Acceptance Criteria:**
- WHEN a class exceeds 200 lines THEN responsibilities SHALL be extracted
- WHEN extracting THEN composition SHALL be preferred over inheritance
- WHEN extracting THEN public API SHALL be preserved

#### REQ-REF-1.3: Maximum Method Size
All methods SHALL NOT exceed 30 lines.

**Acceptance Criteria:**
- WHEN a method exceeds 30 lines THEN logic SHALL be extracted to helper methods
- WHEN extracting THEN method names SHALL clearly describe responsibility
- WHEN extracting THEN cyclomatic complexity SHALL be reduced

### 2.2 Maintainability Requirements

#### REQ-REF-2.1: Single Responsibility
Each module SHALL have a single, clearly defined responsibility.

**Acceptance Criteria:**
- WHEN describing a module THEN one sentence SHALL suffice without "and"
- WHEN a module has multiple responsibilities THEN it SHALL be split
- WHEN splitting THEN dependency direction SHALL be maintained

#### REQ-REF-2.2: Domain Separation
Configuration and model classes SHALL be organized by domain.

**Acceptance Criteria:**
- WHEN config.py exceeds 200 lines THEN it SHALL be split by domain
- WHEN splitting THEN related classes SHALL be grouped together
- WHEN splitting THEN __init__.py SHALL re-export for backward compatibility

### 2.3 Quality Assurance Requirements

#### REQ-REF-3.1: Test Coverage Preservation
Test coverage SHALL remain ≥99% throughout refactoring.

**Acceptance Criteria:**
- WHEN refactoring THEN all existing tests SHALL pass
- WHEN extracting modules THEN tests SHALL be updated to cover new files
- WHEN coverage drops THEN additional tests SHALL be added before merge

#### REQ-REF-3.2: No Functional Regression
All existing functionality SHALL be preserved.

**Acceptance Criteria:**
- WHEN refactoring THEN public APIs SHALL not change behavior
- WHEN changing internal implementation THEN integration tests SHALL pass
- WHEN completing phase THEN full verification suite SHALL pass

---

## 3. Severity Analysis

### 2.1 CRITICAL (Blocks Maintainability)

#### CR-1: `src/models/config.py` - 570 lines, 22 classes
**Problem:** Configuration for all domains mixed in single file.
**Impact:** Every new feature requires modifying this file. High coupling.
**Solution:** Split by domain.

```
BEFORE:
  src/models/config.py (570 lines, 22 classes)
    ├── TimeframeType, RelativeTimeframe, DateRangeTimeframe
    ├── ResearchTopic, ProviderConfig, DiscoverySettings
    ├── PDFStrategy, ExtractionConfig, OutputConfig
    ├── CacheConfig, DedupConfig, CheckpointConfig
    ├── RegistryConfig, NotificationConfig, SynthesisConfig
    └── ... more mixed classes

AFTER:
  src/models/config/
    ├── __init__.py (re-exports for backward compat)
    ├── core.py (~80 lines)
    │   ├── TimeframeType, RelativeTimeframe, DateRangeTimeframe
    │   └── ResearchTopic
    ├── discovery.py (~100 lines)
    │   ├── ProviderConfig, DiscoverySettings
    │   └── ProviderPriority, SearchScope
    ├── extraction.py (~100 lines)
    │   ├── PDFStrategy, ExtractionConfig
    │   └── PDFMode, ConversionSettings
    ├── output.py (~80 lines)
    │   ├── OutputConfig, SynthesisConfig
    │   └── OutputFormat, MarkdownSettings
    └── infrastructure.py (~100 lines)
        ├── CacheConfig, DedupConfig
        ├── CheckpointConfig, RegistryConfig
        └── NotificationConfig
```

#### CR-2: `src/services/llm/service.py` - 1,022 lines
**Problem:** Single class handling orchestration, cost tracking, error classification, provider selection.
**Impact:** Any LLM change requires understanding 1000+ lines.
**Status:** Phase 5.1 already extracted some modules.
**Remaining Work:** Extract error classification and simplify orchestration.

```
CURRENT STATE:
  src/services/llm/
    ├── service.py (1,022 lines) ← Still too large
    ├── cost_tracker.py (233 lines) ✓
    ├── prompt_builder.py (165 lines) ✓
    ├── response_parser.py (241 lines) ✓
    └── providers/ ✓

AFTER:
  src/services/llm/
    ├── service.py (~400 lines) - Orchestration only
    ├── error_classifier.py (~150 lines) - NEW
    │   ├── classify_error()
    │   ├── is_retryable()
    │   └── get_retry_delay()
    ├── request_builder.py (~150 lines) - NEW
    │   ├── build_request()
    │   └── validate_request()
    ├── cost_tracker.py ✓
    ├── prompt_builder.py ✓
    ├── response_parser.py ✓
    └── providers/ ✓
```

#### CR-3: `src/orchestration/concurrent_pipeline.py` - 745 lines
**Problem:** Complex async producer-consumer with 13 internal imports.
**Impact:** Hard to test, hard to modify, tight coupling.
**Solution:** Extract worker pool and queue management.

```
AFTER:
  src/orchestration/
    ├── concurrent_pipeline.py (~350 lines) - Orchestration only
    ├── worker_pool.py (~150 lines) - NEW
    │   ├── WorkerPool class
    │   ├── Worker management
    │   └── Task distribution
    ├── queue_manager.py (~150 lines) - NEW
    │   ├── QueueManager class
    │   ├── Backpressure logic
    │   └── Priority handling
    └── phases/ ✓
```

### 2.2 HIGH (Code Quality Issues)

#### HI-1: `src/services/discovery_service.py` - 673 lines
**Problem:** Mixes provider fallback, result ranking, PDF strategy selection.
**Solution:** Extract to focused classes.

```
AFTER:
  src/services/discovery/
    ├── __init__.py (re-exports)
    ├── orchestrator.py (~250 lines) - Main discovery logic
    ├── provider_fallback.py (~150 lines) - Fallback strategy
    ├── result_ranker.py (~150 lines) - Ranking logic
    └── pdf_selector.py (~100 lines) - PDF strategy selection
```

#### HI-2: `src/services/registry_service.py` - 622 lines
**Problem:** Mixes identity resolution (DOI matching, fuzzy title) with persistence.
**Solution:** Separate identity from persistence.

```
AFTER:
  src/services/registry/
    ├── __init__.py
    ├── service.py (~200 lines) - Orchestration
    ├── identity_resolver.py (~200 lines) - DOI + fuzzy matching
    ├── persistence.py (~150 lines) - File I/O
    └── state.py (~100 lines) - In-memory state
```

#### HI-3: `src/services/notification_service.py` - 627 lines
**Problem:** Contains SlackMessageBuilder embedded, mixes formatting with API calls.
**Solution:** Extract formatting and client.

```
AFTER:
  src/services/notification/
    ├── __init__.py
    ├── service.py (~200 lines) - Orchestration
    ├── slack_formatter.py (~200 lines) - Message building
    ├── slack_client.py (~150 lines) - API calls
    └── templates.py (~100 lines) - Message templates
```

#### HI-4: `src/services/cross_synthesis_service.py` - 731 lines
**Problem:** Combines synthesis orchestration, LLM interaction, state management.
**Solution:** Extract to focused modules.

```
AFTER:
  src/services/synthesis/
    ├── __init__.py
    ├── cross_synthesis.py (~250 lines) - Main orchestration
    ├── question_generator.py (~200 lines) - Question creation
    ├── answer_synthesizer.py (~200 lines) - Answer generation
    └── state_manager.py (~100 lines) - State tracking
```

### 2.3 MEDIUM (Maintainability)

#### ME-1: Output Generators - 4 files, 1,811 lines
**Problem:** Overlapping markdown generation logic, no shared base.
**Solution:** Extract common utilities, create base generator.

```
CURRENT:
  src/output/
    ├── synthesis_engine.py (543 lines)
    ├── cross_synthesis_generator.py (534 lines)
    ├── enhanced_generator.py (386 lines)
    ├── delta_generator.py (348 lines)
    └── markdown_generator.py (104 lines)

AFTER:
  src/output/
    ├── base_generator.py (~150 lines) - NEW shared base
    ├── markdown_utils.py (~100 lines) - NEW utilities
    ├── templates/ - NEW template directory
    │   ├── synthesis.md
    │   ├── extraction.md
    │   └── delta.md
    ├── synthesis_engine.py (~350 lines)
    ├── cross_synthesis_generator.py (~350 lines)
    ├── enhanced_generator.py (~250 lines)
    └── delta_generator.py (~250 lines)
```

#### ME-2: Provider Implementations - 5 files, 1,779 lines
**Problem:** Each provider re-implements query building, result parsing, rate limiting.
**Solution:** Extract shared utilities.

```
AFTER:
  src/services/providers/
    ├── base.py (~150 lines) - Enhanced base class
    ├── query_builder.py (~100 lines) - NEW shared query building
    ├── result_parser.py (~100 lines) - NEW shared parsing
    ├── arxiv.py (~200 lines) - Reduced
    ├── semantic_scholar.py (~180 lines) - Reduced
    ├── openalex.py (~350 lines) - Reduced
    └── huggingface.py (~400 lines) - Reduced
```

#### ME-3: Model Layer - 10 files, 3,275 lines
**Problem:** Some models mix multiple concerns.
**Solution:** Domain-based organization.

```
CURRENT:
  src/models/
    ├── config.py (570 lines, 22 classes) ← CR-1
    ├── discovery.py (517 lines, 11 classes)
    ├── llm.py (378 lines, 8 classes)
    ├── notification.py (368 lines, 6 classes)
    ├── cross_synthesis.py (350 lines)
    └── ...

AFTER:
  src/models/
    ├── config/ (CR-1 split)
    ├── discovery.py (~300 lines) - Core discovery models
    ├── discovery_metrics.py (~200 lines) - Extracted metrics
    ├── llm/
    │   ├── config.py (~150 lines)
    │   ├── usage.py (~100 lines)
    │   └── resilience.py (~130 lines)
    ├── notification.py (~250 lines)
    └── ...
```

---

## 4. Refactoring Principles

### 3.1 Extract, Don't Rewrite
- Extract focused modules from large files
- Maintain existing public APIs
- Use re-exports for backward compatibility

### 3.2 One Responsibility Per Module
- Each file should answer: "What is this file's single responsibility?"
- If you need "and" to describe it, split it

### 3.3 Test-First Refactoring
- Ensure existing tests pass before refactoring
- Add tests for any uncovered code paths
- Verify coverage remains ≥99%

### 3.4 Incremental Delivery
- Each refactoring can be a separate PR
- No big-bang rewrites
- Feature flags for gradual rollout if needed

---

## 5. Implementation Plan

### Phase R1: Model Decomposition (2-3 days)
**Target:** `config.py` (CR-1)

| Task | Effort | Files Created |
|------|--------|---------------|
| Create `src/models/config/` directory | 0.5h | - |
| Extract `core.py` (timeframes, topics) | 2h | 1 |
| Extract `discovery.py` (provider config) | 2h | 1 |
| Extract `extraction.py` (PDF, extraction) | 2h | 1 |
| Extract `output.py` (output, synthesis) | 1h | 1 |
| Extract `infrastructure.py` (cache, etc.) | 2h | 1 |
| Create `__init__.py` with re-exports | 1h | 1 |
| Update all imports across codebase | 2h | - |
| Verify tests pass | 1h | - |

**Deliverable:** `config.py` split into 6 focused modules, ~100 lines each.

### Phase R2: LLM Service Completion (1-2 days)
**Target:** `llm/service.py` (CR-2)

| Task | Effort | Files Created |
|------|--------|---------------|
| Extract `error_classifier.py` | 3h | 1 |
| Extract `request_builder.py` | 2h | 1 |
| Simplify `service.py` orchestration | 2h | - |
| Update imports | 1h | - |
| Verify tests pass | 1h | - |

**Deliverable:** `service.py` reduced from 1,022 to ~400 lines.

### Phase R3: Pipeline Decomposition (2-3 days)
**Target:** `concurrent_pipeline.py` (CR-3)

| Task | Effort | Files Created |
|------|--------|---------------|
| Extract `worker_pool.py` | 4h | 1 |
| Extract `queue_manager.py` | 3h | 1 |
| Simplify main orchestration | 2h | - |
| Update async tests | 2h | - |
| Verify tests pass | 1h | - |

**Deliverable:** `concurrent_pipeline.py` reduced from 745 to ~350 lines.

### Phase R4: Service Layer Refactoring (3-4 days)
**Targets:** HI-1 through HI-4

| Service | Current | Target | Days |
|---------|---------|--------|------|
| discovery_service | 673 | ~250 + 3 modules | 1 |
| registry_service | 622 | ~200 + 3 modules | 1 |
| notification_service | 627 | ~200 + 3 modules | 0.5 |
| cross_synthesis_service | 731 | ~250 + 3 modules | 1 |

### Phase R5: Output & Provider Cleanup (2-3 days)
**Targets:** ME-1, ME-2

| Area | Task | Days |
|------|------|------|
| Output | Create base generator, extract utils | 1 |
| Output | Apply to all generators | 1 |
| Providers | Extract shared utilities | 1 |

---

## 6. File Size Targets

### After Refactoring

| Category | Max Lines | Target |
|----------|-----------|--------|
| Service orchestrator | 300 | Primary logic only |
| Service module | 200 | Single responsibility |
| Model file | 200 | Related models only |
| Utility | 150 | Single utility |
| Provider | 300 | Including error handling |

### Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Files >500 lines | 15 | 0 |
| Files >300 lines | 30 | 10 |
| Average file size | 233 lines | <150 lines |
| Max class size | 500+ lines | 200 lines |
| Max method size | 80+ lines | 30 lines |

---

## 7. Security Requirements 🔒

### SR-REF-1: No Security Regression
- [ ] All security tests must pass after refactoring
- [ ] Path sanitization logic must be preserved
- [ ] API key handling must not be modified

### SR-REF-2: Backward Compatibility
- [ ] Public APIs must be preserved via re-exports
- [ ] Import paths should work with deprecation warnings
- [ ] No breaking changes without migration guide

---

## 8. Testing Strategy

### 7.1 Pre-Refactoring
1. Ensure all tests pass: `./verify.sh`
2. Document current coverage per module
3. Add tests for any uncovered code paths

### 7.2 During Refactoring
1. Run tests after each extraction
2. Maintain ≥99% coverage
3. Add unit tests for new modules

### 7.3 Post-Refactoring
1. Full regression test: `./verify.sh`
2. Performance benchmark comparison
3. Integration test verification

---

## 9. Implementation Checklist

### Phase R1: Model Decomposition
- [ ] Create `src/models/config/` directory structure
- [ ] Extract core.py (timeframes, topics)
- [ ] Extract discovery.py (provider config)
- [ ] Extract extraction.py (PDF settings)
- [ ] Extract output.py (output config)
- [ ] Extract infrastructure.py (cache, checkpoint)
- [ ] Create __init__.py with re-exports
- [ ] Update imports across codebase
- [ ] Verify all tests pass
- [ ] Update CLAUDE.md if needed

### Phase R2: LLM Service Completion
- [ ] Extract error_classifier.py
- [ ] Extract request_builder.py
- [ ] Simplify service.py
- [ ] Update imports
- [ ] Verify all tests pass

### Phase R3: Pipeline Decomposition
- [ ] Extract worker_pool.py
- [ ] Extract queue_manager.py
- [ ] Simplify concurrent_pipeline.py
- [ ] Update async tests
- [ ] Verify all tests pass

### Phase R4: Service Layer
- [ ] Refactor discovery_service
- [ ] Refactor registry_service
- [ ] Refactor notification_service
- [ ] Refactor cross_synthesis_service
- [ ] Verify all tests pass

### Phase R5: Output & Providers
- [ ] Create base_generator.py
- [ ] Extract markdown_utils.py
- [ ] Apply to all generators
- [ ] Extract provider shared utilities
- [ ] Verify all tests pass

---

## 10. Risk Assessment

### 9.1 Low Risk
- Model decomposition (no logic changes)
- Re-export backward compatibility
- Utility extraction

### 9.2 Medium Risk
- Service layer refactoring (logic redistribution)
- Async pipeline changes (timing sensitive)

### 9.3 Mitigation
- Each phase is a separate PR
- Full test suite run after each change
- Rollback via git revert if needed

---

## 11. Sign-off

### 10.1 Approval Checklist
- [ ] Specification reviewed by project maintainer
- [ ] Refactoring priorities agreed upon
- [ ] Timeline is acceptable
- [ ] Test coverage requirements understood

### 10.2 Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Author | Claude Code | 2026-03-15 | ✅ |
| Reviewer | | | |
| Approver | | | |

---

## 12. Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-15 | Claude Code | Initial specification |

---

## Appendix A: Complete File Analysis

### Files >500 Lines (Refactoring Required)

| Rank | File | Lines | Priority |
|------|------|-------|----------|
| 1 | `src/services/llm/service.py` | 1,022 | CR-2 |
| 2 | `src/orchestration/concurrent_pipeline.py` | 745 | CR-3 |
| 3 | `src/services/cross_synthesis_service.py` | 731 | HI-4 |
| 4 | `src/services/discovery_service.py` | 673 | HI-1 |
| 5 | `src/services/notification_service.py` | 627 | HI-3 |
| 6 | `src/services/registry_service.py` | 622 | HI-2 |
| 7 | `src/models/config.py` | 570 | CR-1 |
| 8 | `src/output/synthesis_engine.py` | 543 | ME-1 |
| 9 | `src/output/cross_synthesis_generator.py` | 534 | ME-1 |
| 10 | `src/models/discovery.py` | 517 | ME-3 |
| 11 | `src/services/extraction_service.py` | 504 | Future |
| 12 | `src/services/providers/huggingface.py` | 500 | ME-2 |

### Codebase Composition

| Directory | Files | Lines | % of Total |
|-----------|-------|-------|------------|
| `src/services/` | 22 | 8,567 | 32% |
| `src/models/` | 10 | 3,275 | 12% |
| `src/orchestration/` | 11 | 2,609 | 10% |
| `src/output/` | 5 | 1,921 | 7% |
| `src/utils/` | 12 | 1,927 | 7% |
| `src/services/providers/` | 6 | 1,779 | 7% |
| `src/services/llm/` | 7 | 2,317 | 9% |
| Other | 43 | 4,654 | 17% |
| **Total** | **116** | **~27,000** | **100%** |

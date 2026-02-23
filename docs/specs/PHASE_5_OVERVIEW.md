# Phase 5: Architectural Refactoring (Code Health Initiative)
**Version:** 1.0
**Status:** 📋 Planning
**Timeline:** 4-6 weeks (incremental)
**Dependencies:**
- All Phase 3.x features complete
- Phase 4 observability complete
- Test coverage ≥99% maintained

---

## Executive Summary

Phase 5 is a **code health initiative** focused on refactoring the codebase to improve maintainability, reduce complexity, and establish patterns that support future growth. Unlike feature phases, this phase delivers no new functionality—it improves the architecture of existing functionality.

**Codebase Stats at Start:**
- ~17,781 lines of Python code
- 140+ classes across 75 source files
- 1,468 automated tests (99.58% coverage)

**Sub-Phases:**

| Phase | Focus | Priority | Effort | Risk |
|-------|-------|----------|--------|------|
| 5.1 | LLMService Decomposition | HIGH | 3-4 days + 0.5 day integration | Low |
| 5.2 | ResearchPipeline Refactoring | HIGH | 3-4 days + 0.5 day integration | Medium |
| 5.3 | CLI Command Splitting | MEDIUM | 2 days + 0.5 day integration | Low |
| 5.4 | Utility Pattern Extraction | MEDIUM | 2 days + 0.5 day integration | Low |
| 5.5 | Model Consolidation | LOW | 3-4 days + 0.5 day integration | Medium |
| 5.6 | Service Layer Improvements | LOW | 3-4 days + 0.5 day integration | Medium |

---

## Guiding Principles

### 1. No Behavioral Changes
All refactoring MUST maintain exact behavioral equivalence. If a test fails after refactoring, the refactoring is incorrect.

### 2. Incremental Delivery
Each sub-phase is independently deployable. We can stop after any phase and still have a better codebase.

### 3. Test Coverage Maintenance
Coverage MUST remain ≥99% throughout. New modules created by splitting require proportional test coverage.

### 4. Backward Compatibility
All public APIs (CLI commands, service interfaces) MUST remain backward compatible. Deprecation warnings allowed.

---

## Success Criteria (Overall)

| Metric | Current | Target |
|--------|---------|--------|
| Largest file | 838 lines | <300 lines |
| Average file size | 237 lines | <200 lines |
| Files >500 lines | 10 | 0 |
| Test coverage | 99.58% | ≥99% |
| Cyclomatic complexity (avg) | TBD | <10 |

---

## Implementation Order

```
Week 1: Phase 5.1 (LLMService)
Week 2: Phase 5.2 (ResearchPipeline)
Week 3: Phase 5.3 + 5.4 (CLI + Utilities)
Week 4: Phase 5.5 (Models) - Optional
Week 5: Phase 5.6 (Services) - Optional
```

Phases 5.5 and 5.6 are optional and can be deferred based on team capacity.

**Note:** Each phase includes 0.5 day of integration testing. Total estimate: 5-7 weeks including buffer.

---

## Deprecation Policy

### Timeline
All deprecated APIs follow this schedule:

| Phase | Action | Timeline |
|-------|--------|----------|
| Introduction | Add deprecation warnings | During Phase 5.x implementation |
| Warning Period | Warnings emitted on legacy imports | 3 months minimum |
| Removal | Remove deprecated paths | Phase 6 or +3 months after Phase 5 complete |

### Notification Process
1. **Changelog Entry:** Document deprecated APIs in CHANGELOG.md
2. **Warning Messages:** Clear messages with migration path
3. **Documentation:** Update all docs to show new import patterns
4. **CI Notification:** Deprecation warnings logged in CI output

### Example Deprecation Warning
```python
import warnings
warnings.warn(
    "Importing from src.models.paper is deprecated. "
    "Use 'from src.models import PaperMetadata' instead. "
    "This import path will be removed in Phase 6.",
    DeprecationWarning,
    stacklevel=2,
)
```

---

## Risk Assessment

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Breaking changes | High | Low | Comprehensive test suite (1468 tests) |
| Coverage drop | Medium | Low | Per-module coverage enforcement |
| Import cycles | Medium | Medium | Careful dependency ordering |
| Merge conflicts | Low | Medium | Short-lived feature branches |

---

## Related Documents

- [REFACTORING_OPPORTUNITIES.md](../REFACTORING_OPPORTUNITIES.md) - Detailed analysis
- [SYSTEM_ARCHITECTURE.md](../SYSTEM_ARCHITECTURE.md) - Architecture overview
- [PHASE_5.1_SPEC.md](./PHASE_5.1_SPEC.md) - LLMService Decomposition
- [PHASE_5.2_SPEC.md](./PHASE_5.2_SPEC.md) - ResearchPipeline Refactoring
- [PHASE_5.3_SPEC.md](./PHASE_5.3_SPEC.md) - CLI Command Splitting
- [PHASE_5.4_SPEC.md](./PHASE_5.4_SPEC.md) - Utility Pattern Extraction
- [PHASE_5.5_SPEC.md](./PHASE_5.5_SPEC.md) - Model Consolidation
- [PHASE_5.6_SPEC.md](./PHASE_5.6_SPEC.md) - Service Layer Improvements

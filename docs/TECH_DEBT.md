# Technical Debt Tracking

This document tracks technical debt identified during code reviews and development, with prioritization and planned resolution.

## Active Debt Items

**No active debt items.** ✅

All previously identified technical debt has been resolved. The project maintains:
- **99.10% overall test coverage** (exceeds ≥95% requirement)
- **442 automated tests** (100% pass rate)
- **100% coverage** on all core services

---

## Resolved Debt Items

### ✅ ExtractionService Coverage Gap (Resolved in Phase 3.1)

**Resolved:** 2026-01-31
**Original Coverage:** 85%
**Final Coverage:** 100%

**Description:**
The `src/services/extraction_service.py` module was at 85% test coverage, below the project's 95% requirement. The missing coverage primarily affected error handling paths in the LLM extraction orchestration logic.

**Resolution:**
- Added comprehensive error handling tests during Phase 3.1 implementation
- Mocked LLM service failures (timeout, rate limit, invalid response)
- Tested extraction result validation failures
- Tested partial extraction and concurrent processing scenarios
- Full integration with ConcurrentPipeline verified

---

### ✅ Base Extractor Abstract Method Coverage (Resolved in PR #17)

**Resolved:** 2026-02-01
**Original Coverage:** 88%
**Final Coverage:** 100%

**Description:**
The `src/services/pdf_extractors/base.py` showed coverage gaps that were addressed through comprehensive edge case testing.

**Resolution:**
- Added edge case tests in PR #17 (Tech Debt: Comprehensive Test Coverage)
- All concrete implementations verified at 100% coverage
- Abstract base class patterns properly tested through subclasses

---

### ✅ Comprehensive Edge Case Tests (Resolved in PR #17)

**Resolved:** 2026-02-01
**PR:** #17 - Tech Debt: Add Edge Case Tests for Core Services

**Description:**
Added comprehensive edge case tests for LLM, PDF, and batch services to improve overall test coverage and robustness.

**Resolution:**
- Added edge case tests for LLM service error handling
- Added edge case tests for PDF extraction edge cases
- Added batch processing tests
- Overall test count: 408 → 442 tests
- Overall coverage: 98.12% → 99.10%

---

### ✅ Cache Service Coverage Regression (Resolved in PR #9)

**Resolved:** 2026-01-26
**Original Coverage:** 77%
**Final Coverage:** 99%

**Description:**
Cache service showed coverage regression when initially added to Phase 2.5. Fixed by adding 20 comprehensive tests covering all error paths, disabled scenarios, and edge cases.

**Resolution:**
- Added `tests/unit/test_cache_service_coverage.py` with 20 new tests
- All exception handling paths now tested
- Disabled cache scenarios verified
- TimeframeDateRange and TimeframeSinceYear handling tested
- Clear cache by type (api, pdf, extraction) tested

---

### ✅ PDF Extractor Coverage Gaps (Resolved in PR #9)

**Resolved:** 2026-01-26
**Original Coverage:**
- pdfplumber_extractor.py: 87%
- pymupdf_extractor.py: 91%
- pandoc_extractor.py: 91%
- fallback_service.py: 94%

**Final Coverage:** 100% for all extractors

**Description:**
New PDF extractors lacked comprehensive error handling tests, particularly for external library failures and malformed data scenarios.

**Resolution:**
Added targeted tests for:
- File not found scenarios
- General exception handling
- Empty and malformed table handling
- Library import failures
- Quality comparison logic

---

## Debt Prevention Guidelines

To minimize future technical debt:

1. **Coverage Requirements:**
   - All new modules must have ≥95% coverage from day one
   - Run `./verify.sh` before creating any PR
   - Document any legitimately uncoverable lines

2. **Code Review Focus:**
   - Error handling paths must be explicitly tested
   - Edge cases documented in test docstrings
   - Integration tests for cross-module interactions

3. **Documentation:**
   - Update TECH_DEBT.md when debt is identified or resolved
   - Include debt tracking in PR descriptions
   - Link debt items to specific phase planning

4. **Prioritization:**
   - High: Blocks releases, security risks, >5% coverage gaps
   - Medium: Quality of life, <5% coverage gaps, minor tech debt
   - Low: False positives, acceptable architectural constraints

---

## Quarterly Debt Review

**Last Review:** 2026-02-01
**Next Review:** End of Q1 2026
**Goal:** Zero high-priority debt items ✅ **ACHIEVED**

**Review Checklist:**
- [x] All high-priority items resolved or downgraded
- [x] Medium-priority items have concrete resolution plans
- [x] No new debt introduced without justification
- [x] Coverage maintained at ≥95% project-wide (currently 99.10%)

**Current Status:**
- **Active Debt Items:** 0
- **Overall Coverage:** 99.10%
- **Total Tests:** 442
- **Pass Rate:** 100%

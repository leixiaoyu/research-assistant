# Technical Debt Tracking

This document tracks technical debt identified during code reviews and development, with prioritization and planned resolution.

## Active Debt Items

### 1. ExtractionService Coverage Gap (Phase 3.1)

**Priority:** High
**Identified:** PR #9 Review (2026-01-26)
**Current Coverage:** 85%
**Target Coverage:** ≥95%
**Planned Resolution:** Phase 3.1 - Final Orchestration

**Description:**
The `src/services/extraction_service.py` module is at 85% test coverage, below the project's 95% requirement. The missing coverage primarily affects error handling paths in the LLM extraction orchestration logic.

**Uncovered Areas:**
- Lines 176-177: Error handling for invalid extraction results
- Line 194: Fallback logic when extraction fails
- Lines 228-254: Complex orchestration error scenarios

**Impact:**
- Medium risk: Core functionality is tested, but error paths are not fully verified
- Could lead to unhandled exceptions in production under edge cases
- Blocks achieving 100% coverage goal for Phase 3

**Resolution Plan:**
Add comprehensive error handling tests in Phase 3.1:
1. Mock LLM service failures (timeout, rate limit, invalid response)
2. Test extraction result validation failures
3. Test partial extraction scenarios
4. Test retry logic under various failure modes

**Acceptance Criteria:**
- `extraction_service.py` coverage ≥95%
- All error paths tested with mocked failures
- Integration tests verify end-to-end error handling
- Documentation updated with error handling patterns

---

### 2. Base Extractor Abstract Method Coverage (Acceptable)

**Priority:** Low (False Positive)
**Identified:** PR #9 Review (2026-01-26)
**Current Coverage:** 88%
**Target Coverage:** N/A (acceptable as-is)

**Description:**
The `src/services/pdf_extractors/base.py` shows coverage gaps at 88%, but these are false positives related to abstract method `pass` statements that cannot be executed directly.

**Uncovered Areas:**
- Line 43: Abstract method `validate_setup()`
- Line 53: Abstract method `extract()`
- Line 59: Abstract method `name` property

**Impact:**
- No actual risk: Abstract methods are implemented in all concrete subclasses
- All concrete implementations (PyMuPDF, PDFPlumber, Pandoc) have 100% coverage

**Resolution Plan:**
No action required. This is acceptable architectural debt inherent to abstract base classes.

---

## Resolved Debt Items

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

**Next Review:** End of Q1 2026
**Goal:** Zero high-priority debt items

**Review Checklist:**
- [ ] All high-priority items resolved or downgraded
- [ ] Medium-priority items have concrete resolution plans
- [ ] No new debt introduced without justification
- [ ] Coverage maintained at ≥95% project-wide

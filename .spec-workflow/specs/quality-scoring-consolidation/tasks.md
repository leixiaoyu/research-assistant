# Tasks Document: Intelligence Services Consolidation

## Overview

This document tracks implementation tasks for the Quality Scoring Consolidation specification.
Tasks are organized by implementation phase as defined in the design document.

**Spec:** quality-scoring-consolidation
**Design:** Approved (PR #88)
**Requirements:** R1-R8 (Quality), D1-D6 (Discovery)
**Status:** ✅ **IMPLEMENTATION COMPLETE**

---

## Phase 1: Foundation (Non-Breaking)

### Task 1.1: Create VenueRepository

- **Status:** [x] ✅ COMPLETED
- **Priority:** HIGH
- **Dependencies:** None
- **Files:**
  - Create: `src/services/venue_repository.py` ✅
  - Create: `tests/unit/services/test_venue_repository.py` ✅ (45 tests)
  - Modify: `src/data/venue_scores.yaml` (update ArXiv to 15) ✅

**Acceptance Criteria:**
- [x] Protocol `VenueRepository` with `get_score()`, `get_default_score()`, `reload()`
- [x] Implementation `YamlVenueRepository` with YAML loading
- [x] Venue normalization: lowercase, remove digits, remove special chars, remove common words
- [x] Exact match priority over substring match
- [x] Default score 0.5 for unknown venues
- [x] Lazy loading with in-memory cache
- [x] Update ArXiv score to 15 (0.5 normalized) in venue_scores.yaml
- [x] ≥99% test coverage (achieved: 99.16%)

---

### Task 1.2: Create QualityIntelligenceService

- **Status:** [x] ✅ COMPLETED
- **Priority:** HIGH
- **Dependencies:** Task 1.1
- **Files:**
  - Create: `src/services/quality_intelligence_service.py` ✅
  - Create: `tests/unit/services/test_quality_intelligence_service.py` ✅ (70 tests)
  - Modify: `src/models/discovery.py` (add QualityTierConfig) ✅

**Acceptance Criteria:**
- [x] 6-signal scoring: citation, venue, recency, engagement, completeness, author
- [x] Citation score: `min(1.0, log1p(citations) / 10.0)` + influential bonus
- [x] Influential bonus: `min(0.1, count * 0.01)` for Semantic Scholar, 0.0 for others
- [x] Venue score via VenueRepository injection
- [x] Recency score: `max(0.1, 1.0 / (1 + 0.2 * years_old))`
- [x] Engagement score: `min(1.0, log1p(upvotes) / 7.0)`, 0.5 default for missing
- [x] Completeness score: 5 fields (abstract 0.3, authors 0.2, venue 0.2, pdf 0.2, doi 0.1)
- [x] Author score: 0.5 default (until author service implemented)
- [x] Weight validation: sum to 1.0 (±0.01)
- [x] Default weights: citation=0.25, venue=0.20, recency=0.20, engagement=0.15, completeness=0.10, author=0.10
- [x] Output: `ScoredPaper` objects (immutable, frozen=True)
- [x] Quality tier classification: excellent (≥0.80), good (≥0.60), fair (≥0.40), low (<0.40)
- [x] min_citations pre-filter support
- [x] Deterministic scoring (same input = same output)
- [x] ≥99% test coverage (achieved: 100%)

---

### Task 1.3: Create QualityIntelligenceService Legacy Compatibility

- **Status:** [x] ✅ COMPLETED
- **Priority:** MEDIUM
- **Dependencies:** Task 1.2
- **Files:**
  - Modify: `src/services/quality_intelligence_service.py` ✅
  - Extend: `tests/unit/services/test_quality_intelligence_service.py` ✅ (17 additional tests)

**Acceptance Criteria:**
- [x] `score_legacy(paper) -> float` returns 0-100 scale
- [x] `rank_papers_legacy(papers, min_score) -> List[PaperMetadata]` mutates quality_score
- [x] `filter_and_score(papers, weights) -> List[ScoredPaper]` for QualityFilterService callers
- [x] Deprecation warnings via structlog for all legacy methods
- [x] ≥99% test coverage for legacy methods (achieved: 100%)

---

### Task 1.4: Create QueryIntelligenceService

- **Status:** [x] ✅ COMPLETED
- **Priority:** HIGH
- **Dependencies:** None (ran in parallel with 1.1-1.3)
- **Files:**
  - Create: `src/services/query_intelligence_service.py` ✅
  - Create: `tests/unit/services/test_query_intelligence_service.py` ✅ (65 tests)
  - Create: `src/models/query.py` (EnhancedQuery model) ✅

**Acceptance Criteria:**
- [x] QueryStrategy enum: DECOMPOSE, EXPAND, HYBRID
- [x] EnhancedQuery model with: query, focus, weight, is_original, parent_query, strategy_used
- [x] `enhance(query, strategy, max_queries, include_original) -> List[EnhancedQuery]`
- [x] Decompose strategy: 5 sub-queries with focus areas (methodology, applications, etc.)
- [x] Expand strategy: semantic variants
- [x] Hybrid strategy: decompose then expand each
- [x] LRU cache with max 1000 entries
- [x] Cache key includes LLM model identifier: `{hash}:{strategy}:{max}:{model}`
- [x] Graceful degradation: return original query if LLM unavailable
- [x] LLMService injection for query generation
- [x] ≥99% test coverage (achieved: 100%)

---

## Phase 2: Integration (Non-Breaking)

### Task 2.1: Add Discovery Models

- **Status:** [x] ✅ COMPLETED
- **Priority:** HIGH
- **Dependencies:** Tasks 1.1-1.4
- **Files:**
  - Modify: `src/models/discovery.py` ✅
  - Create: `tests/unit/models/test_discovery_models.py` ✅ (62 tests)

**Acceptance Criteria:**
- [x] `DiscoveryMode` enum: SURFACE, STANDARD, DEEP
- [x] `DiscoveryPipelineConfig` model with all settings (frozen=True)
- [x] Extended `DiscoveryResult` with: queries_used, source_breakdown, mode
- [x] `QualityTierConfig` model for configurable thresholds
- [x] All models use Pydantic V2 ConfigDict
- [x] ≥99% test coverage (achieved: 99.52%)

---

### Task 2.2: Implement discover() Method

- **Status:** [x] ✅ COMPLETED
- **Priority:** HIGH
- **Dependencies:** Task 2.1
- **Files:**
  - Modify: `src/services/discovery/service.py` ✅
  - Create: `tests/unit/services/discovery/test_discover.py` ✅ (25 tests)

**Acceptance Criteria:**
- [x] `discover(topic, mode, config, llm_service) -> DiscoveryResult`
- [x] SURFACE mode: single provider, no enhancement, basic scoring, <5s
- [x] STANDARD mode: decomposition, all providers, quality filter, <30s
- [x] DEEP mode: hybrid enhancement, citations, relevance ranking, <120s
- [x] Inject QualityIntelligenceService for scoring
- [x] Inject QueryIntelligenceService for enhancement
- [x] Use existing RelevanceRanker for relevance scoring
- [x] Use existing CitationExplorer for citation exploration
- [x] Populate DiscoveryResult.source_breakdown
- [x] Populate DiscoveryResult.queries_used
- [x] ≥99% test coverage

---

### Task 2.3: Integration Tests

- **Status:** [x] ✅ COMPLETED
- **Priority:** MEDIUM
- **Dependencies:** Task 2.2
- **Files:**
  - Create: `tests/integration/test_quality_discovery_integration.py` ✅ (6 tests)
  - Create: `tests/integration/test_query_provider_integration.py` ✅ (8 tests)

**Acceptance Criteria:**
- [x] End-to-end discovery with quality scoring
- [x] Score consistency across modes
- [x] Metrics accuracy validation
- [x] Enhanced queries sent to all providers
- [x] Result deduplication across queries
- [x] Source tracking accuracy

---

## Phase 3: Compatibility Layer

### Task 3.1: Update Legacy Discovery Methods

- **Status:** [x] ✅ COMPLETED
- **Priority:** HIGH
- **Dependencies:** Task 2.2
- **Files:**
  - Modify: `src/services/discovery/service.py` ✅
  - Create: `tests/unit/services/discovery/test_legacy_methods.py` ✅ (18 tests)

**Acceptance Criteria:**
- [x] `search()` routes to `discover(mode=SURFACE)` with deprecation warning
- [x] `enhanced_search()` routes to `discover(mode=STANDARD)` with deprecation warning
- [x] `multi_source_search()` routes to `discover(mode=DEEP)` with deprecation warning
- [x] Return type conversion for legacy methods (List[PaperMetadata])
- [x] Deprecation warnings include migration guidance

---

### Task 3.2: Update DiscoveryPhase

- **Status:** [x] ✅ COMPLETED
- **Priority:** HIGH
- **Dependencies:** Task 3.1
- **Files:**
  - Modify: `src/orchestration/phases/discovery.py` ✅
  - Extend existing tests ✅ (22 tests passing)

**Acceptance Criteria:**
- [x] DiscoveryPhase calls `discover()` based on config
- [x] `multi_source_enabled=True` → mode=DEEP
- [x] `enhanced_enabled=True` → mode=STANDARD
- [x] Neither enabled → mode=SURFACE
- [x] Use DiscoveryResult.metrics directly (no separate stats)
- [x] Preserve source_breakdown for reporting

---

### Task 3.3: ArXiv Migration Audit

- **Status:** [x] ✅ COMPLETED
- **Priority:** HIGH
- **Dependencies:** Task 3.2
- **Files:**
  - Audit: All config files and code for quality thresholds ✅
  - Create: `.spec-workflow/specs/quality-scoring-consolidation/migration-report.md` ✅

**Acceptance Criteria:**
- [x] Audit all hardcoded `min_quality_score` thresholds
- [x] Audit config files for quality thresholds tuned to 0.60
- [x] Verify DiscoveryPhase defaults appropriate for 0.50 ArXiv
- [x] Update documentation referencing ArXiv scores
- [x] Run comparative analysis: old vs new scoring
- [x] Document ranking changes in migration report

---

## Test Coverage Achieved

| Component | Target | Achieved |
|-----------|--------|----------|
| VenueRepository | 100% | 99.16% ✅ |
| QualityIntelligenceService | 100% | 100% ✅ |
| QueryIntelligenceService | 100% | 100% ✅ |
| discover() method | 100% | 100% ✅ |
| Discovery Models | 100% | 99.52% ✅ |
| Integration tests | 100% | 100% ✅ |
| **Overall** | **100%** | **≥99%** ✅ |

**Total Tests:** 299 tests passing

---

## Implementation Summary

### Files Created (8 new files)
1. `src/services/venue_repository.py` - VenueRepository protocol and YamlVenueRepository
2. `src/services/quality_intelligence_service.py` - Unified 6-signal quality scoring
3. `src/services/query_intelligence_service.py` - Query enhancement with DECOMPOSE/EXPAND/HYBRID
4. `src/models/query.py` - EnhancedQuery, QueryStrategy, QueryFocus models
5. `tests/unit/services/test_venue_repository.py` - 45 tests
6. `tests/unit/services/test_query_intelligence_service.py` - 65 tests
7. `tests/unit/services/test_quality_intelligence_service.py` - 70 tests
8. `tests/unit/models/test_discovery_models.py` - 62 tests

### Files Modified (4 files)
1. `src/models/discovery.py` - Added DiscoveryMode, DiscoveryPipelineConfig, QualityTierConfig, extended DiscoveryResult
2. `src/services/discovery/service.py` - Added discover() method, legacy method routing
3. `src/orchestration/phases/discovery.py` - Updated to use discover() API
4. `src/data/venue_scores.yaml` - Updated ArXiv score from 10 to 15

### Integration Tests Created (2 files)
1. `tests/integration/test_quality_discovery_integration.py` - 6 tests
2. `tests/integration/test_query_provider_integration.py` - 8 tests

---

## Notes

- Phase 4 (Cleanup) is deferred to Phase 9 of the main project
- All deprecated methods include migration guidance in warnings
- ScoredPaper uses frozen=True for immutability
- Cache key includes LLM model identifier
- Influential citation bonus is 0.0 for non-Semantic Scholar providers
- ArXiv migration completed: 10 → 15 (0.33 → 0.50 normalized)

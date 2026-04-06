# Requirements Document: Quality Scoring Consolidation

## Introduction

This specification addresses critical **Quality Scoring Fragmentation** identified during Phase 8.1 code review. The codebase currently contains two redundant quality scoring systems (QualityScorer from Phase 3.4 and QualityFilterService from Phase 6) that use incompatible algorithms, scales, and data sources. This causes **Ranking Drift** where identical papers receive different quality scores depending on which pipeline processes them.

**Business Impact:**
- Same query returns different paper rankings based on pipeline choice
- User confusion when results vary between basic and enhanced search
- Technical debt accumulating as both systems evolve independently
- Blocking condition for Phase 8 DRA (Deep Research Agent) development

**Goal:** Consolidate into a single, authoritative `QualityIntelligenceService` that provides consistent, accurate quality scoring across all discovery pipelines.

## Alignment with Product Vision

This consolidation directly supports ARISP's core mission of providing **reliable, consistent research paper rankings** to engineering teams. Quality scoring is foundational to:
- Surfacing the most relevant, high-quality papers
- Building trust in automated research recommendations
- Enabling the Phase 8 DRA to make intelligent corpus decisions

## Current State Analysis

### Existing Services Comparison

| Aspect | QualityScorer (Phase 3.4) | QualityFilterService (Phase 6) |
|--------|---------------------------|--------------------------------|
| **Output Scale** | 0-100 | 0-1 |
| **Citation Math** | `log10(n+1)/3.0` + influential bonus | `log1p(n)/10.0` |
| **Recency Model** | Tiered (4 levels: 1.0, 0.75, 0.5, 0.25) | Half-life decay (rate=0.2, min=0.1) |
| **Venue Data** | YAML file (0-30 scale) | Hardcoded dict (0-1 scale) |
| **Venue Matching** | Simple lowercase + substring | Advanced normalization (remove digits, common words) |
| **Signals** | 4 (citation, venue, recency, completeness) | 6 (+engagement, author) |
| **Weights** | 0.40, 0.30, 0.20, 0.10 | 0.25, 0.20, 0.20, 0.15, 0.10, 0.10 |
| **Completeness** | Abstract=0.5, Authors=0.3, DOI=0.2 | Abstract=0.3, Authors=0.2, Venue=0.2, PDF=0.2, DOI=0.1 |
| **Output Type** | Mutates PaperMetadata.quality_score | Returns new ScoredPaper objects |
| **ArXiv Score** | 10/30 = 0.33 | 0.60 |

### Key Discrepancies Requiring Resolution

1. **ArXiv Score:** 0.33 vs 0.60 (81% difference) - affects majority of ML papers
2. **Citation Scaling:** log10 vs log1p - different normalization curves
3. **Influential Citations:** Only QualityScorer has bonus for highly-cited citations
4. **Weight Distribution:** Different emphasis on signals
5. **Engagement Signal:** Only in Phase 6, returns 0.0 for non-HuggingFace papers

## Requirements

### Requirement 1: Unified Quality Scoring Service

**User Story:** As a research engineer, I want consistent paper quality scores regardless of which discovery pipeline I use, so that I can trust the rankings and make informed decisions about which papers to read.

#### Acceptance Criteria

1. WHEN a paper is scored THEN the system SHALL return a score on a normalized 0.0-1.0 scale
2. WHEN the same paper is scored multiple times THEN the system SHALL return identical scores (deterministic)
3. WHEN scoring papers THEN the system SHALL use a single, consolidated algorithm for all pipelines
4. IF a paper lacks certain metadata THEN the system SHALL apply graceful degradation with documented default values (0.5 for missing optional fields)
5. WHEN the QualityIntelligenceService is instantiated THEN it SHALL validate that configured weights sum to 1.0 (±0.01)
6. WHEN scoring THEN the system SHALL return `ScoredPaper` objects (not mutate input PaperMetadata)

### Requirement 2: Consolidated Venue Scoring

**User Story:** As a system maintainer, I want a single source of truth for venue quality scores, so that I can update venue rankings in one place and have changes apply consistently.

#### Acceptance Criteria

1. WHEN venue scores are loaded THEN the system SHALL read from the single authoritative YAML file (`src/data/venue_scores.yaml`)
2. WHEN loading venue scores THEN the system SHALL normalize the 0-30 YAML scale to 0-1 by dividing by 30.0
3. WHEN a venue is matched THEN the system SHALL use advanced normalization: lowercase, remove digits, remove special characters, remove common words ("proceedings", "conference", "journal", "international")
4. IF a venue is not found in the data source THEN the system SHALL return a configurable default score (0.5 on 0-1 scale, equivalent to 15/30)
5. WHEN matching venues THEN the system SHALL try exact match first, then substring matching
6. **DECISION:** ArXiv venue score SHALL be updated to 0.5 in YAML (15/30 → 0.5) as a balanced compromise between 0.33 (too strict) and 0.60 (too lenient)

### Requirement 3: Standardized Scoring Components

**User Story:** As a data scientist, I want transparent, well-documented scoring algorithms, so that I can understand and explain why papers are ranked as they are.

#### Acceptance Criteria

1. WHEN calculating citation scores THEN the system SHALL use: `min(1.0, log1p(citations) / 10.0)` PLUS influential citation bonus: `min(0.1, influential_count * 0.01)` if available
   - **Rationale:** Preserves valuable influential citation signal from QualityScorer while using log1p normalization
2. WHEN calculating recency scores THEN the system SHALL use half-life decay: `max(0.1, 1.0 / (1 + 0.2 * years_old))`
   - **Rationale:** Uses existing Phase 6 decay rate (0.2) for consistency
3. WHEN calculating completeness scores THEN the system SHALL evaluate 5 fields:
   - Abstract (minimum 50 chars): 0.30 weight
   - Authors (at least 1): 0.20 weight
   - Venue: 0.20 weight
   - PDF URL (open_access_pdf or pdf_available): 0.20 weight
   - DOI: 0.10 weight
   - **Note:** This changes from QualityScorer's 3-field model (Abstract=0.5, Authors=0.3, DOI=0.2)
4. WHEN calculating engagement scores THEN the system SHALL use: `min(1.0, log1p(upvotes) / 7.0)` for platforms that provide upvotes
5. IF engagement data is unavailable (upvotes=0 or None) THEN the system SHALL use neutral score (0.5) to avoid penalizing non-HuggingFace papers
6. IF author h-index data is unavailable THEN the system SHALL use neutral score (0.5) until author service is implemented

### Requirement 4: Configurable Weights with Sensible Defaults

**User Story:** As a pipeline operator, I want to configure scoring weights for different use cases, so that I can tune rankings for specific research domains.

#### Acceptance Criteria

1. WHEN weights are not specified THEN the system SHALL use defaults: citation=0.25, venue=0.20, recency=0.20, engagement=0.15, completeness=0.10, author=0.10
   - **Note:** This changes from QualityScorer's 4-weight model (0.40, 0.30, 0.20, 0.10). Papers will rank differently - this is intentional to support richer signals.
2. WHEN custom weights are provided THEN the system SHALL validate they sum to 1.0 (±0.01)
3. IF weights validation fails THEN the system SHALL raise `ValueError` with message: "Weights must sum to 1.0 (±0.01), got {actual_sum}"
4. WHEN weights are configured THEN the system SHALL persist them in a `QualityWeights` model for traceability
5. IF a weight is set to 0.0 THEN the system SHALL skip that scoring component entirely for efficiency

### Requirement 5: Backward Compatibility Layer

**User Story:** As a developer maintaining existing integrations, I want the new service to be a drop-in replacement, so that I don't need to rewrite calling code immediately.

#### Acceptance Criteria

1. WHEN migrating from QualityScorer THEN the system SHALL provide a `score_legacy()` method returning 0-100 scale scores
2. WHEN migrating from QualityScorer THEN the system SHALL provide a `rank_papers_legacy()` method that mutates `paper.quality_score` (0-100) and returns `List[PaperMetadata]`
3. WHEN migrating from QualityFilterService THEN the system SHALL accept the same input types via `filter_and_score()` method returning `List[ScoredPaper]`
4. WHEN the deprecated methods are called THEN the system SHALL emit deprecation warnings via `structlog.warning("deprecated_method_called", method=..., replacement=...)`
5. WITHIN 2 release cycles (or Phase 9) THEN the compatibility layer SHALL be removed and legacy callers updated

### Requirement 6: DiscoveryService Unification

**User Story:** As a user of the discovery API, I want a single search method that provides quality-scored results, so that I don't need to choose between "basic" and "enhanced" search.

#### Acceptance Criteria

1. WHEN `DiscoveryService.search()` is called THEN the system SHALL use the unified QualityIntelligenceService
2. WHEN `DiscoveryService.enhanced_search()` is called THEN the system SHALL route to the same scoring logic as basic search (while preserving query decomposition and relevance ranking)
3. WHEN `DiscoveryService.multi_source_search()` is called THEN the system SHALL use the same quality scoring
4. IF the `enhanced_search` method is called THEN it SHALL continue to work but log deprecation warning with guidance to use `search()` with `enhanced=True` parameter
5. WHEN filtering by quality THEN the system SHALL accept thresholds on the 0.0-1.0 scale only
6. WHEN returning results THEN the system SHALL include a `quality_score` field (0.0-1.0) on all paper objects

### Requirement 7: Quality Tier Classification

**User Story:** As a research consumer, I want papers categorized into quality tiers (excellent, good, fair, low), so that I can quickly identify top-tier research.

#### Acceptance Criteria

1. WHEN a paper has score >= 0.80 THEN the system SHALL classify it as "excellent"
2. WHEN a paper has score >= 0.60 AND < 0.80 THEN the system SHALL classify it as "good"
3. WHEN a paper has score >= 0.40 AND < 0.60 THEN the system SHALL classify it as "fair"
4. WHEN a paper has score < 0.40 THEN the system SHALL classify it as "low"
5. WHEN tier thresholds need adjustment THEN the system SHALL support configuration via `QualityTierConfig` model
6. **Note:** These thresholds are equivalent to QualityScorer's 80/60/40 on 0-100 scale

### Requirement 8: Citation Count Pre-Filtering

**User Story:** As a researcher, I want to optionally filter out papers with very low citation counts before scoring, so that I can focus on papers with demonstrated impact.

#### Acceptance Criteria

1. WHEN `min_citations` parameter is provided THEN the system SHALL filter papers with `citation_count < min_citations` BEFORE quality scoring
2. WHEN `min_citations` is 0 (default) THEN the system SHALL include all papers (no pre-filtering)
3. WHEN papers are pre-filtered THEN the system SHALL log the count: `structlog.info("papers_pre_filtered", original=X, after_filter=Y, min_citations=Z)`
4. **Rationale:** Preserves useful capability from QualityFilterService

## Non-Functional Requirements

### Code Architecture and Modularity

- **Single Responsibility Principle**: QualityIntelligenceService handles scoring only; venue data loading is delegated to VenueRepository
- **Modular Design**: Each scoring component (citation, venue, recency, engagement, completeness, author) is a separate, testable private method
- **Dependency Management**: Service depends on abstractions (VenueRepository protocol) not concrete implementations
- **Clear Interfaces**: Public API consists of:
  - `score_paper(paper: PaperMetadata) -> ScoredPaper`
  - `score_papers(papers: List[PaperMetadata]) -> List[ScoredPaper]`
  - `filter_by_quality(papers: List[PaperMetadata], min_score: float) -> List[ScoredPaper]`
  - `get_tier(score: float) -> str`
  - Legacy: `score_legacy()`, `rank_papers_legacy()`, `filter_and_score()`

### Performance

- Scoring a single paper SHALL complete in < 1ms (excluding I/O)
- Batch scoring of 1000 papers SHALL complete in < 500ms
- Venue data SHALL be cached in memory after first load (lazy initialization)
- No external API calls during scoring (all data local)

### Security

- Venue data file path SHALL be validated to prevent path traversal (use `Path.resolve()` and check within allowed directory)
- No user-supplied data SHALL be used in file paths
- Logging SHALL NOT include paper abstracts or full content (potential PII)
- Log only: paper_id, title[:50], scores, final_score

### Reliability

- Service SHALL handle missing/null fields gracefully without exceptions
- Service SHALL be stateless (no mutable instance state between calls)
- All scoring methods SHALL be deterministic (same input = same output)
- Service SHALL include comprehensive unit tests with ≥99% coverage

### Usability

- Error messages SHALL clearly indicate which validation failed and expected values
- Deprecation warnings SHALL include migration guidance: method name, replacement, and link to documentation
- API documentation SHALL include examples for common use cases

## Behavioral Changes Summary

**The following behaviors will change from QualityScorer to QualityIntelligenceService:**

| Behavior | Before (QualityScorer) | After (QualityIntelligenceService) | Impact |
|----------|------------------------|-----------------------------------|--------|
| Output scale | 0-100 | 0-1 | Thresholds need updating |
| ArXiv score | 0.33 | 0.50 | ArXiv papers score higher |
| Signal count | 4 | 6 | More nuanced scoring |
| Weight distribution | citation-heavy (40%) | balanced (25%) | Different rankings |
| Completeness fields | 3 fields | 5 fields | More granular completeness |
| Abstract weight | 0.5 | 0.3 | Less emphasis on abstract |
| Output type | Mutated PaperMetadata | New ScoredPaper | Different return type |
| Engagement handling | N/A | 0.5 default | Neutral for missing data |

## Migration Strategy

### Phase 1: Create QualityIntelligenceService (Non-Breaking)
- Implement new service alongside existing services
- Add comprehensive tests (≥99% coverage)
- No changes to existing code paths
- Update ArXiv score in `venue_scores.yaml` to 15 (0.5 normalized)

### Phase 2: Add Compatibility Layer
- Add adapter methods for legacy callers (`score_legacy`, `rank_papers_legacy`, `filter_and_score`)
- Emit deprecation warnings with migration guidance
- Update DiscoveryService to use new service internally (behind feature flag initially)

### Phase 3: Update Callers (Breaking)
- Update all direct callers to use new service
- Remove QualityScorer class (archive to `_deprecated/`)
- Remove QualityFilterService class (archive to `_deprecated/`)
- Update documentation

### Phase 4: Cleanup
- Remove compatibility layer
- Remove deprecated methods
- Remove archived classes
- Update all tests to use new service exclusively

## Appendix: Algorithm Comparison

### Citation Score Comparison (100 citations)

```
QualityScorer:     log10(101) / 3.0 = 0.67
QualityFilterService: log1p(100) / 10.0 = 0.46
New (with bonus):  log1p(100) / 10.0 + bonus = 0.46 + 0.05 = 0.51
```

### Recency Score Comparison (5 years old)

```
QualityScorer:     0.50 (tiered)
QualityFilterService: 1/(1 + 0.2*5) = 0.50 (matches!)
New:               1/(1 + 0.2*5) = 0.50
```

### Venue Score Comparison (ArXiv)

```
QualityScorer:     10/30 = 0.33
QualityFilterService: 0.60 (hardcoded)
New (after YAML update): 15/30 = 0.50 (compromise)
```

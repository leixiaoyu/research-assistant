# Requirements Document: Discovery Orchestration Consolidation

## Introduction

This document extends the Quality Scoring Consolidation specification to address the broader **Discovery Fragmentation** issue identified by the senior engineer. While the primary spec consolidates quality scoring, this companion document addresses the fragmented discovery orchestration layer.

**Current State:** Three discovery methods with inconsistent interfaces:
- `search()` - Basic discovery, returns `List[PaperMetadata]`
- `enhanced_search()` - Phase 6 pipeline, returns `DiscoveryResult`
- `multi_source_search()` - Phase 7.2, returns `List[PaperMetadata]`

**Problem Impact:**
- Inconsistent return types break downstream synthesis
- Duplicate query enhancement logic (QueryDecomposer vs QueryExpander)
- No unified observability across discovery methods
- Configuration fragmentation (3 separate config models)
- Quality/relevance scores lost in basic and multi-source methods

**Goal:** Consolidate into a unified discovery API with tiered complexity modes while preserving all Phase 6 and Phase 7.2 capabilities.

## Current State Analysis

### Discovery Methods Comparison

| Aspect | `search()` | `enhanced_search()` | `multi_source_search()` |
|--------|------------|---------------------|-------------------------|
| **Return Type** | `List[PaperMetadata]` | `DiscoveryResult` | `List[PaperMetadata]` |
| **Contains Scores** | No | Yes (ScoredPaper) | No |
| **Contains Metrics** | No | Yes (DiscoveryMetrics) | No (separate Phase72Stats) |
| **Query Processing** | None | QueryDecomposer | QueryExpander |
| **Provider Strategy** | Single (with fallback) | All concurrent | All concurrent |
| **Citation Exploration** | No | No | Yes |
| **Result Aggregation** | Basic merge | Dedup + rank | Dedup + rank + relevance filter |

### Query Processing Services Comparison

| Aspect | QueryDecomposer (Phase 6) | QueryExpander (Phase 7.2) |
|--------|---------------------------|---------------------------|
| **Location** | `src/services/query_decomposer.py` | `src/utils/query_expander.py` |
| **Return Type** | `List[DecomposedQuery]` | `List[str]` |
| **Has Metadata** | Yes (focus, weight) | No |
| **Caching** | LRU (max 1000) | Simple dict |
| **Focus Areas** | 5 categories (methodology, etc.) | None |

### Configuration Fragmentation

| Config Model | Used By | Key Settings |
|--------------|---------|--------------|
| `ProviderSelectionConfig` | `search()` | auto_select, fallback, preference_order |
| `EnhancedDiscoveryConfig` | `enhanced_search()` | decomposition, quality, relevance |
| `QueryExpansionConfig` | `multi_source_search()` | max_variants, cache |
| `CitationExplorationConfig` | `multi_source_search()` | forward, backward, depth |
| `AggregationConfig` | `multi_source_search()` | ranking_weights, relevance_filter |

## Requirements

### Requirement D1: Unified Query Intelligence Service

**User Story:** As a discovery pipeline developer, I want a single query enhancement service that provides both decomposition and expansion capabilities, so that I can apply consistent query intelligence across all discovery modes.

#### Acceptance Criteria

1. WHEN the QueryIntelligenceService is instantiated THEN it SHALL support multiple enhancement strategies: `decompose`, `expand`, `hybrid`
2. WHEN `strategy="decompose"` THEN the system SHALL break queries into focused sub-queries with metadata (focus area, weight)
3. WHEN `strategy="expand"` THEN the system SHALL generate semantically related query variants
4. WHEN `strategy="hybrid"` THEN the system SHALL first decompose, then expand each sub-query
5. WHEN enhancing queries THEN the system SHALL return a unified `EnhancedQuery` model:
   ```python
   class EnhancedQuery(BaseModel):
       query: str                           # The query text
       focus: Optional[QueryFocus] = None   # Focus area if decomposed
       weight: float = 1.0                  # Weight for result merging
       is_original: bool = False            # True for the original query
       parent_query: Optional[str] = None   # Parent query if expanded from decomposition
   ```
6. WHEN caching is enabled THEN the system SHALL use LRU eviction (max 1000 entries) with hash-based keys
7. IF LLM service is unavailable THEN the system SHALL return the original query with `is_original=True`

### Requirement D2: Tiered Discovery API

**User Story:** As a user of the discovery API, I want a single entry point with configurable complexity modes, so that I can choose the right trade-off between speed and comprehensiveness.

#### Acceptance Criteria

1. WHEN `DiscoveryService.discover()` is called THEN it SHALL be the single entry point for all discovery operations
2. WHEN `mode=DiscoveryMode.SURFACE` THEN the system SHALL perform fast discovery:
   - Single best provider (auto-selected or specified)
   - No query enhancement
   - Basic quality scoring
   - Returns in < 5 seconds
3. WHEN `mode=DiscoveryMode.STANDARD` THEN the system SHALL perform balanced discovery:
   - Query decomposition (5 sub-queries)
   - All providers queried concurrently
   - Quality filtering applied
   - Returns in < 30 seconds
4. WHEN `mode=DiscoveryMode.DEEP` THEN the system SHALL perform comprehensive discovery:
   - Hybrid query enhancement (decompose + expand)
   - All providers queried concurrently
   - Citation exploration (forward + backward)
   - Quality filtering + relevance ranking
   - Result aggregation with all signals
   - Returns in < 120 seconds
5. WHEN the deprecated methods (`search`, `enhanced_search`, `multi_source_search`) are called THEN the system SHALL route to `discover()` with appropriate mode and emit deprecation warnings
6. WHEN `discover()` is called THEN the system SHALL always return `DiscoveryResult` regardless of mode

### Requirement D3: Unified Discovery Result

**User Story:** As a downstream synthesis pipeline, I want consistent result objects from all discovery methods, so that I can process papers without handling multiple return types.

#### Acceptance Criteria

1. WHEN any discovery method completes THEN it SHALL return a `DiscoveryResult` object containing:
   ```python
   class DiscoveryResult(BaseModel):
       papers: List[ScoredPaper]            # Always scored, even if basic scoring
       metrics: DiscoveryMetrics            # Always present
       queries_used: List[EnhancedQuery]    # Query enhancement trace
       source_breakdown: Dict[str, int]     # Papers per source
       mode: DiscoveryMode                  # Mode used
   ```
2. WHEN `mode=SURFACE` THEN `metrics` SHALL include: papers_discovered, duration_ms, providers_queried
3. WHEN `mode=STANDARD` THEN `metrics` SHALL additionally include: queries_generated, papers_after_quality_filter
4. WHEN `mode=DEEP` THEN `metrics` SHALL additionally include: forward_citations_found, backward_citations_found, papers_after_relevance_filter
5. WHEN papers are returned THEN each `ScoredPaper` SHALL have `quality_score` populated (using QualityIntelligenceService)
6. WHEN source tracking is available THEN `source_breakdown` SHALL include counts for: arxiv, semantic_scholar, openalex, huggingface, forward_citations, backward_citations

### Requirement D4: Unified Discovery Configuration

**User Story:** As a pipeline operator, I want a single configuration model for all discovery modes, so that I don't need to manage multiple overlapping configurations.

#### Acceptance Criteria

1. WHEN configuring discovery THEN the system SHALL accept a unified `DiscoveryPipelineConfig`:
   ```python
   class DiscoveryPipelineConfig(BaseModel):
       # Mode selection
       mode: DiscoveryMode = DiscoveryMode.STANDARD

       # Provider configuration
       providers: List[ProviderType] = [ARXIV, SEMANTIC_SCHOLAR, OPENALEX, HUGGINGFACE]
       provider_timeout_seconds: float = 30.0
       fallback_enabled: bool = True

       # Query enhancement
       query_enhancement: QueryEnhancementConfig

       # Citation exploration (DEEP mode only)
       citation_exploration: CitationExplorationConfig

       # Quality filtering (uses QualityIntelligenceService)
       min_quality_score: float = 0.3
       min_citations: int = 0

       # Relevance filtering (STANDARD and DEEP modes)
       enable_relevance_ranking: bool = True
       min_relevance_score: float = 0.5

       # Result limits
       max_papers: int = 50
   ```
2. WHEN `mode=SURFACE` THEN the system SHALL ignore `citation_exploration` and `relevance_ranking` settings
3. WHEN `mode=STANDARD` THEN the system SHALL ignore `citation_exploration` settings
4. WHEN legacy configuration objects are provided THEN the system SHALL convert them to unified config with deprecation warnings

### Requirement D5: Backward Compatibility Layer

**User Story:** As a developer maintaining existing integrations, I want the new unified API to be backward compatible, so that I don't need to rewrite calling code immediately.

#### Acceptance Criteria

1. WHEN `DiscoveryService.search()` is called THEN the system SHALL:
   - Route to `discover(topic, mode=SURFACE)`
   - Convert `DiscoveryResult.papers` to `List[PaperMetadata]` for return
   - Emit deprecation warning with migration guidance
2. WHEN `DiscoveryService.enhanced_search()` is called THEN the system SHALL:
   - Route to `discover(topic, mode=STANDARD)`
   - Return `DiscoveryResult` directly (already compatible)
   - Emit deprecation warning with migration guidance
3. WHEN `DiscoveryService.multi_source_search()` is called THEN the system SHALL:
   - Route to `discover(topic, mode=DEEP)`
   - Convert `DiscoveryResult.papers` to `List[PaperMetadata]` for return
   - Emit deprecation warning with migration guidance
4. WITHIN 2 release cycles (or Phase 9) THEN the deprecated methods SHALL be removed

### Requirement D6: Discovery Phase Integration

**User Story:** As the orchestration layer, I want the discovery phase to use the unified API seamlessly, so that all discovery runs benefit from consistent behavior.

#### Acceptance Criteria

1. WHEN `DiscoveryPhase.execute()` runs THEN it SHALL call `DiscoveryService.discover()` with appropriate mode based on config
2. WHEN `multi_source_enabled=True` THEN the phase SHALL use `mode=DEEP`
3. WHEN `multi_source_enabled=False` AND `settings.enhanced_discovery is not None` THEN the phase SHALL use `mode=STANDARD`
4. WHEN neither is configured THEN the phase SHALL use `mode=SURFACE`
5. Precedence: `multi_source_enabled` (DEEP) SHALL take precedence over `enhanced_discovery` (STANDARD) when both are set
6. WHEN discovery completes THEN the phase SHALL use `DiscoveryResult.metrics` directly (no separate stats collection)
7. WHEN discovery completes THEN the phase SHALL preserve `DiscoveryResult.source_breakdown` for reporting

## Non-Functional Requirements

### Code Architecture and Modularity

- **Single Responsibility**: QueryIntelligenceService handles query enhancement only
- **Strategy Pattern**: Discovery modes implemented as composable strategies
- **Dependency Injection**: All services injectable for testing
- **Clear Interfaces**:
  - `QueryIntelligenceService.enhance(query, strategy) -> List[EnhancedQuery]`
  - `DiscoveryService.discover(topic, config) -> DiscoveryResult`

### Performance

| Mode | Target Latency | Typical Paper Count |
|------|---------------|---------------------|
| SURFACE | < 5 seconds | 10-30 papers |
| STANDARD | < 30 seconds | 30-100 papers |
| DEEP | < 120 seconds | 50-200 papers |

- Query enhancement caching SHALL reduce LLM calls by > 80% for repeated queries
- Provider queries SHALL execute concurrently (not sequentially)
- Citation exploration SHALL be parallelized

### Reliability

- Service SHALL handle provider failures gracefully (continue with remaining providers)
- Service SHALL handle LLM failures gracefully (fall back to simpler modes)
- All methods SHALL be idempotent (same input = same output structure)
- Timeouts SHALL be configurable per mode

### Observability

- All discovery runs SHALL emit structured logs with: mode, duration, paper_count, provider_breakdown
- Metrics SHALL be collected for: cache hit rates, provider latencies, LLM call counts
- Errors SHALL be logged with full context for debugging

## Migration Strategy

### Phase 1: Create QueryIntelligenceService (Non-Breaking)
- Implement new service alongside existing QueryDecomposer and QueryExpander
- Support all three strategies (decompose, expand, hybrid)
- Add comprehensive tests
- No changes to existing code paths

### Phase 2: Create Unified discover() Method (Non-Breaking)
- Add `discover(topic, mode, config)` method to DiscoveryService
- Implement SURFACE, STANDARD, DEEP modes using existing components
- Return DiscoveryResult for all modes
- No changes to existing methods

### Phase 3: Add Compatibility Layer
- Update `search()`, `enhanced_search()`, `multi_source_search()` to route to `discover()`
- Emit deprecation warnings
- Update DiscoveryPhase to use `discover()` internally

### Phase 4: Update Callers (Breaking)
- Update all direct callers to use `discover()` with appropriate mode
- Remove deprecated methods
- Remove QueryDecomposer and QueryExpander (archive to `_deprecated/`)
- Update documentation

## Appendix: Discovery Mode Comparison

### Feature Matrix

| Feature | SURFACE | STANDARD | DEEP |
|---------|---------|----------|------|
| Query Enhancement | None | Decompose | Hybrid |
| Providers Queried | 1 (best) | All | All |
| Quality Scoring | Basic | Full | Full |
| Relevance Ranking | No | Yes | Yes |
| Citation Exploration | No | No | Yes |
| Result Aggregation | Basic | Dedup | Full |
| Typical Latency | < 5s | < 30s | < 120s |

### Mode Selection Guide

| Use Case | Recommended Mode |
|----------|------------------|
| Quick lookup / testing | SURFACE |
| Regular research discovery | STANDARD |
| Comprehensive literature review | DEEP |
| Real-time applications | SURFACE |
| Batch processing | STANDARD or DEEP |
| Citation analysis | DEEP |

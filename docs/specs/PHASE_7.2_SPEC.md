# Requirements Document: Phase 7.2 - Discovery Expansion

## Introduction

Phase 7.2 expands paper discovery capabilities beyond the single-source, keyword-only approach. This milestone adds:

1. **Multi-source paper discovery** - Integrate OpenAlex, Paper Search MCP, and additional academic APIs
2. **Citation network exploration** - Discover papers through forward/backward citation traversal
3. **Query expansion** - Generate related queries from topic keywords for broader coverage
4. **Source aggregation and ranking** - Merge results from multiple sources with intelligent deduplication

These features address the limitation of returning the same papers by actively broadening the search space.

## Alignment with Product Vision

This feature supports ARISP's mission to discover cutting-edge research comprehensively:

- **Broader coverage**: Multiple sources capture papers missed by any single API
- **Deeper discovery**: Citation networks reveal foundational and derivative works
- **Research continuity**: Query expansion surfaces related research directions
- **Quality improvement**: Cross-source validation increases paper relevance

## Dependencies

- **Phase 7.1 (Required)**: Foundation infrastructure (registry filtering, incremental timeframes)
- **Phase 3.5 (Complete)**: RegistryService for cross-source deduplication

## Requirements

### Requirement 1: OpenAlex Provider Integration

**User Story:** As a researcher, I want the pipeline to search OpenAlex in addition to existing sources, so that I can discover papers from a broader academic catalog.

#### Acceptance Criteria

1. WHEN `config.providers` includes `openalex` THEN the system SHALL query OpenAlex API for papers
2. WHEN querying OpenAlex THEN the system SHALL use the `pyalex` Python library
3. WHEN OpenAlex returns results THEN the system SHALL map them to `PaperMetadata` format
4. IF OpenAlex API is unavailable THEN the system SHALL log warning and continue with other providers
5. WHEN OpenAlex returns papers THEN the system SHALL extract: title, abstract, DOI, publication_date, open_access_pdf, citation_count
6. IF `OPENALEX_API_KEY` environment variable is set THEN the system SHALL use polite pool (faster rate limits)

### Requirement 2: Paper Search MCP Integration

**User Story:** As a researcher, I want the pipeline to leverage Paper Search MCP for unified multi-source queries, so that I can search arXiv, PubMed, bioRxiv, and Google Scholar simultaneously.

#### Acceptance Criteria

1. WHEN `config.providers` includes `paper_search_mcp` THEN the system SHALL connect to Paper Search MCP server
2. WHEN Paper Search MCP is configured THEN the system SHALL query all supported sources (arXiv, PubMed, bioRxiv, medRxiv, Google Scholar, Semantic Scholar)
3. IF Paper Search MCP is not available THEN the system SHALL fall back to direct provider queries
4. WHEN MCP returns results THEN the system SHALL deduplicate across sources using DOI/title matching
5. WHEN MCP query completes THEN the system SHALL log source breakdown (papers per source)
6. IF a source within MCP fails THEN the system SHALL continue with remaining sources

### Requirement 3: Forward Citation Discovery

**User Story:** As a researcher, I want the pipeline to find papers that cite my discovered papers, so that I can track how research has evolved and find newer related work.

#### Acceptance Criteria

1. WHEN a paper is discovered AND `config.citation_exploration.forward` is True THEN the system SHALL fetch papers citing it
2. WHEN fetching forward citations THEN the system SHALL use Semantic Scholar citations API
3. IF forward citations exceed `config.citation_exploration.max_forward_per_paper` THEN the system SHALL limit to top-cited papers
4. WHEN forward citations are discovered THEN the system SHALL mark them with `discovery_method: forward_citation`
5. IF a citing paper is already in registry THEN the system SHALL skip it (no duplicate processing)
6. WHEN forward citation discovery completes THEN the system SHALL log count of new papers discovered

### Requirement 4: Backward Citation Discovery

**User Story:** As a researcher, I want the pipeline to find papers referenced by my discovered papers, so that I can understand foundational work and research lineage.

#### Acceptance Criteria

1. WHEN a paper is discovered AND `config.citation_exploration.backward` is True THEN the system SHALL fetch its references
2. WHEN fetching backward citations THEN the system SHALL use Semantic Scholar references API
3. IF backward citations exceed `config.citation_exploration.max_backward_per_paper` THEN the system SHALL limit to most-cited references
4. WHEN backward citations are discovered THEN the system SHALL mark them with `discovery_method: backward_citation`
5. IF a referenced paper is already in registry THEN the system SHALL skip it
6. WHEN backward citation depth is configured THEN the system SHALL NOT exceed `max_citation_depth` levels

### Requirement 5: Query Expansion

**User Story:** As a researcher, I want the pipeline to automatically generate related queries from my topic, so that I can discover papers using alternative terminology.

#### Acceptance Criteria

1. WHEN `config.query_expansion.enabled` is True THEN the system SHALL generate expanded queries for each topic
2. WHEN expanding queries THEN the system SHALL use LLM to generate 3-5 semantically related queries
3. IF query expansion is enabled THEN the system SHALL cache expanded queries per topic (avoid re-generating)
4. WHEN expanded queries return results THEN the system SHALL deduplicate against original query results
5. IF expanded query returns 0 new papers THEN the system SHALL log and skip future expansions of that variant
6. WHEN query expansion completes THEN the system SHALL log: original_query, expanded_queries, papers_per_query

### Requirement 6: Multi-Source Result Aggregation

**User Story:** As a researcher, I want papers from multiple sources to be intelligently merged and ranked, so that I receive a unified, deduplicated list of the most relevant papers.

#### Acceptance Criteria

1. WHEN multiple providers return results THEN the system SHALL merge into single deduplicated list
2. WHEN merging results THEN the system SHALL use DOI as primary dedup key, then ArXiv ID, then title similarity
3. WHEN a paper appears in multiple sources THEN the system SHALL merge metadata (prefer richest source)
4. WHEN ranking merged results THEN the system SHALL score by: citation_count, recency, source_count, pdf_availability
5. IF `config.aggregation.max_papers_per_topic` is set THEN the system SHALL return top-ranked papers only
6. WHEN aggregation completes THEN the system SHALL log: total_raw, after_dedup, source_breakdown

## Non-Functional Requirements

### Code Architecture and Modularity

- **Single Responsibility Principle**: Each provider in separate module under `src/services/providers/`
- **Modular Design**: `CitationExplorer` class handles forward/backward traversal
- **Dependency Management**: Provider interface allows easy addition of new sources
- **Clear Interfaces**: `ProviderProtocol` defines standard search/fetch methods
- **Backward Compatibility**: New providers are opt-in via config

### Performance

- Multi-source queries should execute in parallel (asyncio.gather)
- Citation exploration should respect rate limits (Semantic Scholar: 100 req/min)
- Query expansion LLM calls should be cached to avoid repeated cost
- Note: Discovery latency is not a priority metric - thoroughness of research is prioritized over speed

### Security

- OpenAlex API key stored in environment variable (not config file)
- MCP server connections use secure protocols
- No user credentials exposed in logs

### Reliability

- Provider failures should not break entire discovery
- Graceful degradation when sources are unavailable
- Retry logic with exponential backoff for transient failures
- Circuit breaker pattern for repeatedly failing sources

### Usability

- Config schema clearly documents all new options
- CLI command to test individual providers: `python -m src.cli test-provider openalex`
- Logs clearly indicate which source discovered each paper
- Slack notification includes source breakdown

## Configuration Schema

```yaml
# research_config.yaml additions
settings:
  providers:
    - arxiv          # Existing
    - semantic_scholar  # Existing
    - openalex       # NEW
    - paper_search_mcp  # NEW (requires MCP server)

  citation_exploration:
    enabled: true
    forward: true
    backward: true
    max_forward_per_paper: 10
    max_backward_per_paper: 10
    max_citation_depth: 1

  query_expansion:
    enabled: true
    max_variants: 5
    cache_expansions: true

  aggregation:
    max_papers_per_topic: 50
    ranking_weights:
      citation_count: 0.3
      recency: 0.3
      source_count: 0.2
      pdf_availability: 0.2
```

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Unique papers per topic | 2x increase vs Phase 7.1 | Compare daily run outputs |
| Source diversity | At least 3 sources contributing | Source breakdown logs |
| Citation network papers | At least 20% of discoveries from citations | `discovery_method` stats |
| Query expansion effectiveness | At least 10% new papers from expanded queries | Papers from expanded queries |
| Deep research coverage | At least 2 levels of citation depth explored | Citation traversal logs |
| Cross-source discovery rate | At least 30% of papers found in multiple sources | Deduplication stats |

## Out of Scope (Deferred to Phase 7.3)

- Human feedback integration
- Preference learning and personalization
- Semantic similarity search with embeddings
- "Find more like this" functionality

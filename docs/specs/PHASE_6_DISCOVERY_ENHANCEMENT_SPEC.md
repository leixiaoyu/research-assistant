# Phase 6: Discovery Enhancement Specification

**Status:** PROPOSED
**Author:** Claude Code
**Date:** 2026-02-28
**PR:** TBD

---

## Executive Summary

This specification proposes comprehensive enhancements to the paper discovery pipeline to address low relevance and quality issues observed in the current implementation. Despite retrieving 90+ papers, the synthesis phase covered 0 topics due to poor paper-query relevance matching.

### Key Problems

| Problem | Current State | Impact |
|---------|---------------|--------|
| Single-query retrieval | One query per topic | Misses semantically related papers |
| No relevance scoring | API default ordering | Irrelevant papers included |
| Limited quality signals | Basic citation filter | Low-impact papers included |
| Single source | Semantic Scholar only | Limited coverage |

### Proposed Solution

Implement a **4-stage intelligent discovery pipeline**:

1. **Query Decomposition** - LLM-generated sub-queries
2. **Multi-Source Retrieval** - ArXiv + Semantic Scholar + OpenAlex
3. **Quality Filtering** - Citation, venue, metadata signals
4. **LLM Relevance Re-Ranking** - Semantic relevance scoring

**Expected Improvement:** +50-70% relevant paper yield based on literature benchmarks.

---

## Table of Contents

1. [Goals and Non-Goals](#1-goals-and-non-goals)
2. [Architecture Overview](#2-architecture-overview)
3. [Component Specifications](#3-component-specifications)
4. [Data Models](#4-data-models)
5. [API Integration](#5-api-integration)
6. [Implementation Plan](#6-implementation-plan)
7. [Testing Strategy](#7-testing-strategy)
8. [Success Metrics](#8-success-metrics)
9. [Risks and Mitigations](#9-risks-and-mitigations)
10. [Appendix](#10-appendix)

---

## 1. Goals and Non-Goals

### Goals

- **G1:** Improve paper-query relevance by implementing LLM-based relevance scoring
- **G2:** Increase paper coverage by adding OpenAlex as a secondary source
- **G3:** Improve paper quality by implementing multi-signal quality filtering
- **G4:** Improve query coverage by implementing LLM-based query decomposition
- **G5:** Maintain backward compatibility with existing configuration format
- **G6:** Ensure only academic papers are retrieved (no blogs, news, preprints optionally)

### Non-Goals

- **NG1:** Real-time paper monitoring (out of scope for Phase 6)
- **NG2:** Citation network analysis (future enhancement)
- **NG3:** Full-text semantic search (requires infrastructure changes)
- **NG4:** User feedback loop for relevance training (future enhancement)

---

## 2. Architecture Overview

### Current Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│   Config    │────▶│DiscoveryService  │────▶│   Papers    │
│   (query)   │     │(single provider) │     │  (unranked) │
└─────────────┘     └──────────────────┘     └─────────────┘
```

### Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        EnhancedDiscoveryService                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌────────────────┐                                                      │
│  │ QueryDecomposer│  Stage 1: Generate 3-5 focused sub-queries          │
│  │    (LLM)       │                                                      │
│  └───────┬────────┘                                                      │
│          │                                                               │
│          ▼                                                               │
│  ┌────────────────────────────────────────────────────────┐             │
│  │              MultiSourceRetriever                       │             │
│  │  ┌─────────┐  ┌─────────────────┐  ┌─────────────┐     │  Stage 2    │
│  │  │ ArXiv   │  │SemanticScholar  │  │  OpenAlex   │     │             │
│  │  │Provider │  │   Provider      │  │  Provider   │     │             │
│  │  └────┬────┘  └───────┬─────────┘  └──────┬──────┘     │             │
│  │       │               │                   │             │             │
│  │       └───────────────┼───────────────────┘             │             │
│  │                       ▼                                 │             │
│  │              ┌────────────────┐                         │             │
│  │              │  Deduplicator  │                         │             │
│  │              └────────────────┘                         │             │
│  └───────────────────────┬────────────────────────────────┘             │
│                          ▼                                               │
│  ┌────────────────────────────────────────────────────────┐             │
│  │              QualityFilterService                       │  Stage 3    │
│  │  • Citation threshold (configurable)                    │             │
│  │  • Venue quality (CORE ranking integration)             │             │
│  │  • Metadata completeness (abstract, authors)            │             │
│  │  • Publication type (journal, conference, preprint)     │             │
│  └───────────────────────┬────────────────────────────────┘             │
│                          ▼                                               │
│  ┌────────────────────────────────────────────────────────┐             │
│  │              RelevanceRanker (LLM)                      │  Stage 4    │
│  │  • Score each paper 0.0-1.0 for query relevance         │             │
│  │  • Filter papers below threshold (default: 0.5)         │             │
│  │  • Combine with quality score for final ranking         │             │
│  └───────────────────────┬────────────────────────────────┘             │
│                          ▼                                               │
│  ┌────────────────────────────────────────────────────────┐             │
│  │              Ranked, Relevant Papers                    │  Output     │
│  └────────────────────────────────────────────────────────┘             │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Specifications

### 3.1 QueryDecomposer

**Purpose:** Transform a broad research query into multiple focused sub-queries to improve recall.

**Location:** `src/services/query_decomposer.py`

**Interface:**

```python
class QueryDecomposer:
    """Decomposes research queries into focused sub-queries using LLM."""

    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service

    async def decompose(
        self,
        query: str,
        max_subqueries: int = 5,
        include_original: bool = True
    ) -> List[DecomposedQuery]:
        """
        Decompose a research query into focused sub-queries.

        Args:
            query: Original research query
            max_subqueries: Maximum sub-queries to generate (default: 5)
            include_original: Include original query in results (default: True)

        Returns:
            List of DecomposedQuery objects with query text and focus area
        """
        pass
```

**Prompt Template:**

```
You are an academic research expert. Decompose the following research query
into {max_subqueries} focused sub-queries that would help find relevant
academic papers.

Original Query: {query}

For each sub-query:
1. Focus on a specific aspect (methodology, application, comparison, etc.)
2. Use academic terminology appropriate for paper search
3. Include relevant synonyms and related concepts

Output format (JSON):
[
  {"query": "...", "focus": "methodology"},
  {"query": "...", "focus": "applications"},
  ...
]
```

**Example:**

```
Input: "Tree of Thoughts for machine translation"

Output:
[
  {"query": "Tree of Thoughts prompting technique", "focus": "methodology"},
  {"query": "reasoning-based approaches neural machine translation", "focus": "application"},
  {"query": "chain-of-thought vs tree-of-thought translation", "focus": "comparison"},
  {"query": "LLM prompting strategies translation quality", "focus": "related"},
  {"query": "structured reasoning machine translation NMT", "focus": "intersection"}
]
```

---

### 3.2 OpenAlexProvider

**Purpose:** Retrieve papers from OpenAlex API with comprehensive filtering.

**Location:** `src/services/providers/openalex.py`

**Key Features:**

- Free API with 100K requests/day
- Comprehensive filtering (50+ parameters)
- Field-weighted citation impact (FWCI)
- Open access metadata
- Institution and author linking

**Interface:**

```python
class OpenAlexProvider(DiscoveryProvider):
    """Search for papers using OpenAlex API.

    OpenAlex provides access to 260M+ scholarly works with comprehensive
    metadata including citations, venues, institutions, and open access status.

    API Details:
    - Endpoint: https://api.openalex.org/works
    - Method: GET
    - Rate limit: 100K requests/day (with polite pool)
    - No authentication required (email for polite pool)
    """

    BASE_URL = "https://api.openalex.org/works"

    def __init__(self, email: str = None):
        """Initialize with optional email for polite pool access."""
        self.email = email or os.getenv("OPENALEX_EMAIL")
        self.rate_limiter = RateLimiter(max_requests=100, window_seconds=1)

    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search OpenAlex for papers matching the topic."""
        pass

    def _build_filter(self, topic: ResearchTopic) -> str:
        """Build OpenAlex filter string from topic configuration."""
        filters = []

        # Title and abstract search
        filters.append(f"title_and_abstract.search:{topic.query}")

        # Quality filters
        if topic.min_citations:
            filters.append(f"cited_by_count:>{topic.min_citations}")

        # Date range
        if isinstance(topic.timeframe, TimeframeSinceYear):
            filters.append(f"publication_year:{topic.timeframe.year}-")
        elif isinstance(topic.timeframe, TimeframeRecent):
            # Convert to date
            start_date = self._calculate_start_date(topic.timeframe.value)
            filters.append(f"from_publication_date:{start_date}")

        # Open access filter
        if topic.require_pdf:
            filters.append("is_oa:true")

        # Exclude retractions
        filters.append("is_retracted:false")

        # Require abstract
        filters.append("has_abstract:true")

        return ",".join(filters)
```

**API Parameters:**

| Parameter | Usage | Example |
|-----------|-------|---------|
| `filter` | Combined filter string | `title_and_abstract.search:machine learning,is_oa:true` |
| `sort` | Result ordering | `cited_by_count:desc`, `relevance_score:desc` |
| `per_page` | Results per page | `50` (max 200) |
| `select` | Fields to return | `id,title,abstract_inverted_index,cited_by_count` |

---

### 3.3 QualityFilterService

**Purpose:** Filter papers based on multiple quality signals.

**Location:** `src/services/quality_filter_service.py`

**Quality Signals:**

| Signal | Source | Weight | Description |
|--------|--------|--------|-------------|
| `citation_score` | All APIs | 0.30 | Log-normalized citation count |
| `venue_score` | CORE/SJR | 0.25 | Venue quality tier (A*, A, B, C) |
| `recency_score` | Publication date | 0.20 | Decay over 5 years |
| `completeness_score` | Metadata | 0.15 | Has abstract, PDF, references |
| `author_score` | Author h-index | 0.10 | Max author h-index |

**Interface:**

```python
class QualityFilterService:
    """Multi-signal quality filtering for academic papers."""

    def __init__(
        self,
        min_citations: int = 0,
        min_quality_score: float = 0.3,
        venue_data_path: str = "data/venue_rankings.json"
    ):
        self.min_citations = min_citations
        self.min_quality_score = min_quality_score
        self.venue_scores = self._load_venue_scores(venue_data_path)

    def filter_and_score(
        self,
        papers: List[PaperMetadata],
        weights: Optional[QualityWeights] = None
    ) -> List[ScoredPaper]:
        """
        Filter papers by quality and compute composite scores.

        Args:
            papers: List of papers to filter
            weights: Optional custom weights for quality signals

        Returns:
            List of papers with quality scores, filtered by min_quality_score
        """
        pass

    def _calculate_citation_score(self, paper: PaperMetadata) -> float:
        """Logarithmic citation score (0-1 range)."""
        return min(1.0, math.log1p(paper.citation_count) / 10)

    def _calculate_venue_score(self, paper: PaperMetadata) -> float:
        """Venue quality score based on CORE/SJR rankings."""
        venue_key = self._normalize_venue(paper.venue)
        return self.venue_scores.get(venue_key, 0.5)  # Default: medium

    def _calculate_recency_score(self, paper: PaperMetadata) -> float:
        """Recency score with 5-year half-life decay."""
        years_old = datetime.now().year - paper.publication_year
        return max(0.1, 1.0 / (1 + 0.2 * years_old))
```

---

### 3.4 RelevanceRanker

**Purpose:** Score and rank papers by semantic relevance to the research query using LLM.

**Location:** `src/services/relevance_ranker.py`

**Interface:**

```python
class RelevanceRanker:
    """LLM-based semantic relevance ranking for academic papers."""

    def __init__(
        self,
        llm_service: LLMService,
        min_relevance_score: float = 0.5,
        batch_size: int = 10
    ):
        self.llm_service = llm_service
        self.min_relevance_score = min_relevance_score
        self.batch_size = batch_size

    async def rank(
        self,
        papers: List[PaperMetadata],
        query: str,
        top_k: Optional[int] = None
    ) -> List[RankedPaper]:
        """
        Rank papers by relevance to query.

        Args:
            papers: Papers to rank
            query: Original research query
            top_k: Return only top k papers (default: all above threshold)

        Returns:
            Papers ranked by relevance, filtered by min_relevance_score
        """
        pass

    async def _score_paper_batch(
        self,
        papers: List[PaperMetadata],
        query: str
    ) -> List[float]:
        """Score a batch of papers for relevance (0.0-1.0)."""
        pass
```

**Relevance Prompt:**

```
You are an academic research relevance evaluator. Score how relevant each paper
is to the research query on a scale of 0.0 to 1.0.

Research Query: {query}

Papers to evaluate:
{papers_json}

Scoring criteria:
- 0.9-1.0: Directly addresses the exact topic
- 0.7-0.8: Highly relevant methodology or application
- 0.5-0.6: Related but tangential
- 0.3-0.4: Loosely related
- 0.0-0.2: Not relevant

Output format (JSON array of scores in same order):
[0.85, 0.72, 0.45, ...]
```

**Batching Strategy:**

- Process papers in batches of 10 for efficiency
- Use concurrent batch processing with semaphore
- Cache scores for repeated queries

---

### 3.5 EnhancedDiscoveryService

**Purpose:** Orchestrate the 4-stage discovery pipeline.

**Location:** `src/services/enhanced_discovery_service.py`

**Interface:**

```python
class EnhancedDiscoveryService:
    """Enhanced paper discovery with multi-stage retrieval and ranking."""

    def __init__(
        self,
        providers: List[DiscoveryProvider],
        query_decomposer: QueryDecomposer,
        quality_filter: QualityFilterService,
        relevance_ranker: RelevanceRanker,
        config: EnhancedDiscoveryConfig
    ):
        self.providers = providers
        self.query_decomposer = query_decomposer
        self.quality_filter = quality_filter
        self.relevance_ranker = relevance_ranker
        self.config = config

    async def discover(
        self,
        topic: ResearchTopic
    ) -> DiscoveryResult:
        """
        Execute 4-stage discovery pipeline.

        Returns:
            DiscoveryResult with ranked papers and pipeline metrics
        """
        # Stage 1: Query Decomposition
        queries = await self.query_decomposer.decompose(topic.query)

        # Stage 2: Multi-Source Retrieval
        raw_papers = await self._retrieve_from_all_sources(queries, topic)

        # Stage 3: Quality Filtering
        quality_papers = self.quality_filter.filter_and_score(raw_papers)

        # Stage 4: Relevance Ranking
        ranked_papers = await self.relevance_ranker.rank(
            quality_papers,
            topic.query,
            top_k=topic.max_papers
        )

        return DiscoveryResult(
            papers=ranked_papers,
            metrics=self._build_metrics(queries, raw_papers, quality_papers, ranked_papers)
        )
```

---

## 4. Data Models

### 4.1 New Models

**Location:** `src/models/discovery.py`

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

class QueryFocus(str, Enum):
    """Focus area for decomposed queries."""
    METHODOLOGY = "methodology"
    APPLICATION = "application"
    COMPARISON = "comparison"
    RELATED = "related"
    INTERSECTION = "intersection"

class DecomposedQuery(BaseModel):
    """A focused sub-query generated from the original query."""
    query: str = Field(..., description="The decomposed query text")
    focus: QueryFocus = Field(..., description="The focus area of this query")
    weight: float = Field(1.0, ge=0.0, le=2.0, description="Weight for result merging")

class QualityWeights(BaseModel):
    """Weights for quality signal combination."""
    citation: float = Field(0.30, ge=0.0, le=1.0)
    venue: float = Field(0.25, ge=0.0, le=1.0)
    recency: float = Field(0.20, ge=0.0, le=1.0)
    completeness: float = Field(0.15, ge=0.0, le=1.0)
    author: float = Field(0.10, ge=0.0, le=1.0)

class ScoredPaper(BaseModel):
    """Paper with quality and relevance scores."""
    paper: PaperMetadata
    quality_score: float = Field(..., ge=0.0, le=1.0)
    relevance_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    composite_score: Optional[float] = Field(None, ge=0.0, le=1.0)

    @property
    def final_score(self) -> float:
        """Combined quality and relevance score."""
        if self.relevance_score is not None:
            return 0.4 * self.quality_score + 0.6 * self.relevance_score
        return self.quality_score

class DiscoveryMetrics(BaseModel):
    """Metrics from the discovery pipeline."""
    queries_generated: int
    papers_retrieved: int
    papers_after_dedup: int
    papers_after_quality_filter: int
    papers_after_relevance_filter: int
    providers_queried: List[str]
    avg_relevance_score: float
    avg_quality_score: float
    pipeline_duration_ms: int

class DiscoveryResult(BaseModel):
    """Result of the enhanced discovery pipeline."""
    papers: List[ScoredPaper]
    metrics: DiscoveryMetrics
    queries_used: List[DecomposedQuery]
```

### 4.2 Config Model Extensions

**Location:** `src/models/config.py` (additions)

```python
class EnhancedDiscoveryConfig(BaseModel):
    """Configuration for enhanced discovery pipeline."""

    # Query decomposition
    enable_query_decomposition: bool = Field(
        True,
        description="Enable LLM-based query decomposition"
    )
    max_subqueries: int = Field(
        5,
        ge=1,
        le=10,
        description="Maximum sub-queries to generate"
    )

    # Multi-source retrieval
    providers: List[ProviderType] = Field(
        [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR, ProviderType.OPENALEX],
        description="Providers to query"
    )
    papers_per_provider: int = Field(
        100,
        ge=10,
        le=500,
        description="Max papers to retrieve per provider per query"
    )

    # Quality filtering
    min_citations: int = Field(0, ge=0, description="Minimum citation threshold")
    min_quality_score: float = Field(0.3, ge=0.0, le=1.0)
    require_abstract: bool = Field(True)
    require_pdf: bool = Field(False)
    exclude_preprints: bool = Field(False)
    quality_weights: QualityWeights = Field(default_factory=QualityWeights)

    # Relevance ranking
    enable_relevance_ranking: bool = Field(
        True,
        description="Enable LLM-based relevance ranking"
    )
    min_relevance_score: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description="Minimum relevance score to include"
    )
    relevance_batch_size: int = Field(10, ge=1, le=50)
```

---

## 5. API Integration

### 5.1 OpenAlex API

**Base URL:** `https://api.openalex.org/works`

**Key Endpoints:**

| Endpoint | Purpose | Rate Limit |
|----------|---------|------------|
| `GET /works` | Search papers | 100K/day |
| `GET /works/{id}` | Get single paper | 100K/day |

**Response Mapping:**

```python
def _map_openalex_response(self, work: dict) -> PaperMetadata:
    """Map OpenAlex work to PaperMetadata."""
    return PaperMetadata(
        paper_id=work["id"].split("/")[-1],  # Extract OpenAlex ID
        title=work.get("title", ""),
        abstract=self._reconstruct_abstract(work.get("abstract_inverted_index")),
        authors=[
            Author(name=a["author"]["display_name"])
            for a in work.get("authorships", [])
        ],
        publication_date=work.get("publication_date"),
        venue=work.get("primary_location", {}).get("source", {}).get("display_name"),
        doi=work.get("doi"),
        citation_count=work.get("cited_by_count", 0),
        pdf_url=self._extract_pdf_url(work),
        source=ProviderType.OPENALEX
    )

def _reconstruct_abstract(self, inverted_index: dict) -> str:
    """Reconstruct abstract from OpenAlex inverted index format."""
    if not inverted_index:
        return ""
    words = [""] * (max(max(positions) for positions in inverted_index.values()) + 1)
    for word, positions in inverted_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words)
```

### 5.2 Rate Limiting Strategy

| Provider | Rate Limit | Strategy |
|----------|------------|----------|
| ArXiv | 1 req/3s | Sequential with delay |
| Semantic Scholar | 100 req/5min | Token bucket |
| OpenAlex | 100K/day | Polite pool with email |
| HuggingFace | 30 req/min | Token bucket |

---

## 6. Implementation Plan

### Phase 6.1: Foundation (Week 1)

**Tasks:**

1. Create `src/models/discovery.py` with new data models
2. Add `EnhancedDiscoveryConfig` to config models
3. Update `research_config.yaml` schema
4. Create `src/services/providers/openalex.py`
5. Write unit tests for OpenAlex provider

**Files:**
- `src/models/discovery.py` (NEW)
- `src/models/config.py` (MODIFY)
- `src/services/providers/openalex.py` (NEW)
- `tests/unit/test_providers/test_openalex.py` (NEW)

### Phase 6.2: Query Decomposition (Week 1-2)

**Tasks:**

1. Create `src/services/query_decomposer.py`
2. Design and test decomposition prompts
3. Add caching for decomposed queries
4. Write unit and integration tests

**Files:**
- `src/services/query_decomposer.py` (NEW)
- `tests/unit/test_query_decomposer.py` (NEW)

### Phase 6.3: Quality Filtering (Week 2)

**Tasks:**

1. Create `src/services/quality_filter_service.py`
2. Load venue rankings data (CORE/SJR)
3. Implement multi-signal scoring
4. Write unit tests

**Files:**
- `src/services/quality_filter_service.py` (NEW)
- `data/venue_rankings.json` (NEW)
- `tests/unit/test_quality_filter.py` (NEW)

### Phase 6.4: Relevance Ranking (Week 2-3)

**Tasks:**

1. Create `src/services/relevance_ranker.py`
2. Design and test relevance prompts
3. Implement batched scoring
4. Add relevance caching
5. Write unit and integration tests

**Files:**
- `src/services/relevance_ranker.py` (NEW)
- `tests/unit/test_relevance_ranker.py` (NEW)
- `tests/integration/test_relevance_ranking.py` (NEW)

### Phase 6.5: Pipeline Integration (Week 3)

**Tasks:**

1. Create `src/services/enhanced_discovery_service.py`
2. Update `DiscoveryService` to optionally use enhanced pipeline
3. Add feature flag for gradual rollout
4. Update CLI commands
5. Write end-to-end tests

**Files:**
- `src/services/enhanced_discovery_service.py` (NEW)
- `src/services/discovery_service.py` (MODIFY)
- `src/cli/run.py` (MODIFY)
- `tests/integration/test_enhanced_discovery.py` (NEW)

### Phase 6.6: Validation & Optimization (Week 4)

**Tasks:**

1. Performance benchmarking
2. Cost analysis (LLM calls)
3. Relevance quality evaluation
4. Documentation updates
5. Production deployment

---

## 7. Testing Strategy

### Unit Tests

| Component | Test Focus | Coverage Target |
|-----------|------------|-----------------|
| `QueryDecomposer` | Prompt generation, parsing, edge cases | 100% |
| `OpenAlexProvider` | API mapping, filtering, error handling | 100% |
| `QualityFilterService` | Score calculation, filtering logic | 100% |
| `RelevanceRanker` | Batching, scoring, threshold filtering | 100% |

### Integration Tests

| Test | Description |
|------|-------------|
| `test_multi_source_retrieval` | Query all providers, verify deduplication |
| `test_full_pipeline` | End-to-end discovery with all stages |
| `test_relevance_accuracy` | Compare LLM relevance to human labels |
| `test_quality_correlation` | Verify quality score predicts paper impact |

### Benchmark Tests

| Metric | Baseline | Target |
|--------|----------|--------|
| Relevant papers (P@10) | 30% | 70% |
| Query latency | 5s | 15s |
| LLM cost per topic | $0 | <$0.50 |

---

## 8. Success Metrics

### Primary Metrics

| Metric | Definition | Target |
|--------|------------|--------|
| **Relevance@K** | % of top-K papers rated relevant by user | >70% |
| **Topic Coverage** | % of synthesis questions answered | >80% |
| **Quality Score** | Avg quality of retrieved papers | >0.6 |

### Secondary Metrics

| Metric | Definition | Target |
|--------|------------|--------|
| Pipeline latency | Time from query to ranked results | <30s |
| LLM cost per topic | $ spent on decomposition + ranking | <$0.50 |
| Provider diversity | % papers from non-primary source | >20% |

### Monitoring

- Log relevance scores for analysis
- Track quality filter rejection rates
- Monitor LLM token usage per query

---

## 9. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| LLM relevance inconsistency | Medium | Medium | Use temperature=0, implement calibration |
| OpenAlex rate limiting | Low | Low | Implement exponential backoff, caching |
| Increased latency | High | Medium | Parallel provider queries, batch LLM calls |
| Higher LLM costs | Medium | Medium | Cache decomposed queries, limit re-ranking |
| Quality filter too strict | Medium | Medium | Configurable thresholds, gradual tuning |

---

## 10. Appendix

### A. Venue Rankings Data Source

**CORE Conference Rankings:** https://portal.core.edu.au/conf-ranks/

**Format:**
```json
{
  "venues": {
    "ACL": {"tier": "A*", "score": 1.0},
    "EMNLP": {"tier": "A*", "score": 1.0},
    "NAACL": {"tier": "A", "score": 0.85},
    "COLING": {"tier": "A", "score": 0.85},
    ...
  }
}
```

### B. Example Configuration

```yaml
settings:
  # Enhanced discovery settings (Phase 6)
  enhanced_discovery:
    # Query decomposition
    enable_query_decomposition: true
    max_subqueries: 5

    # Multi-source retrieval
    providers:
      - arxiv
      - semantic_scholar
      - openalex
    papers_per_provider: 100

    # Quality filtering
    min_citations: 5
    min_quality_score: 0.3
    require_abstract: true
    require_pdf: false
    exclude_preprints: false
    quality_weights:
      citation: 0.30
      venue: 0.25
      recency: 0.20
      completeness: 0.15
      author: 0.10

    # Relevance ranking
    enable_relevance_ranking: true
    min_relevance_score: 0.5
    relevance_batch_size: 10
```

### C. References

1. [SPAR: Scholar Paper Retrieval with LLM Agents](https://arxiv.org/abs/2507.15245)
2. [SemRank: LLM-Guided Semantic Ranking](https://arxiv.org/abs/2505.21815)
3. [Query Expansion Survey 2025](https://arxiv.org/abs/2509.07794)
4. [OpenAlex API Documentation](https://docs.openalex.org/)
5. [Semantic Scholar API](https://api.semanticscholar.org/api-docs/)
6. [oh-my-claudecode Research Mode](https://github.com/Yeachan-Heo/oh-my-claudecode)

---

## Approval

- [ ] Technical Lead Review
- [ ] Architecture Review
- [ ] Security Review
- [ ] Product Owner Approval

---

*Document Version: 1.0*
*Last Updated: 2026-02-28*

# Phase 9: Research Intelligence Layer Specification

**Version:** 1.3
**Status:** 📋 Aligned with as-built foundation (PR #105)
**Timeline:** 12-14 weeks (4 milestones)
**Author:** Claude Code
**Created:** 2026-04-18
**Last Updated:** 2026-04-24

**Dependencies:**
- Phase 8 Complete (Deep Research Agent with corpus, browser, agent loop)
- Phase 3.5 Complete (Global Paper Registry)
- Phase 6 Core Complete (Enhanced Discovery with multi-provider support)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Architecture Overview](#3-architecture-overview)
4. [Milestone 9.1: Proactive Paper Monitoring](#4-milestone-91-proactive-paper-monitoring)
5. [Milestone 9.2: Citation Graph Intelligence](#5-milestone-92-citation-graph-intelligence)
6. [Milestone 9.3: Knowledge Graph Synthesis](#6-milestone-93-knowledge-graph-synthesis)
7. [Milestone 9.4: Research Frontier Detection](#7-milestone-94-research-frontier-detection)
8. [Unified Data Architecture](#8-unified-data-architecture)
9. [Integration Design](#9-integration-design)
10. [Security Requirements](#10-security-requirements)
11. [Cost Analysis & Optimization](#11-cost-analysis--optimization)
12. [Implementation Schedule](#12-implementation-schedule)
13. [Success Metrics](#13-success-metrics)
14. [Risks & Mitigations](#14-risks--mitigations)
15. [Dependencies](#15-dependencies)
16. [Design Decisions](#16-design-decisions)
17. [Implementation Notes (As-Built Foundation)](#17-implementation-notes-as-built-foundation)

---

## 1. Executive Summary

Phase 9 introduces the **Research Intelligence Layer**, a suite of four complementary capabilities that transform ARISP from a reactive paper discovery system into a **proactive, relationship-aware, knowledge-extracting research intelligence platform**.

### 1.1 The Four Pillars of Research Intelligence

| Pillar | Capability | Intelligence Type |
|--------|------------|-------------------|
| **Monitoring** | Proactive Paper Monitoring | Awareness Intelligence |
| **Citation** | Citation Graph Intelligence | Relationship Intelligence |
| **Knowledge** | Knowledge Graph Synthesis | Fact-level Intelligence |
| **Frontier** | Research Frontier Detection | Strategic Intelligence |

### 1.2 Key Achievements

After Phase 9 completion, ARISP will be able to:

1. **Proactively alert users** when new relevant papers appear (not wait for queries)
2. **Discover hidden connections** via citation chains that keyword search cannot find
3. **Answer comparative questions** like "Which papers achieved >40 BLEU on WMT?"
4. **Identify research trends** and gaps before they become obvious
5. **Provide strategic guidance** on promising vs saturated research directions

### 1.3 What This Phase Is

- ✅ Proactive monitoring system with configurable subscriptions
- ✅ Citation graph with multi-hop relationship traversal
- ✅ Structured knowledge extraction and fact-based querying
- ✅ Trend analysis and research gap detection
- ✅ Unified graph storage architecture
- ✅ Full integration with existing DRA and discovery systems

### 1.4 What This Phase Is NOT

- ❌ Real-time collaborative research platform
- ❌ Automated paper writing or generation
- ❌ Replacement for human research judgment
- ❌ External API service (internal use only)

---

## 2. Problem Statement

### 2.1 Current Limitations

Even with Phase 8's Deep Research Agent, ARISP has four fundamental intelligence gaps:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CURRENT ARISP INTELLIGENCE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  ✅ Query-based discovery (user must ask)                                   │
│  ✅ Single-paper extraction (facts isolated per paper)                      │
│  ✅ Point-in-time analysis (no temporal awareness)                          │
│  ✅ Keyword-based search (vocabulary-dependent)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                        INTELLIGENCE GAPS                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  ❌ Gap 1: Reactive Only - User must manually check for new papers          │
│  ❌ Gap 2: No Relationships - Papers are islands, not a connected network   │
│  ❌ Gap 3: No Cross-Paper Facts - Cannot compare results across papers      │
│  ❌ Gap 4: No Trend Awareness - Cannot identify emerging vs mature areas    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Impact of These Gaps

| Gap | User Pain Point | Business Impact |
|-----|-----------------|-----------------|
| Reactive Only | Miss relevant papers for days/weeks | Competitive disadvantage |
| No Relationships | Reinvent existing work unknowingly | Wasted research effort |
| No Cross-Paper Facts | Manual comparison across papers | Hours of tedious work |
| No Trend Awareness | Pursue saturated directions | Poor research ROI |

### 2.3 Industry Context

Research intelligence is becoming critical in 2025-2026:

- **Paper Volume**: ArXiv receives 15,000+ papers/month in CS alone
- **Citation Networks**: Average paper has 30+ references; following all manually is impossible
- **Knowledge Fragmentation**: Same concept appears under different names across communities
- **Trend Velocity**: Hot topics emerge and saturate within 12-18 months

**Leading Research Tools Comparison:**

| Tool | Monitoring | Citation Graph | Knowledge Graph | Frontier Detection |
|------|------------|----------------|-----------------|-------------------|
| Semantic Scholar | ✅ Alerts | ✅ Basic | ❌ | ❌ |
| Connected Papers | ❌ | ✅ Visual | ❌ | ❌ |
| Elicit | ❌ | ❌ | ✅ Partial | ❌ |
| Research Rabbit | ✅ | ✅ | ❌ | ❌ |
| **ARISP Phase 9** | ✅ | ✅ | ✅ | ✅ |

---

## 3. Architecture Overview

### 3.1 Layered Intelligence Stack

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE 9: RESEARCH INTELLIGENCE LAYER                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Milestone 9.4: RESEARCH FRONTIER DETECTION                         │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │   │
│  │  │   Trend     │ │  Emergence  │ │ Saturation  │ │    Gap      │   │   │
│  │  │  Analyzer   │ │  Detector   │ │   Scorer    │ │   Finder    │   │   │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ▲                                        │
│  ┌─────────────────────────────────┼───────────────────────────────────┐   │
│  │  Milestone 9.3: KNOWLEDGE GRAPH SYNTHESIS                           │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │   │
│  │  │   Entity    │ │  Relation   │ │   Query     │ │Contradiction│   │   │
│  │  │  Extractor  │ │   Linker    │ │   Engine    │ │  Detector   │   │   │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ▲                                        │
│  ┌─────────────────────────────────┼───────────────────────────────────┐   │
│  │  Milestone 9.2: CITATION GRAPH INTELLIGENCE                         │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │   │
│  │  │   Graph     │ │  Citation   │ │  Coupling   │ │  Influence  │   │   │
│  │  │  Builder    │ │   Crawler   │ │  Analyzer   │ │   Scorer    │   │   │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ▲                                        │
│  ┌─────────────────────────────────┼───────────────────────────────────┐   │
│  │  Milestone 9.1: PROACTIVE PAPER MONITORING                          │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │   │
│  │  │ Subscription│ │   ArXiv     │ │  Relevance  │ │   Digest    │   │   │
│  │  │  Manager    │ │   Monitor   │ │   Scorer    │ │  Generator  │   │   │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ▲                                        │
├────────────────────────────────────┼────────────────────────────────────────┤
│                    PHASE 8: DEEP RESEARCH AGENT                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │   Corpus    │ │  Research   │ │    DRA      │ │     Trajectory      │   │
│  │  Manager    │ │   Browser   │ │  Agent Loop │ │      Learning       │   │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────────┤
│                    FOUNDATION: DISCOVERY + REGISTRY                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │  Discovery  │ │   Registry  │ │     LLM     │ │     Extraction      │   │
│  │   Service   │ │   Service   │ │   Service   │ │      Pipeline       │   │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Package Structure

> **Implementation note (PR #105):** The graph storage layer was relocated
> from `src/services/intelligence/storage/` to `src/storage/intelligence_graph/`
> during the Phase 9 foundation build. Storage is a cross-cutting persistence
> primitive — any service may consume it without introducing a service↔service
> dependency — so it now lives in the top-level `src/storage/` namespace
> alongside other backends. The four milestone subpackages
> (`monitoring/`, `citation/`, `knowledge/`, `frontier/`) remain under
> `src/services/intelligence/`. See [Section 17: Implementation
> Notes](#17-implementation-notes-as-built-foundation) for rationale.

```
src/services/intelligence/
├── __init__.py
├── models/                      # Shared data models (split into submodules)
│   ├── __init__.py              # Re-exports kernel surface
│   ├── graph.py                 # NodeType, EdgeType, GraphNode, GraphEdge
│   ├── knowledge.py             # EntityType, ExtractedEntity, ExtractedRelation
│   ├── frontier.py              # TrendStatus, GapType
│   ├── monitoring.py            # PaperSource, SubscriptionLimitError
│   └── exceptions.py            # GraphStoreError, NodeNotFoundError, ...
│
├── monitoring/                  # Milestone 9.1
│   ├── __init__.py
│   ├── subscription_manager.py  # Manage user subscriptions
│   ├── arxiv_monitor.py         # Watch ArXiv for new papers
│   ├── relevance_scorer.py      # Score new papers against interests
│   └── digest_generator.py      # Generate notification digests
│
├── citation/                    # Milestone 9.2
│   ├── __init__.py
│   ├── graph_builder.py         # Build citation graph from APIs
│   ├── crawler.py               # Walk citation chains
│   ├── coupling_analyzer.py     # Bibliographic coupling analysis
│   ├── influence_scorer.py      # Compute influence metrics
│   └── recommender.py           # Citation-based recommendations
│
├── knowledge/                   # Milestone 9.3
│   ├── __init__.py
│   ├── entity_extractor.py      # Extract structured entities
│   ├── relation_linker.py       # Link entities across papers
│   ├── query_engine.py          # Natural language queries
│   └── contradiction_detector.py # Find conflicting claims
│   # NOTE: knowledge graph storage uses src/storage/intelligence_graph/
│
├── frontier/                    # Milestone 9.4
│   ├── __init__.py
│   ├── trend_analyzer.py        # Track topic velocity
│   ├── emergence_detector.py    # Identify new concepts
│   ├── saturation_scorer.py     # Measure topic maturity
│   ├── gap_finder.py            # Find research gaps
│   └── strategic_advisor.py     # Generate research recommendations
│
└── unified_query.py             # Cross-layer query engine

src/storage/intelligence_graph/  # Cross-cutting graph persistence (PR #105)
├── __init__.py                  # Re-exports GraphStore, SQLiteGraphStore,
│                                # GraphAlgorithms, MigrationManager, ...
├── unified_graph.py             # GraphStore Protocol + SQLiteGraphStore impl
├── algorithms.py                # GraphAlgorithms (PageRank, ...) — decoupled
│                                # from the storage Protocol
├── migrations.py                # Versioned schema migrations
├── time_series.py               # Temporal data storage
└── path_utils.py                # Storage path sanitization helpers
```

### 3.3 Data Flow Architecture

```
                                    ┌─────────────────┐
                                    │   User/CLI/API  │
                                    └────────┬────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    │                        │                        │
                    ▼                        ▼                        ▼
           ┌───────────────┐        ┌───────────────┐        ┌───────────────┐
           │  Subscription │        │  DRA Research │        │   Frontier    │
           │    Queries    │        │    Session    │        │    Query      │
           └───────┬───────┘        └───────┬───────┘        └───────┬───────┘
                   │                        │                        │
                   ▼                        ▼                        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         UNIFIED QUERY ENGINE                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  Semantic   │  │  Citation   │  │  Knowledge  │  │   Frontier  │         │
│  │   Search    │  │   Expand    │  │   Filter    │  │   Filter    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘         │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         UNIFIED GRAPH STORE                                   │
│                                                                              │
│   ┌─────────┐        ┌─────────┐        ┌─────────┐        ┌─────────┐     │
│   │  Paper  │──CITES─▶│  Paper  │        │ Entity  │──ACHIEVES─▶│ Result │  │
│   │  Node   │◀─CITES──│  Node   │        │  Node   │        │  Node   │     │
│   └────┬────┘        └────┬────┘        └────┬────┘        └─────────┘     │
│        │                  │                  │                              │
│        └──────MENTIONS────┴──────────────────┘                              │
│                                                                              │
│   Edge Types: CITES, MENTIONS, ACHIEVES, COMPARES, BELONGS_TO               │
│   Node Types: Paper, Entity, Result, Topic, Author, Venue                   │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL DATA SOURCES                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │Semantic Sch.│  │   ArXiv     │  │  OpenAlex   │  │ HuggingFace │         │
│  │  Citations  │  │    RSS      │  │   Works     │  │    Daily    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘         │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Milestone 9.1: Proactive Paper Monitoring

**Duration:** 2 weeks
**Goal:** Never miss a relevant paper again

### 4.1 Overview

Transform ARISP from a pull-based system ("user queries for papers") to a push-based system ("system notifies user of relevant papers").

### 4.2 Requirements

#### REQ-9.1.1: Subscription Management

The system SHALL allow users to create and manage research subscriptions.

**Subscription Model:**
```python
class ResearchSubscription(BaseModel):
    """A user's subscription to a research topic."""
    subscription_id: str = Field(..., description="Unique identifier")
    name: str = Field(..., max_length=100, description="Human-readable name")
    query: str = Field(..., description="Base search query")
    keywords: list[str] = Field(default_factory=list, description="Additional keywords")
    exclude_keywords: list[str] = Field(default_factory=list)
    min_relevance_score: float = Field(0.7, ge=0.0, le=1.0)
    sources: list[PaperSource] = Field(default_factory=lambda: [PaperSource.ARXIV])
    created_at: datetime
    last_checked: datetime | None = None
    is_active: bool = True

class PaperSource(str, Enum):
    ARXIV = "arxiv"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    HUGGINGFACE = "huggingface"
    OPENALEX = "openalex"

# MVP Scope: Only ARXIV has RSS/Atom feeds enabling efficient monitoring.
# Other sources require polling with API rate limits:
# - SEMANTIC_SCHOLAR: No feed, requires search API polling (rate limited)
# - HUGGINGFACE: Daily papers endpoint, but no subscription filtering
# - OPENALEX: No feed, requires works API polling
# Post-MVP: Add polling-based monitors with careful rate limit management.
```

**Scenario: Create Subscription**
```gherkin
Given a user wants to track "parameter-efficient fine-tuning"
When they create a subscription with query="LoRA OR QLoRA OR adapter tuning"
Then the subscription SHALL be stored with a unique ID
And monitoring SHALL begin on the next check cycle
```

#### REQ-9.1.2: ArXiv Monitoring

The system SHALL monitor ArXiv for new papers matching subscriptions.

**Monitoring Strategy:**
- **Frequency:** Configurable (default: every 6 hours)
- **Method:** ArXiv API with date filters or RSS feed parsing
- **Deduplication:** Skip papers already in registry
- **Rate Limiting:** Respect ArXiv API limits (3 requests/second)

**Scenario: New Paper Detection**
```gherkin
Given a subscription for "large language model alignment"
And ArXiv publishes a new paper titled "RLHF Improvements for LLM Alignment"
When the monitoring cycle runs
Then the paper SHALL be flagged as potentially relevant
And relevance scoring SHALL be triggered
```

#### REQ-9.1.3: Relevance Scoring

New papers SHALL be scored against subscription criteria using lightweight LLM evaluation.

**Scoring Approach:**
```python
class RelevanceScoreResult(BaseModel):
    """Result of relevance scoring for a new paper."""
    paper_id: str
    subscription_id: str
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., max_length=500)
    key_matches: list[str] = Field(default_factory=list)
    scored_at: datetime
```

**LLM Prompt Strategy:**
- Use small/fast model (Haiku or Gemini Flash) for cost efficiency
- Input: Paper title + abstract + subscription query
- Output: Relevance score (0-1) + brief reasoning
- Cache results to avoid re-scoring

#### REQ-9.1.4: Digest Generation

The system SHALL generate periodic digests of new relevant papers.

**Digest Types:**
- **Immediate:** For high-relevance papers (score > 0.9)
- **Daily:** Summary of all papers above threshold
- **Weekly:** Comprehensive digest with trends

**Digest Model:**
```python
class PaperDigest(BaseModel):
    """A digest of new papers for a subscription."""
    digest_id: str
    subscription_id: str
    period_start: datetime
    period_end: datetime
    papers: list[DigestPaper]
    summary: str | None = None  # LLM-generated summary
    generated_at: datetime

class DigestPaper(BaseModel):
    """A paper entry in a digest."""
    paper_id: str
    title: str
    authors: list[str]
    abstract_snippet: str = Field(..., max_length=300)
    relevance_score: float
    relevance_reasoning: str
    arxiv_url: str | None = None
    pdf_url: str | None = None
```

### 4.3 CLI Commands

```bash
# Subscription management
arisp monitor add "PEFT Research" --query "LoRA OR QLoRA" --min-score 0.7
arisp monitor list
arisp monitor update <id> --query "LoRA OR QLoRA OR DoRA"
arisp monitor pause <id>
arisp monitor delete <id>

# Manual check
arisp monitor check [--subscription <id>]

# Digest management
arisp monitor digest --period daily
arisp monitor digest --subscription <id> --since 2026-04-01
```

### 4.4 Integration Points

- **Registry Service:** New papers added to registry for deduplication
- **Discovery Service:** Reuse existing provider clients
- **Notification Service:** Leverage existing notification infrastructure
- **DRA Corpus:** High-relevance papers can be auto-ingested into corpus

### 4.5 Test Cases

| Test | Description | Coverage Target |
|------|-------------|-----------------|
| `test_create_subscription` | Subscription creation and validation | 100% |
| `test_arxiv_monitor_new_papers` | Detect new papers from ArXiv | 100% |
| `test_relevance_scoring` | Score papers against subscription | 100% |
| `test_deduplication` | Skip already-seen papers | 100% |
| `test_digest_generation` | Generate daily/weekly digests | 100% |
| `test_rate_limiting` | Respect API rate limits | 100% |

---

## 5. Milestone 9.2: Citation Graph Intelligence

**Duration:** 3 weeks
**Goal:** Discover papers through citation relationships, not just keywords

### 5.1 Overview

Build a citation graph that enables:
- Finding papers via citation chains (forward/backward)
- Identifying related papers through shared references
- Computing paper influence metrics
- Recommending papers based on citation patterns

### 5.2 Requirements

#### REQ-9.2.1: Citation Graph Construction

The system SHALL build a citation graph from external APIs.

**Graph Model:**
```python
class CitationNode(BaseModel):
    """A paper in the citation graph."""
    paper_id: str  # Registry paper ID or external ID
    external_ids: dict[str, str]  # doi, arxiv_id, s2_id, etc.
    title: str
    year: int | None = None
    citation_count: int = 0
    reference_count: int = 0
    is_in_corpus: bool = False  # True if we have full text
    influence_score: float | None = None
    fetched_at: datetime

class CitationEdge(BaseModel):
    """A citation relationship."""
    citing_paper_id: str
    cited_paper_id: str
    context: str | None = None  # Citation context if available
    section: str | None = None  # Where the citation appears
```

**Data Sources:**
- Semantic Scholar API (primary - richest citation data)
- OpenAlex API (backup - broader coverage)

**Scenario: Build Graph for Seed Paper**
```gherkin
Given a seed paper "Attention Is All You Need" (arxiv:1706.03762)
When citation graph is built with depth=1
Then all papers citing it (forward) SHALL be fetched
And all papers it references (backward) SHALL be fetched
And edges SHALL be created for each citation relationship
```

#### REQ-9.2.2: Citation Chain Crawling

The system SHALL traverse citation chains to discover related papers.

**Crawling Parameters:**
```python
class CrawlConfig(BaseModel):
    """Configuration for citation crawling."""
    max_depth: int = Field(2, ge=1, le=3)  # Limit depth to control explosion
    max_papers_per_level: int = Field(50, ge=10, le=200)
    direction: CrawlDirection = CrawlDirection.BOTH
    filter_min_citations: int = Field(0, ge=0)  # Skip low-citation papers
    filter_year_min: int | None = None

class CrawlDirection(str, Enum):
    FORWARD = "forward"   # Papers citing the seed
    BACKWARD = "backward" # Papers cited by the seed
    BOTH = "both"
```

**Ranking Function (for top_k selection):**
```python
def sort_by_influence(papers: list[Paper]) -> list[Paper]:
    """Sort papers by influence for deterministic top_k selection.

    Ranking criteria (descending priority):
    1. influentialCitationCount (Semantic Scholar metric)
    2. citationCount (fallback)
    3. publicationDate (recency tiebreaker)
    """
    return sorted(papers, key=lambda p: (
        p.influential_citation_count or 0,
        p.citation_count or 0,
        p.publication_date or date.min
    ), reverse=True)
```

**Crawling Algorithm (BFS):**
```
function crawl(seed_paper_id, config):
    visited = {seed_paper_id}
    queue = deque([(seed_paper_id, 0)])  # (paper_id, depth) - use deque for BFS

    while queue not empty:
        paper_id, depth = queue.popleft()  # BFS: popleft() ensures shortest paths
        if depth >= config.max_depth:
            continue

        if config.direction in [BACKWARD, BOTH]:
            references = fetch_references(paper_id)
            # Rank by: influentialCitationCount DESC, citationCount DESC, year DESC
            ranked_refs = sort_by_influence(references)
            for ref in top_k(ranked_refs, config.max_papers_per_level):
                if ref.id not in visited:
                    add_to_graph(ref)
                    queue.append((ref.id, depth + 1))
                    visited.add(ref.id)

        if config.direction in [FORWARD, BOTH]:
            citations = fetch_citations(paper_id)
            # Rank by: influentialCitationCount DESC, citationCount DESC, year DESC
            ranked_cites = sort_by_influence(citations)
            for cite in top_k(ranked_cites, config.max_papers_per_level):
                if cite.id not in visited:
                    add_to_graph(cite)
                    queue.append((cite.id, depth + 1))
                    visited.add(cite.id)

    return graph
```

#### REQ-9.2.3: Bibliographic Coupling Analysis

Papers sharing many references SHALL be identified as related.

**Coupling Metrics:**
```python
class CouplingResult(BaseModel):
    """Result of bibliographic coupling analysis."""
    paper_a_id: str
    paper_b_id: str
    shared_references: list[str]  # Paper IDs
    coupling_strength: float  # Jaccard similarity of references
    co_citation_count: int  # Times cited together
```

**Scenario: Find Related Papers via Coupling**
```gherkin
Given paper A references [R1, R2, R3, R4, R5]
And paper B references [R2, R3, R4, R6, R7]
When coupling analysis runs
Then coupling_strength = |{R2,R3,R4}| / |{R1,R2,R3,R4,R5,R6,R7}| = 3/7 = 0.43
And papers A and B SHALL be marked as related
```

#### REQ-9.2.4: Influence Scoring

The system SHALL compute influence metrics for papers in the graph.

**Influence Metrics:**
```python
class InfluenceMetrics(BaseModel):
    """Influence metrics for a paper."""
    paper_id: str
    citation_count: int
    citation_velocity: float  # Citations per year since publication
    pagerank_score: float  # PageRank over citation graph
    hub_score: float  # HITS hub score
    authority_score: float  # HITS authority score
    computed_at: datetime
```

**PageRank Adaptation:**
- Damping factor: 0.85 (standard)
- Edge weight: Optionally weight by citation context relevance
- Recency bias: Optionally boost recent papers

#### REQ-9.2.5: Citation-Based Recommendations

The system SHALL recommend papers based on citation patterns.

**Recommendation Strategies:**
1. **Similar Papers:** Papers with high coupling to a seed
2. **Influential Predecessors:** High-influence papers in the backward chain
3. **Active Successors:** Recent papers citing the seed with high velocity
4. **Bridge Papers:** Papers connecting different citation clusters

### 5.3 CLI Commands

```bash
# Graph building
arisp citation build <paper_id> --depth 2
arisp citation expand <paper_id> --direction forward

# Analysis
arisp citation related <paper_id> --top 10
arisp citation influence <paper_id>
arisp citation path <paper_a> <paper_b>  # Citation path between papers

# Visualization (optional)
arisp citation visualize <paper_id> --output graph.html
```

### 5.4 Integration Points

- **DRA Browser:** Add `cite_expand(paper_id)` primitive to find related papers
- **Discovery Service:** Citation-based re-ranking of search results
- **Monitoring:** Boost relevance score if paper cites known relevant papers

### 5.5 Test Cases

| Test | Description | Coverage Target |
|------|-------------|-----------------|
| `test_graph_construction` | Build graph from API data | 100% |
| `test_crawl_depth_limit` | Respect max depth | 100% |
| `test_bibliographic_coupling` | Compute coupling metrics | 100% |
| `test_influence_pagerank` | PageRank computation | 100% |
| `test_recommendation_similar` | Similar paper recommendations | 100% |
| `test_api_rate_limiting` | Respect S2/OpenAlex limits | 100% |

---

## 6. Milestone 9.3: Knowledge Graph Synthesis

**Duration:** 4 weeks
**Goal:** Extract and connect facts across papers for comparative analysis

### 6.1 Overview

Transform isolated paper extractions into a connected knowledge graph where:
- Entities (methods, datasets, metrics) are nodes
- Relationships (achieves, compares, uses) are edges
- Users can query across papers: "Which papers achieve >40 BLEU?"

### 6.2 Requirements

#### REQ-9.3.1: Entity Extraction

The system SHALL extract structured entities from paper content.

**Entity Types:**
```python
class EntityType(str, Enum):
    METHOD = "method"           # e.g., "LoRA", "Chain-of-Thought"
    DATASET = "dataset"         # e.g., "WMT14", "SQuAD"
    METRIC = "metric"           # e.g., "BLEU", "accuracy"
    MODEL = "model"             # e.g., "GPT-4", "LLaMA-2"
    TASK = "task"               # e.g., "machine translation", "QA"
    RESULT = "result"           # e.g., "42.3 BLEU on WMT14"
    HYPERPARAMETER = "hyperparam"  # e.g., "learning_rate=1e-4"

class ExtractedEntity(BaseModel):
    """An entity extracted from a paper."""
    entity_id: str
    entity_type: EntityType
    name: str  # Canonical name
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    paper_id: str  # Source paper
    section: str | None = None  # Where it appeared
    confidence: float = Field(..., ge=0.0, le=1.0)
    extracted_at: datetime
```

**Extraction Prompt Strategy:**
```
Given the following paper section, extract all entities:

Section: {section_text}

For each entity, provide:
1. Type (method/dataset/metric/model/task/result/hyperparameter)
2. Name (canonical form)
3. Aliases (other names used)
4. Description (brief context)

Output as JSON array.
```

#### REQ-9.3.2: Relation Extraction

The system SHALL extract relationships between entities.

**Relation Types:**

> **Implementation note (PR #105):** Knowledge-graph relations reuse the
> shared `EdgeType` enum (see Section 8.1) instead of a separate
> `RelationType`. This keeps a single type system across the knowledge layer
> and the underlying graph store, so relations extracted in 9.3 can be
> persisted directly as graph edges without translation. The relevant
> `EdgeType` members for Milestone 9.3 are: `ACHIEVES`, `USES`,
> `EVALUATES_ON`, `IMPROVES`, `COMPARES`, `EXTENDS`, `REQUIRES`, and
> `MENTIONS`.

```python
from src.services.intelligence.models import EdgeType

class ExtractedRelation(BaseModel):
    """A relationship between entities."""
    relation_id: str
    relation_type: EdgeType  # was RelationType pre-PR #105
    source_entity_id: str
    target_entity_id: str
    context: str | None = None  # Supporting text
    paper_id: str
    confidence: float = Field(..., ge=0.0, le=1.0)
```

**Example Extraction:**
```
Text: "Our LoRA method achieves 42.3 BLEU on WMT14, outperforming
       the baseline full fine-tuning approach by 2.1 points."

Entities:
  - E1: {type: METHOD, name: "LoRA"}
  - E2: {type: RESULT, name: "42.3 BLEU"}
  - E3: {type: DATASET, name: "WMT14"}
  - E4: {type: METHOD, name: "full fine-tuning"}

Relations:
  - {type: ACHIEVES, source: E1, target: E2}
  - {type: EVALUATES_ON, source: E1, target: E3}
  - {type: IMPROVES, source: E1, target: E4}
```

#### REQ-9.3.3: Entity Resolution

The system SHALL merge duplicate entities across papers.

**Resolution Strategies:**
1. **Exact Match:** Same canonical name
2. **Alias Match:** Name appears in another entity's aliases
3. **Embedding Similarity:** High cosine similarity between entity descriptions
4. **LLM Verification:** For ambiguous cases, use LLM to verify equivalence

**Resolution Model:**
```python
class EntityCluster(BaseModel):
    """A cluster of merged entities."""
    cluster_id: str
    canonical_name: str
    entity_type: EntityType
    all_aliases: list[str]
    member_entity_ids: list[str]  # Original entity IDs
    mention_count: int  # Total mentions across papers
    paper_count: int  # Number of papers mentioning
```

#### REQ-9.3.4: Knowledge Query Engine

The system SHALL support natural language queries over the knowledge graph.

**Query Types:**
```python
class KnowledgeQuery(BaseModel):
    """A query over the knowledge graph."""
    query_text: str
    query_type: QueryType
    filters: dict = Field(default_factory=dict)
    limit: int = Field(20, ge=1, le=100)

class QueryType(str, Enum):
    ENTITY_SEARCH = "entity_search"      # Find entities by name/type
    RELATION_SEARCH = "relation_search"  # Find relations
    COMPARISON = "comparison"            # Compare methods/results
    AGGREGATION = "aggregation"          # Aggregate results
```

**Example Queries:**
```
Q: "Which methods achieve BLEU > 40 on WMT14?"
→ QueryType.RELATION_SEARCH (filter query, not aggregation)
→ Filter: entity_type=RESULT, dataset=WMT14, metric=BLEU, value>40
→ Return: List of (method, result, paper) tuples

Q: "What is the average BLEU score across all LoRA papers?"
→ QueryType.AGGREGATION (GROUP BY with AVG function)
→ Filter: method=LoRA, metric=BLEU
→ Return: Single aggregated value

Q: "Compare LoRA and full fine-tuning"
→ QueryType.COMPARISON
→ Entities: [LoRA, full fine-tuning]
→ Return: Side-by-side results across all papers mentioning both

Q: "What datasets are used for evaluating QA models?"
→ QueryType.RELATION_SEARCH
→ Filter: relation_type=EVALUATES_ON, source_type=MODEL, task=QA
→ Return: List of datasets with usage counts
```

#### REQ-9.3.5: Contradiction Detection

The system SHALL identify conflicting claims across papers.

**Contradiction Types:**
```python
class ContradictionType(str, Enum):
    RESULT_CONFLICT = "result_conflict"    # Different results for same setup
    CLAIM_CONFLICT = "claim_conflict"      # Opposing claims
    METHOD_CONFLICT = "method_conflict"    # Incompatible methodologies

class Contradiction(BaseModel):
    """A detected contradiction between papers."""
    contradiction_id: str
    contradiction_type: ContradictionType
    paper_a_id: str
    paper_b_id: str
    claim_a: str
    claim_b: str
    entities_involved: list[str]
    severity: float = Field(..., ge=0.0, le=1.0)  # How significant
    resolution_hint: str | None = None  # Possible explanation
```

### 6.3 CLI Commands

```bash
# Entity management
arisp knowledge extract <paper_id>
arisp knowledge entities --type method --search "LoRA"
arisp knowledge resolve  # Run entity resolution

# Queries
arisp knowledge query "methods achieving BLEU > 40 on WMT"
arisp knowledge compare "LoRA" "full fine-tuning"

# Analysis
arisp knowledge contradictions
arisp knowledge stats
```

### 6.4 Integration Points

- **DRA Agent:** Add `knowledge_query(query)` primitive
- **Extraction Pipeline:** Trigger entity extraction on new extractions
- **Frontier Detection:** Entity velocity feeds trend analysis

### 6.5 Test Cases

| Test | Description | Coverage Target |
|------|-------------|-----------------|
| `test_entity_extraction` | Extract entities from text | 100% |
| `test_relation_extraction` | Extract relationships | 100% |
| `test_entity_resolution` | Merge duplicate entities | 100% |
| `test_query_aggregation` | Aggregate queries | 100% |
| `test_comparison_query` | Compare entities | 100% |
| `test_contradiction_detection` | Find conflicts | 100% |

---

## 7. Milestone 9.4: Research Frontier Detection

**Duration:** 3 weeks
**Goal:** Identify emerging trends, saturated areas, and research gaps

### 7.1 Overview

Provide strategic intelligence about research landscape:
- What's emerging (early-stage, high velocity)
- What's saturated (mature, diminishing novelty)
- What's missing (underexplored intersections)

### 7.2 Requirements

#### REQ-9.4.1: Trend Analysis

The system SHALL track topic velocity over time.

**Trend Metrics:**
```python
class TopicTrend(BaseModel):
    """Trend analysis for a research topic."""
    topic: str
    time_series: list[TrendPoint]
    current_velocity: float  # Papers/month recent
    acceleration: float  # Change in velocity
    peak_date: date | None = None
    trend_status: TrendStatus

class TrendPoint(BaseModel):
    """A single point in a trend time series."""
    period: date  # Month or week
    paper_count: int
    citation_count: int
    author_count: int

class TrendStatus(str, Enum):
    EMERGING = "emerging"       # Low volume, high acceleration
    GROWING = "growing"         # High volume, positive acceleration
    PEAKED = "peaked"           # High volume, zero/negative acceleration
    DECLINING = "declining"     # Decreasing volume
    NICHE = "niche"             # Consistently low volume
```

**Scenario: Detect Emerging Topic**
```gherkin
Given "mixture of experts" had 10 papers/month in 2024
And "mixture of experts" has 50 papers/month in 2025
When trend analysis runs
Then topic status SHALL be "emerging" or "growing"
And acceleration SHALL be positive
```

#### REQ-9.4.2: Emergence Detection

The system SHALL identify newly appearing concepts.

**Emergence Signals:**
1. **New Term Frequency:** Term appears significantly more than N months ago
2. **Cross-Pollination:** Term appears in new venue/community
3. **Citation Burst:** Rapid increase in citations to papers using term
4. **Author Diversity:** Rapid increase in unique authors

**Emergence Model:**
```python
class EmergingConcept(BaseModel):
    """A newly emerging research concept."""
    concept: str
    first_significant_date: date  # When it crossed threshold
    current_velocity: float
    emergence_score: float  # 0-1, confidence it's emerging
    related_topics: list[str]
    key_papers: list[str]  # Early influential papers
    predicted_peak: date | None = None
```

#### REQ-9.4.3: Saturation Scoring

The system SHALL identify saturated research areas.

**Saturation Signals:**
1. **Novelty Decay:** New papers incrementally improve, no breakthroughs
2. **Result Plateau:** Performance metrics approaching theoretical limits
3. **Author Consolidation:** Same authors dominate, few newcomers
4. **Citation Saturation:** Citations go to old papers, not new

**Saturation Model:**
```python
class SaturationAnalysis(BaseModel):
    """Analysis of topic saturation."""
    topic: str
    saturation_score: float  # 0-1, higher = more saturated
    novelty_trend: float  # Declining = saturated
    result_improvement_rate: float  # Marginal gains
    newcomer_ratio: float  # New authors / total authors
    recommendation: SaturationRecommendation

class SaturationRecommendation(str, Enum):
    PURSUE = "pursue"          # Active, opportunities remain
    CAUTIOUS = "cautious"      # Maturing, incremental gains
    AVOID = "avoid"            # Saturated, low ROI
    NICHE_OPPORTUNITY = "niche"  # Saturated overall, but niche gaps
```

#### REQ-9.4.4: Gap Detection

The system SHALL identify underexplored research areas.

**Gap Types:**
```python
class ResearchGap(BaseModel):
    """An identified gap in the research landscape."""
    gap_id: str
    gap_type: GapType
    description: str
    related_topics: list[str]
    evidence: list[str]  # Supporting observations
    opportunity_score: float  # 0-1, higher = better opportunity
    suggested_directions: list[str]

class GapType(str, Enum):
    INTERSECTION = "intersection"  # Topic A + Topic B underexplored
    APPLICATION = "application"    # Method not applied to domain
    SCALE = "scale"                # Not tested at different scales
    MODALITY = "modality"          # Not explored in other modalities
    REPLICATION = "replication"    # Results not independently verified
```

**Gap Detection Strategies:**
1. **Intersection Analysis:** Find topic pairs with few papers at intersection
2. **Method-Domain Matrix:** Identify methods not applied to certain domains
3. **Contradiction Gaps:** Areas with unresolved contradictions
4. **Citation Analysis:** Papers citing need for future work in area

#### REQ-9.4.5: Strategic Advisor

The system SHALL generate research direction recommendations.

**Recommendation Model:**
```python
class StrategicRecommendation(BaseModel):
    """A strategic research recommendation."""
    recommendation_id: str
    recommendation_type: RecommendationType
    title: str
    description: str
    supporting_evidence: list[str]
    confidence: float
    related_papers: list[str]
    estimated_difficulty: Difficulty
    estimated_impact: Impact

class RecommendationType(str, Enum):
    PURSUE_EMERGING = "pursue_emerging"    # Get in early on trend
    EXPLOIT_GAP = "exploit_gap"            # Fill research gap
    AVOID_SATURATED = "avoid_saturated"    # Steer away
    DIFFERENTIATE = "differentiate"         # Novel angle on mature topic
```

### 7.3 CLI Commands

```bash
# Trend analysis
arisp frontier trends --topic "large language models"
arisp frontier emerging --since 2025-01
arisp frontier saturated --threshold 0.7

# Gap analysis
arisp frontier gaps --topics "LoRA,vision"
arisp frontier opportunities --limit 10

# Recommendations
arisp frontier recommend --interests "efficient fine-tuning"
arisp frontier report --output frontier_report.md
```

### 7.4 Integration Points

- **Monitoring:** Prioritize subscriptions for emerging topics
- **DRA:** Agent can query frontier status during research
- **Knowledge Graph:** Entity velocity feeds emergence detection

### 7.5 Test Cases

| Test | Description | Coverage Target |
|------|-------------|-----------------|
| `test_trend_calculation` | Compute topic velocity | 100% |
| `test_emergence_detection` | Identify new concepts | 100% |
| `test_saturation_scoring` | Score topic maturity | 100% |
| `test_gap_intersection` | Find intersection gaps | 100% |
| `test_recommendation_generation` | Generate recommendations | 100% |

---

## 8. Unified Data Architecture

### 8.1 Graph Storage Design

All four milestones share a unified graph storage layer to enable cross-layer queries.

**Node Types:**
```python
class NodeType(str, Enum):
    PAPER = "paper"
    ENTITY = "entity"       # Method, dataset, metric, etc.
    RESULT = "result"
    TOPIC = "topic"
    AUTHOR = "author"
    VENUE = "venue"
    SUBSCRIPTION = "subscription"
```

**Edge Types:**
```python
class EdgeType(str, Enum):
    # Citation edges (Milestone 9.2)
    CITES = "cites"
    CITED_BY = "cited_by"

    # Knowledge edges (Milestone 9.3)
    MENTIONS = "mentions"
    ACHIEVES = "achieves"
    USES = "uses"
    COMPARES = "compares"
    IMPROVES = "improves"
    EXTENDS = "extends"
    EVALUATES_ON = "evaluates_on"
    REQUIRES = "requires"

    # Frontier edges (Milestone 9.4)
    BELONGS_TO = "belongs_to"  # Paper belongs to topic
    AUTHORED_BY = "authored_by"
    PUBLISHED_IN = "published_in"

    # Monitoring edges (Milestone 9.1)
    MATCHES = "matches"  # Paper matches subscription
```

> **Implementation note (PR #105):** The previously separate `RelationType`
> enum (Milestone 9.3) was consolidated into `EdgeType` so that knowledge-graph
> relations and graph-storage edges share a single type system. The
> `ExtractedRelation` model now uses `relation_type: EdgeType` directly.
> See [Section 17: Implementation
> Notes](#17-implementation-notes-as-built-foundation).

### 8.2 Storage Implementation Options

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **NetworkX + JSON** | Simple, no dependencies | Memory-limited, slow queries | Dev/testing only |
| **SQLite + JSON columns** | Portable, good enough | Limited graph queries | MVP/small scale |
| **Neo4j** | Native graph, powerful queries | Operational complexity | Production scale |
| **DuckDB** | Fast analytics, embedded | Less graph-native | If analytics-heavy |

**Recommended Approach:**
- Start with SQLite for MVP (Milestone 9.1-9.2)
- Add optional Neo4j backend for production scale (Milestone 9.3-9.4)
- Abstract storage behind `GraphStore` interface for flexibility

### 8.3 Schema Design (SQLite Version)

**Connection Initialization (REQUIRED):**

Every SQLite connection opened by `SQLiteGraphStore` applies the following
pragmas, in this order, before any user-issued statement runs. These four
together implement the Phase 9 concurrency model.

```sql
-- Referential integrity (CRITICAL — SQLite default is OFF per connection)
PRAGMA foreign_keys = ON;
-- Writers do not block readers; concurrent reads stay non-blocking
PRAGMA journal_mode = WAL;
-- Crash-safe enough for our durability needs; faster than FULL
PRAGMA synchronous = NORMAL;
-- Wait up to 5 s for a held lock before raising SQLITE_BUSY
PRAGMA busy_timeout = 5000;
```

**Concurrency model (PR #105 decision):**

- **WAL** decouples readers from writers so monitoring/citation/knowledge
  pipelines can read while another worker writes.
- **`busy_timeout = 5000`** absorbs short lock contention (typical bulk
  insert is well under 1 s) without raising up to the caller.
- **`BEGIN IMMEDIATE`** is used at the start of `update_node` (and the
  bulk insert `with conn:` blocks) to acquire the write lock up-front.
  This eliminates the read-then-update race that would otherwise let two
  workers observe the same `version` and both try to bump it.
- **Optimistic locking** is documented at the model level via
  `GraphNode.version` / `GraphEdge.version`. `update_node` increments the
  version atomically and raises `OptimisticLockError(node_id, expected,
  actual)` on mismatch — the actual version is re-queried so the error
  reports the truth, not a guess.

```sql
-- Nodes table
CREATE TABLE nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    properties JSON NOT NULL,
    version INTEGER DEFAULT 1,  -- Optimistic concurrency control
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_nodes_type ON nodes(node_type);

-- Edges table
CREATE TABLE edges (
    edge_id TEXT PRIMARY KEY,
    edge_type TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES nodes(node_id),
    target_id TEXT NOT NULL REFERENCES nodes(node_id),
    properties JSON,
    version INTEGER DEFAULT 1,  -- Optimistic concurrency control
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Optimistic Locking Pattern:
-- UPDATE nodes SET ..., version = version + 1 WHERE node_id = ? AND version = ?
-- If rows_affected == 0, another worker modified the record; retry or abort.

CREATE INDEX idx_edges_type ON edges(edge_type);
CREATE INDEX idx_edges_source ON edges(source_id);
CREATE INDEX idx_edges_target ON edges(target_id);

-- Time series for trends
CREATE TABLE time_series (
    series_id TEXT,
    period DATE,
    metric_name TEXT,
    value REAL,
    PRIMARY KEY (series_id, period, metric_name)
);

-- Subscriptions
CREATE TABLE subscriptions (
    subscription_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    config JSON NOT NULL,
    last_checked TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 8.4 Refresh Strategies

Different data has different freshness requirements:

| Data Type | Refresh Frequency | Trigger |
|-----------|-------------------|---------|
| Subscriptions | Real-time | User action |
| New paper checks | 6 hours | Scheduled |
| Citation graph | Weekly | Scheduled + on-demand |
| Entity extraction | On extraction | Pipeline event |
| Entity resolution | Daily | Scheduled |
| Trend analysis | Weekly | Scheduled |
| Frontier metrics | Weekly | Scheduled |

---

## 9. Integration Design

### 9.1 DRA Integration

The Deep Research Agent gains new primitives:

```python
# New browser primitives
class ResearchBrowserV2(ResearchBrowser):
    """Extended browser with Phase 9 capabilities."""

    def cite_expand(
        self,
        paper_id: str,
        direction: str = "both",
        depth: int = 1
    ) -> list[CitationResult]:
        """Expand search via citation chains."""

    def knowledge_query(
        self,
        query: str
    ) -> list[KnowledgeResult]:
        """Query knowledge graph for facts."""

    def frontier_status(
        self,
        topic: str
    ) -> FrontierStatus:
        """Get trend/saturation status for topic."""
```

**Updated System Prompt:**
```
## Additional Tools (Phase 9)

### 5. cite_expand(paper_id, direction, depth)
Expand your search using citation relationships.
- Use when keyword search isn't finding related work
- `direction`: "forward" (papers citing this), "backward" (references), "both"
- Returns related papers with relationship explanation

### 6. knowledge_query(query)
Query extracted facts across all papers.
- Use for comparative questions: "Which methods beat X on dataset Y?"
- Returns structured results with evidence

### 7. frontier_status(topic)
Check if a research area is emerging, saturated, or stable.
- Use before deep-diving into a topic
- Returns trend analysis and recommendations
```

### 9.2 Discovery Integration

Citation and knowledge data enhance discovery:

```python
class EnhancedDiscoveryServiceV2(EnhancedDiscoveryService):
    """Discovery with Phase 9 enhancements."""

    def search(self, query: str, config: SearchConfig) -> list[Paper]:
        # 1. Base semantic search
        candidates = super().search(query, config)

        # 2. Citation expansion (if enabled)
        if config.expand_citations:
            seed_papers = candidates[:config.citation_seed_count]
            expanded = self.citation_service.expand(seed_papers)
            candidates = self._merge_unique(candidates, expanded)

        # 3. Knowledge filtering (if enabled)
        if config.knowledge_filters:
            candidates = self.knowledge_service.filter(
                candidates,
                config.knowledge_filters
            )

        # 4. Frontier-aware ranking (if enabled)
        if config.frontier_boost:
            candidates = self._apply_frontier_boost(candidates)

        return candidates
```

### 9.3 Monitoring Integration

Monitoring feeds other systems:

```python
# When new paper detected
async def on_new_paper_detected(paper: Paper, subscription: Subscription):
    # 1. Score relevance
    score = await relevance_scorer.score(paper, subscription)

    if score >= subscription.min_relevance_score:
        # 2. Add to registry for deduplication
        await registry_service.register(paper)

        # 3. Optionally expand citation graph
        if subscription.auto_expand_citations:
            await citation_service.build_graph(paper.id, depth=1)

        # 4. Optionally ingest into DRA corpus
        if subscription.auto_ingest and score >= 0.9:
            await corpus_manager.ingest(paper)

        # 5. Queue for digest
        await digest_queue.add(paper, subscription, score)
```

---

## 10. Security Requirements

### SR-9.1: API Key Management

All external API keys (Semantic Scholar, OpenAlex) SHALL be managed via environment variables.

**Implementation:**
- Never hardcode API keys
- Use `SEMANTIC_SCHOLAR_API_KEY`, `OPENALEX_EMAIL` env vars
- Log API usage but never log keys

### SR-9.2: Rate Limiting

All external API calls SHALL respect rate limits.

**Limits:**
| API | Rate Limit | Implementation |
|-----|------------|----------------|
| Semantic Scholar | 100 req/5min | Token bucket |
| OpenAlex | Polite pool (email required) | Request spacing |
| ArXiv | 3 req/sec | Fixed delay |

### SR-9.3: Data Sanitization

All extracted entities and relations SHALL be sanitized.

**Implementation:**
- Strip HTML/scripts from extracted text
- Validate entity names against allowed patterns
- Truncate oversized fields
- Reject malformed JSON from LLM

### SR-9.4: Graph Integrity

Graph operations SHALL maintain referential integrity.

**Implementation:**
- Foreign key constraints on edges
- Atomic transactions for multi-node updates
- Checksums for graph exports

### SR-9.5: Subscription Limits

Subscriptions SHALL be limited to prevent resource exhaustion.

**Limits:**
- Max 50 subscriptions per user
- Max 100 keywords per subscription
- Max 1000 papers checked per cycle

---

## 11. Cost Analysis & Optimization

### 11.1 LLM Cost Breakdown

| Operation | Model | Cost/Call | Frequency | Monthly Est. |
|-----------|-------|-----------|-----------|--------------|
| Relevance scoring | Haiku | $0.0003 | 500/day | $4.50 |
| Entity extraction | Sonnet | $0.015 | 50/day | $22.50 |
| Relation extraction | Sonnet | $0.015 | 50/day | $22.50 |
| Entity resolution | Haiku | $0.0003 | 100/week | $0.50 |
| Trend summary | Sonnet | $0.015 | 4/month | $0.06 |
| **Total** | | | | **~$50/month** |

### 11.2 API Cost Breakdown

| API | Free Tier | Paid Rate | Est. Usage | Monthly Est. |
|-----|-----------|-----------|------------|--------------|
| Semantic Scholar | 100 req/5min | Free | 10K/month | $0 |
| OpenAlex | Unlimited | Free | 50K/month | $0 |
| ArXiv | Unlimited | Free | 5K/month | $0 |
| **Total** | | | | **$0** |

### 11.3 Cost Optimization Strategies

1. **Tiered Model Selection:**
   - Haiku for scoring/classification (cheap)
   - Sonnet for extraction (balanced)
   - Opus only for complex reasoning (expensive, rare)

2. **Aggressive Caching:**
   - Cache relevance scores (24h TTL)
   - Cache entity extractions (permanent)
   - Cache citation data (7d TTL)

3. **Batch Processing:**
   - Batch entity extraction requests
   - Batch citation API calls

4. **Lazy Extraction:**
   - Extract entities only for high-relevance papers
   - Defer full extraction until paper is accessed

---

## 12. Implementation Schedule

### 12.1 Timeline Overview

```
Week  1  2  3  4  5  6  7  8  9  10 11 12 13 14
      ├──────────┼──────────────┼────────────────┼──────────────┤
      │ 9.1 Mon. │ 9.2 Citation │ 9.3 Knowledge  │ 9.4 Frontier │
      │  2 wks   │   3 wks      │    4 wks       │    3 wks     │
      └──────────┴──────────────┴────────────────┴──────────────┘
```

### 12.2 Milestone 9.1: Proactive Monitoring (Weeks 1-2)

| Week | Tasks |
|------|-------|
| 1 | Data models, subscription manager, ArXiv monitor |
| 2 | Relevance scorer, digest generator, CLI, tests |

**Deliverables:**
- `src/services/intelligence/monitoring/` complete
- CLI commands: `arisp monitor add/list/check/digest`
- 100% test coverage

### 12.3 Milestone 9.2: Citation Graph (Weeks 3-5)

| Week | Tasks |
|------|-------|
| 3 | Graph builder, S2/OpenAlex integration, storage |
| 4 | Citation crawler, coupling analyzer |
| 5 | Influence scorer, recommender, CLI, tests |

**Deliverables:**
- `src/services/intelligence/citation/` complete
- CLI commands: `arisp citation build/related/influence`
- 100% test coverage

### 12.4 Milestone 9.3: Knowledge Graph (Weeks 6-9)

| Week | Tasks |
|------|-------|
| 6 | Entity extractor, extraction prompts |
| 7 | Relation extractor, graph store |
| 8 | Entity resolution, query engine |
| 9 | Contradiction detector, CLI, tests |

**Deliverables:**
- `src/services/intelligence/knowledge/` complete
- CLI commands: `arisp knowledge extract/query/compare`
- 100% test coverage

### 12.5 Milestone 9.4: Frontier Detection (Weeks 10-12)

| Week | Tasks |
|------|-------|
| 10 | Trend analyzer, emergence detector |
| 11 | Saturation scorer, gap finder |
| 12 | Strategic advisor, CLI, tests |

**Deliverables:**
- `src/services/intelligence/frontier/` complete
- CLI commands: `arisp frontier trends/gaps/recommend`
- 100% test coverage

### 12.6 Integration & Polish (Weeks 13-14)

| Week | Tasks |
|------|-------|
| 13 | DRA integration, discovery integration |
| 14 | Documentation, performance tuning, final tests |

**Deliverables:**
- Full integration with existing systems
- User documentation
- Performance benchmarks
- 99%+ overall test coverage

---

## 13. Success Metrics

### 13.1 Milestone 9.1 (Monitoring)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Paper detection latency | < 24h from ArXiv publication | Timestamp comparison |
| Relevance precision | > 80% | Manual review of top-scored papers |
| Digest generation time | < 30s | Timing measurement |
| Subscription CRUD | 100% reliability | Automated tests |

### 13.2 Milestone 9.2 (Citation)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Graph build time | < 60s for depth=2 | Timing measurement |
| Citation coverage | > 95% of S2 data | Comparison with API |
| Coupling accuracy | > 85% | Manual verification |
| Related paper precision | > 70% | User feedback |

### 13.3 Milestone 9.3 (Knowledge)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Entity extraction precision | > 85% | Manual annotation comparison |
| Entity extraction recall | > 75% | Manual annotation comparison |
| Relation extraction F1 | > 70% | Manual annotation comparison |
| Query latency | < 2s | Timing measurement |

### 13.4 Milestone 9.4 (Frontier)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Trend prediction accuracy | > 70% | Retrospective validation |
| Gap identification precision | > 60% | Expert review |
| Recommendation usefulness | > 3.5/5 | User ratings |

### 13.5 Overall Phase 9

| Metric | Target | Measurement |
|--------|--------|-------------|
| Test coverage | ≥ 99% | pytest-cov |
| Test pass rate | 100% | CI pipeline |
| Documentation completeness | 100% | Checklist |
| Integration stability | 0 regressions | Integration tests |

---

## 14. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| API rate limits too restrictive | High | Medium | Implement caching, request batching |
| LLM extraction quality insufficient | High | Medium | Iterative prompt tuning, human review |
| Graph storage too slow at scale | Medium | Low | Migrate to Neo4j if needed |
| Entity resolution creates false merges | Medium | Medium | Conservative thresholds, verification step |
| Trend detection too noisy | Medium | Medium | Longer time windows, smoothing |
| Scope creep delays milestones | High | Medium | Strict milestone boundaries, MVP first |
| Citation data incomplete for recent papers | Medium | High | Combine multiple sources, handle gracefully |
| Cost exceeds budget | Medium | Low | Tiered models, aggressive caching |

---

## 15. Dependencies

### 15.1 New Python Dependencies

| Package | Version | Purpose | License |
|---------|---------|---------|---------|
| `networkx` | ≥3.0 | In-memory graph operations | BSD |
| `aiosqlite` | ≥0.19 | Async SQLite access | MIT |
| `feedparser` | ≥6.0 | ArXiv RSS parsing | BSD |
| `schedule` | ≥1.2 | Job scheduling | MIT |

### 15.2 Optional Dependencies

| Package | Version | Purpose | When Needed |
|---------|---------|---------|-------------|
| `neo4j` | ≥5.0 | Production graph database | Scale > 100K nodes |
| `pyvis` | ≥0.3 | Graph visualization | Visualization feature |

### 15.3 Existing Dependencies Reused

- `pydantic` — Data models
- `httpx` — API clients
- `structlog` — Logging
- LLM service (Phase 5.1) — Entity/relation extraction
- Registry service (Phase 3.5) — Paper deduplication
- Discovery service (Phase 6) — Paper providers

---

## 16. Design Decisions

This section documents key architectural decisions with options considered, trade-offs, and rationale.

### 16.1 Graph Storage

**Decision:** SQLite with adjacency tables, designed for Neo4j migration

| Option | Pros | Cons |
|--------|------|------|
| **SQLite + JSON** | Zero dependencies, portable, embedded, sufficient for <100K nodes, familiar SQL, easy backup | Limited graph traversal performance, no native Cypher, manual relationship management |
| **Neo4j** | Native graph queries (Cypher), excellent traversal performance, built-in algorithms (PageRank), scales to millions | Operational overhead (server process), learning curve, Docker dependency |
| **Hybrid (SQLite → Neo4j)** | Start simple, migrate when needed | Migration complexity, two codepaths |

**Rationale:**
- Milestones 9.1 and 9.4 don't need graph traversal - SQLite sufficient
- Milestone 9.2 depth=2 traversal manageable with recursive CTEs
- Neo4j adds operational complexity not justified until >1M nodes
- SQLite keeps system self-contained (no Docker, no server process)

---

#### Migration Path: SQLite → Neo4j

**Architecture for Migration-Readiness:**

> **Implementation note (PR #105):** The shipped Protocol is intentionally
> narrower than the original draft below. PageRank (and any future graph
> algorithm) lives in a sibling `GraphAlgorithms` class in
> `src/storage/intelligence_graph/algorithms.py` rather than on the Protocol
> itself. Bulk insert APIs (`add_nodes_batch`, `add_edges_batch`) were added
> with a `_MAX_BULK_BATCH_SIZE = 10_000` DoS guard. See [Section 17:
> Implementation Notes](#17-implementation-notes-as-built-foundation) for
> rationale on both decisions.

```python
# Abstract interface - ALL CRUD + traversal goes through this
class GraphStore(Protocol):
    """Abstract graph storage interface for migration flexibility.

    Algorithms (PageRank, etc.) are NOT on this Protocol — they live in
    GraphAlgorithms and operate on a store via narrow read primitives.
    """

    # Node operations
    def add_node(self, node_id: str, node_type: NodeType, properties: dict[str, Any]) -> GraphNode: ...
    def get_node(self, node_id: str) -> GraphNode | None: ...
    def update_node(
        self,
        node_id: str,
        properties: dict[str, Any],
        expected_version: int | None = None,
    ) -> GraphNode: ...
    def delete_node(self, node_id: str) -> bool: ...

    # Bulk node insert (PR #105) — atomic in a single transaction.
    # Rolls back the entire batch on any constraint violation. Callers
    # must chunk inputs to <= _MAX_BULK_BATCH_SIZE (10_000) rows.
    def add_nodes_batch(self, nodes: Sequence[GraphNode]) -> None: ...

    # Edge operations
    def add_edge(
        self,
        edge_id: str,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        properties: dict[str, Any],
    ) -> GraphEdge: ...
    def get_edge(self, edge_id: str) -> GraphEdge | None: ...
    def get_edges(
        self,
        node_id: str,
        direction: str = "both",
        edge_type: EdgeType | None = None,
    ) -> list[GraphEdge]: ...
    def delete_edge(self, edge_id: str) -> bool: ...

    # Bulk edge insert (PR #105) — atomic in a single transaction.
    # Raises ReferentialIntegrityError on missing source/target; rolls
    # back on any constraint violation. Capped at _MAX_BULK_BATCH_SIZE.
    def add_edges_batch(self, edges: Sequence[GraphEdge]) -> None: ...

    # Graph traversal (abstracted for both backends)
    def traverse(
        self,
        start_id: str,
        edge_types: list[EdgeType],
        max_depth: int,
        direction: str = "outgoing",
    ) -> list[GraphNode]: ...
    def shortest_path(
        self, source_id: str, target_id: str
    ) -> list[GraphNode] | None: ...

    # Metrics
    def get_node_count(self, node_type: NodeType | None = None) -> int: ...
    def get_edge_count(self, edge_type: EdgeType | None = None) -> int: ...


# Algorithms live OFF the Protocol so backends do not have to reimplement
# them and so callers must opt in to which edge types they want to follow.
class GraphAlgorithms:
    """Stateless container for graph algorithms operating on a store."""

    @staticmethod
    def pagerank(
        store: _PageRankReadable,
        edge_types: list[str],          # REQUIRED — no implicit "cites" default
        damping: float = 0.85,
        iterations: int = 20,
        node_type: NodeType | None = None,
    ) -> dict[str, float]:
        """Iterative PageRank suitable for small/medium graphs.

        Raises ValueError if edge_types is empty. The store is duck-typed
        against the read primitives `_list_node_ids` and
        `_list_edges_by_types`; SQLiteGraphStore exposes both, and a future
        Neo4jGraphStore will provide the same primitives or wrap the
        backend's native PageRank.
        """
        ...


# Implementations
class SQLiteGraphStore:
    """SQLite implementation with adjacency tables.

    Lives in src/storage/intelligence_graph/unified_graph.py and structurally
    satisfies the GraphStore Protocol (which is @runtime_checkable).
    """
    ...

class Neo4jGraphStore:
    """Neo4j implementation with native Cypher (future)."""
    ...
```

**Migration Triggers (When to Consider Neo4j):**

| Metric | SQLite Comfort Zone | Migration Trigger |
|--------|---------------------|-------------------|
| **Node count** | <100K | >500K |
| **Edge count** | <500K | >2M |
| **Traversal depth** | ≤2 hops | >3 hops needed frequently |
| **Query latency (traversal)** | <500ms | >2s consistently |
| **Concurrent users** | 1-5 | >10 simultaneous |
| **Algorithm needs** | Basic PageRank | Community detection, centrality |

**Migration Process:**

```
Phase 1: Preparation (during normal development)
├── All code uses GraphStore interface (no direct SQLite calls)
├── Unit tests use interface, can run against both backends
└── Export script: SQLite → Neo4j bulk import format (CSV)

Phase 2: Migration (when triggers hit)
├── Deploy Neo4j alongside SQLite (read from both, write to both)
├── Validate data consistency between backends
├── Performance benchmark on production queries
└── Gradual traffic shift with feature flag

Phase 3: Cutover
├── Switch default backend to Neo4j
├── Keep SQLite as backup for 30 days
└── Remove SQLite dependency after validation
```

**Configuration for Backend Selection:**

```yaml
# config/research_config.yaml
intelligence:
  graph_storage:
    backend: "sqlite"  # or "neo4j"
    sqlite:
      path: "./data/intelligence/graph.db"
    neo4j:  # Ignored if backend != neo4j
      uri: "bolt://localhost:7687"
      username: "${NEO4J_USER}"
      password: "${NEO4J_PASSWORD}"
```

**Compatibility Guarantees:**
1. All queries work identically on both backends (same results, different performance)
2. Data export/import scripts maintain full fidelity
3. Application code never imports backend-specific modules directly
4. Integration tests run against both backends in CI (when Neo4j added)

---

### 16.2 Entity Resolution Strategy

**Decision:** Tiered strategy with conservative defaults

| Option | Pros | Cons |
|--------|------|------|
| **Conservative** (high threshold) | Fewer false merges, preserves distinctions | More duplicates, fragmented graph |
| **Aggressive** (lower threshold) | Cleaner graph, better queries | Risk of merging distinct concepts |
| **Tiered** (auto + flagged) | Best of both worlds | More complex implementation |

**Merge Rules:**
```
AUTO_MERGE:    Same paper_id + exact canonical_name (after normalization)
AUTO_MERGE:    Name appears in other entity's alias list (explicit mapping)
SUGGEST_MERGE: Exact name + same type + different paper (human review)
SUGGEST_MERGE: Embedding similarity >0.9, no name match (human review)
KEEP_SEPARATE: Ambiguous terms ("BERT", "Transformer", "Adam")
```

**Note:** "Same context" is intentionally NOT used for AUTO_MERGE as context
matching is non-deterministic. Context similarity triggers SUGGEST_MERGE instead.

**Rationale:**
- False merges corrupt the knowledge graph permanently
- False separates can be fixed later with merge operations
- Conservative by default, aggressive opt-in

---

### 16.3 LLM Model Selection

**Decision:** Three-tier model strategy

| Tier | Model | Use Cases | Cost/1M tokens |
|------|-------|-----------|----------------|
| **Tier 1 (Fast/Cheap)** | Gemini Flash | Relevance scoring, entity verification, classification | $0.075 in / $0.30 out |
| **Tier 2 (Balanced)** | Claude Sonnet | Entity extraction, relation extraction, summarization | $3 in / $15 out |
| **Tier 3 (Quality)** | Claude Sonnet (extended) | Contradiction detection, complex queries | $3 in / $15 out |

**Options Considered:**

| Option | Monthly Cost Est. | Quality |
|--------|-------------------|---------|
| All Haiku | ~$15 | Insufficient for extraction |
| All Sonnet | ~$75 | Overkill for simple tasks |
| Haiku + Sonnet | ~$50 | Good but Gemini cheaper |
| **Gemini Flash + Sonnet** | ~$35 | Optimal cost/quality |

**Rationale:**
- Gemini Flash is 4x cheaper than Haiku for simple tasks
- Sonnet handles extraction well; Opus not needed
- Keep Opus available for future complex reasoning tasks

---

### 16.4 Visualization

**Decision:** Defer to Phase 10, provide export + ASCII tree

| Option | Effort | Value |
|--------|--------|-------|
| **Include in Phase 9** | 2-3 weeks | Nice UX, helps understanding |
| **Defer to Phase 10** | 0 weeks | Focus on core functionality |
| **CLI export only** | 1 week | Users can use Gephi, Obsidian |

**Compromise Implemented:**
- Export graph data in standard formats (GraphML, JSON)
- Simple ASCII tree rendering: `arisp citation tree <paper_id>`
- Defer interactive visualization to Phase 10

**Rationale:**
- Core value is data and queries, not visualization
- Building good visualization UI is separate skill set
- Users can export to existing tools (Gephi, Obsidian graph view)

---

### 16.5 Multi-User Support

**Decision:** Single-user MVP with `user_id` field for future

| Option | Effort | Value |
|--------|--------|-------|
| **Multi-user from start** | +3-4 weeks | Future-proof, team collab |
| **Single-user MVP** | 0 weeks | Simpler, faster |
| **Single-user + user_id field** | +1 week | Easy migration path |

**Implementation:**
```python
class Subscription(BaseModel):
    user_id: str = Field(default="default")  # Ready for multi-user
    # ... rest of fields
```

**Rationale:**
- Current ARISP is single-user; no immediate requirement
- Adding `user_id` field is minimal effort
- Authentication/authorization deferred to Phase 10+

---

### 16.6 Monitoring Task Scheduling

**Decision:** Scheduled batch jobs every 6 hours (configurable) + on-demand refresh

**What this controls:** How often the system checks ArXiv/other sources for new papers matching subscriptions.

| Option | Paper Detection Latency | Resource Use |
|--------|-------------------------|--------------|
| **Real-time (streaming)** | Minutes | High (constant polling) |
| **Hourly** | 1-2 hours | Medium |
| **Daily** | Up to 24 hours | Low |
| **6-hour + on-demand** (chosen) | 6h typical, immediate when requested | Medium |

**Configuration:**
```yaml
monitoring:
  check_interval_hours: 6  # Scheduled job frequency (configurable: 1-24)
  digest_schedule: "daily"  # When to generate digest emails ("daily" or "weekly")
```

**Rationale:**
- ArXiv updates in daily batches (submission deadlines) - more frequent polling doesn't help
- 6 hours catches papers within reasonable time without wasting resources
- `arisp monitor check` provides on-demand refresh for immediate needs
- Digest generation is separate from paper checking (daily/weekly summary)

---

### 16.7 Milestone Ordering

**Decision:** Keep current order (Monitoring → Citation → Knowledge → Frontier)

| Order | Rationale | Risk |
|-------|-----------|------|
| **Citation first** | Most impactful for discovery | Loses quick early win |
| **Knowledge first** | Feeds all other layers | Highest complexity, risky |
| **Monitoring first** (chosen) | Simplest, quick win, creates data stream | None significant |

**Dependency Analysis:**
```
Monitoring (standalone) → Citation (uses new papers) → Knowledge (uses graph) → Frontier (uses all)
```

**Rationale:**
1. Monitoring is simplest - quick team win, builds confidence
2. Monitoring creates paper stream - feeds Citation and Knowledge
3. Citation before Knowledge - Citation is well-defined, Knowledge needs iteration
4. Frontier last - depends on all previous layers

---

### 16.8 MVP Scope per Milestone

#### Engineering Foundation (ALL Milestones)

Every milestone MVP **must** include:

| Requirement | Standard | Rationale |
|-------------|----------|-----------|
| **Test Coverage** | ≥99% (unit + integration) | Non-negotiable per CLAUDE.md |
| **Type Safety** | Mypy clean, full type hints | Catch errors at compile time |
| **Data Models** | Pydantic V2 with validation | Runtime validation, serialization |
| **Error Handling** | Typed exceptions, graceful degradation | Production reliability |
| **Logging** | structlog with correlation IDs | Observability, debugging |
| **Security** | All SR-9.x requirements verified | Security-first development |
| **Documentation** | Docstrings, module README | Maintainability |
| **Code Quality** | Black, Flake8, SOLID principles | Consistency, readability |

**Verification Checklist (per milestone):**
- [ ] `./verify.sh` passes 100%
- [ ] All new modules have ≥99% coverage
- [ ] Security requirements verified
- [ ] Integration tests with existing systems
- [ ] CLI commands documented in `--help`
- [ ] Structured logging in place

---

#### Milestone 9.1 (Monitoring) - 2 weeks

| Feature | MVP | Post-MVP |
|---------|:---:|:--------:|
| Subscription CRUD | ✅ | |
| ArXiv monitoring | ✅ | |
| Relevance scoring | ✅ | |
| Daily digest | ✅ | |
| Weekly digest | | ✅ |
| Immediate alerts | | ✅ |
| Multi-source (S2, HF) | | ✅ |

#### Milestone 9.2 (Citation) - 3 weeks

| Feature | MVP | Post-MVP |
|---------|:---:|:--------:|
| Graph build (depth=1) | ✅ | |
| Backward citations | ✅ | |
| Forward citations | ✅ | |
| Coupling analysis | ✅ | |
| Influence scoring (PageRank) | | ✅ |
| Recommendations | | ✅ |
| Depth=2+ crawling | | ✅ |

#### Milestone 9.3 (Knowledge) - 4 weeks

| Feature | MVP | Post-MVP |
|---------|:---:|:--------:|
| Entity extraction | ✅ | |
| Relation extraction | ✅ | |
| Basic queries | ✅ | |
| Entity resolution (conservative) | ✅ | |
| Comparison queries | | ✅ |
| Contradiction detection | | ✅ |
| Natural language queries | | ✅ |

#### Milestone 9.4 (Frontier) - 3 weeks

| Feature | MVP | Post-MVP |
|---------|:---:|:--------:|
| Trend analysis | ✅ | |
| Emergence detection | ✅ | |
| Saturation scoring | | ✅ |
| Gap detection | | ✅ |
| Strategic recommendations | | ✅ |

---

### 16.9 DRA Browser Enhancement Schedule

**Decision:** Extend DRA browser with new primitives as each milestone completes

**Context:** Phase 8.4 completes the initial DRA integration (corpus + browser + agent + trajectory). Phase 9 **extends** the DRA browser with new intelligence primitives—this is enhancement, not a dependency.

| Milestone | New DRA Primitive | Description |
|-----------|-------------------|-------------|
| After 9.1 | None needed | Monitoring is standalone (subscriptions, digests) |
| After 9.2 | `cite_expand(paper_id, direction, depth)` | Expand search via citation chains |
| After 9.3 | `knowledge_query(query)` | Query extracted facts across papers |
| After 9.4 | `frontier_status(topic)` | Get trend/saturation status |

**Rationale:**
- Each primitive is independent and can be added incrementally
- High-value primitives (cite_expand, knowledge_query) available early
- No blocking dependencies between milestones and DRA enhancement

---

### 16.10 Backward Compatibility

**Decision:** Audit complete - Low risk (additive changes only)

| Existing System | Risk | Mitigation |
|-----------------|------|------------|
| Discovery Service | Low | New methods only, no modifications |
| DRA Browser | Low | New primitives are additive |
| Registry Service | Low | No schema changes |
| LLM Service | Low | New prompt templates only |
| CLI | Low | New command groups, no conflicts |

**Compatibility Commitments:**
1. All existing CLI commands unchanged
2. All existing APIs unchanged
3. New command groups: `arisp monitor`, `arisp citation`, `arisp knowledge`, `arisp frontier`
4. New packages: `src/services/intelligence/` (milestone consumers) and
   `src/storage/intelligence_graph/` (cross-cutting graph persistence) — no
   modifications to existing packages
5. Optional DRA integration flags (`--enable-citation-expand`, etc.)

---

## 17. Implementation Notes (As-Built Foundation)

This section records architectural decisions made during the Phase 9
foundation build (PR #105) that diverge from earlier drafts of this spec.
The decisions are reflected throughout Sections 3, 8, and 16; this section
gives the rationale in one place so reviewers do not have to reconstruct
it from the diff.

All four decisions were locally scoped to the foundation layer
(storage + shared models) and were chosen so that the downstream
milestone work (9.1 Monitoring, 9.2 Citation, 9.3 Knowledge,
9.4 Frontier) can build on a stable, narrow surface.

### 17.1 Storage moved to `src/storage/intelligence_graph/`

**What changed.** The graph storage layer moved from
`src/services/intelligence/storage/` to
`src/storage/intelligence_graph/`.

**Rationale.** Graph persistence is a cross-cutting primitive — the
monitoring service writes subscription nodes, the citation service writes
paper/citation edges, the knowledge service writes entities/relations,
and the frontier service reads aggregates. Keeping it nested inside one
of its own consumers (`services/intelligence/`) implied an ownership it
does not have. The top-level `src/storage/` namespace already hosts other
backends and is the natural home for a layer that any service may consume
without introducing a service↔service dependency. The move is purely
relocation — the public surface (`GraphStore`, `SQLiteGraphStore`,
`MigrationManager`, `TimeSeriesStore`) is unchanged and re-exported from
the new package's `__init__.py`.

### 17.2 PageRank extracted to `GraphAlgorithms`

**What changed.** `pagerank()` was removed from the `GraphStore` Protocol
and lives on a sibling `GraphAlgorithms` class in
`src/storage/intelligence_graph/algorithms.py`. The signature now takes
the store as its first argument and **requires** an explicit `edge_types`
parameter (no implicit `cites` default). It also accepts an optional
`node_type` filter so callers can score only papers, only entities, etc.

**Rationale.** Three concerns motivated the extraction:

1. **Protocol minimality.** A storage Protocol should describe persistence
   primitives, not algorithm catalog entries. Mixing them forces every
   backend (SQLite today, Neo4j tomorrow) to either reimplement the
   algorithm or fall back to a stub — both bad outcomes. With the algorithm
   off-Protocol, a single Python implementation runs against any backend
   that exposes the read primitives.
2. **Explicit edge-type semantics.** The original implementation hardcoded
   `cites`. That silently mis-ran for any caller wanting blended PageRank
   over `cites + mentions`, or topic-level PageRank over `belongs_to`.
   Requiring the caller to opt in eliminates a footgun.
3. **Reuse across milestones.** Milestone 9.4 (frontier) wants
   topic-restricted PageRank over `belongs_to`; Milestone 9.2 wants
   citation PageRank over `cites`. One algorithm, two configurations,
   zero subclassing.

The store side exposes two read primitives (`_list_node_ids`,
`_list_edges_by_types`) that the algorithm consumes. They are
intentionally underscore-prefixed and **not** part of the Protocol — they
are an algorithm-internal contract, not a stable public API.

### 17.3 Bulk insert APIs (`add_nodes_batch`, `add_edges_batch`)

**What changed.** `add_nodes_batch(nodes)` and `add_edges_batch(edges)`
were added to the `GraphStore` Protocol. Both insert atomically in one
transaction (`with conn:` / `executemany`), roll back the entire batch
on any constraint violation, log a single INFO record on success, and
reject batches over `_MAX_BULK_BATCH_SIZE = 10_000` rows with a
`ValueError`.

**Rationale.** Per-row inserts dominate runtime when the citation crawler
or entity extractor flushes a paper's worth of nodes/edges (often hundreds
to low thousands at a time). Batching collapses that into one transaction
and one commit, with order-of-magnitude throughput improvement on SQLite.
The `_MAX_BULK_BATCH_SIZE = 10_000` cap is a DoS guard: each row holds a
JSON-serialized properties blob in memory while the executemany payload
is built, so an unbounded count from an upstream caller could trivially
push 10 MB+ of memory pressure (and a multi-second pause) per call.
Callers with more rows must chunk upstream — that keeps the chunking
policy explicit at the call site instead of hidden inside the storage
layer. Edge bulk insert distinguishes `ReferentialIntegrityError`
(missing source/target) from generic `GraphStoreError` (e.g. duplicate
edge_id) so callers can react appropriately.

### 17.4 Concurrency model: WAL + `BEGIN IMMEDIATE` + optimistic locking

**What changed.** Section 8.3 now documents the full concurrency stack:

- `journal_mode = WAL` (writers don't block readers)
- `synchronous = NORMAL` (durability vs. throughput balance)
- `busy_timeout = 5000` (5 s wait before raising `SQLITE_BUSY`)
- `BEGIN IMMEDIATE` at the start of `update_node` and the bulk insert
  transactions (write lock acquired up-front)
- Optimistic locking via `version` columns on `GraphNode` / `GraphEdge`,
  surfaced as `OptimisticLockError(node_id, expected, actual)` with the
  actual version re-queried after a conflict so the error reports truth.

**Rationale.** The Phase 9 pipelines run several writers and many readers
against the same SQLite file — monitoring jobs, citation refresh,
knowledge extraction, and ad-hoc CLI queries can all be live simultaneously.
WAL is the standard SQLite answer for that read/write mix. `BEGIN
IMMEDIATE` was chosen specifically to close a read-then-update race in
`update_node`: without it, two workers could each `SELECT` the same
`version`, both compute their `version+1`, and then the second `UPDATE`
would silently observe a row count of zero — which we'd then have to
distinguish from a genuine version mismatch. Acquiring the write lock
up-front collapses that ambiguity. The 5 s `busy_timeout` absorbs short
contention (typical bulk insert is well under 1 s) without surfacing
`SQLITE_BUSY` to application code, while still providing an upper bound
that prevents indefinite blocking. The `version` field stays on the model
(rather than being a hidden storage detail) because future Neo4j or
Postgres backends will want to honor the same optimistic-locking contract.

### 17.5 Reference

- **PR:** [#105 — Phase 9 foundation](https://github.com/leixiaoyu/research-assistant/pull/105)
  (storage relocation, GraphAlgorithms split, bulk APIs, concurrency model)
- **Open questions log:** `.omc/plans/open-questions.md` (decisions 3 & 4
  recorded under "Phase 9 — 2026-04-22")

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **Bibliographic Coupling** | Two papers sharing many references are likely related |
| **Citation Chain** | Sequence of papers connected by citations |
| **Co-citation** | Two papers frequently cited together |
| **Emergence** | A concept appearing significantly more over time |
| **Entity Resolution** | Merging duplicate entities into canonical form |
| **Frontier** | The boundary between known and unknown research |
| **Knowledge Graph** | Graph of entities and relationships extracted from text |
| **PageRank** | Algorithm for measuring node importance in a graph |
| **Saturation** | A research area with diminishing novelty |
| **Trend Velocity** | Rate of paper publication on a topic |

---

## Appendix B: Related Documents

- [Phase 8 DRA Specification](PHASE_8_DRA_SPEC.md)
- [Phase 6 Discovery Enhancement](PHASE_6_DISCOVERY_ENHANCEMENT_SPEC.md)
- [Phase 3.5 Global Registry](PHASE_3.5_SPEC.md)
- [System Architecture](../SYSTEM_ARCHITECTURE.md)

---

**Document Version:** 1.3
**Status:** 📋 Aligned with as-built foundation (PR #105)
**Last Updated:** 2026-04-24
**Design Decisions:** All 10 design decisions + 4 implementation notes documented
**Next Step:** Downstream milestone PRs (9.1, 9.2) build against this spec

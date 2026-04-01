# Phase 8: Deep Research Agent (DRA) Specification
**Version:** 1.0
**Status:** 📋 Planning
**Timeline:** 4-5 weeks
**Dependencies:**
- Phase 3.5 Complete (Global Paper Registry)
- Phase 5.1 Complete (LLM Service Decomposition)
- Phase 6 Core Complete (Enhanced Discovery, optional integration)

---

## Architecture Reference

This phase transforms ARISP from a pipeline-driven ingestion system into an **autonomous, self-improving research agent**. See [Proposal 004](../proposals/004_OPENRESEARCHER_OFFLINE_TRAJECTORY_SYNTHESIS.md) for complete problem statement and research foundation.

**Architectural Gaps Addressed:**
- ❌ Gap: No iterative, multi-step research capability (single-shot API queries only)
- ❌ Gap: No evidence gathering or cross-paper reasoning
- ❌ Gap: Live API dependency limits reproducibility and scalability
- ❌ Gap: No trajectory learning or self-improvement mechanism

**Components Added:**
- Corpus Manager (src/services/dra/corpus_manager.py)
- Research Browser (src/services/dra/browser.py)
- Deep Research Agent (src/services/dra/agent.py)
- Trajectory Collector & Learning (src/services/dra/trajectory.py)
- Hybrid Search Infrastructure (FAISS + BM25)

**Coverage Targets:**
- Corpus management: ≥99%
- Browser primitives: ≥99%
- Agent loop: ≥95%
- Trajectory learning: ≥95%

---

## 1. Executive Summary

Phase 8 introduces the **Deep Research Agent (DRA)**, an autonomous research system that:
- Executes multi-turn research sessions using browser primitives (search, open, find)
- Operates over an offline corpus built from ARISP's extracted papers
- Learns from its own execution trajectories to improve future research quality
- Enables reproducible, cost-effective deep research without live API dependencies

**What This Phase Is:**
- ✅ Autonomous agent with iterative search-reason-search loops
- ✅ Offline corpus with hybrid retrieval (SPECTER2 + BM25)
- ✅ Trajectory-based learning for continuous improvement
- ✅ ReAct-style reasoning with browser primitives

**What This Phase Is NOT:**
- ❌ Real-time web search agent (offline corpus only)
- ❌ Multi-user collaborative research platform
- ❌ Model fine-tuning service (SFT export is optional)
- ❌ Replacement for existing pipeline (additive only)

**Key Achievement:** Enable ARISP to answer deep research questions requiring multi-hop reasoning, evidence gathering, and synthesis across multiple papers.

---

## 2. Problem Statement

### 2.1 Current Limitations

ARISP currently operates as a **pipeline-driven ingestion system**:

```
User Query → API Call → Papers → Extract → Brief (END)
```

This architecture creates four fundamental limitations:

1. **Shallow Discovery**: Single-shot API queries miss papers requiring iterative refinement or citation chaining
2. **No Multi-Step Reasoning**: Papers processed independently; no cross-paper synthesis or comparative analysis
3. **Live API Dependency**: Every run requires API calls (expensive, rate-limited, non-reproducible)
4. **Static System**: No learning from execution patterns; cannot improve over time

### 2.2 Industry Context

Research from 2025 demonstrates:
- **Agentic systems achieve 34.0+ point improvements** on research benchmarks (OpenResearcher, BrowseComp-Plus)
- **Offline corpus construction enables cost-effective execution** (OpenResearcher: 97K trajectories over 15M documents)
- **Trajectory-informed learning achieves 14.3+ point gains** through pattern analysis (AppWorld benchmark)
- **Enterprise AI spending reached $37B** (2025, 3.2x increase from 2024)

---

## 3. Requirements

### 3.1 Corpus Construction

#### REQ-8.1.1: Registry Integration
The system SHALL ingest all papers from ARISP's global registry (Phase 3.5).

**Scenario: Corpus Ingest**
**Given** the global registry contains 500 extracted papers
**When** `corpus.ingest_from_registry()` is executed
**Then** all 500 papers SHALL be segmented into searchable chunks
**And** metadata (paper_id, section_type, token_count) SHALL be preserved

#### REQ-8.1.2: Section-Level Chunking
Papers SHALL be segmented at section boundaries (abstract, introduction, methods, results, discussion, conclusion).

**Chunking Rules:**
- Maximum 512 tokens per chunk
- Oversized sections split at paragraph boundaries
- Minimum 64-token overlap between consecutive chunks
- Section type metadata preserved for each chunk

#### REQ-8.1.3: Hybrid Search Index
The system SHALL build both dense (FAISS) and sparse (BM25) indices.

**Dense Index:**
- Embedding model: `allenai/specter2` (citation-aware, academic-optimized)
- Vector dimensions: 768
- Index type: Flat (for corpora <100K chunks) or IVF (for larger corpora)

**Sparse Index:**
- Algorithm: BM25 (keyword/exact-match retrieval)
- Tokenization: English stopword removal + lowercase normalization

**Hybrid Retrieval:**
- Combine results using Reciprocal Rank Fusion (RRF)
- Default weights: 0.7 dense + 0.3 sparse
- Configurable per-topic weight tuning

#### REQ-8.1.4: Incremental Refresh
The corpus SHALL support incremental updates without full rebuild.

**Scenario: Incremental Update**
**Given** the corpus contains 500 papers indexed yesterday
**When** 50 new papers are added to the registry
**Then** only the 50 new papers SHALL be chunked and indexed
**And** the existing index SHALL be updated atomically (no downtime)

### 3.2 Browser Primitives

#### REQ-8.2.1: Search Primitive
`search(query: str, top_k: int = 10) -> list[SearchResult]`

**Behavior:**
- Execute hybrid retrieval (dense + sparse)
- Return ranked results with paper_id, title, section, snippet, relevance_score
- Track search queries in trajectory

**Scenario: Search Execution**
**Given** the corpus contains 10 papers on "attention mechanisms"
**When** `search("attention mechanisms transformers", top_k=5)` is called
**Then** 5 results SHALL be returned ranked by relevance
**And** each result SHALL include paper metadata and a 1000-char snippet

#### REQ-8.2.2: Open Primitive
`open(paper_id: str, section: str | None = None) -> DocumentContent`

**Behavior:**
- Retrieve full markdown content of paper or specific section
- Track opened papers/sections in trajectory
- Return structured content with section boundaries

**Scenario: Section-Scoped Open**
**Given** paper "arxiv:2301.12345" has 8 sections
**When** `open("arxiv:2301.12345", section="methods")` is called
**Then** only the "methods" section content SHALL be returned
**And** the opened section SHALL be recorded in the trajectory

#### REQ-8.2.3: Find Primitive
`find(pattern: str, scope: str = "current") -> list[FindResult]`

**Behavior:**
- Locate exact or fuzzy matches within currently opened document
- Support regex patterns for flexible matching
- Return matched text with surrounding context (2 sentences)

**Scenario: Evidence Localization**
**Given** a paper is currently open
**When** `find("BLEU score.*40\\.2")` is called with regex pattern
**Then** all matching occurrences SHALL be returned
**And** each match SHALL include 2 sentences of surrounding context

### 3.3 Agent Loop

#### REQ-8.3.1: ReAct Architecture
The agent SHALL follow the ReAct (Reasoning + Acting) pattern.

**Loop Structure:**
```
for turn in range(max_turns):
    1. LLM generates reasoning + tool call
    2. Execute tool against offline corpus
    3. Observe result
    4. Update trajectory
    5. Check termination (answer produced or budget exhausted)
```

#### REQ-8.3.2: Resource Limits
The agent SHALL enforce configurable resource limits.

**Limits:**
- `max_turns`: 50 (default), configurable 1-200
- `max_context_tokens`: 128,000 (default), configurable 1K-1M
- `max_session_duration_seconds`: 600 (default), configurable 60-3600
- `max_open_documents`: 20 (default), configurable 1-100

**Scenario: Turn Limit Enforcement**
**Given** max_turns is set to 10
**When** the agent executes 10 turns without producing an answer
**Then** the session SHALL terminate with `exhausted=True`
**And** the partial trajectory SHALL be saved

#### REQ-8.3.3: Trajectory Recording
All turns SHALL be recorded in a structured trajectory.

**Turn Data:**
```python
class Turn(BaseModel):
    turn_number: int
    reasoning: str  # Agent's chain-of-thought
    action: ToolCall  # search/open/find with arguments
    observation: str  # Tool response (truncated if needed)
    observation_tokens: int
```

### 3.4 Trajectory Learning

#### REQ-8.4.1: Pattern Analysis
The system SHALL analyze trajectory patterns to extract insights.

**Analysis Outputs:**
- Effective query patterns (e.g., "papers using 'X vs Y' queries find comparative analysis")
- Successful evidence gathering sequences (e.g., "search → open abstract → find metrics → open methods")
- Common failure modes (e.g., "searching for generic terms returns low-relevance papers")
- Average turns to success by question type

#### REQ-8.4.2: Contextual Learning Tips
The system SHALL generate strategy tips from trajectory analysis.

**Tip Structure:**
```python
class ContextualTip(BaseModel):
    context: str  # "When searching for comparative analysis..."
    strategy: str  # "...use 'vs' or 'compared to' in queries"
    confidence: float  # 0.0-1.0
    examples: list[str]  # Trajectory IDs demonstrating success
```

**Scenario: Tip Generation**
**Given** 20 trajectories with comparative analysis questions
**When** 15/20 succeeded using "vs" in search queries
**Then** a tip SHALL be generated with confidence ≥ 0.75
**And** the tip SHALL be injected into future agent system prompts

#### REQ-8.4.3: Quality Filtering
The system SHALL filter low-quality trajectories before analysis.

**Filter Criteria:**
- Minimum 3 turns (remove degenerate sessions)
- Answer produced (remove failed sessions, unless analyzing failure modes)
- Context length within limits (remove truncated sessions)
- No malformed tool calls

**Scenario: Quality Filter Application**
**Given** 100 recorded trajectories
**When** `filter_quality(min_turns=3, require_answer=True)` is applied
**Then** only trajectories meeting ALL criteria SHALL be retained
**And** filter statistics SHALL be logged (X kept, Y rejected by criterion)

### 3.5 Integration with Existing Systems

#### REQ-8.5.1: Registry Service Integration
The DRA SHALL read papers from the global registry (Phase 3.5).

**Scenario: Registry-Corpus Sync**
**Given** the registry contains a paper with extraction results
**When** the corpus is refreshed
**Then** the paper's extracted markdown SHALL be indexed
**And** paper metadata (DOI, ArXiv ID, title) SHALL be searchable

#### REQ-8.5.2: LLM Service Integration
The agent SHALL use the decomposed LLM service (Phase 5.1).

**Scenario: Provider Fallback**
**Given** the primary LLM provider (Claude) returns 429 rate limit error
**When** the agent requests reasoning generation
**Then** the LLM service SHALL automatically fall back to Gemini
**And** the trajectory SHALL record the provider switch

#### REQ-8.5.3: Backward Compatibility
All existing ARISP functionality SHALL remain unchanged.

**Non-Breaking Changes:**
- New package: `src/services/dra/`
- New CLI commands: `arisp research`, `arisp corpus`, `arisp trajectories`
- New config section: `dra_settings` (optional)
- No modifications to existing modules

---

## 4. Technical Design

### 4.1 Data Models

Located in `src/models/dra.py`:

```python
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime

class ChunkType(str, Enum):
    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    METHODS = "methods"
    RESULTS = "results"
    DISCUSSION = "discussion"
    CONCLUSION = "conclusion"
    REFERENCES = "references"
    OTHER = "other"

class CorpusChunk(BaseModel):
    """A searchable unit within the corpus."""
    chunk_id: str = Field(..., description="Unique chunk identifier")
    paper_id: str = Field(..., description="Registry paper ID")
    section_type: ChunkType
    title: str = Field(..., max_length=500)
    content: str = Field(..., min_length=1)
    token_count: int = Field(..., ge=0)
    embedding: list[float] | None = None
    metadata: dict = Field(default_factory=dict)

class SearchResult(BaseModel):
    """Result from a corpus search."""
    chunk_id: str
    paper_id: str
    paper_title: str
    section_type: ChunkType
    snippet: str = Field(..., max_length=1000)
    relevance_score: float = Field(..., ge=0.0, le=1.0)

class FindResult(BaseModel):
    """Result from a find operation within an open document."""
    matched_text: str
    context: str = Field(..., description="Surrounding sentences")
    position: int = Field(..., ge=0)
    section: ChunkType | None = None

class ToolCallType(str, Enum):
    SEARCH = "search"
    OPEN = "open"
    FIND = "find"

class ToolCall(BaseModel):
    """A single tool invocation."""
    tool: ToolCallType
    arguments: dict
    timestamp: datetime

class Turn(BaseModel):
    """A single reasoning-action-observation turn."""
    turn_number: int = Field(..., ge=1)
    reasoning: str
    action: ToolCall
    observation: str
    observation_tokens: int = Field(..., ge=0)

class ResearchResult(BaseModel):
    """Complete result of a research session."""
    question: str
    answer: str | None = None
    trajectory: list[Turn] = Field(default_factory=list)
    papers_consulted: list[str] = Field(default_factory=list)
    total_turns: int = Field(..., ge=0)
    exhausted: bool = False
    total_tokens: int = Field(0, ge=0)
    duration_seconds: float = Field(0.0, ge=0.0)

class TrajectoryInsights(BaseModel):
    """Insights extracted from trajectory analysis."""
    effective_query_patterns: list[str] = Field(default_factory=list)
    successful_sequences: list[str] = Field(default_factory=list)
    failure_modes: dict[str, int] = Field(default_factory=dict)
    average_turns_to_success: float = Field(0.0, ge=0.0)
    paper_consultation_patterns: dict[str, int] = Field(default_factory=dict)

class ContextualTip(BaseModel):
    """Contextual strategy tip learned from trajectories."""
    context: str
    strategy: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    examples: list[str] = Field(default_factory=list)

class TrajectoryRecord(BaseModel):
    """A recorded trajectory with quality metadata and learning insights."""
    trajectory_id: str
    question: str
    answer: str | None
    turns: list[Turn]
    quality_score: float = Field(0.0, ge=0.0, le=1.0)
    papers_opened: int = Field(0, ge=0)
    unique_searches: int = Field(0, ge=0)
    find_operations: int = Field(0, ge=0)
    context_length_tokens: int = Field(0, ge=0)
    insights: TrajectoryInsights | None = None
    created_at: datetime
```

### 4.2 Configuration Schema

Add to `config/research_config.yaml`:

```yaml
# Existing config sections remain unchanged
research_topics:
  - query: "attention mechanisms"
    # ... existing fields

# New DRA settings (optional)
dra_settings:
  corpus:
    embedding_model: "allenai/specter2"
    chunk_max_tokens: 512
    chunk_overlap_tokens: 64
    embedding_batch_size: 32

  search:
    dense_weight: 0.7        # SPECTER2 semantic similarity
    sparse_weight: 0.3       # BM25 keyword matching
    default_top_k: 10
    max_top_k: 50

  agent:
    max_turns: 50
    max_context_tokens: 128000
    max_session_duration_seconds: 600
    max_open_documents: 20
    llm_provider: "claude"
    llm_model: "claude-sonnet-4-20250514"

  trajectory_learning:
    enable_learning: true
    min_trajectories_for_analysis: 10
    learning_refresh_interval_hours: 24
    quality_threshold: 0.6
```

### 4.3 Service Architecture

```
src/services/dra/
├── __init__.py
├── corpus_manager.py       # Corpus ingestion, indexing, refresh
├── browser.py              # search/open/find primitives
├── agent.py                # ReAct loop implementation
├── trajectory.py           # Recording, analysis, learning
├── search_engine.py        # Hybrid retrieval (FAISS + BM25)
└── utils.py                # Chunking, tokenization, normalization
```

### 4.4 CLI Commands

```bash
# Corpus management
arisp corpus build                  # Build initial corpus from registry
arisp corpus refresh                # Incremental update
arisp corpus stats                  # Show corpus statistics

# Research sessions
arisp research "question"           # Interactive research
arisp research --question-file questions.txt  # Batch mode

# Trajectory management
arisp trajectories list             # List all recorded trajectories
arisp trajectories analyze          # Analyze patterns and generate tips
arisp trajectories export --format jsonl  # Export for external use
```

---

## 5. Security Requirements (MANDATORY) 🔒

### SR-8.1: Corpus Integrity (CRITICAL)

**Requirement:** Prevent corpus tampering and ensure index consistency.

**Implementation:**
- SHA-256 checksums for all corpus chunks
- Atomic index swap during refresh (write new → rename into place)
- Corpus directory permissions restricted to 0700
- Validate chunk integrity on load

**Verification:**
- [ ] Unit test: `test_corpus_checksum_validation()`
- [ ] Unit test: `test_atomic_index_swap()`
- [ ] Integration test: Verify corrupted chunk detection

### SR-8.2: Agent Output Sanitization

**Requirement:** Sanitize all agent-generated content before storage.

**Implementation:**
- Strip embedded tool calls or system prompt fragments from reasoning
- Validate tool arguments against allowed patterns
- Truncate observations to configurable maximum length (default: 10K chars)

**Verification:**
- [ ] Unit test: `test_agent_output_sanitization()`
- [ ] Unit test: `test_tool_argument_validation()`

### SR-8.3: Trajectory Data Privacy

**Requirement:** Trajectory exports must not contain sensitive data.

**Implementation:**
- Strip API keys, file paths, system prompts from exports
- Validate export format before writing
- Configurable redaction patterns

**Verification:**
- [ ] Unit test: `test_trajectory_export_no_secrets()`
- [ ] Unit test: `test_redaction_patterns()`

### SR-8.4: Resource Limits

**Requirement:** Prevent runaway agent sessions.

**Implementation:**
```python
class AgentLimits(BaseModel):
    max_turns: int = Field(50, ge=1, le=200)
    max_context_tokens: int = Field(128_000, ge=1000, le=1_000_000)
    max_session_duration_seconds: int = Field(600, ge=60, le=3600)
    max_open_documents: int = Field(20, ge=1, le=100)
```

**Verification:**
- [ ] Unit test: `test_turn_limit_enforced()`
- [ ] Unit test: `test_context_length_limit()`
- [ ] Unit test: `test_session_timeout()`

### SR-8.5: Embedding Model Validation

**Requirement:** Only allow approved embedding models.

**Implementation:**
```python
APPROVED_EMBEDDING_MODELS = {
    "allenai/specter2",
    "allenai/specter",
    "sentence-transformers/all-MiniLM-L6-v2",
}

def validate_embedding_model(model_name: str) -> str:
    if model_name not in APPROVED_EMBEDDING_MODELS:
        raise ValueError(f"Unapproved embedding model: {model_name}")
    return model_name
```

**Verification:**
- [ ] Unit test: `test_approved_models_only()`
- [ ] Unit test: `test_rejected_model_raises()`

---

## 6. Implementation Tasks

### Phase 8.1: Corpus Infrastructure (Week 1-2)

**Goal:** Build offline corpus with hybrid search.

**Files:**
- `src/models/dra.py` (NEW) — Data models
- `src/services/dra/corpus_manager.py` (NEW) — Corpus management
- `src/services/dra/search_engine.py` (NEW) — Hybrid retrieval
- `src/services/dra/utils.py` (NEW) — Utilities
- `tests/unit/test_dra/test_corpus_manager.py` (NEW)
- `tests/unit/test_dra/test_search_engine.py` (NEW)

**Tasks:**
1. Implement `CorpusChunk` and related Pydantic models
2. Implement section-aware markdown parser
3. Integrate SPECTER2 embedding model
4. Implement FAISS index builder with atomic swap
5. Implement BM25 index using `rank_bm25`
6. Implement Reciprocal Rank Fusion
7. Write unit tests (>99% coverage target)

**Success Criteria:**
- 95%+ of registry papers successfully ingested and indexed
- Search latency < 200ms for 10K-chunk corpus
- Hybrid retrieval outperforms dense-only on manual spot checks

### Phase 8.2: Browser Primitives & Agent Loop (Week 2-3)

**Goal:** Implement ReAct agent with browser primitives.

**Files:**
- `src/services/dra/browser.py` (NEW) — search/open/find
- `src/services/dra/agent.py` (NEW) — ReAct loop
- `src/cli/research.py` (NEW) — CLI commands
- `tests/unit/test_dra/test_browser.py` (NEW)
- `tests/unit/test_dra/test_agent.py` (NEW)

**Tasks:**
1. Implement `ResearchBrowser` with all primitives
2. Implement `DeepResearchAgent` ReAct loop
3. Design system prompt with research protocol
4. Implement resource limits and timeout handling
5. Implement output sanitization
6. Create CLI command: `arisp research`
7. Write unit tests (>95% coverage target)

**Success Criteria:**
- Agent produces cited answers for 70%+ of test questions
- Average session completes in < 50 turns
- All resource limits enforced (verified by tests)

### Phase 8.3: Trajectory Collection & Learning (Week 3-4)

**Goal:** Enable self-improvement through trajectory learning.

**Files:**
- `src/services/dra/trajectory.py` (NEW) — Learning system
- `src/cli/trajectories.py` (NEW) — CLI commands
- `tests/unit/test_dra/test_trajectory.py` (NEW)

**Tasks:**
1. Implement `TrajectoryCollector` with recording
2. Implement pattern extraction from trajectory history
3. Implement contextual learning tip generation
4. Implement adaptive memory retrieval
5. Implement quality scoring and filtering
6. Implement JSONL export (ShareGPT format)
7. Create CLI commands: `arisp trajectories`
8. Write unit tests (>95% coverage target)

**Success Criteria:**
- 80%+ of trajectories pass quality filters
- Trajectory analysis produces actionable insights (5+ tips)
- Agent performance improves measurably after learning (10+ trajectories)

### Phase 8.4: Integration & Validation (Week 4-5)

**Goal:** Integrate all components and validate end-to-end.

**Files:**
- `tests/integration/test_dra/test_research_session.py` (NEW)
- `tests/integration/test_dra/test_trajectory_learning.py` (NEW)
- `docs/user_guides/DRA_USER_GUIDE.md` (NEW)

**Tasks:**
1. Batch trajectory synthesis over question sets
2. Decision attribution analysis (failure/success patterns)
3. End-to-end integration tests
4. Performance benchmarking (latency, cost)
5. Documentation (user guide, API reference)

**Success Criteria:**
- Full pipeline executes without errors
- 1000+ quality trajectories generated in batch
- Decision attribution identifies top 5 patterns

---

## 7. Verification Criteria

### 7.1 Unit Tests

**Corpus Manager** (`tests/unit/test_dra/test_corpus_manager.py`):
- `test_ingest_from_registry()` — Papers correctly chunked
- `test_section_chunking()` — Markdown sections identified
- `test_chunk_max_tokens_enforced()` — Oversized sections split
- `test_incremental_refresh()` — Only new papers re-indexed
- `test_corpus_checksum_integrity()` — Corrupted chunks detected

**Browser Primitives** (`tests/unit/test_dra/test_browser.py`):
- `test_search_returns_ranked_results()` — Hybrid scoring
- `test_open_returns_full_content()` — Paper retrieval
- `test_open_tracks_opened_papers()` — Trajectory tracking
- `test_find_exact_match()` — String matching with context
- `test_find_fuzzy_match()` — Regex pattern support

**Agent Loop** (`tests/unit/test_dra/test_agent.py`):
- `test_agent_completes_research()` — Answer produced
- `test_agent_respects_turn_limit()` — Stops at max_turns
- `test_agent_records_trajectory()` — All turns captured
- `test_agent_timeout_enforced()` — Session duration limit

**Trajectory Learning** (`tests/unit/test_dra/test_trajectory.py`):
- `test_record_trajectory()` — Research results stored
- `test_analyze_patterns()` — Insights extracted
- `test_generate_learning_tips()` — Tips generated with confidence
- `test_filter_quality()` — Low-quality trajectories removed
- `test_export_sft_jsonl()` — Valid JSONL export

### 7.2 Integration Tests

**End-to-End Research** (`tests/integration/test_dra/test_research_session.py`):
- `test_full_research_session()` — Ingest → index → research → record
- `test_corpus_refresh_and_re_search()` — New papers discoverable

**Trajectory Learning** (`tests/integration/test_dra/test_trajectory_learning.py`):
- `test_learning_cycle()` — Analyze → tips → improved performance
- `test_tip_injection()` — Tips appear in system prompts

### 7.3 Security Verification

- [ ] Verify no secrets in trajectory exports
- [ ] Verify path sanitization for corpus operations
- [ ] Verify input validation for tool arguments
- [ ] Verify resource limits enforced

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| SPECTER2 embeddings too slow | Medium | Batch embedding with progress; GPU acceleration optional |
| Agent reasoning quality insufficient | High | Start with Claude Sonnet; upgrade to Opus if needed |
| Corpus too small for meaningful retrieval | High | Supplement with OpenResearcher's FineWeb subset |
| FAISS index memory usage | Medium | Use IVF index for corpora >100K chunks |
| Context window exhaustion | Medium | Configurable observation truncation; summarization |
| Learning system produces low-quality tips | Medium | Quality filtering; manual review; confidence scoring |
| Trajectories don't improve performance | High | Baseline A/B testing; iterate on pattern extraction |

---

## 9. Success Metrics

### Phase 8.1 (Corpus)
- [ ] 95%+ of registry papers successfully ingested
- [ ] Search latency < 200ms (10K chunks)
- [ ] Hybrid retrieval outperforms dense-only

### Phase 8.2 (Agent)
- [ ] 70%+ test questions answered with citations
- [ ] Average session < 50 turns
- [ ] All resource limits enforced

### Phase 8.3 (Learning)
- [ ] 80%+ trajectories pass quality filters
- [ ] 5+ actionable contextual tips generated
- [ ] Measurable performance improvement after 10+ trajectories

### Phase 8.4 (Integration)
- [ ] 1000+ quality trajectories in batch synthesis
- [ ] Top 5 failure/success patterns identified
- [ ] Full documentation complete

---

## 10. Dependencies

### New Dependencies

| Package | Version | Purpose | License |
|---------|---------|---------|---------|
| `faiss-cpu` | ≥1.8.0 | Dense vector indexing | MIT |
| `rank-bm25` | ≥0.2.2 | Sparse retrieval | Apache 2.0 |
| `transformers` | ≥4.40.0 | SPECTER2 loading | Apache 2.0 |
| `torch` | ≥2.2.0 | Embedding computation | BSD |

### Existing Dependencies Reused

- `pydantic` — Data models
- LLM service (Phase 5.1) — Agent reasoning
- Registry service (Phase 3.5) — Paper inventory
- Extraction pipeline (Phase 2/2.5) — Markdown content
- Resilience patterns (Phase 3.3) — Circuit breakers, retries

---

**Related Documents:**
- [Proposal 004: DRA Proposal](../proposals/004_OPENRESEARCHER_OFFLINE_TRAJECTORY_SYNTHESIS.md)
- [System Architecture](../SYSTEM_ARCHITECTURE.md)
- [Phase 3.5 Spec: Global Registry](PHASE_3.5_SPEC.md)
- [Phase 5.1 Spec: LLM Service Decomposition](PHASE_5.1_SPEC.md)

---

*Document Version: 1.0*
*Last Updated: 2026-03-31*

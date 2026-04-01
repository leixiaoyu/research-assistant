# Proposal 004: Deep Research Agent (DRA) - Autonomous, Self-Improving Research System

**Author:** AI Engineering Lead
**Date:** 2026-03-31
**Status:** Revised Draft
**Related Spec:** PHASE_8_DRA_SPEC.md
**References:**
- [OpenResearcher (Li et al., 2025)](https://arxiv.org/abs/2603.20278) | [GitHub](https://github.com/TIGER-AI-Lab/OpenResearcher)
- [ReAct: Reasoning and Acting (Yao et al., 2022)](https://arxiv.org/abs/2210.03629)
- [Trajectory-Informed Memory Generation (2025)](https://arxiv.org/abs/2603.10600)
- [ResearchArena Benchmark (2025)](https://arxiv.org/html/2406.10291v2)
- [AgentTrek: Trajectory Synthesis (2025)](https://agenttrek.github.io/)
- [Tongyi DeepResearch (Alibaba, 2025)](https://github.com/Alibaba-NLP/DeepResearch)
- [LangChain Open Deep Research (2025)](https://github.com/langchain-ai/open_deep_research)
- [GPT Researcher](https://github.com/assafelovic/gpt-researcher)
- [SPECTER2 Paper Embeddings (Allen AI)](https://allenai.org/blog/specter2)

---

## 1. Problem Statement

### 1.1 The Core Challenge: Building Autonomous, Self-Improving Research Assistants

**The Vision:** Users should be able to define research outcomes and direction ("Find all papers on Tree-of-Thought reasoning applied to code generation and explain how they compare"), and the system should autonomously execute the research — conducting iterative searches, evaluating evidence, cross-referencing findings, and synthesizing insights — while continuously learning from its own execution trajectories to improve future research quality.

**The Reality:** ARISP currently operates as a **pipeline-driven ingestion system**, not an autonomous research agent. This architectural limitation creates four fundamental gaps:

### 1.2 Limitation 1: Shallow, Non-Iterative Discovery

**Current Behavior:**
```
User Query → API Call → Papers Retrieved → End
```

ARISP executes single-shot API queries against paper databases (ArXiv, Semantic Scholar, OpenAlex). The system never:
- Follows citation chains discovered in papers
- Refines queries based on findings ("this paper mentions X, let me search for X specifically")
- Browses into paper content to verify claims or locate specific evidence
- Conducts comparative analysis across multiple papers

**Industry Context:** Research from 2025 shows that agentic systems using iterative search-and-browse loops achieve 34.0+ point improvements on complex research benchmarks (OpenResearcher, BrowseComp-Plus). Systems like Tongyi DeepResearch, LangChain Open Deep Research, and GPT Researcher demonstrate that multi-turn reasoning with evidence gathering significantly outperforms single-shot retrieval.

**Consequence:** Users receive paper lists, not answers to research questions.

### 1.3 Limitation 2: No Multi-Step Reasoning Capability

**Current Behavior:**
```
Paper A → Extract → Brief A
Paper B → Extract → Brief B
(No cross-paper reasoning, no synthesis across findings)
```

The pipeline processes papers independently. It cannot:
- Perform iterative search-reason-search loops ("Paper A claims X, but lacks evidence on Y — search for papers on Y")
- Build evidence chains across multiple papers
- Resolve contradictions by consulting additional sources
- Answer comparative questions ("How does approach A compare to approach B?")

**Industry Context:** The ReAct framework (Yao et al., 2022) and subsequent agentic AI research show that interleaved reasoning-and-acting patterns are essential for complex tasks. Modern research agents like Queryome deploy parallel subagent teams conducting iterative planner-critic cycles, with systems performing 5+ retrieval iterations to gather sufficient evidence.

**Consequence:** The system cannot answer deep research questions requiring multi-hop reasoning.

### 1.3 Limitation 3: Live API Dependency and Non-Reproducibility

**Current Behavior:**
- Every research run requires live API calls
- Costs scale linearly with research depth (more searches = more API costs)
- Rate limits constrain research speed (ArXiv: 3s delay, Semantic Scholar: quota limits)
- Same query may return different results on different days (non-reproducible)

**Industry Context:** OpenResearcher (2025) demonstrates that decoupling corpus construction from research execution is critical for:
- Cost control: One-time corpus bootstrapping vs. per-search API costs
- Reproducibility: Stable offline corpus enables consistent evaluations
- Speed: Local search (ms latency) vs. API calls (seconds with rate limits)
- Scalability: Offline systems like ResearchArena support 12M+ papers with 50+ episodes/minute throughput

**Consequence:** Research is expensive, slow, rate-limited, and non-reproducible.

### 1.4 Limitation 4: No Trajectory Learning or Self-Improvement

**Current Behavior:**
```
Run 1: Query → Papers → Extract (no learning captured)
Run 2: Query → Papers → Extract (repeats same patterns)
Run 3: Query → Papers → Extract (no improvement)
```

ARISP has no mechanism to:
- Capture successful research trajectories (what searches worked, what evidence was useful, what reasoning chains led to good syntheses)
- Learn from failures (which search strategies led to dead ends, which queries returned irrelevant results)
- Improve future research quality based on past experience

**Industry Context:** Recent research on trajectory-informed learning (2025) shows that LLM-powered agents often repeat inefficient patterns and fail to recover from similar errors. Novel frameworks demonstrate:
- **Trajectory Intelligence Extraction**: Semantic analysis of agent reasoning patterns
- **Decision Attribution Analysis**: Identifying decisions leading to failures or inefficiencies
- **Contextual Learning Generation**: Producing strategy tips from execution patterns
- **Adaptive Memory Retrieval**: Retrieving guidance tailored to specific task contexts

Systems using trajectory-based learning achieve 14.3+ point improvements in scenario goal completion (AppWorld benchmark). ChemCRAFT and other agentic systems use cold-start supervised fine-tuning with synthesized trajectories to establish fundamental behavioral patterns.

**Consequence:** The system cannot get better over time — it's static, not self-improving.

### 1.5 Why This Matters Now

The AI research landscape in 2025-2026 has converged on three key findings:

1. **Agentic AI is the next frontier**: Enterprise spending on generative AI reached $37B in 2025 (3.2x increase from 2024). Gartner projects that 15% of work decisions will be made autonomously by agentic AI by 2028 (up from 0% in 2024).

2. **Offline trajectory synthesis enables cost-effective agent development**: OpenResearcher synthesized 97K trajectories over 15M documents, demonstrating that high-quality agentic behavior can be learned from offline trajectories without expensive live experimentation.

3. **Self-improvement through trajectory learning is achievable**: Multiple 2025 frameworks (ASTRA, SynthAgent, AgentTrek) demonstrate that agents can learn from their own execution trajectories using dual refinement, quality scoring, and iterative feedback loops.

**The Opportunity:** ARISP is well-positioned to evolve from a pipeline system into an autonomous, self-improving research agent that learns from experience and continuously improves research quality.

---

## 2. Proposed Solution

### 2.1 Overview: Deep Research Agent (DRA)

Introduce a new subsystem — **Deep Research Agent (DRA)** — that layers an agentic, trajectory-based research loop on top of ARISP's existing discovery and extraction infrastructure. The system operates in three modes:

1. **Corpus Mode**: Build and maintain an offline indexed corpus from ARISP's paper collection
2. **Agent Mode**: Execute multi-turn research sessions using browser primitives over the offline corpus
3. **Training Mode**: Synthesize trajectories from agent sessions and enable model self-improvement

**Key Innovation:** Unlike OpenResearcher (designed for web-scale 15M documents), DRA is optimized for **domain-specific, curated corpora** (hundreds to thousands of papers), leveraging ARISP's existing high-quality extraction pipeline and registry system.

### 2.2 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Deep Research Agent (DRA)                 │
│                                                             │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐ │
│  │   Corpus      │  │  Agent Loop   │  │   Trajectory     │ │
│  │   Manager     │  │  (ReAct)      │  │   Collector      │ │
│  │              │  │               │  │                  │ │
│  │ • Ingest     │  │ • search()    │  │ • Record turns   │ │
│  │ • Index      │  │ • open()      │  │ • Analyze        │ │
│  │ • Refresh    │  │ • find()      │  │ • Learn patterns │ │
│  └──────┬───────┘  └───────┬───────┘  └────────┬─────────┘ │
│         │                  │                    │           │
│         ▼                  ▼                    ▼           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Offline Search Engine                    │  │
│  │  FAISS Index (dense) + BM25 (sparse) + Metadata      │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         │                  │                    │
         ▼                  ▼                    ▼
┌──────────────┐  ┌─────────────────┐  ┌──────────────────┐
│ ARISP Paper  │  │  LLM Providers  │  │  Trajectory      │
│ Registry +   │  │  (Claude/Gemini) │  │  Learning        │
│ Extractions  │  │                 │  │  System          │
└──────────────┘  └─────────────────┘  └──────────────────┘
```

### 2.3 Core Components

#### 2.3.1 Corpus Manager (`src/services/dra/corpus_manager.py`)

Builds and maintains the offline search environment from ARISP's existing paper collection.

```python
class CorpusManager:
    """Manages the offline document corpus and search indices."""

    async def ingest_from_registry(self, registry: RegistryService) -> CorpusStats:
        """Import all extracted papers from ARISP registry into the corpus."""
        # Reads extracted markdown from ARISP's existing extraction pipeline
        # Segments into searchable chunks (section-level granularity)
        # Stores in document store with full metadata

    async def build_index(self, embedding_model: str = "SPECTER2") -> IndexStats:
        """Build dense (FAISS) and sparse (BM25) indices over corpus."""
        # SPECTER2 embeddings for academic-domain semantic search
        # BM25 index for keyword/exact-match queries
        # Hybrid retrieval with configurable weighting

    async def refresh(self, since: datetime | None = None) -> RefreshResult:
        """Incrementally update corpus with newly ingested papers."""
        # Only re-indexes papers added since last refresh
        # Maintains index consistency with atomic swap
```

**Corpus Segmentation Strategy:**
- **Section-level chunks**: Each paper section (abstract, introduction, methods, results, etc.) becomes a separate searchable document
- **Metadata preservation**: Each chunk retains paper ID, section type, citation context, and position
- **Cross-reference linking**: Citations within chunks are resolved to other corpus entries where available

**Why SPECTER2?**
SPECTER2 (Allen AI) is trained on 6M triplets spanning 23 fields, specifically designed for academic document embeddings using citation-informed training. Unlike general-purpose embeddings (e.g., OpenAI text-embedding), SPECTER2 understands academic relatedness through citation graphs, making it optimal for paper search.

#### 2.3.2 Browser Primitives (`src/services/dra/browser.py`)

Three explicit operations modeled after OpenResearcher's design, adapted for academic papers:

```python
class ResearchBrowser:
    """Browser primitives for structured evidence gathering over the offline corpus."""

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """Hybrid search over corpus. Returns ranked results with title,
        paper ID, section, and snippet."""
        # Combines dense (SPECTER2) + sparse (BM25) retrieval
        # Returns: title, paper_id, section_name, snippet, relevance_score

    async def open(self, paper_id: str, section: str | None = None) -> DocumentContent:
        """Open full content of a paper or specific section."""
        # Returns complete markdown content with preserved structure
        # Optionally scoped to a specific section
        # Tracks which papers/sections have been opened (for trajectory)

    async def find(self, pattern: str, scope: str = "current") -> list[FindResult]:
        """Locate exact or fuzzy matches within the currently opened document."""
        # String matching within open document
        # Returns: matched_text, context (surrounding sentences), position
        # Supports regex patterns for flexible evidence localization
```

**Key Design Decisions:**
- **Hybrid retrieval** (dense + sparse) instead of OpenResearcher's dense-only approach, because academic queries often contain specific technical terms that benefit from exact match
- **Section-level granularity** for `open()` instead of full-document, because research papers are long and section scoping reduces context window pressure
- **Fuzzy find** in addition to exact match, because terminology varies across papers (e.g., "attention mechanism" vs "self-attention" vs "multi-head attention")

**Research Foundation:** BrowserAgent (2025) demonstrates that browser-native actions (search, click, type, scroll) enable agents to solve complex tasks, achieving 50+ episodes/minute throughput. Our simplified academic primitives (search, open, find) are optimized for paper-specific workflows.

#### 2.3.3 Agent Loop (`src/services/dra/agent.py`)

ReAct-style agent that uses browser primitives to conduct multi-turn research:

```python
class DeepResearchAgent:
    """Agentic research loop using browser primitives over offline corpus."""

    def __init__(
        self,
        browser: ResearchBrowser,
        llm_service: LLMService,
        max_turns: int = 50,
        max_context_tokens: int = 128_000,
    ):
        self.browser = browser
        self.llm = llm_service
        self.max_turns = max_turns
        self.trajectory: list[Turn] = []

    async def research(self, question: str) -> ResearchResult:
        """Execute a multi-turn research session.

        The agent follows a ReAct loop:
        1. Reason about what information is needed
        2. Choose a browser action (search/open/find)
        3. Observe the result
        4. Repeat until confident in an answer or budget exhausted
        """
        system_prompt = self._build_system_prompt(question)
        history: list[Turn] = []

        for turn in range(self.max_turns):
            # LLM generates reasoning + tool call
            response = await self.llm.generate(
                system_prompt=system_prompt,
                history=history,
                tools=self.browser.tool_definitions(),
            )

            # Execute tool call against offline corpus
            if response.tool_call:
                observation = await self.browser.execute(response.tool_call)
                history.append(Turn(
                    reasoning=response.reasoning,
                    action=response.tool_call,
                    observation=observation,
                ))
            else:
                # Agent has produced final answer
                return ResearchResult(
                    answer=response.content,
                    trajectory=history,
                    papers_consulted=self.browser.opened_papers,
                    total_turns=turn + 1,
                )

        return ResearchResult(
            answer=None,
            trajectory=history,
            exhausted=True,
            total_turns=self.max_turns,
        )
```

**Research Foundation:** The ReAct framework (Yao et al., 2022) demonstrates that interleaving reasoning traces with actions enables models to induce, track, and update action plans while handling exceptions. The framework achieves superior performance over standard action-only models across question answering, fact verification, and interactive task benchmarks.

#### 2.3.4 Trajectory Collector & Learning System (`src/services/dra/trajectory.py`)

Records, analyzes, and learns from research trajectories:

```python
class TrajectoryCollector:
    """Collect, analyze, and learn from research trajectories."""

    async def record(self, result: ResearchResult) -> TrajectoryRecord:
        """Record a completed research session as a trajectory."""
        # Stores the full (question, reasoning, action, observation)* sequence
        # Annotates with metadata: duration, papers_opened, search_count, etc.

    async def analyze_patterns(
        self,
        trajectories: list[TrajectoryRecord],
    ) -> TrajectoryInsights:
        """Analyze trajectory patterns to identify effective strategies.

        Extracts:
        - Successful search query patterns
        - Effective evidence gathering sequences
        - Common failure modes and recovery strategies
        - Decision points leading to high-quality answers
        """

    async def generate_learning_tips(
        self,
        insights: TrajectoryInsights,
    ) -> list[ContextualTip]:
        """Generate strategy tips from trajectory analysis.

        Produces contextual guidance like:
        - "When searching for comparative analysis, use 'vs' or 'compared to' in queries"
        - "After finding a key paper, check its citations for foundational work"
        - "If abstract mentions a dataset, search for dataset name for implementation details"
        """

    async def filter_quality(
        self,
        trajectories: list[TrajectoryRecord],
        min_turns: int = 3,
        require_answer: bool = True,
        max_context_length: int = 128_000,
    ) -> list[TrajectoryRecord]:
        """Filter trajectories by quality criteria."""

    def export_sft(
        self,
        trajectories: list[TrajectoryRecord],
        format: str = "jsonl",
    ) -> Path:
        """Export trajectories in SFT-ready format."""
```

**Research Foundation:** Trajectory-Informed Memory Generation (2025) shows that analyzing agent execution patterns — not just storing conversational facts — enables agents to improve from experience. The framework's Decision Attribution Analyzer identifies decisions leading to failures/inefficiencies, while Contextual Learning Generators produce strategy tips tailored to task contexts, achieving 14.3 point gains in goal completion.

---

## 3. Alternatives Considered

### Option A: Live Web Search Agent (Rejected)

Run the agent loop using live API calls (ArXiv, Semantic Scholar) instead of an offline corpus.

**Pros:**
- Always up-to-date results
- No corpus maintenance overhead

**Cons:**
- ❌ Expensive: every search path incurs API cost, including dead ends
- ❌ Non-reproducible: same query returns different results over time
- ❌ Rate-limited: ArXiv enforces 3-second delays; Semantic Scholar has quota limits
- ❌ Cannot analyze trajectories against stable ground truth

**Verdict:** Rejected. OpenResearcher specifically demonstrates that offline execution is critical for reproducibility, cost control, and analytical capability. Industry consensus (2025) supports offline corpus construction for agentic research systems.

### Option B: RAG-Only Approach (Rejected)

Use standard Retrieval-Augmented Generation without explicit browser primitives or multi-turn reasoning.

**Pros:**
- Simpler implementation
- Well-understood architecture
- Many existing frameworks (LangChain, LlamaIndex)

**Cons:**
- ❌ Single-shot retrieval misses evidence requiring iterative refinement
- ❌ No evidence localization within documents
- ❌ Cannot capture reasoning trajectories for learning
- ❌ OpenResearcher's ablation (RQ4) shows search+open+find significantly outperforms search-only
- ❌ Cannot build evidence chains across multiple reasoning steps

**Verdict:** Rejected. RAG is a subset of what we need. The browser primitives and multi-turn loop are the key differentiators for deep research. Systems like LAD-RAG (90%+ perfect recall) and agentic memory-augmented retrieval demonstrate that agentic orchestration outperforms static RAG.

### Option C: Full OpenResearcher Fork (Rejected)

Fork the OpenResearcher repository and adapt it directly.

**Pros:**
- Fastest path to a working system
- Leverages tested codebase

**Cons:**
- ❌ OpenResearcher is designed for web-scale (15M documents); ARISP operates on curated domain-specific corpora (hundreds to low thousands of papers)
- ❌ Different embedding strategy needed (SPECTER2 for academic vs. Qwen3-Embedding-8B for web)
- ❌ Tight coupling to OpenResearcher's data formats and pipeline structure
- ❌ Maintenance burden of tracking upstream changes

**Verdict:** Rejected. We adopt the *architecture and principles* but implement natively within ARISP's existing codebase, using our established patterns (Pydantic models, provider abstraction, resilience patterns).

### Option D: Native ARISP Integration (Recommended) ✅

Build the DRA subsystem within ARISP, leveraging existing infrastructure (registry, extraction pipeline, LLM service, resilience patterns) while implementing OpenResearcher's core innovations.

**Pros:**
- ✅ Integrates with existing paper registry and extraction pipeline
- ✅ Reuses LLM service with provider failover and circuit breakers
- ✅ Domain-optimized (SPECTER2 embeddings, academic-aware chunking)
- ✅ Follows established codebase conventions and security patterns
- ✅ Incremental delivery possible (corpus first, then agent, then learning)
- ✅ Optimized for domain-specific corpora (hundreds to thousands of papers)

**Cons:**
- More implementation effort than a fork
- Need to build and validate search infrastructure

---

## 4. Detailed Design

### 4.1 Data Models

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
    context: str = Field(..., description="Surrounding sentences for context")
    position: int = Field(..., ge=0, description="Character offset in document")
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
    reasoning: str = Field(..., description="Agent's chain-of-thought")
    action: ToolCall
    observation: str = Field(..., description="Tool response (truncated if needed)")
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
    context: str = Field(..., description="When to apply this tip")
    strategy: str = Field(..., description="What to do")
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

[... Rest of the sections remain largely the same, but with updated references and context ...]

### 4.2 Corpus Construction Pipeline

```
ARISP Registry                    Offline Corpus
┌──────────────┐                 ┌──────────────────────────┐
│ Paper 1      │──── Extract ───▶│ Chunk: Paper1/Abstract   │
│  - metadata  │     & Chunk     │ Chunk: Paper1/Methods    │
│  - markdown  │                 │ Chunk: Paper1/Results    │
│              │                 │ ...                      │
├──────────────┤                 ├──────────────────────────┤
│ Paper 2      │──── Extract ───▶│ Chunk: Paper2/Abstract   │
│  - metadata  │     & Chunk     │ Chunk: Paper2/Intro      │
│              │                 │ ...                      │
├──────────────┤                 ├──────────────────────────┤
│ ...          │                 │ ...                      │
└──────────────┘                 └──────────┬───────────────┘
                                            │
                                 ┌──────────▼───────────────┐
                                 │     Index Layer           │
                                 │                          │
                                 │  FAISS (SPECTER2 dense)  │
                                 │  + BM25 (sparse/keyword) │
                                 │  + Metadata store        │
                                 └──────────────────────────┘
```

**Chunking Strategy:**
1. Parse extracted markdown into sections using heading structure
2. Split oversized sections at paragraph boundaries (max 512 tokens per chunk)
3. Preserve cross-references as metadata links
4. Generate SPECTER2 embeddings per chunk (title + content concatenated)

**Index Configuration:**
```yaml
dra_settings:
  corpus:
    chunk_max_tokens: 512
    chunk_overlap_tokens: 64
    embedding_model: "allenai/specter2"
    embedding_batch_size: 32

  search:
    dense_weight: 0.7        # SPECTER2 cosine similarity
    sparse_weight: 0.3       # BM25 score
    default_top_k: 10
    max_top_k: 50

  agent:
    max_turns: 50
    max_context_tokens: 128000
    llm_provider: "claude"    # Primary provider for reasoning
    llm_model: "claude-sonnet-4-20250514"

  trajectory_learning:
    enable_learning: true
    min_trajectories_for_analysis: 10
    learning_refresh_interval_hours: 24
    quality_threshold: 0.6
```

### 4.3 Hybrid Retrieval

The search primitive uses Reciprocal Rank Fusion (RRF) to combine dense and sparse results:

```python
def reciprocal_rank_fusion(
    dense_results: list[SearchResult],
    sparse_results: list[SearchResult],
    k: int = 60,
    dense_weight: float = 0.7,
    sparse_weight: float = 0.3,
) -> list[SearchResult]:
    """Combine dense and sparse retrieval results using weighted RRF.

    RRF score = Σ (weight / (k + rank_i)) for each ranking list
    """
    scores: dict[str, float] = {}

    for rank, result in enumerate(dense_results):
        scores[result.chunk_id] = scores.get(result.chunk_id, 0.0)
        scores[result.chunk_id] += dense_weight / (k + rank + 1)

    for rank, result in enumerate(sparse_results):
        scores[result.chunk_id] = scores.get(result.chunk_id, 0.0)
        scores[result.chunk_id] += sparse_weight / (k + rank + 1)

    # Sort by fused score, return top results
    ...
```

### 4.4 Agent System Prompt

The agent receives a structured system prompt that defines its research methodology:

```
You are a research agent with access to an offline corpus of academic papers.
Your task is to answer research questions by systematically searching, reading,
and analyzing papers in the corpus.

## Available Tools

1. **search(query)** — Search the corpus. Returns top results with title,
   paper ID, section, and snippet. Use varied queries to explore different angles.

2. **open(paper_id, section?)** — Open a paper or specific section to read
   the full content. Use after search identifies promising papers.

3. **find(pattern)** — Find exact or fuzzy matches in the currently open document.
   Use to locate specific claims, numbers, methods, or citations.

## Research Protocol

1. Start broad: search for the main topic to understand the landscape
2. Open promising papers and read key sections (abstract, methods, results)
3. Use find() to locate specific evidence (numbers, claims, comparisons)
4. Refine your search based on what you've learned
5. Cross-reference findings across multiple papers
6. When confident, synthesize your answer with citations

## Learned Strategies

{contextual_tips_from_trajectory_learning}

## Important

- Cite specific papers and sections when making claims
- If evidence is contradictory, acknowledge it
- If the corpus doesn't contain sufficient evidence, say so
- Prefer depth (thorough reading of key papers) over breadth (skimming many)
```

**Note:** The `{contextual_tips_from_trajectory_learning}` section is dynamically populated with learned strategies from the Trajectory Learning System, enabling self-improvement over time.

---

## 5. Security Requirements (MANDATORY) 🔒

[Security requirements remain unchanged from original proposal]

---

## 6. Test Requirements

[Test requirements remain unchanged from original proposal]

---

## 7. Implementation Plan

### Phase 8.1: Corpus Infrastructure (Week 1-2)

**Goal:** Build the offline corpus from ARISP's existing paper collection.

**Deliverables:**
- [ ] `CorpusChunk` and related Pydantic models
- [ ] `CorpusManager` with ingest, chunk, and refresh operations
- [ ] Section-aware markdown parser for academic papers
- [ ] SPECTER2 embedding integration
- [ ] FAISS index builder with atomic swap
- [ ] BM25 index using `rank_bm25` library
- [ ] Hybrid retrieval with RRF
- [ ] Configuration in `research_config.yaml`
- [ ] Unit tests with >90% coverage

**Dependencies:**
- ARISP Registry (Phase 3.5) — for paper inventory
- ARISP Extraction (Phase 2/2.5) — for markdown content
- `faiss-cpu` or `faiss-gpu` package
- `rank_bm25` package
- `transformers` + `allenai/specter2` model

### Phase 8.2: Browser Primitives & Agent Loop (Week 2-3)

**Goal:** Implement the search/open/find primitives and ReAct agent loop.

**Deliverables:**
- [ ] `ResearchBrowser` with search, open, find operations
- [ ] `DeepResearchAgent` with ReAct loop
- [ ] System prompt and tool definitions
- [ ] Resource limits and timeout handling
- [ ] Output sanitization
- [ ] CLI command: `arisp research "question"` for interactive research
- [ ] Unit tests with >90% coverage

**Dependencies:**
- Phase 8.1 (corpus infrastructure)
- ARISP LLM Service (Phase 5.1) — for agent reasoning

### Phase 8.3: Trajectory Collection & Learning (Week 3-4)

**Goal:** Record research sessions, analyze patterns, and enable self-improvement.

**Deliverables:**
- [ ] `TrajectoryCollector` with recording and analysis
- [ ] Pattern extraction from trajectory history
- [ ] Contextual learning tip generation
- [ ] Adaptive memory retrieval for strategy tips
- [ ] Quality scoring for trajectories
- [ ] JSONL export in ShareGPT-compatible format
- [ ] CLI command: `arisp trajectories export --format jsonl`
- [ ] CLI command: `arisp trajectories analyze`
- [ ] Trajectory analysis utilities (stats, visualization)
- [ ] Unit tests with >90% coverage

**Dependencies:**
- Phase 8.2 (agent loop)

### Phase 8.4: Batch Synthesis & Advanced Learning (Week 4-5)

**Goal:** Synthesize trajectories at scale and prepare for optional model fine-tuning.

**Deliverables:**
- [ ] Batch trajectory synthesis over question sets
- [ ] Quality filtering and deduplication
- [ ] Decision attribution analysis (identify failure/success patterns)
- [ ] SFT data preparation scripts (optional, for future model training)
- [ ] Documentation for fine-tuning workflow (optional)
- [ ] Integration tests for full pipeline

**Dependencies:**
- Phase 8.3 (trajectory learning)

---

## 8. Dependency Analysis

### New Dependencies

| Package | Version | Purpose | License | Size |
|---------|---------|---------|---------|------|
| `faiss-cpu` | ≥1.8.0 | Dense vector indexing | MIT | ~30MB |
| `rank-bm25` | ≥0.2.2 | Sparse retrieval (BM25) | Apache 2.0 | <1MB |
| `transformers` | ≥4.40.0 | SPECTER2 model loading | Apache 2.0 | Already in deps |
| `torch` | ≥2.2.0 | Embedding computation | BSD | Already in deps (optional) |

### Existing ARISP Dependencies Reused
- `pydantic` — Data models (consistent with all existing phases)
- LLM service — Agent reasoning (Phase 5.1 provider abstraction)
- Registry service — Paper inventory (Phase 3.5)
- Extraction pipeline — Paper markdown content (Phase 2/2.5)
- Resilience patterns — Circuit breakers, retries (Phase 3.3)
- Rate limiter — Embedding API throttling (Phase 1.5)

---

## 9. Cost Analysis

### Corpus Construction (One-Time)

| Operation | Cost | Notes |
|-----------|------|-------|
| SPECTER2 embeddings (1000 papers × 10 chunks) | $0 | Local model inference |
| FAISS index build | $0 | CPU computation |
| Storage (embeddings + index) | ~50MB per 1000 papers | Local disk |

### Per Research Session

| Operation | Cost | Notes |
|-----------|------|-------|
| LLM reasoning (50 turns × ~2K tokens) | ~$0.30-0.50 | Claude Sonnet pricing |
| Corpus search | $0 | Local computation |
| Trajectory analysis | $0 | Local computation |
| Total per session | ~$0.30-0.50 | |

### Batch Trajectory Synthesis (1000 sessions)

| Operation | Cost | Notes |
|-----------|------|-------|
| LLM reasoning | ~$300-500 | Primary cost driver |
| Filtering & export | $0 | Local computation |
| Trajectory learning analysis | $0 | Local computation |

**Comparison with live-API approach:** Each live search session would cost ~$0.01-0.05 in API fees per search call × 20-50 searches = $0.20-2.50 *in addition to* LLM costs, plus rate limiting would extend wall-clock time 10-50×.

---

## 10. Backward Compatibility

### No Breaking Changes

The DRA subsystem is entirely additive:
- New package: `src/services/dra/`
- New CLI commands: `arisp research`, `arisp corpus`, `arisp trajectories`
- New configuration section: `dra_settings` in `research_config.yaml`
- No changes to existing modules, APIs, or data formats

### Configuration Compatibility

```yaml
# Existing config (unchanged)
research_topics:
  - query: "attention mechanisms"
    provider: "arxiv"
    # ... existing fields

# New config section (optional, DRA only)
dra_settings:
  corpus:
    embedding_model: "allenai/specter2"
    chunk_max_tokens: 512
  search:
    dense_weight: 0.7
    sparse_weight: 0.3
  agent:
    max_turns: 50
    llm_model: "claude-sonnet-4-20250514"
  trajectory_learning:
    enable_learning: true
    min_trajectories_for_analysis: 10
```

---

## 11. Success Metrics

### Phase 8.1 (Corpus)
- [ ] 95%+ of registry papers successfully ingested and indexed
- [ ] Search latency < 200ms for 10K-chunk corpus
- [ ] Hybrid retrieval outperforms dense-only on manual spot checks

### Phase 8.2 (Agent)
- [ ] Agent produces cited answers for 70%+ of test questions
- [ ] Average session completes in < 50 turns
- [ ] All resource limits enforced (verified by tests)

### Phase 8.3 (Trajectory Learning)
- [ ] 80%+ of trajectories pass quality filters
- [ ] Trajectory analysis produces actionable insights (5+ contextual tips)
- [ ] Agent performance improves measurably after learning cycle (10+ trajectories)

### Phase 8.4 (Advanced Learning)
- [ ] 1000+ quality trajectories generated in batch
- [ ] Decision attribution identifies top 5 failure/success patterns
- [ ] (Optional) Fine-tuned model shows improvement over base on domain questions

---

## 12. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SPECTER2 embeddings too slow for large corpora | Medium | Medium | Batch embedding with progress tracking; GPU acceleration optional |
| Agent reasoning quality insufficient | Medium | High | Start with Claude Sonnet (strong reasoning); can upgrade to Opus |
| Corpus too small for meaningful retrieval | Low | High | Supplement with OpenResearcher's public FineWeb subset as distractor corpus |
| FAISS index memory usage | Low | Medium | Use IVF index for corpora > 100K chunks; mmap for disk-backed index |
| Context window exhaustion on long sessions | Medium | Medium | Configurable observation truncation; progressive summarization of history |
| Learning system produces low-quality tips | Medium | Medium | Quality filtering on trajectory insights; manual review of top tips; confidence scoring |
| Trajectories don't lead to measurable improvement | Medium | High | Start with clear baselines; A/B test with/without learning tips; iterate on pattern extraction |

---

## 13. Relationship to Phase 7 Research

This proposal builds on the extensive research conducted in Phase 7 Discovery Research:

| Phase 7 Research Finding | Application in This Proposal |
|--------------------------|------------------------------|
| SPECTER2 for paper embeddings (§3.1) | Dense retrieval in hybrid search |
| FAISS for vector search (§5.1) | Corpus index backend |
| Redis for embedding cache (§5.2) | Future optimization (Phase 8.4+) |
| Contextual bandits for personalization (§4.3) | Future: personalized search ranking based on trajectory feedback |
| ColBERT for re-ranking (§6.2) | Future: fine-grained re-ranking after initial retrieval |
| arxiv-sanity-lite architecture (§9.1) | Influenced corpus construction and tagging approach |

---

## 14. Future Directions

### Phase 8.5+: Advanced Capabilities (Future)

**Multi-Agent Collaboration:**
- Parallel subagent teams (inspired by Queryome's 10-agent architecture)
- Specialized agents for different research aspects (citation analysis, methodology comparison, trend detection)

**Preference Learning & RLHF:**
- Collect user feedback on research quality (thumbs up/down on answers)
- Train reward model to represent user preferences
- Use RLHF to fine-tune agent policy based on learned preferences

**Cross-Corpus Federation:**
- Federated search across multiple domain-specific corpora
- Inter-corpus citation resolution
- Unified trajectory learning across research domains

**Interactive Research Sessions:**
- User-in-the-loop refinement (user can guide agent mid-session)
- Clarification questions from agent to user
- Collaborative evidence gathering

---

## 15. Recommendation

**✅ RECOMMEND APPROVAL — Implement DRA Subsystem in Phases 8.1–8.4**

### Justification

1. **Addresses Core Limitation:** ARISP currently cannot perform iterative, multi-step research — only pipeline-style ingestion. DRA adds the agentic capability that makes the system genuinely useful for deep research questions, addressing the fundamental problem of building autonomous, self-improving research assistants.

2. **Proven Architecture:** OpenResearcher demonstrates +34.0 point improvement from offline trajectory synthesis on BrowseComp-Plus. The architecture is validated at scale (97K trajectories, 15M documents). Multiple 2025 systems (Tongyi DeepResearch, LangChain Open Deep Research, GPT Researcher) confirm the agentic research paradigm.

3. **Self-Improvement Path:** Trajectory-informed learning frameworks (2025) demonstrate 14.3+ point gains through pattern analysis and contextual strategy generation. DRA's learning system positions ARISP to continuously improve research quality over time.

4. **Leverages Existing Infrastructure:** DRA reuses ARISP's registry, extraction pipeline, LLM service, and resilience patterns — minimizing new code and risk.

5. **Incremental Delivery:** Each phase is independently valuable. Phase 8.1 (corpus) enables better search even without the agent. Phase 8.2 (agent) enables interactive research. Phase 8.3-8.4 (trajectory learning) enable self-improvement.

6. **Research-Validated Design:** Every major component (ReAct loops, browser primitives, hybrid retrieval, trajectory synthesis, SPECTER2 embeddings) is backed by peer-reviewed research from leading institutions (Allen AI, Tsinghua, Peking U, UCLA, Stanford).

7. **Industry Momentum:** With enterprise AI spending at $37B (2025) and Gartner predicting 15% of decisions made autonomously by 2028, autonomous research agents represent a strategic capability for modern research teams.

### Implementation Priority
🟡 **HIGH** — Start after Phase 6 integration is complete.

---

*End of Proposal*

"""Phase 8: Deep Research Agent (DRA) data models.

This module contains Pydantic models for:
- Corpus chunks and search results
- Browser primitives (search, open, find)
- Agent turns and tool calls
- Research results and trajectories
- Learning insights and contextual tips
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class ChunkType(str, Enum):
    """Section types for corpus chunks."""

    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    METHODS = "methods"
    RESULTS = "results"
    DISCUSSION = "discussion"
    CONCLUSION = "conclusion"
    REFERENCES = "references"
    OTHER = "other"


class CorpusChunk(BaseModel):
    """A searchable unit within the corpus.

    Attributes:
        chunk_id: Unique chunk identifier
        paper_id: Registry paper ID this chunk belongs to
        section_type: Type of section (abstract, methods, etc.)
        title: Paper title
        content: Chunk text content
        token_count: Number of tokens in content
        embedding: Dense embedding vector (optional, computed on indexing)
        metadata: Additional metadata (DOI, ArXiv ID, etc.)
    """

    chunk_id: str = Field(..., max_length=256, description="Unique chunk identifier")
    paper_id: str = Field(..., max_length=256, description="Registry paper ID")
    section_type: ChunkType = Field(default=ChunkType.OTHER, description="Section type")
    title: str = Field(..., max_length=500, description="Paper title")
    content: str = Field(
        ..., min_length=1, max_length=50000, description="Chunk text content"
    )
    token_count: int = Field(..., ge=0, description="Token count")
    embedding: Optional[list[float]] = Field(
        default=None, description="Dense embedding vector"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )
    checksum: Optional[str] = Field(
        default=None, max_length=64, description="SHA-256 checksum for integrity"
    )


class SearchResult(BaseModel):
    """Result from a corpus search.

    Attributes:
        chunk_id: ID of the matched chunk
        paper_id: Registry paper ID
        paper_title: Title of the paper
        section_type: Type of section matched
        snippet: Text snippet (max 1000 chars)
        relevance_score: Relevance score (0.0-1.0)
    """

    chunk_id: str = Field(..., max_length=256, description="Chunk ID")
    paper_id: str = Field(..., max_length=256, description="Paper ID")
    paper_title: str = Field(..., max_length=500, description="Paper title")
    section_type: ChunkType = Field(..., description="Section type")
    snippet: str = Field(..., max_length=1000, description="Text snippet")
    relevance_score: float = Field(..., ge=0.0, le=1.0, description="Relevance score")

    @field_validator("relevance_score")
    @classmethod
    def validate_score(cls, v: float) -> float:
        """Ensure score is within valid range."""
        return round(v, 4)


class FindResult(BaseModel):
    """Result from a find operation within an open document.

    Attributes:
        matched_text: The text that matched the pattern
        context: Surrounding sentences for context
        position: Character position in the document
        section: Section where match was found (if known)
    """

    matched_text: str = Field(..., max_length=2000, description="Matched text")
    context: str = Field(..., max_length=5000, description="Surrounding sentences")
    position: int = Field(..., ge=0, description="Character position")
    section: Optional[ChunkType] = Field(default=None, description="Section type")


class ToolCallType(str, Enum):
    """Types of browser tool calls."""

    SEARCH = "search"
    OPEN = "open"
    FIND = "find"
    ANSWER = "answer"


class ToolCall(BaseModel):
    """A single tool invocation by the agent.

    Attributes:
        tool: Type of tool called
        arguments: Tool arguments as dict
        timestamp: When the call was made
    """

    tool: ToolCallType = Field(..., description="Tool type")
    arguments: dict[str, Any] = Field(..., description="Tool arguments")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Call timestamp"
    )


class Turn(BaseModel):
    """A single reasoning-action-observation turn in the agent loop.

    Attributes:
        turn_number: Sequential turn number (1-indexed)
        reasoning: Agent's chain-of-thought reasoning
        action: Tool call made
        observation: Tool response (may be truncated)
        observation_tokens: Token count of observation
    """

    turn_number: int = Field(..., ge=1, description="Turn number")
    reasoning: str = Field(
        ..., max_length=10000, description="Chain-of-thought reasoning"
    )
    action: ToolCall = Field(..., description="Tool call")
    observation: str = Field(..., max_length=50000, description="Tool response")
    observation_tokens: int = Field(..., ge=0, description="Observation tokens")


class ResearchResult(BaseModel):
    """Complete result of a research session.

    Attributes:
        question: The research question asked
        answer: Final answer (None if not produced)
        trajectory: List of turns in the session
        papers_consulted: List of paper IDs opened
        total_turns: Total number of turns taken
        exhausted: Whether resource limits were hit
        total_tokens: Total tokens used in session
        duration_seconds: Session duration
    """

    question: str = Field(..., max_length=2000, description="Research question")
    answer: Optional[str] = Field(
        default=None, max_length=50000, description="Final answer"
    )
    trajectory: list[Turn] = Field(
        default_factory=list, description="Session trajectory"
    )
    papers_consulted: list[str] = Field(
        default_factory=list, description="Papers opened"
    )
    total_turns: int = Field(..., ge=0, description="Total turns")
    exhausted: bool = Field(default=False, description="Resource limits exhausted")
    total_tokens: int = Field(0, ge=0, description="Total tokens used")
    duration_seconds: float = Field(0.0, ge=0.0, description="Session duration")


class TrajectoryInsights(BaseModel):
    """Insights extracted from trajectory analysis.

    Attributes:
        effective_query_patterns: Patterns that lead to good results
        successful_sequences: Action sequences that succeed
        failure_modes: Common failure patterns and counts
        average_turns_to_success: Mean turns for successful sessions
        paper_consultation_patterns: Which sections are most useful
    """

    effective_query_patterns: list[str] = Field(
        default_factory=list, description="Effective query patterns"
    )
    successful_sequences: list[str] = Field(
        default_factory=list, description="Successful action sequences"
    )
    failure_modes: dict[str, int] = Field(
        default_factory=dict, description="Failure mode counts"
    )
    average_turns_to_success: float = Field(
        0.0, ge=0.0, description="Average turns to success"
    )
    paper_consultation_patterns: dict[str, int] = Field(
        default_factory=dict, description="Section consultation counts"
    )


class ContextualTip(BaseModel):
    """Contextual strategy tip learned from trajectories.

    Attributes:
        context: When this tip applies
        strategy: What to do
        confidence: Confidence score (0.0-1.0)
        examples: Trajectory IDs demonstrating success
    """

    context: str = Field(..., max_length=2000, description="When tip applies")
    strategy: str = Field(..., max_length=5000, description="Strategy to use")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    examples: list[str] = Field(
        default_factory=list, description="Example trajectory IDs"
    )

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Round confidence to 4 decimal places."""
        return round(v, 4)


class TrajectoryRecord(BaseModel):
    """A recorded trajectory with quality metadata and learning insights.

    Attributes:
        trajectory_id: Unique trajectory identifier
        question: Research question
        answer: Final answer (if produced)
        turns: List of turns
        quality_score: Quality score (0.0-1.0)
        papers_opened: Number of papers opened
        unique_searches: Number of unique search queries
        find_operations: Number of find operations
        context_length_tokens: Total context length
        insights: Extracted insights (optional)
        created_at: When trajectory was recorded
    """

    trajectory_id: str = Field(..., max_length=256, description="Trajectory ID")
    question: str = Field(..., max_length=2000, description="Research question")
    answer: Optional[str] = Field(
        default=None, max_length=50000, description="Final answer"
    )
    turns: list[Turn] = Field(default_factory=list, description="Turns")
    quality_score: float = Field(0.0, ge=0.0, le=1.0, description="Quality score")
    papers_opened: int = Field(0, ge=0, description="Papers opened")
    unique_searches: int = Field(0, ge=0, description="Unique searches")
    find_operations: int = Field(0, ge=0, description="Find operations")
    context_length_tokens: int = Field(0, ge=0, description="Context tokens")
    insights: Optional[TrajectoryInsights] = Field(
        default=None, description="Extracted insights"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Creation timestamp"
    )

    @field_validator("quality_score")
    @classmethod
    def validate_quality(cls, v: float) -> float:
        """Round quality score to 4 decimal places."""
        return round(v, 4)


class AgentLimits(BaseModel):
    """Resource limits for agent sessions (SR-8.4).

    Attributes:
        max_turns: Maximum turns per session
        max_context_tokens: Maximum context window tokens
        max_session_duration_seconds: Maximum session duration
        max_open_documents: Maximum simultaneously open documents
    """

    max_turns: int = Field(50, ge=1, le=200, description="Maximum turns")
    max_context_tokens: int = Field(
        128_000, ge=1000, le=1_000_000, description="Maximum context tokens"
    )
    max_session_duration_seconds: int = Field(
        600, ge=60, le=3600, description="Maximum session duration"
    )
    max_open_documents: int = Field(
        20, ge=1, le=100, description="Maximum open documents"
    )


class CorpusConfig(BaseModel):
    """Configuration for corpus management.

    Attributes:
        embedding_model: HuggingFace model name for embeddings
        embedding_model_path: Optional local path for offline model
        chunk_max_tokens: Maximum tokens per chunk
        chunk_overlap_tokens: Overlap between consecutive chunks
        embedding_batch_size: Batch size for embedding generation
        corpus_dir: Directory to store corpus data
    """

    embedding_model: str = Field(
        "allenai/specter2", max_length=256, description="Embedding model name"
    )
    embedding_model_path: Optional[str] = Field(
        default=None, max_length=1024, description="Local model path for offline use"
    )
    chunk_max_tokens: int = Field(
        512, ge=64, le=2048, description="Max tokens per chunk"
    )
    chunk_overlap_tokens: int = Field(
        64, ge=0, le=256, description="Overlap tokens between chunks"
    )
    embedding_batch_size: int = Field(
        32, ge=1, le=256, description="Embedding batch size"
    )
    corpus_dir: str = Field(
        "./data/dra/corpus", max_length=1024, description="Corpus storage directory"
    )


class SearchConfig(BaseModel):
    """Configuration for hybrid search.

    Attributes:
        dense_weight: Weight for dense (semantic) retrieval
        sparse_weight: Weight for sparse (BM25) retrieval
        default_top_k: Default number of results to return
        max_top_k: Maximum allowed top_k value
    """

    dense_weight: float = Field(
        0.7, ge=0.0, le=1.0, description="Dense retrieval weight"
    )
    sparse_weight: float = Field(
        0.3, ge=0.0, le=1.0, description="Sparse retrieval weight"
    )
    default_top_k: int = Field(10, ge=1, le=100, description="Default results count")
    max_top_k: int = Field(50, ge=1, le=500, description="Maximum results count")

    @field_validator("sparse_weight")
    @classmethod
    def validate_weights_sum(cls, v: float, info) -> float:
        """Validate that weights sum to approximately 1.0."""
        dense = info.data.get("dense_weight", 0.7)
        total = dense + v
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"Search weights must sum to 1.0, got {total}")
        return v


class DRASettings(BaseModel):
    """Complete DRA settings configuration.

    Attributes:
        corpus: Corpus configuration
        search: Search configuration
        agent: Agent resource limits
    """

    corpus: CorpusConfig = Field(
        default_factory=CorpusConfig, description="Corpus settings"
    )
    search: SearchConfig = Field(
        default_factory=SearchConfig, description="Search settings"
    )
    agent: AgentLimits = Field(default_factory=AgentLimits, description="Agent limits")

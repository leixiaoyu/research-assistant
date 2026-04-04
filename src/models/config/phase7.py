"""Phase 7.2 configuration models: discovery expansion.

This module contains configuration for Phase 7.2 discovery expansion:
- Query expansion settings
- Citation exploration configuration
- Multi-source aggregation settings
- Ranking weights
"""

from pydantic import BaseModel, Field, field_validator


class RankingWeights(BaseModel):
    """Weights for multi-source paper ranking (Phase 7.2).

    All weights should sum to 1.0 for normalized scoring.

    Attributes:
        citation_count: Weight for citation-based scoring (log-scaled)
        recency: Weight for publication date recency
        source_count: Weight for number of sources finding the paper
        pdf_availability: Weight for PDF availability
    """

    citation_count: float = Field(
        0.3, ge=0.0, le=1.0, description="Weight for citation count"
    )
    recency: float = Field(0.3, ge=0.0, le=1.0, description="Weight for recency")
    source_count: float = Field(
        0.2, ge=0.0, le=1.0, description="Weight for source count"
    )
    pdf_availability: float = Field(
        0.2, ge=0.0, le=1.0, description="Weight for PDF availability"
    )

    @field_validator("pdf_availability")
    @classmethod
    def validate_weights_sum(cls, v: float, info) -> float:
        """Validate that weights sum to approximately 1.0."""
        values = info.data
        total = (
            values.get("citation_count", 0.3)
            + values.get("recency", 0.3)
            + values.get("source_count", 0.2)
            + v
        )
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"Ranking weights must sum to 1.0, got {total}")
        return v


class CitationExplorationConfig(BaseModel):
    """Configuration for citation network exploration (Phase 7.2).

    Controls forward and backward citation discovery for seed papers.

    Attributes:
        enabled: Enable citation exploration
        forward: Enable forward citation discovery (papers citing this one)
        backward: Enable backward citation discovery (papers this one cites)
        max_forward_per_paper: Max forward citations per seed paper
        max_backward_per_paper: Max backward citations per seed paper
        max_citation_depth: Maximum depth for citation traversal
        respect_registry: Skip papers already in registry
    """

    enabled: bool = Field(True, description="Enable citation exploration")
    forward: bool = Field(True, description="Enable forward citations")
    backward: bool = Field(True, description="Enable backward citations")
    max_forward_per_paper: int = Field(
        10, ge=1, le=100, description="Max forward citations per paper"
    )
    max_backward_per_paper: int = Field(
        10, ge=1, le=100, description="Max backward citations per paper"
    )
    max_citation_depth: int = Field(
        1, ge=1, le=3, description="Max citation traversal depth"
    )
    respect_registry: bool = Field(True, description="Skip papers already in registry")


class QueryExpansionConfig(BaseModel):
    """Configuration for LLM-based query expansion (Phase 7.2).

    Uses LLM to generate semantically related queries for broader coverage.

    Attributes:
        enabled: Enable query expansion
        max_variants: Maximum number of query variants to generate
        cache_expansions: Cache expanded queries
        llm_model: LLM model to use for expansion
    """

    enabled: bool = Field(True, description="Enable query expansion")
    max_variants: int = Field(
        5, ge=1, le=10, description="Max query variants to generate"
    )
    cache_expansions: bool = Field(True, description="Cache expanded queries")
    llm_model: str = Field("gemini-1.5-flash", description="LLM model for expansion")


class RelevanceFilterConfig(BaseModel):
    """Configuration for embedding-based relevance filtering (Phase 7 Fix I2).

    Filters papers based on semantic similarity to the query using embeddings.

    Attributes:
        enabled: Enable relevance filtering
        threshold: Minimum similarity score to keep paper (0.0-1.0)
        embedding_model: Model to use for embeddings
        batch_size: Batch size for embedding generation
    """

    enabled: bool = Field(True, description="Enable relevance filtering")
    threshold: float = Field(
        0.3, ge=0.0, le=1.0, description="Minimum similarity threshold"
    )
    embedding_model: str = Field(
        "specter2", description="Embedding model (specter2 or tfidf)"
    )
    batch_size: int = Field(
        32, ge=1, le=128, description="Batch size for embedding generation"
    )


class AggregationConfig(BaseModel):
    """Configuration for multi-source result aggregation (Phase 7.2).

    Controls deduplication and ranking of papers from multiple sources.

    Attributes:
        max_papers_per_topic: Maximum papers to return per topic
        ranking_weights: Weights for ranking algorithm
        relevance_filter: Relevance filtering configuration (Phase 7 Fix I2)
    """

    max_papers_per_topic: int = Field(
        50, ge=1, le=500, description="Max papers per topic"
    )
    ranking_weights: RankingWeights = Field(
        default_factory=lambda: RankingWeights(),
        description="Ranking algorithm weights",
    )
    relevance_filter: RelevanceFilterConfig = Field(
        default_factory=lambda: RelevanceFilterConfig(),
        description="Relevance filtering configuration",
    )

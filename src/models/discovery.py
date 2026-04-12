"""Discovery data models for Phase 6 & 7.1: Enhanced Discovery Pipeline.

This module defines data structures for:
- Query decomposition (sub-queries with focus areas)
- Quality scoring weights
- Scored papers with quality and relevance metrics
- Discovery pipeline metrics and results
- Phase 7.1: Discovery statistics, filtering results, and timeframe resolution

Usage:
    from src.models.discovery import (
        DecomposedQuery,
        QueryFocus,
        QualityWeights,
        ScoredPaper,
        DiscoveryMetrics,
        DiscoveryResult,
        DiscoveryStats,
        FilteredPaper,
        DiscoveryFilterResult,
        ResolvedTimeframe,
    )
"""

from enum import Enum
from typing import List, Optional, Dict, TYPE_CHECKING
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, computed_field, model_validator

import structlog

if TYPE_CHECKING:
    from src.models.paper import PaperMetadata

logger = structlog.get_logger()


class QueryFocus(str, Enum):
    """Focus area for decomposed queries.

    Categorizes sub-queries by their research perspective:
    - METHODOLOGY: Focus on techniques, algorithms, approaches
    - APPLICATION: Focus on use cases, domains, implementations
    - COMPARISON: Focus on comparisons, benchmarks, evaluations
    - RELATED: Focus on related concepts, synonyms, variations
    - INTERSECTION: Focus on cross-disciplinary aspects
    """

    METHODOLOGY = "methodology"
    APPLICATION = "application"
    COMPARISON = "comparison"
    RELATED = "related"
    INTERSECTION = "intersection"


class ProviderCategory(str, Enum):
    """Provider category for query routing.

    Determines how queries are sent to different providers:
    - COMPREHENSIVE: Search-based APIs that benefit from focused queries
    - TRENDING: Curated/sampling feeds that need local semantic filtering
    """

    COMPREHENSIVE = "comprehensive"  # ArXiv, Semantic Scholar, OpenAlex
    TRENDING = "trending"  # HuggingFace


class DiscoveryMode(str, Enum):
    """Discovery operation mode determining speed vs comprehensiveness tradeoff.

    - SURFACE: Fast discovery (<5s), single provider, no query enhancement
    - STANDARD: Balanced (<30s), query decomposition, all providers, quality filter
    - DEEP: Comprehensive (<120s), hybrid enhancement, citations, relevance ranking
    """

    SURFACE = "surface"
    STANDARD = "standard"
    DEEP = "deep"


class QueryEnhancementConfig(BaseModel):
    """Configuration for query enhancement strategies."""

    model_config = ConfigDict(frozen=True)

    strategy: str = Field(
        "decompose", description="Enhancement strategy: decompose, expand, hybrid"
    )
    max_queries: int = Field(
        5, ge=1, le=20, description="Maximum sub-queries to generate"
    )
    include_original: bool = Field(
        True, description="Include original query in results"
    )
    cache_enabled: bool = Field(True, description="Enable query cache")


class CitationExplorationConfig(BaseModel):
    """Configuration for citation exploration in DEEP mode."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(True, description="Enable citation exploration")
    forward_citations: bool = Field(
        True, description="Explore papers citing discovered papers"
    )
    backward_citations: bool = Field(
        True, description="Explore papers cited by discovered papers"
    )
    max_depth: int = Field(1, ge=1, le=3, description="Citation exploration depth")
    max_papers_per_direction: int = Field(
        10, ge=1, le=50, description="Max papers per direction"
    )


class DecomposedQuery(BaseModel):
    """A focused sub-query generated from the original research query.

    Used by QueryDecomposer to break broad queries into targeted searches.

    Attributes:
        query: The decomposed query text for API search
        focus: The focus area this query targets
        weight: Weight for result merging (default: 1.0)
    """

    model_config = ConfigDict(frozen=True)

    query: str = Field(..., min_length=1, max_length=500, description="Query text")
    focus: QueryFocus = Field(..., description="Focus area of this query")
    weight: float = Field(1.0, ge=0.0, le=2.0, description="Weight for result merging")


class QualityTierConfig(BaseModel):
    """Configuration for quality tier thresholds.

    Attributes:
        excellent: Minimum score for excellent tier (default: 0.80)
        good: Minimum score for good tier (default: 0.60)
        fair: Minimum score for fair tier (default: 0.40)
        # Papers below fair threshold are "low" tier
    """

    model_config = ConfigDict(frozen=True)

    excellent: float = Field(0.80, ge=0.0, le=1.0)
    good: float = Field(0.60, ge=0.0, le=1.0)
    fair: float = Field(0.40, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_tier_order(self) -> "QualityTierConfig":
        """Validate tiers are in descending order."""
        if not (self.excellent > self.good > self.fair):
            raise ValueError(
                "Tier thresholds must be in order: excellent > good > fair"
            )
        return self


class QualityWeights(BaseModel):
    """Weights for quality signal combination in QualityFilterService.

    All weights should sum to approximately 1.0 for normalized scoring.

    Attributes:
        citation: Weight for citation count signal
        venue: Weight for venue quality signal
        recency: Weight for publication recency signal
        engagement: Weight for community engagement (HuggingFace upvotes)
        completeness: Weight for metadata completeness
        author: Weight for author reputation (h-index)
    """

    model_config = ConfigDict(frozen=True)

    citation: float = Field(0.25, ge=0.0, le=1.0, description="Citation weight")
    venue: float = Field(0.20, ge=0.0, le=1.0, description="Venue quality weight")
    recency: float = Field(0.20, ge=0.0, le=1.0, description="Recency weight")
    engagement: float = Field(
        0.15, ge=0.0, le=1.0, description="Engagement weight (upvotes)"
    )
    completeness: float = Field(
        0.10, ge=0.0, le=1.0, description="Metadata completeness weight"
    )
    author: float = Field(0.10, ge=0.0, le=1.0, description="Author reputation weight")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_weight(self) -> float:
        """Sum of all weights for validation."""
        return (
            self.citation
            + self.venue
            + self.recency
            + self.engagement
            + self.completeness
            + self.author
        )

    @model_validator(mode="after")
    def validate_weights_sum(self) -> "QualityWeights":
        """Validate that weights sum to approximately 1.0.

        Logs a warning if weights are significantly off from 1.0,
        which could lead to inconsistent scoring.
        """
        total = self.total_weight
        if not (0.99 <= total <= 1.01):
            logger.warning(
                "quality_weights_not_normalized",
                total_weight=total,
                expected=1.0,
                message="Weights do not sum to 1.0, scoring may be inconsistent",
            )
        return self


class DiscoveryPipelineConfig(BaseModel):
    """Unified configuration for all discovery modes.

    Replaces fragmented configs: ProviderSelectionConfig, EnhancedDiscoveryConfig,
    QueryExpansionConfig, AggregationConfig.
    """

    model_config = ConfigDict(frozen=True)

    # Mode selection
    mode: DiscoveryMode = Field(DiscoveryMode.STANDARD, description="Discovery mode")

    # Provider configuration
    providers: List[str] = Field(
        default_factory=lambda: [
            "arxiv",
            "semantic_scholar",
            "openalex",
            "huggingface",
        ],
        description="Providers to query",
    )
    provider_timeout_seconds: float = Field(30.0, ge=1.0, le=300.0)
    fallback_enabled: bool = Field(True, description="Enable provider fallback")

    # Query enhancement
    query_enhancement: QueryEnhancementConfig = Field(
        default_factory=QueryEnhancementConfig
    )

    # Citation exploration (DEEP mode only)
    citation_exploration: CitationExplorationConfig = Field(
        default_factory=CitationExplorationConfig
    )

    # Quality filtering
    quality_weights: QualityWeights = Field(default_factory=QualityWeights)
    quality_tiers: QualityTierConfig = Field(default_factory=QualityTierConfig)
    min_quality_score: float = Field(
        0.3, ge=0.0, le=1.0, description="Minimum quality threshold"
    )
    min_citations: int = Field(0, ge=0, description="Minimum citation count")

    # Relevance filtering
    enable_relevance_ranking: bool = Field(True)
    min_relevance_score: float = Field(0.5, ge=0.0, le=1.0)

    # Result limits
    max_papers: int = Field(50, ge=1, le=500, description="Maximum papers to return")


class ScoredPaper(BaseModel):
    """Paper with quality and relevance scores.

    Combines a PaperMetadata with computed scores from the discovery pipeline.

    Attributes:
        paper_id: Unique identifier for the paper
        title: Paper title
        abstract: Paper abstract
        doi: Digital Object Identifier
        url: URL to paper
        pdf_url: URL to PDF (if available)
        authors: List of author names
        publication_date: Publication date string
        venue: Publication venue
        citation_count: Number of citations
        source: Provider source
        quality_score: Computed quality score (0.0-1.0)
        relevance_score: LLM-computed relevance score (0.0-1.0)
        engagement_score: Community engagement score (upvotes)
    """

    model_config = ConfigDict(extra="allow")

    # Paper metadata (flattened for easier access)
    paper_id: str = Field(..., description="Paper identifier")
    title: str = Field(..., description="Paper title")
    abstract: Optional[str] = Field(None, description="Paper abstract")
    doi: Optional[str] = Field(None, description="DOI")
    url: Optional[str] = Field(None, description="Paper URL")
    open_access_pdf: Optional[str] = Field(None, description="Open access PDF URL")
    authors: List[str] = Field(default_factory=list, description="Author names")
    publication_date: Optional[str] = Field(None, description="Publication date")
    venue: Optional[str] = Field(None, description="Publication venue")
    citation_count: int = Field(0, ge=0, description="Citation count")
    source: Optional[str] = Field(None, description="Provider source")

    # Computed scores
    quality_score: float = Field(
        0.0, ge=0.0, le=1.0, description="Quality score (0.0-1.0)"
    )
    relevance_score: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Relevance score (0.0-1.0)"
    )
    engagement_score: float = Field(
        0.0, ge=0.0, description="Engagement score (upvotes)"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def final_score(self) -> float:
        """Combined quality and relevance score.

        If relevance_score is available, weights it 60% with quality at 40%.
        Otherwise, returns the quality_score alone.
        """
        if self.relevance_score is not None:
            return 0.4 * self.quality_score + 0.6 * self.relevance_score
        return self.quality_score

    @classmethod
    def from_paper_metadata(
        cls,
        paper: "PaperMetadata",
        quality_score: float = 0.0,
        relevance_score: Optional[float] = None,
        engagement_score: float = 0.0,
        source: Optional[str] = None,
    ) -> "ScoredPaper":
        """Create ScoredPaper from PaperMetadata.

        Args:
            paper: Source PaperMetadata object
            quality_score: Computed quality score
            relevance_score: Optional relevance score from LLM
            engagement_score: Community engagement score
            source: Optional provider source name

        Returns:
            ScoredPaper with flattened metadata and scores
        """
        # Extract author names
        authors = []
        if paper.authors:
            for author in paper.authors:
                if hasattr(author, "name"):
                    authors.append(author.name)
                elif isinstance(author, str):
                    authors.append(author)
                elif isinstance(author, dict) and "name" in author:
                    authors.append(author["name"])

        # Get PDF URL if available
        open_access_pdf = None
        if hasattr(paper, "open_access_pdf") and paper.open_access_pdf:
            open_access_pdf = str(paper.open_access_pdf)

        # Get publication date as string
        pub_date = None
        if paper.publication_date:
            if isinstance(paper.publication_date, str):
                pub_date = paper.publication_date
            elif hasattr(paper.publication_date, "isoformat"):
                pub_date = paper.publication_date.isoformat()

        # Get source from paper if available, otherwise use provided
        paper_source = source
        if hasattr(paper, "source") and paper.source:
            if hasattr(paper.source, "value"):
                paper_source = paper.source.value
            else:
                paper_source = str(paper.source)

        return cls(
            paper_id=paper.paper_id,
            title=paper.title,
            abstract=paper.abstract,
            doi=paper.doi,
            url=str(paper.url) if paper.url else None,
            open_access_pdf=open_access_pdf,
            authors=authors,
            publication_date=pub_date,
            venue=paper.venue,
            citation_count=paper.citation_count or 0,
            source=paper_source,
            quality_score=quality_score,
            relevance_score=relevance_score,
            engagement_score=engagement_score,
        )


class DiscoveryMetrics(BaseModel):
    """Metrics from the discovery pipeline execution.

    Tracks papers at each stage and aggregate statistics.

    Attributes:
        queries_generated: Number of sub-queries generated
        papers_retrieved: Total papers from all providers
        papers_after_dedup: Papers after deduplication
        papers_after_quality_filter: Papers passing quality threshold
        papers_after_relevance_filter: Papers passing relevance threshold
        providers_queried: List of provider names queried
        avg_relevance_score: Average relevance score of final papers
        avg_quality_score: Average quality score of final papers
        pipeline_duration_ms: Total pipeline execution time
        forward_citations_found: Forward citations discovered (DEEP mode)
        backward_citations_found: Backward citations discovered (DEEP mode)
        duration_ms: Alias for pipeline_duration_ms
    """

    model_config = ConfigDict(frozen=True)

    queries_generated: int = Field(0, ge=0, description="Sub-queries generated")
    papers_retrieved: int = Field(0, ge=0, description="Papers from all providers")
    papers_after_dedup: int = Field(0, ge=0, description="Papers after dedup")
    papers_after_quality_filter: int = Field(
        0, ge=0, description="Papers after quality filter"
    )
    papers_after_relevance_filter: int = Field(
        0, ge=0, description="Papers after relevance filter"
    )
    providers_queried: List[str] = Field(
        default_factory=list, description="Providers queried"
    )
    avg_relevance_score: float = Field(
        0.0, ge=0.0, le=1.0, description="Avg relevance score"
    )
    avg_quality_score: float = Field(
        0.0, ge=0.0, le=1.0, description="Avg quality score"
    )
    pipeline_duration_ms: int = Field(0, ge=0, description="Pipeline duration (ms)")
    forward_citations_found: int = Field(0, ge=0, description="Forward citations found")
    backward_citations_found: int = Field(
        0, ge=0, description="Backward citations found"
    )
    duration_ms: int = Field(0, ge=0, description="Alias for pipeline_duration_ms")


class DiscoveryResult(BaseModel):
    """Result of the enhanced discovery pipeline.

    Contains the final ranked papers, metrics, and queries used.

    Attributes:
        papers: List of scored and ranked papers
        metrics: Pipeline execution metrics
        queries_used: Decomposed queries used for retrieval
        source_breakdown: Papers per source
        mode: Discovery mode used
    """

    model_config = ConfigDict(extra="forbid")

    papers: List[ScoredPaper] = Field(default_factory=list, description="Ranked papers")
    metrics: DiscoveryMetrics = Field(
        default_factory=DiscoveryMetrics,  # type: ignore[arg-type]
        description="Pipeline metrics",
    )
    queries_used: List[DecomposedQuery] = Field(
        default_factory=list, description="Queries used"
    )
    source_breakdown: Dict[str, int] = Field(
        default_factory=dict, description="Papers per source"
    )
    mode: Optional[DiscoveryMode] = Field(None, description="Discovery mode used")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def paper_count(self) -> int:
        """Number of papers in result."""
        return len(self.papers)

    def get_top_papers(self, n: int = 10) -> List[ScoredPaper]:
        """Get top N papers by final score.

        Args:
            n: Number of papers to return

        Returns:
            Top N papers sorted by final_score descending
        """
        sorted_papers = sorted(self.papers, key=lambda p: p.final_score, reverse=True)
        return sorted_papers[:n]


# Phase 7.1: Discovery Foundation Models


class DiscoveryStats(BaseModel):
    """Statistics from discovery filtering operation.

    Tracks the number of papers discovered, filtered, and the breakdown
    of filter reasons for incremental discovery.

    Attributes:
        total_discovered: Total papers discovered from provider
        new_count: Number of new papers not in registry
        filtered_count: Number of papers filtered out as duplicates
        filter_breakdown: Breakdown of filter reasons (doi, arxiv, title, provider_id)
        incremental_query: Whether this was an incremental query
        query_start_date: Start date for incremental queries
    """

    total_discovered: int = Field(
        ..., ge=0, description="Total papers discovered from provider"
    )
    new_count: int = Field(
        ..., ge=0, description="Number of new papers not in registry"
    )
    filtered_count: int = Field(
        ..., ge=0, description="Number of papers filtered out as duplicates"
    )
    filter_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="Breakdown of filter reasons (doi, arxiv, title, provider_id)",
    )
    incremental_query: bool = Field(
        default=False, description="Whether this was an incremental query"
    )
    query_start_date: Optional[datetime] = Field(
        default=None, description="Start date for incremental queries"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_discovered": 25,
                "new_count": 18,
                "filtered_count": 7,
                "filter_breakdown": {"doi": 5, "arxiv": 2, "title": 0},
                "incremental_query": True,
                "query_start_date": "2025-01-20T00:00:00Z",
            }
        }
    )


class FilteredPaper(BaseModel):
    """Information about a paper that was filtered out.

    Records the paper metadata, why it was filtered, and which
    existing registry entry it matched.

    Attributes:
        paper: Paper metadata that was filtered
        filter_reason: Reason for filtering (doi, arxiv, title, provider_id)
        matched_entry_id: Registry entry ID that matched this paper
    """

    paper: "PaperMetadata" = Field(..., description="Paper metadata that was filtered")
    filter_reason: str = Field(
        ...,
        description="Reason for filtering (doi, arxiv, title, provider_id)",
    )
    matched_entry_id: str = Field(
        ..., description="Registry entry ID that matched this paper"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "paper": {
                    "paper_id": "2301.12345",
                    "title": "Sample Paper",
                    "url": "https://example.com/paper",
                },
                "filter_reason": "doi",
                "matched_entry_id": "entry_2025-01-20_001",
            }
        }
    )


class DiscoveryFilterResult(BaseModel):
    """Result of discovery filtering operation.

    Contains the list of new papers to process, filtered papers for
    tracking, and statistics about the filtering operation.

    Attributes:
        new_papers: New papers not in registry
        filtered_papers: Papers filtered out as duplicates
        stats: Filtering statistics
    """

    new_papers: List["PaperMetadata"] = Field(
        default_factory=list, description="New papers not in registry"
    )
    filtered_papers: List[FilteredPaper] = Field(
        default_factory=list, description="Papers filtered out as duplicates"
    )
    stats: DiscoveryStats = Field(..., description="Filtering statistics")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "new_papers": [],
                "filtered_papers": [],
                "stats": {
                    "total_discovered": 25,
                    "new_count": 18,
                    "filtered_count": 7,
                    "filter_breakdown": {"doi": 5, "arxiv": 2},
                    "incremental_query": True,
                },
            }
        }
    )


class ResolvedTimeframe(BaseModel):
    """Resolved timeframe for discovery query.

    Converts configuration timeframe into concrete start/end dates,
    with support for incremental queries based on last run time.

    Attributes:
        start_date: Query start date (inclusive)
        end_date: Query end date (inclusive)
        is_incremental: Whether this is based on last run time
        overlap_buffer_hours: Hours of overlap to prevent gaps
        original_timeframe: Original timeframe configuration (stored as dict)
    """

    start_date: datetime = Field(..., description="Query start date (inclusive)")
    end_date: datetime = Field(..., description="Query end date (inclusive)")
    is_incremental: bool = Field(
        default=False, description="Whether this is based on last run time"
    )
    overlap_buffer_hours: int = Field(
        default=1, ge=0, le=168, description="Hours of overlap to prevent gaps"
    )
    original_timeframe: Optional[Dict] = Field(
        default=None, description="Original timeframe configuration (as dict)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "start_date": "2025-01-20T00:00:00Z",
                "end_date": "2025-01-24T23:59:59Z",
                "is_incremental": True,
                "overlap_buffer_hours": 1,
                "original_timeframe": None,
            }
        }
    )

"""Discovery data models for Phase 6: Enhanced Discovery Pipeline.

This module defines data structures for:
- Query decomposition (sub-queries with focus areas)
- Quality scoring weights
- Scored papers with quality and relevance metrics
- Discovery pipeline metrics and results

Usage:
    from src.models.discovery import (
        DecomposedQuery,
        QueryFocus,
        QualityWeights,
        ScoredPaper,
        DiscoveryMetrics,
        DiscoveryResult,
    )
"""

from enum import Enum
from typing import List, Optional, TYPE_CHECKING
from pydantic import BaseModel, Field, ConfigDict, computed_field

if TYPE_CHECKING:
    from src.models.paper import PaperMetadata


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


class DiscoveryResult(BaseModel):
    """Result of the enhanced discovery pipeline.

    Contains the final ranked papers, metrics, and queries used.

    Attributes:
        papers: List of scored and ranked papers
        metrics: Pipeline execution metrics
        queries_used: Decomposed queries used for retrieval
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

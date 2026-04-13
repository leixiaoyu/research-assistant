from pydantic import BaseModel, Field, HttpUrl, ConfigDict
from typing import Optional, List
from datetime import datetime, timezone


class Author(BaseModel):
    """Paper author information"""

    name: str
    author_id: Optional[str] = None
    affiliation: Optional[str] = None


class PaperMetadata(BaseModel):
    """Complete metadata for a research paper"""

    # Identifiers
    paper_id: str = Field(..., description="Semantic Scholar paper ID")
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None

    # Content
    title: str = Field(..., min_length=1, max_length=1000)
    abstract: Optional[str] = Field(None, max_length=10000)

    # Links
    url: HttpUrl
    open_access_pdf: Optional[HttpUrl] = None

    # Metadata
    authors: List[Author] = Field(default_factory=list)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    publication_date: Optional[datetime] = None
    venue: Optional[str] = None

    # Metrics
    citation_count: int = Field(0, ge=0)
    # None = unknown (non-SS source), 0 = known to have no influential citations
    influential_citation_count: Optional[int] = Field(None, ge=0)

    # Computed fields
    relevance_score: float = Field(0.0, ge=0.0, le=1.0)

    # Phase 3.4: Quality scoring and PDF availability tracking
    quality_score: float = Field(
        0.0, ge=0.0, le=100.0, description="Composite quality score (0-100)"
    )
    pdf_available: bool = Field(
        False, description="Whether a PDF is available for download"
    )
    pdf_source: Optional[str] = Field(
        None, description="Source of PDF (open_access, arxiv, etc.)"
    )

    # Phase 7.2: Multi-source tracking fields
    discovery_source: Optional[str] = Field(
        None,
        description=(
            "Provider that discovered this paper "
            "(arxiv, semantic_scholar, openalex, feedback_recommended, etc.)"
        ),
    )
    discovery_method: Optional[str] = Field(
        None,
        description=(
            "How paper was discovered "
            "(keyword, forward_citation, backward_citation, expanded_query)"
        ),
    )
    source_count: int = Field(
        1, ge=1, description="Number of sources that found this paper"
    )
    ranking_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Aggregation ranking score for multi-source results",
    )

    # Phase 7.3: Feedback integration fields
    preference_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="User preference score from feedback learning",
    )

    model_config = ConfigDict(populate_by_name=True)


class SearchResult(BaseModel):
    """Result from a search query"""

    query: str
    timeframe: str
    total_found: int
    papers: List[PaperMetadata]
    search_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

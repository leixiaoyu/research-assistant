from pydantic import BaseModel, Field, HttpUrl, ConfigDict
from typing import Optional, List
from datetime import datetime

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
    influential_citation_count: int = Field(0, ge=0)

    # Computed fields
    relevance_score: float = Field(0.0, ge=0.0, le=1.0)

    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
            HttpUrl: lambda v: str(v)
        }
    )

class SearchResult(BaseModel):
    """Result from a search query"""
    query: str
    timeframe: str
    total_found: int
    papers: List[PaperMetadata]
    search_timestamp: datetime = Field(default_factory=datetime.utcnow)

"""Shared type helpers for test fixtures.

Provides proper Pydantic V2 type construction for tests to ensure
type safety and Mypy compliance.

Usage:
    from tests.conftest_types import make_url, make_paper_metadata
"""

from datetime import datetime
from typing import Optional, List

from pydantic import TypeAdapter, HttpUrl

from src.models.paper import PaperMetadata, Author


# Type adapters for Pydantic strict types
_url_adapter = TypeAdapter(HttpUrl)


def make_url(url_string: str) -> HttpUrl:
    """Convert a string to a validated HttpUrl.

    Args:
        url_string: A valid URL string

    Returns:
        A Pydantic HttpUrl object

    Example:
        >>> url = make_url("https://arxiv.org/abs/2301.12345")
    """
    return _url_adapter.validate_python(url_string)


def make_paper_metadata(
    paper_id: str = "test-paper-001",
    title: str = "Test Paper Title",
    abstract: Optional[
        str
    ] = "This is a test abstract with sufficient length for completeness scoring.",
    doi: Optional[str] = None,
    url: str = "https://example.com/paper",
    open_access_pdf: Optional[str] = None,
    authors: Optional[List[Author]] = None,
    publication_date: Optional[datetime] = None,
    venue: Optional[str] = None,
    citation_count: int = 0,
    influential_citation_count: int = 0,
    quality_score: float = 0.0,
    relevance_score: float = 0.0,
    discovery_source: Optional[str] = None,
) -> PaperMetadata:
    """Create a PaperMetadata with proper Pydantic types.

    This helper ensures all fields use correct Pydantic V2 types
    (HttpUrl, datetime with timezone, etc.) for Mypy compliance.

    Args:
        paper_id: Unique identifier for the paper
        title: Paper title
        abstract: Paper abstract (optional)
        doi: Digital Object Identifier (optional)
        url: Paper URL (required, converted to HttpUrl)
        open_access_pdf: Open access PDF URL (optional, converted to HttpUrl)
        authors: List of Author objects (defaults to empty list)
        publication_date: Publication date with timezone (optional)
        venue: Publication venue (optional)
        citation_count: Number of citations
        influential_citation_count: Number of influential citations
        quality_score: Computed quality score
        relevance_score: Computed relevance score
        discovery_source: Provider that discovered this paper (optional)

    Returns:
        A properly constructed PaperMetadata object
    """
    return PaperMetadata(
        paper_id=paper_id,
        title=title,
        abstract=abstract,
        doi=doi,
        url=make_url(url),
        open_access_pdf=make_url(open_access_pdf) if open_access_pdf else None,
        authors=authors or [],
        publication_date=publication_date,
        venue=venue,
        citation_count=citation_count,
        influential_citation_count=influential_citation_count,
        quality_score=quality_score,
        relevance_score=relevance_score,
        discovery_source=discovery_source,
    )

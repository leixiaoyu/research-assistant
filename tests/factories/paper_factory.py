"""Factory for creating PaperMetadata and related model instances.

Provides sensible defaults and convenience methods for common test scenarios.

Note: Pydantic coerces string URLs to HttpUrl at runtime, so we use
string literals for URL fields. Type ignores are added where mypy
cannot infer this coercion.
"""

from typing import Any, cast

from pydantic import HttpUrl

from src.models.paper import PaperMetadata, Author
from src.models.discovery import ScoredPaper


class AuthorFactory:
    """Factory for creating Author instances."""

    _counter = 0

    @classmethod
    def _next_id(cls) -> int:
        """Generate sequential ID for unique author names."""
        cls._counter += 1
        return cls._counter

    @classmethod
    def reset_counter(cls) -> None:
        """Reset the counter (useful between tests)."""
        cls._counter = 0

    @classmethod
    def create(
        cls,
        name: str | None = None,
        author_id: str | None = None,
        affiliation: str | None = None,
        **kwargs: Any,
    ) -> Author:
        """Create an Author with defaults.

        Args:
            name: Author name. Defaults to "Author {N}".
            author_id: Optional author ID.
            affiliation: Optional affiliation.
            **kwargs: Additional fields to pass to Author.

        Returns:
            Author instance.
        """
        idx = cls._next_id()
        return Author(
            name=name or f"Author {idx}",
            author_id=author_id,
            affiliation=affiliation,
            **kwargs,
        )

    @classmethod
    def create_batch(cls, count: int, **kwargs: Any) -> list[Author]:
        """Create multiple authors.

        Args:
            count: Number of authors to create.
            **kwargs: Common fields for all authors.

        Returns:
            List of Author instances.
        """
        return [cls.create(**kwargs) for _ in range(count)]

    @classmethod
    def with_affiliation(cls, affiliation: str = "MIT") -> Author:
        """Create an author with affiliation."""
        return cls.create(affiliation=affiliation)


class PaperFactory:
    """Factory for creating PaperMetadata instances."""

    _counter = 0

    @classmethod
    def _next_id(cls) -> int:
        """Generate sequential ID for unique paper IDs."""
        cls._counter += 1
        return cls._counter

    @classmethod
    def reset_counter(cls) -> None:
        """Reset the counter (useful between tests)."""
        cls._counter = 0

    @classmethod
    def create(
        cls,
        paper_id: str | None = None,
        title: str | None = None,
        url: str | None = None,
        abstract: str | None = None,
        authors: list[Author] | None = None,
        year: int | None = None,
        doi: str | None = None,
        arxiv_id: str | None = None,
        citation_count: int = 0,
        pdf_available: bool = False,
        open_access_pdf: str | None = None,
        discovery_source: str | None = "test",
        discovery_method: str | None = "keyword",
        **kwargs: Any,
    ) -> PaperMetadata:
        """Create a PaperMetadata with defaults.

        Args:
            paper_id: Paper identifier. Defaults to "paper-{N}".
            title: Paper title. Defaults to "Test Paper {N}".
            url: Paper URL. Defaults to "https://example.com/paper/{N}".
            abstract: Paper abstract. Defaults to a generic abstract.
            authors: List of authors. Defaults to empty list.
            year: Publication year. Defaults to 2024.
            doi: DOI identifier. Optional.
            arxiv_id: ArXiv identifier. Optional.
            citation_count: Citation count. Defaults to 0.
            pdf_available: Whether PDF is available. Defaults to False.
            open_access_pdf: URL to open access PDF. Optional.
            discovery_source: Source of discovery. Defaults to "test".
            discovery_method: Method of discovery. Defaults to "keyword".
            **kwargs: Additional fields.

        Returns:
            PaperMetadata instance.
        """
        idx = cls._next_id()
        # Pydantic coerces strings to HttpUrl at runtime
        url_value = cast(HttpUrl, url or f"https://example.com/paper/{idx}")
        pdf_url = cast(HttpUrl, open_access_pdf) if open_access_pdf else None
        return PaperMetadata(
            paper_id=paper_id or f"paper-{idx}",
            title=title or f"Test Paper {idx}",
            url=url_value,
            abstract=abstract or f"This is the abstract for test paper {idx}.",
            authors=authors if authors is not None else [],
            year=year or 2024,
            doi=doi,
            arxiv_id=arxiv_id,
            citation_count=citation_count,
            pdf_available=pdf_available,
            open_access_pdf=pdf_url,
            discovery_source=discovery_source,
            discovery_method=discovery_method,
            **kwargs,
        )

    @classmethod
    def create_batch(cls, count: int, **kwargs: Any) -> list[PaperMetadata]:
        """Create multiple papers.

        Args:
            count: Number of papers to create.
            **kwargs: Common fields for all papers.

        Returns:
            List of PaperMetadata instances.
        """
        return [cls.create(**kwargs) for _ in range(count)]

    @classmethod
    def minimal(cls, **kwargs: Any) -> PaperMetadata:
        """Create a minimal paper with only required fields.

        Useful for testing validation or minimal data scenarios.
        """
        idx = cls._next_id()
        return PaperMetadata(
            paper_id=kwargs.get("paper_id", f"minimal-{idx}"),
            title=kwargs.get("title", f"Minimal Paper {idx}"),
            url=cast(HttpUrl, kwargs.get("url", f"https://example.com/minimal/{idx}")),
        )

    @classmethod
    def with_doi(cls, doi: str | None = None, **kwargs: Any) -> PaperMetadata:
        """Create a paper with a DOI.

        Args:
            doi: DOI string. Defaults to a generated DOI.
            **kwargs: Additional fields.

        Returns:
            PaperMetadata with DOI.
        """
        idx = cls._next_id()
        return cls.create(
            paper_id=f"doi-paper-{idx}",
            doi=doi or f"10.1234/test.{idx}",
            **kwargs,
        )

    @classmethod
    def with_arxiv(cls, arxiv_id: str | None = None, **kwargs: Any) -> PaperMetadata:
        """Create a paper with an ArXiv ID.

        Args:
            arxiv_id: ArXiv ID. Defaults to a generated ID.
            **kwargs: Additional fields.

        Returns:
            PaperMetadata with ArXiv ID.
        """
        idx = cls._next_id()
        return cls.create(
            paper_id=f"arxiv-paper-{idx}",
            arxiv_id=arxiv_id or f"2401.{idx:05d}",
            discovery_source="arxiv",
            **kwargs,
        )

    @classmethod
    def with_citations(cls, count: int = 100, **kwargs: Any) -> PaperMetadata:
        """Create a paper with citation count.

        Args:
            count: Number of citations.
            **kwargs: Additional fields.

        Returns:
            PaperMetadata with citations.
        """
        return cls.create(citation_count=count, **kwargs)

    @classmethod
    def with_pdf(cls, pdf_url: str | None = None, **kwargs: Any) -> PaperMetadata:
        """Create a paper with available PDF.

        Args:
            pdf_url: URL to PDF. Defaults to a generated URL.
            **kwargs: Additional fields.

        Returns:
            PaperMetadata with PDF available.
        """
        idx = cls._next_id()
        pdf_url_value = pdf_url or f"https://example.com/pdf/{idx}.pdf"
        return cls.create(
            paper_id=f"pdf-paper-{idx}",
            pdf_available=True,
            open_access_pdf=pdf_url_value,
            **kwargs,
        )

    @classmethod
    def highly_cited(cls, **kwargs: Any) -> PaperMetadata:
        """Create a highly-cited paper (>1000 citations)."""
        return cls.with_citations(count=1500, **kwargs)

    @classmethod
    def recent(cls, year: int = 2024, **kwargs: Any) -> PaperMetadata:
        """Create a recent paper."""
        return cls.create(year=year, **kwargs)

    @classmethod
    def from_source(
        cls, source: str, method: str = "keyword", **kwargs: Any
    ) -> PaperMetadata:
        """Create a paper from a specific discovery source.

        Args:
            source: Discovery source (arxiv, semantic_scholar, etc.)
            method: Discovery method (keyword, citation, etc.)
            **kwargs: Additional fields.

        Returns:
            PaperMetadata with specified source.
        """
        return cls.create(
            discovery_source=source,
            discovery_method=method,
            **kwargs,
        )


class ScoredPaperFactory:
    """Factory for creating ScoredPaper instances."""

    _counter = 0

    @classmethod
    def _next_id(cls) -> int:
        """Generate sequential ID."""
        cls._counter += 1
        return cls._counter

    @classmethod
    def reset_counter(cls) -> None:
        """Reset the counter."""
        cls._counter = 0

    @classmethod
    def create(
        cls,
        paper_id: str | None = None,
        title: str | None = None,
        url: str | None = None,
        abstract: str | None = None,
        quality_score: float = 0.8,
        relevance_score: float = 0.7,
        **kwargs: Any,
    ) -> ScoredPaper:
        """Create a ScoredPaper with defaults.

        Args:
            paper_id: Paper identifier.
            title: Paper title.
            url: Paper URL.
            abstract: Paper abstract.
            quality_score: Quality score (0-1). Defaults to 0.8.
            relevance_score: Relevance score (0-1). Defaults to 0.7.
            **kwargs: Additional fields.

        Returns:
            ScoredPaper instance.
        """
        idx = cls._next_id()
        return ScoredPaper(
            paper_id=paper_id or f"scored-{idx}",
            title=title or f"Scored Paper {idx}",
            url=url or f"https://example.com/scored/{idx}",
            abstract=abstract or f"Abstract for scored paper {idx}.",
            quality_score=quality_score,
            relevance_score=relevance_score,
            **kwargs,
        )

    @classmethod
    def create_batch(cls, count: int, **kwargs: Any) -> list[ScoredPaper]:
        """Create multiple scored papers."""
        return [cls.create(**kwargs) for _ in range(count)]

    @classmethod
    def high_quality(cls, **kwargs: Any) -> ScoredPaper:
        """Create a high-quality paper (score > 0.9)."""
        return cls.create(quality_score=0.95, relevance_score=0.9, **kwargs)

    @classmethod
    def low_quality(cls, **kwargs: Any) -> ScoredPaper:
        """Create a low-quality paper (score < 0.3)."""
        return cls.create(quality_score=0.2, relevance_score=0.3, **kwargs)

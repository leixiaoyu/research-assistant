"""Factory for creating configuration model instances.

Provides sensible defaults for FilterConfig, DedupConfig, and related configs.
"""

from typing import Any

from src.models.filters import FilterConfig
from src.models.dedup import DedupConfig
from src.models.config import (
    QueryExpansionConfig,
    CitationExplorationConfig,
    AggregationConfig,
    RankingWeights,
)


class FilterConfigFactory:
    """Factory for creating FilterConfig instances."""

    @classmethod
    def create(
        cls,
        min_citation_count: int = 0,
        min_year: int | None = None,
        max_year: int | None = None,
        min_relevance_score: float = 0.0,
        citation_weight: float = 0.30,
        recency_weight: float = 0.20,
        relevance_weight: float = 0.50,
        **kwargs: Any,
    ) -> FilterConfig:
        """Create a FilterConfig with defaults.

        Args:
            min_citation_count: Minimum citations required.
            min_year: Minimum publication year.
            max_year: Maximum publication year.
            min_relevance_score: Minimum relevance score.
            citation_weight: Weight for citation score.
            recency_weight: Weight for recency score.
            relevance_weight: Weight for relevance score.
            **kwargs: Additional fields.

        Returns:
            FilterConfig instance.
        """
        return FilterConfig(
            min_citation_count=min_citation_count,
            min_year=min_year,
            max_year=max_year,
            min_relevance_score=min_relevance_score,
            citation_weight=citation_weight,
            recency_weight=recency_weight,
            relevance_weight=relevance_weight,
            **kwargs,
        )

    @classmethod
    def strict(cls, **kwargs: Any) -> FilterConfig:
        """Create a strict filter config.

        Requires:
        - At least 10 citations
        - Papers from 2020 onwards
        - Min relevance score of 0.5
        """
        return cls.create(
            min_citation_count=10,
            min_year=2020,
            min_relevance_score=0.5,
            **kwargs,
        )

    @classmethod
    def relaxed(cls, **kwargs: Any) -> FilterConfig:
        """Create a relaxed filter config (minimal filtering)."""
        return cls.create(
            min_citation_count=0,
            min_year=None,
            min_relevance_score=0.0,
            **kwargs,
        )

    @classmethod
    def recent_only(cls, year: int = 2023, **kwargs: Any) -> FilterConfig:
        """Create a filter for recent papers only."""
        return cls.create(min_year=year, **kwargs)

    @classmethod
    def citation_focused(cls, **kwargs: Any) -> FilterConfig:
        """Create a citation-focused filter config."""
        return cls.create(
            citation_weight=0.60,
            recency_weight=0.10,
            relevance_weight=0.30,
            **kwargs,
        )


class DedupConfigFactory:
    """Factory for creating DedupConfig instances."""

    @classmethod
    def create(
        cls,
        enabled: bool = True,
        title_similarity_threshold: float = 0.90,
        use_doi_matching: bool = True,
        use_title_matching: bool = True,
        **kwargs: Any,
    ) -> DedupConfig:
        """Create a DedupConfig with defaults.

        Args:
            enabled: Whether deduplication is enabled.
            title_similarity_threshold: Threshold for title similarity.
            use_doi_matching: Use DOI for matching.
            use_title_matching: Use title for matching.
            **kwargs: Additional fields.

        Returns:
            DedupConfig instance.
        """
        return DedupConfig(
            enabled=enabled,
            title_similarity_threshold=title_similarity_threshold,
            use_doi_matching=use_doi_matching,
            use_title_matching=use_title_matching,
            **kwargs,
        )

    @classmethod
    def disabled(cls, **kwargs: Any) -> DedupConfig:
        """Create a disabled dedup config."""
        return cls.create(enabled=False, **kwargs)

    @classmethod
    def doi_only(cls, **kwargs: Any) -> DedupConfig:
        """Create a DOI-only dedup config."""
        return cls.create(
            use_doi_matching=True,
            use_title_matching=False,
            **kwargs,
        )

    @classmethod
    def strict(cls, **kwargs: Any) -> DedupConfig:
        """Create a strict dedup config (high similarity threshold)."""
        return cls.create(title_similarity_threshold=0.95, **kwargs)

    @classmethod
    def relaxed(cls, **kwargs: Any) -> DedupConfig:
        """Create a relaxed dedup config (lower threshold)."""
        return cls.create(title_similarity_threshold=0.80, **kwargs)


class QueryExpansionConfigFactory:
    """Factory for creating QueryExpansionConfig instances."""

    @classmethod
    def create(
        cls,
        enabled: bool = True,
        max_variants: int = 5,
        cache_expansions: bool = True,
        **kwargs: Any,
    ) -> QueryExpansionConfig:
        """Create a QueryExpansionConfig with defaults."""
        return QueryExpansionConfig(
            enabled=enabled,
            max_variants=max_variants,
            cache_expansions=cache_expansions,
            **kwargs,
        )

    @classmethod
    def disabled(cls, **kwargs: Any) -> QueryExpansionConfig:
        """Create a disabled query expansion config."""
        return cls.create(enabled=False, **kwargs)

    @classmethod
    def minimal(cls, **kwargs: Any) -> QueryExpansionConfig:
        """Create a minimal expansion config (2 variants)."""
        return cls.create(max_variants=2, **kwargs)


class CitationConfigFactory:
    """Factory for creating CitationExplorationConfig instances."""

    @classmethod
    def create(
        cls,
        enabled: bool = True,
        forward: bool = True,
        backward: bool = True,
        max_forward_per_paper: int = 10,
        max_backward_per_paper: int = 10,
        **kwargs: Any,
    ) -> CitationExplorationConfig:
        """Create a CitationExplorationConfig with defaults."""
        return CitationExplorationConfig(
            enabled=enabled,
            forward=forward,
            backward=backward,
            max_forward_per_paper=max_forward_per_paper,
            max_backward_per_paper=max_backward_per_paper,
            **kwargs,
        )

    @classmethod
    def disabled(cls, **kwargs: Any) -> CitationExplorationConfig:
        """Create a disabled citation config."""
        return cls.create(enabled=False, **kwargs)

    @classmethod
    def forward_only(cls, **kwargs: Any) -> CitationExplorationConfig:
        """Create a forward-only citation config."""
        return cls.create(forward=True, backward=False, **kwargs)

    @classmethod
    def backward_only(cls, **kwargs: Any) -> CitationExplorationConfig:
        """Create a backward-only citation config."""
        return cls.create(forward=False, backward=True, **kwargs)


class AggregationConfigFactory:
    """Factory for creating AggregationConfig instances."""

    @classmethod
    def create(
        cls,
        max_papers_per_topic: int = 50,
        ranking_weights: RankingWeights | None = None,
        **kwargs: Any,
    ) -> AggregationConfig:
        """Create an AggregationConfig with defaults."""
        return AggregationConfig(
            max_papers_per_topic=max_papers_per_topic,
            ranking_weights=ranking_weights or RankingWeights(),
            **kwargs,
        )

    @classmethod
    def small_batch(cls, **kwargs: Any) -> AggregationConfig:
        """Create a config for small batches (10 papers)."""
        return cls.create(max_papers_per_topic=10, **kwargs)

    @classmethod
    def large_batch(cls, **kwargs: Any) -> AggregationConfig:
        """Create a config for large batches (200 papers)."""
        return cls.create(max_papers_per_topic=200, **kwargs)

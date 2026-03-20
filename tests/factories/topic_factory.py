"""Factory for creating ResearchTopic and Timeframe instances.

Provides sensible defaults and convenience methods for common test scenarios.
"""

from datetime import date
from typing import Any

from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    TimeframeSinceYear,
    TimeframeDateRange,
    ProviderType,
)


class TimeframeFactory:
    """Factory for creating Timeframe instances."""

    @classmethod
    def recent(cls, value: str = "48h") -> TimeframeRecent:
        """Create a recent timeframe.

        Args:
            value: Time value (e.g., "48h", "7d").

        Returns:
            TimeframeRecent instance.
        """
        return TimeframeRecent(value=value)

    @classmethod
    def since_year(cls, year: int = 2020) -> TimeframeSinceYear:
        """Create a since-year timeframe.

        Args:
            year: Starting year.

        Returns:
            TimeframeSinceYear instance.
        """
        return TimeframeSinceYear(value=year)

    @classmethod
    def date_range(
        cls,
        start: date | None = None,
        end: date | None = None,
    ) -> TimeframeDateRange:
        """Create a date range timeframe.

        Args:
            start: Start date. Defaults to 2024-01-01.
            end: End date. Defaults to 2024-12-31.

        Returns:
            TimeframeDateRange instance.
        """
        return TimeframeDateRange(
            start_date=start or date(2024, 1, 1),
            end_date=end or date(2024, 12, 31),
        )

    @classmethod
    def last_24h(cls) -> TimeframeRecent:
        """Convenience: last 24 hours."""
        return cls.recent("24h")

    @classmethod
    def last_week(cls) -> TimeframeRecent:
        """Convenience: last 7 days."""
        return cls.recent("7d")

    @classmethod
    def last_month(cls) -> TimeframeRecent:
        """Convenience: last 30 days."""
        return cls.recent("30d")


class TopicFactory:
    """Factory for creating ResearchTopic instances."""

    _counter = 0

    @classmethod
    def _next_id(cls) -> int:
        """Generate sequential ID for unique queries."""
        cls._counter += 1
        return cls._counter

    @classmethod
    def reset_counter(cls) -> None:
        """Reset the counter (useful between tests)."""
        cls._counter = 0

    @classmethod
    def create(
        cls,
        query: str | None = None,
        timeframe: (
            TimeframeRecent | TimeframeSinceYear | TimeframeDateRange | None
        ) = None,
        max_papers: int = 50,
        provider: ProviderType = ProviderType.ARXIV,
        **kwargs: Any,
    ) -> ResearchTopic:
        """Create a ResearchTopic with defaults.

        Args:
            query: Search query. Defaults to "machine learning test {N}".
            timeframe: Timeframe for search. Defaults to 48h.
            max_papers: Maximum papers to retrieve. Defaults to 50.
            provider: Provider type. Defaults to ARXIV.
            **kwargs: Additional fields.

        Returns:
            ResearchTopic instance.
        """
        idx = cls._next_id()
        return ResearchTopic(
            query=query or f"machine learning test {idx}",
            timeframe=timeframe or TimeframeFactory.recent(),
            max_papers=max_papers,
            provider=provider,
            **kwargs,
        )

    @classmethod
    def create_batch(cls, count: int, **kwargs: Any) -> list[ResearchTopic]:
        """Create multiple topics.

        Args:
            count: Number of topics to create.
            **kwargs: Common fields for all topics.

        Returns:
            List of ResearchTopic instances.
        """
        return [cls.create(**kwargs) for _ in range(count)]

    @classmethod
    def arxiv(cls, query: str | None = None, **kwargs: Any) -> ResearchTopic:
        """Create a topic for ArXiv provider.

        Args:
            query: Search query.
            **kwargs: Additional fields.

        Returns:
            ResearchTopic configured for ArXiv.
        """
        return cls.create(
            query=query or "deep learning",
            provider=ProviderType.ARXIV,
            **kwargs,
        )

    @classmethod
    def semantic_scholar(cls, query: str | None = None, **kwargs: Any) -> ResearchTopic:
        """Create a topic for Semantic Scholar provider.

        Args:
            query: Search query.
            **kwargs: Additional fields.

        Returns:
            ResearchTopic configured for Semantic Scholar.
        """
        return cls.create(
            query=query or "natural language processing",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            **kwargs,
        )

    @classmethod
    def recent_papers(cls, hours: int = 48, **kwargs: Any) -> ResearchTopic:
        """Create a topic for recent papers.

        Args:
            hours: How many hours back to search.
            **kwargs: Additional fields.

        Returns:
            ResearchTopic with recent timeframe.
        """
        return cls.create(
            timeframe=TimeframeFactory.recent(f"{hours}h"),
            **kwargs,
        )

    @classmethod
    def since_year(cls, year: int = 2020, **kwargs: Any) -> ResearchTopic:
        """Create a topic for papers since a specific year.

        Args:
            year: Starting year.
            **kwargs: Additional fields.

        Returns:
            ResearchTopic with since-year timeframe.
        """
        return cls.create(
            timeframe=TimeframeFactory.since_year(year),
            **kwargs,
        )

    @classmethod
    def large_batch(cls, max_papers: int = 100, **kwargs: Any) -> ResearchTopic:
        """Create a topic for large paper retrieval.

        Args:
            max_papers: Maximum papers (default 100).
            **kwargs: Additional fields.

        Returns:
            ResearchTopic configured for large batches.
        """
        return cls.create(max_papers=max_papers, **kwargs)

    @classmethod
    def minimal(cls, **kwargs: Any) -> ResearchTopic:
        """Create a minimal topic with only required fields."""
        idx = cls._next_id()
        query = kwargs.get("query", f"minimal query {idx}")
        timeframe = kwargs.get("timeframe", TimeframeFactory.recent())
        return ResearchTopic(
            query=query,  # type: ignore[arg-type]
            timeframe=timeframe,  # type: ignore[arg-type]
        )

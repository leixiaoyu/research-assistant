"""Shared helpers for constructing monitoring paper records and topics.

Extracted from :class:`ArxivMonitor` and :class:`MultiProviderMonitor` so
neither monitor duplicates the same DTO-building and topic-building logic.

H-C1: ``to_paper_record`` consolidates ``ArxivMonitor._to_record`` and the
inline import of that static method in ``MultiProviderMonitor._resolve_and_register``.

H-C3: ``build_topic`` consolidates ``ArxivMonitor._build_topic`` and
``MultiProviderMonitor._build_topic_for_query`` into one canonical impl.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.models.config.core import ResearchTopic, TimeframeRecent, TimeframeType
from src.models.paper import PaperMetadata
from src.services.intelligence.models.monitoring import PaperSource
from src.services.intelligence.monitoring.models import (
    MAX_POLL_HOURS,
    MonitoringPaperRecord,
)


def to_paper_record(
    paper: PaperMetadata, *, is_new: bool, source: PaperSource
) -> MonitoringPaperRecord:
    """Convert a :class:`PaperMetadata` into a :class:`MonitoringPaperRecord`.

    ``PaperMetadata.url`` and ``open_access_pdf`` are Pydantic ``HttpUrl``
    objects; ``MonitoringPaperRecord`` stores plain strings. ``str()``
    serialisation is correct here — Pydantic's ``HttpUrl`` coerces cleanly
    to the canonical URL string.

    Args:
        paper: Source paper metadata from a discovery provider.
        is_new: ``True`` if the paper was not yet known to the registry
            before this cycle.
        source: Discovery provider this paper came from (issue #141).
            Required keyword arg so callers must explicitly thread the
            actual provider through — never falls back to a hardcoded
            default (which is what #141 is fixing).

    Returns:
        A ``MonitoringPaperRecord`` ready to be appended to
        ``MonitoringRun.papers``.
    """
    published: Optional[datetime] = paper.publication_date
    return MonitoringPaperRecord(
        paper_id=paper.paper_id,
        title=paper.title,
        url=str(paper.url) if paper.url else None,
        pdf_url=str(paper.open_access_pdf) if paper.open_access_pdf else None,
        published_at=published,
        is_new=is_new,
        source=source,
    )


def build_topic(query: str, poll_interval_hours: int) -> ResearchTopic:
    """Construct a :class:`ResearchTopic` for a given query and interval.

    The ``TimeframeRecent`` value pattern is ``\\d+[hd]``, with a
    ``MAX_POLL_HOURS`` cap (~30 days) enforced by the model's
    ``validate_recent_format``. We clamp ``poll_interval_hours`` to that
    ceiling here to avoid a validation error mid-cycle.

    Args:
        query: The search query string (already expanded / validated by
            the caller).
        poll_interval_hours: The subscription's polling interval; used as
            the look-back window. Values above ``MAX_POLL_HOURS`` are
            silently clamped.

    Returns:
        A ``ResearchTopic`` ready to be passed to a
        ``DiscoveryProvider.search`` call.
    """
    hours = min(poll_interval_hours, MAX_POLL_HOURS)
    timeframe = TimeframeRecent(
        type=TimeframeType.RECENT,
        value=f"{hours}h",
    )
    return ResearchTopic(query=query, timeframe=timeframe)

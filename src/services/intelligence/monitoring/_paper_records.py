"""Shared helpers for constructing monitoring paper records and topics.

Extracted from :class:`ArxivMonitor` and :class:`MultiProviderMonitor` so
neither monitor duplicates the same DTO-building and topic-building logic.

H-C1: ``to_paper_record`` consolidates ``ArxivMonitor._to_record`` and the
inline import of that static method in ``MultiProviderMonitor._resolve_and_register``.

H-C3: ``build_topic`` consolidates ``ArxivMonitor._build_topic`` and
``MultiProviderMonitor._build_topic_for_query`` into one canonical impl.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Union

from src.models.config.core import (
    ResearchTopic,
    TimeframeDateRange,
    TimeframeRecent,
    TimeframeType,
)
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


def build_topic(
    query: str,
    poll_interval_hours: int,
    *,
    time_window: Optional[tuple[date, date]] = None,
    max_papers: Optional[int] = None,
) -> ResearchTopic:
    """Construct a :class:`ResearchTopic` for a given query and interval.

    When ``time_window`` is provided (a ``(since, until)`` date pair), the
    topic's timeframe is set to a :class:`TimeframeDateRange` spanning that
    explicit window.  This is used by the backfill step so each backfill
    cycle searches the historical window it is assigned rather than
    re-fetching the same fresh-feed window derived from
    ``poll_interval_hours``.

    When ``time_window`` is ``None`` (the default — normal fresh-feed path),
    the timeframe is a :class:`TimeframeRecent` window derived from
    ``poll_interval_hours`` as before.

    The ``TimeframeRecent`` value pattern is ``\\d+[hd]``, with a
    ``MAX_POLL_HOURS`` cap (~30 days) enforced by the model's
    ``validate_recent_format``. We clamp ``poll_interval_hours`` to that
    ceiling here to avoid a validation error mid-cycle.

    When ``max_papers`` is provided it is passed as
    :attr:`ResearchTopic.max_papers` so the discovery provider never
    fetches more than the caller's budget (H-2). When ``None`` the
    ``ResearchTopic`` default (50) applies.

    Args:
        query: The search query string (already expanded / validated by
            the caller).
        poll_interval_hours: The subscription's polling interval; used as
            the look-back window for the default fresh-feed path. Values
            above ``MAX_POLL_HOURS`` are silently clamped.
        time_window: Optional ``(since_date, until_date)`` pair that
            overrides the ``poll_interval_hours``-derived window.
            Callers that need an explicit historical range (backfill)
            pass this; the fresh-feed path leaves it ``None``.
        max_papers: Optional provider-level paper cap injected into
            :attr:`ResearchTopic.max_papers` (H-2). When ``None`` the
            model's default of 50 is used.

    Returns:
        A ``ResearchTopic`` ready to be passed to a
        ``DiscoveryProvider.search`` call.
    """
    timeframe: Union[TimeframeDateRange, TimeframeRecent]
    if time_window is not None:
        since, until = time_window
        timeframe = TimeframeDateRange(
            type=TimeframeType.DATE_RANGE,
            start_date=since,
            end_date=until,
        )
    else:
        hours = min(poll_interval_hours, MAX_POLL_HOURS)
        timeframe = TimeframeRecent(
            type=TimeframeType.RECENT,
            value=f"{hours}h",
        )
    kwargs: dict = {"query": query, "timeframe": timeframe}
    if max_papers is not None:
        kwargs["max_papers"] = max_papers
    return ResearchTopic(**kwargs)

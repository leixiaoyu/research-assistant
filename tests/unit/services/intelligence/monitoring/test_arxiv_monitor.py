"""Tests for ``ArxivMonitor`` (Milestone 9.1).

All ArXiv HTTP traffic is mocked at the ``ArxivProvider.search`` boundary —
no live network calls are made.

Covers:
- Constructor validation (max_papers_per_cycle bounds)
- Skip behavior for paused / non-arxiv subscriptions
- Topic construction from subscription (poll_interval clamping)
- Topic-slug derivation
- Provider-error path (search raises) → FAILED run
- Per-cycle paper cap (post-fetch truncation)
- Dedup via registry: matched papers go to ``deduplicated_papers``
- New papers registered via ``register_paper(discovery_only=True)``
- Identity-resolution failure → PARTIAL run
- Registry-write failure → PARTIAL run
- Empty result set → SUCCESS run with zero counts
- ``_to_record`` URL stringification
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.config.core import ResearchTopic, TimeframeRecent, TimeframeType
from src.models.paper import Author, PaperMetadata
from src.models.registry import IdentityMatch, RegistryEntry
from src.services.intelligence.monitoring.arxiv_monitor import (
    ArxivMonitor,
    ArxivMonitorResult,
)
from src.services.intelligence.monitoring.models import (
    MAX_PAPERS_PER_CYCLE,
    MonitoringRunStatus,
    ResearchSubscription,
    SubscriptionStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paper(
    *,
    paper_id: str = "2301.12345",
    title: str = "A Paper",
    url: str = "https://arxiv.org/abs/2301.12345",
    pdf: str | None = "https://arxiv.org/pdf/2301.12345",
    pub_date: datetime | None = None,
) -> PaperMetadata:
    return PaperMetadata(
        paper_id=paper_id,
        title=title,
        abstract="abstract",
        url=url,  # type: ignore[arg-type]
        open_access_pdf=pdf,  # type: ignore[arg-type]
        authors=[Author(name="Alice")],
        year=2024,
        publication_date=pub_date or datetime(2024, 1, 1, tzinfo=timezone.utc),
        venue="ArXiv",
    )


def _make_subscription(
    *,
    subscription_id: str = "sub-test",
    poll_interval_hours: int = 6,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> ResearchSubscription:
    return ResearchSubscription(
        subscription_id=subscription_id,
        user_id="alice",
        name="Sub",
        query="tree of thoughts",
        poll_interval_hours=poll_interval_hours,
        status=status,
    )


def _make_provider(papers: list[PaperMetadata] | None = None) -> MagicMock:
    """Build a mocked ArxivProvider whose ``search`` returns ``papers``."""
    provider = MagicMock()
    provider.search = AsyncMock(return_value=papers or [])
    return provider


def _make_registry(
    *,
    matches: dict[str, IdentityMatch] | None = None,
    raise_on_resolve: Exception | None = None,
    raise_on_register: Exception | None = None,
) -> MagicMock:
    """Build a mocked RegistryService.

    ``matches`` maps a paper_id to the IdentityMatch returned by
    ``resolve_identity``. Default is "no match" (new paper).
    """
    matches = matches or {}
    registry = MagicMock()

    def resolve(paper: PaperMetadata) -> IdentityMatch:
        if raise_on_resolve is not None:
            raise raise_on_resolve
        return matches.get(paper.paper_id, IdentityMatch(matched=False))

    def register(**kwargs: Any) -> RegistryEntry:
        if raise_on_register is not None:
            raise raise_on_register
        return RegistryEntry(
            title_normalized=kwargs["paper"].title.lower(),
            extraction_target_hash="sha256:test",
        )

    registry.resolve_identity = MagicMock(side_effect=resolve)
    registry.register_paper = MagicMock(side_effect=register)
    return registry


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestArxivMonitorInit:
    def test_init_default_cap(self) -> None:
        monitor = ArxivMonitor(_make_provider(), _make_registry())
        assert monitor._max_papers_per_cycle == MAX_PAPERS_PER_CYCLE

    def test_init_custom_cap(self) -> None:
        monitor = ArxivMonitor(
            _make_provider(), _make_registry(), max_papers_per_cycle=10
        )
        assert monitor._max_papers_per_cycle == 10

    def test_init_zero_cap_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            ArxivMonitor(_make_provider(), _make_registry(), max_papers_per_cycle=0)

    def test_init_negative_cap_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            ArxivMonitor(_make_provider(), _make_registry(), max_papers_per_cycle=-1)

    def test_init_above_global_cap_rejected(self) -> None:
        with pytest.raises(ValueError, match="cannot exceed"):
            ArxivMonitor(
                _make_provider(),
                _make_registry(),
                max_papers_per_cycle=MAX_PAPERS_PER_CYCLE + 1,
            )

    def test_init_custom_topic_slug_prefix(self) -> None:
        monitor = ArxivMonitor(
            _make_provider(), _make_registry(), topic_slug_prefix="custom"
        )
        sub = _make_subscription(subscription_id="sub-x")
        assert monitor._topic_slug(sub) == "custom-sub-x"


# ---------------------------------------------------------------------------
# Skip / eligibility
# ---------------------------------------------------------------------------


class TestEligibility:
    @pytest.mark.asyncio
    async def test_paused_subscription_skipped(self) -> None:
        provider = _make_provider()
        registry = _make_registry()
        monitor = ArxivMonitor(provider, registry)
        sub = _make_subscription(status=SubscriptionStatus.PAUSED)
        result = await monitor.check(sub)

        assert isinstance(result, ArxivMonitorResult)
        assert result.run.status is MonitoringRunStatus.SUCCESS
        assert result.run.papers_seen == 0
        assert result.new_papers == []
        assert result.deduplicated_papers == []
        # Provider must not have been called.
        provider.search.assert_not_awaited()

    def test_eligibility_checks_arxiv_in_sources(self) -> None:
        # The model normalizes sources to ArXiv, but we exercise the
        # static helper directly with an empty sources list to cover
        # the "no arxiv" branch.
        sub = _make_subscription()
        sub.sources = []  # bypass validator after construction
        assert ArxivMonitor._monitor_eligible(sub) is False

    def test_eligibility_paused(self) -> None:
        sub = _make_subscription(status=SubscriptionStatus.PAUSED)
        assert ArxivMonitor._monitor_eligible(sub) is False

    def test_eligibility_active(self) -> None:
        sub = _make_subscription()
        assert ArxivMonitor._monitor_eligible(sub) is True


# ---------------------------------------------------------------------------
# Topic construction
# ---------------------------------------------------------------------------


class TestBuildTopic:
    def test_build_topic_uses_poll_interval(self) -> None:
        sub = _make_subscription(poll_interval_hours=12)
        topic = ArxivMonitor._build_topic(sub)
        assert isinstance(topic, ResearchTopic)
        assert topic.query == sub.query
        assert isinstance(topic.timeframe, TimeframeRecent)
        assert topic.timeframe.type == TimeframeType.RECENT
        assert topic.timeframe.value == "12h"

    def test_build_topic_clamps_to_max(self) -> None:
        # ResearchSubscription caps poll_interval_hours at 24*7=168, well
        # below the provider's 720h ceiling. To exercise the clamp
        # branch we mutate the field directly post-construction.
        sub = _make_subscription()
        sub.poll_interval_hours = 1000  # bypass validator
        topic = ArxivMonitor._build_topic(sub)
        assert isinstance(topic.timeframe, TimeframeRecent)
        # Clamped to 720h.
        assert topic.timeframe.value == "720h"


# ---------------------------------------------------------------------------
# Provider error path
# ---------------------------------------------------------------------------


class TestProviderError:
    @pytest.mark.asyncio
    async def test_provider_raises_returns_failed_run(self) -> None:
        provider = _make_provider()
        provider.search = AsyncMock(side_effect=RuntimeError("boom"))
        registry = _make_registry()
        monitor = ArxivMonitor(provider, registry)

        result = await monitor.check(_make_subscription())

        assert result.run.status is MonitoringRunStatus.FAILED
        assert result.run.error is not None
        assert "arxiv_provider_error" in result.run.error
        assert "boom" in result.run.error
        assert result.run.finished_at is not None
        assert result.new_papers == []
        assert result.deduplicated_papers == []
        # Registry must not have been touched.
        registry.resolve_identity.assert_not_called()


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestPollHappyPath:
    @pytest.mark.asyncio
    async def test_empty_result_returns_success_run(self) -> None:
        monitor = ArxivMonitor(_make_provider([]), _make_registry())
        result = await monitor.check(_make_subscription())

        assert result.run.status is MonitoringRunStatus.SUCCESS
        assert result.run.papers_seen == 0
        assert result.run.papers_new == 0
        assert result.run.papers_deduplicated == 0
        assert result.new_papers == []
        assert result.deduplicated_papers == []

    @pytest.mark.asyncio
    async def test_all_new_papers_registered(self) -> None:
        papers = [
            _make_paper(paper_id="2301.0001"),
            _make_paper(paper_id="2301.0002"),
        ]
        registry = _make_registry()  # default: no matches
        monitor = ArxivMonitor(_make_provider(papers), registry)

        result = await monitor.check(_make_subscription())

        assert result.run.status is MonitoringRunStatus.SUCCESS
        assert result.run.papers_seen == 2
        assert result.run.papers_new == 2
        assert result.run.papers_deduplicated == 0
        assert [p.paper_id for p in result.new_papers] == [
            "2301.0001",
            "2301.0002",
        ]
        assert registry.register_paper.call_count == 2
        # Verify discovery_only=True was passed.
        for call in registry.register_paper.call_args_list:
            assert call.kwargs["discovery_only"] is True

    @pytest.mark.asyncio
    async def test_dedup_against_registry(self) -> None:
        papers = [
            _make_paper(paper_id="2301.0001"),
            _make_paper(paper_id="2301.0002"),
        ]
        # Mark the second as already-known.
        registry = _make_registry(
            matches={"2301.0002": IdentityMatch(matched=True, match_method="arxiv")}
        )
        monitor = ArxivMonitor(_make_provider(papers), registry)

        result = await monitor.check(_make_subscription())

        assert result.run.papers_seen == 2
        assert result.run.papers_new == 1
        assert result.run.papers_deduplicated == 1
        assert [p.paper_id for p in result.new_papers] == ["2301.0001"]
        assert [p.paper_id for p in result.deduplicated_papers] == ["2301.0002"]
        # Only the new paper hits register_paper.
        assert registry.register_paper.call_count == 1

    @pytest.mark.asyncio
    async def test_topic_slug_passed_to_registry(self) -> None:
        papers = [_make_paper()]
        registry = _make_registry()
        monitor = ArxivMonitor(_make_provider(papers), registry)
        sub = _make_subscription(subscription_id="sub-abc")

        await monitor.check(sub)

        registry.register_paper.assert_called_once_with(
            paper=registry.register_paper.call_args.kwargs["paper"],
            topic_slug="monitor-sub-abc",
            discovery_only=True,
        )


# ---------------------------------------------------------------------------
# Per-cycle paper cap
# ---------------------------------------------------------------------------


class TestPerCycleCap:
    @pytest.mark.asyncio
    async def test_cap_truncates_results(self) -> None:
        papers = [_make_paper(paper_id=f"2301.{i:04d}") for i in range(5)]
        monitor = ArxivMonitor(
            _make_provider(papers),
            _make_registry(),
            max_papers_per_cycle=3,
        )
        result = await monitor.check(_make_subscription())

        # Only the first 3 are processed.
        assert result.run.papers_seen == 3
        assert result.run.papers_new == 3
        assert [p.paper_id for p in result.new_papers] == [
            "2301.0000",
            "2301.0001",
            "2301.0002",
        ]


# ---------------------------------------------------------------------------
# Partial-failure paths
# ---------------------------------------------------------------------------


class TestPartialFailures:
    @pytest.mark.asyncio
    async def test_identity_resolution_error_yields_partial(self) -> None:
        papers = [_make_paper(paper_id="2301.0001")]
        registry = _make_registry(raise_on_resolve=RuntimeError("bad row"))
        monitor = ArxivMonitor(_make_provider(papers), registry)

        result = await monitor.check(_make_subscription())

        assert result.run.status is MonitoringRunStatus.PARTIAL
        assert result.run.error == "one_or_more_papers_failed"
        assert result.run.papers_seen == 1
        assert result.run.papers_new == 0
        assert result.run.papers_deduplicated == 0
        # No paper added to records (the loop ``continue``d before
        # appending).
        assert result.run.papers == []

    @pytest.mark.asyncio
    async def test_register_failure_yields_partial(self) -> None:
        papers = [_make_paper(paper_id="2301.0001")]
        registry = _make_registry(raise_on_register=RuntimeError("disk full"))
        monitor = ArxivMonitor(_make_provider(papers), registry)

        result = await monitor.check(_make_subscription())

        assert result.run.status is MonitoringRunStatus.PARTIAL
        assert result.run.error == "one_or_more_papers_failed"
        assert result.run.papers_seen == 1
        assert result.run.papers_new == 0
        assert result.new_papers == []

    @pytest.mark.asyncio
    async def test_partial_with_some_success(self) -> None:
        # First paper succeeds, second blows up on register.
        papers = [
            _make_paper(paper_id="2301.0001"),
            _make_paper(paper_id="2301.0002"),
        ]
        registry = MagicMock()
        registry.resolve_identity = MagicMock(return_value=IdentityMatch(matched=False))
        call_count = {"n": 0}

        def register_side_effect(**kwargs: Any) -> RegistryEntry:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return RegistryEntry(
                    title_normalized=kwargs["paper"].title.lower(),
                    extraction_target_hash="sha256:test",
                )
            raise RuntimeError("disk full")

        registry.register_paper = MagicMock(side_effect=register_side_effect)
        monitor = ArxivMonitor(_make_provider(papers), registry)

        result = await monitor.check(_make_subscription())

        assert result.run.status is MonitoringRunStatus.PARTIAL
        assert result.run.papers_seen == 2
        assert result.run.papers_new == 1
        # Only the first paper was added to the records list.
        assert [r.paper_id for r in result.run.papers] == ["2301.0001"]


# ---------------------------------------------------------------------------
# Record conversion
# ---------------------------------------------------------------------------


class TestToRecord:
    def test_to_record_with_urls(self) -> None:
        paper = _make_paper(
            paper_id="2301.0001",
            url="https://arxiv.org/abs/2301.0001",
            pdf="https://arxiv.org/pdf/2301.0001",
        )
        rec = ArxivMonitor._to_record(paper, is_new=True)
        # HttpUrl is stringified into a plain str for the DTO.
        assert isinstance(rec.url, str)
        assert rec.url.startswith("https://arxiv.org/abs/")
        assert isinstance(rec.pdf_url, str)
        assert rec.pdf_url.startswith("https://arxiv.org/pdf/")
        assert rec.is_new is True
        assert rec.published_at is not None

    def test_to_record_without_pdf(self) -> None:
        paper = _make_paper(pdf=None)
        rec = ArxivMonitor._to_record(paper, is_new=False)
        assert rec.pdf_url is None
        assert rec.is_new is False


# ---------------------------------------------------------------------------
# C-2: real-monitor tests for _paper_records.build_topic time_window→DateRange
# ---------------------------------------------------------------------------


class TestBuildTopicTimeWindowToDateRange:
    """C-2: Exercises _paper_records.py:108-109 through the real ArxivMonitor.

    These tests call monitor.check(sub, time_window=...) with stubbed
    providers and assert that the ResearchTopic seen by the provider has
    a TimeframeDateRange (not a TimeframeRecent) with the correct dates.
    The provider is patched at the search boundary; the monitor's internal
    build_topic call is exercised for real.
    """

    @pytest.mark.asyncio
    async def test_time_window_produces_timeframe_date_range(self) -> None:
        """When time_window is given, the provider sees a TimeframeDateRange.

        This exercises _paper_records.py:108-109 (the ``if time_window is
        not None:`` branch) through the real ArxivMonitor.check code path.
        """
        from datetime import date as date_t
        from src.models.config.core import TimeframeDateRange

        since = date_t(2025, 1, 1)
        until = date_t(2025, 1, 8)

        captured_topic: list = []

        async def capture_search(topic):  # type: ignore[override]
            captured_topic.append(topic)
            return []

        provider = MagicMock()
        provider.search = AsyncMock(side_effect=capture_search)
        registry = _make_registry()
        monitor = ArxivMonitor(provider, registry)
        sub = _make_subscription()

        await monitor.check(sub, time_window=(since, until))

        assert len(captured_topic) == 1, "provider.search must be called once"
        topic = captured_topic[0]
        assert isinstance(topic.timeframe, TimeframeDateRange), (
            f"Expected TimeframeDateRange, got {type(topic.timeframe).__name__}. "
            "C-2: _paper_records.py:108-109 must construct TimeframeDateRange "
            "when time_window is not None."
        )
        assert (
            topic.timeframe.start_date == since
        ), f"start_date should be {since}, got {topic.timeframe.start_date}"
        assert (
            topic.timeframe.end_date == until
        ), f"end_date should be {until}, got {topic.timeframe.end_date}"

    @pytest.mark.asyncio
    async def test_time_window_none_produces_timeframe_recent(self) -> None:
        """When time_window is None, the provider sees a TimeframeRecent.

        Regression guard: confirms that the fresh-feed path still uses
        TimeframeRecent — the C-2 fix must not break the default path.
        """
        from src.models.config.core import TimeframeRecent

        captured_topic: list = []

        async def capture_search(topic):  # type: ignore[override]
            captured_topic.append(topic)
            return []

        provider = MagicMock()
        provider.search = AsyncMock(side_effect=capture_search)
        registry = _make_registry()
        monitor = ArxivMonitor(provider, registry)
        sub = _make_subscription(poll_interval_hours=12)

        await monitor.check(sub)  # no time_window

        assert len(captured_topic) == 1
        topic = captured_topic[0]
        assert isinstance(topic.timeframe, TimeframeRecent), (
            f"Expected TimeframeRecent for fresh-feed path, "
            f"got {type(topic.timeframe).__name__}"
        )
        assert topic.timeframe.value == "12h"

    @pytest.mark.asyncio
    async def test_time_window_dates_not_swapped(self) -> None:
        """start_date / end_date must not be swapped in the built topic.

        This would catch a ``TimeframeDateRange(start_date=until,
        end_date=since)`` bug (field-swap regression).
        """
        from datetime import date as date_t
        from src.models.config.core import TimeframeDateRange

        since = date_t(2025, 3, 1)
        until = date_t(2025, 3, 8)

        captured_topic: list = []

        async def capture_search(topic):  # type: ignore[override]
            captured_topic.append(topic)
            return []

        provider = MagicMock()
        provider.search = AsyncMock(side_effect=capture_search)
        registry = _make_registry()
        monitor = ArxivMonitor(provider, registry)
        sub = _make_subscription()

        await monitor.check(sub, time_window=(since, until))

        topic = captured_topic[0]
        tf = topic.timeframe
        assert isinstance(tf, TimeframeDateRange)
        # If dates were swapped, start > end, which Pydantic would reject;
        # explicitly assert the correct mapping so intent is clear.
        assert tf.start_date == since
        assert tf.end_date == until
        assert tf.start_date < tf.end_date

    @pytest.mark.asyncio
    async def test_max_papers_passed_to_topic(self) -> None:
        """When max_papers is given, the provider topic carries that cap (H-2).

        Exercises _paper_records.py:131 (the ``if max_papers is not None:``
        branch in build_topic) which was previously uncovered.
        """
        captured_topic: list = []

        async def capture_search(topic):  # type: ignore[override]
            captured_topic.append(topic)
            return []

        provider = MagicMock()
        provider.search = AsyncMock(side_effect=capture_search)
        registry = _make_registry()
        monitor = ArxivMonitor(provider, registry)
        sub = _make_subscription()

        await monitor.check(sub, max_papers=25)

        assert len(captured_topic) == 1
        topic = captured_topic[0]
        assert topic.max_papers == 25, (
            f"ResearchTopic.max_papers must be 25 when max_papers=25 is "
            f"passed, got {topic.max_papers}. "
            "H-2: provider fetch cap must come from the caller, not default."
        )

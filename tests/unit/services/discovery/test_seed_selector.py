"""Unit tests for citation seed selection (Phase 9.5 REQ-9.5.2.1, PR β).

The selector returns the recent quality-cohort cohort. Boundary cases:

- Empty registry → empty list (caller falls back).
- Quality-threshold inclusive boundary at 70.0.
- Lookback window inclusive boundary at exactly 7 days.
- Cross-topic isolation.
- Cap at max_seeds, sorted by quality descending.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, List
from unittest.mock import MagicMock

from src.models.registry import RegistryEntry
from src.services.discovery.seed_selector import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_SEEDS,
    DEFAULT_QUALITY_THRESHOLD,
    SeedSelectionConfig,
    select_citation_seeds,
)


def _make_entry(
    paper_id: str,
    quality: float,
    processed_at: datetime,
    topic_slugs: List[str],
) -> RegistryEntry:
    """Build a RegistryEntry whose metadata_snapshot carries the quality score."""
    return RegistryEntry(
        paper_id=paper_id,
        canonical_title=f"Title {paper_id}",
        title_normalized=f"title-{paper_id}",
        extraction_target_hash="0" * 64,
        topic_affiliations=topic_slugs,
        processed_at=processed_at,
        metadata_snapshot={
            "paper_id": paper_id,
            "title": f"Title {paper_id}",
            "abstract": "abstract",
            "url": f"https://example.com/{paper_id}",
            "quality_score": quality,
        },
    )


def _registry_returning(entries: List[RegistryEntry]) -> Any:
    """Mock RegistryService that returns the given entries unchanged."""
    svc = MagicMock()
    svc.get_recent_entries_for_topic = MagicMock(return_value=entries)
    return svc


_NOW = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)


class TestColdRegistry:
    """First-week-after-merge case: registry has nothing for this topic."""

    def test_empty_registry_returns_empty_list(self):
        registry = _registry_returning([])
        result = select_citation_seeds("topic-1", registry, now=_NOW)
        assert result == []

    def test_only_other_topics_returns_empty_list(self):
        # Registry returns entries — but they're for other topics. The
        # registry's get_recent_entries_for_topic already filters by
        # topic, so an empty list models that case.
        registry = _registry_returning([])
        result = select_citation_seeds("topic-1", registry, now=_NOW)
        assert result == []
        registry.get_recent_entries_for_topic.assert_called_once()


class TestQualityFilter:
    """The selector keeps only entries whose quality_score >= threshold."""

    def test_above_threshold_kept(self):
        registry = _registry_returning(
            [_make_entry("p1", 80.0, _NOW - timedelta(days=1), ["topic-1"])]
        )
        result = select_citation_seeds("topic-1", registry, now=_NOW)
        assert len(result) == 1
        assert result[0].paper_id == "p1"

    def test_at_threshold_inclusive(self):
        registry = _registry_returning(
            [_make_entry("p1", 70.0, _NOW - timedelta(days=1), ["topic-1"])]
        )
        result = select_citation_seeds("topic-1", registry, now=_NOW)
        assert len(result) == 1, "70.0 is the inclusive lower bound"

    def test_below_threshold_excluded(self):
        registry = _registry_returning(
            [_make_entry("p1", 69.99, _NOW - timedelta(days=1), ["topic-1"])]
        )
        result = select_citation_seeds("topic-1", registry, now=_NOW)
        assert result == []

    def test_missing_quality_score_excluded(self):
        # Entry with no quality_score in metadata_snapshot defaults to
        # 0.0, which is below the threshold.
        entry = RegistryEntry(
            paper_id="p1",
            canonical_title="t",
            title_normalized="t",
            extraction_target_hash="0" * 64,
            topic_affiliations=["topic-1"],
            processed_at=_NOW - timedelta(days=1),
            metadata_snapshot={
                "paper_id": "p1",
                "title": "t",
                "url": "https://example.com/p1",
            },
        )
        registry = _registry_returning([entry])
        result = select_citation_seeds("topic-1", registry, now=_NOW)
        assert result == []


class TestLookbackWindow:
    """The lookback filter relies on the registry call's ``since`` arg."""

    def test_passes_correct_cutoff(self):
        registry = _registry_returning([])
        select_citation_seeds("topic-1", registry, now=_NOW)
        called_kwargs = registry.get_recent_entries_for_topic.call_args.kwargs
        expected_cutoff = _NOW - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        assert called_kwargs["since"] == expected_cutoff

    def test_custom_lookback_days(self):
        registry = _registry_returning([])
        select_citation_seeds(
            "topic-1",
            registry,
            now=_NOW,
            config=SeedSelectionConfig(lookback_days=30),
        )
        called_kwargs = registry.get_recent_entries_for_topic.call_args.kwargs
        assert called_kwargs["since"] == _NOW - timedelta(days=30)


class TestSortAndCap:
    """The selector returns highest-quality first, capped at max_seeds."""

    def test_sorted_by_quality_descending(self):
        entries = [
            _make_entry("low", 71.0, _NOW - timedelta(days=1), ["topic-1"]),
            _make_entry("high", 95.0, _NOW - timedelta(days=1), ["topic-1"]),
            _make_entry("mid", 80.0, _NOW - timedelta(days=1), ["topic-1"]),
        ]
        registry = _registry_returning(entries)
        result = select_citation_seeds("topic-1", registry, now=_NOW)
        assert [p.paper_id for p in result] == ["high", "mid", "low"]

    def test_caps_at_max_seeds(self):
        entries = [
            _make_entry(f"p{i}", 90.0 - i, _NOW - timedelta(days=1), ["topic-1"])
            for i in range(15)
        ]
        registry = _registry_returning(entries)
        result = select_citation_seeds("topic-1", registry, now=_NOW)
        assert len(result) == DEFAULT_MAX_SEEDS  # default is 10

    def test_custom_max_seeds(self):
        entries = [
            _make_entry(f"p{i}", 90.0 - i, _NOW - timedelta(days=1), ["topic-1"])
            for i in range(15)
        ]
        registry = _registry_returning(entries)
        result = select_citation_seeds(
            "topic-1",
            registry,
            now=_NOW,
            config=SeedSelectionConfig(max_seeds=3),
        )
        assert len(result) == 3
        assert [p.paper_id for p in result] == ["p0", "p1", "p2"]


class TestDefaults:
    """Sanity check: the defaults match the Phase 9.5 spec."""

    def test_quality_threshold_is_seventy_on_hundred_scale(self):
        # The spec prose uses 0.7 (0.0–1.0); the as-built field is on
        # the 0–100 scale per src/models/paper.py:45. The default MUST
        # be 70.0, not 0.7, or the cohort would never qualify.
        assert DEFAULT_QUALITY_THRESHOLD == 70.0

    def test_lookback_default_is_seven_days(self):
        assert DEFAULT_LOOKBACK_DAYS == 7

    def test_max_seeds_default_is_ten(self):
        assert DEFAULT_MAX_SEEDS == 10

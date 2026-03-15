"""Unit tests for TimeframeResolver (Phase 7.1).

Tests incremental discovery timeframe resolution logic.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock

from src.utils.timeframe_resolver import TimeframeResolver
from src.models.discovery import ResolvedTimeframe
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    TimeframeSinceYear,
    TimeframeDateRange,
    ProviderType,
)


@pytest.fixture
def mock_catalog_service():
    """Mock CatalogService for testing."""
    mock = Mock()
    mock.get_last_discovery_at = Mock(return_value=None)
    mock.set_last_discovery_at = Mock()
    mock.detect_query_change = Mock(return_value=False)
    return mock


@pytest.fixture
def resolver(mock_catalog_service):
    """TimeframeResolver instance with mocked catalog service."""
    return TimeframeResolver(mock_catalog_service)


@pytest.fixture
def topic_recent():
    """ResearchTopic with recent timeframe."""
    return ResearchTopic(
        query="test query",
        provider=ProviderType.ARXIV,
        timeframe=TimeframeRecent(type="recent", value="48h"),
        max_papers=50,
    )


@pytest.fixture
def topic_since_year():
    """ResearchTopic with since_year timeframe."""
    return ResearchTopic(
        query="test query",
        provider=ProviderType.ARXIV,
        timeframe=TimeframeSinceYear(type="since_year", value=2020),
        max_papers=50,
    )


@pytest.fixture
def topic_date_range():
    """ResearchTopic with date_range timeframe."""
    start = datetime(2025, 1, 1).date()
    end = datetime(2025, 1, 31).date()
    return ResearchTopic(
        query="test query",
        provider=ProviderType.ARXIV,
        timeframe=TimeframeDateRange(type="date_range", start_date=start, end_date=end),
        max_papers=50,
    )


class TestTimeframeResolverFirstRun:
    """Test behavior on first run (no previous timestamp)."""

    def test_first_run_recent_timeframe(
        self, resolver, mock_catalog_service, topic_recent
    ):
        """First run should use config timeframe (recent)."""
        # Setup: no previous timestamp
        mock_catalog_service.get_last_discovery_at.return_value = None
        mock_catalog_service.detect_query_change.return_value = False

        # Execute
        result = resolver.resolve(topic_recent, "test-topic")

        # Verify
        assert isinstance(result, ResolvedTimeframe)
        assert result.is_incremental is False
        assert result.overlap_buffer_hours == 0
        assert result.original_timeframe == {"type": "recent", "value": "48h"}

        # Should span last 48 hours
        now = datetime.utcnow()
        expected_start = now - timedelta(hours=48)
        assert abs((result.start_date - expected_start).total_seconds()) < 5
        assert abs((result.end_date - now).total_seconds()) < 5

    def test_first_run_since_year_timeframe(
        self, resolver, mock_catalog_service, topic_since_year
    ):
        """First run should use config timeframe (since_year)."""
        # Setup: no previous timestamp
        mock_catalog_service.get_last_discovery_at.return_value = None
        mock_catalog_service.detect_query_change.return_value = False

        # Execute
        result = resolver.resolve(topic_since_year, "test-topic")

        # Verify
        assert isinstance(result, ResolvedTimeframe)
        assert result.is_incremental is False
        assert result.overlap_buffer_hours == 0
        assert result.original_timeframe == {"type": "since_year", "value": 2020}

        # Should start from 2020-01-01
        assert result.start_date == datetime(2020, 1, 1)
        assert abs((result.end_date - datetime.utcnow()).total_seconds()) < 5

    def test_first_run_date_range_timeframe(
        self, resolver, mock_catalog_service, topic_date_range
    ):
        """First run should use config timeframe (date_range)."""
        # Setup: no previous timestamp
        mock_catalog_service.get_last_discovery_at.return_value = None
        mock_catalog_service.detect_query_change.return_value = False

        # Execute
        result = resolver.resolve(topic_date_range, "test-topic")

        # Verify
        assert isinstance(result, ResolvedTimeframe)
        assert result.is_incremental is False
        assert result.overlap_buffer_hours == 0
        assert "start_date" in result.original_timeframe
        assert "end_date" in result.original_timeframe

        # Should match configured range
        assert result.start_date == datetime(2025, 1, 1, 0, 0, 0)
        # datetime.max.time() includes microseconds, so check without them
        assert result.end_date.date() == datetime(2025, 1, 31).date()
        assert result.end_date.hour == 23
        assert result.end_date.minute == 59
        assert result.end_date.second == 59


class TestTimeframeResolverIncremental:
    """Test incremental discovery behavior."""

    def test_incremental_with_previous_timestamp(
        self, resolver, mock_catalog_service, topic_recent
    ):
        """Should use incremental timeframe when previous timestamp exists."""
        # Setup: previous discovery 24 hours ago
        last_discovery = datetime.utcnow() - timedelta(hours=24)
        mock_catalog_service.get_last_discovery_at.return_value = last_discovery
        mock_catalog_service.detect_query_change.return_value = False

        # Execute
        result = resolver.resolve(topic_recent, "test-topic")

        # Verify
        assert result.is_incremental is True
        assert result.overlap_buffer_hours == 1

        # Start should be last_discovery minus 1-hour buffer
        expected_start = last_discovery - timedelta(hours=1)
        assert abs((result.start_date - expected_start).total_seconds()) < 1
        assert abs((result.end_date - datetime.utcnow()).total_seconds()) < 5

    def test_incremental_with_overlap_buffer(
        self, resolver, mock_catalog_service, topic_recent
    ):
        """Incremental query should include 1-hour overlap buffer."""
        # Setup
        last_discovery = datetime(2025, 1, 20, 12, 0, 0)
        mock_catalog_service.get_last_discovery_at.return_value = last_discovery
        mock_catalog_service.detect_query_change.return_value = False

        # Execute
        result = resolver.resolve(topic_recent, "test-topic")

        # Verify buffer applied
        expected_start = datetime(2025, 1, 20, 11, 0, 0)  # 12:00 - 1 hour
        assert result.start_date == expected_start
        assert result.overlap_buffer_hours == 1

    def test_incremental_with_since_year_timeframe(
        self, resolver, mock_catalog_service, topic_since_year
    ):
        """Incremental mode should preserve since_year in original_timeframe."""
        last_discovery = datetime.utcnow() - timedelta(hours=24)
        mock_catalog_service.get_last_discovery_at.return_value = last_discovery
        mock_catalog_service.detect_query_change.return_value = False

        result = resolver.resolve(topic_since_year, "test-topic")

        # Should be incremental with original config preserved
        assert result.is_incremental is True
        assert result.original_timeframe["type"] == "since_year"
        assert result.original_timeframe["value"] == 2020

    def test_incremental_with_date_range_timeframe(
        self, resolver, mock_catalog_service, topic_date_range
    ):
        """Incremental mode should preserve date_range in original_timeframe."""
        last_discovery = datetime.utcnow() - timedelta(hours=24)
        mock_catalog_service.get_last_discovery_at.return_value = last_discovery
        mock_catalog_service.detect_query_change.return_value = False

        result = resolver.resolve(topic_date_range, "test-topic")

        # Should be incremental with original config preserved
        assert result.is_incremental is True
        assert result.original_timeframe["type"] == "date_range"
        assert "start_date" in result.original_timeframe
        assert "end_date" in result.original_timeframe
        assert result.original_timeframe["start_date"] == "2025-01-01"
        assert result.original_timeframe["end_date"] == "2025-01-31"

    def test_incremental_unknown_timeframe_handled(
        self, resolver, mock_catalog_service, topic_recent
    ):
        """Incremental mode should handle unknown timeframe gracefully."""
        last_discovery = datetime.utcnow() - timedelta(hours=24)
        mock_catalog_service.get_last_discovery_at.return_value = last_discovery
        mock_catalog_service.detect_query_change.return_value = False

        # Create unknown timeframe type
        class CustomTimeframe:
            def __init__(self):
                self.type = MagicMock()
                self.type.value = "custom"

        topic_recent.timeframe = CustomTimeframe()  # type: ignore

        result = resolver.resolve(topic_recent, "test-topic")

        # Should still create incremental timeframe with unknown type in metadata
        assert result.is_incremental is True
        assert result.original_timeframe["type"] == "custom"


class TestTimeframeResolverQueryChange:
    """Test behavior when query changes."""

    def test_query_change_resets_to_full_timeframe(
        self, resolver, mock_catalog_service, topic_recent
    ):
        """Query change should reset to full config timeframe."""
        # Setup: previous timestamp exists but query changed
        last_discovery = datetime.utcnow() - timedelta(hours=24)
        mock_catalog_service.get_last_discovery_at.return_value = last_discovery
        mock_catalog_service.detect_query_change.return_value = True

        # Execute
        result = resolver.resolve(topic_recent, "test-topic")

        # Verify: should use full timeframe, not incremental
        assert result.is_incremental is False
        assert result.overlap_buffer_hours == 0

        # Should span full 48 hours, not from last_discovery
        now = datetime.utcnow()
        expected_start = now - timedelta(hours=48)
        assert abs((result.start_date - expected_start).total_seconds()) < 5


class TestTimeframeResolverForceFullTimeframe:
    """Test force_full_timeframe flag."""

    def test_force_full_ignores_previous_timestamp(
        self, resolver, mock_catalog_service, topic_recent
    ):
        """force_full_timeframe should ignore previous timestamp."""
        # Setup: previous timestamp exists but force_full is True
        topic_recent.force_full_timeframe = True
        last_discovery = datetime.utcnow() - timedelta(hours=24)
        mock_catalog_service.get_last_discovery_at.return_value = last_discovery
        mock_catalog_service.detect_query_change.return_value = False

        # Execute
        result = resolver.resolve(topic_recent, "test-topic")

        # Verify: should use full timeframe
        assert result.is_incremental is False
        assert result.overlap_buffer_hours == 0

        # Should span full 48 hours
        now = datetime.utcnow()
        expected_start = now - timedelta(hours=48)
        assert abs((result.start_date - expected_start).total_seconds()) < 5

    def test_force_full_takes_precedence_over_query_change(
        self, resolver, mock_catalog_service, topic_recent
    ):
        """force_full_timeframe should take precedence over all logic."""
        # Setup: force_full AND query changed
        topic_recent.force_full_timeframe = True
        mock_catalog_service.get_last_discovery_at.return_value = (
            datetime.utcnow() - timedelta(hours=24)
        )
        mock_catalog_service.detect_query_change.return_value = True

        # Execute
        result = resolver.resolve(topic_recent, "test-topic")

        # Verify: should still use full timeframe
        assert result.is_incremental is False


class TestTimeframeResolverUpdateLastRun:
    """Test update_last_run functionality."""

    def test_update_last_run_sets_timestamp(self, resolver, mock_catalog_service):
        """update_last_run should call catalog service."""
        timestamp = datetime(2025, 1, 20, 15, 30, 0)

        # Execute
        resolver.update_last_run("test-topic", timestamp)

        # Verify
        mock_catalog_service.set_last_discovery_at.assert_called_once_with(
            "test-topic", timestamp
        )

    def test_update_last_run_with_current_time(self, resolver, mock_catalog_service):
        """update_last_run should work with current timestamp."""
        now = datetime.utcnow()

        # Execute
        resolver.update_last_run("test-topic", now)

        # Verify
        mock_catalog_service.set_last_discovery_at.assert_called_once()
        call_args = mock_catalog_service.set_last_discovery_at.call_args
        assert call_args[0][0] == "test-topic"
        assert abs((call_args[0][1] - now).total_seconds()) < 1


class TestTimeframeResolverTimeframeTypes:
    """Test all timeframe type parsing."""

    def test_recent_hours_timeframe(self, resolver, mock_catalog_service):
        """Should parse hour-based recent timeframes."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(type="recent", value="72h"),
            max_papers=50,
        )
        mock_catalog_service.get_last_discovery_at.return_value = None
        mock_catalog_service.detect_query_change.return_value = False

        result = resolver.resolve(topic, "test-topic")

        # Should span 72 hours
        now = datetime.utcnow()
        expected_start = now - timedelta(hours=72)
        assert abs((result.start_date - expected_start).total_seconds()) < 5

    def test_recent_days_timeframe(self, resolver, mock_catalog_service):
        """Should parse day-based recent timeframes."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(type="recent", value="7d"),
            max_papers=50,
        )
        mock_catalog_service.get_last_discovery_at.return_value = None
        mock_catalog_service.detect_query_change.return_value = False

        result = resolver.resolve(topic, "test-topic")

        # Should span 7 days
        now = datetime.utcnow()
        expected_start = now - timedelta(days=7)
        assert abs((result.start_date - expected_start).total_seconds()) < 5

    def test_invalid_timeframe_unit_raises_error(self, resolver, mock_catalog_service):
        """Should raise error for invalid timeframe unit."""
        # Create a valid topic first
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(type="recent", value="48h"),
            max_papers=50,
        )

        # Monkey-patch the value to bypass Pydantic validation
        # This simulates a corrupt/invalid state that could occur from
        # external data manipulation or future code changes
        topic.timeframe.value = "48x"  # type: ignore

        mock_catalog_service.get_last_discovery_at.return_value = None
        mock_catalog_service.detect_query_change.return_value = False

        # Should raise ValueError for invalid unit
        with pytest.raises(ValueError, match="Invalid timeframe unit"):
            resolver.resolve(topic, "test-topic")

    def test_unknown_timeframe_type_raises_error(self, resolver, mock_catalog_service):
        """Should raise error for unknown timeframe type."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(type="recent", value="48h"),
            max_papers=50,
        )

        # Replace with completely unknown type
        class UnknownTimeframe:
            def __init__(self):
                self.type = MagicMock()
                self.type.value = "unknown"

        topic.timeframe = UnknownTimeframe()  # type: ignore

        mock_catalog_service.get_last_discovery_at.return_value = None
        mock_catalog_service.detect_query_change.return_value = False

        # Should raise ValueError for unknown type
        with pytest.raises(ValueError, match="Unknown timeframe type"):
            resolver.resolve(topic, "test-topic")


class TestTimeframeResolverEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_recent_last_discovery(
        self, resolver, mock_catalog_service, topic_recent
    ):
        """Should handle very recent last discovery (minutes ago)."""
        last_discovery = datetime.utcnow() - timedelta(minutes=5)
        mock_catalog_service.get_last_discovery_at.return_value = last_discovery
        mock_catalog_service.detect_query_change.return_value = False

        result = resolver.resolve(topic_recent, "test-topic")

        # Should still apply 1-hour buffer
        assert result.is_incremental is True
        expected_start = last_discovery - timedelta(hours=1)
        assert abs((result.start_date - expected_start).total_seconds()) < 1

    def test_old_last_discovery(self, resolver, mock_catalog_service, topic_recent):
        """Should handle very old last discovery (years ago)."""
        last_discovery = datetime(2020, 1, 1, 0, 0, 0)
        mock_catalog_service.get_last_discovery_at.return_value = last_discovery
        mock_catalog_service.detect_query_change.return_value = False

        result = resolver.resolve(topic_recent, "test-topic")

        # Should use incremental from old timestamp
        assert result.is_incremental is True
        expected_start = datetime(2019, 12, 31, 23, 0, 0)  # 2020-01-01 minus 1 hour
        assert result.start_date == expected_start

    def test_original_timeframe_preserved(
        self, resolver, mock_catalog_service, topic_recent
    ):
        """Original timeframe config should be preserved in result."""
        mock_catalog_service.get_last_discovery_at.return_value = None
        mock_catalog_service.detect_query_change.return_value = False

        result = resolver.resolve(topic_recent, "test-topic")

        # Verify original config is preserved
        assert result.original_timeframe is not None
        assert result.original_timeframe["type"] == "recent"
        assert result.original_timeframe["value"] == "48h"

    def test_original_timeframe_preserved_incremental(
        self, resolver, mock_catalog_service, topic_recent
    ):
        """Original timeframe should be preserved even in incremental mode."""
        last_discovery = datetime.utcnow() - timedelta(hours=24)
        mock_catalog_service.get_last_discovery_at.return_value = last_discovery
        mock_catalog_service.detect_query_change.return_value = False

        result = resolver.resolve(topic_recent, "test-topic")

        # Verify original config is preserved in incremental mode
        assert result.original_timeframe is not None
        assert result.original_timeframe["type"] == "recent"
        assert result.original_timeframe["value"] == "48h"


class TestTimeframeResolverIntegration:
    """Integration-style tests with realistic scenarios."""

    def test_typical_daily_schedule_workflow(
        self, resolver, mock_catalog_service, topic_recent
    ):
        """Simulate typical daily scheduled discovery workflow."""
        # Day 1: First run
        mock_catalog_service.get_last_discovery_at.return_value = None
        mock_catalog_service.detect_query_change.return_value = False

        result_day1 = resolver.resolve(topic_recent, "daily-topic")
        assert result_day1.is_incremental is False

        # Simulate successful completion
        day1_timestamp = datetime(2025, 1, 20, 0, 0, 0)
        resolver.update_last_run("daily-topic", day1_timestamp)

        # Day 2: Incremental run
        mock_catalog_service.get_last_discovery_at.return_value = day1_timestamp

        result_day2 = resolver.resolve(topic_recent, "daily-topic")
        assert result_day2.is_incremental is True
        expected_start = day1_timestamp - timedelta(hours=1)
        assert result_day2.start_date == expected_start

    def test_query_modification_resets_schedule(
        self, resolver, mock_catalog_service, topic_recent
    ):
        """Changing query should reset incremental discovery."""
        # Initial run
        last_discovery = datetime(2025, 1, 20, 0, 0, 0)
        mock_catalog_service.get_last_discovery_at.return_value = last_discovery
        mock_catalog_service.detect_query_change.return_value = False

        result1 = resolver.resolve(topic_recent, "test-topic")
        assert result1.is_incremental is True

        # Query changes
        mock_catalog_service.detect_query_change.return_value = True

        result2 = resolver.resolve(topic_recent, "test-topic")
        assert result2.is_incremental is False  # Reset to full

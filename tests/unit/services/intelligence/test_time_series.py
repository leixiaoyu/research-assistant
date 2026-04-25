"""Tests for time series storage.

Tests cover:
- TimeSeriesStore CRUD operations
- Range queries
- Aggregation functions
- Velocity and acceleration computation
- Edge cases
"""

import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.services.intelligence.storage.time_series import (
    AggregationPeriod,
    TimeSeriesPoint,
    TimeSeriesStore,
)


@pytest.fixture
def temp_db() -> Path:
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        return Path(f.name)


@pytest.fixture
def ts_store(temp_db: Path) -> TimeSeriesStore:
    """Create an initialized time series store."""
    store = TimeSeriesStore(temp_db)
    store.initialize()
    return store


class TestTimeSeriesStoreInit:
    """Tests for TimeSeriesStore initialization."""

    def test_init_without_initialize_raises(self, temp_db: Path) -> None:
        """Test operations fail before initialize() is called."""
        store = TimeSeriesStore(temp_db)
        with pytest.raises(RuntimeError, match="not initialized"):
            store.get_point("test", date.today(), "metric")

    def test_initialize_idempotent(self, temp_db: Path) -> None:
        """Test initialize can be called multiple times."""
        store = TimeSeriesStore(temp_db)
        store.initialize()
        store.initialize()  # Should not raise


class TestPointOperations:
    """Tests for time series point CRUD."""

    def test_add_point_minimal(self, ts_store: TimeSeriesStore) -> None:
        """Test adding a point with minimal fields."""
        point = ts_store.add_point(
            series_id="topic:llm",
            period=date(2024, 1, 15),
            metric_name="paper_count",
            value=42.0,
        )

        assert point.series_id == "topic:llm"
        assert point.period == date(2024, 1, 15)
        assert point.metric_name == "paper_count"
        assert point.value == 42.0
        assert point.metadata == {}

    def test_add_point_with_metadata(self, ts_store: TimeSeriesStore) -> None:
        """Test adding a point with metadata."""
        point = ts_store.add_point(
            series_id="topic:llm",
            period=date(2024, 1, 15),
            metric_name="paper_count",
            value=42.0,
            metadata={"source": "arxiv", "query": "llm"},
        )

        assert point.metadata["source"] == "arxiv"
        assert point.metadata["query"] == "llm"

    def test_add_point_upsert(self, ts_store: TimeSeriesStore) -> None:
        """Test adding point replaces existing."""
        ts_store.add_point("topic:llm", date(2024, 1, 1), "count", 10.0)
        ts_store.add_point("topic:llm", date(2024, 1, 1), "count", 20.0)

        point = ts_store.get_point("topic:llm", date(2024, 1, 1), "count")
        assert point is not None
        assert point.value == 20.0

    def test_get_point_exists(self, ts_store: TimeSeriesStore) -> None:
        """Test getting existing point."""
        ts_store.add_point("topic:test", date(2024, 1, 1), "metric", 100.0)

        point = ts_store.get_point("topic:test", date(2024, 1, 1), "metric")

        assert point is not None
        assert point.value == 100.0

    def test_get_point_not_found(self, ts_store: TimeSeriesStore) -> None:
        """Test getting non-existent point."""
        point = ts_store.get_point("nonexistent", date(2024, 1, 1), "metric")
        assert point is None

    def test_add_points_batch(self, ts_store: TimeSeriesStore) -> None:
        """Test batch adding points."""
        points = [
            TimeSeriesPoint(
                series_id="topic:test",
                period=date(2024, 1, i),
                metric_name="count",
                value=float(i),
                metadata={},
            )
            for i in range(1, 11)
        ]

        count = ts_store.add_points_batch(points)

        assert count == 10

        # Verify some points
        p1 = ts_store.get_point("topic:test", date(2024, 1, 1), "count")
        assert p1 is not None
        assert p1.value == 1.0

        p10 = ts_store.get_point("topic:test", date(2024, 1, 10), "count")
        assert p10 is not None
        assert p10.value == 10.0

    def test_add_points_batch_empty(self, ts_store: TimeSeriesStore) -> None:
        """Test batch adding empty list."""
        count = ts_store.add_points_batch([])
        assert count == 0


class TestRangeQueries:
    """Tests for range queries."""

    def test_get_range_single_point(self, ts_store: TimeSeriesStore) -> None:
        """Test range query with single point."""
        ts_store.add_point("topic:test", date(2024, 1, 15), "count", 50.0)

        points = ts_store.get_range(
            "topic:test", "count", date(2024, 1, 1), date(2024, 1, 31)
        )

        assert len(points) == 1
        assert points[0].value == 50.0

    def test_get_range_multiple_points(self, ts_store: TimeSeriesStore) -> None:
        """Test range query with multiple points."""
        for day in range(1, 11):
            ts_store.add_point("topic:test", date(2024, 1, day), "count", float(day))

        points = ts_store.get_range(
            "topic:test", "count", date(2024, 1, 1), date(2024, 1, 5)
        )

        assert len(points) == 5
        # Should be ordered by period
        assert points[0].period == date(2024, 1, 1)
        assert points[4].period == date(2024, 1, 5)

    def test_get_range_empty(self, ts_store: TimeSeriesStore) -> None:
        """Test range query with no matching points."""
        points = ts_store.get_range(
            "nonexistent", "count", date(2024, 1, 1), date(2024, 1, 31)
        )
        assert len(points) == 0

    def test_get_range_filters_series(self, ts_store: TimeSeriesStore) -> None:
        """Test range query filters by series ID."""
        ts_store.add_point("topic:a", date(2024, 1, 1), "count", 10.0)
        ts_store.add_point("topic:b", date(2024, 1, 1), "count", 20.0)

        points = ts_store.get_range(
            "topic:a", "count", date(2024, 1, 1), date(2024, 1, 31)
        )

        assert len(points) == 1
        assert points[0].series_id == "topic:a"

    def test_get_range_filters_metric(self, ts_store: TimeSeriesStore) -> None:
        """Test range query filters by metric name."""
        ts_store.add_point("topic:test", date(2024, 1, 1), "count", 10.0)
        ts_store.add_point("topic:test", date(2024, 1, 1), "citations", 100.0)

        points = ts_store.get_range(
            "topic:test", "count", date(2024, 1, 1), date(2024, 1, 31)
        )

        assert len(points) == 1
        assert points[0].metric_name == "count"


class TestLatestQueries:
    """Tests for latest point queries."""

    def test_get_latest_single(self, ts_store: TimeSeriesStore) -> None:
        """Test getting latest single point."""
        for day in range(1, 11):
            ts_store.add_point("topic:test", date(2024, 1, day), "count", float(day))

        points = ts_store.get_latest("topic:test", "count", count=1)

        assert len(points) == 1
        assert points[0].period == date(2024, 1, 10)
        assert points[0].value == 10.0

    def test_get_latest_multiple(self, ts_store: TimeSeriesStore) -> None:
        """Test getting multiple latest points."""
        for day in range(1, 11):
            ts_store.add_point("topic:test", date(2024, 1, day), "count", float(day))

        points = ts_store.get_latest("topic:test", "count", count=3)

        assert len(points) == 3
        # Should be in descending order
        assert points[0].period == date(2024, 1, 10)
        assert points[1].period == date(2024, 1, 9)
        assert points[2].period == date(2024, 1, 8)

    def test_get_latest_empty(self, ts_store: TimeSeriesStore) -> None:
        """Test getting latest from empty series."""
        points = ts_store.get_latest("nonexistent", "count", count=5)
        assert len(points) == 0


class TestAggregation:
    """Tests for time series aggregation."""

    def test_aggregate_daily(self, ts_store: TimeSeriesStore) -> None:
        """Test daily aggregation (essentially no aggregation)."""
        for day in range(1, 4):
            ts_store.add_point("topic:test", date(2024, 1, day), "count", float(day))

        aggs = ts_store.aggregate(
            "topic:test",
            "count",
            AggregationPeriod.DAILY,
            date(2024, 1, 1),
            date(2024, 1, 3),
        )

        assert len(aggs) == 3
        assert aggs[0].count == 1
        assert aggs[0].avg_value == 1.0

    def test_aggregate_weekly(self, ts_store: TimeSeriesStore) -> None:
        """Test weekly aggregation."""
        # Add points for two weeks (Jan 2024)
        # Week 1: Jan 1-7 (Mon-Sun)
        # Week 2: Jan 8-14
        for day in range(1, 15):
            ts_store.add_point("topic:test", date(2024, 1, day), "count", 1.0)

        aggs = ts_store.aggregate(
            "topic:test",
            "count",
            AggregationPeriod.WEEKLY,
            date(2024, 1, 1),
            date(2024, 1, 14),
        )

        assert len(aggs) == 2
        assert aggs[0].count == 7  # First week
        assert aggs[1].count == 7  # Second week

    def test_aggregate_monthly(self, ts_store: TimeSeriesStore) -> None:
        """Test monthly aggregation."""
        # Add points for two months
        for day in range(1, 32):  # January
            ts_store.add_point("topic:test", date(2024, 1, day), "count", 1.0)
        for day in range(1, 29):  # February
            ts_store.add_point("topic:test", date(2024, 2, day), "count", 1.0)

        aggs = ts_store.aggregate(
            "topic:test",
            "count",
            AggregationPeriod.MONTHLY,
            date(2024, 1, 1),
            date(2024, 2, 28),
        )

        assert len(aggs) == 2
        assert aggs[0].count == 31  # January
        assert aggs[1].count == 28  # February

    def test_aggregate_computes_stats(self, ts_store: TimeSeriesStore) -> None:
        """Test aggregation computes correct statistics."""
        ts_store.add_point("topic:test", date(2024, 1, 1), "count", 10.0)
        ts_store.add_point("topic:test", date(2024, 1, 2), "count", 20.0)
        ts_store.add_point("topic:test", date(2024, 1, 3), "count", 30.0)

        # All in same week (Mon Jan 1, 2024)
        aggs = ts_store.aggregate(
            "topic:test",
            "count",
            AggregationPeriod.WEEKLY,
            date(2024, 1, 1),
            date(2024, 1, 7),
        )

        assert len(aggs) == 1
        agg = aggs[0]
        assert agg.count == 3
        assert agg.sum_value == 60.0
        assert agg.avg_value == 20.0
        assert agg.min_value == 10.0
        assert agg.max_value == 30.0

    def test_aggregate_empty(self, ts_store: TimeSeriesStore) -> None:
        """Test aggregation on empty range."""
        aggs = ts_store.aggregate(
            "nonexistent",
            "count",
            AggregationPeriod.DAILY,
            date(2024, 1, 1),
            date(2024, 1, 31),
        )
        assert len(aggs) == 0


class TestVelocity:
    """Tests for velocity computation."""

    def test_compute_velocity_increasing(self, ts_store: TimeSeriesStore) -> None:
        """Test velocity for increasing trend."""
        today = date.today()

        # Older window: low values (30-60 days ago)
        for i in range(30, 60):
            ts_store.add_point("topic:test", today - timedelta(days=i), "count", 10.0)

        # Recent window: high values (0-30 days ago)
        for i in range(0, 30):
            ts_store.add_point("topic:test", today - timedelta(days=i), "count", 50.0)

        velocity = ts_store.compute_velocity("topic:test", "count", window_days=30)

        assert velocity is not None
        assert velocity > 0  # Increasing

    def test_compute_velocity_decreasing(self, ts_store: TimeSeriesStore) -> None:
        """Test velocity for decreasing trend."""
        today = date.today()

        # Older window: high values
        for i in range(30, 60):
            ts_store.add_point("topic:test", today - timedelta(days=i), "count", 50.0)

        # Recent window: low values
        for i in range(0, 30):
            ts_store.add_point("topic:test", today - timedelta(days=i), "count", 10.0)

        velocity = ts_store.compute_velocity("topic:test", "count", window_days=30)

        assert velocity is not None
        assert velocity < 0  # Decreasing

    def test_compute_velocity_insufficient_data(
        self, ts_store: TimeSeriesStore
    ) -> None:
        """Test velocity with insufficient data."""
        # Only add data for recent window, not older
        today = date.today()
        for i in range(0, 10):
            ts_store.add_point("topic:test", today - timedelta(days=i), "count", 10.0)

        velocity = ts_store.compute_velocity("topic:test", "count", window_days=30)

        assert velocity is None


class TestAcceleration:
    """Tests for acceleration computation."""

    def test_compute_acceleration_accelerating(self, ts_store: TimeSeriesStore) -> None:
        """Test acceleration for accelerating trend."""
        today = date.today()

        # Three windows with increasing velocity
        # Window 3 (oldest): values 10
        for i in range(60, 90):
            ts_store.add_point("topic:test", today - timedelta(days=i), "count", 10.0)

        # Window 2: values 30 (increase of 20)
        for i in range(30, 60):
            ts_store.add_point("topic:test", today - timedelta(days=i), "count", 30.0)

        # Window 1 (recent): values 70 (increase of 40)
        for i in range(0, 30):
            ts_store.add_point("topic:test", today - timedelta(days=i), "count", 70.0)

        acceleration = ts_store.compute_acceleration(
            "topic:test", "count", window_days=30
        )

        assert acceleration is not None
        assert acceleration > 0  # Accelerating

    def test_compute_acceleration_decelerating(self, ts_store: TimeSeriesStore) -> None:
        """Test acceleration for decelerating trend."""
        today = date.today()

        # Three windows with decreasing velocity
        # Window 3 (oldest): 10
        for i in range(60, 90):
            ts_store.add_point("topic:test", today - timedelta(days=i), "count", 10.0)

        # Window 2: 50 (increase of 40)
        for i in range(30, 60):
            ts_store.add_point("topic:test", today - timedelta(days=i), "count", 50.0)

        # Window 1 (recent): 60 (increase of only 10)
        for i in range(0, 30):
            ts_store.add_point("topic:test", today - timedelta(days=i), "count", 60.0)

        acceleration = ts_store.compute_acceleration(
            "topic:test", "count", window_days=30
        )

        assert acceleration is not None
        assert acceleration < 0  # Decelerating

    def test_compute_acceleration_insufficient_data(
        self, ts_store: TimeSeriesStore
    ) -> None:
        """Test acceleration with insufficient data."""
        acceleration = ts_store.compute_acceleration(
            "nonexistent", "count", window_days=30
        )
        assert acceleration is None


class TestDeletion:
    """Tests for deletion operations."""

    def test_delete_range(self, ts_store: TimeSeriesStore) -> None:
        """Test deleting points in range."""
        for day in range(1, 11):
            ts_store.add_point("topic:test", date(2024, 1, day), "count", float(day))

        deleted = ts_store.delete_range(
            "topic:test", "count", date(2024, 1, 3), date(2024, 1, 7)
        )

        assert deleted == 5

        # Verify remaining points
        remaining = ts_store.get_range(
            "topic:test", "count", date(2024, 1, 1), date(2024, 1, 10)
        )
        assert len(remaining) == 5

    def test_delete_range_empty(self, ts_store: TimeSeriesStore) -> None:
        """Test deleting from empty range."""
        deleted = ts_store.delete_range(
            "nonexistent", "count", date(2024, 1, 1), date(2024, 1, 31)
        )
        assert deleted == 0

    def test_delete_series(self, ts_store: TimeSeriesStore) -> None:
        """Test deleting entire series."""
        for day in range(1, 11):
            ts_store.add_point("topic:test", date(2024, 1, day), "count", 1.0)
            ts_store.add_point("topic:test", date(2024, 1, day), "citations", 10.0)

        deleted = ts_store.delete_series("topic:test")

        assert deleted == 20  # 10 days x 2 metrics

        # Verify series is empty
        remaining = ts_store.get_range(
            "topic:test", "count", date(2024, 1, 1), date(2024, 1, 31)
        )
        assert len(remaining) == 0


class TestListing:
    """Tests for listing operations."""

    def test_list_series(self, ts_store: TimeSeriesStore) -> None:
        """Test listing all series."""
        ts_store.add_point("topic:a", date(2024, 1, 1), "count", 1.0)
        ts_store.add_point("topic:b", date(2024, 1, 1), "count", 2.0)
        ts_store.add_point("topic:c", date(2024, 1, 1), "count", 3.0)

        series = ts_store.list_series()

        assert len(series) == 3
        assert "topic:a" in series
        assert "topic:b" in series
        assert "topic:c" in series

    def test_list_series_empty(self, ts_store: TimeSeriesStore) -> None:
        """Test listing series when empty."""
        series = ts_store.list_series()
        assert len(series) == 0

    def test_list_metrics(self, ts_store: TimeSeriesStore) -> None:
        """Test listing metrics for a series."""
        ts_store.add_point("topic:test", date(2024, 1, 1), "count", 1.0)
        ts_store.add_point("topic:test", date(2024, 1, 1), "citations", 10.0)
        ts_store.add_point("topic:test", date(2024, 1, 1), "authors", 5.0)

        metrics = ts_store.list_metrics("topic:test")

        assert len(metrics) == 3
        assert "count" in metrics
        assert "citations" in metrics
        assert "authors" in metrics

    def test_list_metrics_empty(self, ts_store: TimeSeriesStore) -> None:
        """Test listing metrics for non-existent series."""
        metrics = ts_store.list_metrics("nonexistent")
        assert len(metrics) == 0


class TestBucketCalculation:
    """Tests for aggregation bucket calculation."""

    def test_bucket_daily(self, ts_store: TimeSeriesStore) -> None:
        """Test daily bucket calculation."""
        d = date(2024, 1, 15)
        start, end = ts_store._get_bucket(d, AggregationPeriod.DAILY)
        assert start == d
        assert end == d

    def test_bucket_weekly(self, ts_store: TimeSeriesStore) -> None:
        """Test weekly bucket calculation."""
        # Wednesday, Jan 17, 2024
        d = date(2024, 1, 17)
        start, end = ts_store._get_bucket(d, AggregationPeriod.WEEKLY)

        # Week starts on Monday (Jan 15)
        assert start == date(2024, 1, 15)
        assert end == date(2024, 1, 21)

    def test_bucket_monthly(self, ts_store: TimeSeriesStore) -> None:
        """Test monthly bucket calculation."""
        d = date(2024, 1, 15)
        start, end = ts_store._get_bucket(d, AggregationPeriod.MONTHLY)

        assert start == date(2024, 1, 1)
        assert end == date(2024, 1, 31)

    def test_bucket_monthly_february(self, ts_store: TimeSeriesStore) -> None:
        """Test monthly bucket for February."""
        d = date(2024, 2, 15)  # 2024 is leap year
        start, end = ts_store._get_bucket(d, AggregationPeriod.MONTHLY)

        assert start == date(2024, 2, 1)
        assert end == date(2024, 2, 29)

    def test_bucket_monthly_december(self, ts_store: TimeSeriesStore) -> None:
        """Test monthly bucket for December."""
        d = date(2024, 12, 15)
        start, end = ts_store._get_bucket(d, AggregationPeriod.MONTHLY)

        assert start == date(2024, 12, 1)
        assert end == date(2024, 12, 31)


class TestClose:
    """Tests for resource cleanup."""

    def test_close_no_error(self, ts_store: TimeSeriesStore) -> None:
        """Test close method doesn't raise."""
        ts_store.close()  # Should not raise

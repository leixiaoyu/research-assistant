"""Time Series Storage for Research Intelligence.

This module provides:
- Temporal data storage for trend analysis (Milestone 9.4)
- Time series CRUD operations
- Aggregation queries (daily, weekly, monthly)
- Efficient querying by time range and metric

Used for:
- Topic velocity tracking
- Paper publication trends
- Citation rate analysis
- Emergence/saturation detection
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import structlog

from src.services.intelligence.storage.migrations import MigrationManager
from src.services.intelligence.storage.path_utils import sanitize_storage_path

logger = structlog.get_logger()


class AggregationPeriod(str, Enum):
    """Time periods for aggregation."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class TimeSeriesPoint:
    """A single point in a time series.

    Attributes:
        series_id: Identifier for the time series
        period: Date of the measurement
        metric_name: Name of the metric
        value: Numeric value
        metadata: Optional additional data
    """

    series_id: str
    period: date
    metric_name: str
    value: float
    metadata: dict[str, Any]


@dataclass
class TimeSeriesAggregate:
    """Aggregated time series data.

    Attributes:
        series_id: Identifier for the time series
        metric_name: Name of the metric
        period_start: Start of aggregation period
        period_end: End of aggregation period
        count: Number of data points
        sum_value: Sum of values
        avg_value: Average value
        min_value: Minimum value
        max_value: Maximum value
    """

    series_id: str
    metric_name: str
    period_start: date
    period_end: date
    count: int
    sum_value: float
    avg_value: float
    min_value: float
    max_value: float


class TimeSeriesStore:
    """Time series storage using SQLite.

    Features:
    - Store time-indexed metrics for trend analysis
    - Efficient range queries
    - Aggregation support (daily, weekly, monthly)
    - Metadata storage for context

    Usage:
        store = TimeSeriesStore("./data/intelligence/graph.db")
        store.initialize()

        # Add data point
        store.add_point(
            series_id="topic:llm-alignment",
            period=date(2024, 1, 15),
            metric_name="paper_count",
            value=42.0,
            metadata={"source": "arxiv"}
        )

        # Query range
        points = store.get_range(
            series_id="topic:llm-alignment",
            metric_name="paper_count",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31)
        )

        # Aggregate
        agg = store.aggregate(
            series_id="topic:llm-alignment",
            metric_name="paper_count",
            period=AggregationPeriod.WEEKLY,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31)
        )
    """

    def __init__(self, db_path: Path | str):
        """Initialize time series store.

        Args:
            db_path: Path to SQLite database file. Must reside under one of
                the approved storage roots (``data/``, ``cache/``, or the
                system temp directory). See ``sanitize_storage_path``.
        """
        self.db_path = sanitize_storage_path(db_path)
        self._migration_manager = MigrationManager(self.db_path)
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the database with migrations."""
        self._migration_manager.migrate()
        self._initialized = True
        logger.debug("time_series_store_initialized", db_path=str(self.db_path))

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection configured for safe concurrent access.

        Pragmas applied: ``foreign_keys=ON``, ``journal_mode=WAL``,
        ``synchronous=NORMAL``, ``busy_timeout=5000``.

        Returns:
            SQLite connection.

        Raises:
            RuntimeError: If store not initialized.
        """
        if not self._initialized:
            raise RuntimeError(
                "TimeSeriesStore not initialized. Call initialize() first."
            )

        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.row_factory = sqlite3.Row
        return conn

    def _serialize_metadata(self, metadata: dict[str, Any]) -> str:
        """Serialize metadata to JSON string."""
        return json.dumps(metadata, default=str)

    def _deserialize_metadata(self, json_str: str) -> dict[str, Any]:
        """Deserialize metadata from JSON string."""
        return json.loads(json_str) if json_str else {}

    def add_point(
        self,
        series_id: str,
        period: date,
        metric_name: str,
        value: float,
        metadata: Optional[dict[str, Any]] = None,
    ) -> TimeSeriesPoint:
        """Add a data point to the time series.

        If a point already exists for the same (series_id, period, metric_name),
        it will be replaced (upsert behavior).

        Args:
            series_id: Identifier for the time series
            period: Date of the measurement
            metric_name: Name of the metric
            value: Numeric value
            metadata: Optional additional data

        Returns:
            Created TimeSeriesPoint
        """
        conn = self._get_connection()
        try:
            metadata = metadata or {}
            metadata_json = self._serialize_metadata(metadata)
            period_str = period.isoformat()

            conn.execute(
                """
                INSERT OR REPLACE INTO time_series
                (series_id, period, metric_name, value, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (series_id, period_str, metric_name, value, metadata_json),
            )
            conn.commit()

            logger.debug(
                "time_series_point_added",
                series_id=series_id,
                period=period_str,
                metric_name=metric_name,
                value=value,
            )

            return TimeSeriesPoint(
                series_id=series_id,
                period=period,
                metric_name=metric_name,
                value=value,
                metadata=metadata,
            )
        finally:
            conn.close()

    def add_points_batch(self, points: list[TimeSeriesPoint]) -> int:
        """Add multiple data points efficiently.

        Args:
            points: List of TimeSeriesPoint objects

        Returns:
            Number of points added
        """
        if not points:
            return 0

        conn = self._get_connection()
        try:
            data = [
                (
                    p.series_id,
                    p.period.isoformat(),
                    p.metric_name,
                    p.value,
                    self._serialize_metadata(p.metadata),
                )
                for p in points
            ]

            conn.executemany(
                """
                INSERT OR REPLACE INTO time_series
                (series_id, period, metric_name, value, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                data,
            )
            conn.commit()

            logger.debug("time_series_batch_added", count=len(points))
            return len(points)
        finally:
            conn.close()

    def get_point(
        self, series_id: str, period: date, metric_name: str
    ) -> Optional[TimeSeriesPoint]:
        """Get a specific data point.

        Args:
            series_id: Identifier for the time series
            period: Date of the measurement
            metric_name: Name of the metric

        Returns:
            TimeSeriesPoint if found, None otherwise
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM time_series
                WHERE series_id = ? AND period = ? AND metric_name = ?
                """,
                (series_id, period.isoformat(), metric_name),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return TimeSeriesPoint(
                series_id=row["series_id"],
                period=date.fromisoformat(row["period"]),
                metric_name=row["metric_name"],
                value=row["value"],
                metadata=self._deserialize_metadata(row["metadata"]),
            )
        finally:
            conn.close()

    def get_range(
        self,
        series_id: str,
        metric_name: str,
        start_date: date,
        end_date: date,
    ) -> list[TimeSeriesPoint]:
        """Get data points in a date range.

        Args:
            series_id: Identifier for the time series
            metric_name: Name of the metric
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)

        Returns:
            List of TimeSeriesPoint objects ordered by period
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM time_series
                WHERE series_id = ? AND metric_name = ?
                AND period >= ? AND period <= ?
                ORDER BY period ASC
                """,
                (
                    series_id,
                    metric_name,
                    start_date.isoformat(),
                    end_date.isoformat(),
                ),
            )

            return [
                TimeSeriesPoint(
                    series_id=row["series_id"],
                    period=date.fromisoformat(row["period"]),
                    metric_name=row["metric_name"],
                    value=row["value"],
                    metadata=self._deserialize_metadata(row["metadata"]),
                )
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def get_latest(
        self, series_id: str, metric_name: str, count: int = 1
    ) -> list[TimeSeriesPoint]:
        """Get the most recent data points.

        Args:
            series_id: Identifier for the time series
            metric_name: Name of the metric
            count: Number of points to return

        Returns:
            List of TimeSeriesPoint objects ordered by period (most recent first)
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM time_series
                WHERE series_id = ? AND metric_name = ?
                ORDER BY period DESC
                LIMIT ?
                """,
                (series_id, metric_name, count),
            )

            return [
                TimeSeriesPoint(
                    series_id=row["series_id"],
                    period=date.fromisoformat(row["period"]),
                    metric_name=row["metric_name"],
                    value=row["value"],
                    metadata=self._deserialize_metadata(row["metadata"]),
                )
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def aggregate(
        self,
        series_id: str,
        metric_name: str,
        period: AggregationPeriod,
        start_date: date,
        end_date: date,
    ) -> list[TimeSeriesAggregate]:
        """Aggregate data points by time period.

        Args:
            series_id: Identifier for the time series
            metric_name: Name of the metric
            period: Aggregation period (daily, weekly, monthly)
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)

        Returns:
            List of TimeSeriesAggregate objects
        """
        conn = self._get_connection()
        try:
            # Get all points in range
            points = self.get_range(series_id, metric_name, start_date, end_date)

            if not points:
                return []

            # Group points by period
            buckets: dict[tuple[date, date], list[float]] = {}

            for point in points:
                bucket_start, bucket_end = self._get_bucket(point.period, period)
                key = (bucket_start, bucket_end)
                if key not in buckets:
                    buckets[key] = []
                buckets[key].append(point.value)

            # Compute aggregates
            result = []
            for (bucket_start, bucket_end), values in sorted(buckets.items()):
                result.append(
                    TimeSeriesAggregate(
                        series_id=series_id,
                        metric_name=metric_name,
                        period_start=bucket_start,
                        period_end=bucket_end,
                        count=len(values),
                        sum_value=sum(values),
                        avg_value=sum(values) / len(values),
                        min_value=min(values),
                        max_value=max(values),
                    )
                )

            return result
        finally:
            conn.close()

    def _get_bucket(self, d: date, period: AggregationPeriod) -> tuple[date, date]:
        """Get the bucket (start, end) for a date and aggregation period.

        Args:
            d: Date to bucket
            period: Aggregation period

        Returns:
            Tuple of (bucket_start, bucket_end) dates
        """
        if period == AggregationPeriod.DAILY:
            return (d, d)
        elif period == AggregationPeriod.WEEKLY:
            # Week starts on Monday
            start = d - timedelta(days=d.weekday())
            end = start + timedelta(days=6)
            return (start, end)
        else:  # MONTHLY
            start = d.replace(day=1)
            # Last day of month
            if d.month == 12:
                end = d.replace(month=12, day=31)
            else:
                end = d.replace(month=d.month + 1, day=1) - timedelta(days=1)
            return (start, end)

    def compute_velocity(
        self,
        series_id: str,
        metric_name: str,
        window_days: int = 30,
    ) -> Optional[float]:
        """Compute velocity (rate of change) for a time series.

        Velocity is calculated as (recent_avg - older_avg) / window_days,
        comparing the most recent window to the previous window.

        Args:
            series_id: Identifier for the time series
            metric_name: Name of the metric
            window_days: Window size in days for comparison

        Returns:
            Velocity value, or None if insufficient data
        """
        conn = self._get_connection()
        try:
            today = date.today()
            recent_start = today - timedelta(days=window_days)
            older_start = recent_start - timedelta(days=window_days)

            # Get recent window average
            cursor = conn.execute(
                """
                SELECT AVG(value) as avg_value, COUNT(*) as count
                FROM time_series
                WHERE series_id = ? AND metric_name = ?
                AND period >= ? AND period <= ?
                """,
                (series_id, metric_name, recent_start.isoformat(), today.isoformat()),
            )
            recent_row = cursor.fetchone()

            # Get older window average
            cursor = conn.execute(
                """
                SELECT AVG(value) as avg_value, COUNT(*) as count
                FROM time_series
                WHERE series_id = ? AND metric_name = ?
                AND period >= ? AND period < ?
                """,
                (
                    series_id,
                    metric_name,
                    older_start.isoformat(),
                    recent_start.isoformat(),
                ),
            )
            older_row = cursor.fetchone()

            # Need data in both windows
            if (
                not recent_row
                or not older_row
                or recent_row["count"] == 0
                or older_row["count"] == 0
            ):
                return None

            recent_avg = float(recent_row["avg_value"])
            older_avg = float(older_row["avg_value"])

            # Velocity = change per day
            velocity: float = (recent_avg - older_avg) / window_days

            return velocity
        finally:
            conn.close()

    def compute_acceleration(
        self,
        series_id: str,
        metric_name: str,
        window_days: int = 30,
    ) -> Optional[float]:
        """Compute acceleration (change in velocity) for a time series.

        Acceleration measures how velocity is changing over time.

        Args:
            series_id: Identifier for the time series
            metric_name: Name of the metric
            window_days: Window size in days for comparison

        Returns:
            Acceleration value, or None if insufficient data
        """
        # Compute velocity for two consecutive periods
        # For acceleration, we need 3 windows of data
        conn = self._get_connection()
        try:
            today = date.today()
            w1_start = today - timedelta(days=window_days)
            w2_start = w1_start - timedelta(days=window_days)
            w3_start = w2_start - timedelta(days=window_days)

            # Get averages for each window
            windows = []
            for start, end in [
                (w3_start, w2_start),
                (w2_start, w1_start),
                (w1_start, today),
            ]:
                cursor = conn.execute(
                    """
                    SELECT AVG(value) as avg_value, COUNT(*) as count
                    FROM time_series
                    WHERE series_id = ? AND metric_name = ?
                    AND period >= ? AND period < ?
                    """,
                    (series_id, metric_name, start.isoformat(), end.isoformat()),
                )
                row = cursor.fetchone()
                if not row or row["count"] == 0:
                    return None
                windows.append(row["avg_value"])

            # Velocity in older period
            v1: float = (windows[1] - windows[0]) / window_days
            # Velocity in recent period
            v2: float = (windows[2] - windows[1]) / window_days

            # Acceleration = change in velocity
            acceleration: float = (v2 - v1) / window_days

            return acceleration
        finally:
            conn.close()

    def delete_range(
        self,
        series_id: str,
        metric_name: str,
        start_date: date,
        end_date: date,
    ) -> int:
        """Delete data points in a date range.

        Args:
            series_id: Identifier for the time series
            metric_name: Name of the metric
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)

        Returns:
            Number of points deleted
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                DELETE FROM time_series
                WHERE series_id = ? AND metric_name = ?
                AND period >= ? AND period <= ?
                """,
                (
                    series_id,
                    metric_name,
                    start_date.isoformat(),
                    end_date.isoformat(),
                ),
            )
            conn.commit()

            deleted = cursor.rowcount
            if deleted > 0:
                logger.debug(
                    "time_series_range_deleted",
                    series_id=series_id,
                    metric_name=metric_name,
                    deleted=deleted,
                )

            return deleted
        finally:
            conn.close()

    def delete_series(self, series_id: str) -> int:
        """Delete all data points for a series.

        Args:
            series_id: Identifier for the time series

        Returns:
            Number of points deleted
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM time_series WHERE series_id = ?",
                (series_id,),
            )
            conn.commit()

            deleted = cursor.rowcount
            if deleted > 0:
                logger.debug(
                    "time_series_deleted",
                    series_id=series_id,
                    deleted=deleted,
                )

            return deleted
        finally:
            conn.close()

    def list_series(self) -> list[str]:
        """List all unique series IDs.

        Returns:
            List of series IDs
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT DISTINCT series_id FROM time_series ORDER BY series_id"
            )
            return [row["series_id"] for row in cursor.fetchall()]
        finally:
            conn.close()

    def list_metrics(self, series_id: str) -> list[str]:
        """List all metrics for a series.

        Args:
            series_id: Identifier for the time series

        Returns:
            List of metric names
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT DISTINCT metric_name FROM time_series
                WHERE series_id = ?
                ORDER BY metric_name
                """,
                (series_id,),
            )
            return [row["metric_name"] for row in cursor.fetchall()]
        finally:
            conn.close()

    def close(self) -> None:
        """Clean up resources."""
        pass

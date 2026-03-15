"""Timeframe resolution for incremental discovery (Phase 7.1).

Resolves query timeframes based on last successful run timestamp or
configuration for incremental discovery.

Usage:
    from src.utils.timeframe_resolver import TimeframeResolver

    resolver = TimeframeResolver(catalog_service)
    resolved = resolver.resolve(topic, topic_slug)

    # After successful discovery
    resolver.update_last_run(topic_slug, datetime.utcnow())
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, Any

import structlog

from src.models.discovery import ResolvedTimeframe
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    TimeframeSinceYear,
    TimeframeDateRange,
)

if TYPE_CHECKING:
    from src.services.catalog_service import CatalogService

logger = structlog.get_logger()


class TimeframeResolver:
    """Resolve query timeframes for incremental discovery.

    Converts configuration timeframes into concrete start/end dates,
    with support for incremental queries based on last run timestamp.

    Attributes:
        catalog_service: CatalogService for timestamp tracking
    """

    def __init__(self, catalog_service: "CatalogService"):
        """Initialize TimeframeResolver.

        Args:
            catalog_service: CatalogService instance for timestamp access
        """
        self.catalog_service = catalog_service

    def resolve(
        self,
        topic: ResearchTopic,
        topic_slug: str,
    ) -> ResolvedTimeframe:
        """Resolve timeframe for a topic query.

        Logic:
        1. IF topic.force_full_timeframe is True THEN use config timeframe
        2. ELSE IF query changed THEN reset and use config timeframe
        3. ELSE IF last_successful_discovery_at exists THEN use incremental
        4. ELSE use config timeframe (first run)

        Args:
            topic: ResearchTopic with timeframe configuration
            topic_slug: Topic slug for catalog lookup

        Returns:
            ResolvedTimeframe with concrete start/end dates
        """
        # Check for forced full timeframe
        if topic.force_full_timeframe:
            logger.info(
                "force_full_timeframe_enabled",
                topic_slug=topic_slug,
                reason="force_full_timeframe=True",
            )
            return self._resolve_config_timeframe(topic, is_incremental=False)

        # Check for query change (resets timestamp)
        query_changed = self.catalog_service.detect_query_change(topic, topic_slug)
        if query_changed:
            logger.info(
                "query_changed_reset_timeframe",
                topic_slug=topic_slug,
                reason="Query text changed, resetting to full timeframe",
            )
            return self._resolve_config_timeframe(topic, is_incremental=False)

        # Get last successful discovery timestamp
        last_discovery_at = self.catalog_service.get_last_discovery_at(topic_slug)

        if last_discovery_at is None:
            logger.info(
                "first_run_full_timeframe",
                topic_slug=topic_slug,
                reason="No previous discovery timestamp",
            )
            return self._resolve_config_timeframe(topic, is_incremental=False)

        # Use incremental timeframe
        logger.info(
            "incremental_discovery_mode",
            topic_slug=topic_slug,
            last_discovery_at=last_discovery_at.isoformat(),
        )
        return self._resolve_incremental_timeframe(topic, last_discovery_at)

    def update_last_run(
        self,
        topic_slug: str,
        timestamp: datetime,
    ) -> None:
        """Update last successful discovery timestamp.

        Should be called AFTER discovery succeeds. Do NOT call on failure.

        Args:
            topic_slug: Topic slug to update
            timestamp: Discovery completion timestamp
        """
        logger.info(
            "updating_last_discovery_timestamp",
            topic_slug=topic_slug,
            timestamp=timestamp.isoformat(),
        )
        self.catalog_service.set_last_discovery_at(topic_slug, timestamp)

    def _resolve_config_timeframe(
        self,
        topic: ResearchTopic,
        is_incremental: bool,
    ) -> ResolvedTimeframe:
        """Resolve timeframe from topic configuration.

        Args:
            topic: ResearchTopic with timeframe configuration
            is_incremental: Whether this is incremental (always False here)

        Returns:
            ResolvedTimeframe with concrete dates
        """
        now = datetime.utcnow()
        timeframe = topic.timeframe

        # Store original timeframe as dict for tracking
        original_timeframe: Dict[str, Any] = {
            "type": (
                timeframe.type.value
                if hasattr(timeframe.type, "value")
                else str(timeframe.type)
            ),
        }

        if isinstance(timeframe, TimeframeRecent):
            # Parse recent timeframe (e.g., "48h", "7d")
            value = timeframe.value
            unit = value[-1]
            amount = int(value[:-1])

            if unit == "h":
                delta = timedelta(hours=amount)
            elif unit == "d":
                delta = timedelta(days=amount)
            else:
                raise ValueError(f"Invalid timeframe unit: {unit}")

            start_date = now - delta
            end_date = now
            original_timeframe["value"] = timeframe.value

        elif isinstance(timeframe, TimeframeSinceYear):
            # Papers since specific year
            start_date = datetime(timeframe.value, 1, 1)
            end_date = now
            original_timeframe["value"] = timeframe.value

        elif isinstance(timeframe, TimeframeDateRange):
            # Custom date range
            start_date = datetime.combine(timeframe.start_date, datetime.min.time())
            end_date = datetime.combine(timeframe.end_date, datetime.max.time())
            original_timeframe["start_date"] = timeframe.start_date.isoformat()
            original_timeframe["end_date"] = timeframe.end_date.isoformat()

        else:
            raise ValueError(f"Unknown timeframe type: {type(timeframe)}")

        logger.info(
            "resolved_config_timeframe",
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            timeframe_type=(
                timeframe.type.value
                if hasattr(timeframe.type, "value")
                else str(timeframe.type)
            ),
        )

        return ResolvedTimeframe(
            start_date=start_date,
            end_date=end_date,
            is_incremental=is_incremental,
            overlap_buffer_hours=0,  # No buffer for full timeframe
            original_timeframe=original_timeframe,
        )

    def _resolve_incremental_timeframe(
        self,
        topic: ResearchTopic,
        last_discovery_at: datetime,
    ) -> ResolvedTimeframe:
        """Resolve incremental timeframe with overlap buffer.

        Queries papers published after last_discovery_at minus overlap buffer.

        Args:
            topic: ResearchTopic with timeframe configuration
            last_discovery_at: Last successful discovery timestamp

        Returns:
            ResolvedTimeframe with incremental dates and buffer
        """
        now = datetime.utcnow()

        # Apply 1-hour overlap buffer to prevent edge case gaps
        buffer_hours = 1
        start_date = last_discovery_at - timedelta(hours=buffer_hours)
        end_date = now

        # Store original timeframe for reference
        timeframe = topic.timeframe
        original_timeframe: Dict[str, Any] = {
            "type": (
                timeframe.type.value
                if hasattr(timeframe.type, "value")
                else str(timeframe.type)
            ),
        }

        if isinstance(timeframe, TimeframeRecent):
            original_timeframe["value"] = timeframe.value
        elif isinstance(timeframe, TimeframeSinceYear):
            original_timeframe["value"] = timeframe.value
        elif isinstance(timeframe, TimeframeDateRange):
            original_timeframe["start_date"] = timeframe.start_date.isoformat()
            original_timeframe["end_date"] = timeframe.end_date.isoformat()

        logger.info(
            "resolved_incremental_timeframe",
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            last_discovery_at=last_discovery_at.isoformat(),
            overlap_buffer_hours=buffer_hours,
        )

        return ResolvedTimeframe(
            start_date=start_date,
            end_date=end_date,
            is_incremental=True,
            overlap_buffer_hours=buffer_hours,
            original_timeframe=original_timeframe,
        )

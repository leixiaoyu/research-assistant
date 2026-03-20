"""Registry query operations - search and filter functionality.

This module provides query operations for the registry:
- Lookup by paper ID
- Filter by topic affiliation
- Statistics aggregation
"""

from typing import Optional, List
import structlog

from src.models.registry import RegistryEntry, RegistryState

logger = structlog.get_logger()


class RegistryQueries:
    """Query operations for the registry.

    Provides read-only query operations for retrieving and filtering
    registry entries.
    """

    def __init__(self):
        """Initialize query handler."""
        logger.debug("registry_queries_initialized")

    def get_entry(self, paper_id: str, state: RegistryState) -> Optional[RegistryEntry]:
        """Get a registry entry by paper ID.

        Args:
            paper_id: Canonical paper UUID.
            state: Current registry state.

        Returns:
            Registry entry or None.
        """
        return state.entries.get(paper_id)

    def get_entries_for_topic(
        self, topic_slug: str, state: RegistryState
    ) -> List[RegistryEntry]:
        """Get all registry entries affiliated with a topic.

        Args:
            topic_slug: Topic slug to filter by.
            state: Current registry state.

        Returns:
            List of registry entries for the topic.
        """
        return [
            entry
            for entry in state.entries.values()
            if topic_slug in entry.topic_affiliations
        ]

    def get_stats(self, state: RegistryState) -> dict:
        """Get registry statistics.

        Args:
            state: Current registry state.

        Returns:
            Dictionary of registry stats.
        """
        return {
            "total_entries": state.get_entry_count(),
            "total_dois": len(state.doi_index),
            "total_provider_ids": len(state.provider_id_index),
            "created_at": state.created_at.isoformat(),
            "updated_at": state.updated_at.isoformat(),
        }

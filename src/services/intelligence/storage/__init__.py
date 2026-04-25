"""Unified Storage Layer for Research Intelligence.

This module provides:
- GraphStore Protocol for backend abstraction
- SQLiteGraphStore implementation
- Time series storage for trend analysis
- Schema migrations with version tracking

The GraphStore abstraction enables future migration from SQLite to Neo4j
when node count exceeds 100K threshold.
"""

from src.services.intelligence.storage.unified_graph import (
    GraphStore,
    SQLiteGraphStore,
)
from src.services.intelligence.storage.time_series import TimeSeriesStore
from src.services.intelligence.storage.migrations import MigrationManager

__all__ = [
    "GraphStore",
    "SQLiteGraphStore",
    "TimeSeriesStore",
    "MigrationManager",
]

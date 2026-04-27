"""Intelligence graph storage layer (formerly
``src/services/intelligence/storage``).

Provides:
- ``MigrationManager`` — versioned schema migrations
- ``SQLiteGraphStore`` and the ``GraphStore`` Protocol
- ``TimeSeriesStore`` — temporal data for trend analysis
- ``GraphAlgorithms`` — algorithms (PageRank, ...) decoupled from the
  storage Protocol so the Protocol stays minimal.

Re-exports the most-used surface for convenience.
"""

from src.storage.intelligence_graph.algorithms import GraphAlgorithms
from src.storage.intelligence_graph.connection import open_connection
from src.storage.intelligence_graph.migrations import (
    ALL_MIGRATIONS,
    MIGRATION_V1_INITIAL,
    Migration,
    MigrationManager,
)
from src.storage.intelligence_graph.time_series import (
    AggregationPeriod,
    TimeSeriesAggregate,
    TimeSeriesPoint,
    TimeSeriesStore,
)
from src.storage.intelligence_graph.unified_graph import (
    GraphStore,
    SQLiteGraphStore,
)

__all__ = [
    "GraphStore",
    "SQLiteGraphStore",
    "GraphAlgorithms",
    "MigrationManager",
    "Migration",
    "MIGRATION_V1_INITIAL",
    "ALL_MIGRATIONS",
    "TimeSeriesStore",
    "TimeSeriesPoint",
    "TimeSeriesAggregate",
    "AggregationPeriod",
    "open_connection",
]

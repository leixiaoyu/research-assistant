"""Shared kernel models for Phase 9: Research Intelligence Layer.

This package provides the small set of models used everywhere across the
Phase 9 milestones:

- ``NodeType``, ``EdgeType``, ``GraphNode``, ``GraphEdge`` (graph kernel)
- The graph storage exception hierarchy
  (``GraphStoreError``, ``NodeNotFoundError``, ``EdgeNotFoundError``,
  ``OptimisticLockError``, ``ReferentialIntegrityError``)

Milestone-specific models (entities, relations, trends, gaps,
subscription enums, etc.) live in dedicated submodules and must be
imported from there explicitly. This keeps the shared surface narrow and
prevents milestones from accidentally coupling to one another's concerns.

Submodules:
- ``graph``: NodeType, EdgeType, GraphNode, GraphEdge, ENTITY_NAME_PATTERN
- ``knowledge``: EntityType, ExtractedEntity, ExtractedRelation
- ``frontier``: TrendStatus, GapType
- ``monitoring``: PaperSource, SubscriptionLimitError
- ``exceptions``: shared graph storage exceptions
"""

from src.services.intelligence.models.exceptions import (
    EdgeNotFoundError,
    GraphStoreError,
    NodeNotFoundError,
    OptimisticLockError,
    ReferentialIntegrityError,
)
from src.services.intelligence.models.graph import (
    ENTITY_NAME_PATTERN,
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
)

__all__ = [
    # Graph kernel
    "NodeType",
    "EdgeType",
    "GraphNode",
    "GraphEdge",
    "ENTITY_NAME_PATTERN",
    # Exceptions
    "GraphStoreError",
    "NodeNotFoundError",
    "EdgeNotFoundError",
    "OptimisticLockError",
    "ReferentialIntegrityError",
]

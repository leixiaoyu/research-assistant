"""Phase 9: Research Intelligence Layer.

This package provides intelligent research capabilities:
- Milestone 9.1: Proactive Paper Monitoring (monitoring/)
- Milestone 9.2: Citation Graph Intelligence (citation/)
- Milestone 9.3: Knowledge Graph Synthesis (knowledge/)
- Milestone 9.4: Research Frontier Detection (frontier/)

Shared infrastructure:
- models.py: Shared data models (NodeType, EdgeType, etc.)
- storage/: Unified graph storage layer
"""

from src.services.intelligence.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
)

__all__ = [
    "NodeType",
    "EdgeType",
    "GraphNode",
    "GraphEdge",
]

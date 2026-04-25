"""Graph algorithms decoupled from the storage Protocol.

Keeping algorithms outside the ``GraphStore`` Protocol:

- Lets the Protocol stay narrow — only CRUD + traversal.
- Lets us implement algorithms once and reuse across backends.
- Makes the edge-type filter for PageRank explicit and configurable
  (the original implementation hardcoded ``cites``).

Currently exposes:
- ``GraphAlgorithms.pagerank(store, edge_types, damping, iterations)``

The ``store`` argument is duck-typed against
``SQLiteGraphStore``-style read primitives (``_list_node_ids`` and
``_list_edges_by_types``). When a Neo4j backend lands it will provide
the same primitives (or a native PageRank wrapper).
"""

from __future__ import annotations

from typing import Optional, Protocol

from src.services.intelligence.models import NodeType


class _PageRankReadable(Protocol):
    """Minimal read interface required by ``GraphAlgorithms.pagerank``."""

    def _list_node_ids(  # pragma: no cover - Protocol abstract method
        self, node_type: Optional[NodeType] = None
    ) -> list[str]: ...

    def _list_edges_by_types(  # pragma: no cover - Protocol abstract method
        self, edge_type_values: list[str]
    ) -> list[tuple[str, str]]: ...


class GraphAlgorithms:
    """Stateless container for graph algorithms operating on a store."""

    @staticmethod
    def pagerank(
        store: _PageRankReadable,
        edge_types: list[str],
        damping: float = 0.85,
        iterations: int = 20,
        node_type: Optional[NodeType] = None,
    ) -> dict[str, float]:
        """Iterative PageRank suitable for small/medium graphs.

        Args:
            store: A graph store exposing ``_list_node_ids`` and
                ``_list_edges_by_types``.
            edge_types: REQUIRED list of edge-type string values to follow
                (e.g. ``[EdgeType.CITES.value]`` for citation PageRank, or
                ``[EdgeType.CITES.value, EdgeType.MENTIONS.value]`` for a
                blended graph). The previous implementation hardcoded
                ``cites``; callers must now opt in explicitly.
            damping: Damping factor (typical: 0.85).
            iterations: Fixed iteration count (typical: 20).
            node_type: Optional NodeType filter; restricts the scoring set
                to nodes of this type (e.g. only papers).

        Returns:
            ``{node_id: pagerank_score}``. Empty dict when no nodes match.

        Raises:
            ValueError: If ``edge_types`` is empty.
        """
        if not edge_types:
            raise ValueError("GraphAlgorithms.pagerank requires at least one edge type")

        node_ids = store._list_node_ids(node_type=node_type)
        if not node_ids:
            return {}

        n = len(node_ids)
        scores: dict[str, float] = {node_id: 1.0 / n for node_id in node_ids}
        node_set = set(node_ids)

        outgoing: dict[str, list[str]] = {nid: [] for nid in node_ids}
        incoming: dict[str, list[str]] = {nid: [] for nid in node_ids}

        for source, target in store._list_edges_by_types(edge_types):
            if source in node_set and target in node_set:
                outgoing[source].append(target)
                incoming[target].append(source)

        for _ in range(iterations):
            new_scores: dict[str, float] = {}
            for node_id in node_ids:
                rank = (1 - damping) / n
                for source in incoming[node_id]:
                    out_degree = len(outgoing[source])
                    if out_degree > 0:
                        rank += damping * scores[source] / out_degree
                new_scores[node_id] = rank
            scores = new_scores

        return scores

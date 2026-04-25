"""Tests for ``GraphAlgorithms`` (extracted from SQLiteGraphStore.pagerank).

These tests parallel the pre-refactor PageRank tests but go through the
new ``GraphAlgorithms.pagerank`` entry point with an explicit edge-type
list.
"""

import tempfile
from pathlib import Path

import pytest

from src.services.intelligence.models import EdgeType, NodeType
from src.storage.intelligence_graph import GraphAlgorithms, SQLiteGraphStore


@pytest.fixture
def temp_db() -> Path:
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        return Path(f.name)


@pytest.fixture
def graph_store(temp_db: Path) -> SQLiteGraphStore:
    """Create an initialized graph store."""
    store = SQLiteGraphStore(temp_db)
    store.initialize()
    return store


CITES = [EdgeType.CITES.value]


class TestPageRank:
    """Tests for ``GraphAlgorithms.pagerank``."""

    def test_pagerank_empty_graph(self, graph_store: SQLiteGraphStore) -> None:
        scores = GraphAlgorithms.pagerank(graph_store, edge_types=CITES)
        assert scores == {}

    def test_pagerank_single_node(self, graph_store: SQLiteGraphStore) -> None:
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        scores = GraphAlgorithms.pagerank(graph_store, edge_types=CITES)
        assert len(scores) == 1
        assert "paper:1" in scores

    def test_pagerank_basic(self, graph_store: SQLiteGraphStore) -> None:
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("paper:3", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "paper:1", "paper:3", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:2", "paper:3", EdgeType.CITES, {})

        scores = GraphAlgorithms.pagerank(graph_store, edge_types=CITES)

        assert len(scores) == 3
        assert scores["paper:3"] >= scores["paper:1"]
        assert scores["paper:3"] >= scores["paper:2"]

    def test_pagerank_filter_by_node_type(self, graph_store: SQLiteGraphStore) -> None:
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("entity:1", NodeType.ENTITY, {})

        scores = GraphAlgorithms.pagerank(
            graph_store, edge_types=CITES, node_type=NodeType.PAPER
        )

        assert len(scores) == 2
        assert "paper:1" in scores
        assert "paper:2" in scores
        assert "entity:1" not in scores

    def test_pagerank_with_cycles(self, graph_store: SQLiteGraphStore) -> None:
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("paper:3", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:2", "paper:3", EdgeType.CITES, {})
        graph_store.add_edge("e:3", "paper:3", "paper:1", EdgeType.CITES, {})

        scores = GraphAlgorithms.pagerank(graph_store, edge_types=CITES)
        assert len(scores) == 3
        values = list(scores.values())
        assert max(values) - min(values) < 0.1

    def test_pagerank_with_dangling_nodes(self, graph_store: SQLiteGraphStore) -> None:
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("paper:3", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "paper:1", "paper:3", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:2", "paper:3", EdgeType.CITES, {})

        scores = GraphAlgorithms.pagerank(graph_store, edge_types=CITES)
        assert len(scores) == 3
        assert scores["paper:3"] >= scores["paper:1"]

    def test_pagerank_blended_edge_types(self, graph_store: SQLiteGraphStore) -> None:
        """Multiple edge types in the filter list compose into one graph."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("entity:1", NodeType.ENTITY, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:1", "entity:1", EdgeType.MENTIONS, {})

        scores = GraphAlgorithms.pagerank(
            graph_store,
            edge_types=[EdgeType.CITES.value, EdgeType.MENTIONS.value],
        )
        # All 3 nodes are scored; edges from both types contribute
        assert set(scores.keys()) == {"paper:1", "paper:2", "entity:1"}

    def test_pagerank_rejects_empty_edge_types(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        with pytest.raises(ValueError, match="at least one edge type"):
            GraphAlgorithms.pagerank(graph_store, edge_types=[])

    def test_list_edges_by_types_handles_empty_input(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """The store-level helper short-circuits on empty input."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        # Empty edge_type_values: no SQL is executed; returns []
        assert graph_store._list_edges_by_types([]) == []

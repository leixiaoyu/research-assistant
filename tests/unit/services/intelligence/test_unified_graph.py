"""Tests for unified graph store.

Tests cover:
- GraphStore Protocol compliance
- SQLiteGraphStore CRUD operations
- Graph traversal (BFS)
- PageRank computation
- Optimistic locking (incl. concurrent-update race)
- Foreign key enforcement
- Path-traversal rejection
- JSONPath-injection rejection
- Edge cases and error handling
"""

import sqlite3
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from src.services.intelligence.models import (
    EdgeType,
    GraphStoreError,
    NodeNotFoundError,
    NodeType,
    OptimisticLockError,
    ReferentialIntegrityError,
)
from src.services.intelligence.storage.unified_graph import (
    GraphStore,
    SQLiteGraphStore,
)
from src.utils.security import SecurityError


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


class TestGraphStoreProtocol:
    """Tests for GraphStore protocol compliance."""

    def test_sqlite_implements_protocol(self) -> None:
        """Test SQLiteGraphStore implements GraphStore protocol."""
        assert isinstance(SQLiteGraphStore, type)
        # Check protocol compliance via runtime check
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            store = SQLiteGraphStore(Path(f.name))
            assert isinstance(store, GraphStore)


class TestSQLiteGraphStoreInit:
    """Tests for SQLiteGraphStore initialization."""

    def test_init_without_initialize_raises(self, temp_db: Path) -> None:
        """Test operations fail before initialize() is called."""
        store = SQLiteGraphStore(temp_db)
        with pytest.raises(GraphStoreError, match="not initialized"):
            store.get_node("test")

    def test_initialize_creates_tables(self, temp_db: Path) -> None:
        """Test initialize creates database schema."""
        store = SQLiteGraphStore(temp_db)
        store.initialize()

        conn = sqlite3.connect(str(temp_db))
        try:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            assert "nodes" in tables
            assert "edges" in tables
        finally:
            conn.close()

    def test_initialize_idempotent(self, temp_db: Path) -> None:
        """Test initialize can be called multiple times."""
        store = SQLiteGraphStore(temp_db)
        store.initialize()
        store.initialize()  # Should not raise


class TestNodeOperations:
    """Tests for node CRUD operations."""

    def test_add_node_minimal(self, graph_store: SQLiteGraphStore) -> None:
        """Test adding a node with minimal fields."""
        node = graph_store.add_node(
            node_id="paper:arxiv:2301.12345",
            node_type=NodeType.PAPER,
            properties={},
        )

        assert node.node_id == "paper:arxiv:2301.12345"
        assert node.node_type == NodeType.PAPER
        assert node.version == 1

    def test_add_node_with_properties(self, graph_store: SQLiteGraphStore) -> None:
        """Test adding a node with properties."""
        props = {"title": "Test Paper", "year": 2024}
        node = graph_store.add_node(
            node_id="paper:test",
            node_type=NodeType.PAPER,
            properties=props,
        )

        assert node.properties == props

    def test_add_node_duplicate_raises(self, graph_store: SQLiteGraphStore) -> None:
        """Test adding duplicate node raises error."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})

        with pytest.raises(GraphStoreError, match="already exists"):
            graph_store.add_node("paper:1", NodeType.PAPER, {})

    def test_get_node_exists(self, graph_store: SQLiteGraphStore) -> None:
        """Test getting existing node."""
        graph_store.add_node("paper:1", NodeType.PAPER, {"title": "Test"})

        node = graph_store.get_node("paper:1")
        assert node is not None
        assert node.node_id == "paper:1"
        assert node.properties["title"] == "Test"

    def test_get_node_not_found(self, graph_store: SQLiteGraphStore) -> None:
        """Test getting non-existent node returns None."""
        node = graph_store.get_node("nonexistent")
        assert node is None

    def test_update_node_properties(self, graph_store: SQLiteGraphStore) -> None:
        """Test updating node properties."""
        graph_store.add_node("paper:1", NodeType.PAPER, {"title": "Old"})

        updated = graph_store.update_node("paper:1", {"title": "New"})

        assert updated.properties["title"] == "New"
        assert updated.version == 2

    def test_update_node_merges_properties(self, graph_store: SQLiteGraphStore) -> None:
        """Test update merges with existing properties."""
        graph_store.add_node("paper:1", NodeType.PAPER, {"a": 1, "b": 2})

        updated = graph_store.update_node("paper:1", {"b": 3, "c": 4})

        assert updated.properties == {"a": 1, "b": 3, "c": 4}

    def test_update_node_not_found_raises(self, graph_store: SQLiteGraphStore) -> None:
        """Test updating non-existent node raises error."""
        with pytest.raises(NodeNotFoundError):
            graph_store.update_node("nonexistent", {})

    def test_update_node_optimistic_lock_success(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Test optimistic locking with correct version."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})

        # First update
        updated = graph_store.update_node("paper:1", {"x": 1}, expected_version=1)
        assert updated.version == 2

        # Second update with new version
        updated = graph_store.update_node("paper:1", {"y": 2}, expected_version=2)
        assert updated.version == 3

    def test_update_node_optimistic_lock_failure(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Test optimistic locking with wrong version."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})

        with pytest.raises(OptimisticLockError):
            graph_store.update_node("paper:1", {"x": 1}, expected_version=99)

    def test_delete_node_exists(self, graph_store: SQLiteGraphStore) -> None:
        """Test deleting existing node."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})

        deleted = graph_store.delete_node("paper:1")
        assert deleted is True

        node = graph_store.get_node("paper:1")
        assert node is None

    def test_delete_node_not_found(self, graph_store: SQLiteGraphStore) -> None:
        """Test deleting non-existent node returns False."""
        deleted = graph_store.delete_node("nonexistent")
        assert deleted is False

    def test_delete_node_cascades_edges(self, graph_store: SQLiteGraphStore) -> None:
        """Test deleting node cascades to edges."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("edge:1", "paper:1", "paper:2", EdgeType.CITES, {})

        # Delete source node
        graph_store.delete_node("paper:1")

        # Edge should be deleted
        edge = graph_store.get_edge("edge:1")
        assert edge is None


class TestEdgeOperations:
    """Tests for edge CRUD operations."""

    def test_add_edge_minimal(self, graph_store: SQLiteGraphStore) -> None:
        """Test adding an edge with minimal fields."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})

        edge = graph_store.add_edge(
            edge_id="edge:cites:1:2",
            source_id="paper:1",
            target_id="paper:2",
            edge_type=EdgeType.CITES,
            properties={},
        )

        assert edge.edge_id == "edge:cites:1:2"
        assert edge.edge_type == EdgeType.CITES
        assert edge.source_id == "paper:1"
        assert edge.target_id == "paper:2"

    def test_add_edge_with_properties(self, graph_store: SQLiteGraphStore) -> None:
        """Test adding an edge with properties."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})

        edge = graph_store.add_edge(
            "edge:1",
            "paper:1",
            "paper:2",
            EdgeType.CITES,
            {"context": "Building on..."},
        )

        assert edge.properties["context"] == "Building on..."

    def test_add_edge_missing_source_raises(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Test adding edge with missing source raises error."""
        graph_store.add_node("paper:2", NodeType.PAPER, {})

        with pytest.raises(ReferentialIntegrityError):
            graph_store.add_edge("edge:1", "nonexistent", "paper:2", EdgeType.CITES, {})

    def test_add_edge_missing_target_raises(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Test adding edge with missing target raises error."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})

        with pytest.raises(ReferentialIntegrityError):
            graph_store.add_edge("edge:1", "paper:1", "nonexistent", EdgeType.CITES, {})

    def test_add_edge_duplicate_raises(self, graph_store: SQLiteGraphStore) -> None:
        """Test adding duplicate edge raises error."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("edge:1", "paper:1", "paper:2", EdgeType.CITES, {})

        with pytest.raises(GraphStoreError, match="already exists"):
            graph_store.add_edge("edge:1", "paper:1", "paper:2", EdgeType.CITES, {})

    def test_get_edge_exists(self, graph_store: SQLiteGraphStore) -> None:
        """Test getting existing edge."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("edge:1", "paper:1", "paper:2", EdgeType.CITES, {"x": 1})

        edge = graph_store.get_edge("edge:1")
        assert edge is not None
        assert edge.edge_id == "edge:1"
        assert edge.properties["x"] == 1

    def test_get_edge_not_found(self, graph_store: SQLiteGraphStore) -> None:
        """Test getting non-existent edge returns None."""
        edge = graph_store.get_edge("nonexistent")
        assert edge is None

    def test_get_edges_outgoing(self, graph_store: SQLiteGraphStore) -> None:
        """Test getting outgoing edges."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("paper:3", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:1", "paper:3", EdgeType.CITES, {})
        graph_store.add_edge("e:3", "paper:2", "paper:1", EdgeType.CITES, {})

        edges = graph_store.get_edges("paper:1", direction="outgoing")
        assert len(edges) == 2
        assert all(e.source_id == "paper:1" for e in edges)

    def test_get_edges_incoming(self, graph_store: SQLiteGraphStore) -> None:
        """Test getting incoming edges."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "paper:2", "paper:1", EdgeType.CITES, {})

        edges = graph_store.get_edges("paper:1", direction="incoming")
        assert len(edges) == 1
        assert edges[0].target_id == "paper:1"

    def test_get_edges_both(self, graph_store: SQLiteGraphStore) -> None:
        """Test getting both incoming and outgoing edges."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("paper:3", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:3", "paper:1", EdgeType.CITES, {})

        edges = graph_store.get_edges("paper:1", direction="both")
        assert len(edges) == 2

    def test_get_edges_filter_by_type(self, graph_store: SQLiteGraphStore) -> None:
        """Test filtering edges by type."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("entity:1", NodeType.ENTITY, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:1", "entity:1", EdgeType.MENTIONS, {})

        cites = graph_store.get_edges(
            "paper:1", direction="outgoing", edge_type=EdgeType.CITES
        )
        assert len(cites) == 1
        assert cites[0].edge_type == EdgeType.CITES

    def test_delete_edge_exists(self, graph_store: SQLiteGraphStore) -> None:
        """Test deleting existing edge."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("edge:1", "paper:1", "paper:2", EdgeType.CITES, {})

        deleted = graph_store.delete_edge("edge:1")
        assert deleted is True

        edge = graph_store.get_edge("edge:1")
        assert edge is None

    def test_delete_edge_not_found(self, graph_store: SQLiteGraphStore) -> None:
        """Test deleting non-existent edge returns False."""
        deleted = graph_store.delete_edge("nonexistent")
        assert deleted is False


class TestGraphTraversal:
    """Tests for graph traversal operations."""

    def _create_citation_chain(self, store: SQLiteGraphStore, length: int) -> None:
        """Helper to create a linear citation chain."""
        for i in range(length):
            store.add_node(f"paper:{i}", NodeType.PAPER, {"index": i})
        for i in range(length - 1):
            store.add_edge(f"e:{i}", f"paper:{i}", f"paper:{i+1}", EdgeType.CITES, {})

    def test_traverse_depth_1(self, graph_store: SQLiteGraphStore) -> None:
        """Test traversal with depth 1."""
        self._create_citation_chain(graph_store, 5)

        nodes = graph_store.traverse("paper:0", [EdgeType.CITES], max_depth=1)

        assert len(nodes) == 1
        assert nodes[0].node_id == "paper:1"

    def test_traverse_depth_2(self, graph_store: SQLiteGraphStore) -> None:
        """Test traversal with depth 2."""
        self._create_citation_chain(graph_store, 5)

        nodes = graph_store.traverse("paper:0", [EdgeType.CITES], max_depth=2)

        assert len(nodes) == 2
        node_ids = {n.node_id for n in nodes}
        assert node_ids == {"paper:1", "paper:2"}

    def test_traverse_incoming(self, graph_store: SQLiteGraphStore) -> None:
        """Test traversal following incoming edges."""
        self._create_citation_chain(graph_store, 5)

        # Traverse backward from paper:4
        nodes = graph_store.traverse(
            "paper:4", [EdgeType.CITES], max_depth=2, direction="incoming"
        )

        assert len(nodes) == 2
        node_ids = {n.node_id for n in nodes}
        assert node_ids == {"paper:3", "paper:2"}

    def test_traverse_both_directions(self, graph_store: SQLiteGraphStore) -> None:
        """Test traversal in both directions."""
        self._create_citation_chain(graph_store, 5)

        # Traverse from middle
        nodes = graph_store.traverse(
            "paper:2", [EdgeType.CITES], max_depth=1, direction="both"
        )

        node_ids = {n.node_id for n in nodes}
        assert node_ids == {"paper:1", "paper:3"}

    def test_traverse_empty_result(self, graph_store: SQLiteGraphStore) -> None:
        """Test traversal from isolated node."""
        graph_store.add_node("isolated:1", NodeType.PAPER, {})

        nodes = graph_store.traverse("isolated:1", [EdgeType.CITES], max_depth=2)

        assert len(nodes) == 0

    def test_traverse_zero_depth(self, graph_store: SQLiteGraphStore) -> None:
        """Test traversal with zero depth returns empty."""
        self._create_citation_chain(graph_store, 3)

        nodes = graph_store.traverse("paper:0", [EdgeType.CITES], max_depth=0)

        assert len(nodes) == 0

    def test_traverse_filters_edge_types(self, graph_store: SQLiteGraphStore) -> None:
        """Test traversal only follows specified edge types."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("entity:1", NodeType.ENTITY, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:1", "entity:1", EdgeType.MENTIONS, {})

        nodes = graph_store.traverse("paper:1", [EdgeType.CITES], max_depth=1)

        assert len(nodes) == 1
        assert nodes[0].node_id == "paper:2"


class TestShortestPath:
    """Tests for shortest path finding."""

    def test_shortest_path_direct(self, graph_store: SQLiteGraphStore) -> None:
        """Test shortest path between directly connected nodes."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})

        path = graph_store.shortest_path("paper:1", "paper:2")

        assert path is not None
        assert len(path) == 2
        assert path[0].node_id == "paper:1"
        assert path[1].node_id == "paper:2"

    def test_shortest_path_multi_hop(self, graph_store: SQLiteGraphStore) -> None:
        """Test shortest path with multiple hops."""
        for i in range(5):
            graph_store.add_node(f"paper:{i}", NodeType.PAPER, {})
        for i in range(4):
            graph_store.add_edge(
                f"e:{i}", f"paper:{i}", f"paper:{i+1}", EdgeType.CITES, {}
            )

        path = graph_store.shortest_path("paper:0", "paper:4")

        assert path is not None
        assert len(path) == 5

    def test_shortest_path_same_node(self, graph_store: SQLiteGraphStore) -> None:
        """Test shortest path to same node."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})

        path = graph_store.shortest_path("paper:1", "paper:1")

        assert path is not None
        assert len(path) == 1
        assert path[0].node_id == "paper:1"

    def test_shortest_path_no_path(self, graph_store: SQLiteGraphStore) -> None:
        """Test shortest path when no path exists."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        # No edges

        path = graph_store.shortest_path("paper:1", "paper:2")

        assert path is None


class TestPageRank:
    """Tests for PageRank computation."""

    def test_pagerank_empty_graph(self, graph_store: SQLiteGraphStore) -> None:
        """Test PageRank on empty graph."""
        scores = graph_store.pagerank()
        assert scores == {}

    def test_pagerank_single_node(self, graph_store: SQLiteGraphStore) -> None:
        """Test PageRank with single node."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})

        scores = graph_store.pagerank()

        assert len(scores) == 1
        assert "paper:1" in scores

    def test_pagerank_basic(self, graph_store: SQLiteGraphStore) -> None:
        """Test PageRank on simple graph."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("paper:3", NodeType.PAPER, {})
        # paper:1 cites paper:3, paper:2 cites paper:3
        graph_store.add_edge("e:1", "paper:1", "paper:3", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:2", "paper:3", EdgeType.CITES, {})

        scores = graph_store.pagerank()

        assert len(scores) == 3
        # paper:3 should have highest score (most cited)
        assert scores["paper:3"] >= scores["paper:1"]
        assert scores["paper:3"] >= scores["paper:2"]

    def test_pagerank_filter_by_type(self, graph_store: SQLiteGraphStore) -> None:
        """Test PageRank filtered by node type."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("entity:1", NodeType.ENTITY, {})

        scores = graph_store.pagerank(node_type=NodeType.PAPER)

        assert len(scores) == 2
        assert "paper:1" in scores
        assert "paper:2" in scores
        assert "entity:1" not in scores


class TestMetrics:
    """Tests for graph metrics."""

    def test_get_node_count_empty(self, graph_store: SQLiteGraphStore) -> None:
        """Test node count on empty graph."""
        assert graph_store.get_node_count() == 0

    def test_get_node_count(self, graph_store: SQLiteGraphStore) -> None:
        """Test node count."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("entity:1", NodeType.ENTITY, {})

        assert graph_store.get_node_count() == 3

    def test_get_node_count_by_type(self, graph_store: SQLiteGraphStore) -> None:
        """Test node count filtered by type."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("entity:1", NodeType.ENTITY, {})

        assert graph_store.get_node_count(NodeType.PAPER) == 2
        assert graph_store.get_node_count(NodeType.ENTITY) == 1

    def test_get_edge_count_empty(self, graph_store: SQLiteGraphStore) -> None:
        """Test edge count on empty graph."""
        assert graph_store.get_edge_count() == 0

    def test_get_edge_count(self, graph_store: SQLiteGraphStore) -> None:
        """Test edge count."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("entity:1", NodeType.ENTITY, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:1", "entity:1", EdgeType.MENTIONS, {})

        assert graph_store.get_edge_count() == 2

    def test_get_edge_count_by_type(self, graph_store: SQLiteGraphStore) -> None:
        """Test edge count filtered by type."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("entity:1", NodeType.ENTITY, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:1", "entity:1", EdgeType.MENTIONS, {})

        assert graph_store.get_edge_count(EdgeType.CITES) == 1
        assert graph_store.get_edge_count(EdgeType.MENTIONS) == 1


class TestNodeQueries:
    """Tests for node query operations."""

    def test_get_nodes_by_type(self, graph_store: SQLiteGraphStore) -> None:
        """Test getting nodes by type."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("entity:1", NodeType.ENTITY, {})

        papers = graph_store.get_nodes_by_type(NodeType.PAPER)
        assert len(papers) == 2

        entities = graph_store.get_nodes_by_type(NodeType.ENTITY)
        assert len(entities) == 1

    def test_get_nodes_by_type_pagination(self, graph_store: SQLiteGraphStore) -> None:
        """Test pagination in get_nodes_by_type."""
        for i in range(10):
            graph_store.add_node(f"paper:{i}", NodeType.PAPER, {})

        page1 = graph_store.get_nodes_by_type(NodeType.PAPER, limit=3, offset=0)
        page2 = graph_store.get_nodes_by_type(NodeType.PAPER, limit=3, offset=3)

        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0].node_id != page2[0].node_id

    def test_search_nodes_by_property(self, graph_store: SQLiteGraphStore) -> None:
        """Test searching nodes by property."""
        graph_store.add_node("paper:1", NodeType.PAPER, {"title": "Test A"})
        graph_store.add_node("paper:2", NodeType.PAPER, {"title": "Test B"})
        graph_store.add_node("paper:3", NodeType.PAPER, {"title": "Test A"})

        results = graph_store.search_nodes("title", "Test A")

        assert len(results) == 2

    def test_search_nodes_by_property_with_type(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Test searching nodes by property with type filter."""
        graph_store.add_node("paper:1", NodeType.PAPER, {"name": "X"})
        graph_store.add_node("entity:1", NodeType.ENTITY, {"name": "X"})

        results = graph_store.search_nodes("name", "X", node_type=NodeType.PAPER)

        assert len(results) == 1
        assert results[0].node_type == NodeType.PAPER


class TestThresholdChecks:
    """Tests for threshold monitoring."""

    def test_check_thresholds_no_warning(self, graph_store: SQLiteGraphStore) -> None:
        """Test threshold check returns None when below threshold."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})

        warning = graph_store.check_thresholds()
        assert warning is None

    def test_close(self, graph_store: SQLiteGraphStore) -> None:
        """Test close method doesn't raise."""
        graph_store.close()  # Should not raise


class TestSearchNodesInjection:
    """Security tests: search_nodes must reject JSONPath injection."""

    @pytest.mark.parametrize(
        "bad_key",
        [
            'a"]; DROP',
            "$.title",
            "",
            "a" * 100,
            "1abc",
            "key with space",
            "key-with-dash",
            "key.with.dot",
        ],
    )
    def test_search_nodes_rejects_jsonpath_injection(
        self, graph_store: SQLiteGraphStore, bad_key: str
    ) -> None:
        """Reject any property_key that is not a safe identifier."""
        with pytest.raises(ValueError, match="Invalid property_key"):
            graph_store.search_nodes(bad_key, "value")


class TestPathTraversalRejection:
    """Security tests: SQLiteGraphStore must reject unsafe paths."""

    @pytest.mark.parametrize(
        "bad_path",
        [
            "../../etc/passwd.db",
            "/etc/passwd",
            "/usr/bin/sqlite3.db",
            "../../../shadow.db",
        ],
    )
    def test_graph_store_rejects_traversal_path(self, bad_path: str) -> None:
        """SQLiteGraphStore must reject paths outside approved roots."""
        with pytest.raises(SecurityError):
            SQLiteGraphStore(bad_path)


class TestOptimisticLockRace:
    """Security tests: concurrent updates must be serialized correctly."""

    def test_concurrent_update_rejects_stale_writer(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Two concurrent updates from version=1: exactly one wins.

        With ``BEGIN IMMEDIATE`` the loser observes the actual updated
        version (2) when its CAS UPDATE returns 0 rows, so the
        ``OptimisticLockError`` reports ``actual_version=2``.
        """
        graph_store.add_node("paper:race", NodeType.PAPER, {"counter": 0})

        barrier = threading.Barrier(2)
        results: list[object] = [None, None]

        def worker(index: int, value: int) -> None:
            barrier.wait()
            try:
                node = graph_store.update_node(
                    "paper:race", {"counter": value}, expected_version=1
                )
                results[index] = node
            except OptimisticLockError as e:
                results[index] = e

        t1 = threading.Thread(target=worker, args=(0, 100))
        t2 = threading.Thread(target=worker, args=(1, 200))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        successes = [r for r in results if not isinstance(r, OptimisticLockError)]
        failures = [r for r in results if isinstance(r, OptimisticLockError)]

        assert len(successes) == 1
        assert len(failures) == 1
        # The failure must report version=2 as the actual current version
        err = failures[0]
        assert isinstance(err, OptimisticLockError)
        assert err.expected_version == 1
        assert err.actual_version == 2


class TestUpdateNodeErrorPaths:
    """Tests for previously pragma'd error branches in update_node."""

    def test_update_node_serialization_error(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """If the merged properties cannot be JSON-serialized, raise
        GraphStoreError and roll back."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})

        def boom(*args: object, **kwargs: object) -> str:
            raise TypeError("not serializable")

        with patch.object(SQLiteGraphStore, "_serialize_properties", side_effect=boom):
            with pytest.raises(GraphStoreError, match="Failed to update node"):
                graph_store.update_node("paper:1", {"x": 1})

        # Node version unchanged after rollback
        node = graph_store.get_node("paper:1")
        assert node is not None
        assert node.version == 1

    def test_update_node_rowcount_zero_reports_actual_version(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """If the CAS UPDATE returns 0 rows (e.g., a future change drops
        BEGIN IMMEDIATE), the error must report the actual current version
        from a re-query rather than guessing ``current_version + 1``.

        BEGIN IMMEDIATE makes this path unreachable in normal flow, so we
        simulate it by wrapping the connection in a proxy that intercepts
        ``execute`` to force rowcount=0 on the UPDATE and version=42 on the
        follow-up SELECT.
        """
        graph_store.add_node("paper:rc0", NodeType.PAPER, {})
        _install_update_rowcount_proxy(graph_store, version_after=42)

        with pytest.raises(OptimisticLockError) as exc_info:
            graph_store.update_node("paper:rc0", {"x": 1})

        # Must report the re-queried actual version, not current_version + 1
        assert exc_info.value.actual_version == 42

    def test_update_node_rowcount_zero_node_deleted(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """If the row vanishes between SELECT and UPDATE, fall back to
        reporting the originally-observed version."""
        graph_store.add_node("paper:rc1", NodeType.PAPER, {})
        _install_update_rowcount_proxy(graph_store, version_after=None)

        with pytest.raises(OptimisticLockError) as exc_info:
            graph_store.update_node("paper:rc1", {"x": 1})

        # Falls back to the originally-observed version (1)
        assert exc_info.value.actual_version == 1


def _install_update_rowcount_proxy(
    graph_store: SQLiteGraphStore, version_after: object
) -> None:
    """Patch ``_get_connection`` to force the rowcount=0 branch.

    The returned wrapper:
    - Returns a cursor with ``rowcount=0`` for any UPDATE on ``nodes``.
    - Returns a cursor whose ``fetchone()`` yields the supplied
      ``version_after`` (or ``None`` for the deleted-row case) for the
      subsequent ``SELECT version FROM nodes`` re-query.
    All other statements pass through to the real connection.
    """

    real_get_connection = SQLiteGraphStore._get_connection

    class _ZeroRowCursor:
        rowcount = 0

    class _VersionCursor:
        def __init__(self, value: object) -> None:
            self._value = value

        def fetchone(self) -> object:
            if self._value is None:
                return None
            return {"version": self._value}

    class _ConnProxy:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn

        def execute(self, sql: str, *args: object, **kwargs: object) -> object:
            stripped = " ".join(sql.split()).upper()
            if stripped.startswith("UPDATE NODES"):
                return _ZeroRowCursor()
            if stripped.startswith("SELECT VERSION FROM NODES"):
                return _VersionCursor(version_after)
            return self._conn.execute(sql, *args, **kwargs)

        def commit(self) -> None:
            self._conn.commit()

        def rollback(self) -> None:
            self._conn.rollback()

        def close(self) -> None:
            self._conn.close()

    def patched(self: SQLiteGraphStore) -> object:
        return _ConnProxy(real_get_connection(self))

    # Bind the patch directly on the instance so other operations remain
    # untouched after the test exits via fixture teardown.
    graph_store._get_connection = patched.__get__(  # type: ignore[method-assign]
        graph_store, SQLiteGraphStore
    )


class TestAddIntegrityErrorBranches:
    """Tests for IntegrityError fall-through branches in add_node/add_edge."""

    def test_add_node_non_unique_integrity_error_reraised(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """A non-UNIQUE IntegrityError surfaces as GraphStoreError."""

        class FakeConn:
            def __init__(self) -> None:
                self.executes: list[tuple[object, ...]] = []

            def execute(self, *args: object, **kwargs: object) -> None:
                # First call is INSERT; raise an unfamiliar IntegrityError
                raise sqlite3.IntegrityError("custom not-unique not-fk msg")

            def commit(self) -> None:  # pragma: no cover - never reached
                pass

            def rollback(self) -> None:
                pass

            def close(self) -> None:
                pass

        with patch.object(SQLiteGraphStore, "_get_connection", return_value=FakeConn()):
            with pytest.raises(GraphStoreError, match="Failed to add node"):
                graph_store.add_node("paper:bad", NodeType.PAPER, {})

    def test_add_edge_non_unique_non_fk_integrity_error_reraised(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """A non-UNIQUE non-FK IntegrityError surfaces as GraphStoreError."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})

        class FakeConn:
            def execute(self, *args: object, **kwargs: object) -> None:
                raise sqlite3.IntegrityError("CHECK constraint failed: edges")

            def commit(self) -> None:  # pragma: no cover - never reached
                pass

            def rollback(self) -> None:
                pass

            def close(self) -> None:
                pass

        with patch.object(SQLiteGraphStore, "_get_connection", return_value=FakeConn()):
            with pytest.raises(GraphStoreError, match="Failed to add edge"):
                graph_store.add_edge(
                    "edge:bad", "paper:1", "paper:2", EdgeType.CITES, {}
                )

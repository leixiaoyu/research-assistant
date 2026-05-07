"""Tests for unified graph store.

Tests cover:
- GraphStore Protocol compliance
- SQLiteGraphStore CRUD operations
- Graph traversal (BFS)
- Optimistic locking (incl. concurrent-update race)
- Foreign key enforcement
- Path-traversal rejection
- JSONPath-injection rejection
- Edge cases and error handling

PageRank tests now live in
``tests/unit/storage/intelligence_graph/test_algorithms.py``.
"""

import sqlite3
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from src.services.intelligence.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    GraphStoreDuplicateError,
    GraphStoreError,
    NodeNotFoundError,
    NodeType,
    OptimisticLockError,
    ReferentialIntegrityError,
)
from src.storage.intelligence_graph.unified_graph import (
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
        """Test adding duplicate node raises typed duplicate error."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})

        # Typed signal — must be a ``GraphStoreDuplicateError`` (a
        # subclass of ``GraphStoreError`` so existing handlers still
        # match) and the message must still say "already exists" so
        # any human-facing logs stay readable (#S5).
        with pytest.raises(GraphStoreDuplicateError, match="already exists"):
            graph_store.add_node("paper:1", NodeType.PAPER, {})

    def test_add_node_duplicate_is_graph_store_error_subclass(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Existing ``except GraphStoreError`` handlers still catch dup errors."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        with pytest.raises(GraphStoreError):
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
        """Test adding duplicate edge raises typed duplicate error."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("edge:1", "paper:1", "paper:2", EdgeType.CITES, {})

        with pytest.raises(GraphStoreDuplicateError, match="already exists"):
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

    def test_shortest_path_source_equals_target_returns_single_node(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """``shortest_path(x, x)`` returns ``[node_x]`` via the same
        connection used by the BFS path (no separate get_node call)."""
        graph_store.add_node("paper:x", NodeType.PAPER, {"k": "v"})

        path = graph_store.shortest_path("paper:x", "paper:x")

        assert path is not None
        assert len(path) == 1
        assert path[0].node_id == "paper:x"
        assert path[0].properties == {"k": "v"}

    def test_shortest_path_source_equals_target_missing_returns_none(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """``shortest_path(missing, missing)`` returns ``None`` rather than
        synthesizing a node — the early-exit shares the BFS connection but
        still respects existence."""
        path = graph_store.shortest_path("paper:missing", "paper:missing")
        assert path is None

    def test_shortest_path_max_depth_bounds_bfs(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """``max_depth`` causes BFS to return ``None`` when target is beyond bound.

        Graph: p:0 -> p:1 -> p:2 -> p:3
        With max_depth=1 the BFS only expands one hop from p:0, so p:3
        (3 hops away) is unreachable and None is returned.
        """
        for i in range(4):
            graph_store.add_node(f"p:md:{i}", NodeType.PAPER, {})
        for i in range(3):
            graph_store.add_edge(
                f"edge:md:{i}:{i+1}",
                f"p:md:{i}",
                f"p:md:{i+1}",
                EdgeType.CITES,
                {},
            )
        # Without bound, full path is found.
        path_full = graph_store.shortest_path("p:md:0", "p:md:3")
        assert path_full is not None
        assert len(path_full) == 4  # 4 nodes, 3 hops

        # With max_depth=2, p:md:3 (3 hops away) is NOT reachable.
        path_bounded = graph_store.shortest_path("p:md:0", "p:md:3", max_depth=2)
        assert path_bounded is None

        # With max_depth=3, p:md:3 IS exactly reachable.
        path_exact = graph_store.shortest_path("p:md:0", "p:md:3", max_depth=3)
        assert path_exact is not None
        assert [n.node_id for n in path_exact] == [
            "p:md:0",
            "p:md:1",
            "p:md:2",
            "p:md:3",
        ]

    def test_shortest_path_max_depth_none_is_unbounded(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """``max_depth=None`` (the default) leaves BFS fully unbounded."""
        for i in range(3):
            graph_store.add_node(f"p:unb:{i}", NodeType.PAPER, {})
        for i in range(2):
            graph_store.add_edge(
                f"edge:unb:{i}:{i+1}",
                f"p:unb:{i}",
                f"p:unb:{i+1}",
                EdgeType.CITES,
                {},
            )
        path = graph_store.shortest_path("p:unb:0", "p:unb:2", max_depth=None)
        assert path is not None
        assert len(path) == 3


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

    def test_search_nodes_rejects_none_property_key(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """``None`` gets a dedicated, informative message (not the regex one)."""
        with pytest.raises(ValueError, match="non-empty identifier-style string"):
            graph_store.search_nodes(None, "value")  # type: ignore[arg-type]

    def test_search_nodes_rejects_empty_property_key(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Empty string also gets the dedicated message."""
        with pytest.raises(ValueError, match="non-empty identifier-style string"):
            graph_store.search_nodes("", "value")

    def test_search_nodes_property_key_error_message_is_informative(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """The None/empty error message includes the bad value's repr."""
        with pytest.raises(ValueError) as exc_info_none:
            graph_store.search_nodes(None, "value")  # type: ignore[arg-type]
        assert "None" in str(exc_info_none.value)

        with pytest.raises(ValueError) as exc_info_empty:
            graph_store.search_nodes("", "value")
        assert "''" in str(exc_info_empty.value)


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


class TestGraphStoreAdditionalEdgeCases:
    """Tests folded in from former test_coverage_extras.py."""

    def test_add_node_with_complex_properties(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Test adding node with nested properties."""
        props = {
            "title": "Test",
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "date": "2024-01-01",
        }
        graph_store.add_node("paper:1", NodeType.PAPER, props)

        retrieved = graph_store.get_node("paper:1")
        assert retrieved is not None
        assert retrieved.properties["nested"]["key"] == "value"
        assert retrieved.properties["list"] == [1, 2, 3]

    def test_update_node_round_trip(self, graph_store: SQLiteGraphStore) -> None:
        """Update succeeds and the new property is persisted."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        node = graph_store.update_node("paper:1", {"new": "prop"})
        assert node.properties["new"] == "prop"

    def test_add_edge_unique_constraint(self, graph_store: SQLiteGraphStore) -> None:
        """Adding the same edge twice raises GraphStoreError."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})
        with pytest.raises(GraphStoreError, match="already exists"):
            graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})

    def test_get_edges_incoming_with_filter(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Test getting incoming edges with type filter."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("entity:1", NodeType.ENTITY, {})
        graph_store.add_edge("e:1", "paper:2", "paper:1", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "entity:1", "paper:1", EdgeType.MENTIONS, {})

        edges = graph_store.get_edges(
            "paper:1", direction="incoming", edge_type=EdgeType.CITES
        )
        assert len(edges) == 1
        assert edges[0].edge_type == EdgeType.CITES

    def test_get_edges_both_with_filter(self, graph_store: SQLiteGraphStore) -> None:
        """Test getting both direction edges with type filter."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("paper:3", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:3", "paper:1", EdgeType.CITES, {})
        graph_store.add_edge("e:3", "paper:1", "paper:3", EdgeType.CITED_BY, {})

        edges = graph_store.get_edges(
            "paper:1", direction="both", edge_type=EdgeType.CITES
        )
        assert len(edges) == 2

    def test_shortest_path_source_not_found(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Test shortest path when source doesn't exist."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        path = graph_store.shortest_path("nonexistent", "paper:1")
        assert path is None

    def test_search_nodes_no_results(self, graph_store: SQLiteGraphStore) -> None:
        """Test search nodes returns empty for no matches."""
        graph_store.add_node("paper:1", NodeType.PAPER, {"title": "Test"})
        results = graph_store.search_nodes("title", "Nonexistent")
        assert len(results) == 0

    def test_traverse_with_multiple_edge_types(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Test traverse following multiple edge types."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_node("entity:1", NodeType.ENTITY, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})
        graph_store.add_edge("e:2", "paper:1", "entity:1", EdgeType.MENTIONS, {})

        nodes = graph_store.traverse(
            "paper:1", [EdgeType.CITES, EdgeType.MENTIONS], max_depth=1
        )
        assert len(nodes) == 2

    def test_initialize_with_threshold_warning(self, temp_db: Path) -> None:
        """Test initialize logs warning when threshold exceeded."""
        from src.storage.intelligence_graph.migrations import MigrationManager

        store = SQLiteGraphStore(temp_db)
        store.initialize()

        conn = sqlite3.connect(str(temp_db))
        try:
            for i in range(MigrationManager.NODE_COUNT_WARNING_THRESHOLD):
                conn.execute(
                    "INSERT INTO nodes (node_id, node_type, properties) "
                    "VALUES (?, 'paper', '{}')",
                    (f"paper:{i}",),
                )
            conn.commit()
        finally:
            conn.close()

        store2 = SQLiteGraphStore(temp_db)
        store2._initialized = False
        store2.initialize()

    def test_update_node_concurrent_modification_via_external_write(
        self, graph_store: SQLiteGraphStore, temp_db: Path
    ) -> None:
        """An external bump of version causes optimistic-lock failure."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})

        conn = sqlite3.connect(str(temp_db))
        try:
            conn.execute("UPDATE nodes SET version = 5 WHERE node_id = 'paper:1'")
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(OptimisticLockError):
            graph_store.update_node("paper:1", {"new": "prop"}, expected_version=1)

    def test_traverse_no_neighbors_of_requested_type(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Traverse returns empty when no edges of requested type exist."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.MENTIONS, {})
        nodes = graph_store.traverse("paper:1", [EdgeType.CITES], max_depth=1)
        assert len(nodes) == 0

    def test_get_nodes_by_type_empty_result(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Empty result when no nodes of the requested type exist."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        nodes = graph_store.get_nodes_by_type(NodeType.ENTITY)
        assert len(nodes) == 0

    def test_add_node_duplicate_message_includes_node_id(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """The duplicate-add error mentions the conflicting node id."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        with pytest.raises(GraphStoreError) as exc_info:
            graph_store.add_node("paper:1", NodeType.PAPER, {})
        assert "paper:1" in str(exc_info.value)


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


class TestTraverseBatching:
    """Performance tests: traverse must batch node fetches per BFS layer.

    Without batching, BFS over a fan-out tree issues one
    ``SELECT * FROM nodes WHERE node_id = ?`` per visited neighbor —
    O(N) round-trips. With per-layer batching this collapses to one
    ``SELECT ... WHERE node_id IN (...)`` per layer.
    """

    def test_traverse_batches_node_fetch_per_layer(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Root → 5 children → 25 grandchildren, depth=2 must use few node selects.

        We do not assert an exact query count (over-coupling); we assert the
        number of ``SELECT * FROM nodes WHERE node_id IN`` queries is small
        (≤ depth) and that we are NOT issuing per-id node selects.
        """
        # Build root → 5 children → 25 grandchildren.
        graph_store.add_node("root", NodeType.PAPER, {})
        for i in range(5):
            cid = f"child:{i}"
            graph_store.add_node(cid, NodeType.PAPER, {})
            graph_store.add_edge(f"e:r:{i}", "root", cid, EdgeType.CITES, {})
            for j in range(5):
                gid = f"grand:{i}:{j}"
                graph_store.add_node(gid, NodeType.PAPER, {})
                graph_store.add_edge(f"e:c:{i}:{j}", cid, gid, EdgeType.CITES, {})

        # Sanity-check the traversal still returns all 30 descendants.
        nodes = graph_store.traverse("root", [EdgeType.CITES], max_depth=2)
        assert len(nodes) == 30

        # Now wrap the connection to count node-row queries by SQL shape.
        original_get_connection = graph_store._get_connection
        in_clause_queries: list[str] = []
        per_id_queries: list[str] = []

        class _CountingConn:
            def __init__(self, conn: sqlite3.Connection) -> None:
                self._conn = conn

            def execute(self, sql: str, *args: object, **kwargs: object) -> object:
                norm = " ".join(sql.split()).upper()
                if "FROM NODES WHERE NODE_ID IN" in norm:
                    in_clause_queries.append(norm)
                elif "FROM NODES WHERE NODE_ID = ?" in norm:
                    per_id_queries.append(norm)
                return self._conn.execute(sql, *args, **kwargs)

            def commit(self) -> None:
                self._conn.commit()

            def rollback(self) -> None:
                self._conn.rollback()

            def close(self) -> None:
                self._conn.close()

        def patched(self: SQLiteGraphStore) -> object:
            return _CountingConn(original_get_connection())

        graph_store._get_connection = patched.__get__(  # type: ignore[method-assign]
            graph_store, SQLiteGraphStore
        )

        nodes = graph_store.traverse("root", [EdgeType.CITES], max_depth=2)
        assert len(nodes) == 30

        # Per-id node selects must be zero — batching means we never use them.
        assert (
            per_id_queries == []
        ), f"Expected 0 per-id node selects, got {len(per_id_queries)}"
        # One IN-clause query per BFS layer; the test graph has 30 nodes,
        # well under the 500-id chunk limit, so no chunking expected. With
        # ``max_depth=2`` we should see exactly two layer queries.
        assert (
            len(in_clause_queries) == 2
        ), f"expected 2 layer queries, got {len(in_clause_queries)}"

    def test_traverse_direction_both_uses_union_all(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Bidirectional neighbor query must use UNION ALL, not bare UNION.

        The BFS visited set already deduplicates, so plain UNION is wasted
        sort/distinct work on every hop.
        """
        graph_store.add_node("a", NodeType.PAPER, {})
        graph_store.add_node("b", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "a", "b", EdgeType.CITES, {})

        original_get_connection = graph_store._get_connection
        captured_sql: list[str] = []

        class _CapturingConn:
            def __init__(self, conn: sqlite3.Connection) -> None:
                self._conn = conn

            def execute(self, sql: str, *args: object, **kwargs: object) -> object:
                captured_sql.append(sql)
                return self._conn.execute(sql, *args, **kwargs)

            def commit(self) -> None:
                self._conn.commit()

            def rollback(self) -> None:
                self._conn.rollback()

            def close(self) -> None:
                self._conn.close()

        def patched(self: SQLiteGraphStore) -> object:
            return _CapturingConn(original_get_connection())

        graph_store._get_connection = patched.__get__(  # type: ignore[method-assign]
            graph_store, SQLiteGraphStore
        )

        graph_store.traverse("a", [EdgeType.CITES], max_depth=1, direction="both")

        # Find the neighbor query for direction=both — it must say UNION ALL.
        bidir = [s for s in captured_sql if "source_id" in s and "target_id" in s]
        assert bidir, "Bidirectional neighbor query was not issued"
        assert any(
            "UNION ALL" in s for s in bidir
        ), f"Expected UNION ALL in bidirectional query, got: {bidir}"
        for s in bidir:
            # Bare UNION (i.e. without ALL) must not appear in the bidir query.
            normalized = " ".join(s.split())
            assert " UNION " not in normalized.upper().replace("UNION ALL", "").replace(
                "  ", " "
            ), f"Found bare UNION (without ALL) in bidir query: {s}"


class TestShortestPathLongChain:
    """Coverage for parent-dict reconstruction over a longer path."""

    def test_shortest_path_long_chain_reconstructs_correctly(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """A 6-hop chain (7 nodes) must be reconstructed in order via parent map."""
        n = 7
        for i in range(n):
            graph_store.add_node(f"p:{i}", NodeType.PAPER, {})
        for i in range(n - 1):
            graph_store.add_edge(f"e:{i}", f"p:{i}", f"p:{i+1}", EdgeType.CITES, {})

        path = graph_store.shortest_path("p:0", f"p:{n-1}")
        assert path is not None
        assert [node.node_id for node in path] == [f"p:{i}" for i in range(n)]


class TestAddNodesBatch:
    """Tests for ``add_nodes_batch`` bulk insert API."""

    def _make_node(self, node_id: str) -> GraphNode:
        return GraphNode(node_id=node_id, node_type=NodeType.PAPER, properties={})

    def test_add_nodes_batch_success(self, graph_store: SQLiteGraphStore) -> None:
        """Insert 100 nodes in one batch and confirm all are persisted."""
        nodes = [self._make_node(f"paper:{i}") for i in range(100)]
        graph_store.add_nodes_batch(nodes)

        # Verify count via get_nodes_by_type
        retrieved = graph_store.get_nodes_by_type(NodeType.PAPER, limit=200)
        assert len(retrieved) == 100
        assert {n.node_id for n in retrieved} == {f"paper:{i}" for i in range(100)}

    def test_add_nodes_batch_empty_list(self, graph_store: SQLiteGraphStore) -> None:
        """Empty input is a no-op (no crash, no connection opened)."""
        # Patch _get_connection to fail loudly if it is called.
        with patch.object(
            SQLiteGraphStore,
            "_get_connection",
            side_effect=AssertionError("connection opened for empty batch"),
        ):
            graph_store.add_nodes_batch([])
        assert graph_store.get_node_count() == 0

    def test_add_nodes_batch_atomic_rollback(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """A duplicate node_id inside the batch rolls back the whole batch
        and surfaces the typed ``GraphStoreDuplicateError`` (#S5)."""
        # Pre-existing node that will collide with one in the batch.
        graph_store.add_node("paper:dup", NodeType.PAPER, {})
        baseline_count = graph_store.get_node_count()

        batch = [
            self._make_node("paper:new1"),
            self._make_node("paper:dup"),  # collides
            self._make_node("paper:new2"),
        ]

        with pytest.raises(GraphStoreDuplicateError, match="duplicate node_id"):
            graph_store.add_nodes_batch(batch)

        # No new nodes from the batch should have been inserted.
        assert graph_store.get_node_count() == baseline_count
        assert graph_store.get_node("paper:new1") is None
        assert graph_store.get_node("paper:new2") is None

    def test_add_nodes_batch_chains_cause(self, graph_store: SQLiteGraphStore) -> None:
        """The wrapped GraphStoreDuplicateError chains the IntegrityError."""
        graph_store.add_node("paper:dup", NodeType.PAPER, {})
        batch = [self._make_node("paper:dup")]
        with pytest.raises(GraphStoreDuplicateError) as exc_info:
            graph_store.add_nodes_batch(batch)
        assert isinstance(exc_info.value.__cause__, sqlite3.IntegrityError)

    def test_add_nodes_batch_non_unique_error_falls_back_to_generic(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """A non-UNIQUE IntegrityError surfaces as the generic
        ``GraphStoreError`` (not the duplicate subclass) so callers'
        recovery loops do not silently swallow it (#S5)."""
        batch = [self._make_node("paper:1")]

        original_get_conn = graph_store._get_connection

        class _ConnProxy:
            def __init__(self, conn: sqlite3.Connection) -> None:
                self._conn = conn

            def __enter__(self):  # type: ignore[no-untyped-def]
                return self._conn.__enter__()

            def __exit__(self, *args):  # type: ignore[no-untyped-def]
                return self._conn.__exit__(*args)

            def executemany(self, sql: str, rows):  # type: ignore[no-untyped-def]
                # Drive the non-UNIQUE branch — message shape mirrors
                # what SQLite produces for a CHECK constraint failure.
                raise sqlite3.IntegrityError("CHECK constraint failed: synthetic")

            def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                return self._conn.execute(*args, **kwargs)

            def close(self) -> None:
                self._conn.close()

        def get_conn() -> _ConnProxy:  # type: ignore[type-arg]
            return _ConnProxy(original_get_conn())

        with patch.object(graph_store, "_get_connection", side_effect=get_conn):
            with pytest.raises(GraphStoreError) as exc_info:
                graph_store.add_nodes_batch(batch)
        # Must NOT be the duplicate subclass — the recovery loop relies
        # on this distinction to surface unrecoverable errors.
        assert not isinstance(exc_info.value, GraphStoreDuplicateError)
        assert "Failed to bulk insert nodes" in str(exc_info.value)

    def test_add_nodes_batch_rejects_oversized_batch(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Batches above ``_MAX_BULK_BATCH_SIZE`` are refused without
        opening any DB connection (DoS guard)."""
        from src.storage.intelligence_graph.unified_graph import (
            _MAX_BULK_BATCH_SIZE,
        )

        oversized = [
            self._make_node(f"paper:{i}") for i in range(_MAX_BULK_BATCH_SIZE + 1)
        ]
        # Patch _get_connection to fail loudly if the DB is touched.
        with patch.object(
            SQLiteGraphStore,
            "_get_connection",
            side_effect=AssertionError("connection opened for oversized batch"),
        ):
            with pytest.raises(ValueError) as exc_info:
                graph_store.add_nodes_batch(oversized)

        msg = str(exc_info.value)
        assert str(len(oversized)) in msg
        assert str(_MAX_BULK_BATCH_SIZE) in msg


class TestAddEdgesBatch:
    """Tests for ``add_edges_batch`` bulk insert API."""

    def _make_edge(self, edge_id: str, source: str, target: str) -> GraphEdge:
        return GraphEdge(
            edge_id=edge_id,
            edge_type=EdgeType.CITES,
            source_id=source,
            target_id=target,
            properties={},
        )

    def test_add_edges_batch_success(self, graph_store: SQLiteGraphStore) -> None:
        """Insert 100 edges in one batch and confirm count."""
        # Need source/target nodes for FK satisfaction.
        for i in range(101):
            graph_store.add_node(f"paper:{i}", NodeType.PAPER, {})

        edges = [
            self._make_edge(f"e:{i}", f"paper:{i}", f"paper:{i+1}") for i in range(100)
        ]
        graph_store.add_edges_batch(edges)

        assert graph_store.get_edge_count() == 100

    def test_add_edges_batch_empty_list(self, graph_store: SQLiteGraphStore) -> None:
        """Empty input is a no-op (no connection opened)."""
        with patch.object(
            SQLiteGraphStore,
            "_get_connection",
            side_effect=AssertionError("connection opened for empty batch"),
        ):
            graph_store.add_edges_batch([])
        assert graph_store.get_edge_count() == 0

    def test_add_edges_batch_atomic_rollback(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """A duplicate edge_id inside the batch rolls back the whole batch
        and surfaces the typed ``GraphStoreDuplicateError`` (#S5)."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("e:dup", "paper:1", "paper:2", EdgeType.CITES, {})
        baseline = graph_store.get_edge_count()

        batch = [
            self._make_edge("e:new1", "paper:1", "paper:2"),
            self._make_edge("e:dup", "paper:1", "paper:2"),  # collides
            self._make_edge("e:new2", "paper:1", "paper:2"),
        ]

        with pytest.raises(GraphStoreDuplicateError, match="duplicate edge_id"):
            graph_store.add_edges_batch(batch)

        # None of the new edges should be inserted.
        assert graph_store.get_edge_count() == baseline
        assert graph_store.get_edge("e:new1") is None
        assert graph_store.get_edge("e:new2") is None

    def test_add_edges_batch_orphan_edge_rejected(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """An edge referencing a missing node fails the whole batch with FK error."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        baseline = graph_store.get_edge_count()

        batch = [
            self._make_edge("e:ok", "paper:1", "paper:2"),
            # References a node that does not exist:
            self._make_edge("e:orphan", "paper:1", "paper:nonexistent"),
        ]

        with pytest.raises(ReferentialIntegrityError):
            graph_store.add_edges_batch(batch)

        # Even the valid edge must not be inserted (transaction rolled back).
        assert graph_store.get_edge_count() == baseline
        assert graph_store.get_edge("e:ok") is None

    def test_add_edges_batch_chains_cause(self, graph_store: SQLiteGraphStore) -> None:
        """The wrapped duplicate error chains the IntegrityError as __cause__."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("e:dup", "paper:1", "paper:2", EdgeType.CITES, {})
        with pytest.raises(GraphStoreDuplicateError) as exc_info:
            graph_store.add_edges_batch(
                [self._make_edge("e:dup", "paper:1", "paper:2")]
            )
        assert isinstance(exc_info.value.__cause__, sqlite3.IntegrityError)

    def test_add_edges_batch_non_unique_non_fk_error_falls_back_to_generic(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """A non-UNIQUE non-FK IntegrityError surfaces as the generic
        ``GraphStoreError`` (not the duplicate subclass) so callers'
        recovery loops do not silently swallow it (#S5)."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        batch = [self._make_edge("e:1", "paper:1", "paper:2")]

        original_get_conn = graph_store._get_connection

        class _ConnProxy:
            def __init__(self, conn: sqlite3.Connection) -> None:
                self._conn = conn

            def __enter__(self):  # type: ignore[no-untyped-def]
                return self._conn.__enter__()

            def __exit__(self, *args):  # type: ignore[no-untyped-def]
                return self._conn.__exit__(*args)

            def executemany(self, sql: str, rows):  # type: ignore[no-untyped-def]
                raise sqlite3.IntegrityError("CHECK constraint failed: synthetic")

            def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                return self._conn.execute(*args, **kwargs)

            def close(self) -> None:
                self._conn.close()

        def get_conn() -> _ConnProxy:  # type: ignore[type-arg]
            return _ConnProxy(original_get_conn())

        with patch.object(graph_store, "_get_connection", side_effect=get_conn):
            with pytest.raises(GraphStoreError) as exc_info:
                graph_store.add_edges_batch(batch)
        assert not isinstance(exc_info.value, GraphStoreDuplicateError)
        assert "Failed to bulk insert edges" in str(exc_info.value)

    def test_add_edges_batch_rejects_oversized_batch(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Batches above ``_MAX_BULK_BATCH_SIZE`` are refused without
        opening any DB connection (DoS guard)."""
        from src.storage.intelligence_graph.unified_graph import (
            _MAX_BULK_BATCH_SIZE,
        )

        oversized = [
            self._make_edge(f"e:{i}", "paper:1", "paper:2")
            for i in range(_MAX_BULK_BATCH_SIZE + 1)
        ]
        # Patch _get_connection to fail loudly if the DB is touched.
        with patch.object(
            SQLiteGraphStore,
            "_get_connection",
            side_effect=AssertionError("connection opened for oversized batch"),
        ):
            with pytest.raises(ValueError) as exc_info:
                graph_store.add_edges_batch(oversized)

        msg = str(exc_info.value)
        assert str(len(oversized)) in msg
        assert str(_MAX_BULK_BATCH_SIZE) in msg


class TestBulkInsertVolumeSmoke:
    """Smoke test that bulk insert of 1000 nodes/edges completes and persists.

    NOT a perf benchmark — runtime is not asserted.
    """

    def test_bulk_insert_1000_nodes_smoke(self, graph_store: SQLiteGraphStore) -> None:
        """1000-node batch insert completes and persists correctly."""
        nodes = [
            GraphNode(node_id=f"p:{i}", node_type=NodeType.PAPER, properties={})
            for i in range(1000)
        ]
        graph_store.add_nodes_batch(nodes)
        assert graph_store.get_node_count() == 1000


class TestTraverseInternalBranches:
    """Branch coverage for the new batched traverse implementation.

    These tests target the small set of branches that don't otherwise fire:
    - revisiting an already-visited neighbor (skips append to next layer)
    - a row returned by neighbor query whose node row was deleted
      between the edge query and the batched node fetch (defensive
      ``fetched.get(nid) is None`` skip)
    - the empty-input early return inside ``_fetch_nodes_by_ids``
    """

    def test_traverse_skips_already_visited_neighbor(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """A diamond ensures the same neighbor is reached by two parents.

        With ``direction='both'`` the BFS will see ``paper:d`` twice (once
        via ``b`` and once via ``c``); the second visit must be skipped by
        the ``if neighbor_id in visited`` branch.
        """
        # Diamond: a -> b -> d ; a -> c -> d
        for nid in ("paper:a", "paper:b", "paper:c", "paper:d"):
            graph_store.add_node(nid, NodeType.PAPER, {})
        graph_store.add_edge("e:ab", "paper:a", "paper:b", EdgeType.CITES, {})
        graph_store.add_edge("e:ac", "paper:a", "paper:c", EdgeType.CITES, {})
        graph_store.add_edge("e:bd", "paper:b", "paper:d", EdgeType.CITES, {})
        graph_store.add_edge("e:cd", "paper:c", "paper:d", EdgeType.CITES, {})

        nodes = graph_store.traverse(
            "paper:a", [EdgeType.CITES], max_depth=3, direction="both"
        )
        # b, c, d — d only appears once even though two paths reach it.
        assert {n.node_id for n in nodes} == {"paper:b", "paper:c", "paper:d"}

    def test_traverse_handles_missing_node_row_for_neighbor(
        self, graph_store: SQLiteGraphStore, temp_db: Path
    ) -> None:
        """If a node row is missing for an edge endpoint, the batched fetch
        gracefully skips it (defensive ``fetched.get(nid) is None``)."""
        graph_store.add_node("paper:1", NodeType.PAPER, {})
        graph_store.add_node("paper:2", NodeType.PAPER, {})
        graph_store.add_edge("e:1", "paper:1", "paper:2", EdgeType.CITES, {})

        # Bypass FK CASCADE by deleting the node row directly with FKs OFF.
        conn = sqlite3.connect(str(temp_db))
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("DELETE FROM nodes WHERE node_id = 'paper:2'")
            conn.commit()
        finally:
            conn.close()

        # The edge still references paper:2 but no row exists for it.
        nodes = graph_store.traverse("paper:1", [EdgeType.CITES], max_depth=1)
        assert nodes == []

    def test_fetch_nodes_by_ids_empty_input(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """The internal helper returns ``{}`` immediately for empty input."""
        conn = graph_store._get_connection()
        try:
            assert graph_store._fetch_nodes_by_ids(conn, []) == {}
        finally:
            conn.close()

    def test_fetch_nodes_by_ids_silently_skips_missing(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Missing IDs are silently absent (no exception, no placeholder).

        This pins the documented behavior: a node may be deleted between
        edge discovery and node hydration, so the helper returns only the
        rows it actually finds.
        """
        graph_store.add_node("paper:exists", NodeType.PAPER, {})

        conn = graph_store._get_connection()
        try:
            fetched = graph_store._fetch_nodes_by_ids(
                conn, ["paper:exists", "paper:nonexistent"]
            )
        finally:
            conn.close()

        assert set(fetched.keys()) == {"paper:exists"}
        assert "paper:nonexistent" not in fetched

    @pytest.mark.parametrize("n", [500, 501, 1000, 1500])
    def test_fetch_nodes_by_ids_chunks_at_boundary(
        self, graph_store: SQLiteGraphStore, n: int
    ) -> None:
        """The IN-clause is chunked at 500. Verify chunk count = ceil(n/500)
        for representative N values around and above the boundary."""
        # Insert n nodes via the bulk path (well under the 10K cap).
        nodes = [
            GraphNode(node_id=f"chunk:{i}", node_type=NodeType.PAPER, properties={})
            for i in range(n)
        ]
        graph_store.add_nodes_batch(nodes)
        node_ids = [f"chunk:{i}" for i in range(n)]

        # Wrap the connection to count IN-clause node-fetch queries.
        original_get_connection = graph_store._get_connection
        in_clause_queries: list[str] = []

        class _CountingConn:
            def __init__(self, conn: sqlite3.Connection) -> None:
                self._conn = conn

            def execute(self, sql: str, *args: object, **kwargs: object) -> object:
                norm = " ".join(sql.split()).upper()
                if "FROM NODES WHERE NODE_ID IN" in norm:
                    in_clause_queries.append(norm)
                return self._conn.execute(sql, *args, **kwargs)

            def commit(self) -> None:
                self._conn.commit()

            def rollback(self) -> None:
                self._conn.rollback()

            def close(self) -> None:
                self._conn.close()

        conn = _CountingConn(original_get_connection())
        try:
            fetched = graph_store._fetch_nodes_by_ids(
                conn,  # type: ignore[arg-type]
                node_ids,
            )
        finally:
            conn.close()

        # All inserted ids should be returned across the chunks.
        assert len(fetched) == n
        # Expected chunk count = ceil(n / 500).
        expected_chunks = (n + 499) // 500
        assert len(in_clause_queries) == expected_chunks, (
            f"expected {expected_chunks} IN-clause queries for n={n}, "
            f"got {len(in_clause_queries)}"
        )


class TestListOutgoingEdgesForNodes:
    """Coverage for ``_list_outgoing_edges_for_nodes`` — bulk fan-out
    helper added in PR #146 to replace per-node ``traverse`` calls in
    the recommender's bridge-paper strategy."""

    def test_returns_empty_dict_for_empty_source_ids(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Empty source_ids short-circuits to {}."""
        result = graph_store._list_outgoing_edges_for_nodes(
            source_ids=[],
            edge_type_values=[EdgeType.CITES.value],
        )
        assert result == {}

    def test_returns_empty_dict_for_empty_edge_types(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Empty edge_type_values short-circuits to {}."""
        graph_store.add_node("paper:a", NodeType.PAPER, {})
        result = graph_store._list_outgoing_edges_for_nodes(
            source_ids=["paper:a"],
            edge_type_values=[],
        )
        assert result == {}

    def test_returns_targets_grouped_by_source(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Targets are grouped under their source id."""
        for nid in ("paper:a", "paper:b", "paper:c", "paper:d"):
            graph_store.add_node(nid, NodeType.PAPER, {})
        graph_store.add_edge("edge:1", "paper:a", "paper:c", EdgeType.CITES, {})
        graph_store.add_edge("edge:2", "paper:a", "paper:d", EdgeType.CITES, {})
        graph_store.add_edge("edge:3", "paper:b", "paper:c", EdgeType.CITES, {})

        result = graph_store._list_outgoing_edges_for_nodes(
            source_ids=["paper:a", "paper:b"],
            edge_type_values=[EdgeType.CITES.value],
        )
        assert set(result.keys()) == {"paper:a", "paper:b"}
        assert sorted(result["paper:a"]) == ["paper:c", "paper:d"]
        assert result["paper:b"] == ["paper:c"]

    def test_filters_by_edge_type(self, graph_store: SQLiteGraphStore) -> None:
        """Only requested edge types appear in the result."""
        graph_store.add_node("paper:a", NodeType.PAPER, {})
        graph_store.add_node("paper:b", NodeType.PAPER, {})
        graph_store.add_node("paper:c", NodeType.PAPER, {})
        graph_store.add_edge("edge:cites", "paper:a", "paper:b", EdgeType.CITES, {})
        graph_store.add_edge(
            "edge:cited_by",
            "paper:a",
            "paper:c",
            EdgeType.CITED_BY,
            {},
        )

        result = graph_store._list_outgoing_edges_for_nodes(
            source_ids=["paper:a"],
            edge_type_values=[EdgeType.CITES.value],
        )
        assert result == {"paper:a": ["paper:b"]}

    def test_omits_sources_with_no_outgoing_edges(
        self, graph_store: SQLiteGraphStore
    ) -> None:
        """Source ids with no matching outgoing edges are absent (not empty list)."""
        graph_store.add_node("paper:a", NodeType.PAPER, {})
        graph_store.add_node("paper:b", NodeType.PAPER, {})

        result = graph_store._list_outgoing_edges_for_nodes(
            source_ids=["paper:a", "paper:b"],
            edge_type_values=[EdgeType.CITES.value],
        )
        assert result == {}

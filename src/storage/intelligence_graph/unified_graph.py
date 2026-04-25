"""Unified Graph Store for Research Intelligence.

This module provides:
- GraphStore Protocol for backend abstraction (SQLite -> Neo4j migration path)
- SQLiteGraphStore implementation with full CRUD operations
- Graph traversal and algorithm support
- Optimistic locking for concurrent access
- PRAGMA foreign_keys enforcement for referential integrity
"""

import json
import re
import sqlite3
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

import structlog

from src.services.intelligence.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    GraphStoreError,
    NodeNotFoundError,
    NodeType,
    OptimisticLockError,
    ReferentialIntegrityError,
)
from src.storage.intelligence_graph.migrations import MigrationManager
from src.storage.intelligence_graph.path_utils import sanitize_storage_path

logger = structlog.get_logger()


# Strict pattern for property keys used in JSONPath expressions.
# Prevents JSONPath injection in search_nodes by ensuring only safe identifier
# characters are used (alphanumeric, underscore, max 64 chars).
_PROPERTY_KEY_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


@runtime_checkable
class GraphStore(Protocol):
    """Abstract graph storage interface for migration flexibility.

    This protocol defines the contract for graph storage backends.
    Implementations must support:
    - Node CRUD operations
    - Edge CRUD operations
    - Graph traversal (BFS/DFS)
    - Algorithm support (PageRank stub for SQLite)

    Migration Path:
    - SQLiteGraphStore: MVP implementation, suitable for <100K nodes
    - Neo4jGraphStore: Future implementation for production scale
    """

    # Node operations
    def add_node(
        self, node_id: str, node_type: NodeType, properties: dict[str, Any]
    ) -> GraphNode:
        """Add a new node to the graph.

        Args:
            node_id: Unique node identifier
            node_type: Type of node
            properties: Node properties

        Returns:
            Created GraphNode

        Raises:
            GraphStoreError: If node already exists
        """
        ...  # pragma: no cover - Protocol abstract method

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by ID.

        Args:
            node_id: Node identifier

        Returns:
            GraphNode if found, None otherwise
        """
        ...  # pragma: no cover - Protocol abstract method

    def update_node(
        self,
        node_id: str,
        properties: dict[str, Any],
        expected_version: Optional[int] = None,
    ) -> GraphNode:
        """Update node properties with optimistic locking.

        Args:
            node_id: Node identifier
            properties: New properties (merged with existing)
            expected_version: Expected version for optimistic locking

        Returns:
            Updated GraphNode

        Raises:
            NodeNotFoundError: If node doesn't exist
            OptimisticLockError: If version mismatch
        """
        ...  # pragma: no cover - Protocol abstract method

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and its edges.

        Args:
            node_id: Node identifier

        Returns:
            True if deleted, False if not found
        """
        ...  # pragma: no cover - Protocol abstract method

    # Edge operations
    def add_edge(
        self,
        edge_id: str,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        properties: dict[str, Any],
    ) -> GraphEdge:
        """Add a new edge to the graph.

        Args:
            edge_id: Unique edge identifier
            source_id: Source node ID
            target_id: Target node ID
            edge_type: Type of edge
            properties: Edge properties

        Returns:
            Created GraphEdge

        Raises:
            ReferentialIntegrityError: If source or target node doesn't exist
        """
        ...  # pragma: no cover - Protocol abstract method

    def get_edge(self, edge_id: str) -> Optional[GraphEdge]:
        """Get an edge by ID.

        Args:
            edge_id: Edge identifier

        Returns:
            GraphEdge if found, None otherwise
        """
        ...  # pragma: no cover - Protocol abstract method

    def get_edges(
        self,
        node_id: str,
        direction: str = "both",
        edge_type: Optional[EdgeType] = None,
    ) -> list[GraphEdge]:
        """Get edges connected to a node.

        Args:
            node_id: Node identifier
            direction: "outgoing", "incoming", or "both"
            edge_type: Filter by edge type (optional)

        Returns:
            List of connected edges
        """
        ...  # pragma: no cover - Protocol abstract method

    def delete_edge(self, edge_id: str) -> bool:
        """Delete an edge.

        Args:
            edge_id: Edge identifier

        Returns:
            True if deleted, False if not found
        """
        ...  # pragma: no cover - Protocol abstract method

    # Graph traversal
    def traverse(
        self,
        start_id: str,
        edge_types: list[EdgeType],
        max_depth: int,
        direction: str = "outgoing",
    ) -> list[GraphNode]:
        """Traverse the graph using BFS.

        Args:
            start_id: Starting node ID
            edge_types: Edge types to follow
            max_depth: Maximum traversal depth
            direction: "outgoing", "incoming", or "both"

        Returns:
            List of visited nodes (excluding start)
        """
        ...  # pragma: no cover - Protocol abstract method

    def shortest_path(
        self, source_id: str, target_id: str
    ) -> Optional[list[GraphNode]]:
        """Find shortest path between two nodes.

        Args:
            source_id: Source node ID
            target_id: Target node ID

        Returns:
            List of nodes in path, or None if no path exists
        """
        ...  # pragma: no cover - Protocol abstract method

    # Metrics
    def get_node_count(self, node_type: Optional[NodeType] = None) -> int:
        """Get total node count.

        Args:
            node_type: Filter by node type (optional)

        Returns:
            Number of nodes
        """
        ...  # pragma: no cover - Protocol abstract method

    def get_edge_count(self, edge_type: Optional[EdgeType] = None) -> int:
        """Get total edge count.

        Args:
            edge_type: Filter by edge type (optional)

        Returns:
            Number of edges
        """
        ...  # pragma: no cover - Protocol abstract method


class SQLiteGraphStore:
    """SQLite implementation of GraphStore.

    Features:
    - Full CRUD for nodes and edges
    - BFS/DFS graph traversal
    - PageRank computation (iterative, in-memory)
    - Optimistic locking with version column
    - Foreign key enforcement for referential integrity
    - Proactive node count monitoring

    Migration Triggers:
    - Warning at 75K nodes
    - Consider migration at 100K nodes

    Usage:
        store = SQLiteGraphStore("./data/intelligence/graph.db")
        store.initialize()  # Apply migrations

        # Add nodes
        paper = store.add_node("paper:arxiv:1234", NodeType.PAPER, {"title": "..."})

        # Add edges
        edge = store.add_edge(
            "edge:cites:1234:5678",
            "paper:arxiv:1234",
            "paper:arxiv:5678",
            EdgeType.CITES,
            {}
        )

        # Traverse
        related = store.traverse("paper:arxiv:1234", [EdgeType.CITES], max_depth=2)
    """

    def __init__(self, db_path: Path | str):
        """Initialize SQLite graph store.

        Args:
            db_path: Path to SQLite database file. Must reside under one of
                the approved storage roots (``data/``, ``cache/``, or the
                system temp directory). See ``sanitize_storage_path``.
        """
        self.db_path = sanitize_storage_path(db_path)
        self._migration_manager = MigrationManager(self.db_path)
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the database with migrations.

        This must be called before any other operations.
        """
        migrations_applied = self._migration_manager.migrate()
        if migrations_applied > 0:
            logger.info(
                "graph_store_initialized",
                db_path=str(self.db_path),
                migrations_applied=migrations_applied,
            )
        self._initialized = True

        # Check node count thresholds
        warning = self._migration_manager.check_node_count_threshold()
        if warning:
            logger.warning("node_count_threshold", message=warning)

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection configured for safe concurrent access.

        Pragmas applied:
        - ``foreign_keys=ON``: referential integrity (CRITICAL)
        - ``journal_mode=WAL``: writers don't block readers
        - ``synchronous=NORMAL``: durability vs. throughput trade-off
        - ``busy_timeout=5000``: wait up to 5s for locks before failing

        Returns:
            SQLite connection ready for use.

        Raises:
            GraphStoreError: If store not initialized.
        """
        if not self._initialized:
            raise GraphStoreError(
                "GraphStore not initialized. Call initialize() first."
            )

        conn = sqlite3.connect(str(self.db_path))
        # CRITICAL: Enable foreign keys for referential integrity
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.row_factory = sqlite3.Row
        return conn

    def _serialize_properties(self, properties: dict[str, Any]) -> str:
        """Serialize properties to JSON string."""
        return json.dumps(properties, default=str)

    def _deserialize_properties(self, json_str: str) -> dict[str, Any]:
        """Deserialize properties from JSON string."""
        return json.loads(json_str) if json_str else {}

    def _row_to_node(self, row: sqlite3.Row) -> GraphNode:
        """Convert a database row to GraphNode."""
        return GraphNode(
            node_id=row["node_id"],
            node_type=NodeType(row["node_type"]),
            properties=self._deserialize_properties(row["properties"]),
            version=row["version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_edge(self, row: sqlite3.Row) -> GraphEdge:
        """Convert a database row to GraphEdge."""
        return GraphEdge(
            edge_id=row["edge_id"],
            edge_type=EdgeType(row["edge_type"]),
            source_id=row["source_id"],
            target_id=row["target_id"],
            properties=self._deserialize_properties(row["properties"] or "{}"),
            version=row["version"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # Node operations

    def add_node(
        self, node_id: str, node_type: NodeType, properties: dict[str, Any]
    ) -> GraphNode:
        """Add a new node to the graph."""
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            props_json = self._serialize_properties(properties)

            conn.execute(
                """
                INSERT INTO nodes (node_id, node_type, properties, version,
                                   created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (node_id, node_type.value, props_json, now, now),
            )
            conn.commit()

            logger.debug("node_added", node_id=node_id, node_type=node_type.value)

            return GraphNode(
                node_id=node_id,
                node_type=node_type,
                properties=properties,
                version=1,
                created_at=datetime.fromisoformat(now),
                updated_at=datetime.fromisoformat(now),
            )
        except sqlite3.IntegrityError as e:
            conn.rollback()
            if "UNIQUE constraint failed" in str(e):
                raise GraphStoreError(f"Node already exists: {node_id}")
            logger.error("node_add_integrity_error", node_id=node_id, error=str(e))
            raise GraphStoreError(f"Failed to add node: {e}")
        finally:
            conn.close()

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
            row = cursor.fetchone()
            return self._row_to_node(row) if row else None
        finally:
            conn.close()

    def update_node(
        self,
        node_id: str,
        properties: dict[str, Any],
        expected_version: Optional[int] = None,
    ) -> GraphNode:
        """Update node properties with optimistic locking.

        Uses ``BEGIN IMMEDIATE`` to acquire a write lock at the start of the
        read+update sequence so concurrent writers serialize and the
        optimistic-lock check observes the same version it later updates.
        """
        conn = self._get_connection()
        try:
            # Acquire write lock up-front to prevent the read-then-update race
            conn.execute("BEGIN IMMEDIATE")

            # Get current node
            cursor = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
            row = cursor.fetchone()

            if not row:
                conn.rollback()
                raise NodeNotFoundError(node_id)

            current_version = row["version"]

            # Check version for optimistic locking
            if expected_version is not None and current_version != expected_version:
                conn.rollback()
                raise OptimisticLockError(node_id, expected_version, current_version)

            # Merge properties
            current_props = self._deserialize_properties(row["properties"])
            merged_props = {**current_props, **properties}
            try:
                props_json = self._serialize_properties(merged_props)
            except (TypeError, ValueError) as e:
                conn.rollback()
                logger.error(
                    "node_update_serialize_failed",
                    node_id=node_id,
                    error=str(e),
                )
                raise GraphStoreError(f"Failed to update node: {e}")

            now = datetime.now(timezone.utc).isoformat()
            new_version = current_version + 1

            # Update with version increment
            cursor = conn.execute(
                """
                UPDATE nodes
                SET properties = ?, version = ?, updated_at = ?
                WHERE node_id = ? AND version = ?
                """,
                (props_json, new_version, now, node_id, current_version),
            )

            if cursor.rowcount == 0:
                # Concurrent modification detected: re-query actual version
                # so the error reports the truth, not a guess.
                actual_cursor = conn.execute(
                    "SELECT version FROM nodes WHERE node_id = ?", (node_id,)
                )
                actual_row = actual_cursor.fetchone()
                conn.rollback()
                actual_version = (
                    actual_row["version"] if actual_row else current_version
                )
                raise OptimisticLockError(node_id, current_version, actual_version)

            conn.commit()

            logger.debug(
                "node_updated",
                node_id=node_id,
                old_version=current_version,
                new_version=new_version,
            )

            return GraphNode(
                node_id=node_id,
                node_type=NodeType(row["node_type"]),
                properties=merged_props,
                version=new_version,
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(now),
            )
        finally:
            conn.close()

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and its edges (via CASCADE)."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("DELETE FROM nodes WHERE node_id = ?", (node_id,))
            conn.commit()
            deleted = cursor.rowcount > 0

            if deleted:
                logger.debug("node_deleted", node_id=node_id)

            return deleted
        finally:
            conn.close()

    # Edge operations

    def add_edge(
        self,
        edge_id: str,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        properties: dict[str, Any],
    ) -> GraphEdge:
        """Add a new edge to the graph."""
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            props_json = self._serialize_properties(properties)

            conn.execute(
                """
                INSERT INTO edges (edge_id, edge_type, source_id, target_id,
                                   properties, version, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (edge_id, edge_type.value, source_id, target_id, props_json, now),
            )
            conn.commit()

            logger.debug(
                "edge_added",
                edge_id=edge_id,
                edge_type=edge_type.value,
                source_id=source_id,
                target_id=target_id,
            )

            return GraphEdge(
                edge_id=edge_id,
                edge_type=edge_type,
                source_id=source_id,
                target_id=target_id,
                properties=properties,
                version=1,
                created_at=datetime.fromisoformat(now),
            )
        except sqlite3.IntegrityError as e:
            conn.rollback()
            if "FOREIGN KEY constraint failed" in str(e):
                raise ReferentialIntegrityError(
                    f"Source or target node not found: {source_id}, {target_id}"
                )
            if "UNIQUE constraint failed" in str(e):
                raise GraphStoreError(f"Edge already exists: {edge_id}")
            logger.error(
                "edge_add_integrity_error",
                edge_id=edge_id,
                source_id=source_id,
                target_id=target_id,
                error=str(e),
            )
            raise GraphStoreError(f"Failed to add edge: {e}")
        finally:
            conn.close()

    def get_edge(self, edge_id: str) -> Optional[GraphEdge]:
        """Get an edge by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT * FROM edges WHERE edge_id = ?", (edge_id,))
            row = cursor.fetchone()
            return self._row_to_edge(row) if row else None
        finally:
            conn.close()

    def get_edges(
        self,
        node_id: str,
        direction: str = "both",
        edge_type: Optional[EdgeType] = None,
    ) -> list[GraphEdge]:
        """Get edges connected to a node."""
        conn = self._get_connection()
        try:
            edges: list[GraphEdge] = []

            if direction in ("outgoing", "both"):
                if edge_type:
                    cursor = conn.execute(
                        "SELECT * FROM edges WHERE source_id = ? AND edge_type = ?",
                        (node_id, edge_type.value),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT * FROM edges WHERE source_id = ?", (node_id,)
                    )
                edges.extend(self._row_to_edge(row) for row in cursor.fetchall())

            if direction in ("incoming", "both"):
                if edge_type:
                    cursor = conn.execute(
                        "SELECT * FROM edges WHERE target_id = ? AND edge_type = ?",
                        (node_id, edge_type.value),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT * FROM edges WHERE target_id = ?", (node_id,)
                    )
                edges.extend(self._row_to_edge(row) for row in cursor.fetchall())

            return edges
        finally:
            conn.close()

    def delete_edge(self, edge_id: str) -> bool:
        """Delete an edge."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("DELETE FROM edges WHERE edge_id = ?", (edge_id,))
            conn.commit()
            deleted = cursor.rowcount > 0

            if deleted:
                logger.debug("edge_deleted", edge_id=edge_id)

            return deleted
        finally:
            conn.close()

    # Graph traversal

    def traverse(
        self,
        start_id: str,
        edge_types: list[EdgeType],
        max_depth: int,
        direction: str = "outgoing",
    ) -> list[GraphNode]:
        """Traverse the graph using BFS."""
        if max_depth < 1:
            return []

        conn = self._get_connection()
        try:
            visited: set[str] = {start_id}
            result: list[GraphNode] = []
            queue: deque[tuple[str, int]] = deque([(start_id, 0)])

            edge_type_values = [et.value for et in edge_types]
            placeholders = ",".join("?" * len(edge_type_values))

            while queue:
                current_id, depth = queue.popleft()

                if depth >= max_depth:
                    continue

                # Get connected edges based on direction
                if direction == "outgoing":
                    cursor = conn.execute(
                        f"""
                        SELECT target_id as neighbor_id
                        FROM edges
                        WHERE source_id = ? AND edge_type IN ({placeholders})
                        """,
                        (current_id, *edge_type_values),
                    )
                elif direction == "incoming":
                    cursor = conn.execute(
                        f"""
                        SELECT source_id as neighbor_id
                        FROM edges
                        WHERE target_id = ? AND edge_type IN ({placeholders})
                        """,
                        (current_id, *edge_type_values),
                    )
                else:  # both
                    cursor = conn.execute(
                        f"""
                        SELECT target_id as neighbor_id
                        FROM edges
                        WHERE source_id = ? AND edge_type IN ({placeholders})
                        UNION
                        SELECT source_id as neighbor_id
                        FROM edges
                        WHERE target_id = ? AND edge_type IN ({placeholders})
                        """,
                        (current_id, *edge_type_values, current_id, *edge_type_values),
                    )

                for row in cursor.fetchall():
                    neighbor_id = row["neighbor_id"]
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        queue.append((neighbor_id, depth + 1))

                        # Fetch neighbor node
                        node_cursor = conn.execute(
                            "SELECT * FROM nodes WHERE node_id = ?",
                            (neighbor_id,),
                        )
                        node_row = node_cursor.fetchone()
                        if node_row:
                            result.append(self._row_to_node(node_row))

            return result
        finally:
            conn.close()

    def shortest_path(
        self, source_id: str, target_id: str
    ) -> Optional[list[GraphNode]]:
        """Find shortest path between two nodes using BFS."""
        if source_id == target_id:
            node = self.get_node(source_id)
            return [node] if node else None

        conn = self._get_connection()
        try:
            visited: set[str] = {source_id}
            queue: deque[tuple[str, list[str]]] = deque([(source_id, [source_id])])

            while queue:
                current_id, path = queue.popleft()

                # Get all neighbors
                cursor = conn.execute(
                    """
                    SELECT target_id as neighbor_id FROM edges WHERE source_id = ?
                    UNION
                    SELECT source_id as neighbor_id FROM edges WHERE target_id = ?
                    """,
                    (current_id, current_id),
                )

                for row in cursor.fetchall():
                    neighbor_id = row["neighbor_id"]

                    if neighbor_id == target_id:
                        # Found target - build result path
                        final_path = path + [neighbor_id]
                        result = []
                        for node_id in final_path:
                            node_cursor = conn.execute(
                                "SELECT * FROM nodes WHERE node_id = ?",
                                (node_id,),
                            )
                            node_row = node_cursor.fetchone()
                            if node_row:
                                result.append(self._row_to_node(node_row))
                        return result

                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        queue.append((neighbor_id, path + [neighbor_id]))

            return None  # No path found
        finally:
            conn.close()

    # Algorithm primitives — exposed so GraphAlgorithms can read the
    # raw graph without coupling the Protocol to specific algorithms.

    def _list_node_ids(self, node_type: Optional[NodeType] = None) -> list[str]:
        """Return every node id, optionally filtered by node type.

        Used by ``GraphAlgorithms``; not part of the GraphStore Protocol.
        """
        conn = self._get_connection()
        try:
            if node_type:
                cursor = conn.execute(
                    "SELECT node_id FROM nodes WHERE node_type = ?",
                    (node_type.value,),
                )
            else:
                cursor = conn.execute("SELECT node_id FROM nodes")
            return [row["node_id"] for row in cursor.fetchall()]
        finally:
            conn.close()

    def _list_edges_by_types(
        self, edge_type_values: list[str]
    ) -> list[tuple[str, str]]:
        """Return ``(source_id, target_id)`` tuples for the given edge types.

        Used by ``GraphAlgorithms``; not part of the GraphStore Protocol.
        """
        if not edge_type_values:
            return []
        conn = self._get_connection()
        try:
            placeholders = ",".join("?" * len(edge_type_values))
            cursor = conn.execute(
                f"""
                SELECT source_id, target_id FROM edges
                WHERE edge_type IN ({placeholders})
                """,
                tuple(edge_type_values),
            )
            return [(row["source_id"], row["target_id"]) for row in cursor.fetchall()]
        finally:
            conn.close()

    # Metrics

    def get_node_count(self, node_type: Optional[NodeType] = None) -> int:
        """Get total node count."""
        conn = self._get_connection()
        try:
            if node_type:
                cursor = conn.execute(
                    "SELECT COUNT(*) as count FROM nodes WHERE node_type = ?",
                    (node_type.value,),
                )
            else:
                cursor = conn.execute("SELECT COUNT(*) as count FROM nodes")
            row = cursor.fetchone()
            return row["count"] if row else 0
        finally:
            conn.close()

    def get_edge_count(self, edge_type: Optional[EdgeType] = None) -> int:
        """Get total edge count."""
        conn = self._get_connection()
        try:
            if edge_type:
                cursor = conn.execute(
                    "SELECT COUNT(*) as count FROM edges WHERE edge_type = ?",
                    (edge_type.value,),
                )
            else:
                cursor = conn.execute("SELECT COUNT(*) as count FROM edges")
            row = cursor.fetchone()
            return row["count"] if row else 0
        finally:
            conn.close()

    def check_thresholds(self) -> Optional[str]:
        """Check if node count is approaching migration thresholds.

        Returns:
            Warning message if threshold reached, None otherwise.
        """
        return self._migration_manager.check_node_count_threshold()

    def get_nodes_by_type(
        self, node_type: NodeType, limit: int = 100, offset: int = 0
    ) -> list[GraphNode]:
        """Get nodes of a specific type with pagination.

        Args:
            node_type: Type of nodes to retrieve
            limit: Maximum number of nodes to return
            offset: Number of nodes to skip

        Returns:
            List of GraphNode objects
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM nodes
                WHERE node_type = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (node_type.value, limit, offset),
            )
            return [self._row_to_node(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def search_nodes(
        self,
        property_key: str,
        property_value: str,
        node_type: Optional[NodeType] = None,
        limit: int = 100,
    ) -> list[GraphNode]:
        """Search nodes by property value (exact match in JSON).

        ``property_key`` is interpolated into a SQLite JSONPath
        (``$.<property_key>``) and is therefore validated against
        ``_PROPERTY_KEY_PATTERN`` to prevent JSONPath injection. Only
        identifier-like keys (``[A-Za-z_][A-Za-z0-9_]{0,63}``) are accepted.

        Args:
            property_key: Property key to search (validated)
            property_value: Property value to match
            node_type: Filter by node type (optional)
            limit: Maximum number of nodes to return

        Returns:
            List of matching GraphNode objects

        Raises:
            ValueError: If ``property_key`` does not match the safe pattern.
        """
        if not _PROPERTY_KEY_PATTERN.match(property_key or ""):
            raise ValueError(f"Invalid property_key: {property_key!r}")

        conn = self._get_connection()
        try:
            # Use JSON extraction for property search
            if node_type:
                cursor = conn.execute(
                    """
                    SELECT * FROM nodes
                    WHERE node_type = ?
                    AND json_extract(properties, ?) = ?
                    LIMIT ?
                    """,
                    (node_type.value, f"$.{property_key}", property_value, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM nodes
                    WHERE json_extract(properties, ?) = ?
                    LIMIT ?
                    """,
                    (f"$.{property_key}", property_value, limit),
                )
            return [self._row_to_node(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def close(self) -> None:
        """Clean up resources.

        Note: SQLite connections are created per-operation,
        so this is mainly for interface consistency.
        """
        pass

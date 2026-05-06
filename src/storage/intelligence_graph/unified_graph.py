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
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

import structlog

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
from src.storage.intelligence_graph.migrations import MigrationManager
from src.storage.intelligence_graph.path_utils import sanitize_storage_path

logger = structlog.get_logger()


# Maximum number of placeholders to embed in a single SQL ``IN (?, ?, ...)``
# clause when batching node fetches per BFS layer. Chosen well below SQLite's
# default ``SQLITE_MAX_VARIABLE_NUMBER`` (999 historically, 32766 since 3.32).
# 500 keeps planner cost and parse time small while still collapsing typical
# BFS layers into a single round-trip.
_BATCH_NODE_FETCH_CHUNK_SIZE = 500


# Maximum number of rows accepted by a single ``add_nodes_batch`` /
# ``add_edges_batch`` call. This is a DoS guard: each row holds a
# JSON-serialized properties blob in memory while the executemany payload is
# constructed, so an unbounded count from an untrusted upstream caller could
# easily push 10MB+ of memory pressure (and a multi-second pause) per call.
# Callers with more rows must chunk upstream — that keeps the chunking policy
# explicit at the call site instead of hidden inside the storage layer.
_MAX_BULK_BATCH_SIZE = 10_000


# Strict pattern for property keys used in JSONPath expressions.
#
# JSONPath injection rationale:
#
# (a) ``search_nodes`` interpolates ``property_key`` into a SQLite JSONPath
#     literal of the form ``$.<key>`` and passes that literal as a parameter
#     to ``json_extract(properties, ?)``. SQLite's ``json_extract`` accepts
#     a rich JSONPath grammar — segments like ``$.foo.bar``, array indexing
#     ``$.foo[0]``, bracketed string keys ``$.foo['key']``, and so on — so an
#     unvalidated key allows the caller to escape the intended single-segment
#     path and reach into arbitrary parts of the JSON document, change the
#     semantics of the query, or trigger pathological evaluation.
#
# (b) The chosen identifier-style pattern is intentionally **stricter** than
#     JSON allows. JSON property names may contain spaces, quotes, brackets,
#     and Unicode; we deliberately admit only ``[A-Za-z_][A-Za-z0-9_]{0,63}``
#     so that no JSONPath metacharacter (``.``, ``[``, ``]``, ``'``, ``"``,
#     ``$``, whitespace, etc.) can appear inside the interpolated segment.
#     This is a defense-in-depth measure on top of parameter binding because
#     parameter binding does not parse the JSONPath grammar — the user input
#     is taken as a literal path string by ``json_extract``.
#
# (c) If a legitimate property uses a non-matching name (e.g., contains
#     ``-`` or ``.``), it should be **remapped at the data layer**
#     (rename on ingest, or store under an alias) rather than relaxing this
#     regex. Loosening the regex anywhere weakens the JSONPath injection
#     guarantee for every caller.
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

    def add_nodes_batch(self, nodes: Sequence[GraphNode]) -> None:
        """Insert many nodes atomically in a single transaction.

        Implementations must roll back the entire batch on any constraint
        violation (e.g. duplicate ``node_id``) so callers can retry safely.

        Args:
            nodes: Sequence of fully-formed ``GraphNode`` instances.

        Raises:
            GraphStoreError: If any node violates a constraint; the batch
                is rolled back and no nodes are persisted.
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

    def add_edges_batch(self, edges: Sequence[GraphEdge]) -> None:
        """Insert many edges atomically in a single transaction.

        Implementations must roll back the entire batch on any constraint
        violation (duplicate ``edge_id``, missing source/target) so callers
        can retry safely.

        Args:
            edges: Sequence of fully-formed ``GraphEdge`` instances.

        Raises:
            ReferentialIntegrityError: If any edge references a missing node;
                the batch is rolled back and no edges are persisted.
            GraphStoreError: For other constraint violations; the batch is
                rolled back and no edges are persisted.
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

        TODO(phase-10): consolidate onto
            ``src.storage.intelligence_graph.connection.open_connection``
            once this store moves to the per-operation context-manager
            pattern used by ``SubscriptionManager`` /
            ``MonitoringRunRepository``.
        """
        if not self._initialized:
            raise GraphStoreError(
                "GraphStore not initialized. Call initialize() first."
            )

        # NOTE: ``isolation_level`` is intentionally left at sqlite3's default
        # ("deferred") so that ``with conn:`` provides real transactional
        # ``BEGIN``/``COMMIT``/``ROLLBACK`` semantics — this is what the bulk
        # insert paths and ``update_node``'s ``BEGIN IMMEDIATE`` rely on.
        # Future maintainers must NOT switch to ``isolation_level=None`` /
        # ``autocommit=True`` without auditing every ``with conn:`` and
        # explicit transaction call site in this module.
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
                # Typed signal so callers performing best-effort idempotent
                # inserts can ``except GraphStoreDuplicateError`` instead of
                # substring-matching on the message text.
                raise GraphStoreDuplicateError(f"Node already exists: {node_id}")
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

    def add_nodes_batch(self, nodes: Sequence[GraphNode]) -> None:
        """Insert many nodes atomically via ``executemany`` in one tx.

        - Empty input is a true no-op: no connection is opened.
        - On any constraint violation, the **entire** batch is rolled back
          (transaction semantics) and a ``GraphStoreError`` is raised with
          the underlying ``sqlite3.IntegrityError`` chained as ``__cause__``.
        - Logs a single ``bulk_insert_nodes`` INFO record on success with
          the row count.

        Caller-supplied ``GraphNode.created_at``/``updated_at``/``version``
        are honored (they are backend-managed defaults set by the model).
        """
        if not nodes:
            return

        # DoS guard: reject oversized batches before opening any connection
        # or building the row payload. See ``_MAX_BULK_BATCH_SIZE``.
        if len(nodes) > _MAX_BULK_BATCH_SIZE:
            raise ValueError(
                f"Batch size {len(nodes)} exceeds maximum "
                f"{_MAX_BULK_BATCH_SIZE}; chunk the input upstream"
            )

        rows = [
            (
                n.node_id,
                n.node_type.value,
                self._serialize_properties(n.properties),
                n.version,
                n.created_at.isoformat(),
                n.updated_at.isoformat(),
            )
            for n in nodes
        ]

        conn = self._get_connection()
        try:
            with conn:  # commit on success / rollback on exception
                conn.executemany(
                    """
                    INSERT INTO nodes (node_id, node_type, properties, version,
                                       created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            # Success log lives inside the try block (after the ``with conn:``
            # commit) so that if a future maintainer narrows the except clause
            # and accidentally swallows an error, we do NOT log a spurious
            # success record.
            logger.info("bulk_insert_nodes", count=len(rows))
        except sqlite3.IntegrityError as e:
            logger.error(
                "bulk_insert_nodes_integrity_error",
                count=len(rows),
                error=str(e),
            )
            # Distinguish duplicate-id collisions (typical re-run) from
            # other constraint violations so the caller's recovery path
            # can match on a typed exception (#S5).
            if "UNIQUE constraint failed" in str(e):
                raise GraphStoreDuplicateError(
                    f"Failed to bulk insert nodes (duplicate node_id): {e}"
                ) from e
            raise GraphStoreError(f"Failed to bulk insert nodes: {e}") from e
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
            # TODO(#134): wrap in retry_on_lock_contention
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
                # Typed signal — see ``add_node`` for rationale.
                raise GraphStoreDuplicateError(f"Edge already exists: {edge_id}")
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

    def add_edges_batch(self, edges: Sequence[GraphEdge]) -> None:
        """Insert many edges atomically via ``executemany`` in one tx.

        - Empty input is a true no-op: no connection is opened.
        - On a foreign-key violation (orphan edge), the **entire** batch is
          rolled back and a ``ReferentialIntegrityError`` is raised with the
          underlying ``sqlite3.IntegrityError`` chained as ``__cause__``.
        - On any other constraint violation (e.g. duplicate ``edge_id``),
          a ``GraphStoreError`` is raised with the same chaining.
        - Logs a single ``bulk_insert_edges`` INFO record on success with
          the row count.
        """
        if not edges:
            return

        # DoS guard: reject oversized batches before opening any connection
        # or building the row payload. See ``_MAX_BULK_BATCH_SIZE``.
        if len(edges) > _MAX_BULK_BATCH_SIZE:
            raise ValueError(
                f"Batch size {len(edges)} exceeds maximum "
                f"{_MAX_BULK_BATCH_SIZE}; chunk the input upstream"
            )

        rows = [
            (
                e.edge_id,
                e.edge_type.value,
                e.source_id,
                e.target_id,
                self._serialize_properties(e.properties),
                e.version,
                e.created_at.isoformat(),
            )
            for e in edges
        ]

        conn = self._get_connection()
        try:
            with conn:  # commit on success / rollback on exception
                conn.executemany(
                    """
                    INSERT INTO edges (edge_id, edge_type, source_id, target_id,
                                       properties, version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            # Success log lives inside the try block (after the ``with conn:``
            # commit) so that if a future maintainer narrows the except clause
            # and accidentally swallows an error, we do NOT log a spurious
            # success record.
            logger.info("bulk_insert_edges", count=len(rows))
        except sqlite3.IntegrityError as e:
            logger.error(
                "bulk_insert_edges_integrity_error",
                count=len(rows),
                error=str(e),
            )
            if "FOREIGN KEY constraint failed" in str(e):
                raise ReferentialIntegrityError(
                    f"Bulk edge insert hit a missing source/target node: {e}"
                ) from e
            # Distinguish duplicate-id collisions from other constraint
            # violations so the caller's recovery path can match on a
            # typed exception (#S5).
            if "UNIQUE constraint failed" in str(e):
                raise GraphStoreDuplicateError(
                    f"Failed to bulk insert edges (duplicate edge_id): {e}"
                ) from e
            raise GraphStoreError(f"Failed to bulk insert edges: {e}") from e
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
        """Traverse the graph using BFS.

        Performance: neighbor node rows are fetched in **one batched query
        per BFS layer** (``SELECT * FROM nodes WHERE node_id IN (...)``)
        rather than one query per neighbor. The ``IN``-list is chunked at
        ``_BATCH_NODE_FETCH_CHUNK_SIZE`` to stay safely under SQLite's
        bind-parameter limit. The bidirectional neighbor query uses
        ``UNION ALL`` (not ``UNION``) because the BFS ``visited`` set
        already deduplicates ids — the ``UNION`` sort/distinct is wasted
        work on every hop.
        """
        if max_depth < 1:
            return []

        conn = self._get_connection()
        try:
            visited: set[str] = {start_id}
            result: list[GraphNode] = []
            # BFS layer-by-layer so we can batch the neighbor-node fetch.
            current_layer: list[str] = [start_id]
            depth = 0

            edge_type_values = [et.value for et in edge_types]
            placeholders = ",".join("?" * len(edge_type_values))

            while current_layer and depth < max_depth:
                next_layer_ids: list[str] = []

                for current_id in current_layer:
                    # Get connected edges based on direction
                    if direction == "outgoing":
                        cursor = conn.execute(
                            f"""
                            SELECT target_id as neighbor_id
                            FROM edges
                            WHERE source_id = ?
                              AND edge_type IN ({placeholders})
                            """,
                            (current_id, *edge_type_values),
                        )
                    elif direction == "incoming":
                        cursor = conn.execute(
                            f"""
                            SELECT source_id as neighbor_id
                            FROM edges
                            WHERE target_id = ?
                              AND edge_type IN ({placeholders})
                            """,
                            (current_id, *edge_type_values),
                        )
                    else:  # both
                        # UNION ALL is intentional: visited set dedupes; the
                        # implicit DISTINCT in plain UNION would be wasted work.
                        cursor = conn.execute(
                            f"""
                            SELECT target_id as neighbor_id
                            FROM edges
                            WHERE source_id = ?
                              AND edge_type IN ({placeholders})
                            UNION ALL
                            SELECT source_id as neighbor_id
                            FROM edges
                            WHERE target_id = ?
                              AND edge_type IN ({placeholders})
                            """,
                            (
                                current_id,
                                *edge_type_values,
                                current_id,
                                *edge_type_values,
                            ),
                        )

                    for row in cursor.fetchall():
                        neighbor_id = row["neighbor_id"]
                        if neighbor_id not in visited:
                            visited.add(neighbor_id)
                            next_layer_ids.append(neighbor_id)

                # Batch-fetch the entire next layer in one query (chunked).
                if next_layer_ids:
                    fetched = self._fetch_nodes_by_ids(conn, next_layer_ids)
                    # Preserve discovery order to keep traversal output stable.
                    for nid in next_layer_ids:
                        node = fetched.get(nid)
                        if node is not None:
                            result.append(node)

                current_layer = next_layer_ids
                depth += 1

            return result
        finally:
            conn.close()

    def _fetch_nodes_by_ids(
        self, conn: sqlite3.Connection, node_ids: list[str]
    ) -> dict[str, GraphNode]:
        """Fetch many node rows in a single batched query (or a few chunks).

        ``node_id`` values are bound as parameters — the placeholder string
        is constructed from a count, never from caller-supplied data — so
        SQL injection is not possible. Chunking keeps the
        ``IN (?, ?, ...)`` list bounded by
        ``_BATCH_NODE_FETCH_CHUNK_SIZE``.

        Silently skips IDs not found in the DB. This is by design — a node
        may be deleted between edge discovery and node hydration. Callers
        requiring strict consistency should re-check counts.
        """
        out: dict[str, GraphNode] = {}
        if not node_ids:
            return out

        for start in range(0, len(node_ids), _BATCH_NODE_FETCH_CHUNK_SIZE):
            chunk = node_ids[start : start + _BATCH_NODE_FETCH_CHUNK_SIZE]
            placeholders = f"({','.join('?' * len(chunk))})"
            cursor = conn.execute(
                f"SELECT * FROM nodes WHERE node_id IN {placeholders}",
                tuple(chunk),
            )
            for row in cursor.fetchall():
                node = self._row_to_node(row)
                out[node.node_id] = node
        # Note: ``out`` only contains rows that were actually found. Missing
        # ids are silently absent — callers must use ``.get(nid)`` or check
        # membership rather than indexing blindly.
        return out

    def shortest_path(
        self, source_id: str, target_id: str
    ) -> Optional[list[GraphNode]]:
        """Find shortest path between two nodes using BFS.

        Implementation note: the BFS frontier stores **only node ids**
        (``deque[str]``) and uses a ``parent: dict[str, Optional[str]]``
        map to reconstruct the path on success by walking from ``target``
        back to ``source``. This avoids the per-push ``list[str]`` copy
        that the previous implementation paid on every neighbor expansion
        (O(L) per push, O(N*L) overall for path length L).

        The bidirectional neighbor query uses ``UNION ALL``; the BFS
        ``visited`` set already deduplicates, so plain ``UNION`` is wasted
        work.
        """
        conn = self._get_connection()
        try:
            # Degenerate case: source == target. Use the same connection
            # (and the same batched-fetch helper) the BFS path uses below
            # so the early-exit goes through one consistent code path
            # instead of opening a separate connection via ``get_node``.
            if source_id == target_id:
                fetched = self._fetch_nodes_by_ids(conn, [source_id])
                node = fetched.get(source_id)
                return [node] if node else None

            visited: set[str] = {source_id}
            parent: dict[str, Optional[str]] = {source_id: None}
            queue: deque[str] = deque([source_id])

            while queue:
                current_id = queue.popleft()

                # Get all neighbors (UNION ALL: visited dedupes already)
                cursor = conn.execute(
                    """
                    SELECT target_id as neighbor_id FROM edges WHERE source_id = ?
                    UNION ALL
                    SELECT source_id as neighbor_id FROM edges WHERE target_id = ?
                    """,
                    (current_id, current_id),
                )

                for row in cursor.fetchall():
                    neighbor_id = row["neighbor_id"]
                    if neighbor_id in visited:
                        continue
                    visited.add(neighbor_id)
                    parent[neighbor_id] = current_id

                    if neighbor_id == target_id:
                        # Reconstruct path: walk parents from target → source.
                        path_ids: list[str] = []
                        cursor_id: Optional[str] = neighbor_id
                        while cursor_id is not None:
                            path_ids.append(cursor_id)
                            cursor_id = parent[cursor_id]
                        path_ids.reverse()

                        # Batch-fetch all node rows on the path.
                        fetched = self._fetch_nodes_by_ids(conn, path_ids)
                        # Silently skips IDs not found in the DB. This is by
                        # design — a node may be deleted between edge
                        # discovery and node hydration. Callers requiring
                        # strict consistency should re-check counts.
                        return [fetched[nid] for nid in path_ids if nid in fetched]

                    queue.append(neighbor_id)

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

    def _list_outgoing_edges_for_nodes(
        self,
        source_ids: list[str],
        edge_type_values: list[str],
    ) -> dict[str, list[str]]:
        """Return outgoing edge targets grouped by source, for the given nodes.

        Issues a single SQL query instead of one traverse call per node,
        making it suitable for bulk bridge-paper detection.  Only direct
        (depth-1) outgoing edges are returned.

        Args:
            source_ids: Node ids whose outgoing edges should be fetched.
            edge_type_values: Edge-type string values to filter by.

        Returns:
            A dict mapping each source id to its list of target node ids.
            Source ids with no outgoing edges are absent from the dict.
        """
        if not source_ids or not edge_type_values:
            return {}
        conn = self._get_connection()
        try:
            src_placeholders = ",".join("?" * len(source_ids))
            type_placeholders = ",".join("?" * len(edge_type_values))
            cursor = conn.execute(
                f"""
                SELECT source_id, target_id FROM edges
                WHERE source_id IN ({src_placeholders})
                  AND edge_type IN ({type_placeholders})
                """,
                tuple(source_ids) + tuple(edge_type_values),
            )
            result: dict[str, list[str]] = {}
            for row in cursor.fetchall():
                src = row["source_id"]
                result.setdefault(src, []).append(row["target_id"])
            return result
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
            ValueError: If ``property_key`` is ``None``, empty, or does not
                match the safe identifier pattern. ``None``/empty get a
                dedicated, explicit message instead of the generic
                "Invalid property_key" so misuses are easier to debug.
        """
        # Explicit None / empty handling — the generic regex error below is
        # not friendly enough for the most common misuse.
        if property_key is None or property_key == "":
            raise ValueError(
                "property_key must be a non-empty identifier-style string, "
                f"got {property_key!r}"
            )
        if not _PROPERTY_KEY_PATTERN.match(property_key):
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

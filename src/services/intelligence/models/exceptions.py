"""Shared exceptions for graph storage operations.

Hierarchy:

    Exception
        └── GraphStoreError
                ├── NodeNotFoundError
                ├── EdgeNotFoundError
                ├── ReferentialIntegrityError
                └── GraphStoreDuplicateError

    Exception
        └── OptimisticLockError  (concurrent-modification signal)

``OptimisticLockError`` is intentionally NOT a subclass of
``GraphStoreError`` so callers can distinguish "operation truly failed"
from "operation should be retried with fresh data".

``GraphStoreDuplicateError`` is a typed signal for UNIQUE-constraint
violations. Callers performing best-effort idempotent inserts (e.g. the
citation graph builder's per-row recovery path) should ``except`` this
specifically rather than substring-matching on the underlying message —
SQLite's wording is not a stable contract.
"""


class GraphStoreError(Exception):
    """Base exception for graph store operations."""

    pass


class GraphStoreDuplicateError(GraphStoreError):
    """Raised when an insert hits a UNIQUE constraint (duplicate id).

    This is a *typed* signal callers can match on instead of inspecting
    error message strings — SQLite's ``IntegrityError`` text is not a
    stable contract and would silently break per-row recovery loops if
    the underlying driver ever rephrased it. Backends other than
    SQLite (e.g. a future Neo4j store) raise this same type so the
    builder layer stays storage-agnostic.
    """

    pass


class NodeNotFoundError(GraphStoreError):
    """Raised when a node is not found in the graph."""

    def __init__(self, node_id: str):
        super().__init__(f"Node not found: {node_id}")
        self.node_id = node_id


class EdgeNotFoundError(GraphStoreError):
    """Raised when an edge is not found in the graph."""

    def __init__(self, edge_id: str):
        super().__init__(f"Edge not found: {edge_id}")
        self.edge_id = edge_id


class ReferentialIntegrityError(GraphStoreError):
    """Raised when an operation would violate referential integrity."""

    def __init__(self, message: str):
        super().__init__(message)


class OptimisticLockError(Exception):
    """Raised when optimistic locking detects a concurrent modification.

    This indicates another process modified the record between read and
    write. The caller should retry the operation with fresh data.
    """

    def __init__(self, node_id: str, expected_version: int, actual_version: int):
        message = (
            f"Concurrent modification detected for {node_id}: "
            f"expected version {expected_version}, found {actual_version}. "
            "Retry with fresh data."
        )
        super().__init__(message)
        self.node_id = node_id
        self.expected_version = expected_version
        self.actual_version = actual_version

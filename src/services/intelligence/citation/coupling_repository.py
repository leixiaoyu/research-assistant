"""Persistence for :class:`CouplingResult` (V6 ``citation_coupling``).

Why a standalone repository
---------------------------
Mirrors the layering motivation of :class:`CitationInfluenceRepository`
(PR #143): the analyzer (writer) and any future recommender (reader)
both go through this class — no other module touches the
``citation_coupling`` table directly.

Canonical-pair ordering
-----------------------
``(paper_a_id, paper_b_id)`` is stored as ``(min_id, max_id)`` so a
lookup for (A,B) and (B,A) hits the same row.  The returned
:class:`CouplingResult` always carries the **canonical** (lexicographic
min, max) order — ``get(B, A)`` returns a result whose ``paper_a_id``
is ``min(A, B)`` and ``paper_b_id`` is ``max(A, B)``.  Callers that
need to map the result back to their original ordering must re-derive
the pair from the canonical ids.  The DB's ``CHECK (paper_a_id <
paper_b_id)`` constraint enforces this at the storage layer; a
repository that fails to call min/max before INSERT will receive a
constraint error, which is the intended loud-failure mode.

Schema (created by ``MIGRATION_V6_CITATION_COUPLING_CACHE``)
------------------------------------------------------------
::

    citation_coupling(
        paper_a_id             TEXT NOT NULL,
        paper_b_id             TEXT NOT NULL,
        coupling_strength      REAL NOT NULL CHECK (…),
        shared_references_json TEXT NOT NULL,
        co_citation_count      INTEGER NOT NULL CHECK (…),
        computed_at            TEXT NOT NULL,
        PRIMARY KEY (paper_a_id, paper_b_id),
        CHECK (paper_a_id < paper_b_id)
    )

TTL semantics
-------------
``get`` filters out rows whose ``computed_at`` is older than
``max_age_days`` (default 30).  The stale row is NOT deleted on read —
:meth:`delete_stale` handles bulk cleanup.

Concurrency model
-----------------
Same as :class:`CitationInfluenceRepository`: each method opens a fresh
connection through :func:`open_connection`, applies the standard
PRAGMAs, and closes on exit.  ``record`` uses
:func:`retry_on_lock_contention` (issue #133).

Failure semantics
-----------------
``record`` RAISES :class:`sqlite3.Error` on a non-retryable write
failure — mirrors :class:`CitationInfluenceRepository.record_metrics`
(PR #143 pattern).  The caller (:meth:`CouplingAnalyzer.analyze_pair`)
is responsible for the swallow-and-log pattern so callers can opt into
loud failure if they choose a different wiring.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional, TypeVar

import structlog

from src.services.intelligence.citation.models import CouplingResult
from src.storage.intelligence_graph.connection import (
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    open_connection,
    retry_on_lock_contention,
)
from src.storage.intelligence_graph.migrations import MigrationManager
from src.storage.intelligence_graph.path_utils import sanitize_storage_path

logger = structlog.get_logger(__name__)

_T = TypeVar("_T")

# Default freshness window for ``get``.  Mirrors spec REQ-9.2.3 (30 days).
DEFAULT_MAX_AGE_DAYS: int = 30


class CitationCouplingRepository:
    """Owns the V6 ``citation_coupling`` SQLite table.

    Provides:

    - :meth:`record` upsert one :class:`CouplingResult` row.
    - :meth:`get` fetch by ``(paper_a_id, paper_b_id)`` honouring a TTL.
    - :meth:`delete_stale` bulk delete rows older than a cutoff.

    Async safety:
        ALL methods are SYNC — **async callers MUST wrap invocations in**
        ``asyncio.to_thread(...)`` per CLAUDE.md "SQLite write retry".
    """

    def __init__(self, db_path: Path | str) -> None:
        """Initialise the repository.

        Args:
            db_path: SQLite database path. Must lie under one of the
                approved storage roots — enforced by
                :func:`sanitize_storage_path`.
        """
        self.db_path = sanitize_storage_path(db_path)
        self._migrations = MigrationManager(self.db_path)
        self._initialized = False

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Apply pending schema migrations.

        Idempotent — safe to call multiple times.  Must be called before
        any read/write operation.
        """
        applied = self._migrations.migrate()
        if applied > 0:
            logger.info(
                "citation_coupling_repository_migrations_applied",
                count=applied,
                db_path=str(self.db_path),
            )
        self._initialized = True

    @classmethod
    def connect(cls, db_path: Path | str) -> "CitationCouplingRepository":
        """Construct, run pending migrations, and return a ready repo.

        Side effects (disclosed):
            1. Calls :meth:`initialize` which invokes
               :class:`~src.storage.intelligence_graph.migrations.MigrationManager`
               ``migrate()`` — applies any pending schema migrations up
               to the latest version (including V6
               ``citation_coupling`` if the DB was created by an older
               version of the code).
            2. Issues PRAGMA statements (via :func:`open_connection`)
               on a temporary connection opened during ``migrate()``.

        This is the intended entry-point for production callers.
        """
        repo = cls(db_path)
        repo.initialize()
        return repo

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open + auto-close a SQLite connection with the standard PRAGMAs."""
        if not self._initialized:
            raise RuntimeError(
                "CitationCouplingRepository not initialized. "
                "Call initialize() first."
            )
        with open_connection(self.db_path) as conn:
            yield conn

    def _retry(
        self,
        operation: Callable[[], _T],
        *,
        operation_name: str,
        **extra_log_fields: object,
    ) -> _T:
        """Thin wrapper around :func:`retry_on_lock_contention`."""
        return retry_on_lock_contention(
            operation,
            max_attempts=DEFAULT_MAX_ATTEMPTS,
            backoff_seconds=DEFAULT_BACKOFF_SECONDS,
            operation_name=operation_name,
            **extra_log_fields,
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def record(self, result: CouplingResult) -> None:
        """Upsert one :class:`CouplingResult` row.

        Canonicalizes the pair (stores ``min(a,b)`` as ``paper_a_id``
        and ``max(a,b)`` as ``paper_b_id``) to honour the DB's
        ``CHECK (paper_a_id < paper_b_id)`` constraint.

        Concurrency:
            Uses ``BEGIN IMMEDIATE``; transient lock contention is
            retried up to :data:`DEFAULT_MAX_ATTEMPTS` times.
            **Async callers MUST wrap in ``asyncio.to_thread(...)``.**

        Failure semantics:
            Raises :class:`sqlite3.Error` on a non-retryable write
            failure — mirrors :meth:`CitationInfluenceRepository.record_metrics`
            (PR #143 pattern).  The caller (typically
            :meth:`CouplingAnalyzer.analyze_pair`) is responsible for
            swallowing the error if cache-write failures should not
            propagate to end users.

        Args:
            result: Single :class:`CouplingResult` to upsert.

        Raises:
            sqlite3.Error: If the upsert fails after all retry attempts.
        """
        self._retry(
            lambda: self._record_once(result),
            operation_name="coupling_record",
            paper_a_id=result.paper_a_id,
            paper_b_id=result.paper_b_id,
        )

    def _record_once(self, result: CouplingResult) -> None:
        """Single-attempt upsert of one row."""
        # Canonical ordering: always store (min, max) so (A,B) and (B,A)
        # land on the same row — the DB's CHECK constraint enforces this.
        canon_a = min(result.paper_a_id, result.paper_b_id)
        canon_b = max(result.paper_a_id, result.paper_b_id)
        refs_json = json.dumps(result.shared_references)
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO citation_coupling (
                        paper_a_id, paper_b_id,
                        coupling_strength, shared_references_json,
                        co_citation_count, computed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(paper_a_id, paper_b_id) DO UPDATE SET
                        coupling_strength      = excluded.coupling_strength,
                        shared_references_json = excluded.shared_references_json,
                        co_citation_count      = excluded.co_citation_count,
                        computed_at            = excluded.computed_at
                    """,
                    (
                        canon_a,
                        canon_b,
                        result.coupling_strength,
                        refs_json,
                        result.co_citation_count,
                        now_iso,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def delete_stale(self, older_than: datetime) -> int:
        """Bulk delete rows whose ``computed_at`` predates ``older_than``.

        Returns:
            The number of rows deleted.

        Concurrency:
            Same retry semantics as :meth:`record`.
        """

        def _delete_once() -> int:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    cursor = conn.execute(
                        "DELETE FROM citation_coupling WHERE computed_at < ?",
                        (older_than.isoformat(),),
                    )
                    affected = cursor.rowcount
                    conn.commit()
                    return int(affected)
                except Exception:
                    conn.rollback()
                    raise

        return self._retry(
            _delete_once,
            operation_name="coupling_delete_stale",
            cutoff=older_than.isoformat(),
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(
        self,
        paper_a_id: str,
        paper_b_id: str,
        max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    ) -> Optional[CouplingResult]:
        """Fetch a cached row or ``None``.

        TTL semantics:
            Rows whose ``computed_at`` is older than ``max_age_days``
            are treated as cache misses.

        Concurrency:
            Wrapped in :func:`retry_on_lock_contention` so transient
            contention does not cause a spurious cache miss.

        Args:
            paper_a_id: First paper id.
            paper_b_id: Second paper id.
            max_age_days: Freshness window. Must be > 0.

        Returns:
            :class:`CouplingResult` if a fresh row exists, else ``None``.

        Raises:
            ValueError: If ``max_age_days`` is not positive.
        """
        if max_age_days <= 0:
            raise ValueError("max_age_days must be positive")

        # Canonicalize lookup order so (A,B) and (B,A) hit the same row.
        canon_a = min(paper_a_id, paper_b_id)
        canon_b = max(paper_a_id, paper_b_id)

        def _get_once() -> Optional[CouplingResult]:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    SELECT paper_a_id, paper_b_id,
                           coupling_strength, shared_references_json,
                           co_citation_count, computed_at
                    FROM citation_coupling
                    WHERE paper_a_id = ? AND paper_b_id = ?
                    """,
                    (canon_a, canon_b),
                )
                row = cursor.fetchone()
            if row is None:
                return None
            computed_at = datetime.fromisoformat(row["computed_at"])
            if computed_at.tzinfo is None:
                computed_at = computed_at.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            if computed_at < cutoff:
                return None

            shared: list[str] = json.loads(row["shared_references_json"])
            return CouplingResult(
                paper_a_id=row["paper_a_id"],
                paper_b_id=row["paper_b_id"],
                shared_references=shared,
                coupling_strength=row["coupling_strength"],
                co_citation_count=row["co_citation_count"],
            )

        return self._retry(
            _get_once,
            operation_name="coupling_get",
            paper_a_id=paper_a_id,
            paper_b_id=paper_b_id,
        )

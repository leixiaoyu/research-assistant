"""Persistence for ``InfluenceMetrics`` (V4 ``citation_influence_metrics``).

Why a standalone repository
---------------------------
PR #132 self-review surfaced H-A3: :class:`InfluenceScorer` reached
around :class:`SQLiteGraphStore` directly (via
``open_connection(self.store.db_path)``) to manage the V4 cache table
that the graph store does not know about. Folding cache CRUD into the
service blurred the layering -- services owning their own SQL schemas
sets a precedent that erodes the repository pattern (compare
:class:`MonitoringRunRepository`'s motivation).

This module hosts the canonical owner of the
``citation_influence_metrics`` table introduced by
``MIGRATION_V4_CITATION_INFLUENCE_METRICS``. The scorer (writer) and
the recommender (Issue #130, future reader) both go through this
class -- no other module should touch the table directly.

Schema (created by ``MIGRATION_V4_CITATION_INFLUENCE_METRICS``)
---------------------------------------------------------------
::

    citation_influence_metrics(
        paper_id           TEXT PRIMARY KEY,
        citation_count     INTEGER NOT NULL DEFAULT 0,
        citation_velocity  REAL    NOT NULL DEFAULT 0.0,
        pagerank_score     REAL    NOT NULL DEFAULT 0.0,
        hub_score          REAL    NOT NULL DEFAULT 0.0,
        authority_score    REAL    NOT NULL DEFAULT 0.0,
        computed_at        TEXT    NOT NULL,
        version            INTEGER NOT NULL DEFAULT 1
    )

TTL semantics
-------------
``get_metrics`` filters out rows whose ``computed_at`` is older than
``max_age_days`` ago (default 7 to match the spec REQ-9.2.4 ``CACHE_TTL``).
Callers receive ``None`` for stale rows so they can decide whether to
recompute. The stale row itself is *not* deleted on read -- that is
:meth:`delete_stale`'s job (a Phase 10 cleanup hook will call it on a
schedule).

Concurrency model
-----------------
Same approach as :class:`MonitoringRunRepository`: each method opens a
fresh connection through :func:`open_connection`, applies the standard
PRAGMAs, and closes on exit. ``record_metrics`` uses
:func:`retry_on_lock_contention` (issue #133) so transient
SQLITE_BUSY/SQLITE_LOCKED contention from a colliding writer does not
silently drop a cache row. **Async callers MUST wrap
``record_metrics`` / ``get_metrics`` / ``delete_stale`` in
``asyncio.to_thread(...)``** -- the retry helper sleeps via
``time.sleep`` and the connection helper itself is sync.

Failure semantics
-----------------
``record_metrics``'s outer ``try`` catches ``sqlite3.Error`` (the
common ancestor of ``OperationalError``, ``IntegrityError``,
``DatabaseError``, ...) so the don't-fail-the-API-call contract from
the original ``_write_cache`` is preserved. The retry helper itself
only retries lock contention; any other ``sqlite3.Error`` propagates
out of the helper, lands in the outer try, and is logged via the
``citation_influence_repo_write_failed`` event. The caller still gets
its in-memory metrics back.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Optional

import structlog

from src.storage.intelligence_graph.connection import (
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    open_connection,
    retry_on_lock_contention,
)
from src.storage.intelligence_graph.migrations import MigrationManager
from src.storage.intelligence_graph.path_utils import sanitize_storage_path

if TYPE_CHECKING:
    from src.services.intelligence.citation.influence_scorer import InfluenceMetrics

logger = structlog.get_logger(__name__)


# Default freshness window for ``get_metrics``. Mirrors
# ``DEFAULT_CACHE_TTL`` in influence_scorer.py (REQ-9.2.4) so the
# scorer's read path semantics are preserved when callers do not
# supply ``max_age_days`` explicitly.
DEFAULT_MAX_AGE_DAYS: int = 7


class CitationInfluenceRepository:
    """Owns the V4 ``citation_influence_metrics`` SQLite table.

    Provides a small, repository-shaped surface for callers:

    - :meth:`record_metrics` upsert one :class:`InfluenceMetrics` row.
    - :meth:`get_metrics` fetch by ``paper_id`` honouring a TTL.
    - :meth:`delete_stale` bulk delete rows older than a cutoff.

    Async safety:
        ALL methods are SYNC -- they open a SQLite connection,
        possibly sleep on retry, and return. **Async callers MUST
        wrap invocations in** ``asyncio.to_thread(...)`` per the
        canonical pattern documented in CLAUDE.md "SQLite write retry"
        section. Forgetting the wrap will block the event loop for the
        full retry budget on every contended write (and any read that
        races a writer).
    """

    def __init__(self, db_path: Path | str) -> None:
        """Initialise the repository.

        Args:
            db_path: SQLite database path. Must lie under one of the
                approved storage roots -- enforced by
                :func:`sanitize_storage_path`. The same database file
                also hosts the citation graph and (in the long-term
                Phase 10 plan) the monitoring tables, so this points
                at the shared intelligence DB.
        """
        self.db_path = sanitize_storage_path(db_path)
        self._migrations = MigrationManager(self.db_path)
        self._initialized = False

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------
    def initialize(self) -> None:
        """Apply pending schema migrations.

        Idempotent -- safe to call multiple times. Must be called
        before any read/write operation. Mirrors
        :meth:`MonitoringRunRepository.initialize` so callers that
        already use that pattern have no surprises.
        """
        applied = self._migrations.migrate()
        if applied > 0:
            logger.info(
                "citation_influence_repository_migrations_applied",
                count=applied,
                db_path=str(self.db_path),
            )
        self._initialized = True

    @classmethod
    def from_path(cls, db_path: Path | str) -> "CitationInfluenceRepository":
        """Construct + initialise in one call.

        Convenience factory mirroring
        :meth:`MonitoringRunner.from_paths`. Used by
        :meth:`InfluenceScorer.from_paths` when no repository is
        injected by the caller.
        """
        repo = cls(db_path)
        repo.initialize()
        return repo

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open + auto-close a SQLite connection with the standard PRAGMAs.

        Delegates to :func:`open_connection` so the PRAGMA set is
        defined in exactly one place across the intelligence-graph
        layer.
        """
        if not self._initialized:
            raise RuntimeError(
                "CitationInfluenceRepository not initialized. "
                "Call initialize() first."
            )
        with open_connection(self.db_path) as conn:
            yield conn

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def record_metrics(self, metrics: "InfluenceMetrics") -> None:
        """Upsert one ``InfluenceMetrics`` row.

        Concurrency:
            Uses ``BEGIN IMMEDIATE`` (matching
            :meth:`MonitoringRunRepository.record_run`) so the write
            lock is acquired up front. Transient
            ``OperationalError("database is locked")`` are retried
            up to :data:`DEFAULT_MAX_ATTEMPTS` times via
            :func:`retry_on_lock_contention` (issue #133).

            **Async callers MUST wrap this call in
            ``asyncio.to_thread(...)``** -- the retry loop uses
            ``time.sleep`` which would block the event loop. The
            scorer's ``compute_for_paper`` / ``compute_for_graph`` do
            this at every call site.

        Failure semantics:
            The outer ``try`` catches ``sqlite3.Error`` (superclass of
            ``OperationalError``, ``IntegrityError``, ``DatabaseError``,
            ...) so the don't-fail-the-API-call contract from the
            original ``_write_cache`` is preserved. Any non-contention
            ``sqlite3.Error`` is logged via
            ``citation_influence_repo_write_failed`` and swallowed --
            the caller still receives its in-memory metrics. The retry
            helper handles only contention; everything else propagates
            out of the helper, lands in the outer try, and is logged.

        Args:
            metrics: Single :class:`InfluenceMetrics` row to upsert.
        """
        try:
            retry_on_lock_contention(
                lambda: self._record_metrics_once(metrics),
                max_attempts=DEFAULT_MAX_ATTEMPTS,
                backoff_seconds=DEFAULT_BACKOFF_SECONDS,
                operation_name="influence_record_metrics",
                paper_id=metrics.paper_id,
            )
        except sqlite3.Error as exc:
            # Audit-write the failure path so ops can grep for cache
            # write outages. We swallow the exception so the caller
            # still receives its in-memory metrics (matches the
            # original ``_write_cache`` contract).
            logger.error(
                "citation_influence_repo_write_failed",
                paper_id=metrics.paper_id,
                error=str(exc),
            )

    def _record_metrics_once(self, metrics: "InfluenceMetrics") -> None:
        """Single-attempt upsert of one row.

        Extracted so the retry loop is the only place that catches
        contention errors -- keeps the success path tidy and the
        retry boundary explicit. Mirrors
        :meth:`MonitoringRunRepository._record_run_once`.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO citation_influence_metrics (
                        paper_id, citation_count, citation_velocity,
                        pagerank_score, hub_score, authority_score,
                        computed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(paper_id) DO UPDATE SET
                        citation_count = excluded.citation_count,
                        citation_velocity = excluded.citation_velocity,
                        pagerank_score = excluded.pagerank_score,
                        hub_score = excluded.hub_score,
                        authority_score = excluded.authority_score,
                        computed_at = excluded.computed_at
                    """,
                    (
                        metrics.paper_id,
                        metrics.citation_count,
                        metrics.citation_velocity,
                        metrics.pagerank_score,
                        metrics.hub_score,
                        metrics.authority_score,
                        metrics.computed_at.isoformat(),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def delete_stale(self, older_than: datetime) -> int:
        """Bulk delete rows whose ``computed_at`` predates ``older_than``.

        Returns:
            The number of rows actually deleted, for ops visibility.
            A Phase 10 cleanup hook will surface this number to its
            scheduler so persistent backlog growth is observable.

        Concurrency:
            Same retry semantics as :meth:`record_metrics`. Async
            callers must wrap in ``asyncio.to_thread(...)``.
        """

        def _delete_once() -> int:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    cursor = conn.execute(
                        """
                        DELETE FROM citation_influence_metrics
                        WHERE computed_at < ?
                        """,
                        (older_than.isoformat(),),
                    )
                    affected = cursor.rowcount
                    conn.commit()
                    return int(affected)
                except Exception:
                    conn.rollback()
                    raise

        return retry_on_lock_contention(
            _delete_once,
            max_attempts=DEFAULT_MAX_ATTEMPTS,
            backoff_seconds=DEFAULT_BACKOFF_SECONDS,
            operation_name="influence_delete_stale",
            cutoff=older_than.isoformat(),
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_metrics(
        self,
        paper_id: str,
        max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    ) -> Optional["InfluenceMetrics"]:
        """Fetch a single cached row or ``None``.

        TTL semantics:
            Rows whose ``computed_at`` is older than ``max_age_days``
            ago are treated as cache misses and ``None`` is returned.
            The stale row is *not* deleted -- callers can choose to
            recompute and overwrite, and a future Phase 10 cleanup
            hook calls :meth:`delete_stale` on a schedule.

        Args:
            paper_id: The canonical paper id (validated by the
                scorer before reaching this layer).
            max_age_days: Freshness window. Must be > 0. Default
                is :data:`DEFAULT_MAX_AGE_DAYS` (7) to mirror the
                original scorer's ``CACHE_TTL``.

        Returns:
            ``InfluenceMetrics`` if a fresh row exists, else ``None``.

        Raises:
            ValueError: If ``max_age_days`` is not positive.
        """
        # Local import to avoid a circular import between
        # influence_scorer (which imports the repository) and
        # influence_repository (which would otherwise import the
        # metrics model from the scorer at module load time).
        from src.services.intelligence.citation.influence_scorer import (
            InfluenceMetrics,
        )

        if max_age_days <= 0:
            raise ValueError("max_age_days must be positive")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT paper_id, citation_count, citation_velocity,
                       pagerank_score, hub_score, authority_score,
                       computed_at
                FROM citation_influence_metrics
                WHERE paper_id = ?
                """,
                (paper_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        computed_at = datetime.fromisoformat(row["computed_at"])
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        if computed_at < cutoff:
            return None
        return InfluenceMetrics(
            paper_id=row["paper_id"],
            citation_count=row["citation_count"],
            citation_velocity=row["citation_velocity"],
            pagerank_score=row["pagerank_score"],
            hub_score=row["hub_score"],
            authority_score=row["authority_score"],
            computed_at=computed_at,
        )

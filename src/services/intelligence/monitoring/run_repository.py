"""Persistence for ``MonitoringRun`` audit records.

Why a standalone repository (vs. extending ``SubscriptionManager``)
------------------------------------------------------------------
``SubscriptionManager`` already owns CRUD for the ``subscriptions``
table plus the per-user / per-subscription limit enforcement that
gates writes. Folding run-history persistence into it would mix two
distinct lifecycles (long-lived configuration vs. append-only audit
log) under one class -- a Single Responsibility violation that would
also blur error-handling expectations (e.g. a corrupt run row should
not affect subscription reads). A dedicated ``MonitoringRunRepository``
keeps each concern testable and replaceable in isolation.

Schema (created by ``MIGRATION_V2_MONITORING_RUNS``)
----------------------------------------------------
::

    monitoring_runs(
        run_id           TEXT PRIMARY KEY,
        subscription_id  TEXT NOT NULL,
        user_id          TEXT NOT NULL,
        started_at       TEXT NOT NULL,
        finished_at      TEXT,
        status           TEXT NOT NULL,
        error            TEXT,
        papers_found     INTEGER NOT NULL DEFAULT 0,
        papers_new       INTEGER NOT NULL DEFAULT 0
    )

    monitoring_papers(
        run_id              TEXT NOT NULL,
        paper_id            TEXT NOT NULL,
        registered          INTEGER NOT NULL DEFAULT 0,
        relevance_score     REAL,
        relevance_reasoning TEXT,
        PRIMARY KEY (run_id, paper_id),
        FOREIGN KEY (run_id) REFERENCES monitoring_runs(run_id) ON DELETE CASCADE
    )

The ``user_id`` column is denormalized onto ``monitoring_runs`` because
the ``MonitoringRun`` model itself does not carry one (subscriptions
do). The ``MonitoringRunner`` resolves the owning user from the
subscription before calling :meth:`record_run` so per-user audit
queries don't have to JOIN every read.

Concurrency model
-----------------
Same approach as ``SubscriptionManager``: each method opens a fresh
connection through :func:`open_connection`, applies the standard
PRAGMAs, and closes on exit. ``record_run`` uses a single transaction
to insert the run row plus all its paper rows atomically.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

import structlog

from src.services.intelligence.models.monitoring import PaperSource
from src.services.intelligence.monitoring.models import (
    MonitoringPaperRecord,
    MonitoringRun,
    MonitoringRunStatus,
)
from src.storage.intelligence_graph.connection import open_connection
from src.storage.intelligence_graph.migrations import MigrationManager
from src.storage.intelligence_graph.path_utils import sanitize_storage_path

logger = structlog.get_logger()


class MonitoringRunRepository:
    """Append-only store for ``MonitoringRun`` audit records.

    Owns the ``monitoring_runs`` and ``monitoring_papers`` tables
    introduced by ``MIGRATION_V2_MONITORING_RUNS``. The runner facade
    (``MonitoringRunner``) is the primary writer; the digest generator
    (Week 2) and any future CLI / REST surface are the primary readers.
    """

    def __init__(self, db_path: Path | str, *, user_id: str = "default") -> None:
        """Initialize the repository.

        Args:
            db_path: SQLite database path. Must lie under one of the
                approved storage roots -- enforced by
                :func:`sanitize_storage_path`.
            user_id: Default user_id stamped on rows when
                :meth:`record_run` is called without an explicit
                override. The runner passes the resolved owning user
                from the source subscription, so this is mostly a
                convenience for tests and ad-hoc scripts.
        """
        self.db_path = sanitize_storage_path(db_path)
        self._migrations = MigrationManager(self.db_path)
        self._default_user_id = user_id
        self._initialized = False

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------
    def initialize(self) -> None:
        """Apply pending schema migrations.

        Idempotent -- safe to call multiple times. Must be called
        before any read/write operation.
        """
        applied = self._migrations.migrate()
        if applied > 0:
            logger.info(
                "monitoring_run_repository_migrations_applied",
                count=applied,
                db_path=str(self.db_path),
            )
        self._initialized = True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open + auto-close a SQLite connection with the standard PRAGMAs.

        Delegates to :func:`open_connection` so the PRAGMA set is
        defined in exactly one place across the intelligence-graph
        layer.
        """
        if not self._initialized:
            raise RuntimeError(
                "MonitoringRunRepository not initialized. Call initialize() first."
            )
        with open_connection(self.db_path) as conn:
            yield conn

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    # Retry tuning for ``record_run`` lock contention (PR #119 review #S9).
    # WAL + busy_timeout already buys 5s on the connection level; this
    # adds three short application-level retries on top so a transient
    # ``OperationalError("database is locked")`` from a colliding writer
    # does not silently drop an audit row (the runner's per-sub error
    # envelope catches generic Exception and continues).
    _RECORD_RUN_MAX_ATTEMPTS = 3
    _RECORD_RUN_RETRY_BACKOFF_SECONDS = 0.05  # 50ms, 100ms (linear)

    def record_run(
        self,
        run: MonitoringRun,
        *,
        user_id: Optional[str] = None,
    ) -> None:
        """Persist ``run`` and all its paper records atomically.

        The run row plus its per-paper rows are written in a single
        transaction so a partial commit cannot leave dangling papers
        without their parent run (or vice versa).

        Concurrency:
            Uses ``BEGIN IMMEDIATE`` (matching ``SubscriptionManager``)
            so the write lock is acquired up front -- the existence
            check + INSERTs are atomic against concurrent writers.
            Transient ``OperationalError("database is locked")`` are
            retried up to ``_RECORD_RUN_MAX_ATTEMPTS`` times with linear
            backoff so a colliding writer doesn't drop the audit row.

        Args:
            run: ``MonitoringRun`` to persist.
            user_id: Owner user. When ``None`` the repository's
                default user_id is used (mainly for tests).

        Raises:
            ValueError: If a run with the same ``run_id`` already
                exists -- runs are append-only by design.
            sqlite3.OperationalError: If the lock contention persists
                past all retry attempts. The runner logs and continues
                rather than aborting the cycle.
        """
        owner = user_id or self._default_user_id
        finished = run.finished_at.isoformat() if run.finished_at else None

        attempt = 0
        while True:
            try:
                self._record_run_once(run, owner, finished)
                break  # success
            except sqlite3.OperationalError as exc:
                # Only retry the specific "database is locked" race; any
                # other OperationalError (corrupt db, disk full, schema
                # drift) propagates immediately. After exhausting all
                # attempts, re-raise so the caller sees the failure.
                is_lock_error = "locked" in str(exc).lower()
                is_last_attempt = attempt >= self._RECORD_RUN_MAX_ATTEMPTS - 1
                if not is_lock_error or is_last_attempt:
                    raise
                backoff = self._RECORD_RUN_RETRY_BACKOFF_SECONDS * (attempt + 1)
                logger.warning(
                    "monitoring_run_record_retry",
                    run_id=run.run_id,
                    attempt=attempt + 1,
                    max_attempts=self._RECORD_RUN_MAX_ATTEMPTS,
                    backoff_seconds=backoff,
                    error=str(exc),
                )
                time.sleep(backoff)
                attempt += 1

        logger.info(
            "monitoring_run_recorded",
            run_id=run.run_id,
            subscription_id=run.subscription_id,
            user_id=owner,
            status=run.status.value,
            papers_found=run.papers_seen,
            papers_new=run.papers_new,
        )

    def _record_run_once(
        self,
        run: MonitoringRun,
        owner: str,
        finished: Optional[str],
    ) -> None:
        """Single-attempt write of one run + its papers.

        Extracted from :meth:`record_run` so the retry loop is the only
        place that catches ``OperationalError`` -- keeps the success
        path tidy and the retry boundary explicit.
        """
        with self._connect() as conn:
            # BEGIN IMMEDIATE acquires the write lock up front so the
            # existence check + INSERTs are atomic against concurrent
            # writers (matches subscription_manager.add_subscription --
            # review #C2).
            conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = conn.execute(
                    "SELECT 1 FROM monitoring_runs WHERE run_id = ?",
                    (run.run_id,),
                )
                if cursor.fetchone() is not None:
                    raise ValueError(f"MonitoringRun already exists: {run.run_id!r}")
                conn.execute(
                    """
                    INSERT INTO monitoring_runs (
                        run_id, subscription_id, user_id,
                        started_at, finished_at, status, error,
                        papers_found, papers_new
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id,
                        run.subscription_id,
                        owner,
                        run.started_at.isoformat(),
                        finished,
                        run.status.value,
                        run.error,
                        run.papers_seen,
                        run.papers_new,
                    ),
                )
                if run.papers:
                    conn.executemany(
                        """
                        INSERT INTO monitoring_papers (
                            run_id, paper_id, registered,
                            relevance_score, relevance_reasoning
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                run.run_id,
                                paper.paper_id,
                                1 if paper.is_new else 0,
                                paper.relevance_score,
                                paper.relevance_reasoning,
                            )
                            for paper in run.papers
                        ],
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_run(self, run_id: str) -> Optional[MonitoringRun]:
        """Fetch a single run (with its paper records), or ``None``."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT run_id, subscription_id, user_id, started_at,
                       finished_at, status, error,
                       papers_found, papers_new
                FROM monitoring_runs
                WHERE run_id = ?
                """,
                (run_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            papers = self._fetch_papers(conn, run_id)
        return self._row_to_run(row, papers)

    def list_runs(
        self,
        subscription_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[MonitoringRun]:
        """List runs ordered by ``started_at DESC``.

        Args:
            subscription_id: When set, only runs for that subscription
                are returned.
            limit: Maximum number of runs to return. Must be > 0.

        Raises:
            ValueError: If ``limit`` is not positive.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        clauses: list[str] = []
        params: list[object] = []
        if subscription_id is not None:
            clauses.append("subscription_id = ?")
            params.append(subscription_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                SELECT run_id, subscription_id, user_id, started_at,
                       finished_at, status, error,
                       papers_found, papers_new
                FROM monitoring_runs
                {where}
                ORDER BY started_at DESC
                LIMIT ?
                """,
                tuple(params),
            )
            rows = cursor.fetchall()
            runs: list[MonitoringRun] = []
            for row in rows:
                papers = self._fetch_papers(conn, row["run_id"])
                runs.append(self._row_to_run(row, papers))
        return runs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _fetch_papers(
        conn: sqlite3.Connection, run_id: str
    ) -> list[MonitoringPaperRecord]:
        cursor = conn.execute(
            """
            SELECT paper_id, registered, relevance_score, relevance_reasoning
            FROM monitoring_papers
            WHERE run_id = ?
            ORDER BY paper_id ASC
            """,
            (run_id,),
        )
        records: list[MonitoringPaperRecord] = []
        for row in cursor.fetchall():
            records.append(
                MonitoringPaperRecord(
                    paper_id=row["paper_id"],
                    # The DTO requires title; we only store paper_id at
                    # the audit layer (titles live on the registry).
                    # Use the paper_id as a placeholder so the model
                    # round-trips without a JOIN.
                    title=row["paper_id"],
                    is_new=bool(row["registered"]),
                    relevance_score=row["relevance_score"],
                    relevance_reasoning=row["relevance_reasoning"],
                )
            )
        return records

    @staticmethod
    def _row_to_run(
        row: sqlite3.Row, papers: list[MonitoringPaperRecord]
    ) -> MonitoringRun:
        finished_iso = row["finished_at"]
        return MonitoringRun(
            run_id=row["run_id"],
            subscription_id=row["subscription_id"],
            source=PaperSource.ARXIV,
            started_at=datetime.fromisoformat(row["started_at"]),
            finished_at=(
                datetime.fromisoformat(finished_iso) if finished_iso else None
            ),
            status=MonitoringRunStatus(row["status"]),
            papers_seen=int(row["papers_found"]),
            papers_new=int(row["papers_new"]),
            error=row["error"],
            papers=papers,
        )

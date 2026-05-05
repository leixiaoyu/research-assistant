"""Schema migrations for Research Intelligence storage.

This module provides:
- Version-tracked schema migrations
- Forward migrations for schema updates
- Migration state persistence
- Atomic migration execution

Migration Strategy:
- Each migration has a unique version number
- Migrations are applied in order
- State is tracked in a migrations table
- Failed migrations rollback automatically

Transaction semantics
---------------------

Contrary to a common misconception, **SQLite supports transactional DDL**:
``CREATE TABLE``, ``CREATE INDEX``, ``ALTER TABLE``, etc. participate in
the surrounding transaction and are rolled back on ``ROLLBACK``. Most
other engines (Oracle, MySQL pre-8, MS SQL in some modes) auto-commit on
DDL — SQLite explicitly does not. See
https://www.sqlite.org/lang_transaction.html.

The one trap is ``Connection.executescript()``, which the Python sqlite3
binding wraps with an implicit ``COMMIT`` before the script runs (so it
can dispatch multiple statements). That implicit commit defeats
rollback-on-failure for multi-statement migrations.

We therefore deliberately:

1. Split the migration ``up`` script into individual statements via
   ``_split_sql_statements``.
2. Open an explicit transaction with ``BEGIN``.
3. Dispatch each statement with ``conn.execute()``.
4. ``COMMIT`` only after the ``schema_migrations`` row is also inserted.
5. ``ROLLBACK`` on any exception, so DDL + DML changes from the failed
   migration are reverted **and** the migration is NOT recorded as
   applied — re-running ``migrate()`` will retry it cleanly.

The ``test_apply_migration_rolls_back_ddl_on_later_failure`` test in
``tests/unit/storage/intelligence_graph/test_migrations.py`` pins this
behavior so future regressions (e.g. accidental switch back to
``executescript``) fail loudly.
"""

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import structlog

from src.storage.intelligence_graph.path_utils import sanitize_storage_path

logger = structlog.get_logger()


# SQL identifier pattern: standard ASCII identifiers only.
# Used to validate table names read from sqlite_master before interpolation.
_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_identifier(name: str) -> str:
    """Validate a SQL identifier against a strict whitelist pattern.

    This guards against identifier injection when interpolating table names
    into DDL/DML that cannot be parameterized (e.g., ``DROP TABLE``).

    Args:
        name: Candidate SQL identifier (e.g., a table name).

    Returns:
        The validated identifier (unchanged).

    Raises:
        ValueError: If the identifier does not match
            ``^[a-zA-Z_][a-zA-Z0-9_]*$``.
    """
    if not isinstance(name, str) or not _IDENTIFIER_PATTERN.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


@dataclass
class Migration:
    """A single schema migration.

    Attributes:
        version: Unique migration version (monotonically increasing)
        name: Human-readable migration name
        up: SQL or callable to apply migration
        description: Optional description of changes
    """

    version: int
    name: str
    up: str | Callable[[sqlite3.Connection], None]
    description: str = ""


# Schema version 1: Initial schema
MIGRATION_V1_INITIAL = Migration(
    version=1,
    name="initial_schema",
    description="Create initial tables for graph storage",
    up="""
    -- Nodes table for unified graph storage
    CREATE TABLE IF NOT EXISTS nodes (
        node_id TEXT PRIMARY KEY,
        node_type TEXT NOT NULL,
        properties TEXT NOT NULL DEFAULT '{}',
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
    CREATE INDEX IF NOT EXISTS idx_nodes_updated ON nodes(updated_at);

    -- Edges table for unified graph storage
    CREATE TABLE IF NOT EXISTS edges (
        edge_id TEXT PRIMARY KEY,
        edge_type TEXT NOT NULL,
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        properties TEXT DEFAULT '{}',
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (source_id) REFERENCES nodes(node_id) ON DELETE CASCADE,
        FOREIGN KEY (target_id) REFERENCES nodes(node_id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
    CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
    CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
    CREATE INDEX IF NOT EXISTS idx_edges_source_type ON edges(source_id, edge_type);
    CREATE INDEX IF NOT EXISTS idx_edges_target_type ON edges(target_id, edge_type);

    -- Time series table for trend analysis
    CREATE TABLE IF NOT EXISTS time_series (
        series_id TEXT NOT NULL,
        period TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        value REAL NOT NULL,
        metadata TEXT DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (series_id, period, metric_name)
    );

    CREATE INDEX IF NOT EXISTS idx_time_series_period ON time_series(period);
    CREATE INDEX IF NOT EXISTS idx_time_series_metric ON time_series(metric_name);

    -- Subscriptions table for monitoring
    CREATE TABLE IF NOT EXISTS subscriptions (
        subscription_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT 'default',
        name TEXT NOT NULL,
        config TEXT NOT NULL,
        last_checked TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);
    CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON subscriptions(is_active);

    -- Graph metrics table for monitoring node counts
    CREATE TABLE IF NOT EXISTS graph_metrics (
        metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_type TEXT NOT NULL,
        metric_value INTEGER NOT NULL,
        recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_graph_metrics_type ON graph_metrics(metric_type);
    CREATE INDEX IF NOT EXISTS idx_graph_metrics_recorded ON graph_metrics(recorded_at);
    """,
)


# Schema version 2: Monitoring run audit tables (Phase 9.1)
#
# Adds two tables consumed by ``MonitoringRunRepository``:
#
# - ``monitoring_runs``: one row per ``MonitoringRun`` (subscription +
#   cycle outcome + counters + optional error).
# - ``monitoring_papers``: per-paper outcome of each run, FK'd to
#   ``monitoring_runs(run_id) ON DELETE CASCADE`` so deleting a run
#   transparently cleans up its paper records.
#
# Index on ``(subscription_id, started_at DESC)`` accelerates the
# "most recent runs for this subscription" query that the digest
# generator (Week 2) and any future CLI listing would issue.
MIGRATION_V2_MONITORING_RUNS = Migration(
    version=2,
    name="monitoring_runs",
    description="Add monitoring_runs + monitoring_papers tables for run audit",
    up="""
    CREATE TABLE IF NOT EXISTS monitoring_runs (
        run_id TEXT PRIMARY KEY,
        subscription_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        error TEXT,
        papers_found INTEGER NOT NULL DEFAULT 0,
        papers_new INTEGER NOT NULL DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_monitoring_runs_sub_started
        ON monitoring_runs(subscription_id, started_at DESC);

    CREATE TABLE IF NOT EXISTS monitoring_papers (
        run_id TEXT NOT NULL,
        paper_id TEXT NOT NULL,
        registered INTEGER NOT NULL DEFAULT 0,
        relevance_score REAL,
        relevance_reasoning TEXT,
        PRIMARY KEY (run_id, paper_id),
        FOREIGN KEY (run_id) REFERENCES monitoring_runs(run_id)
            ON DELETE CASCADE
    );
    """,
)


# Schema version 3: Add FK + status CHECK to monitoring_runs (Phase 9.1
# self-review fixes — PR #119 #C1 + #S8, hardened in PR #123 #S2).
#
# WHY THIS IS A NEW MIGRATION (NOT A V2 EDIT)
# -------------------------------------------
# Migrations are immutable post-creation -- editing V2 in place would
# cause databases that already ran V2 to silently diverge from the
# canonical schema (their version column says "v2" but their tables
# look different). A separate V3 keeps the migration log honest.
#
# WHY THE TABLE-SWAP PATTERN (NOT DROP-AND-RECREATE)
# --------------------------------------------------
# An earlier draft used ``DROP TABLE IF EXISTS monitoring_runs;`` then
# ``CREATE TABLE monitoring_runs (...)``. That was destructive: any V2
# row inserted between the PR #119 merge and a contributor's first run
# of this V3 migration would be silently wiped, plus any
# ``monitoring_papers`` rows would CASCADE away too. PR #119 *did*
# merge before this hardening pass landed, so the "no production data"
# justification no longer holds.
#
# We now follow the standard SQLite table-swap pattern (the only safe
# way to add constraints to an existing table; SQLite's ``ALTER TABLE``
# cannot add CHECK or FOREIGN KEY constraints in place):
#
#   1. CREATE TABLE monitoring_runs_new (...)  -- new shape
#   2. INSERT INTO monitoring_runs_new SELECT * FROM monitoring_runs
#      -- copy V2 rows; CHECK rejects any pre-existing bad status,
#      which is the correct failure mode (loud, not silent)
#   3. DROP TABLE monitoring_runs                -- old table gone
#   4. ALTER TABLE monitoring_runs_new RENAME TO monitoring_runs
#      -- new table takes the canonical name
#   5. (Re)create the indexes on the now-renamed table.
#
# Atomicity: this migration relies on apply_migration's outer
# BEGIN/COMMIT envelope (see migrations.py:455). Do NOT add another
# BEGIN here -- nested transactions are not supported by SQLite and
# would cause the inner COMMIT to silently no-op. (PR #123 #N6.)
#
# WHAT THE NEW SCHEMA ADDS
# ------------------------
# - FOREIGN KEY (subscription_id) REFERENCES subscriptions(subscription_id)
#   ON DELETE CASCADE  -- review #C1
#   NOTE: ON DELETE CASCADE here, combined with monitoring_papers' own
#   CASCADE on run_id (V2), means deleting a subscription destroys its
#   entire audit trail (runs + papers). This is intentional for the
#   single-user MVP -- the subscription IS the trail. Multi-user phase
#   (Phase 10+) should reconsider: regulatory / forensic retention may
#   require RESTRICT or soft-delete on subscriptions. (PR #123 #N1.)
# - CHECK (status IN ('success','partial','failed')) -- review #S8;
#   values mirror MonitoringRunStatus enum exactly. The
#   test_migrate_v3_check_constraint_matches_monitoring_run_status_enum
#   guard pins the enum-vs-CHECK pairing so a future enum addition
#   that forgets a corresponding V4 widening fails at import-time.
# - CREATE INDEX idx_monitoring_runs_subscription on (subscription_id)
#   -- review #C1 supplemental, accelerates FK enforcement.
# - The original (subscription_id, started_at DESC) composite index
#   from V2 is also re-created on the renamed table.
MIGRATION_V3_MONITORING_RUNS_FK = Migration(
    version=3,
    name="monitoring_runs_fk_and_status_check",
    description=(
        "Rebuild monitoring_runs with FK to subscriptions(ON DELETE CASCADE)"
        " and CHECK constraint on status, preserving any V2 rows via the"
        " standard SQLite table-swap pattern."
    ),
    up="""
    -- Atomicity: this migration relies on apply_migration's outer
    -- BEGIN/COMMIT envelope (see migrations.py:455). Do NOT add another
    -- BEGIN here -- nested transactions are not supported by SQLite and
    -- would cause the inner COMMIT to silently no-op.
    CREATE TABLE monitoring_runs_new (
        run_id TEXT PRIMARY KEY,
        subscription_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL
            CHECK (status IN ('success', 'partial', 'failed')),
        error TEXT,
        papers_found INTEGER NOT NULL DEFAULT 0,
        papers_new INTEGER NOT NULL DEFAULT 0,
        -- ON DELETE CASCADE here, combined with monitoring_papers'
        -- own CASCADE on run_id (V2), means deleting a subscription
        -- destroys its entire audit trail (runs + papers). Intentional
        -- for the single-user MVP -- the subscription IS the trail.
        -- Multi-user phase (Phase 10+) should reconsider: regulatory
        -- / forensic retention may require RESTRICT or soft-delete.
        -- (PR #123 #N1.)
        FOREIGN KEY (subscription_id)
            REFERENCES subscriptions(subscription_id)
            ON DELETE CASCADE
    );

    -- Copy every V2 row into the new shape. Column order is explicit
    -- (rather than SELECT *) so a future V2 column addition does not
    -- silently shift positions. The CHECK constraint will reject any
    -- pre-existing row whose status is outside the enum -- that is
    -- the desired loud-failure behavior, not silent data loss.
    INSERT INTO monitoring_runs_new (
        run_id, subscription_id, user_id, started_at,
        finished_at, status, error, papers_found, papers_new
    )
    SELECT
        run_id, subscription_id, user_id, started_at,
        finished_at, status, error, papers_found, papers_new
    FROM monitoring_runs;

    -- Drop the old table. The monitoring_papers FK on run_id is
    -- preserved because new run_ids are identical (we copied the
    -- column verbatim) -- the CASCADE only fires if a referenced
    -- row vanishes, which it does not in this swap.
    DROP TABLE monitoring_runs;

    ALTER TABLE monitoring_runs_new RENAME TO monitoring_runs;

    CREATE INDEX IF NOT EXISTS idx_monitoring_runs_sub_started
        ON monitoring_runs(subscription_id, started_at DESC);

    CREATE INDEX IF NOT EXISTS idx_monitoring_runs_subscription
        ON monitoring_runs(subscription_id);
    """,
)


# Schema version 4: Citation influence metrics cache.
# Phase 9.2 — REQ-9.2.4 / Issue #129.
#
# Stores the result of one InfluenceScorer.compute_for_paper() call
# keyed by paper_id. The 7-day TTL enforced by InfluenceScorer reads
# the ``computed_at`` column on lookup; this migration provides only
# the persistence shape, no expiration logic.
#
# Schema notes
# ------------
# - ``paper_id`` PRIMARY KEY: each paper has at most one current score
#   row. Recompute UPSERTs (INSERT ... ON CONFLICT REPLACE) so the row
#   reflects the latest snapshot, never a stale one.
# - All score columns are REAL and nullable. PageRank always populates;
#   HITS may be skipped on oversize graphs (returns 0.0 / 0.0). We
#   store the actual zero rather than NULL so downstream consumers
#   don't need to disambiguate "skipped" vs "not yet computed".
# - ``citation_count`` is INTEGER and required (it is the input to
#   PageRank, not a derived metric, so a missing value would be a bug).
# - ``computed_at`` ISO-8601 string consistent with the rest of the
#   intelligence schema (V1-V3 all use ISO-8601 TEXT). The 7-day TTL
#   is enforced in Python — the DB merely persists the value.
# - ``version`` defaults to 1 and is reserved for forward-compatible
#   schema evolution (future hub/authority variants, weighted
#   PageRank, etc.) without forcing a V5 migration on day one.
#
# Indexes: ``computed_at`` to accelerate TTL sweeps the future cleanup
# job (Phase 10) will need; ``pagerank_score DESC`` for the "top
# influential papers" query patterns the recommender (#REQ-9.2.5)
# will issue.
MIGRATION_V4_CITATION_INFLUENCE_METRICS = Migration(
    version=4,
    name="citation_influence_metrics",
    description=(
        "Add citation_influence_metrics table for InfluenceScorer cache "
        "(REQ-9.2.4 / Issue #129)."
    ),
    up="""
    CREATE TABLE IF NOT EXISTS citation_influence_metrics (
        paper_id TEXT PRIMARY KEY,
        citation_count INTEGER NOT NULL DEFAULT 0,
        citation_velocity REAL NOT NULL DEFAULT 0.0,
        pagerank_score REAL NOT NULL DEFAULT 0.0,
        hub_score REAL NOT NULL DEFAULT 0.0,
        authority_score REAL NOT NULL DEFAULT 0.0,
        computed_at TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1
    );

    CREATE INDEX IF NOT EXISTS idx_citation_influence_metrics_computed
        ON citation_influence_metrics(computed_at);

    CREATE INDEX IF NOT EXISTS idx_citation_influence_metrics_pagerank
        ON citation_influence_metrics(pagerank_score DESC);
    """,
)


# Schema version 6: Bibliographic coupling cache.
# Phase 9.2 — REQ-9.2.3 / Issue #128.
#
# Stores the result of one CouplingAnalyzer.analyze_pair() call keyed by the
# ordered pair (paper_a_id, paper_b_id) where paper_a_id < paper_b_id. The
# canonical-pair constraint ensures (A,B) and (B,A) occupy the same row so
# lookups are symmetric by construction.
#
# Schema notes
# ------------
# - ``PRIMARY KEY (paper_a_id, paper_b_id)`` with the additional
#   ``CHECK (paper_a_id < paper_b_id)`` enforces the canonical-ordering
#   invariant at the storage layer; ``CitationCouplingRepository.record``
#   MUST call ``min``/``max`` before INSERT.
# - ``coupling_strength`` is REAL with ``CHECK (… >= 0.0 AND … <= 1.0)``
#   mirroring the Pydantic field constraint so the DB rejects out-of-range
#   rows that somehow slip past model validation.
# - ``co_citation_count`` is INTEGER with ``CHECK (… >= 0)`` likewise.
# - ``shared_references_json`` stores the sorted list as a JSON array.
# - ``computed_at`` ISO-8601 string; the 30-day TTL is enforced in Python.
# - No ``version`` column (unlike V4): the coupling table is a pure cache
#   with no forward-compatibility concerns for its initial version.
MIGRATION_V6_CITATION_COUPLING_CACHE = Migration(
    version=6,
    name="citation_coupling_cache",
    description=(
        "Add citation_coupling table for CouplingAnalyzer cache "
        "(REQ-9.2.3 / Issue #128)."
    ),
    up="""
    CREATE TABLE citation_coupling (
        paper_a_id TEXT NOT NULL,
        paper_b_id TEXT NOT NULL,
        coupling_strength REAL NOT NULL
            CHECK (coupling_strength >= 0.0 AND coupling_strength <= 1.0),
        shared_references_json TEXT NOT NULL,
        co_citation_count INTEGER NOT NULL
            CHECK (co_citation_count >= 0),
        computed_at TEXT NOT NULL,
        PRIMARY KEY (paper_a_id, paper_b_id),
        CHECK (paper_a_id < paper_b_id)
    );

    CREATE INDEX IF NOT EXISTS idx_citation_coupling_computed
        ON citation_coupling(computed_at);
    """,
)


# Schema version 5: Per-paper source provenance on monitoring_papers.
# Phase 9.1 Tier 1 follow-up — Issue #141.
#
# Background
# ----------
# PR #140 shipped ``MultiProviderMonitor`` (arXiv + OpenAlex + HuggingFace
# + Semantic Scholar fan-out) but kept ``MonitoringRun.source =
# PaperSource.ARXIV`` hardcoded for schema-compatibility. The audit log
# silently misattributed any paper that came from a non-arXiv provider.
#
# This migration adds a per-paper ``source`` column to
# ``monitoring_papers`` so each row records its actual discovery
# provider. ``MonitoringRun.source`` (in-memory only — no
# ``monitoring_runs.source`` column exists) is left alone; its semantics
# are widened in code to mean "primary / first-seen source" rather than
# "all sources". The per-paper row is the authoritative record.
#
# Backfill
# --------
# Existing rows default to ``'arxiv'``. This is correct because every
# paper persisted before PR #140 came from arXiv (the monitor was
# arXiv-only). Pre-Tier-1 audit rows that fell into the gap between
# PR #140 and this migration are also backfilled to arXiv — at worst,
# a handful of OpenAlex/HF/S2 papers from a few PR #140 cycles get
# attributed to arXiv. That's the same lie that prompted #141, but
# bounded to a small cohort and easy to identify (those rows have
# the V5 default rather than an explicit per-source write).
#
# Why ``DEFAULT 'arxiv'`` (not NULL)
# ----------------------------------
# A NULL source would force every consumer (digest generator, future
# CLI / REST surface) to handle "unknown source" as a special case.
# Using a sentinel default means downstream code can treat the column
# as required without a None branch. The PaperSource enum already has
# ``ARXIV`` so the default lines up with the enum's first member.
#
# Why table-swap (not ALTER TABLE ADD COLUMN)
# -------------------------------------------
# SQLite's ``ALTER TABLE ... ADD COLUMN`` cannot add a column with a
# CHECK constraint. The table-swap pattern (CREATE new → INSERT from old
# → DROP old → RENAME) is the only SQLite-portable way to add a CHECK to
# an existing table. Mirrors the approach used in V3.
#
# CHECK constraint mirrors ``PaperSource`` enum exactly so that any future
# enum addition that forgets a corresponding V6 widening is caught at
# INSERT time rather than silently storing garbage. The drift-guard test
# ``test_migrate_v5_check_constraint_matches_paper_source_enum`` pins the
# enum-vs-CHECK pairing.
MIGRATION_V5_PAPER_SOURCE_TRACKING = Migration(
    version=5,
    name="paper_source_tracking",
    description=(
        "Add monitoring_papers.source column for per-paper provenance "
        "(Phase 9.1 Tier 1 follow-up / Issue #141). Backfills existing "
        "rows to 'arxiv' since pre-Tier-1 monitoring was arXiv-only. "
        "Uses table-swap to add CHECK (source IN (...)) constraint."
    ),
    up="""
    CREATE TABLE monitoring_papers_new (
        run_id TEXT NOT NULL,
        paper_id TEXT NOT NULL,
        registered INTEGER NOT NULL DEFAULT 0,
        relevance_score REAL,
        relevance_reasoning TEXT,
        source TEXT NOT NULL DEFAULT 'arxiv'
            CHECK (source IN (
                'arxiv', 'semantic_scholar', 'huggingface', 'openalex'
            )),
        PRIMARY KEY (run_id, paper_id),
        FOREIGN KEY (run_id) REFERENCES monitoring_runs(run_id)
            ON DELETE CASCADE
    );

    INSERT INTO monitoring_papers_new (
        run_id, paper_id, registered, relevance_score, relevance_reasoning, source
    )
    SELECT
        run_id, paper_id, registered, relevance_score, relevance_reasoning, 'arxiv'
    FROM monitoring_papers;

    DROP TABLE monitoring_papers;

    ALTER TABLE monitoring_papers_new RENAME TO monitoring_papers;
    """,
)


# All migrations in order
ALL_MIGRATIONS: list[Migration] = [
    MIGRATION_V1_INITIAL,
    MIGRATION_V2_MONITORING_RUNS,
    MIGRATION_V3_MONITORING_RUNS_FK,
    MIGRATION_V4_CITATION_INFLUENCE_METRICS,
    MIGRATION_V5_PAPER_SOURCE_TRACKING,
    MIGRATION_V6_CITATION_COUPLING_CACHE,
]


# The latest migration version known to the codebase. Modules that
# need to assert "we are on the canonical schema" import this rather
# than counting ``ALL_MIGRATIONS`` so a future migration addition is
# a single-line update.
LATEST_MIGRATION_VERSION = 6


class MigrationManager:
    """Manages schema migrations for the intelligence database.

    Provides:
    - Automatic migration detection and application
    - Version tracking in database
    - Atomic migration execution with rollback
    - Proactive node count monitoring setup
    """

    # Migration threshold warnings
    NODE_COUNT_WARNING_THRESHOLD = 75_000
    NODE_COUNT_MIGRATION_THRESHOLD = 100_000

    def __init__(self, db_path: Path | str):
        """Initialize migration manager.

        Args:
            db_path: Path to SQLite database file. Must reside under one of
                the approved storage roots (``data/``, ``cache/``, or the
                system temp directory). See ``sanitize_storage_path``.
        """
        self.db_path = sanitize_storage_path(db_path)
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        """Ensure the database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection configured for safe concurrent access.

        Pragmas applied:
        - ``foreign_keys=ON``: referential integrity
        - ``journal_mode=WAL``: writers don't block readers; better
          concurrency
        - ``synchronous=NORMAL``: durability vs. throughput trade-off
        - ``busy_timeout=5000``: wait up to 5s for locks before failing

        Returns:
            SQLite connection ready for use.

        TODO(phase-10): consolidate onto
            ``src.storage.intelligence_graph.connection.open_connection``
            once this manager moves to the per-operation context-manager
            pattern used by ``SubscriptionManager`` /
            ``MonitoringRunRepository``.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_migrations_table(self, conn: sqlite3.Connection) -> None:
        """Ensure the migrations tracking table exists.

        Args:
            conn: Database connection.
        """
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

    def get_current_version(self) -> int:
        """Get the current schema version.

        Returns:
            Current schema version, or 0 if no migrations applied.
        """
        if not self.db_path.exists():
            return 0

        conn = self._get_connection()
        try:
            self._ensure_migrations_table(conn)
            cursor = conn.execute(
                "SELECT MAX(version) as version FROM schema_migrations"
            )
            row = cursor.fetchone()
            return row["version"] if row["version"] is not None else 0
        finally:
            conn.close()

    def get_pending_migrations(self) -> list[Migration]:
        """Get list of migrations that haven't been applied.

        Returns:
            List of pending migrations in order.
        """
        current_version = self.get_current_version()
        return [m for m in ALL_MIGRATIONS if m.version > current_version]

    @staticmethod
    def _split_sql_statements(script: str) -> list[str]:
        """Split a SQL script into individual statements.

        SQLite's ``executescript`` runs in autocommit mode and cannot be
        rolled back. To preserve atomicity we split on ``;`` and dispatch
        statements individually inside a transaction.

        Comments and blank lines are stripped. Statements that contain
        BEGIN/COMMIT/ROLLBACK are not expected in migration scripts.

        Args:
            script: Raw SQL containing one or more statements.

        Returns:
            List of trimmed, non-empty SQL statements.
        """
        statements: list[str] = []
        for raw in script.split(";"):
            # Strip line comments and surrounding whitespace
            cleaned_lines = []
            for line in raw.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("--"):
                    continue
                cleaned_lines.append(stripped)
            cleaned = " ".join(cleaned_lines).strip()
            if cleaned:
                statements.append(cleaned)
        return statements

    def apply_migration(self, conn: sqlite3.Connection, migration: Migration) -> None:
        """Apply a single migration atomically.

        Strategy: replace ``executescript`` (which auto-commits per
        statement and cannot be rolled back) with explicit per-statement
        execution inside a single transaction. If any statement fails the
        whole migration is rolled back and the version is NOT recorded in
        ``schema_migrations``.

        Args:
            conn: Database connection.
            migration: Migration to apply.

        Raises:
            sqlite3.Error: If migration fails (changes are rolled back).
        """
        logger.info(
            "applying_migration",
            version=migration.version,
            name=migration.name,
        )

        try:
            conn.execute("BEGIN")
            if isinstance(migration.up, str):
                for statement in self._split_sql_statements(migration.up):
                    conn.execute(statement)
            else:
                migration.up(conn)

            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
            conn.commit()

            logger.info(
                "migration_applied",
                version=migration.version,
                name=migration.name,
            )
        except Exception as e:
            conn.rollback()
            logger.error(
                "migration_failed",
                version=migration.version,
                name=migration.name,
                error=str(e),
            )
            raise

    def migrate(self) -> int:
        """Apply all pending migrations.

        Returns:
            Number of migrations applied.
        """
        pending = self.get_pending_migrations()
        if not pending:
            logger.info("no_pending_migrations")
            return 0

        logger.info(
            "starting_migrations",
            pending_count=len(pending),
            versions=[m.version for m in pending],
        )

        conn = self._get_connection()
        try:
            self._ensure_migrations_table(conn)

            for migration in pending:
                self.apply_migration(conn, migration)

            logger.info(
                "migrations_complete",
                applied_count=len(pending),
            )
            return len(pending)
        finally:
            conn.close()

    def get_applied_migrations(self) -> list[dict]:
        """Get list of applied migrations.

        Returns:
            List of dicts with version, name, and applied_at.
        """
        if not self.db_path.exists():
            return []

        conn = self._get_connection()
        try:
            self._ensure_migrations_table(conn)
            cursor = conn.execute(
                "SELECT version, name, applied_at FROM schema_migrations "
                "ORDER BY version"
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def check_node_count_threshold(self) -> Optional[str]:
        """Check if node count is approaching migration thresholds.

        Returns:
            Warning message if threshold reached, None otherwise.
        """
        if not self.db_path.exists():
            return None

        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) as count FROM nodes")
            row = cursor.fetchone()
            node_count = row["count"] if row else 0

            # Record metric
            conn.execute(
                "INSERT INTO graph_metrics (metric_type, metric_value) "
                "VALUES ('node_count', ?)",
                (node_count,),
            )
            conn.commit()

            if node_count >= self.NODE_COUNT_MIGRATION_THRESHOLD:
                message = (
                    f"CRITICAL: Node count ({node_count:,}) exceeds migration "
                    f"threshold ({self.NODE_COUNT_MIGRATION_THRESHOLD:,}). "
                    "Consider migrating to Neo4j for better performance."
                )
                logger.warning("node_count_critical", count=node_count)
                return message
            elif node_count >= self.NODE_COUNT_WARNING_THRESHOLD:
                message = (
                    f"WARNING: Node count ({node_count:,}) approaching migration "
                    f"threshold ({self.NODE_COUNT_MIGRATION_THRESHOLD:,}). "
                    "Plan for Neo4j migration."
                )
                logger.warning("node_count_warning", count=node_count)
                return message

            return None
        except sqlite3.OperationalError:
            # Table doesn't exist yet
            return None
        finally:
            conn.close()

    def get_node_count_history(self, limit: int = 100) -> list[dict]:
        """Get historical node count metrics.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of dicts with metric_value and recorded_at.
        """
        if not self.db_path.exists():
            return []

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT metric_value, recorded_at FROM graph_metrics "
                "WHERE metric_type = 'node_count' "
                "ORDER BY recorded_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    # Environment flag required to authorize destructive reset. Without it,
    # ``reset_database`` raises immediately to prevent accidental wipes.
    DESTRUCTIVE_RESET_ENV_FLAG = "INTELLIGENCE_ALLOW_DESTRUCTIVE_RESET"

    def reset_database(self) -> None:
        """Reset database by removing all tables.

        WARNING: This destroys all data. Gated behind the
        ``INTELLIGENCE_ALLOW_DESTRUCTIVE_RESET=1`` environment variable to
        prevent accidental wipes. Each table name is validated against a
        strict identifier whitelist and double-quoted before interpolation
        into the DDL to defend against identifier injection from a tampered
        ``sqlite_master``.
        """
        if os.environ.get(self.DESTRUCTIVE_RESET_ENV_FLAG) != "1":
            raise RuntimeError(
                "reset_database is destructive and disabled by default. "
                f"Set {self.DESTRUCTIVE_RESET_ENV_FLAG}=1 to authorize."
            )

        if not self.db_path.exists():
            return

        conn = self._get_connection()
        try:
            # Disable foreign keys for cleanup
            conn.execute("PRAGMA foreign_keys = OFF")

            # Get all table names
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row["name"] for row in cursor.fetchall()]

            # Drop all tables (validated + quoted to guard against injection)
            dropped = 0
            for table in tables:
                if table == "sqlite_sequence":
                    continue
                safe_name = _validate_identifier(table)
                conn.execute(f'DROP TABLE IF EXISTS "{safe_name}"')
                dropped += 1

            conn.commit()
            logger.info("database_reset", tables_dropped=dropped)
        finally:
            conn.close()

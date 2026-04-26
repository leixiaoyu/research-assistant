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


# All migrations in order
ALL_MIGRATIONS: list[Migration] = [
    MIGRATION_V1_INITIAL,
]


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

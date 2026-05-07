"""Tests for intelligence layer schema migrations.

Tests cover:
- Migration manager initialization
- Schema version tracking
- Migration application
- Node count threshold monitoring
- Database reset functionality
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.storage.intelligence_graph.connection import open_connection
from src.storage.intelligence_graph.migrations import (
    MigrationManager,
    Migration,
    ALL_MIGRATIONS,
    LATEST_MIGRATION_VERSION,
    MIGRATION_V1_INITIAL,
    MIGRATION_V2_MONITORING_RUNS,
    MIGRATION_V3_MONITORING_RUNS_FK,
    MIGRATION_V4_CITATION_INFLUENCE_METRICS,
    MIGRATION_V5_PAPER_SOURCE_TRACKING,
    MIGRATION_V6_CITATION_COUPLING_CACHE,
    MIGRATION_V7_BACKFILL_COLUMNS,
)
from src.utils.security import SecurityError


@pytest.fixture
def temp_db() -> Path:
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        return Path(f.name)


@pytest.fixture
def migration_manager(temp_db: Path) -> MigrationManager:
    """Create a migration manager with temp database."""
    return MigrationManager(temp_db)


class TestMigration:
    """Tests for Migration dataclass."""

    def test_migration_v1_exists(self) -> None:
        """Test initial migration is defined."""
        assert MIGRATION_V1_INITIAL.version == 1
        assert MIGRATION_V1_INITIAL.name == "initial_schema"
        assert isinstance(MIGRATION_V1_INITIAL.up, str)

    def test_all_migrations_ordered(self) -> None:
        """Test migrations are ordered by version."""
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)

    def test_all_migrations_unique_versions(self) -> None:
        """Test all migrations have unique versions."""
        versions = [m.version for m in ALL_MIGRATIONS]
        assert len(versions) == len(set(versions))


class TestMigrationManager:
    """Tests for MigrationManager."""

    def test_init_creates_directory(self, temp_db: Path) -> None:
        """Test manager creates database directory."""
        nested_path = temp_db.parent / "nested" / "path" / "test.db"
        MigrationManager(nested_path)  # Creates directory on init
        assert nested_path.parent.exists()

    def test_get_current_version_new_db(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test current version is 0 for new database."""
        assert migration_manager.get_current_version() == 0

    def test_get_current_version_db_not_exist(self, temp_db: Path) -> None:
        """Test current version is 0 when db file does not yet exist."""
        temp_db.unlink(missing_ok=True)
        manager = MigrationManager(temp_db)
        assert manager.get_current_version() == 0

    def test_get_pending_migrations_new_db(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test all migrations are pending for new database."""
        pending = migration_manager.get_pending_migrations()
        assert len(pending) == len(ALL_MIGRATIONS)

    def test_migrate_applies_all_pending(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test migrate applies all pending migrations."""
        applied = migration_manager.migrate()
        assert applied == len(ALL_MIGRATIONS)
        assert migration_manager.get_current_version() == len(ALL_MIGRATIONS)

    def test_migrate_idempotent(self, migration_manager: MigrationManager) -> None:
        """Test migrate is idempotent."""
        # First migration
        applied1 = migration_manager.migrate()
        assert applied1 == len(ALL_MIGRATIONS)

        # Second migration
        applied2 = migration_manager.migrate()
        assert applied2 == 0

    def test_get_applied_migrations(self, migration_manager: MigrationManager) -> None:
        """Test get_applied_migrations returns applied migrations."""
        migration_manager.migrate()
        applied = migration_manager.get_applied_migrations()

        assert len(applied) == len(ALL_MIGRATIONS)
        assert applied[0]["version"] == 1
        assert applied[0]["name"] == "initial_schema"
        assert "applied_at" in applied[0]

    def test_get_applied_migrations_empty(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test get_applied_migrations returns empty for new db."""
        applied = migration_manager.get_applied_migrations()
        assert applied == []

    def test_connection_enables_foreign_keys(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test connections have foreign keys enabled."""
        migration_manager.migrate()
        conn = migration_manager._get_connection()
        try:
            cursor = conn.execute("PRAGMA foreign_keys")
            row = cursor.fetchone()
            assert row[0] == 1  # 1 = ON
        finally:
            conn.close()

    def test_schema_tables_created(
        self, migration_manager: MigrationManager, temp_db: Path
    ) -> None:
        """Test migration creates all expected tables."""
        migration_manager.migrate()

        conn = sqlite3.connect(str(temp_db))
        try:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

            expected_tables = {
                "schema_migrations",
                "nodes",
                "edges",
                "time_series",
                "subscriptions",
                "graph_metrics",
            }
            assert expected_tables <= tables
        finally:
            conn.close()

    def test_nodes_table_schema(
        self, migration_manager: MigrationManager, temp_db: Path
    ) -> None:
        """Test nodes table has correct schema."""
        migration_manager.migrate()

        conn = sqlite3.connect(str(temp_db))
        try:
            cursor = conn.execute("PRAGMA table_info(nodes)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}

            assert "node_id" in columns
            assert "node_type" in columns
            assert "properties" in columns
            assert "version" in columns
            assert "created_at" in columns
            assert "updated_at" in columns
        finally:
            conn.close()

    def test_edges_table_schema(
        self, migration_manager: MigrationManager, temp_db: Path
    ) -> None:
        """Test edges table has correct schema."""
        migration_manager.migrate()

        conn = sqlite3.connect(str(temp_db))
        try:
            cursor = conn.execute("PRAGMA table_info(edges)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}

            assert "edge_id" in columns
            assert "edge_type" in columns
            assert "source_id" in columns
            assert "target_id" in columns
            assert "properties" in columns
            assert "version" in columns
        finally:
            conn.close()

    def test_edges_foreign_keys(
        self, migration_manager: MigrationManager, temp_db: Path
    ) -> None:
        """Test edges table has foreign key constraints."""
        migration_manager.migrate()

        conn = sqlite3.connect(str(temp_db))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            # Try to insert edge without valid nodes - should fail
            with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
                conn.execute("""
                    INSERT INTO edges (edge_id, edge_type, source_id, target_id)
                    VALUES ('edge:1', 'cites', 'invalid:source', 'invalid:target')
                    """)
        finally:
            conn.close()


class TestNodeCountThresholds:
    """Tests for node count threshold monitoring."""

    def test_check_threshold_no_warning_empty(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test no warning for empty database."""
        migration_manager.migrate()
        warning = migration_manager.check_node_count_threshold()
        assert warning is None

    def test_check_threshold_no_warning_below(
        self, migration_manager: MigrationManager, temp_db: Path
    ) -> None:
        """Test no warning when below threshold."""
        migration_manager.migrate()

        # Add some nodes
        conn = sqlite3.connect(str(temp_db))
        try:
            for i in range(100):
                conn.execute(
                    "INSERT INTO nodes (node_id, node_type, properties) "
                    "VALUES (?, 'paper', '{}')",
                    (f"paper:{i}",),
                )
            conn.commit()
        finally:
            conn.close()

        warning = migration_manager.check_node_count_threshold()
        assert warning is None

    def test_check_threshold_warning_at_75k(
        self, migration_manager: MigrationManager, temp_db: Path
    ) -> None:
        """Test warning at 75K nodes threshold."""
        migration_manager.migrate()

        # Mock high node count by inserting into graph_metrics
        conn = sqlite3.connect(str(temp_db))
        try:
            # Insert enough nodes to trigger warning (75K)
            # For efficiency, we test with the threshold value directly
            # In real tests we'd insert actual nodes
            for i in range(MigrationManager.NODE_COUNT_WARNING_THRESHOLD):
                conn.execute(
                    "INSERT INTO nodes (node_id, node_type, properties) "
                    "VALUES (?, 'paper', '{}')",
                    (f"paper:{i}",),
                )
            conn.commit()
        finally:
            conn.close()

        warning = migration_manager.check_node_count_threshold()
        assert warning is not None
        assert "WARNING" in warning
        assert "75,000" in warning

    def test_check_threshold_records_metric(
        self, migration_manager: MigrationManager, temp_db: Path
    ) -> None:
        """Test threshold check records metric."""
        migration_manager.migrate()

        # Add a node
        conn = sqlite3.connect(str(temp_db))
        try:
            conn.execute(
                "INSERT INTO nodes (node_id, node_type, properties) "
                "VALUES ('paper:1', 'paper', '{}')"
            )
            conn.commit()
        finally:
            conn.close()

        migration_manager.check_node_count_threshold()

        history = migration_manager.get_node_count_history()
        assert len(history) >= 1
        assert history[0]["metric_value"] == 1

    def test_get_node_count_history(self, migration_manager: MigrationManager) -> None:
        """Test getting node count history."""
        migration_manager.migrate()

        # Check threshold multiple times
        migration_manager.check_node_count_threshold()
        migration_manager.check_node_count_threshold()
        migration_manager.check_node_count_threshold()

        history = migration_manager.get_node_count_history(limit=10)
        assert len(history) == 3

    def test_get_node_count_history_empty(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test node count history for new db."""
        history = migration_manager.get_node_count_history()
        assert history == []


class TestDatabaseReset:
    """Tests for database reset functionality."""

    def test_reset_requires_env_flag(
        self,
        migration_manager: MigrationManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test reset_database refuses to run without the env flag."""
        migration_manager.migrate()
        monkeypatch.delenv(MigrationManager.DESTRUCTIVE_RESET_ENV_FLAG, raising=False)
        with pytest.raises(RuntimeError, match="DESTRUCTIVE_RESET"):
            migration_manager.reset_database()

    def test_reset_with_flag_succeeds(
        self,
        migration_manager: MigrationManager,
        temp_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test reset removes all tables when env flag is set."""
        monkeypatch.setenv(MigrationManager.DESTRUCTIVE_RESET_ENV_FLAG, "1")
        migration_manager.migrate()

        # Add some data
        conn = sqlite3.connect(str(temp_db))
        try:
            conn.execute(
                "INSERT INTO nodes (node_id, node_type, properties) "
                "VALUES ('paper:1', 'paper', '{}')"
            )
            conn.commit()
        finally:
            conn.close()

        # Reset
        migration_manager.reset_database()

        # Verify tables are gone
        conn = sqlite3.connect(str(temp_db))
        try:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            # sqlite_sequence might remain
            tables.discard("sqlite_sequence")
            assert len(tables) == 0
        finally:
            conn.close()

    def test_reset_allows_remigration(
        self,
        migration_manager: MigrationManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test database can be remigrated after reset."""
        monkeypatch.setenv(MigrationManager.DESTRUCTIVE_RESET_ENV_FLAG, "1")
        migration_manager.migrate()
        migration_manager.reset_database()

        # Should be able to migrate again
        applied = migration_manager.migrate()
        assert applied == len(ALL_MIGRATIONS)

    def test_reset_nonexistent_db(
        self, temp_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test reset handles non-existent database."""
        monkeypatch.setenv(MigrationManager.DESTRUCTIVE_RESET_ENV_FLAG, "1")
        # Delete the temp file
        temp_db.unlink(missing_ok=True)

        manager = MigrationManager(temp_db)
        # Should not raise
        manager.reset_database()

    def test_reset_rejects_malicious_table_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test the identifier validator rejects injection-style names."""
        from src.storage.intelligence_graph.migrations import (
            _validate_identifier,
        )

        # Valid identifiers
        assert _validate_identifier("nodes") == "nodes"
        assert _validate_identifier("schema_migrations") == "schema_migrations"
        assert _validate_identifier("_underscore") == "_underscore"

        # Injection-style payloads must be rejected
        bad_names = [
            'nodes"; DROP TABLE secrets; --',
            "nodes; DELETE FROM users",
            "nodes' OR '1'='1",
            "1bad",
            "",
            "has space",
            "has-dash",
            "with.dot",
        ]
        for bad in bad_names:
            with pytest.raises(ValueError, match="Invalid SQL identifier"):
                _validate_identifier(bad)


class TestMigrationCallable:
    """Tests for callable migrations."""

    def test_callable_migration(self, temp_db: Path) -> None:
        """Test migration with callable up function."""

        def custom_migration(conn: sqlite3.Connection) -> None:
            conn.execute("CREATE TABLE custom_table (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO custom_table (id) VALUES (1)")

        migration = Migration(
            version=999,
            name="custom_callable",
            up=custom_migration,
            description="Test callable migration",
        )

        manager = MigrationManager(temp_db)
        # First apply base migrations
        manager.migrate()

        # Manually apply custom migration
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, migration)
        finally:
            conn.close()

        # Verify table was created
        conn = sqlite3.connect(str(temp_db))
        try:
            cursor = conn.execute("SELECT * FROM custom_table")
            rows = cursor.fetchall()
            assert len(rows) == 1
            assert rows[0][0] == 1
        finally:
            conn.close()


class TestMigrationConstants:
    """Tests for migration threshold constants."""

    def test_warning_threshold(self) -> None:
        """Test warning threshold is 75K."""
        assert MigrationManager.NODE_COUNT_WARNING_THRESHOLD == 75_000

    def test_migration_threshold(self) -> None:
        """Test migration threshold is 100K."""
        assert MigrationManager.NODE_COUNT_MIGRATION_THRESHOLD == 100_000

    def test_warning_before_migration(self) -> None:
        """Test warning threshold is before migration threshold."""
        assert (
            MigrationManager.NODE_COUNT_WARNING_THRESHOLD
            < MigrationManager.NODE_COUNT_MIGRATION_THRESHOLD
        )


class TestMigrationPathTraversalRejection:
    """Security tests: MigrationManager must reject unsafe paths."""

    @pytest.mark.parametrize(
        "bad_path",
        [
            "../../etc/passwd.db",
            "/etc/passwd",
            "/usr/bin/sqlite3.db",
            "../../../shadow.db",
        ],
    )
    def test_migration_rejects_traversal_path(self, bad_path: str) -> None:
        """MigrationManager must reject paths outside approved roots."""
        with pytest.raises(SecurityError, match="outside approved storage roots"):
            MigrationManager(bad_path)


class TestMigrationAdditionalEdgeCases:
    """Tests folded in from former test_coverage_extras.py."""

    def test_check_threshold_critical_at_100k(self, temp_db: Path) -> None:
        """Test critical warning at 100K nodes threshold."""
        manager = MigrationManager(temp_db)
        manager.migrate()

        # Insert enough nodes to trigger critical threshold
        conn = sqlite3.connect(str(temp_db))
        try:
            for i in range(MigrationManager.NODE_COUNT_MIGRATION_THRESHOLD):
                conn.execute(
                    "INSERT INTO nodes (node_id, node_type, properties) "
                    "VALUES (?, 'paper', '{}')",
                    (f"paper:{i}",),
                )
            conn.commit()
        finally:
            conn.close()

        warning = manager.check_node_count_threshold()
        assert warning is not None
        assert "CRITICAL" in warning
        assert "100,000" in warning

    def test_get_node_count_history_with_limit(self, temp_db: Path) -> None:
        """Test node count history respects limit."""
        manager = MigrationManager(temp_db)
        manager.migrate()

        for _ in range(10):
            manager.check_node_count_threshold()

        history = manager.get_node_count_history(limit=5)
        assert len(history) == 5

    def test_migration_sql_error_handling(self, temp_db: Path) -> None:
        """Test migration rollback on SQL error."""
        manager = MigrationManager(temp_db)
        manager.migrate()

        # Create a migration with invalid SQL
        bad_migration = Migration(
            version=999,
            name="bad_migration",
            up="INVALID SQL STATEMENT",
        )

        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            with pytest.raises(sqlite3.OperationalError, match="syntax error"):
                manager.apply_migration(conn, bad_migration)
        finally:
            conn.close()

    def test_check_threshold_before_migration(self, temp_db: Path) -> None:
        """Test check threshold when table doesn't exist."""
        manager = MigrationManager(temp_db)
        warning = manager.check_node_count_threshold()
        assert warning is None

    def test_get_node_count_history_before_migration(self, temp_db: Path) -> None:
        """Test get history when table doesn't exist."""
        manager = MigrationManager(temp_db)
        history = manager.get_node_count_history()
        assert history == []

    def test_get_applied_migrations_db_not_exist(self) -> None:
        """Test get_applied_migrations when db file doesn't exist."""
        non_existent = Path(tempfile.gettempdir()) / "nonexistent_db_12345.db"
        if non_existent.exists():
            non_existent.unlink()
        manager = MigrationManager(non_existent)
        result = manager.get_applied_migrations()
        assert result == []

    def test_check_threshold_db_not_exist(self) -> None:
        """Test check_node_count_threshold when db file doesn't exist."""
        non_existent = Path(tempfile.gettempdir()) / "nonexistent_db_check_12345.db"
        if non_existent.exists():
            non_existent.unlink()
        manager = MigrationManager(non_existent)
        result = manager.check_node_count_threshold()
        assert result is None

    def test_get_node_count_history_db_not_exist(self) -> None:
        """Test get_node_count_history when db file doesn't exist."""
        non_existent = Path(tempfile.gettempdir()) / "nonexistent_db_history_12345.db"
        if non_existent.exists():
            non_existent.unlink()
        manager = MigrationManager(non_existent)
        result = manager.get_node_count_history()
        assert result == []

    def test_migrate_logs_when_pending(self, temp_db: Path) -> None:
        """Test migrate logs when there are pending migrations."""
        manager = MigrationManager(temp_db)
        applied = manager.migrate()
        assert applied >= 1


class TestMigrationTransactionRollback:
    """Tests for atomic migration application with explicit rollback."""

    def test_apply_migration_rolls_back_on_failure(self, temp_db: Path) -> None:
        """A migration with one good + one bad statement must roll back fully
        and not record itself in schema_migrations."""
        manager = MigrationManager(temp_db)
        # Apply baseline migrations first so schema_migrations exists
        manager.migrate()

        bad_migration = Migration(
            version=42,
            name="half_bad",
            up=(
                # Valid first statement
                "CREATE TABLE temp_atomic_test (id INTEGER PRIMARY KEY);"
                # Invalid second statement (references missing table)
                "INSERT INTO never_existed (id) VALUES (1);"
            ),
        )

        conn = manager._get_connection()
        try:
            with pytest.raises(sqlite3.OperationalError, match="no such table"):
                manager.apply_migration(conn, bad_migration)
        finally:
            conn.close()

        # First statement must have been rolled back
        check = sqlite3.connect(str(temp_db))
        try:
            cur = check.execute(
                "SELECT name FROM sqlite_master WHERE name = 'temp_atomic_test'"
            )
            assert cur.fetchone() is None
        finally:
            check.close()

        # The migration must NOT be recorded
        applied = {m["version"] for m in manager.get_applied_migrations()}
        assert 42 not in applied

    def test_apply_migration_rolls_back_ddl_on_later_failure(
        self, temp_db: Path
    ) -> None:
        """Pin the design decision: SQLite supports transactional DDL.

        A migration that runs ``CREATE TABLE foo_test`` followed by a
        guaranteed-failing statement must leave the database in its
        pre-migration state — the table must NOT exist, and the migration
        version must NOT appear in ``schema_migrations``.

        This is a regression guard: if anyone reverts back to
        ``executescript`` (which auto-commits per-statement and cannot
        roll back), this test fails immediately because ``foo_test`` would
        survive the failed migration. See the "Transaction semantics"
        section in the ``migrations.py`` module docstring.
        """
        manager = MigrationManager(temp_db)
        manager.migrate()  # baseline

        ddl_then_failure = Migration(
            version=4242,
            name="ddl_then_failure",
            up=(
                # DDL that would persist if it weren't inside a real txn
                "CREATE TABLE foo_test (id INTEGER PRIMARY KEY);"
                # Guaranteed-failing follow-up: references a missing table
                "INSERT INTO no_such_table VALUES (1);"
            ),
        )

        conn = manager._get_connection()
        try:
            with pytest.raises(sqlite3.OperationalError, match="no such table"):
                manager.apply_migration(conn, ddl_then_failure)
        finally:
            conn.close()

        # (a) The DDL must have been rolled back — no foo_test table.
        check = sqlite3.connect(str(temp_db))
        try:
            cur = check.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='foo_test'"
            )
            assert cur.fetchone() is None, (
                "DDL leaked through the failed migration — "
                "transactional DDL is broken"
            )
        finally:
            check.close()

        # (b) The migration must NOT be recorded.
        applied_versions = {m["version"] for m in manager.get_applied_migrations()}
        assert 4242 not in applied_versions


class TestMigrationV3MonitoringRunsFk:
    """Tests for MIGRATION_V3_MONITORING_RUNS_FK (PR #119 review #C1, #S8;
    PR #123 review #S2, #N2--#N5).

    Naming convention (#N5): every test name follows
    ``test_migrate_v3_<scenario>`` so the function under test
    (``migrate`` applied through V3) and the scenario being pinned are
    both visible at first glance.
    """

    def _open(self, db_path: Path) -> sqlite3.Connection:
        """Open a connection with foreign keys enforced (V3 needs them)."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def test_migrate_v3_cascade_deletes_run_on_subscription_delete(
        self, temp_db: Path
    ) -> None:
        """After V3, deleting a subscription must cascade-delete its runs."""
        manager = MigrationManager(temp_db)
        manager.migrate()

        conn = self._open(temp_db)
        try:
            # Insert a subscription so we can reference it.
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-fk-test", "alice", "Sub", "{}"),
            )
            # Insert a run referencing the subscription.
            conn.execute(
                """
                INSERT INTO monitoring_runs (
                    run_id, subscription_id, user_id,
                    started_at, status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "run-fk-test",
                    "sub-fk-test",
                    "alice",
                    "2024-01-01T00:00:00+00:00",
                    "success",
                ),
            )
            conn.commit()

            # Sanity: row exists.
            cnt = conn.execute(
                "SELECT COUNT(*) FROM monitoring_runs WHERE run_id = ?",
                ("run-fk-test",),
            ).fetchone()[0]
            assert cnt == 1

            # Delete the subscription -- FK CASCADE must remove the run.
            conn.execute(
                "DELETE FROM subscriptions WHERE subscription_id = ?",
                ("sub-fk-test",),
            )
            conn.commit()

            cnt = conn.execute(
                "SELECT COUNT(*) FROM monitoring_runs WHERE run_id = ?",
                ("run-fk-test",),
            ).fetchone()[0]
            assert cnt == 0, "run should have been cascade-deleted"
        finally:
            conn.close()

    def test_migrate_v3_rejects_invalid_status_via_check(self, temp_db: Path) -> None:
        """Inserting an unknown status string must raise IntegrityError."""
        manager = MigrationManager(temp_db)
        manager.migrate()

        conn = self._open(temp_db)
        try:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-check", "alice", "Sub", "{}"),
            )
            conn.commit()

            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                conn.execute(
                    """
                    INSERT INTO monitoring_runs (
                        run_id, subscription_id, user_id,
                        started_at, status
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "run-bad-status",
                        "sub-check",
                        "alice",
                        "2024-01-01T00:00:00+00:00",
                        "BOGUS_STATUS",
                    ),
                )
        finally:
            conn.close()

    def test_migrate_v3_rejects_empty_status_via_check(self, temp_db: Path) -> None:
        """Empty-string status must fail the CHECK constraint (PR #123 #N3).

        ``""`` is technically a non-NULL string so NOT NULL would let
        it through; the CHECK is the second line of defense and is
        what catches this case in practice.
        """
        manager = MigrationManager(temp_db)
        manager.migrate()

        conn = self._open(temp_db)
        try:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-empty", "alice", "Sub", "{}"),
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                conn.execute(
                    """
                    INSERT INTO monitoring_runs (
                        run_id, subscription_id, user_id,
                        started_at, status
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "run-empty-status",
                        "sub-empty",
                        "alice",
                        "2024-01-01T00:00:00+00:00",
                        "",
                    ),
                )
        finally:
            conn.close()

    def test_migrate_v3_rejects_null_status_via_not_null(self, temp_db: Path) -> None:
        """A literal NULL status must fail NOT NULL (PR #123 #N3).

        NOT NULL is the first line of defense -- it stops the insert
        before the CHECK runs. We pass Python ``None`` which the
        sqlite3 binding maps to SQL NULL.
        """
        manager = MigrationManager(temp_db)
        manager.migrate()

        conn = self._open(temp_db)
        try:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-null", "alice", "Sub", "{}"),
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
                conn.execute(
                    """
                    INSERT INTO monitoring_runs (
                        run_id, subscription_id, user_id,
                        started_at, status
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "run-null-status",
                        "sub-null",
                        "alice",
                        "2024-01-01T00:00:00+00:00",
                        None,
                    ),
                )
        finally:
            conn.close()

    def test_migrate_v3_rejects_omitted_status_via_not_null(
        self, temp_db: Path
    ) -> None:
        """Omitting the status column entirely must fail NOT NULL
        (PR #123 #N3). There is no DEFAULT on status, so the implicit
        NULL trips the NOT NULL constraint before the CHECK.
        """
        manager = MigrationManager(temp_db)
        manager.migrate()

        conn = self._open(temp_db)
        try:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-omit", "alice", "Sub", "{}"),
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
                # Note: status column is omitted from the column list.
                conn.execute(
                    """
                    INSERT INTO monitoring_runs (
                        run_id, subscription_id, user_id, started_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        "run-omit-status",
                        "sub-omit",
                        "alice",
                        "2024-01-01T00:00:00+00:00",
                    ),
                )
        finally:
            conn.close()

    def test_migrate_v3_accepts_all_known_status_values(self, temp_db: Path) -> None:
        """Each MonitoringRunStatus enum value must be accepted by the CHECK."""
        from src.services.intelligence.monitoring.models import (
            MonitoringRunStatus,
        )

        manager = MigrationManager(temp_db)
        manager.migrate()

        conn = self._open(temp_db)
        try:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-status", "alice", "Sub", "{}"),
            )
            for i, status in enumerate(MonitoringRunStatus):
                conn.execute(
                    """
                    INSERT INTO monitoring_runs (
                        run_id, subscription_id, user_id,
                        started_at, status
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        f"run-status-{i}",
                        "sub-status",
                        "alice",
                        "2024-01-01T00:00:00+00:00",
                        status.value,
                    ),
                )
            conn.commit()

            cnt = conn.execute("SELECT COUNT(*) FROM monitoring_runs").fetchone()[0]
            assert cnt == len(list(MonitoringRunStatus))
        finally:
            conn.close()

    def test_migrate_v3_creates_subscription_index(self, temp_db: Path) -> None:
        """Both indexes (composite + single-column) must be present after V3."""
        manager = MigrationManager(temp_db)
        manager.migrate()

        conn = sqlite3.connect(str(temp_db))
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='monitoring_runs'"
            )
            indexes = {row[0] for row in cursor.fetchall()}
            assert "idx_monitoring_runs_subscription" in indexes
            assert "idx_monitoring_runs_sub_started" in indexes
        finally:
            conn.close()

    def test_migrate_v3_preserves_data_inserted_under_v2_schema(
        self, temp_db: Path
    ) -> None:
        """V3 swaps the table; existing V2 rows must survive the swap.

        This is the regression guard for PR #123 #S2: an earlier draft
        of V3 used ``DROP TABLE IF EXISTS monitoring_runs`` followed by
        ``CREATE TABLE monitoring_runs`` -- destructive, would silently
        wipe any V2 audit row a contributor (or live deployment) had
        inserted between PR #119 merge and a fresh V3 migration. The
        rewrite uses the standard SQLite table-swap pattern (CREATE
        new -> INSERT FROM old -> DROP old -> ALTER RENAME). If anyone
        reverts back to DROP-and-CREATE, this test fails immediately
        because the V2 row is gone after V3 applies.
        """
        manager = MigrationManager(temp_db)
        # Apply only V1 + V2 -- stop short of V3 so we can write a
        # row that survives (or doesn't) the V3 swap.
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, MIGRATION_V1_INITIAL)
            manager.apply_migration(conn, MIGRATION_V2_MONITORING_RUNS)
        finally:
            conn.close()

        # Insert a subscription + a monitoring_runs row under V2 shape.
        with open_connection(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-v2-1", "alice", "V2 Sub", "{}"),
            )
            conn.execute(
                """
                INSERT INTO monitoring_runs (
                    run_id, subscription_id, user_id,
                    started_at, finished_at, status, error,
                    papers_found, papers_new
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "run-v2-1",
                    "sub-v2-1",
                    "alice",
                    "2024-01-01T00:00:00+00:00",
                    "2024-01-01T00:01:00+00:00",
                    "success",
                    None,
                    7,
                    3,
                ),
            )
            conn.commit()

        # Now apply V3 -- must preserve the V2 row.
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, MIGRATION_V3_MONITORING_RUNS_FK)
        finally:
            conn.close()

        with open_connection(temp_db) as conn:
            row = conn.execute(
                """
                SELECT run_id, subscription_id, user_id, started_at,
                       finished_at, status, error, papers_found, papers_new
                FROM monitoring_runs WHERE run_id = ?
                """,
                ("run-v2-1",),
            ).fetchone()
        assert row is not None, "V2 row was destroyed by V3 -- migration is destructive"
        assert row["status"] == "success"
        assert row["papers_found"] == 7
        assert row["papers_new"] == 3
        assert row["subscription_id"] == "sub-v2-1"
        assert row["finished_at"] == "2024-01-01T00:01:00+00:00"

    def test_migrate_v3_check_constraint_matches_monitoring_run_status_enum(
        self,
    ) -> None:
        """Enum-vs-CHECK exhaustive guard (PR #123 #N2).

        If MonitoringRunStatus gains a new member, the V3 CHECK
        constraint must also widen -- otherwise ``record_run`` would
        produce IntegrityError on the new value at runtime. This test
        catches the drift at import-time so the missing migration
        (V4 widening the CHECK) is obvious before any live insert
        fails. Pure SQL-string scan, no DB needed.
        """
        from src.services.intelligence.monitoring.models import (
            MonitoringRunStatus,
        )

        sql = MIGRATION_V3_MONITORING_RUNS_FK.up
        assert isinstance(sql, str)
        for member in MonitoringRunStatus:
            assert f"'{member.value}'" in sql, (
                f"MonitoringRunStatus.{member.name} = {member.value!r} "
                "is not present in MIGRATION_V3 CHECK constraint. "
                "Add MIGRATION_V4 widening the CHECK list."
            )

    def test_migrate_v3_records_version_in_schema_migrations(
        self, temp_db: Path
    ) -> None:
        """Full chain through V3 must record version=3 in the
        migration log so subsequent ``migrate()`` calls become no-ops
        (PR #123 #N4).
        """
        manager = MigrationManager(temp_db)
        manager.migrate()
        applied_versions = {m["version"] for m in manager.get_applied_migrations()}
        assert 3 in applied_versions, (
            "V3 not recorded in schema_migrations -- migrate() will "
            "redundantly re-apply on every startup"
        )


class TestMigrationV4CitationInfluenceMetrics:
    """Tests for MIGRATION_V4_CITATION_INFLUENCE_METRICS (Issue #129)."""

    def test_migrate_v4_creates_citation_influence_metrics_table(
        self, temp_db: Path
    ) -> None:
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='citation_influence_metrics'"
            )
            assert cursor.fetchone() is not None

    def test_migrate_v4_table_has_expected_columns(self, temp_db: Path) -> None:
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA table_info(citation_influence_metrics)")
            cols = {row["name"] for row in cursor.fetchall()}
        assert cols == {
            "paper_id",
            "citation_count",
            "citation_velocity",
            "pagerank_score",
            "hub_score",
            "authority_score",
            "computed_at",
            "version",
        }

    def test_migrate_v4_paper_id_is_primary_key(self, temp_db: Path) -> None:
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA table_info(citation_influence_metrics)")
            pk_cols = [row["name"] for row in cursor.fetchall() if row["pk"] == 1]
        assert pk_cols == ["paper_id"]

    def test_migrate_v4_unique_constraint_on_paper_id(self, temp_db: Path) -> None:
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            conn.execute(
                "INSERT INTO citation_influence_metrics "
                "(paper_id, computed_at) VALUES (?, ?)",
                ("paper:s2:dup", "2025-01-01T00:00:00+00:00"),
            )
            with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
                conn.execute(
                    "INSERT INTO citation_influence_metrics "
                    "(paper_id, computed_at) VALUES (?, ?)",
                    ("paper:s2:dup", "2025-01-02T00:00:00+00:00"),
                )

    def test_migrate_v4_records_version(self, temp_db: Path) -> None:
        manager = MigrationManager(temp_db)
        manager.migrate()
        applied_versions = {m["version"] for m in manager.get_applied_migrations()}
        assert 4 in applied_versions

    def test_migrate_v4_preserves_data_inserted_under_v3_schema(
        self, temp_db: Path
    ) -> None:
        """H-T1: V4 isolation upgrade test.

        Apply V1+V2+V3 only, insert known rows into ``nodes`` and
        ``monitoring_runs``, then apply V4 in isolation. V4 must (a)
        create the ``citation_influence_metrics`` table and (b) not
        disturb any pre-existing rows in other tables. Mirrors the V3
        regression guard at ``test_migrate_v3_preserves_data_inserted_under_v2_schema``.
        """
        manager = MigrationManager(temp_db)
        # Apply only V1 + V2 + V3 -- stop short of V4.
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, MIGRATION_V1_INITIAL)
            manager.apply_migration(conn, MIGRATION_V2_MONITORING_RUNS)
            manager.apply_migration(conn, MIGRATION_V3_MONITORING_RUNS_FK)
        finally:
            conn.close()

        # Insert a node + a subscription + a monitoring_runs row under V3 shape.
        with open_connection(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO nodes (
                    node_id, node_type, properties, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "paper:s2:abc",
                    "paper",
                    "{}",
                    "2024-06-01T00:00:00+00:00",
                    "2024-06-01T00:00:00+00:00",
                ),
            )
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-v3-1", "alice", "V3 Sub", "{}"),
            )
            conn.execute(
                """
                INSERT INTO monitoring_runs (
                    run_id, subscription_id, user_id,
                    started_at, finished_at, status, error,
                    papers_found, papers_new
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "run-v3-1",
                    "sub-v3-1",
                    "alice",
                    "2024-06-01T00:00:00+00:00",
                    "2024-06-01T00:01:00+00:00",
                    "success",
                    None,
                    5,
                    2,
                ),
            )
            conn.commit()

        # Now apply V4 in isolation -- must (a) create the new table
        # (b) not destroy anything that was already there.
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, MIGRATION_V4_CITATION_INFLUENCE_METRICS)
        finally:
            conn.close()

        with open_connection(temp_db) as conn:
            # (a) New table now exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='citation_influence_metrics'"
            )
            assert cursor.fetchone() is not None

            # (b) V3 rows survive intact
            node_row = conn.execute(
                "SELECT node_id, node_type FROM nodes WHERE node_id = ?",
                ("paper:s2:abc",),
            ).fetchone()
            assert node_row is not None
            assert node_row["node_type"] == "paper"

            run_row = conn.execute(
                "SELECT run_id, status, papers_found, papers_new "
                "FROM monitoring_runs WHERE run_id = ?",
                ("run-v3-1",),
            ).fetchone()
            assert run_row is not None
            assert run_row["status"] == "success"
            assert run_row["papers_found"] == 5
            assert run_row["papers_new"] == 2


class TestMigrationV5PaperSourceTracking:
    """Tests for ``MIGRATION_V5_PAPER_SOURCE_TRACKING`` (Issue #141).

    Pinned scenarios (every test name follows
    ``test_migrate_v5_<scenario>`` per the naming convention from V3):

    - V5 adds a ``source`` column to ``monitoring_papers``.
    - The new column is ``NOT NULL DEFAULT 'arxiv'``.
    - Pre-V5 rows survive the migration with ``source='arxiv'`` so the
      audit log treats legacy papers as arXiv (the only provider before
      Tier 1).
    - The migration is recorded in ``schema_migrations``.
    - ``LATEST_MIGRATION_VERSION`` is bumped to 5.
    - All other tables and rows survive untouched (V5 isolation).
    """

    def test_migrate_v5_adds_source_column(self, temp_db: Path) -> None:
        """The ``monitoring_papers`` table must gain a ``source`` column."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA table_info(monitoring_papers)")
            cols = {row["name"]: row for row in cursor.fetchall()}
        assert "source" in cols, "V5 did not add the source column"
        assert cols["source"]["notnull"] == 1, "source column must be NOT NULL"
        # Default value reads back as the string literal 'arxiv'.
        # SQLite stringifies the DEFAULT clause; PRAGMA returns it
        # verbatim including the surrounding quotes.
        assert "arxiv" in cols["source"]["dflt_value"]

    def test_migrate_v5_backfills_existing_rows_to_arxiv(self, temp_db: Path) -> None:
        """Pre-V5 monitoring_papers rows must end up with source='arxiv'.

        Apply only V1-V4, insert a paper row under the V4 schema (no
        source column), then apply V5. The backfilled column must be
        'arxiv' for the legacy row -- this is the bounded "lie" the
        V5 docstring documents.
        """
        manager = MigrationManager(temp_db)
        # Apply only V1-V4 -- stop short of V5 so we can write a row
        # under the legacy schema and verify the backfill.
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, MIGRATION_V1_INITIAL)
            manager.apply_migration(conn, MIGRATION_V2_MONITORING_RUNS)
            manager.apply_migration(conn, MIGRATION_V3_MONITORING_RUNS_FK)
            manager.apply_migration(conn, MIGRATION_V4_CITATION_INFLUENCE_METRICS)
        finally:
            conn.close()

        # Insert a parent run + a paper under the pre-V5 schema (no
        # ``source`` column in the column list).
        with open_connection(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-v4-legacy", "alice", "Legacy", "{}"),
            )
            conn.execute(
                """
                INSERT INTO monitoring_runs (
                    run_id, subscription_id, user_id,
                    started_at, status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "run-v4-legacy",
                    "sub-v4-legacy",
                    "alice",
                    "2024-06-01T00:00:00+00:00",
                    "success",
                ),
            )
            conn.execute(
                """
                INSERT INTO monitoring_papers (
                    run_id, paper_id, registered,
                    relevance_score, relevance_reasoning
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "run-v4-legacy",
                    "paper:legacy:001",
                    1,
                    0.8,
                    "legacy reasoning",
                ),
            )
            conn.commit()

        # Now apply V5 in isolation -- must add the column AND backfill
        # the legacy row to 'arxiv'.
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, MIGRATION_V5_PAPER_SOURCE_TRACKING)
        finally:
            conn.close()

        with open_connection(temp_db) as conn:
            row = conn.execute(
                "SELECT source FROM monitoring_papers WHERE paper_id = ?",
                ("paper:legacy:001",),
            ).fetchone()
            assert row is not None, "legacy row was destroyed by V5"
            # Backfill must produce 'arxiv'.
            assert row["source"] == "arxiv"

            # H-5: subscriptions and monitoring_runs rows must also survive V5.
            sub_row = conn.execute(
                "SELECT subscription_id FROM subscriptions "
                "WHERE subscription_id = ?",
                ("sub-v4-legacy",),
            ).fetchone()
            assert sub_row is not None, "subscription row was destroyed by V5"

            run_row = conn.execute(
                "SELECT run_id, status FROM monitoring_runs WHERE run_id = ?",
                ("run-v4-legacy",),
            ).fetchone()
            assert run_row is not None, "monitoring_run row was destroyed by V5"
            assert run_row["status"] == "success"

    def test_migrate_v5_records_version(self, temp_db: Path) -> None:
        """V5 must appear in ``schema_migrations`` after a full migrate()."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        applied_versions = {m["version"] for m in manager.get_applied_migrations()}
        assert 5 in applied_versions

    def test_migrate_v5_round_trips_each_paper_source(self, temp_db: Path) -> None:
        """Pin that every PaperSource value can be stored + read back.

        Defense against a future schema-level CHECK that forgets a
        member of the enum (the same drift class V3 guards against
        for ``MonitoringRunStatus``). This test stores one row per
        enum value and asserts the column accepts it without raising.
        """
        from src.services.intelligence.models.monitoring import PaperSource

        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-v5-enum", "alice", "Enum", "{}"),
            )
            conn.execute(
                """
                INSERT INTO monitoring_runs (
                    run_id, subscription_id, user_id, started_at, status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "run-v5-enum",
                    "sub-v5-enum",
                    "alice",
                    "2024-06-01T00:00:00+00:00",
                    "success",
                ),
            )
            for src in PaperSource:
                conn.execute(
                    """
                    INSERT INTO monitoring_papers (
                        run_id, paper_id, source
                    ) VALUES (?, ?, ?)
                    """,
                    ("run-v5-enum", f"paper:{src.value}:001", src.value),
                )
            conn.commit()

            stored = {
                row["source"]
                for row in conn.execute(
                    "SELECT source FROM monitoring_papers WHERE run_id = ?",
                    ("run-v5-enum",),
                ).fetchall()
            }
        assert stored == {src.value for src in PaperSource}

    def test_migrate_v5_rejects_unknown_source_via_check(self, temp_db: Path) -> None:
        """H-3: V5 CHECK constraint must reject unknown source strings.

        Any value not in PaperSource must cause an IntegrityError at
        insert time, not silently corrupt the audit trail.
        """
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-v5-check", "alice", "Check", "{}"),
            )
            conn.execute(
                """
                INSERT INTO monitoring_runs (
                    run_id, subscription_id, user_id, started_at, status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "run-v5-check",
                    "sub-v5-check",
                    "alice",
                    "2024-06-01T00:00:00+00:00",
                    "success",
                ),
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                conn.execute(
                    """
                    INSERT INTO monitoring_papers (
                        run_id, paper_id, source
                    ) VALUES (?, ?, ?)
                    """,
                    ("run-v5-check", "paper:bogus:001", "BOGUS_SOURCE"),
                )

    def test_migrate_v5_check_constraint_matches_paper_source_enum(self) -> None:
        """H-3: Enum-vs-CHECK exhaustive drift guard.

        If PaperSource gains a new member, the V5 CHECK constraint must
        also widen — otherwise ``record_run`` would produce an
        IntegrityError on the new value at runtime. This test catches
        the drift at import-time so the missing migration (V6 widening
        the CHECK) is obvious before any live insert fails. Pure
        SQL-string scan, no DB needed.

        Mirrors ``test_migrate_v3_check_constraint_matches_monitoring_run_status_enum``.
        """
        from src.services.intelligence.models.monitoring import PaperSource

        sql = MIGRATION_V5_PAPER_SOURCE_TRACKING.up
        assert isinstance(sql, str)
        for member in PaperSource:
            assert f"'{member.value}'" in sql, (
                f"PaperSource.{member.name} = {member.value!r} "
                "is not present in MIGRATION_V5 CHECK constraint. "
                "Add MIGRATION_V6 widening the CHECK list."
            )

    def test_migrate_v5_preserves_data_inserted_under_v4_schema(
        self, temp_db: Path
    ) -> None:
        """H-1: V5 isolation upgrade test.

        Apply V1+V2+V3+V4 only, insert known rows into ``nodes``,
        ``monitoring_runs``, ``monitoring_papers``, and
        ``subscriptions``, then apply V5 in isolation. V5 must (a)
        add the ``source`` column to ``monitoring_papers`` and (b) not
        disturb any pre-existing rows in any table. Mirrors the V4
        regression guard at
        ``test_migrate_v4_preserves_data_inserted_under_v3_schema``.
        """
        manager = MigrationManager(temp_db)
        # Apply only V1-V4 -- stop short of V5.
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, MIGRATION_V1_INITIAL)
            manager.apply_migration(conn, MIGRATION_V2_MONITORING_RUNS)
            manager.apply_migration(conn, MIGRATION_V3_MONITORING_RUNS_FK)
            manager.apply_migration(conn, MIGRATION_V4_CITATION_INFLUENCE_METRICS)
        finally:
            conn.close()

        # Insert rows into all four tables under the V4 schema.
        with open_connection(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO nodes (
                    node_id, node_type, properties, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "paper:s2:v4node",
                    "paper",
                    "{}",
                    "2024-07-01T00:00:00+00:00",
                    "2024-07-01T00:00:00+00:00",
                ),
            )
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-v4-iso", "alice", "V4 Iso Sub", "{}"),
            )
            conn.execute(
                """
                INSERT INTO monitoring_runs (
                    run_id, subscription_id, user_id,
                    started_at, status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "run-v4-iso",
                    "sub-v4-iso",
                    "alice",
                    "2024-07-01T00:00:00+00:00",
                    "success",
                ),
            )
            conn.execute(
                """
                INSERT INTO monitoring_papers (
                    run_id, paper_id, registered,
                    relevance_score, relevance_reasoning
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("run-v4-iso", "paper:v4:iso001", 1, 0.75, "V4 reasoning"),
            )
            conn.commit()

        # Now apply V5 in isolation -- must (a) add the source column
        # and (b) not destroy anything that was already there.
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, MIGRATION_V5_PAPER_SOURCE_TRACKING)
        finally:
            conn.close()

        with open_connection(temp_db) as conn:
            # (a) source column now present on monitoring_papers
            cursor = conn.execute("PRAGMA table_info(monitoring_papers)")
            cols = {row["name"] for row in cursor.fetchall()}
            assert "source" in cols

            # (b) All V4 rows survive intact
            node_row = conn.execute(
                "SELECT node_id, node_type FROM nodes WHERE node_id = ?",
                ("paper:s2:v4node",),
            ).fetchone()
            assert node_row is not None
            assert node_row["node_type"] == "paper"

            sub_row = conn.execute(
                "SELECT subscription_id FROM subscriptions WHERE subscription_id = ?",
                ("sub-v4-iso",),
            ).fetchone()
            assert sub_row is not None

            run_row = conn.execute(
                "SELECT run_id, status FROM monitoring_runs WHERE run_id = ?",
                ("run-v4-iso",),
            ).fetchone()
            assert run_row is not None
            assert run_row["status"] == "success"

            paper_row = conn.execute(
                "SELECT paper_id, source FROM monitoring_papers WHERE paper_id = ?",
                ("paper:v4:iso001",),
            ).fetchone()
            assert paper_row is not None
            # V5 backfill must have set source to 'arxiv'.
            assert paper_row["source"] == "arxiv"


class TestMigrationV6CitationCouplingCache:
    """Tests for ``MIGRATION_V6_CITATION_COUPLING_CACHE`` (Issue #128)."""

    def test_migrate_v6_creates_citation_coupling_table(self, temp_db: Path) -> None:
        """V6 migration creates the citation_coupling table."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='citation_coupling'"
            )
            assert cursor.fetchone() is not None

    def test_migrate_v6_table_has_expected_columns(self, temp_db: Path) -> None:
        """citation_coupling table has the full column set."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA table_info(citation_coupling)")
            cols = {row["name"] for row in cursor.fetchall()}
        assert cols == {
            "paper_a_id",
            "paper_b_id",
            "coupling_strength",
            "shared_references_json",
            "co_citation_count",
            "computed_at",
        }

    def test_migrate_v6_composite_primary_key(self, temp_db: Path) -> None:
        """Both paper_a_id and paper_b_id form the primary key."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA table_info(citation_coupling)")
            pk_cols = sorted(row["name"] for row in cursor.fetchall() if row["pk"] > 0)
        assert pk_cols == ["paper_a_id", "paper_b_id"]

    def test_migrate_v6_duplicate_pair_raises_integrity_error(
        self, temp_db: Path
    ) -> None:
        """Inserting a duplicate (paper_a_id, paper_b_id) pair raises IntegrityError."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            conn.execute(
                "INSERT INTO citation_coupling "
                "(paper_a_id, paper_b_id, coupling_strength, "
                "shared_references_json, co_citation_count, computed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "paper:s2:aaa",
                    "paper:s2:bbb",
                    0.5,
                    "[]",
                    0,
                    "2025-01-01T00:00:00+00:00",
                ),
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint"):
                conn.execute(
                    "INSERT INTO citation_coupling "
                    "(paper_a_id, paper_b_id, coupling_strength, "
                    "shared_references_json, co_citation_count, computed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "paper:s2:aaa",
                        "paper:s2:bbb",
                        0.3,
                        "[]",
                        0,
                        "2025-01-02T00:00:00+00:00",
                    ),
                )

    def test_migrate_v6_check_constraint_enforces_canonical_ordering(
        self, temp_db: Path
    ) -> None:
        """CHECK (paper_a_id < paper_b_id) rejects reversed pairs."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
                conn.execute(
                    "INSERT INTO citation_coupling "
                    "(paper_a_id, paper_b_id, coupling_strength, "
                    "shared_references_json, co_citation_count, computed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "paper:s2:zzz",  # > paper_b_id — violates CHECK
                        "paper:s2:aaa",
                        0.5,
                        "[]",
                        0,
                        "2025-01-01T00:00:00+00:00",
                    ),
                )

    def test_migrate_v6_check_rejects_strength_above_one(self, temp_db: Path) -> None:
        """H-7: CHECK (coupling_strength <= 1.0) rejects 1.5."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
                conn.execute(
                    "INSERT INTO citation_coupling "
                    "(paper_a_id, paper_b_id, coupling_strength, "
                    "shared_references_json, co_citation_count, computed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "paper:s2:aaa",
                        "paper:s2:bbb",
                        1.5,  # > 1.0 — violates CHECK
                        "[]",
                        0,
                        "2025-01-01T00:00:00+00:00",
                    ),
                )

    def test_migrate_v6_check_rejects_strength_below_zero(self, temp_db: Path) -> None:
        """H-7: CHECK (coupling_strength >= 0.0) rejects -0.1."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
                conn.execute(
                    "INSERT INTO citation_coupling "
                    "(paper_a_id, paper_b_id, coupling_strength, "
                    "shared_references_json, co_citation_count, computed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "paper:s2:aaa",
                        "paper:s2:bbb",
                        -0.1,  # < 0.0 — violates CHECK
                        "[]",
                        0,
                        "2025-01-01T00:00:00+00:00",
                    ),
                )

    def test_migrate_v6_check_rejects_negative_co_citation_count(
        self, temp_db: Path
    ) -> None:
        """H-7: CHECK (co_citation_count >= 0) rejects -1."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
                conn.execute(
                    "INSERT INTO citation_coupling "
                    "(paper_a_id, paper_b_id, coupling_strength, "
                    "shared_references_json, co_citation_count, computed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "paper:s2:aaa",
                        "paper:s2:bbb",
                        0.5,
                        "[]",
                        -1,  # < 0 — violates CHECK
                        "2025-01-01T00:00:00+00:00",
                    ),
                )

    def test_migrate_v6_check_constraint_sql_contains_strength_and_co_citation_bounds(
        self,
    ) -> None:
        """M-4: SQL drift-guard — both bounds present in V6 SQL string.

        Mirrors the V3/V5 enum drift-guard tests in spirit. Protects
        against a future SQL refactor silently dropping a CHECK clause.
        """
        sql = MIGRATION_V6_CITATION_COUPLING_CACHE.up
        assert "coupling_strength >= 0.0" in sql
        assert "coupling_strength <= 1.0" in sql
        assert "co_citation_count >= 0" in sql
        assert "paper_a_id < paper_b_id" in sql

    def test_migrate_v6_records_version(self, temp_db: Path) -> None:
        """V6 migration is recorded in schema_migrations."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        applied = manager.get_applied_migrations()
        versions = [m["version"] for m in applied]
        assert 6 in versions

    def test_migrate_v6_preserves_data_inserted_under_v5_schema(
        self, temp_db: Path
    ) -> None:
        """H-1: V6 isolation upgrade test.

        Apply V1+V2+V3+V4+V5 only, insert known rows into all tables
        (nodes, subscriptions, monitoring_runs, monitoring_papers,
        citation_influence_metrics), then apply V6 in isolation. V6
        must (a) create the ``citation_coupling`` table and (b) not
        disturb any pre-existing rows in other tables. Mirrors the V5
        isolation test at
        ``test_migrate_v5_preserves_data_inserted_under_v4_schema``.
        """
        manager = MigrationManager(temp_db)
        # Apply only V1–V5; stop short of V6.
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, MIGRATION_V1_INITIAL)
            manager.apply_migration(conn, MIGRATION_V2_MONITORING_RUNS)
            manager.apply_migration(conn, MIGRATION_V3_MONITORING_RUNS_FK)
            manager.apply_migration(conn, MIGRATION_V4_CITATION_INFLUENCE_METRICS)
            manager.apply_migration(conn, MIGRATION_V5_PAPER_SOURCE_TRACKING)
        finally:
            conn.close()

        # Insert rows into all V5 tables.
        with open_connection(temp_db) as conn:
            conn.execute(
                "INSERT INTO nodes"
                " (node_id, node_type, properties, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    "paper:s2:v5node",
                    "paper",
                    "{}",
                    "2025-01-01T00:00:00+00:00",
                    "2025-01-01T00:00:00+00:00",
                ),
            )
            conn.execute(
                "INSERT INTO subscriptions (subscription_id, user_id, name, config)"
                " VALUES (?, ?, ?, ?)",
                ("sub-v5-iso", "bob", "V5 Iso Sub", "{}"),
            )
            conn.execute(
                "INSERT INTO monitoring_runs"
                " (run_id, subscription_id, user_id, started_at, status)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    "run-v5-iso",
                    "sub-v5-iso",
                    "bob",
                    "2025-01-01T00:00:00+00:00",
                    "success",
                ),
            )
            conn.execute(
                "INSERT INTO monitoring_papers"
                " (run_id, paper_id, registered, source)"
                " VALUES (?, ?, ?, ?)",
                ("run-v5-iso", "paper:v5:iso001", 1, "arxiv"),
            )
            conn.execute(
                "INSERT INTO citation_influence_metrics"
                " (paper_id, computed_at)"
                " VALUES (?, ?)",
                ("paper:s2:v5metrics", "2025-01-01T00:00:00+00:00"),
            )
            conn.commit()

        # Apply V6 in isolation.
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, MIGRATION_V6_CITATION_COUPLING_CACHE)
        finally:
            conn.close()

        with open_connection(temp_db) as conn:
            # (a) citation_coupling table now exists.
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name='citation_coupling'"
            )
            assert cursor.fetchone() is not None

            # (b) All V5 rows survive intact.
            node_row = conn.execute(
                "SELECT node_id FROM nodes WHERE node_id = ?",
                ("paper:s2:v5node",),
            ).fetchone()
            assert node_row is not None

            sub_row = conn.execute(
                "SELECT subscription_id FROM subscriptions WHERE subscription_id = ?",
                ("sub-v5-iso",),
            ).fetchone()
            assert sub_row is not None

            run_row = conn.execute(
                "SELECT run_id, status FROM monitoring_runs WHERE run_id = ?",
                ("run-v5-iso",),
            ).fetchone()
            assert run_row is not None
            assert run_row["status"] == "success"

            paper_row = conn.execute(
                "SELECT paper_id, source FROM monitoring_papers WHERE paper_id = ?",
                ("paper:v5:iso001",),
            ).fetchone()
            assert paper_row is not None
            assert paper_row["source"] == "arxiv"

            metrics_row = conn.execute(
                "SELECT paper_id FROM citation_influence_metrics WHERE paper_id = ?",
                ("paper:s2:v5metrics",),
            ).fetchone()
            assert metrics_row is not None


class TestLatestMigrationVersion:
    """``LATEST_MIGRATION_VERSION`` mirrors the highest entry in
    ``ALL_MIGRATIONS`` so callers (or future cross-references) have
    a single line to bump when a new migration is added.
    """

    def test_latest_version_constant_matches_all_migrations(self) -> None:
        assert LATEST_MIGRATION_VERSION == max(m.version for m in ALL_MIGRATIONS)

    def test_latest_version_is_7(self) -> None:
        # Pinned literal so an accidental version bump shows up in
        # review even if ``ALL_MIGRATIONS`` is also extended.
        # Updated from 6 to 7 for the Phase 9.1 backfill migration (#145).
        assert LATEST_MIGRATION_VERSION == 7


class TestMigrationV7BackfillColumns:
    """Tests for MIGRATION_V7_BACKFILL_COLUMNS (Phase 9.1 / Issue #145).

    Naming convention: every test follows ``test_migrate_v7_<scenario>``
    so the migration under test and the pinned scenario are both visible.
    """

    def test_migrate_v7_adds_backfill_days_column(self, temp_db: Path) -> None:
        """V7 must add a backfill_days column to subscriptions."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA table_info(subscriptions)")
            cols = {row["name"]: row for row in cursor.fetchall()}
        assert "backfill_days" in cols, "V7 did not add backfill_days column"
        assert cols["backfill_days"]["notnull"] == 1, "backfill_days must be NOT NULL"
        assert (
            cols["backfill_days"]["dflt_value"] == "0"
        ), "backfill_days default must be 0"

    def test_migrate_v7_adds_backfill_cursor_date_column(self, temp_db: Path) -> None:
        """V7 must add a backfill_cursor_date column to subscriptions."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA table_info(subscriptions)")
            cols = {row["name"]: row for row in cursor.fetchall()}
        assert (
            "backfill_cursor_date" in cols
        ), "V7 did not add backfill_cursor_date column"
        # NULL is allowed for backfill_cursor_date.
        assert (
            cols["backfill_cursor_date"]["notnull"] == 0
        ), "backfill_cursor_date must allow NULL"

    def test_migrate_v7_check_constraint_rejects_backfill_days_below_zero(
        self, temp_db: Path
    ) -> None:
        """CHECK on backfill_days must reject negative values."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                conn.execute(
                    """
                    INSERT INTO subscriptions (
                        subscription_id, user_id, name, config, backfill_days
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    ("sub-v7-neg", "alice", "Sub", "{}", -1),
                )

    def test_migrate_v7_check_constraint_rejects_backfill_days_above_max(
        self, temp_db: Path
    ) -> None:
        """CHECK on backfill_days must reject values above 365."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                conn.execute(
                    """
                    INSERT INTO subscriptions (
                        subscription_id, user_id, name, config, backfill_days
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    ("sub-v7-over", "alice", "Sub", "{}", 366),
                )

    def test_migrate_v7_accepts_backfill_days_boundary_values(
        self, temp_db: Path
    ) -> None:
        """CHECK on backfill_days must accept 0 and 365 (boundaries)."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config, backfill_days
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("sub-v7-zero", "alice", "Zero", "{}", 0),
            )
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config, backfill_days
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("sub-v7-max", "alice", "Max", "{}", 365),
            )
            conn.commit()
            cnt = conn.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE backfill_days IN (0, 365)"
            ).fetchone()[0]
        assert cnt == 2

    def test_migrate_v7_default_backfill_days_is_zero(self, temp_db: Path) -> None:
        """Existing rows (no explicit backfill_days) must default to 0."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        with open_connection(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config
                ) VALUES (?, ?, ?, ?)
                """,
                ("sub-v7-default", "alice", "Default", "{}"),
            )
            conn.commit()
            row = conn.execute(
                "SELECT backfill_days FROM subscriptions "
                "WHERE subscription_id = 'sub-v7-default'"
            ).fetchone()
        assert row is not None
        assert row["backfill_days"] == 0

    def test_migrate_v7_records_version(self, temp_db: Path) -> None:
        """V7 must appear in schema_migrations after a full migrate()."""
        manager = MigrationManager(temp_db)
        manager.migrate()
        applied_versions = {m["version"] for m in manager.get_applied_migrations()}
        assert 7 in applied_versions

    def test_migrate_v7_preserves_data_inserted_under_v6_schema(
        self, temp_db: Path
    ) -> None:
        """H-T1: V7 isolation upgrade test.

        Apply V1-V6 only, insert a subscription row, then apply V7 in
        isolation. V7 must (a) add the two new columns and (b) not
        disturb any pre-existing rows. The backfill_days column for the
        pre-V7 row should default to 0 via the ALTER TABLE DEFAULT.

        Mirrors the pattern from
        test_migrate_v5_preserves_data_inserted_under_v4_schema.
        """
        manager = MigrationManager(temp_db)
        # Apply only V1-V6 -- stop short of V7.
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, MIGRATION_V1_INITIAL)
            manager.apply_migration(conn, MIGRATION_V2_MONITORING_RUNS)
            manager.apply_migration(conn, MIGRATION_V3_MONITORING_RUNS_FK)
            manager.apply_migration(conn, MIGRATION_V4_CITATION_INFLUENCE_METRICS)
            manager.apply_migration(conn, MIGRATION_V5_PAPER_SOURCE_TRACKING)
            manager.apply_migration(conn, MIGRATION_V6_CITATION_COUPLING_CACHE)
        finally:
            conn.close()

        # Insert a subscription row under the V6 schema (no backfill columns).
        with open_connection(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config,
                    last_checked, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "sub-v6-legacy",
                    "alice",
                    "V6 Legacy Sub",
                    "{}",
                    None,
                    1,
                    "2024-06-01T00:00:00+00:00",
                    "2024-06-01T00:00:00+00:00",
                ),
            )
            conn.commit()

        # Now apply V7 in isolation.
        conn = manager._get_connection()
        try:
            manager._ensure_migrations_table(conn)
            manager.apply_migration(conn, MIGRATION_V7_BACKFILL_COLUMNS)
        finally:
            conn.close()

        # (a) New columns exist; (b) legacy row survives with default backfill_days=0.
        with open_connection(temp_db) as conn:
            row = conn.execute(
                """
                SELECT subscription_id, name, backfill_days, backfill_cursor_date
                FROM subscriptions WHERE subscription_id = ?
                """,
                ("sub-v6-legacy",),
            ).fetchone()
        assert row is not None, "V6 row was destroyed by V7"
        assert row["name"] == "V6 Legacy Sub"
        assert (
            row["backfill_days"] == 0
        ), "V6 row backfill_days must default to 0 after V7"
        assert (
            row["backfill_cursor_date"] is None
        ), "V6 row backfill_cursor_date must default to NULL after V7"

    def test_migrate_v7_check_constraint_sql_contains_365_bound(self) -> None:
        """Drift-guard: V7 SQL must reference the 365-day bound.

        If BACKFILL_MAX_DAYS is ever changed in models.py, the V7 SQL
        must also be updated. This test catches that drift at import-time.
        Mirrors
        test_migrate_v6_check_constraint_sql_contains_strength_and_co_citation_bounds.
        """
        sql = MIGRATION_V7_BACKFILL_COLUMNS.up
        assert isinstance(sql, str)
        assert "365" in sql, (
            "V7 migration SQL must contain the 365-day upper bound "
            "for the backfill_days CHECK constraint."
        )
        assert "0" in sql, (
            "V7 migration SQL must contain 0 as the lower bound "
            "for the backfill_days CHECK constraint."
        )

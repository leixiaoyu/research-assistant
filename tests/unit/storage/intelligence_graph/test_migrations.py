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

from src.storage.intelligence_graph.migrations import (
    MigrationManager,
    Migration,
    ALL_MIGRATIONS,
    MIGRATION_V1_INITIAL,
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
            with pytest.raises(sqlite3.IntegrityError):
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
        with pytest.raises(SecurityError):
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
            with pytest.raises(sqlite3.OperationalError):
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
            with pytest.raises(sqlite3.OperationalError):
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
            with pytest.raises(sqlite3.OperationalError):
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

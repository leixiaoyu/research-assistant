"""Tests for the shared SQLite connection helper.

Covers:
- All four PRAGMAs are applied (foreign_keys, journal_mode,
  synchronous, busy_timeout).
- ``row_factory`` is set so callers can index by name.
- The connection is closed when the ``with`` block exits normally.
- The connection is closed even if the body raises.
- ``OperationalError`` is raised when ``db_path`` cannot be opened.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.storage.intelligence_graph.connection import open_connection


@pytest.fixture
def db_path() -> Path:
    """Return a temp path under the system temp dir."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    path.unlink(missing_ok=True)
    return path


def _pragma(conn: sqlite3.Connection, name: str) -> object:
    """Read back a PRAGMA value (returns the first column of the row)."""
    cursor = conn.execute(f"PRAGMA {name}")
    row = cursor.fetchone()
    # row is a sqlite3.Row; the actual value is at index 0.
    return row[0] if row is not None else None


class TestPragmas:
    def test_foreign_keys_enabled(self, db_path: Path) -> None:
        with open_connection(db_path) as conn:
            assert _pragma(conn, "foreign_keys") == 1

    def test_journal_mode_wal(self, db_path: Path) -> None:
        with open_connection(db_path) as conn:
            value = _pragma(conn, "journal_mode")
            assert isinstance(value, str)
            assert value.lower() == "wal"

    def test_synchronous_normal(self, db_path: Path) -> None:
        with open_connection(db_path) as conn:
            # NORMAL == 1 in SQLite's PRAGMA values
            assert _pragma(conn, "synchronous") == 1

    def test_busy_timeout_5000(self, db_path: Path) -> None:
        with open_connection(db_path) as conn:
            assert _pragma(conn, "busy_timeout") == 5000

    def test_row_factory_named_access(self, db_path: Path) -> None:
        with open_connection(db_path) as conn:
            conn.execute("CREATE TABLE t (a INTEGER, b TEXT)")
            conn.execute("INSERT INTO t (a, b) VALUES (?, ?)", (1, "hello"))
            row = conn.execute("SELECT a, b FROM t").fetchone()
        # row_factory=sqlite3.Row supports both index AND name access.
        assert row["a"] == 1
        assert row["b"] == "hello"


class TestLifecycle:
    def test_connection_closed_on_normal_exit(self, db_path: Path) -> None:
        with open_connection(db_path) as conn:
            captured = conn
        # After exit, operations on the connection raise ProgrammingError
        # because the connection is closed.
        with pytest.raises(sqlite3.ProgrammingError):
            captured.execute("SELECT 1")

    def test_connection_closed_on_exception(self, db_path: Path) -> None:
        captured: sqlite3.Connection | None = None

        with pytest.raises(RuntimeError, match="boom"):
            with open_connection(db_path) as conn:
                captured = conn
                raise RuntimeError("boom")

        assert captured is not None
        with pytest.raises(sqlite3.ProgrammingError):
            captured.execute("SELECT 1")


class TestErrorPaths:
    def test_invalid_path_raises_operational_error(self, tmp_path: Path) -> None:
        # A path whose parent directory does not exist cannot be opened.
        # ``sqlite3.connect`` surfaces this as ``OperationalError``.
        bad_path = tmp_path / "does" / "not" / "exist" / "x.db"
        with pytest.raises(sqlite3.OperationalError):
            with open_connection(bad_path):
                pass  # pragma: no cover (helper raises before yielding)

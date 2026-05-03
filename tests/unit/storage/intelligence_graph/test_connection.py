"""Tests for the shared SQLite connection helper.

Covers:
- All four PRAGMAs are applied (foreign_keys, journal_mode,
  synchronous, busy_timeout).
- ``row_factory`` is set so callers can index by name.
- The connection is closed when the ``with`` block exits normally.
- The connection is closed even if the body raises.
- ``OperationalError`` is raised when ``db_path`` cannot be opened.
- ``retry_on_lock_contention`` retries on SQLITE_BUSY (5) /
  SQLITE_LOCKED (6) using errorcode introspection plus substring
  fallback, propagates non-contention errors immediately, and emits
  structured warning + error events on retries / exhaustion.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
import structlog

from src.storage.intelligence_graph import connection as conn_mod
from src.storage.intelligence_graph.connection import (
    open_connection,
    retry_on_lock_contention,
)


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


# ---------------------------------------------------------------------------
# retry_on_lock_contention
# ---------------------------------------------------------------------------


def _make_op_error(message: str, *, errorcode: int | None = None) -> Exception:
    """Build a ``sqlite3.OperationalError`` with optional sqlite_errorcode.

    The C binding sets ``sqlite_errorcode`` automatically when sqlite
    raises a real error; tests must set it explicitly to exercise the
    errorcode branch (the substring branch is exercised by leaving it
    ``None``).
    """
    exc = sqlite3.OperationalError(message)
    if errorcode is not None:
        exc.sqlite_errorcode = errorcode
    return exc


class TestRetryOnLockContention:
    """Tests for the shared retry helper added by issue #133.

    The helper wraps any zero-arg callable that performs a SQLite write
    and retries on SQLITE_BUSY / SQLITE_LOCKED. Behaviour pinned here:

    - Returns the operation's value on first success (no retry).
    - Retries on errorcode 5 (BUSY), errorcode 6 (LOCKED), and on
      messages containing "locked" / "busy" when no errorcode is set
      (older SQLite bindings).
    - Does NOT retry any other ``OperationalError`` (e.g. syntax error
      or disk-full surfaced as code 1).
    - Raises after ``max_attempts`` of persistent contention.
    - Emits ``sqlite_lock_contention_retry`` (warning) per retry and
      ``sqlite_lock_contention_exhausted`` (error) on give-up.
    """

    def test_returns_immediately_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Happy path: operation succeeds on the first attempt and the
        helper returns its value verbatim. No sleep should fire.
        """
        sleeps: list[float] = []
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda s: sleeps.append(s),
        )
        calls = {"n": 0}

        def op() -> str:
            calls["n"] += 1
            return "ok"

        result = retry_on_lock_contention(op, operation_name="test_op")
        assert result == "ok"
        assert calls["n"] == 1
        assert sleeps == []  # No retry path taken.

    def test_retries_then_succeeds_on_busy_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SQLITE_BUSY (errorcode 5) must trigger a retry even when the
        message lacks "locked" -- exercises the errorcode branch.
        """
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )
        attempts = {"n": 0}

        def op() -> int:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise _make_op_error(
                    "database is busy",
                    errorcode=conn_mod._SQLITE_BUSY,
                )
            return 42

        result = retry_on_lock_contention(op, operation_name="busy_test")
        assert result == 42
        assert attempts["n"] == 2  # one retry, then success

    def test_retries_then_succeeds_on_locked_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SQLITE_LOCKED (errorcode 6) -- separate from BUSY so a future
        refactor that drops one of the two codes fails loudly.
        """
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )
        attempts = {"n": 0}

        def op() -> str:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise _make_op_error(
                    "some locked-table message",
                    errorcode=conn_mod._SQLITE_LOCKED,
                )
            return "done"

        assert retry_on_lock_contention(op, operation_name="locked_test") == "done"
        assert attempts["n"] == 2

    def test_falls_back_to_substring_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Older SQLite bindings do not populate ``sqlite_errorcode``.
        The helper must still recognize lock contention via the message
        substring ("locked" / "busy"), case-insensitively.
        """
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )
        attempts = {"n": 0}

        def op() -> int:
            attempts["n"] += 1
            if attempts["n"] == 1:
                # No errorcode -- mirrors older sqlite3 binding behavior
                # where the C layer doesn't set sqlite_errorcode.
                raise _make_op_error("database is locked")
            return 7

        assert retry_on_lock_contention(op, operation_name="substr_test") == 7
        assert attempts["n"] == 2

    def test_does_not_retry_on_other_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Any non-contention OperationalError (e.g. syntax error,
        disk full) must propagate on the first attempt -- retrying
        would mask real bugs.
        """
        sleeps: list[float] = []
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda s: sleeps.append(s),
        )
        attempts = {"n": 0}

        def op() -> None:
            attempts["n"] += 1
            # errorcode 1 == SQLITE_ERROR (generic), e.g. SQL syntax
            # error -- must NOT be retried.
            raise _make_op_error("syntax error near 'BEGIN'", errorcode=1)

        with pytest.raises(sqlite3.OperationalError, match="syntax error"):
            retry_on_lock_contention(op, operation_name="no_retry_test")
        assert attempts["n"] == 1
        assert sleeps == []

    def test_does_not_retry_on_other_error_with_no_errorcode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Substring fallback path: an OperationalError with no
        ``sqlite_errorcode`` whose message lacks "locked"/"busy" must
        still propagate immediately (PR #123 #S1 protected this).
        """
        sleeps: list[float] = []
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda s: sleeps.append(s),
        )
        attempts = {"n": 0}

        def op() -> None:
            attempts["n"] += 1
            raise _make_op_error("disk I/O error")

        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
            retry_on_lock_contention(op, operation_name="no_retry_substr")
        assert attempts["n"] == 1
        assert sleeps == []

    def test_exhausts_attempts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Persistent contention past ``max_attempts`` must surface the
        final ``OperationalError`` so the caller can log + skip.
        """
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )
        attempts = {"n": 0}

        def op() -> None:
            attempts["n"] += 1
            raise _make_op_error("database is locked")

        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            retry_on_lock_contention(
                op,
                max_attempts=3,
                operation_name="exhaust_test",
            )
        assert attempts["n"] == 3

    def test_emits_warning_log_per_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each retry emits exactly one ``sqlite_lock_contention_retry``
        warning carrying ``operation_name``, ``attempt``,
        ``max_attempts``, ``backoff_seconds``, and ``error``. The final
        attempt does not warn (it raises and emits the exhausted
        event).

        Uses the canonical ``monkeypatch.setattr(conn_mod, "logger",
        structlog.get_logger())`` pattern: ``cache_logger_on_first_use=True``
        in ``src/utils/logging.py`` freezes the bound logger at first
        call, so ``capture_logs()`` would otherwise miss events emitted
        by the cached production logger (see
        ``tests/unit/test_scheduling/test_monitoring_check_job.py``).
        """
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )
        monkeypatch.setattr(conn_mod, "logger", structlog.get_logger())

        attempts = {"n": 0}

        def op() -> str:
            attempts["n"] += 1
            if attempts["n"] < 3:  # fail attempt 1 + 2, succeed attempt 3
                raise _make_op_error(
                    "database is busy",
                    errorcode=conn_mod._SQLITE_BUSY,
                )
            return "ok"

        with structlog.testing.capture_logs() as logs:
            assert (
                retry_on_lock_contention(
                    op,
                    max_attempts=3,
                    backoff_seconds=0.01,
                    operation_name="warn_test",
                )
                == "ok"
            )

        retry_logs = [
            entry for entry in logs if entry["event"] == "sqlite_lock_contention_retry"
        ]
        # 2 failed attempts -> 2 warnings, then success on attempt 3.
        assert len(retry_logs) == 2
        for idx, entry in enumerate(retry_logs):
            assert entry["log_level"] == "warning"
            assert entry["operation_name"] == "warn_test"
            assert entry["attempt"] == idx + 1
            assert entry["max_attempts"] == 3
            # Linear backoff: 0.01, 0.02
            assert entry["backoff_seconds"] == pytest.approx(0.01 * (idx + 1))
            assert "busy" in entry["error"].lower()

        # Success path -- no exhausted event on this run.
        assert not any(
            entry["event"] == "sqlite_lock_contention_exhausted" for entry in logs
        )

    def test_emits_error_log_when_exhausted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the retry budget is exhausted, the helper emits exactly
        one ``sqlite_lock_contention_exhausted`` error event before
        re-raising. Pins the audit-trail contract so a future refactor
        that drops the give-up event fails loudly.
        """
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )
        monkeypatch.setattr(conn_mod, "logger", structlog.get_logger())

        def op() -> None:
            raise _make_op_error("database is locked")

        with structlog.testing.capture_logs() as logs:
            with pytest.raises(sqlite3.OperationalError):
                retry_on_lock_contention(
                    op,
                    max_attempts=2,
                    operation_name="exhaust_log_test",
                )

        exhausted = [
            entry
            for entry in logs
            if entry["event"] == "sqlite_lock_contention_exhausted"
        ]
        assert len(exhausted) == 1
        entry = exhausted[0]
        assert entry["log_level"] == "error"
        assert entry["operation_name"] == "exhaust_log_test"
        assert entry["attempts"] == 2
        assert "locked" in entry["error"].lower()

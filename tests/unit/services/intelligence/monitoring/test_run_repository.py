"""Tests for ``MonitoringRunRepository`` (Milestone 9.1).

Covers:
- Round-trip persistence (insert + fetch by id).
- ``list_runs`` filtering by subscription_id and ordering by
  ``started_at DESC``.
- ``list_runs`` ``limit`` validation.
- ``record_run`` raises ``ValueError`` on duplicate ``run_id``.
- ``record_run`` rolls back when the paper insert fails (atomicity).
- FOREIGN KEY ON DELETE CASCADE removes paper rows when the parent
  run is deleted (regression for migration FK clause).
- ``initialize`` is required before any read/write.
- Path safety -- repository rejects paths outside approved roots.
- ``get_run`` returns ``None`` for unknown id.
- ``user_id`` denormalization respects the constructor default and
  per-call override.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.services.intelligence.models.monitoring import PaperSource
from src.services.intelligence.monitoring.models import (
    MonitoringPaperRecord,
    MonitoringRun,
    MonitoringRunStatus,
)
from src.services.intelligence.monitoring.run_repository import (
    MonitoringRunRepository,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    path.unlink(missing_ok=True)
    return path


def _seed_subscription(db_path: Path, subscription_id: str) -> None:
    """Insert a stub ``subscriptions`` row so the FK on
    ``monitoring_runs.subscription_id`` (added in MIGRATION_V3) is
    satisfied. Tests that record runs need their subscription_id to
    resolve to a real parent row.
    """
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO subscriptions (
                subscription_id, user_id, name, config
            ) VALUES (?, ?, ?, ?)
            """,
            (subscription_id, "default", "stub", "{}"),
        )
        conn.commit()


@pytest.fixture
def repo(db_path: Path) -> MonitoringRunRepository:
    r = MonitoringRunRepository(db_path)
    r.initialize()
    # Seed the default subscription_id used by ``_make_run`` so tests
    # that don't override it still satisfy the new FK from V3.
    _seed_subscription(db_path, "sub-test001")
    return r


def _make_run(
    *,
    run_id: str = "run-aaa111",
    subscription_id: str = "sub-test001",
    status: MonitoringRunStatus = MonitoringRunStatus.SUCCESS,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    papers_seen: int = 0,
    papers_new: int = 0,
    error: str | None = None,
    papers: list[MonitoringPaperRecord] | None = None,
) -> MonitoringRun:
    return MonitoringRun(
        run_id=run_id,
        subscription_id=subscription_id,
        source=PaperSource.ARXIV,
        started_at=started_at or datetime(2024, 1, 1, tzinfo=timezone.utc),
        finished_at=finished_at,
        status=status,
        papers_seen=papers_seen,
        papers_new=papers_new,
        error=error,
        papers=papers or [],
    )


def _make_record(
    *,
    paper_id: str = "2301.0001",
    is_new: bool = True,
    relevance_score: float | None = None,
    relevance_reasoning: str | None = None,
) -> MonitoringPaperRecord:
    return MonitoringPaperRecord(
        paper_id=paper_id,
        title=paper_id,  # repo stores paper_id only; title=paper_id round-trips
        is_new=is_new,
        relevance_score=relevance_score,
        relevance_reasoning=relevance_reasoning,
    )


def _make_begin_immediate_failure_open(  # type: ignore[no-untyped-def]
    error_message: str,
    *,
    sqlite_errorcode: int | None = None,
    max_failures: int | None = None,
):
    """Return a fake ``open_connection`` plus an attempt counter dict.

    The fake yields a thin proxy whose ``execute`` raises an
    ``OperationalError`` with ``error_message`` whenever the SQL is
    exactly ``"BEGIN IMMEDIATE"``. Every other call is delegated to the
    real connection so PRAGMA setup, queries, and rollback all behave
    normally.

    Args:
        error_message: Message to attach to the synthetic
            ``OperationalError``.
        sqlite_errorcode: When provided, attached to the raised
            ``OperationalError`` via ``sqlite_errorcode`` so tests can
            exercise the broadened error-code retry path (Python 3.11+
            attribute, see :pep:`630` history). ``None`` leaves the
            attribute unset, mirroring the substring-fallback path.
        max_failures: When set, the proxy fails the first
            ``max_failures`` ``BEGIN IMMEDIATE`` calls and then
            transparently succeeds, simulating transient lock contention
            that resolves before the retry budget is exhausted. ``None``
            (default) fails every attempt -- mirrors the legacy
            "always fail" behavior used by the give-up test.

    sqlite3.Connection methods are read-only (C-implemented), so we
    cannot monkeypatch them directly -- a proxy is necessary.
    """
    import sqlite3 as _sqlite3
    from contextlib import contextmanager

    from src.storage.intelligence_graph.connection import (
        open_connection as real_open,
    )

    attempts = {"n": 0, "failures": 0}

    class _ConnProxy:
        def __init__(self, real_conn: _sqlite3.Connection) -> None:
            self._real = real_conn

        def execute(self, sql: str, *args: object, **kwargs: object) -> object:
            if sql == "BEGIN IMMEDIATE":
                # Fail forever, or only the first ``max_failures`` calls
                # when ``max_failures`` is set.
                if max_failures is None or attempts["failures"] < max_failures:
                    attempts["failures"] += 1
                    exc = _sqlite3.OperationalError(error_message)
                    if sqlite_errorcode is not None:
                        # ``sqlite_errorcode`` is set by the C layer
                        # when sqlite emits a real error. Tests must
                        # set it explicitly to exercise the
                        # error-code retry branch.
                        exc.sqlite_errorcode = sqlite_errorcode
                    raise exc
            return self._real.execute(sql, *args, **kwargs)

        def executemany(self, sql: str, *args: object, **kwargs: object) -> object:
            return self._real.executemany(sql, *args, **kwargs)

        def commit(self) -> None:
            self._real.commit()

        def rollback(self) -> None:
            self._real.rollback()

    @contextmanager  # type: ignore[arg-type]
    def fake_open(db_path):  # type: ignore[no-untyped-def]
        with real_open(db_path) as conn:
            attempts["n"] += 1
            yield _ConnProxy(conn)

    return fake_open, attempts


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialize:
    def test_initialize_creates_tables(self, db_path: Path) -> None:
        repo = MonitoringRunRepository(db_path)
        repo.initialize()
        with sqlite3.connect(str(db_path)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "monitoring_runs" in tables
        assert "monitoring_papers" in tables

    def test_initialize_idempotent(self, db_path: Path) -> None:
        repo = MonitoringRunRepository(db_path)
        repo.initialize()
        repo.initialize()  # no-op
        assert repo._initialized is True

    def test_method_before_initialize_raises(self, db_path: Path) -> None:
        repo = MonitoringRunRepository(db_path)
        with pytest.raises(RuntimeError, match="not initialized"):
            repo.get_run("run-x")


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    def test_rejects_path_outside_approved_roots(self) -> None:
        from src.utils.security import SecurityError

        with pytest.raises(SecurityError):
            MonitoringRunRepository("/etc/forbidden.db")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_record_and_get_no_papers(self, repo: MonitoringRunRepository) -> None:
        run = _make_run(papers_seen=0, papers_new=0)
        repo.record_run(run)
        fetched = repo.get_run(run.run_id)
        assert fetched is not None
        assert fetched.run_id == run.run_id
        assert fetched.subscription_id == run.subscription_id
        assert fetched.status is MonitoringRunStatus.SUCCESS
        assert fetched.papers_seen == 0
        assert fetched.papers_new == 0
        assert fetched.papers == []

    def test_record_and_get_with_papers(self, repo: MonitoringRunRepository) -> None:
        records = [
            _make_record(paper_id="2301.0001", is_new=True),
            _make_record(
                paper_id="2301.0002",
                is_new=False,
                relevance_score=0.85,
                relevance_reasoning="strong match",
            ),
        ]
        run = _make_run(papers_seen=2, papers_new=1, papers=records)
        repo.record_run(run)
        fetched = repo.get_run(run.run_id)
        assert fetched is not None
        assert fetched.papers_seen == 2
        assert fetched.papers_new == 1
        # Papers come back ordered by paper_id ASC.
        assert [p.paper_id for p in fetched.papers] == ["2301.0001", "2301.0002"]
        assert fetched.papers[0].is_new is True
        assert fetched.papers[1].is_new is False
        assert fetched.papers[1].relevance_score == 0.85
        assert fetched.papers[1].relevance_reasoning == "strong match"

    def test_record_persists_finished_at_and_error(
        self, repo: MonitoringRunRepository
    ) -> None:
        finished = datetime(2024, 1, 1, 1, 2, 3, tzinfo=timezone.utc)
        run = _make_run(
            run_id="run-failure",
            status=MonitoringRunStatus.FAILED,
            finished_at=finished,
            error="boom",
        )
        repo.record_run(run)
        fetched = repo.get_run(run.run_id)
        assert fetched is not None
        assert fetched.finished_at == finished
        assert fetched.error == "boom"
        assert fetched.status is MonitoringRunStatus.FAILED

    def test_get_returns_none_for_missing(self, repo: MonitoringRunRepository) -> None:
        assert repo.get_run("run-missing") is None


# ---------------------------------------------------------------------------
# user_id handling
# ---------------------------------------------------------------------------


class TestUserId:
    def test_default_user_id_used_when_not_provided(self, db_path: Path) -> None:
        repo = MonitoringRunRepository(db_path, user_id="alice")
        repo.initialize()
        _seed_subscription(db_path, "sub-test001")
        run = _make_run()
        repo.record_run(run)
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT user_id FROM monitoring_runs WHERE run_id = ?",
                (run.run_id,),
            ).fetchone()
        assert row[0] == "alice"

    def test_explicit_user_id_overrides_default(
        self, repo: MonitoringRunRepository, db_path: Path
    ) -> None:
        run = _make_run()
        repo.record_run(run, user_id="bob")
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT user_id FROM monitoring_runs WHERE run_id = ?",
                (run.run_id,),
            ).fetchone()
        assert row[0] == "bob"


# ---------------------------------------------------------------------------
# Duplicate prevention + atomicity
# ---------------------------------------------------------------------------


class TestRecordRunErrors:
    def test_duplicate_run_id_raises(self, repo: MonitoringRunRepository) -> None:
        run = _make_run()
        repo.record_run(run)
        with pytest.raises(ValueError, match="already exists"):
            repo.record_run(run)

    def test_record_run_rolls_back_on_failure(self, db_path: Path) -> None:
        """Insert a paper twice in the same run -- the second triggers a
        PRIMARY KEY violation on (run_id, paper_id), and the whole
        record_run transaction must roll back so no orphaned run row
        survives.
        """
        repo = MonitoringRunRepository(db_path)
        repo.initialize()
        # Pydantic will not let us construct two records with the same
        # paper_id in a single run via normal channels, but we can
        # bypass validation by mutating the list after construction.
        records = [_make_record(paper_id="2301.0001")]
        run = _make_run(papers=records)
        # Append a duplicate directly on the model attribute to bypass
        # the field validator.
        run.papers.append(_make_record(paper_id="2301.0001"))
        with pytest.raises(sqlite3.IntegrityError):
            repo.record_run(run)
        # Run must NOT be persisted.
        assert repo.get_run(run.run_id) is None


# ---------------------------------------------------------------------------
# list_runs
# ---------------------------------------------------------------------------


class TestListRuns:
    def test_list_empty(self, repo: MonitoringRunRepository) -> None:
        assert repo.list_runs() == []

    def test_list_orders_by_started_at_desc(
        self, repo: MonitoringRunRepository
    ) -> None:
        for i, hour in enumerate([10, 12, 11]):
            repo.record_run(
                _make_run(
                    run_id=f"run-{i:03d}",
                    started_at=datetime(2024, 1, 1, hour, tzinfo=timezone.utc),
                )
            )
        runs = repo.list_runs()
        # Sorted DESC: 12, 11, 10
        assert [r.run_id for r in runs] == ["run-001", "run-002", "run-000"]

    def test_list_filter_by_subscription(
        self, repo: MonitoringRunRepository, db_path: Path
    ) -> None:
        _seed_subscription(db_path, "sub-x")
        _seed_subscription(db_path, "sub-y")
        repo.record_run(_make_run(run_id="run-a", subscription_id="sub-x"))
        repo.record_run(_make_run(run_id="run-b", subscription_id="sub-y"))
        result = repo.list_runs(subscription_id="sub-x")
        assert [r.run_id for r in result] == ["run-a"]

    def test_list_respects_limit(self, repo: MonitoringRunRepository) -> None:
        for i in range(5):
            repo.record_run(
                _make_run(
                    run_id=f"run-{i:03d}",
                    started_at=datetime(2024, 1, 1, i, tzinfo=timezone.utc),
                )
            )
        result = repo.list_runs(limit=2)
        assert len(result) == 2

    def test_list_invalid_limit_raises(self, repo: MonitoringRunRepository) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            repo.list_runs(limit=0)
        with pytest.raises(ValueError, match="must be positive"):
            repo.list_runs(limit=-1)


# ---------------------------------------------------------------------------
# Foreign Key CASCADE
# ---------------------------------------------------------------------------


class TestOperationalErrorRetry:
    """Tests for ``record_run`` retry on transient ``database is locked``
    (PR #119 review #S9, hardened in PR #123 #C1).

    History
    -------
    The original success-path test used ``threading.Timer(0.08, ...)``
    to release a real lock holder mid-retry. That was timing-dependent:
    on a slow CI runner the window could close before the first retry
    even fired, masking real bugs. We now use the same in-process
    ``_make_begin_immediate_failure_open`` proxy already used by the
    give-up test, with ``max_failures=N`` so the first N attempts raise
    and the (N+1)th transparently succeeds. This makes the retry
    counter deterministic without losing semantic coverage -- the
    proxy raises the exact ``OperationalError`` the runner would see.
    """

    def test_record_run_retries_on_locked_then_succeeds(
        self,
        repo: MonitoringRunRepository,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two transient lock failures, then success on attempt 3."""
        from src.services.intelligence.monitoring import run_repository as rr_mod

        max_failures = MonitoringRunRepository._RECORD_RUN_MAX_ATTEMPTS - 1
        fake_open, attempts = _make_begin_immediate_failure_open(
            error_message="database is locked",
            max_failures=max_failures,
        )
        monkeypatch.setattr(rr_mod, "open_connection", fake_open)

        # Capture every sleep so we can assert the backoff schedule
        # without actually waiting.
        sleep_calls: list[float] = []
        monkeypatch.setattr(
            "src.services.intelligence.monitoring.run_repository.time.sleep",
            lambda s: sleep_calls.append(s),
        )

        run = _make_run(run_id="run-eventual-success")
        repo.record_run(run)  # eventually succeeds on attempt N+1

        # Exactly ``max_failures`` retries fired, then the success path.
        assert attempts["failures"] == max_failures
        assert attempts["n"] == max_failures + 1
        # One sleep per failed attempt -- linear backoff (50ms, 100ms).
        assert len(sleep_calls) == max_failures
        assert sleep_calls == [
            MonitoringRunRepository._RECORD_RUN_RETRY_BACKOFF_SECONDS * (i + 1)
            for i in range(max_failures)
        ]
        # Run actually persisted -- the proxy passes through to the
        # real connection on the success attempt.
        assert repo.get_run(run.run_id) is not None

    def test_record_run_propagates_non_lock_operational_error(
        self, repo: MonitoringRunRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OperationalError without "locked" in the message must not be
        retried -- it surfaces immediately so callers see the real bug.
        Uses a proxy ``open_connection`` whose BEGIN IMMEDIATE raises a
        non-lock OperationalError; everything else delegates to the
        real connection.
        """
        import sqlite3 as _sqlite3

        from src.services.intelligence.monitoring import run_repository as rr_mod

        fake_open, attempts = _make_begin_immediate_failure_open(
            error_message="disk I/O error"
        )
        monkeypatch.setattr(rr_mod, "open_connection", fake_open)
        run = _make_run(run_id="run-no-retry")
        with pytest.raises(_sqlite3.OperationalError, match="disk I/O error"):
            repo.record_run(run)
        # No retry on a non-lock error.
        assert attempts["n"] == 1

    def test_record_run_gives_up_after_max_attempts(
        self,
        repo: MonitoringRunRepository,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """If the lock contention persists past all retries, the final
        OperationalError must propagate so the runner can log + skip.

        Also asserts the structured ``monitoring_run_record_retry``
        warning fires exactly ``_RECORD_RUN_MAX_ATTEMPTS - 1`` times --
        the final attempt does not warn because it raises (see #S3).
        """
        import sqlite3 as _sqlite3

        import structlog.testing

        from src.services.intelligence.monitoring import run_repository as rr_mod

        fake_open, attempts = _make_begin_immediate_failure_open(
            error_message="database is locked"
        )
        monkeypatch.setattr(rr_mod, "open_connection", fake_open)
        # Speed the test up so we don't sleep through the real backoff.
        monkeypatch.setattr(
            MonitoringRunRepository,
            "_RECORD_RUN_RETRY_BACKOFF_SECONDS",
            0.001,
        )

        run = _make_run(run_id="run-give-up")
        # ``structlog.testing.capture_logs`` is the project-default
        # capture facility -- the codebase does not configure structlog
        # against the stdlib root logger, so plain ``caplog`` would not
        # see structlog events. ``capture_logs`` swaps in a recording
        # processor for the duration of the block.
        with structlog.testing.capture_logs() as logs:
            with pytest.raises(_sqlite3.OperationalError, match="database is locked"):
                repo.record_run(run)
        assert attempts["n"] == MonitoringRunRepository._RECORD_RUN_MAX_ATTEMPTS

        retry_logs = [
            entry for entry in logs if entry["event"] == "monitoring_run_record_retry"
        ]
        # Exactly N-1 retries warn; the final attempt raises before
        # logging. This pins the "log on retry, raise on give-up"
        # semantics so a future refactor that double-logs (or skips
        # the warn) fails loudly.
        assert len(retry_logs) == MonitoringRunRepository._RECORD_RUN_MAX_ATTEMPTS - 1
        for idx, entry in enumerate(retry_logs):
            assert entry["log_level"] == "warning"
            assert entry["run_id"] == "run-give-up"
            assert entry["attempt"] == idx + 1
            assert (
                entry["max_attempts"]
                == MonitoringRunRepository._RECORD_RUN_MAX_ATTEMPTS
            )
            assert "locked" in entry["error"].lower()


class TestCascadeDelete:
    def test_delete_run_cascades_to_papers(
        self, repo: MonitoringRunRepository, db_path: Path
    ) -> None:
        records = [
            _make_record(paper_id="2301.0001"),
            _make_record(paper_id="2301.0002"),
        ]
        run = _make_run(papers_seen=2, papers_new=2, papers=records)
        repo.record_run(run)
        # Delete the parent through a direct SQL call -- the repository
        # is append-only so it has no public delete method, but the FK
        # CASCADE clause should still trigger.
        from src.storage.intelligence_graph.connection import open_connection

        with open_connection(db_path) as conn:
            conn.execute(
                "DELETE FROM monitoring_runs WHERE run_id = ?",
                (run.run_id,),
            )
            conn.commit()
            paper_count = conn.execute(
                "SELECT COUNT(*) FROM monitoring_papers WHERE run_id = ?",
                (run.run_id,),
            ).fetchone()[0]
        assert paper_count == 0

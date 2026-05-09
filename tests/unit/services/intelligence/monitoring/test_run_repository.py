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
    MonitoringPaperAudit,
    MonitoringPaperRecord,
    MonitoringRun,
    MonitoringRunAudit,
    MonitoringRunStatus,
)
from src.services.intelligence.monitoring.run_repository import (
    MonitoringRunRepository,
)
from src.storage.intelligence_graph import connection as conn_mod

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
    source: PaperSource = PaperSource.ARXIV,
) -> MonitoringPaperRecord:
    return MonitoringPaperRecord(
        paper_id=paper_id,
        # Audit DTO has no title field; the rich ``title`` here is for
        # in-memory MonitoringPaperRecord round-trip only -- the
        # repository's read path returns MonitoringPaperAudit which
        # carries only the persisted columns (paper_id, registered,
        # relevance_score, relevance_reasoning, source).
        title=paper_id,
        is_new=is_new,
        relevance_score=relevance_score,
        relevance_reasoning=relevance_reasoning,
        source=source,
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

        with pytest.raises(SecurityError, match="outside approved storage roots"):
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
        # Regression guard for the DTO rename (PR #124 #C3): a refactor
        # that reverts ``_row_to_audit`` to MonitoringRun would still
        # match all field-value asserts since the types share columns.
        assert isinstance(fetched, MonitoringRunAudit)
        assert fetched.run_id == run.run_id
        assert fetched.subscription_id == run.subscription_id
        assert fetched.status is MonitoringRunStatus.SUCCESS
        assert fetched.papers_seen == 0
        assert fetched.papers_new == 0
        assert fetched.papers == []

    def test_record_and_get_with_papers(self, repo: MonitoringRunRepository) -> None:
        records = [
            _make_record(paper_id="2301.0001", is_new=True, source=PaperSource.ARXIV),
            _make_record(
                paper_id="2301.0002",
                is_new=False,
                relevance_score=0.85,
                relevance_reasoning="strong match",
                source=PaperSource.OPENALEX,
            ),
        ]
        run = _make_run(papers_seen=2, papers_new=1, papers=records)
        repo.record_run(run)
        fetched = repo.get_run(run.run_id)
        assert fetched is not None
        # Regression guard for the DTO rename (PR #124 #C3).
        assert isinstance(fetched, MonitoringRunAudit)
        assert fetched.papers_seen == 2
        assert fetched.papers_new == 1
        # Papers come back ordered by paper_id ASC.
        assert [p.paper_id for p in fetched.papers] == ["2301.0001", "2301.0002"]
        for p in fetched.papers:
            # Per-paper DTO type guard (PR #124 #C3) -- prevents a
            # regression that smuggles MonitoringPaperRecord back onto
            # the read path.
            assert isinstance(p, MonitoringPaperAudit)
        # Read path returns MonitoringPaperAudit (PR #119 #S6); the
        # ``is_new`` flag on the rich record is persisted as
        # ``registered`` in the audit type.
        assert fetched.papers[0].registered is True
        assert fetched.papers[1].registered is False
        # Default-NULL round-trip on papers[0] -- prior tests only
        # asserted the non-NULL papers[1] case, leaving the most likely
        # column-mapping regression vector uncovered (PR #124 #C4).
        assert fetched.papers[0].relevance_score is None
        assert fetched.papers[0].relevance_reasoning is None
        assert fetched.papers[1].relevance_score == 0.85
        assert fetched.papers[1].relevance_reasoning == "strong match"
        # Issue #141: per-paper source round-trips through the V5 column.
        assert fetched.papers[0].source is PaperSource.ARXIV
        assert fetched.papers[1].source is PaperSource.OPENALEX

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
        assert isinstance(fetched, MonitoringRunAudit)
        assert fetched.finished_at == finished
        assert fetched.error == "boom"
        assert fetched.status is MonitoringRunStatus.FAILED

    def test_get_returns_none_for_missing(self, repo: MonitoringRunRepository) -> None:
        assert repo.get_run("run-missing") is None

    def test_fetch_papers_returns_only_validated_audit_dtos(
        self, repo: MonitoringRunRepository
    ) -> None:
        """PR #124 team review: pin the read-path type contract.

        ``_fetch_papers`` must return ``list[MonitoringPaperAudit]`` --
        never raw rows / dicts. The source-side assertion in the
        method enforces this at runtime; this test pins the contract
        from the consumer's perspective.
        """
        records = [
            _make_record(paper_id="2301.0001", is_new=True),
            _make_record(
                paper_id="2301.0002",
                is_new=False,
                relevance_score=0.5,
                relevance_reasoning="ok",
            ),
        ]
        run = _make_run(papers_seen=2, papers_new=1, papers=records)
        repo.record_run(run)

        # Use the public read path (which delegates to _fetch_papers).
        fetched = repo.get_run(run.run_id)
        assert fetched is not None
        # Every element must be the audit DTO type -- not a dict, not
        # the rich MonitoringPaperRecord, not a sqlite3.Row.
        # Strict identity check (``type(...) is ...``, not ``isinstance``):
        # a future MonitoringPaperRecord-style subclass that bypasses
        # audit-DTO validation would still satisfy ``isinstance``; only
        # ``is`` catches the type-leak we're guarding against.
        for paper in fetched.papers:
            assert (
                type(paper) is MonitoringPaperAudit
            ), f"_fetch_papers leaked non-audit type: {type(paper).__name__}"


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
        # The test does not seed the subscriptions table, so the
        # monitoring_runs INSERT hits the FOREIGN KEY constraint before
        # the duplicate-paper UNIQUE constraint. Both are IntegrityError;
        # the FK message is what we actually observe.
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint"):
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
        # DTO rename regression guard (PR #124 #C3).
        for r in runs:
            assert isinstance(r, MonitoringRunAudit)

    def test_list_filter_by_subscription(
        self, repo: MonitoringRunRepository, db_path: Path
    ) -> None:
        _seed_subscription(db_path, "sub-x")
        _seed_subscription(db_path, "sub-y")
        repo.record_run(_make_run(run_id="run-a", subscription_id="sub-x"))
        repo.record_run(_make_run(run_id="run-b", subscription_id="sub-y"))
        result = repo.list_runs(subscription_id="sub-x")
        assert [r.run_id for r in result] == ["run-a"]
        for r in result:
            assert isinstance(r, MonitoringRunAudit)

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
        for r in result:
            assert isinstance(r, MonitoringRunAudit)

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

        max_failures = conn_mod.DEFAULT_MAX_ATTEMPTS - 1
        fake_open, attempts = _make_begin_immediate_failure_open(
            error_message="database is locked",
            max_failures=max_failures,
        )
        monkeypatch.setattr(rr_mod, "open_connection", fake_open)

        # Capture every sleep so we can assert the backoff schedule
        # without actually waiting. Retry mechanics now live in
        # ``src.storage.intelligence_graph.connection`` (issue #133).
        sleep_calls: list[float] = []
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
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
            conn_mod.DEFAULT_BACKOFF_SECONDS * (i + 1) for i in range(max_failures)
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

        sleep_calls: list[float] = []
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda s: sleep_calls.append(s),
        )

        fake_open, attempts = _make_begin_immediate_failure_open(
            error_message="disk I/O error"
        )
        monkeypatch.setattr(rr_mod, "open_connection", fake_open)
        run = _make_run(run_id="run-no-retry")
        with pytest.raises(_sqlite3.OperationalError, match="disk I/O error"):
            repo.record_run(run)
        # No retry on a non-lock error -- no sleep should have fired.
        assert attempts["n"] == 1
        assert sleep_calls == []

    def test_record_run_gives_up_after_max_attempts(
        self,
        repo: MonitoringRunRepository,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the lock contention persists past all retries, the final
        OperationalError must propagate so the runner can log + skip.

        Also asserts the shared ``sqlite_lock_contention_retry`` warning
        fires exactly ``_RECORD_RUN_MAX_ATTEMPTS - 1`` times -- the
        final attempt does not warn because it raises (see #S3). Event
        names live on ``retry_on_lock_contention`` (issue #133) so the
        same audit signal is emitted by every SQLite write site that
        adopts the helper.
        """
        import sqlite3 as _sqlite3

        import structlog
        import structlog.testing

        from src.services.intelligence.monitoring import run_repository as rr_mod

        fake_open, attempts = _make_begin_immediate_failure_open(
            error_message="database is locked"
        )
        monkeypatch.setattr(rr_mod, "open_connection", fake_open)
        # Speed the test up by patching sleep in the connection module.
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )
        # ``src/utils/logging.py`` configures structlog with
        # ``cache_logger_on_first_use=True``; under that mode the
        # module-level ``logger`` in ``connection.py`` is bound to the
        # production processor chain at import time and ignores
        # ``capture_logs()``'s processor swap. Re-bind to a fresh proxy
        # so the current global configuration (set by capture_logs) is
        # honored.
        monkeypatch.setattr(conn_mod, "logger", structlog.get_logger())

        run = _make_run(run_id="run-give-up")
        # ``structlog.testing.capture_logs`` is the project-default
        # capture facility -- the codebase does not configure structlog
        # against the stdlib root logger, so plain ``caplog`` would not
        # see structlog events. ``capture_logs`` swaps in a recording
        # processor for the duration of the block.
        with structlog.testing.capture_logs() as logs:
            with pytest.raises(_sqlite3.OperationalError, match="database is locked"):
                repo.record_run(run)
        assert attempts["n"] == conn_mod.DEFAULT_MAX_ATTEMPTS

        retry_logs = [
            entry for entry in logs if entry["event"] == "sqlite_lock_contention_retry"
        ]
        # Exactly N-1 retries warn; the final attempt raises (and emits
        # the ``sqlite_lock_contention_exhausted`` error event instead).
        # This pins the "log on retry, error on give-up" semantics so a
        # future refactor that double-logs (or skips the warn) fails
        # loudly.
        assert len(retry_logs) == conn_mod.DEFAULT_MAX_ATTEMPTS - 1
        for idx, entry in enumerate(retry_logs):
            assert entry["log_level"] == "warning"
            assert entry["operation_name"] == "monitoring_record_run"
            assert entry["attempt"] == idx + 1
            assert entry["max_attempts"] == conn_mod.DEFAULT_MAX_ATTEMPTS
            assert "locked" in entry["error"].lower()
        # The exhausted-attempts error is emitted exactly once by the
        # helper before re-raising.
        exhausted_logs = [
            entry
            for entry in logs
            if entry["event"] == "sqlite_lock_contention_exhausted"
        ]
        assert len(exhausted_logs) == 1
        assert exhausted_logs[0]["log_level"] == "error"
        assert exhausted_logs[0]["operation_name"] == "monitoring_record_run"
        assert exhausted_logs[0]["total_attempts"] == conn_mod.DEFAULT_MAX_ATTEMPTS

    def test_record_run_retries_on_busy_error_code(
        self, repo: MonitoringRunRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SQLITE_BUSY (errorcode 5) is retried even when the message
        does not contain "locked" -- exercises the errorcode-based
        retry path now in the shared helper (issue #133, originally
        PR #123 #S1). Older substring-only logic would miss this because
        SQLite's English wording for code 5 is "database is busy", not
        "locked".
        """
        from src.services.intelligence.monitoring import run_repository as rr_mod

        max_failures = 1  # one BUSY then succeed
        fake_open, attempts = _make_begin_immediate_failure_open(
            error_message="database is busy",
            sqlite_errorcode=conn_mod._SQLITE_BUSY,
            max_failures=max_failures,
        )
        monkeypatch.setattr(rr_mod, "open_connection", fake_open)
        # Skip real backoff sleep -- helper sleeps in connection module.
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )

        run = _make_run(run_id="run-busy-retry")
        repo.record_run(run)

        # The retry actually fired before success.
        assert attempts["failures"] == max_failures
        assert repo.get_run(run.run_id) is not None

    def test_record_run_retries_on_locked_error_code(
        self, repo: MonitoringRunRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SQLITE_LOCKED (errorcode 6) -- same retry contract as
        SQLITE_BUSY. Pinned separately so a future refactor that
        accidentally drops one of the two codes fails loudly.
        """
        from src.services.intelligence.monitoring import run_repository as rr_mod

        fake_open, attempts = _make_begin_immediate_failure_open(
            error_message="some locked-table message",
            sqlite_errorcode=conn_mod._SQLITE_LOCKED,
            max_failures=1,
        )
        monkeypatch.setattr(rr_mod, "open_connection", fake_open)
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )

        run = _make_run(run_id="run-locked-code")
        repo.record_run(run)
        assert attempts["failures"] == 1
        # Persistence assertion: the run was successfully written after retry.
        assert repo.get_run(run.run_id) is not None

    def test_record_run_propagates_unrelated_operational_error_with_no_errorcode(
        self, repo: MonitoringRunRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OperationalError with no sqlite_errorcode and a non-lock
        message must surface immediately -- we must not retry "syntax
        error" or any other non-contention failure mode (PR #123 #S1).
        """
        import sqlite3 as _sqlite3

        from src.services.intelligence.monitoring import run_repository as rr_mod

        fake_open, attempts = _make_begin_immediate_failure_open(
            error_message="syntax error near 'BEGIN'",
            sqlite_errorcode=None,  # explicit -- no errorcode attached
        )
        monkeypatch.setattr(rr_mod, "open_connection", fake_open)
        run = _make_run(run_id="run-no-retry-syntax")
        with pytest.raises(_sqlite3.OperationalError, match="syntax error"):
            repo.record_run(run)
        assert attempts["n"] == 1


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


class TestUnknownSourceFailLoud:
    """M-6: ``_fetch_papers`` re-raises on unrecognised source values.

    A ``monitoring_papers`` row whose ``source`` column contains a
    value not in the ``PaperSource`` enum must (a) emit a structured
    ``monitoring_paper_unknown_source`` log event and (b) re-raise the
    ``ValueError`` so the caller learns about schema drift rather than
    silently swallowing it.
    """

    def test_fetch_papers_unknown_source_logs_and_reraises(
        self,
        repo: MonitoringRunRepository,
        db_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import sqlite3 as _sqlite3
        import structlog
        import structlog.testing

        from src.services.intelligence.monitoring import run_repository as rr_mod

        # Record a run with a valid paper so the FK constraint is satisfied.
        run = _make_run(
            run_id="run-unknown-src",
            papers_seen=1,
            papers_new=1,
            papers=[_make_record(paper_id="paper:bad:001")],
        )
        repo.record_run(run)

        # Corrupt the source column directly -- bypass the CHECK constraint
        # to simulate future schema drift (e.g., a new PaperSource enum value
        # was added to the DB but not yet to this Python version).
        # We must disable CHECK constraints for this raw write because the
        # schema guard from H-3 would otherwise prevent the corrupt value.
        with _sqlite3.connect(str(db_path)) as conn:
            conn.execute("PRAGMA ignore_check_constraints = ON")
            conn.execute(
                "UPDATE monitoring_papers SET source = ? WHERE paper_id = ?",
                ("not_a_real_source", "paper:bad:001"),
            )
            conn.commit()

        # H-5: use monkeypatch.setattr for safe logger rebinding so the
        # original is always restored even if the test body raises.
        monkeypatch.setattr(rr_mod, "logger", structlog.get_logger())
        with structlog.testing.capture_logs() as logs:
            with pytest.raises(ValueError, match=r"not a valid PaperSource"):
                repo.get_run("run-unknown-src")

        error_events = [
            e for e in logs if e.get("event") == "monitoring_paper_unknown_source"
        ]
        assert len(error_events) == 1
        assert error_events[0].get("paper_id") == "paper:bad:001"
        assert error_events[0].get("raw_value") == "not_a_real_source"


# ===========================================================================
# C-2: backfill_papers round-trips through the database (V8 migration)
# ===========================================================================


class TestBackfillPapersRoundTrip:
    """C-2 drift-guard: backfill_papers is persisted and read back correctly."""

    def test_record_run_persists_backfill_papers(
        self, db_path: Path, repo: MonitoringRunRepository
    ) -> None:
        """backfill_papers is written to monitoring_runs and read back via get_run."""
        from src.services.intelligence.monitoring.models import MonitoringRun

        _seed_subscription(db_path, "sub-bf-persist")
        run = MonitoringRun(
            subscription_id="sub-bf-persist",
            backfill_papers=12,
        )
        repo.record_run(run, user_id="alice")
        audit = repo.get_run(run.run_id)
        assert audit is not None
        assert audit.backfill_papers == 12, (
            f"backfill_papers should round-trip as 12, got {audit.backfill_papers}. "
            "C-2 fix: ensure V8 migration, record_run INSERT, and _row_to_audit SELECT "
            "all include the backfill_papers column."
        )

    def test_record_run_backfill_papers_zero_by_default(
        self, db_path: Path, repo: MonitoringRunRepository
    ) -> None:
        """When backfill_papers is not set, it defaults to 0 in the audit."""
        from src.services.intelligence.monitoring.models import MonitoringRun

        _seed_subscription(db_path, "sub-bf-zero")
        run = MonitoringRun(subscription_id="sub-bf-zero")
        repo.record_run(run, user_id="alice")
        audit = repo.get_run(run.run_id)
        assert audit is not None
        assert audit.backfill_papers == 0

    def test_list_runs_includes_backfill_papers(
        self, db_path: Path, repo: MonitoringRunRepository
    ) -> None:
        """list_runs reads backfill_papers from each row."""
        from src.services.intelligence.monitoring.models import MonitoringRun

        _seed_subscription(db_path, "sub-bl-001")
        run_a = MonitoringRun(subscription_id="sub-bl-001", backfill_papers=5)
        run_b = MonitoringRun(subscription_id="sub-bl-001", backfill_papers=0)
        repo.record_run(run_a, user_id="alice")
        repo.record_run(run_b, user_id="alice")
        audits = repo.list_runs(subscription_id="sub-bl-001")
        # list_runs orders by started_at DESC; both runs have the same sub_id
        bp_values = {a.run_id: a.backfill_papers for a in audits}
        assert bp_values[run_a.run_id] == 5
        assert bp_values[run_b.run_id] == 0

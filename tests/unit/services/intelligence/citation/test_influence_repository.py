"""Tests for ``CitationInfluenceRepository`` (Issue #134).

Covers:
- Round-trip persistence (record + get).
- TTL semantics on the read path -- stale rows return ``None``.
- ``delete_stale`` row count.
- ``record_metrics`` retry path on lock contention.
- ``record_metrics`` swallows non-contention ``sqlite3.Error``
  (preserves the original ``_write_cache`` don't-fail-the-API-call
  contract).
- ``from_path`` factory initialises migrations.
- All four failure-path log events asserted via
  ``capture_logs()`` with the canonical "rebind logger before
  capture" pattern (CLAUDE.md "Test Authoring Conventions").
"""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest
import structlog
import structlog.testing

from src.services.intelligence.citation import influence_repository as repo_mod
from src.services.intelligence.citation.influence_repository import (
    DEFAULT_MAX_AGE_DAYS,
    CitationInfluenceRepository,
)
from src.services.intelligence.citation.influence_scorer import InfluenceMetrics
from src.storage.intelligence_graph import connection as conn_mod

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path() -> Iterator[Path]:
    """Fresh on-disk SQLite path per test (auto-cleaned)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    path.unlink(missing_ok=True)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
def repo(db_path: Path) -> CitationInfluenceRepository:
    return CitationInfluenceRepository.from_path(db_path)


def _metrics(
    paper_id: str = "paper:s2:test001",
    *,
    citation_count: int = 3,
    citation_velocity: float = 1.5,
    pagerank_score: float = 0.25,
    hub_score: float = 0.4,
    authority_score: float = 0.6,
    computed_at: datetime | None = None,
) -> InfluenceMetrics:
    """Convenience constructor with explicit defaults for clarity."""
    return InfluenceMetrics(
        paper_id=paper_id,
        citation_count=citation_count,
        citation_velocity=citation_velocity,
        pagerank_score=pagerank_score,
        hub_score=hub_score,
        authority_score=authority_score,
        computed_at=computed_at or datetime.now(timezone.utc),
    )


def _make_begin_immediate_failure_open(
    error_message: str,
    *,
    sqlite_errorcode: int | None = None,
    max_failures: int | None = None,
):
    """Proxy ``open_connection`` whose ``BEGIN IMMEDIATE`` raises.

    Mirrors the helper in ``tests/unit/services/intelligence/monitoring/
    test_run_repository.py`` so the citation repo's contention
    semantics are exercised the same way.
    """
    real_open = conn_mod.open_connection
    attempts = {"n": 0, "failures": 0}

    class _ConnProxy:
        def __init__(self, real_conn: sqlite3.Connection) -> None:
            self._real = real_conn

        def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
            if sql == "BEGIN IMMEDIATE":
                if max_failures is None or attempts["failures"] < max_failures:
                    attempts["failures"] += 1
                    exc = sqlite3.OperationalError(error_message)
                    if sqlite_errorcode is not None:
                        exc.sqlite_errorcode = sqlite_errorcode
                    raise exc
            return self._real.execute(sql, *args, **kwargs)

        def executemany(self, sql: str, *args: Any, **kwargs: Any) -> Any:
            return self._real.executemany(sql, *args, **kwargs)

        def commit(self) -> None:
            self._real.commit()

        def rollback(self) -> None:
            self._real.rollback()

    @contextmanager
    def fake_open(p: Path) -> Iterator[_ConnProxy]:
        with real_open(p) as conn:
            attempts["n"] += 1
            yield _ConnProxy(conn)

    return fake_open, attempts


# ---------------------------------------------------------------------------
# Initialization / factory
# ---------------------------------------------------------------------------


class TestInitialize:
    def test_from_path_initializes_migrations(self, db_path: Path) -> None:
        """``from_path`` runs the migration manager so the table exists."""
        r = CitationInfluenceRepository.from_path(db_path)
        # If migrations ran, recording a row succeeds (no "no such table").
        r.record_metrics(_metrics())
        assert r.get_metrics(_metrics().paper_id) is not None

    def test_record_metrics_requires_initialize(self, db_path: Path) -> None:
        r = CitationInfluenceRepository(db_path)  # no initialize()
        with pytest.raises(RuntimeError, match="not initialized"):
            r.record_metrics(_metrics())

    def test_get_metrics_requires_initialize(self, db_path: Path) -> None:
        r = CitationInfluenceRepository(db_path)  # no initialize()
        with pytest.raises(RuntimeError, match="not initialized"):
            r.get_metrics("paper:s2:x")

    def test_initialize_is_idempotent(self, db_path: Path) -> None:
        r = CitationInfluenceRepository(db_path)
        r.initialize()
        r.initialize()  # second call does nothing surprising
        # And the repo is still usable.
        r.record_metrics(_metrics())

    def test_initialize_logs_when_migrations_apply(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Rebind logger so capture_logs sees the event under
        # cache_logger_on_first_use=True.
        monkeypatch.setattr(repo_mod, "logger", structlog.get_logger())
        with structlog.testing.capture_logs() as logs:
            CitationInfluenceRepository(db_path).initialize()
        # First-time initialization applies V1..V4 -> exactly one
        # "migrations_applied" event from the repo.
        events = [
            e
            for e in logs
            if e.get("event") == "citation_influence_repository_migrations_applied"
        ]
        assert len(events) == 1
        assert events[0]["count"] >= 1

    def test_initialize_no_log_when_no_migrations_pending(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Run once to apply migrations.
        CitationInfluenceRepository(db_path).initialize()
        # Re-bind logger for the second pass.
        monkeypatch.setattr(repo_mod, "logger", structlog.get_logger())
        with structlog.testing.capture_logs() as logs:
            CitationInfluenceRepository(db_path).initialize()
        events = [
            e
            for e in logs
            if e.get("event") == "citation_influence_repository_migrations_applied"
        ]
        assert events == []  # no migrations ⇒ no event


# ---------------------------------------------------------------------------
# CRUD round-trip
# ---------------------------------------------------------------------------


class TestRecordAndGetMetrics:
    def test_record_metrics_persists_correctly(
        self, repo: CitationInfluenceRepository
    ) -> None:
        m = _metrics(
            "paper:s2:roundtrip",
            citation_count=42,
            citation_velocity=8.4,
            pagerank_score=0.31,
            hub_score=0.51,
            authority_score=0.72,
        )
        repo.record_metrics(m)
        out = repo.get_metrics(m.paper_id)
        assert out is not None
        assert out.paper_id == m.paper_id
        assert out.citation_count == 42
        assert out.citation_velocity == 8.4
        assert out.pagerank_score == 0.31
        assert out.hub_score == 0.51
        assert out.authority_score == 0.72
        # Timestamps round-trip via ISO format -- tolerate microsecond
        # precision.
        assert out.computed_at == m.computed_at

    def test_record_metrics_upserts_on_conflict(
        self, repo: CitationInfluenceRepository
    ) -> None:
        """Second record_metrics for the same paper_id overwrites."""
        first = _metrics("paper:s2:upsert", citation_count=1)
        repo.record_metrics(first)
        second = _metrics(
            "paper:s2:upsert",
            citation_count=99,
            computed_at=first.computed_at + timedelta(hours=1),
        )
        repo.record_metrics(second)
        out = repo.get_metrics("paper:s2:upsert")
        assert out is not None
        assert out.citation_count == 99
        assert out.computed_at == second.computed_at

    def test_get_metrics_returns_none_when_not_found(
        self, repo: CitationInfluenceRepository
    ) -> None:
        assert repo.get_metrics("paper:s2:missing") is None

    def test_get_metrics_returns_none_when_stale(
        self, repo: CitationInfluenceRepository
    ) -> None:
        """Rows older than max_age_days are treated as cache misses."""
        stale = _metrics(
            "paper:s2:stale",
            computed_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        repo.record_metrics(stale)
        # Default max_age_days=7 → the 30-day-old row is stale.
        assert repo.get_metrics("paper:s2:stale") is None

    def test_get_metrics_returns_metrics_when_fresh(
        self, repo: CitationInfluenceRepository
    ) -> None:
        fresh = _metrics(
            "paper:s2:fresh",
            computed_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        repo.record_metrics(fresh)
        out = repo.get_metrics("paper:s2:fresh")
        assert out is not None
        assert out.paper_id == "paper:s2:fresh"

    def test_get_metrics_with_custom_max_age_days(
        self, repo: CitationInfluenceRepository
    ) -> None:
        """Larger max_age_days widens the freshness window."""
        old = _metrics(
            "paper:s2:custom",
            computed_at=datetime.now(timezone.utc) - timedelta(days=20),
        )
        repo.record_metrics(old)
        # Default 7 days → stale.
        assert repo.get_metrics("paper:s2:custom") is None
        # 30 days → fresh.
        assert repo.get_metrics("paper:s2:custom", max_age_days=30) is not None

    def test_get_metrics_rejects_non_positive_max_age_days(
        self, repo: CitationInfluenceRepository
    ) -> None:
        with pytest.raises(ValueError, match="max_age_days must be positive"):
            repo.get_metrics("paper:s2:x", max_age_days=0)
        with pytest.raises(ValueError, match="max_age_days must be positive"):
            repo.get_metrics("paper:s2:x", max_age_days=-1)

    def test_default_max_age_days_constant(self) -> None:
        """Pin the public default so callers can reason about it."""
        assert DEFAULT_MAX_AGE_DAYS == 7


# ---------------------------------------------------------------------------
# delete_stale
# ---------------------------------------------------------------------------


class TestDeleteStale:
    def test_delete_stale_returns_affected_row_count(
        self, repo: CitationInfluenceRepository
    ) -> None:
        """The returned count must equal the number of rows actually
        removed -- ops dashboards rely on this for backlog tracking.
        """
        now = datetime.now(timezone.utc)
        for i in range(3):
            repo.record_metrics(
                _metrics(f"paper:s2:old{i}", computed_at=now - timedelta(days=30))
            )
        # cutoff = 7 days ago → all three are older
        cutoff = now - timedelta(days=7)
        assert repo.delete_stale(cutoff) == 3
        for i in range(3):
            # All three should be gone.
            assert repo.get_metrics(f"paper:s2:old{i}", max_age_days=365) is None

    def test_delete_stale_does_not_delete_fresh_rows(
        self, repo: CitationInfluenceRepository
    ) -> None:
        now = datetime.now(timezone.utc)
        repo.record_metrics(_metrics("paper:s2:fresh", computed_at=now))
        repo.record_metrics(
            _metrics("paper:s2:stale", computed_at=now - timedelta(days=30))
        )
        cutoff = now - timedelta(days=7)
        assert repo.delete_stale(cutoff) == 1
        # Fresh row survives.
        assert repo.get_metrics("paper:s2:fresh") is not None
        # Stale row is gone.
        assert repo.get_metrics("paper:s2:stale", max_age_days=365) is None

    def test_delete_stale_returns_zero_when_no_rows_match(
        self, repo: CitationInfluenceRepository
    ) -> None:
        now = datetime.now(timezone.utc)
        repo.record_metrics(_metrics("paper:s2:keep", computed_at=now))
        # Cutoff predates the row → nothing to delete.
        assert repo.delete_stale(now - timedelta(days=365)) == 0

    def test_delete_stale_rolls_back_on_failure(
        self, repo: CitationInfluenceRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the DELETE itself raises (e.g. disk corruption), the
        transaction must roll back AND the exception must propagate
        so callers see the failure -- ``delete_stale`` is invoked
        from a Phase 10 cleanup hook that wants to know if it failed.
        """
        now = datetime.now(timezone.utc)
        repo.record_metrics(_metrics("paper:s2:rb", computed_at=now))
        rollback_calls: list[int] = []
        real_open = conn_mod.open_connection

        @contextmanager
        def fake_open(p: Path):  # type: ignore[no-untyped-def]
            with real_open(p) as conn:

                class _Proxy:
                    def __init__(self, c: sqlite3.Connection) -> None:
                        self._c = c

                    def execute(self, sql: str, *args: Any, **kw: Any) -> Any:
                        if sql.lstrip().startswith("DELETE"):
                            raise sqlite3.OperationalError("disk corruption")
                        return self._c.execute(sql, *args, **kw)

                    def commit(self) -> None:
                        self._c.commit()

                    def rollback(self) -> None:
                        rollback_calls.append(1)
                        self._c.rollback()

                yield _Proxy(conn)

        monkeypatch.setattr(repo_mod, "open_connection", fake_open)
        with pytest.raises(sqlite3.OperationalError, match="disk corruption"):
            repo.delete_stale(now)
        assert rollback_calls == [1]


# ---------------------------------------------------------------------------
# Retry / failure semantics
# ---------------------------------------------------------------------------


class TestRetryOnLockContention:
    def test_record_metrics_uses_retry_helper(
        self, repo: CitationInfluenceRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``record_metrics`` must route through ``retry_on_lock_contention``
        with the canonical operation_name + paper_id extra log field so
        a single audit query can see contention events from this site.
        """
        captured: dict[str, object] = {}

        def _spy(operation, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return operation()

        monkeypatch.setattr(repo_mod, "retry_on_lock_contention", _spy)
        m = _metrics("paper:s2:spy")
        repo.record_metrics(m)
        assert captured.get("operation_name") == "influence_record_metrics"
        assert captured.get("paper_id") == "paper:s2:spy"

    def test_record_metrics_succeeds_after_retry_on_lock_contention(
        self, repo: CitationInfluenceRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Transient SQLITE_BUSY is retried; the row is eventually
        persisted. Mirrors the canonical
        ``MonitoringRunRepository`` test of the same name.
        """
        max_failures = 1  # one BUSY then succeed
        fake_open, attempts = _make_begin_immediate_failure_open(
            error_message="database is busy",
            sqlite_errorcode=conn_mod._SQLITE_BUSY,
            max_failures=max_failures,
        )
        monkeypatch.setattr(repo_mod, "open_connection", fake_open)
        # Skip real backoff sleep -- helper sleeps in connection module.
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )

        m = _metrics("paper:s2:retry")
        repo.record_metrics(m)
        # The retry actually fired before success.
        assert attempts["failures"] == max_failures
        # And the row was actually persisted.
        assert repo.get_metrics("paper:s2:retry") is not None

    def test_record_metrics_retries_on_locked_error_code(
        self, repo: CitationInfluenceRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SQLITE_LOCKED (errorcode 6) -- same retry contract as BUSY."""
        fake_open, attempts = _make_begin_immediate_failure_open(
            error_message="some locked-table message",
            sqlite_errorcode=conn_mod._SQLITE_LOCKED,
            max_failures=1,
        )
        monkeypatch.setattr(repo_mod, "open_connection", fake_open)
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )

        m = _metrics("paper:s2:locked")
        repo.record_metrics(m)
        assert attempts["failures"] == 1
        assert repo.get_metrics("paper:s2:locked") is not None

    def test_record_metrics_propagates_non_lock_sqlite_error(
        self, repo: CitationInfluenceRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``IntegrityError`` (a sqlite3.Error subclass) must NOT be
        retried, must NOT crash the caller, and MUST be logged via
        ``citation_influence_repo_write_failed``.

        The retry helper only catches contention; everything else
        propagates out of the helper, lands in the outer ``try``, and
        is logged + swallowed -- preserves the original
        ``_write_cache`` contract.
        """
        # Rebind logger so capture_logs sees the event.
        monkeypatch.setattr(repo_mod, "logger", structlog.get_logger())

        real_open = conn_mod.open_connection

        @contextmanager
        def fake_open(p: Path):  # type: ignore[no-untyped-def]
            with real_open(p) as conn:
                # Wrap conn so executemany / execute on the upsert
                # raises IntegrityError. We just patch executemany on
                # the proxy.
                class _Proxy:
                    def __init__(self, c: sqlite3.Connection) -> None:
                        self._c = c

                    def execute(self, sql: str, *args: Any, **kw: Any) -> Any:
                        if sql.lstrip().startswith("INSERT"):
                            raise sqlite3.IntegrityError("constraint violation")
                        return self._c.execute(sql, *args, **kw)

                    def executemany(self, sql: str, *args: Any, **kw: Any) -> Any:
                        return self._c.executemany(sql, *args, **kw)

                    def commit(self) -> None:
                        self._c.commit()

                    def rollback(self) -> None:
                        self._c.rollback()

                yield _Proxy(conn)

        monkeypatch.setattr(repo_mod, "open_connection", fake_open)

        with structlog.testing.capture_logs() as logs:
            # Must not raise -- the don't-fail-the-API-call contract.
            repo.record_metrics(_metrics("paper:s2:integ"))

        events = [
            e for e in logs if e.get("event") == "citation_influence_repo_write_failed"
        ]
        assert len(events) == 1
        assert events[0].get("paper_id") == "paper:s2:integ"
        assert "constraint violation" in events[0].get("error", "")

    def test_record_metrics_gives_up_after_max_attempts(
        self, repo: CitationInfluenceRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Persistent contention exhausts the retry budget; the
        ``OperationalError`` propagates *out of the retry helper*, then
        lands in the outer try and is logged -- the caller does NOT
        see an exception.
        """
        # Re-bind the connection-module logger because capture_logs
        # needs the processor swap to be visible (CLAUDE.md
        # "Test Authoring Conventions").
        monkeypatch.setattr(conn_mod, "logger", structlog.get_logger())
        monkeypatch.setattr(repo_mod, "logger", structlog.get_logger())

        fake_open, attempts = _make_begin_immediate_failure_open(
            error_message="database is locked",
        )
        monkeypatch.setattr(repo_mod, "open_connection", fake_open)
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )

        with structlog.testing.capture_logs() as logs:
            # Must not raise -- contention is logged as a write failure.
            repo.record_metrics(_metrics("paper:s2:exhaust"))

        assert attempts["n"] == conn_mod.DEFAULT_MAX_ATTEMPTS
        # The retry helper emits its own exhaustion event AND the
        # outer try logs the wrapped repo failure event. Both must
        # fire so ops have an audit trail at both layers.
        exhausted = [
            e for e in logs if e.get("event") == "sqlite_lock_contention_exhausted"
        ]
        assert len(exhausted) == 1
        assert exhausted[0]["operation_name"] == "influence_record_metrics"
        repo_failures = [
            e for e in logs if e.get("event") == "citation_influence_repo_write_failed"
        ]
        assert len(repo_failures) == 1
        assert repo_failures[0]["paper_id"] == "paper:s2:exhaust"


# ---------------------------------------------------------------------------
# get_metrics retry / contention
# ---------------------------------------------------------------------------


class TestGetMetricsRetry:
    def test_get_metrics_uses_retry_helper(
        self, repo: CitationInfluenceRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``get_metrics`` must route through ``retry_on_lock_contention``
        with the canonical operation_name + paper_id extra log field.
        """
        captured: dict[str, object] = {}

        def _spy(operation, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return operation()

        monkeypatch.setattr(repo_mod, "retry_on_lock_contention", _spy)
        repo.get_metrics("paper:s2:spy-read")
        assert captured.get("operation_name") == "influence_get_metrics"
        assert captured.get("paper_id") == "paper:s2:spy-read"

    def test_get_metrics_succeeds_after_retry_on_lock_contention(
        self, repo: CitationInfluenceRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Transient SQLITE_BUSY on the read path is retried; the row is
        returned on the second attempt. Mirrors
        ``test_record_metrics_succeeds_after_retry_on_lock_contention``.

        ``get_metrics`` issues a SELECT (not BEGIN IMMEDIATE), so we
        inject contention by raising an OperationalError with
        SQLITE_BUSY errorcode on the first SELECT attempt.
        """
        # Pre-populate a row so there is something to read back.
        m = _metrics("paper:s2:read-retry")
        repo.record_metrics(m)

        real_open = conn_mod.open_connection
        select_attempts: dict[str, int] = {"n": 0, "failures": 0}
        max_select_failures = 1

        class _SelectFailProxy:
            def __init__(self, real_conn: sqlite3.Connection) -> None:
                self._real = real_conn

            def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
                if (
                    "citation_influence_metrics" in sql
                    and select_attempts["failures"] < max_select_failures
                ):
                    select_attempts["failures"] += 1
                    exc = sqlite3.OperationalError("database is busy")
                    exc.sqlite_errorcode = (  # type: ignore[attr-defined]
                        conn_mod._SQLITE_BUSY
                    )
                    raise exc
                return self._real.execute(sql, *args, **kwargs)

            def executemany(self, sql: str, *args: Any, **kwargs: Any) -> Any:
                return self._real.executemany(sql, *args, **kwargs)

            def commit(self) -> None:
                self._real.commit()

            def rollback(self) -> None:
                self._real.rollback()

        @contextmanager
        def fake_open(p: Path) -> Iterator[_SelectFailProxy]:
            with real_open(p) as conn:
                select_attempts["n"] += 1
                yield _SelectFailProxy(conn)

        monkeypatch.setattr(repo_mod, "open_connection", fake_open)
        monkeypatch.setattr(
            "src.storage.intelligence_graph.connection.time.sleep",
            lambda _s: None,
        )

        result = repo.get_metrics("paper:s2:read-retry")
        # Retry fired before success.
        assert select_attempts["failures"] == max_select_failures
        # The row was returned despite the initial contention.
        assert result is not None
        assert result.paper_id == "paper:s2:read-retry"


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    def test_constructor_rejects_unsanitized_path(self) -> None:
        """Paths outside approved bases raise ``SecurityError``."""
        from src.utils.security import SecurityError

        with pytest.raises(SecurityError, match="outside approved storage roots"):
            CitationInfluenceRepository("/etc/passwd")

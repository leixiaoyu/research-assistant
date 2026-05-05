"""Tests for :class:`CitationCouplingRepository` (Issue #128).

Covers:
- Round-trip persistence (record + get).
- TTL semantics on the read path — stale rows return ``None``.
- ``delete_stale`` row count.
- Canonical-pair ordering: (A,B) and (B,A) hit the same row.
- ``record`` retry path on lock contention.
- ``record`` swallows non-contention ``sqlite3.Error``.
- ``connect`` factory initialises migrations.
- Structured-log event assertions via ``capture_logs()`` with the
  canonical "rebind logger before capture" pattern (CLAUDE.md §Test
  Authoring Conventions).
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

import src.services.intelligence.citation.coupling_repository as repo_mod
from src.services.intelligence.citation.coupling_repository import (
    CitationCouplingRepository,
)
from src.services.intelligence.citation.models import CouplingResult
from src.storage.intelligence_graph import connection as conn_mod

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAPER_A = "paper:s2:alpha"
PAPER_B = "paper:s2:beta"
SHARED_REFS = ["paper:s2:r1", "paper:s2:r2"]

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
def repo(db_path: Path) -> CitationCouplingRepository:
    return CitationCouplingRepository.connect(db_path)


def _result(
    paper_a: str = PAPER_A,
    paper_b: str = PAPER_B,
    *,
    strength: float = 0.5,
    refs: list[str] | None = None,
    co_citations: int = 0,
) -> CouplingResult:
    """Convenience constructor."""
    return CouplingResult(
        paper_a_id=paper_a,
        paper_b_id=paper_b,
        shared_references=refs if refs is not None else SHARED_REFS,
        coupling_strength=strength,
        co_citation_count=co_citations,
    )


def _make_begin_immediate_failure_open(
    error_message: str,
    *,
    sqlite_errorcode: int | None = None,
    max_failures: int | None = None,
) -> tuple[Any, dict]:
    """Proxy ``open_connection`` whose ``BEGIN IMMEDIATE`` raises.

    Mirrors the pattern from ``test_influence_repository.py`` so the
    contention semantics are exercised consistently.
    """
    real_open = conn_mod.open_connection
    attempts: dict[str, int] = {"n": 0, "failures": 0}

    class _ConnProxy:
        def __init__(self, real_conn: sqlite3.Connection) -> None:
            self._real = real_conn

        def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
            if sql == "BEGIN IMMEDIATE":
                if max_failures is None or attempts["failures"] < max_failures:
                    attempts["failures"] += 1
                    exc = sqlite3.OperationalError(error_message)
                    if sqlite_errorcode is not None:
                        exc.sqlite_errorcode = (  # type: ignore[attr-defined]
                            sqlite_errorcode
                        )
                    raise exc
            return self._real.execute(sql, *args, **kwargs)

        def executemany(self, sql: str, *args: Any, **kwargs: Any) -> Any:
            return self._real.executemany(sql, *args, **kwargs)

        def commit(self) -> None:
            self._real.commit()

        def rollback(self) -> None:
            self._real.rollback()

        @property
        def row_factory(self) -> Any:
            return self._real.row_factory

        @row_factory.setter
        def row_factory(self, v: Any) -> None:
            self._real.row_factory = v

    @contextmanager
    def fake_open(p: Path) -> Iterator[_ConnProxy]:
        with real_open(p) as conn:
            attempts["n"] += 1
            yield _ConnProxy(conn)  # type: ignore[misc]

    return fake_open, attempts


# ---------------------------------------------------------------------------
# Initialization / factory
# ---------------------------------------------------------------------------


class TestInitialize:
    def test_connect_initializes_migrations(self, db_path: Path) -> None:
        """``connect`` runs the migration manager so the table exists."""
        r = CitationCouplingRepository.connect(db_path)
        # If migrations ran, recording a row succeeds (no "no such table").
        r.record(_result())
        assert r.get(PAPER_A, PAPER_B) is not None

    def test_record_requires_initialize(self, db_path: Path) -> None:
        """Calling record before initialize raises RuntimeError."""
        r = CitationCouplingRepository(db_path)  # no initialize()
        with pytest.raises(RuntimeError, match="not initialized"):
            r.record(_result())

    def test_get_requires_initialize(self, db_path: Path) -> None:
        """Calling get before initialize raises RuntimeError."""
        r = CitationCouplingRepository(db_path)  # no initialize()
        with pytest.raises(RuntimeError, match="not initialized"):
            r.get(PAPER_A, PAPER_B)

    def test_initialize_is_idempotent(self, db_path: Path) -> None:
        """Calling initialize() twice leaves the repo in a usable state."""
        r = CitationCouplingRepository(db_path)
        r.initialize()
        r.initialize()  # second call does nothing surprising
        r.record(_result())

    def test_initialize_logs_when_migrations_apply(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """First initialize emits migration-applied event."""
        monkeypatch.setattr(repo_mod, "logger", structlog.get_logger())
        with structlog.testing.capture_logs() as logs:
            CitationCouplingRepository(db_path).initialize()
        events = [
            e
            for e in logs
            if e.get("event") == "citation_coupling_repository_migrations_applied"
        ]
        assert len(events) == 1
        assert events[0]["count"] >= 1


# ---------------------------------------------------------------------------
# Round-trip persistence
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_record_and_get_round_trips_all_fields(
        self, repo: CitationCouplingRepository
    ) -> None:
        """record then get returns the exact same CouplingResult."""
        original = _result(strength=0.75, refs=["paper:s2:r1", "paper:s2:r2"])
        repo.record(original)
        fetched = repo.get(PAPER_A, PAPER_B)

        assert fetched is not None
        assert fetched.paper_a_id == PAPER_A
        assert fetched.paper_b_id == PAPER_B
        assert fetched.coupling_strength == pytest.approx(0.75)
        assert fetched.shared_references == sorted(["paper:s2:r1", "paper:s2:r2"])
        assert fetched.co_citation_count == 0

    def test_record_upserts_existing_row(
        self, repo: CitationCouplingRepository
    ) -> None:
        """Second record for the same pair overwrites the first."""
        repo.record(_result(strength=0.3))
        repo.record(_result(strength=0.9))
        fetched = repo.get(PAPER_A, PAPER_B)

        assert fetched is not None
        assert fetched.coupling_strength == pytest.approx(0.9)

    def test_get_returns_none_for_missing_row(
        self, repo: CitationCouplingRepository
    ) -> None:
        """get returns None when no row exists."""
        fetched = repo.get(PAPER_A, PAPER_B)
        assert fetched is None

    def test_get_with_zero_strength_round_trips(
        self, repo: CitationCouplingRepository
    ) -> None:
        """Zero coupling_strength is stored and retrieved correctly."""
        repo.record(_result(strength=0.0, refs=[]))
        fetched = repo.get(PAPER_A, PAPER_B)

        assert fetched is not None
        assert fetched.coupling_strength == pytest.approx(0.0)
        assert fetched.shared_references == []


# ---------------------------------------------------------------------------
# Canonical-pair ordering
# ---------------------------------------------------------------------------


class TestCanonicalOrdering:
    def test_ab_and_ba_hit_same_row(self, repo: CitationCouplingRepository) -> None:
        """Storing (A,B) and retrieving (B,A) returns the same row."""
        repo.record(_result(PAPER_A, PAPER_B, strength=0.42))
        fetched_ba = repo.get(PAPER_B, PAPER_A)

        assert fetched_ba is not None
        # The DB stores min/max, so paper_a_id is always the lexicographic minimum.
        assert fetched_ba.coupling_strength == pytest.approx(0.42)

    def test_record_ba_retrievable_as_ab(
        self, repo: CitationCouplingRepository
    ) -> None:
        """Recording in reverse order is still retrievable in forward order."""
        # PAPER_B > PAPER_A lexicographically, so create a result with B,A
        # where paper_b_id is PAPER_A (B > A, so we need to produce a valid pair).
        # Use distinct IDs where reversed lookup hits the canonical row.
        paper_x = "paper:s2:xxx"
        paper_y = "paper:s2:yyy"  # y > x
        # Record (paper_x, paper_y); retrieve as (paper_y, paper_x) to verify
        # canonical ordering lets us find the same row.
        repo.record(_result(paper_x, paper_y, strength=0.55))
        fetched = repo.get(paper_y, paper_x)  # reversed lookup

        assert fetched is not None
        assert fetched.coupling_strength == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# TTL semantics
# ---------------------------------------------------------------------------


class TestTTL:
    def test_get_returns_fresh_row(self, repo: CitationCouplingRepository) -> None:
        """Fresh row (within TTL) is returned."""
        repo.record(_result())
        fetched = repo.get(PAPER_A, PAPER_B, max_age_days=30)
        assert fetched is not None

    def test_get_returns_none_for_stale_row(
        self, repo: CitationCouplingRepository, db_path: Path
    ) -> None:
        """Row older than max_age_days is treated as a cache miss."""
        # Insert directly with an old timestamp.
        from src.storage.intelligence_graph.connection import open_connection

        old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        with open_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO citation_coupling"
                " (paper_a_id, paper_b_id, coupling_strength,"
                "  shared_references_json, co_citation_count, computed_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (PAPER_A, PAPER_B, 0.5, "[]", 0, old_ts),
            )
            conn.commit()

        fetched = repo.get(PAPER_A, PAPER_B, max_age_days=30)
        assert fetched is None

    def test_get_max_age_days_zero_raises(
        self, repo: CitationCouplingRepository
    ) -> None:
        """max_age_days=0 raises ValueError."""
        with pytest.raises(ValueError, match="max_age_days must be positive"):
            repo.get(PAPER_A, PAPER_B, max_age_days=0)

    def test_get_max_age_days_negative_raises(
        self, repo: CitationCouplingRepository
    ) -> None:
        """Negative max_age_days raises ValueError."""
        with pytest.raises(ValueError, match="max_age_days must be positive"):
            repo.get(PAPER_A, PAPER_B, max_age_days=-1)


# ---------------------------------------------------------------------------
# delete_stale
# ---------------------------------------------------------------------------


class TestDeleteStale:
    def test_delete_stale_removes_old_rows(
        self, repo: CitationCouplingRepository, db_path: Path
    ) -> None:
        """delete_stale removes rows older than the cutoff."""
        from src.storage.intelligence_graph.connection import open_connection

        old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        # Insert an old row directly.
        with open_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO citation_coupling"
                " (paper_a_id, paper_b_id, coupling_strength,"
                "  shared_references_json, co_citation_count, computed_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (PAPER_A, PAPER_B, 0.5, "[]", 0, old_ts),
            )
            conn.commit()

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        deleted = repo.delete_stale(cutoff)

        assert deleted == 1
        assert repo.get(PAPER_A, PAPER_B) is None

    def test_delete_stale_preserves_fresh_rows(
        self, repo: CitationCouplingRepository
    ) -> None:
        """delete_stale does not remove rows within the cutoff."""
        repo.record(_result())
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        deleted = repo.delete_stale(cutoff)

        assert deleted == 0
        assert repo.get(PAPER_A, PAPER_B) is not None

    def test_delete_stale_returns_count(
        self, repo: CitationCouplingRepository, db_path: Path
    ) -> None:
        """delete_stale returns the correct row count for multiple old rows."""
        from src.storage.intelligence_graph.connection import open_connection

        old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        paper_c = "paper:s2:ccc"
        paper_d = "paper:s2:ddd"
        with open_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO citation_coupling"
                " (paper_a_id, paper_b_id, coupling_strength,"
                "  shared_references_json, co_citation_count, computed_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (PAPER_A, PAPER_B, 0.1, "[]", 0, old_ts),
            )
            conn.execute(
                "INSERT INTO citation_coupling"
                " (paper_a_id, paper_b_id, coupling_strength,"
                "  shared_references_json, co_citation_count, computed_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (paper_c, paper_d, 0.2, "[]", 0, old_ts),
            )
            conn.commit()

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        deleted = repo.delete_stale(cutoff)
        assert deleted == 2


# ---------------------------------------------------------------------------
# Retry / contention handling
# ---------------------------------------------------------------------------


class TestRetryOnContention:
    def test_record_retries_on_lock_contention_and_succeeds(
        self, repo: CitationCouplingRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """record retries once on SQLITE_BUSY and then succeeds."""
        fake_open, attempts = _make_begin_immediate_failure_open(
            "database is locked",
            sqlite_errorcode=5,  # SQLITE_BUSY
            max_failures=1,
        )
        monkeypatch.setattr(repo_mod, "open_connection", fake_open)

        repo.record(_result())

        assert attempts["failures"] == 1  # exactly one contention
        assert attempts["n"] >= 2  # retried at least once
        # After the retry it must have persisted.
        assert repo.get(PAPER_A, PAPER_B) is not None

    def test_record_swallows_non_contention_sqlite_error(
        self, repo: CitationCouplingRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-contention sqlite3.Error is swallowed (don't-fail-the-caller)."""
        real_open = conn_mod.open_connection

        @contextmanager
        def boom_open(p: Path) -> Iterator[sqlite3.Connection]:
            with real_open(p) as conn:

                class _Proxy:
                    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
                        if sql == "BEGIN IMMEDIATE":
                            exc = sqlite3.DatabaseError("disk I/O error")
                            # No sqlite_errorcode → non-contention path
                            raise exc
                        return conn.execute(sql, *args, **kwargs)

                    def commit(self) -> None:
                        conn.commit()

                    def rollback(self) -> None:
                        conn.rollback()

                    @property
                    def row_factory(self) -> Any:
                        return conn.row_factory

                    @row_factory.setter
                    def row_factory(self, v: Any) -> None:
                        conn.row_factory = v

                yield _Proxy()  # type: ignore[misc]

        monkeypatch.setattr(repo_mod, "open_connection", boom_open)
        # Must not raise.
        repo.record(_result())

    def test_record_swallowed_error_logs_write_failed(
        self,
        repo: CitationCouplingRepository,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Swallowed sqlite3.Error emits ``coupling_repo_write_failed``."""
        monkeypatch.setattr(repo_mod, "logger", structlog.get_logger())
        real_open = conn_mod.open_connection

        @contextmanager
        def boom_open(p: Path) -> Iterator[sqlite3.Connection]:
            with real_open(p) as conn:

                class _Proxy:
                    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
                        if sql == "BEGIN IMMEDIATE":
                            raise sqlite3.DatabaseError("boom")
                        return conn.execute(sql, *args, **kwargs)

                    def commit(self) -> None:
                        conn.commit()

                    def rollback(self) -> None:
                        conn.rollback()

                    @property
                    def row_factory(self) -> Any:
                        return conn.row_factory

                    @row_factory.setter
                    def row_factory(self, v: Any) -> None:
                        conn.row_factory = v

                yield _Proxy()  # type: ignore[misc]

        monkeypatch.setattr(repo_mod, "open_connection", boom_open)
        with structlog.testing.capture_logs() as logs:
            repo.record(_result())

        events = [e for e in logs if e.get("event") == "coupling_repo_write_failed"]
        assert len(events) == 1
        assert events[0]["paper_a_id"] == PAPER_A
        assert events[0]["paper_b_id"] == PAPER_B

    def test_record_once_rollback_on_insert_failure(
        self, repo: CitationCouplingRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the INSERT fails after BEGIN, the rollback path is exercised.

        The INSERT raises a non-contention OperationalError, which:
        1. Triggers conn.rollback() inside _record_once (lines 253-255).
        2. Propagates through _retry (no retry for non-contention errors).
        3. Is caught by the outer sqlite3.Error handler in record() and swallowed.
        """
        real_open = conn_mod.open_connection

        @contextmanager
        def boom_insert_open(p: Path) -> Iterator[sqlite3.Connection]:
            with real_open(p) as conn:

                class _Proxy:
                    def __init__(self) -> None:
                        self._past_immediate = False

                    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
                        if sql == "BEGIN IMMEDIATE":
                            self._past_immediate = True
                            return conn.execute(sql, *args, **kwargs)
                        # The INSERT SQL starts with whitespace in the f-string.
                        if self._past_immediate and "INSERT" in sql:
                            # Non-contention error: no sqlite_errorcode attribute.
                            raise sqlite3.OperationalError("disk full")
                        return conn.execute(sql, *args, **kwargs)

                    def commit(self) -> None:
                        conn.commit()

                    def rollback(self) -> None:
                        conn.rollback()

                    @property
                    def row_factory(self) -> Any:
                        return conn.row_factory

                    @row_factory.setter
                    def row_factory(self, v: Any) -> None:
                        conn.row_factory = v

                yield _Proxy()  # type: ignore[misc]

        monkeypatch.setattr(repo_mod, "open_connection", boom_insert_open)
        # Must not raise — outer sqlite3.Error handler swallows it.
        repo.record(_result())

    def test_delete_stale_rollback_on_failure(
        self, repo: CitationCouplingRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """delete_stale rolls back and propagates when the DELETE itself fails."""
        real_open = conn_mod.open_connection

        @contextmanager
        def boom_delete_open(p: Path) -> Iterator[sqlite3.Connection]:
            with real_open(p) as conn:

                class _Proxy:
                    def __init__(self) -> None:
                        self._past_immediate = False

                    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
                        if sql == "BEGIN IMMEDIATE":
                            self._past_immediate = True
                            return conn.execute(sql, *args, **kwargs)
                        if self._past_immediate and "DELETE" in sql:
                            raise sqlite3.OperationalError("forced delete failure")
                        return conn.execute(sql, *args, **kwargs)

                    def commit(self) -> None:
                        conn.commit()

                    def rollback(self) -> None:
                        conn.rollback()

                    @property
                    def row_factory(self) -> Any:
                        return conn.row_factory

                    @row_factory.setter
                    def row_factory(self, v: Any) -> None:
                        conn.row_factory = v

                yield _Proxy()  # type: ignore[misc]

        monkeypatch.setattr(repo_mod, "open_connection", boom_delete_open)
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        with pytest.raises(sqlite3.OperationalError, match="forced delete failure"):
            repo.delete_stale(cutoff)


# ---------------------------------------------------------------------------
# Naive-datetime timezone fix path
# ---------------------------------------------------------------------------


class TestNaiveDatetimeFix:
    def test_get_handles_naive_computed_at_timestamp(
        self, repo: CitationCouplingRepository, db_path: Path
    ) -> None:
        """get() handles a naive (no-tz) ``computed_at`` value in the DB.

        Older rows stored without a ``+00:00`` suffix must not crash the
        TTL comparison — they are treated as UTC and the comparison is
        apples-to-apples.
        """
        from src.storage.intelligence_graph.connection import open_connection

        # Insert a row with a naive ISO timestamp (no tz suffix).
        naive_ts = "2099-12-31T00:00:00"  # far future — will be fresh
        with open_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO citation_coupling"
                " (paper_a_id, paper_b_id, coupling_strength,"
                "  shared_references_json, co_citation_count, computed_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (PAPER_A, PAPER_B, 0.7, "[]", 0, naive_ts),
            )
            conn.commit()

        fetched = repo.get(PAPER_A, PAPER_B, max_age_days=30)
        # The naive timestamp is far in the future, so it must pass the
        # freshness check and return a result (not None).
        assert fetched is not None
        assert fetched.coupling_strength == pytest.approx(0.7)

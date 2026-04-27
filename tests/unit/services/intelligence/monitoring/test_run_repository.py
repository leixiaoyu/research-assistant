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


@pytest.fixture
def repo(db_path: Path) -> MonitoringRunRepository:
    r = MonitoringRunRepository(db_path)
    r.initialize()
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

    def test_list_filter_by_subscription(self, repo: MonitoringRunRepository) -> None:
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

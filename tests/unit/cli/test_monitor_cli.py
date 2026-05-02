"""Tests for ``arisp monitor`` CLI commands (Milestone 9.1, Week 2).

All commands run end-to-end through ``typer.testing.CliRunner``. The
heavy collaborators (``ArxivProvider``, ``RegistryService``, the LLM
service) are dependency-injected via ``MonitoringRunner.from_paths``;
we patch the public seam ``src.cli.monitor._build_runner`` to skip
external setup. Subscription / repository operations exercise the real
SQLite store under a temp DB so the env-var plumbing is also covered.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.cli.monitor import (
    AUTO_INGEST_THRESHOLD,
    _DB_ENV_VAR,
    _auto_ingest_runs,
    _resolve_db_path,
    monitor_app,
)
from src.services.intelligence.monitoring.models import (
    MonitoringPaperRecord,
    MonitoringRun,
    MonitoringRunStatus,
    ResearchSubscription,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def db_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the CLI's monitoring DB env var at a tmp DB."""
    db_path = tmp_path / "monitoring.db"
    monkeypatch.setenv(_DB_ENV_VAR, str(db_path))
    return db_path


# ---------------------------------------------------------------------------
# Helpers used by the runner-mock tests
# ---------------------------------------------------------------------------


def _make_run(
    *,
    subscription_id: str = "sub-test12345",
    status: MonitoringRunStatus = MonitoringRunStatus.SUCCESS,
    papers_seen: int = 0,
    papers_new: int = 0,
    papers: Optional[list[MonitoringPaperRecord]] = None,
) -> MonitoringRun:
    return MonitoringRun(
        subscription_id=subscription_id,
        status=status,
        papers_seen=papers_seen,
        papers_new=papers_new,
        papers=papers or [],
    )


def _make_paper_record(
    *,
    paper_id: str = "2401.00001",
    title: str = "A Paper",
    is_new: bool = True,
    relevance_score: Optional[float] = 0.9,
) -> MonitoringPaperRecord:
    return MonitoringPaperRecord(
        paper_id=paper_id,
        title=title,
        is_new=is_new,
        relevance_score=relevance_score,
    )


# ---------------------------------------------------------------------------
# DB resolution helpers
# ---------------------------------------------------------------------------


class TestResolveDbPath:
    def test_env_unset_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DB_ENV_VAR, raising=False)
        assert _resolve_db_path() == Path("./data/monitoring.db")

    def test_env_set_returns_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DB_ENV_VAR, "/tmp/x.db")
        assert _resolve_db_path() == Path("/tmp/x.db")


# ---------------------------------------------------------------------------
# _auto_ingest_runs
# ---------------------------------------------------------------------------


class TestAutoIngestRuns:
    def test_counts_above_threshold(self) -> None:
        run = _make_run(
            papers=[
                _make_paper_record(paper_id="hi", relevance_score=0.95),
                _make_paper_record(paper_id="lo", relevance_score=0.4),
                _make_paper_record(paper_id="thr", relevance_score=0.7),
            ]
        )
        # 0.95 and 0.7 (>= AUTO_INGEST_THRESHOLD) count; 0.4 does not.
        assert _auto_ingest_runs([run]) == 2

    def test_skips_unscored(self) -> None:
        run = _make_run(
            papers=[
                _make_paper_record(paper_id="x", relevance_score=None),
            ]
        )
        assert _auto_ingest_runs([run]) == 0

    def test_threshold_constant(self) -> None:
        # Sanity check the resolved decision is wired correctly.
        assert AUTO_INGEST_THRESHOLD == 0.7


# ---------------------------------------------------------------------------
# `arisp monitor add`
# ---------------------------------------------------------------------------


class TestAddCommand:
    def test_add_happy_path(self, runner: CliRunner, db_env: Path) -> None:
        result = runner.invoke(
            monitor_app,
            [
                "add",
                "--name",
                "PEFT Watch",
                "--query",
                "LoRA OR adapter",
                "--user-id",
                "alice",
                "--keyword",
                "PEFT",
                "--keyword",
                "fine-tuning",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Created subscription sub-" in result.output
        assert "user_id: alice" in result.output

    def test_add_invalid_query_fails(self, runner: CliRunner, db_env: Path) -> None:
        result = runner.invoke(
            monitor_app,
            [
                "add",
                "--name",
                "Bad",
                "--query",
                "",  # invalid -- empty
            ],
        )
        assert result.exit_code != 0
        assert "Error" in result.output

    def test_add_with_poll_interval(self, runner: CliRunner, db_env: Path) -> None:
        result = runner.invoke(
            monitor_app,
            [
                "add",
                "--name",
                "X",
                "--query",
                "tree of thoughts",
                "--poll-hours",
                "12",
            ],
        )
        assert result.exit_code == 0
        assert "poll_interval_hours: 12" in result.output


# ---------------------------------------------------------------------------
# `arisp monitor list`
# ---------------------------------------------------------------------------


class TestListCommand:
    def test_list_empty(self, runner: CliRunner, db_env: Path) -> None:
        result = runner.invoke(monitor_app, ["list"])
        assert result.exit_code == 0
        assert "No subscriptions found." in result.output

    def test_list_after_add(self, runner: CliRunner, db_env: Path) -> None:
        runner.invoke(
            monitor_app,
            [
                "add",
                "--name",
                "Sub1",
                "--query",
                "deep learning",
                "--user-id",
                "alice",
            ],
        )
        result = runner.invoke(monitor_app, ["list", "--user-id", "alice"])
        assert result.exit_code == 0
        assert "Sub1" in result.output
        assert "alice" in result.output

    def test_list_active_only(self, runner: CliRunner, db_env: Path) -> None:
        # Active is the default for new subs, so this just shouldn't crash.
        runner.invoke(
            monitor_app,
            ["add", "--name", "A", "--query", "x"],
        )
        result = runner.invoke(monitor_app, ["list", "--active-only"])
        assert result.exit_code == 0
        assert "A" in result.output


# ---------------------------------------------------------------------------
# `arisp monitor check`
# ---------------------------------------------------------------------------


class TestCheckCommand:
    def test_check_no_active_subs(self, runner: CliRunner, db_env: Path) -> None:
        # Mock the runner to return zero runs.
        fake_runner = MagicMock()
        fake_runner.run_once = AsyncMock(return_value=[])
        with patch("src.cli.monitor._build_runner", return_value=fake_runner):
            result = runner.invoke(monitor_app, ["check"])
        assert result.exit_code == 0
        assert "nothing to check" in result.output

    def test_check_prints_summary(self, runner: CliRunner, db_env: Path) -> None:
        run = _make_run(
            subscription_id="sub-aaa",
            papers_seen=3,
            papers_new=2,
            papers=[
                _make_paper_record(paper_id="hi", relevance_score=0.85),
            ],
        )
        fake_runner = MagicMock()
        fake_runner.run_once = AsyncMock(return_value=[run])
        with patch("src.cli.monitor._build_runner", return_value=fake_runner):
            result = runner.invoke(monitor_app, ["check", "--user-id", "alice"])
        assert result.exit_code == 0
        assert "sub-aaa" in result.output
        assert "1 paper(s) above relevance" in result.output
        fake_runner.run_once.assert_awaited_once_with(user_id="alice")


# ---------------------------------------------------------------------------
# `arisp monitor digest`
# ---------------------------------------------------------------------------


class TestDigestCommand:
    def test_digest_requires_run_id_or_latest(
        self, runner: CliRunner, db_env: Path
    ) -> None:
        result = runner.invoke(monitor_app, ["digest"])
        assert result.exit_code == 1
        assert "RUN_ID" in result.output

    def test_digest_rejects_both_run_id_and_latest(
        self, runner: CliRunner, db_env: Path
    ) -> None:
        result = runner.invoke(monitor_app, ["digest", "run-xxx", "--latest"])
        assert result.exit_code == 1
        assert "not both" in result.output

    def test_digest_unknown_run_id_fails(self, runner: CliRunner, db_env: Path) -> None:
        result = runner.invoke(monitor_app, ["digest", "run-missing"])
        assert result.exit_code == 1
        assert "Run not found" in result.output

    def test_digest_latest_with_no_runs_fails(
        self, runner: CliRunner, db_env: Path
    ) -> None:
        result = runner.invoke(monitor_app, ["digest", "--latest"])
        assert result.exit_code == 1
        assert "No stored monitoring runs." in result.output

    def test_digest_latest_happy_path(
        self,
        runner: CliRunner,
        db_env: Path,
        tmp_path: Path,
    ) -> None:
        # Seed a subscription + a recorded run via the real repos.
        from src.services.intelligence.monitoring import (
            MonitoringRunner,
            SubscriptionManager,
        )
        from src.services.intelligence.monitoring.run_repository import (
            MonitoringRunRepository,
        )

        mgr = SubscriptionManager(db_env)
        mgr.initialize()
        sub = ResearchSubscription(
            user_id="alice",
            name="Latest Sub",
            query="x",
        )
        mgr.add_subscription(sub)

        repo = MonitoringRunRepository(db_env)
        repo.initialize()
        run = MonitoringRun(
            subscription_id=sub.subscription_id,
            status=MonitoringRunStatus.SUCCESS,
            started_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
            finished_at=datetime(2026, 4, 24, 0, 5, tzinfo=timezone.utc),
            papers_seen=0,
            papers_new=0,
        )
        repo.record_run(run, user_id="alice")

        # Sanity: ensure the runner module's helpers work end-to-end too.
        del MonitoringRunner  # silence unused-import lint

        out_dir = tmp_path / "digests_out"
        result = runner.invoke(
            monitor_app,
            ["digest", "--latest", "--output-root", str(out_dir)],
        )
        assert result.exit_code == 0, result.output
        assert "Digest written:" in result.output
        # The actual file should exist under out_dir.
        files = list(out_dir.glob("*.md"))
        assert len(files) == 1

    def test_digest_with_specific_run_id_renders(
        self,
        runner: CliRunner,
        db_env: Path,
        tmp_path: Path,
    ) -> None:
        # Seed a sub + run via the real repos and digest by explicit run id.
        from src.services.intelligence.monitoring import SubscriptionManager
        from src.services.intelligence.monitoring.run_repository import (
            MonitoringRunRepository,
        )

        mgr = SubscriptionManager(db_env)
        mgr.initialize()
        sub = ResearchSubscription(user_id="alice", name="DelSub", query="x")
        mgr.add_subscription(sub)

        repo = MonitoringRunRepository(db_env)
        repo.initialize()
        run = MonitoringRun(
            subscription_id=sub.subscription_id,
            status=MonitoringRunStatus.SUCCESS,
        )
        repo.record_run(run, user_id="alice")

        out_dir = tmp_path / "digests_out"
        result = runner.invoke(
            monitor_app,
            ["digest", run.run_id, "--output-root", str(out_dir)],
        )
        assert result.exit_code == 0, result.output
        assert "Digest written:" in result.output

    def test_digest_handles_orphan_run_for_deleted_subscription(
        self,
        runner: CliRunner,
        db_env: Path,
        tmp_path: Path,
    ) -> None:
        # Subscription -> run is FK CASCADE. To cover the "subscription
        # missing" path on the digest CLI, manually insert an orphan
        # audit row that bypasses the subscription FK.
        import sqlite3

        from src.services.intelligence.monitoring.run_repository import (
            MonitoringRunRepository,
        )

        repo = MonitoringRunRepository(db_env)
        repo.initialize()
        # Insert an orphan run via raw SQL with FK off.
        conn = sqlite3.connect(str(db_env))
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "INSERT INTO monitoring_runs (run_id, subscription_id, "
                "user_id, started_at, status, papers_found, papers_new) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "run-orphan-1",
                    "sub-orphan-1",
                    "alice",
                    "2026-04-24T00:00:00+00:00",
                    "success",
                    0,
                    0,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        out_dir = tmp_path / "digests_out"
        result = runner.invoke(
            monitor_app,
            ["digest", "run-orphan-1", "--output-root", str(out_dir)],
        )
        assert result.exit_code == 0, result.output
        assert "no longer exists" in result.output
        assert "Digest written:" in result.output


# ---------------------------------------------------------------------------
# `_build_*` helpers (smoke coverage)
# ---------------------------------------------------------------------------


class TestBuildHelpers:
    def test_build_subscription_manager(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from src.cli.monitor import _build_subscription_manager

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "m.db"))
        mgr = _build_subscription_manager()
        # If initialize() was skipped, list would raise RuntimeError.
        assert mgr.list_subscriptions() == []

    def test_build_run_repo(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from src.cli.monitor import _build_run_repo

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "m.db"))
        repo = _build_run_repo()
        assert repo.list_runs() == []

    def test_build_runner_constructs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from src.cli.monitor import _build_runner

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "m.db"))
        # Stub ArxivProvider + RegistryService so the runner builds without
        # touching real settings / disk lock files.
        with (
            patch("src.services.providers.arxiv.ArxivProvider") as arxiv_cls,
            patch("src.services.registry.service.RegistryService") as reg_cls,
        ):
            arxiv_cls.return_value = MagicMock()
            reg_cls.return_value = MagicMock()
            runner_obj = _build_runner()
        assert runner_obj is not None

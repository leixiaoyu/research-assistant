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
        sub = ResearchSubscription(
            subscription_id="sub-test12345",
            user_id="alice",
            name="Sub",
            query="tree of thoughts",
            min_relevance_score=0.7,
        )
        run = _make_run(
            subscription_id="sub-test12345",
            papers=[
                _make_paper_record(paper_id="hi", relevance_score=0.95),
                _make_paper_record(paper_id="lo", relevance_score=0.4),
                _make_paper_record(paper_id="thr", relevance_score=0.7),
            ],
        )
        # 0.95 and 0.7 (>= sub.min_relevance_score=0.7) count; 0.4 does not.
        subs_by_id = {sub.subscription_id: sub}
        assert _auto_ingest_runs([run], subscriptions_by_id=subs_by_id) == 2

    def test_skips_unscored(self) -> None:
        run = _make_run(
            papers=[
                _make_paper_record(paper_id="x", relevance_score=None),
            ]
        )
        assert _auto_ingest_runs([run]) == 0

    def test_threshold_uses_subscription_min_relevance(self) -> None:
        """Per-subscription threshold is used instead of global constant (H-A4)."""
        sub = ResearchSubscription(
            subscription_id="sub-test12345",
            user_id="alice",
            name="High Bar",
            query="tree of thoughts",
            min_relevance_score=0.9,
        )
        run = _make_run(
            subscription_id="sub-test12345",
            papers=[
                _make_paper_record(paper_id="just-below", relevance_score=0.85),
                _make_paper_record(paper_id="above", relevance_score=0.95),
            ],
        )
        subs_by_id = {sub.subscription_id: sub}
        # Only 0.95 clears the 0.9 threshold; 0.85 does not.
        assert _auto_ingest_runs([run], subscriptions_by_id=subs_by_id) == 1

    def test_fallback_default_threshold_without_subscription_map(self) -> None:
        """Without subscription map, falls back to default 0.7 threshold."""
        run = _make_run(
            papers=[
                _make_paper_record(paper_id="above", relevance_score=0.8),
                _make_paper_record(paper_id="below", relevance_score=0.5),
            ]
        )
        assert _auto_ingest_runs([run]) == 1


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
        fake_runner.list_subscriptions = MagicMock(return_value=[])
        with patch("src.cli.monitor._build_runner", return_value=fake_runner):
            result = runner.invoke(monitor_app, ["check", "--user-id", "alice"])
        assert result.exit_code == 0
        assert "sub-aaa" in result.output
        assert "paper(s) above" in result.output
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
        from src.services.intelligence.monitoring.runner import MonitoringRunner

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "m.db"))
        # Without LLM keys, the legacy single-arxiv path runs.
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        # Stub ArxivProvider + RegistryService so the runner builds without
        # touching real settings / disk lock files.
        with (
            patch("src.services.providers.arxiv.ArxivProvider") as arxiv_cls,
            patch("src.services.registry.service.RegistryService") as reg_cls,
        ):
            arxiv_cls.return_value = MagicMock()
            reg_cls.return_value = MagicMock()
            runner_obj = _build_runner()
        # H-T4: Assert isinstance and that public delegation method works.
        assert isinstance(runner_obj, MonitoringRunner)
        assert runner_obj.list_subscriptions() == []

    def test_build_runner_with_llm_key_wires_tier1(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Tier 1 (Issue #139): when LLM_API_KEY is in the env,
        ``_build_runner`` constructs the MultiProviderMonitor with
        OpenAlex + HuggingFace (S2 only when its own key is present)
        plus a QueryExpander.
        """
        from src.cli.monitor import _build_runner
        from src.services.intelligence.monitoring.multi_provider_monitor import (
            MultiProviderMonitor,
        )

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "m.db"))
        monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
        monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
        with (
            patch("src.services.providers.arxiv.ArxivProvider"),
            patch("src.services.registry.service.RegistryService"),
        ):
            runner_obj = _build_runner()
        # Tier 1 monitor selected
        assert isinstance(runner_obj._monitor, MultiProviderMonitor)
        # Without S2 key: no S2 in extras
        from src.services.intelligence.monitoring.models import PaperSource

        assert PaperSource.OPENALEX in runner_obj._monitor._providers
        assert PaperSource.HUGGINGFACE in runner_obj._monitor._providers
        assert PaperSource.SEMANTIC_SCHOLAR not in runner_obj._monitor._providers
        # Expander wired
        assert runner_obj._monitor._query_expander is not None

    def test_build_runner_with_llm_and_s2_keys_includes_s2(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Tier 1: SEMANTIC_SCHOLAR_API_KEY enables Semantic Scholar."""
        from src.cli.monitor import _build_runner

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "m.db"))
        monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "test-s2-key")
        with (
            patch("src.services.providers.arxiv.ArxivProvider"),
            patch("src.services.registry.service.RegistryService"),
        ):
            runner_obj = _build_runner()
        from src.services.intelligence.monitoring.models import PaperSource

        assert PaperSource.SEMANTIC_SCHOLAR in runner_obj._monitor._providers

    def test_build_runner_llm_init_failure_falls_back_to_legacy(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Tier 1: LLMService construction failure -> legacy single-arxiv
        wiring (graceful degradation, no crash).
        """
        from src.cli.monitor import _build_runner
        from src.services.intelligence.monitoring.arxiv_monitor import ArxivMonitor

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "m.db"))
        monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
        with (
            patch("src.services.providers.arxiv.ArxivProvider"),
            patch("src.services.registry.service.RegistryService"),
            patch(
                "src.services.llm.service.LLMService",
                side_effect=RuntimeError("bad llm config"),
            ),
        ):
            runner_obj = _build_runner()
        # LLM init failed → no scorer + legacy ArxivMonitor (no tier 1)
        assert isinstance(runner_obj._monitor, ArxivMonitor)
        assert runner_obj._scorer is None

    def test_build_runner_tier1_provider_init_failure_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Tier 1: extra-provider construction failure -> legacy
        ArxivMonitor (LLM scorer still wired).
        """
        from src.cli.monitor import _build_runner
        from src.services.intelligence.monitoring.arxiv_monitor import ArxivMonitor

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "m.db"))
        monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
        monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
        with (
            patch("src.services.providers.arxiv.ArxivProvider"),
            patch("src.services.registry.service.RegistryService"),
            patch(
                "src.services.providers.openalex.OpenAlexProvider",
                side_effect=RuntimeError("openalex init failed"),
            ),
        ):
            runner_obj = _build_runner()
        # Extras init failed → legacy ArxivMonitor (scorer still works)
        assert isinstance(runner_obj._monitor, ArxivMonitor)
        assert runner_obj._scorer is not None

    def test_add_command_db_raises_exits_nonzero(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """H-T3: @handle_errors converts unexpected exceptions to exit code 1.

        Simulates a database error during add_command to verify the decorator
        catches it and exits with a non-zero code and error message.
        """
        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "m.db"))
        with patch(
            "src.cli.monitor._build_subscription_manager",
            side_effect=RuntimeError("database locked"),
        ):
            result = runner.invoke(
                monitor_app,
                ["add", "--name", "X", "--query", "y"],
            )
        assert result.exit_code != 0
        assert "Error" in result.output or "database locked" in result.output


class TestDigestFailedRunGate:
    """C-2: digest_command exits 1 for FAILED runs; --force bypasses gate."""

    def _seed_failed_run(
        self,
        db_env: Path,
        run_id: str = "run-failed-1",
    ) -> str:
        """Insert a FAILED audit row and return its run_id."""
        import sqlite3

        from src.services.intelligence.monitoring.run_repository import (
            MonitoringRunRepository,
        )

        repo = MonitoringRunRepository(db_env)
        repo.initialize()
        conn = sqlite3.connect(str(db_env))
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "INSERT INTO monitoring_runs (run_id, subscription_id, "
                "user_id, started_at, status, papers_found, papers_new) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    "sub-failed",
                    "alice",
                    "2026-04-24T00:00:00+00:00",
                    "failed",
                    0,
                    0,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return run_id

    def test_digest_failed_run_exits_one(
        self, runner: CliRunner, db_env: Path, tmp_path: Path
    ) -> None:
        """C-2: Digesting a FAILED run exits with code 1 and error message."""
        run_id = self._seed_failed_run(db_env)
        out_dir = tmp_path / "digests_out"
        result = runner.invoke(
            monitor_app,
            ["digest", run_id, "--output-root", str(out_dir)],
        )
        assert result.exit_code == 1
        assert "FAILED" in result.output
        assert "digest would be empty" in result.output

    def test_digest_failed_run_force_flag_generates(
        self, runner: CliRunner, db_env: Path, tmp_path: Path
    ) -> None:
        """C-2: --force bypasses the FAILED gate and writes the (empty) digest."""
        # Need to insert a subscription first so the digest can render a header.
        from src.services.intelligence.monitoring.subscription_manager import (
            SubscriptionManager,
        )

        mgr = SubscriptionManager(db_env)
        mgr.initialize()
        sub = ResearchSubscription(
            subscription_id="sub-failed",
            user_id="alice",
            name="Failed Sub",
            query="x",
        )
        mgr.add_subscription(sub)

        run_id = self._seed_failed_run(db_env)
        out_dir = tmp_path / "digests_out"
        result = runner.invoke(
            monitor_app,
            ["digest", run_id, "--output-root", str(out_dir), "--force"],
        )
        assert result.exit_code == 0, result.output
        assert "Digest written" in result.output

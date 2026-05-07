"""Tests for ``arisp citation`` CLI commands (Phase 9.2, REQ-9.2.6).

All commands run end-to-end through ``typer.testing.CliRunner``. Heavy
collaborators (``CitationGraphBuilder``, ``CitationCrawler``, etc.) are
patched at the CLI module boundary via ``monkeypatch.setattr`` on the
``_build_*`` helper functions (PR #143 H-5 lesson: mock at module boundary).

Test naming convention: ``test_<function>_<scenario>``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
import structlog
import structlog.testing
import typer
from typer.testing import CliRunner

from src.cli.citation import (
    _DB_ENV_VAR,
    _build_crawler,
    _build_graph_builder,
    _build_recommender,
    _build_scorer,
    _build_store,
    _resolve_db_path,
    _validate_paper_id,
    citation_app,
)
from src.services.intelligence.citation.models import (
    CrawlDirection,
    Recommendation,
    RecommendationStrategy,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# _resolve_db_path
# ---------------------------------------------------------------------------


class TestResolveDbPath:
    def test_env_unset_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DB_ENV_VAR, raising=False)
        result = _resolve_db_path()
        # sanitize_storage_path resolves to an absolute path; the default
        # should still end with the canonical db filename.
        assert result.name == "citation.db"
        assert result.is_absolute()

    def test_env_set_returns_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "cit.db"
        monkeypatch.setenv(_DB_ENV_VAR, str(db_path))
        result = _resolve_db_path()
        assert result == db_path.resolve()

    def test_env_set_traversal_raises_security_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A path with directory traversal is rejected at the CLI boundary."""
        from src.utils.security import SecurityError

        monkeypatch.setenv(_DB_ENV_VAR, "../../etc/x.db")
        with pytest.raises(SecurityError):
            _resolve_db_path()

    def test_handle_errors_translates_security_error_to_clean_exit(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SecurityError from _resolve_db_path produces exit 1 + generic message."""
        from src.utils.security import SecurityError

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module,
            "_build_store",
            lambda **kw: (_ for _ in ()).throw(
                SecurityError("path outside approved roots")
            ),
        )

        result = runner.invoke(citation_app, ["path", "paper:s2:a", "paper:s2:b"])
        assert result.exit_code != 0
        # Generic message shown, not the raw SecurityError detail
        assert "Operation failed" in result.output


# ---------------------------------------------------------------------------
# _validate_paper_id
# ---------------------------------------------------------------------------


class TestValidatePaperId:
    def test_valid_id_passes(self) -> None:
        # Should not raise
        _validate_paper_id("paper:s2:abc123")

    def test_empty_string_raises_bad_parameter(self) -> None:
        with pytest.raises(typer.BadParameter, match="non-empty"):
            _validate_paper_id("")

    def test_whitespace_only_raises_bad_parameter(self) -> None:
        with pytest.raises(typer.BadParameter, match="non-empty"):
            _validate_paper_id("   ")

    def test_too_long_raises_bad_parameter(self) -> None:
        with pytest.raises(typer.BadParameter, match="exceeds max"):
            _validate_paper_id("a" * 513)

    def test_invalid_chars_raises_bad_parameter(self) -> None:
        with pytest.raises(typer.BadParameter, match="Invalid paper_id format"):
            _validate_paper_id("paper/with/slashes")


# ---------------------------------------------------------------------------
# Helpers: build functions (no-injection path)
# ---------------------------------------------------------------------------


class TestBuildHelpers:
    def test_build_graph_builder_constructs_from_path(self, tmp_path: Path) -> None:
        from src.services.intelligence.citation.graph_builder import (
            CitationGraphBuilder,
        )

        gb = _build_graph_builder(db_path=tmp_path / "c.db")
        assert isinstance(gb, CitationGraphBuilder)

    def test_build_crawler_constructs_from_path(self, tmp_path: Path) -> None:
        from src.services.intelligence.citation.crawler import CitationCrawler

        cr = _build_crawler(db_path=tmp_path / "c.db")
        assert isinstance(cr, CitationCrawler)

    def test_build_recommender_constructs_from_path(self, tmp_path: Path) -> None:
        from src.services.intelligence.citation.recommender import CitationRecommender

        rec = _build_recommender(db_path=tmp_path / "c.db")
        assert isinstance(rec, CitationRecommender)

    def test_build_scorer_constructs_from_path(self, tmp_path: Path) -> None:
        from src.services.intelligence.citation.influence_scorer import InfluenceScorer

        sc = _build_scorer(db_path=tmp_path / "c.db")
        assert isinstance(sc, InfluenceScorer)

    def test_build_store_constructs_from_path(self, tmp_path: Path) -> None:
        from src.storage.intelligence_graph.unified_graph import SQLiteGraphStore

        st = _build_store(db_path=tmp_path / "c.db")
        assert isinstance(st, SQLiteGraphStore)

    def test_build_graph_builder_uses_env_db_when_no_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from src.services.intelligence.citation.graph_builder import (
            CitationGraphBuilder,
        )

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "env.db"))
        gb = _build_graph_builder()
        assert isinstance(gb, CitationGraphBuilder)

    def test_build_crawler_uses_env_db_when_no_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from src.services.intelligence.citation.crawler import CitationCrawler

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "env.db"))
        cr = _build_crawler()
        assert isinstance(cr, CitationCrawler)

    def test_build_recommender_uses_env_db_when_no_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from src.services.intelligence.citation.recommender import CitationRecommender

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "env.db"))
        rec = _build_recommender()
        assert isinstance(rec, CitationRecommender)

    def test_build_scorer_uses_env_db_when_no_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from src.services.intelligence.citation.influence_scorer import InfluenceScorer

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "env.db"))
        sc = _build_scorer()
        assert isinstance(sc, InfluenceScorer)

    def test_build_store_uses_env_db_when_no_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from src.storage.intelligence_graph.unified_graph import SQLiteGraphStore

        monkeypatch.setenv(_DB_ENV_VAR, str(tmp_path / "env.db"))
        st = _build_store()
        assert isinstance(st, SQLiteGraphStore)


# ---------------------------------------------------------------------------
# `arisp citation build`
# ---------------------------------------------------------------------------


def _make_graph_build_result(
    *,
    seed_paper_id: str = "paper:s2:abc123",
    nodes_added: int = 5,
    edges_added: int = 4,
    provider_used: str = "s2",
    errors: Optional[list] = None,
) -> MagicMock:
    result = MagicMock()
    result.seed_paper_id = seed_paper_id
    result.nodes_added = nodes_added
    result.edges_added = edges_added
    result.provider_used = provider_used
    result.errors = errors or []
    return result


class TestBuildCommand:
    def test_build_happy_path(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result_obj = _make_graph_build_result()
        mock_gb = MagicMock()
        mock_gb.build_for_paper = AsyncMock(return_value=result_obj)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_graph_builder", lambda **kw: mock_gb
        )

        result = runner.invoke(citation_app, ["build", "paper:s2:abc123"])
        assert result.exit_code == 0, result.output
        assert "paper:s2:abc123" in result.output
        assert "nodes_added" in result.output
        mock_gb.build_for_paper.assert_called_once_with(
            "paper:s2:abc123", depth=1, direction=ANY
        )

    def test_build_json_flag(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result_obj = _make_graph_build_result()
        mock_gb = MagicMock()
        mock_gb.build_for_paper = AsyncMock(return_value=result_obj)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_graph_builder", lambda **kw: mock_gb
        )

        result = runner.invoke(citation_app, ["build", "paper:s2:abc123", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["seed_paper_id"] == "paper:s2:abc123"
        assert data["nodes_added"] == 5
        assert "provider_used" in data

    def test_build_invalid_paper_id_exits_nonzero(self, runner: CliRunner) -> None:
        result = runner.invoke(citation_app, ["build", "bad/id/format"])
        assert result.exit_code != 0

    def test_build_service_failure_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_gb = MagicMock()
        mock_gb.build_for_paper = AsyncMock(
            side_effect=RuntimeError("DB connection failed")
        )

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_graph_builder", lambda **kw: mock_gb
        )

        result = runner.invoke(citation_app, ["build", "paper:s2:abc123"])
        assert result.exit_code != 0

    def test_build_with_errors_in_result_shows_warnings(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result_obj = _make_graph_build_result(errors=["S2 rate limited"])
        mock_gb = MagicMock()
        mock_gb.build_for_paper = AsyncMock(return_value=result_obj)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_graph_builder", lambda **kw: mock_gb
        )

        result = runner.invoke(citation_app, ["build", "paper:s2:abc123"])
        assert result.exit_code == 0
        assert "S2 rate limited" in result.output

    def test_build_with_depth_option(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result_obj = _make_graph_build_result()
        mock_gb = MagicMock()
        mock_gb.build_for_paper = AsyncMock(return_value=result_obj)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_graph_builder", lambda **kw: mock_gb
        )

        result = runner.invoke(
            citation_app, ["build", "paper:s2:abc123", "--depth", "1"]
        )
        assert result.exit_code == 0

    def test_build_constructs_builder_correctly(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_build_graph_builder is called with db_path from --db-path option."""
        captured: dict = {}
        result_obj = _make_graph_build_result()
        mock_gb = MagicMock()
        mock_gb.build_for_paper = AsyncMock(return_value=result_obj)

        def fake_builder(*, db_path: Optional[Path] = None) -> MagicMock:
            captured["db_path"] = db_path
            return mock_gb

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_graph_builder", fake_builder)

        result = runner.invoke(
            citation_app,
            ["build", "paper:s2:abc123", "--db-path", "/tmp/test.db"],
        )
        assert result.exit_code == 0, result.output
        assert captured["db_path"] == Path("/tmp/test.db")


# ---------------------------------------------------------------------------
# `arisp citation expand`
# ---------------------------------------------------------------------------


def _make_crawl_result(
    *,
    papers_visited: int = 10,
    levels_reached: int = 2,
    edges_added: int = 8,
    api_calls_made: int = 3,
    budget_exhausted: bool = False,
    persistence_aborted: bool = False,
) -> MagicMock:
    result = MagicMock()
    result.papers_visited = papers_visited
    result.levels_reached = levels_reached
    result.edges_added = edges_added
    result.api_calls_made = api_calls_made
    result.budget_exhausted = budget_exhausted
    result.persistence_aborted = persistence_aborted
    return result


class TestExpandCommand:
    def test_expand_happy_path(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        crawl_result = _make_crawl_result()
        mock_crawler = MagicMock()
        mock_crawler.crawl = AsyncMock(return_value=crawl_result)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_crawler", lambda **kw: mock_crawler
        )

        result = runner.invoke(citation_app, ["expand", "paper:s2:abc123"])
        assert result.exit_code == 0, result.output
        assert "papers_visited" in result.output
        assert "10" in result.output
        mock_crawler.crawl.assert_called_once_with("paper:s2:abc123", config=ANY)

    def test_expand_invalid_paper_id_exits_nonzero(self, runner: CliRunner) -> None:
        result = runner.invoke(citation_app, ["expand", "bad/id"])
        assert result.exit_code != 0

    def test_expand_service_failure_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_crawler = MagicMock()
        mock_crawler.crawl = AsyncMock(side_effect=RuntimeError("network error"))

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_crawler", lambda **kw: mock_crawler
        )

        result = runner.invoke(citation_app, ["expand", "paper:s2:abc123"])
        assert result.exit_code != 0

    def test_expand_json_flag(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        crawl_result = _make_crawl_result(papers_visited=7, edges_added=5)
        mock_crawler = MagicMock()
        mock_crawler.crawl = AsyncMock(return_value=crawl_result)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_crawler", lambda **kw: mock_crawler
        )

        result = runner.invoke(citation_app, ["expand", "paper:s2:abc123", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["papers_visited"] == 7
        assert data["edges_added"] == 5

    def test_expand_budget_exhausted_shows_warning(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        crawl_result = _make_crawl_result(budget_exhausted=True)
        mock_crawler = MagicMock()
        mock_crawler.crawl = AsyncMock(return_value=crawl_result)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_crawler", lambda **kw: mock_crawler
        )

        result = runner.invoke(citation_app, ["expand", "paper:s2:abc123"])
        assert result.exit_code == 0
        assert "budget exhausted" in result.output

    def test_expand_persistence_aborted_shows_warning(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        crawl_result = _make_crawl_result(persistence_aborted=True)
        mock_crawler = MagicMock()
        mock_crawler.crawl = AsyncMock(return_value=crawl_result)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_crawler", lambda **kw: mock_crawler
        )

        result = runner.invoke(citation_app, ["expand", "paper:s2:abc123"])
        assert result.exit_code == 0
        assert "Persistence failure" in result.output

    def test_expand_with_direction_forward(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        crawl_result = _make_crawl_result()
        mock_crawler = MagicMock()
        mock_crawler.crawl = AsyncMock(return_value=crawl_result)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_crawler", lambda **kw: mock_crawler
        )

        result = runner.invoke(
            citation_app,
            ["expand", "paper:s2:abc123", "--direction", "forward"],
        )
        assert result.exit_code == 0, result.output
        # Confirm CrawlConfig got direction=forward
        call_args = mock_crawler.crawl.call_args
        # call may be positional or keyword
        config = (
            call_args.args[1]
            if len(call_args.args) > 1
            else call_args.kwargs.get("config")
        )
        assert config.direction == CrawlDirection.FORWARD

    def test_expand_with_max_papers_option(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        crawl_result = _make_crawl_result()
        mock_crawler = MagicMock()
        mock_crawler.crawl = AsyncMock(return_value=crawl_result)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_crawler", lambda **kw: mock_crawler
        )

        result = runner.invoke(
            citation_app,
            ["expand", "paper:s2:abc123", "--max-papers", "10"],
        )
        assert result.exit_code == 0, result.output
        call_args = mock_crawler.crawl.call_args
        config = (
            call_args.args[1]
            if len(call_args.args) > 1
            else call_args.kwargs.get("config")
        )
        assert config.max_papers_per_level == 10

    def test_expand_db_path_forwarded_to_builder(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}
        crawl_result = _make_crawl_result()
        mock_crawler = MagicMock()
        mock_crawler.crawl = AsyncMock(return_value=crawl_result)

        def fake_build_crawler(*, db_path: Optional[Path] = None) -> MagicMock:
            captured["db_path"] = db_path
            return mock_crawler

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_crawler", fake_build_crawler)

        result = runner.invoke(
            citation_app,
            ["expand", "paper:s2:abc123", "--db-path", "/tmp/x.db"],
        )
        assert result.exit_code == 0, result.output
        assert captured["db_path"] == Path("/tmp/x.db")


# ---------------------------------------------------------------------------
# `arisp citation related`
# ---------------------------------------------------------------------------


def _make_recommendation(
    paper_id: str = "paper:s2:related1",
    score: float = 0.85,
    strategy: RecommendationStrategy = RecommendationStrategy.SIMILAR,
    reasoning: str = "shared references",
    seed_paper_id: str = "paper:s2:abc123",
) -> MagicMock:
    rec = MagicMock(spec=Recommendation)
    rec.paper_id = paper_id
    rec.score = score
    rec.strategy = strategy
    rec.reasoning = reasoning
    rec.seed_paper_id = seed_paper_id
    return rec


class TestRelatedCommand:
    def _make_recommender(
        self,
        all_results: Optional[dict] = None,
        single_results: Optional[list] = None,
    ) -> MagicMock:
        mock_rec = MagicMock()
        if all_results is not None:
            mock_rec.recommend_all = AsyncMock(return_value=all_results)
        if single_results is not None:
            mock_rec.recommend_similar = AsyncMock(return_value=single_results)
            mock_rec.recommend_influential_predecessors = AsyncMock(
                return_value=single_results
            )
            mock_rec.recommend_active_successors = AsyncMock(
                return_value=single_results
            )
            mock_rec.recommend_bridge_papers = AsyncMock(return_value=single_results)
        return mock_rec

    def test_related_happy_path_all_strategies(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec1 = _make_recommendation()
        all_results = {
            RecommendationStrategy.SIMILAR: [rec1],
            RecommendationStrategy.INFLUENTIAL_PREDECESSOR: [],
            RecommendationStrategy.ACTIVE_SUCCESSOR: [],
            RecommendationStrategy.BRIDGE: [],
        }
        mock_rec = self._make_recommender(all_results=all_results)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_recommender", lambda **kw: mock_rec
        )

        result = runner.invoke(citation_app, ["related", "paper:s2:abc123"])
        assert result.exit_code == 0, result.output
        assert "similar" in result.output
        assert "paper:s2:related1" in result.output
        mock_rec.recommend_all.assert_called_once_with(
            "paper:s2:abc123", k_per_strategy=5
        )

    def test_related_single_strategy_similar(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec1 = _make_recommendation()
        mock_rec = self._make_recommender(single_results=[rec1])

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_recommender", lambda **kw: mock_rec
        )

        result = runner.invoke(
            citation_app,
            ["related", "paper:s2:abc123", "--strategy", "similar"],
        )
        assert result.exit_code == 0, result.output
        assert "similar" in result.output
        mock_rec.recommend_similar.assert_called_once_with("paper:s2:abc123", k=5)

    def test_related_single_strategy_influential_predecessor(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec1 = _make_recommendation(
            strategy=RecommendationStrategy.INFLUENTIAL_PREDECESSOR
        )
        mock_rec = self._make_recommender(single_results=[rec1])

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_recommender", lambda **kw: mock_rec
        )

        result = runner.invoke(
            citation_app,
            [
                "related",
                "paper:s2:abc123",
                "--strategy",
                "influential_predecessor",
            ],
        )
        assert result.exit_code == 0, result.output
        mock_rec.recommend_influential_predecessors.assert_called_once_with(
            "paper:s2:abc123", k=5
        )

    def test_related_single_strategy_active_successor(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec1 = _make_recommendation(strategy=RecommendationStrategy.ACTIVE_SUCCESSOR)
        mock_rec = self._make_recommender(single_results=[rec1])

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_recommender", lambda **kw: mock_rec
        )

        result = runner.invoke(
            citation_app,
            ["related", "paper:s2:abc123", "--strategy", "active_successor"],
        )
        assert result.exit_code == 0, result.output
        mock_rec.recommend_active_successors.assert_called_once_with(
            "paper:s2:abc123", k=5
        )

    def test_related_single_strategy_bridge(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec1 = _make_recommendation(strategy=RecommendationStrategy.BRIDGE)
        mock_rec = self._make_recommender(single_results=[rec1])

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_recommender", lambda **kw: mock_rec
        )

        result = runner.invoke(
            citation_app,
            ["related", "paper:s2:abc123", "--strategy", "bridge"],
        )
        assert result.exit_code == 0, result.output
        mock_rec.recommend_bridge_papers.assert_called_once_with("paper:s2:abc123", k=5)

    def test_related_invalid_paper_id_exits_nonzero(self, runner: CliRunner) -> None:
        result = runner.invoke(citation_app, ["related", "bad/id"])
        assert result.exit_code != 0

    def test_related_invalid_strategy_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_rec = MagicMock()
        mock_rec.recommend_all = AsyncMock(return_value={})

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_recommender", lambda **kw: mock_rec
        )

        result = runner.invoke(
            citation_app,
            ["related", "paper:s2:abc123", "--strategy", "nonexistent"],
        )
        assert result.exit_code != 0

    def test_related_service_failure_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_rec = MagicMock()
        mock_rec.recommend_all = AsyncMock(side_effect=RuntimeError("DB error"))

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_recommender", lambda **kw: mock_rec
        )

        result = runner.invoke(citation_app, ["related", "paper:s2:abc123"])
        assert result.exit_code != 0

    def test_related_empty_results_prints_no_results(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        all_results = {
            RecommendationStrategy.SIMILAR: [],
            RecommendationStrategy.INFLUENTIAL_PREDECESSOR: [],
            RecommendationStrategy.ACTIVE_SUCCESSOR: [],
            RecommendationStrategy.BRIDGE: [],
        }
        mock_rec = self._make_recommender(all_results=all_results)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_recommender", lambda **kw: mock_rec
        )

        result = runner.invoke(citation_app, ["related", "paper:s2:abc123"])
        assert result.exit_code == 0
        assert "No related papers found" in result.output

    def test_related_json_flag(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec1 = _make_recommendation()
        all_results = {
            RecommendationStrategy.SIMILAR: [rec1],
            RecommendationStrategy.INFLUENTIAL_PREDECESSOR: [],
            RecommendationStrategy.ACTIVE_SUCCESSOR: [],
            RecommendationStrategy.BRIDGE: [],
        }
        mock_rec = self._make_recommender(all_results=all_results)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_recommender", lambda **kw: mock_rec
        )

        result = runner.invoke(citation_app, ["related", "paper:s2:abc123", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "similar" in data
        assert len(data["similar"]) == 1
        assert data["similar"][0]["paper_id"] == "paper:s2:related1"

    def test_related_with_k_option(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        all_results = {
            RecommendationStrategy.SIMILAR: [],
            RecommendationStrategy.INFLUENTIAL_PREDECESSOR: [],
            RecommendationStrategy.ACTIVE_SUCCESSOR: [],
            RecommendationStrategy.BRIDGE: [],
        }
        mock_rec = self._make_recommender(all_results=all_results)

        import src.cli.citation as citation_module

        monkeypatch.setattr(
            citation_module, "_build_recommender", lambda **kw: mock_rec
        )

        result = runner.invoke(
            citation_app, ["related", "paper:s2:abc123", "--k", "10"]
        )
        assert result.exit_code == 0
        mock_rec.recommend_all.assert_called_once_with(
            "paper:s2:abc123", k_per_strategy=10
        )


# ---------------------------------------------------------------------------
# `arisp citation influence`
# ---------------------------------------------------------------------------


def _make_influence_metrics(
    paper_id: str = "paper:s2:abc123",
    citation_count: int = 42,
    citation_velocity: float = 5.3,
    pagerank_score: float = 0.001234,
    hub_score: float = 0.0,
    authority_score: float = 0.0,
) -> MagicMock:
    m = MagicMock()
    m.paper_id = paper_id
    m.citation_count = citation_count
    m.citation_velocity = citation_velocity
    m.pagerank_score = pagerank_score
    m.hub_score = hub_score
    m.authority_score = authority_score
    return m


class TestInfluenceCommand:
    def test_influence_happy_path(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        metrics = _make_influence_metrics()
        mock_scorer = MagicMock()
        mock_scorer.compute_for_paper = AsyncMock(return_value=metrics)

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_scorer", lambda **kw: mock_scorer)

        result = runner.invoke(citation_app, ["influence", "paper:s2:abc123"])
        assert result.exit_code == 0, result.output
        assert "citation_count" in result.output
        assert "42" in result.output
        assert "pagerank_score" in result.output
        mock_scorer.compute_for_paper.assert_called_once_with("paper:s2:abc123")

    def test_influence_renders_all_metrics(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        metrics = _make_influence_metrics(
            citation_count=10,
            citation_velocity=2.5,
            pagerank_score=0.00042,
            hub_score=0.1,
            authority_score=0.2,
        )
        mock_scorer = MagicMock()
        mock_scorer.compute_for_paper = AsyncMock(return_value=metrics)

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_scorer", lambda **kw: mock_scorer)

        result = runner.invoke(citation_app, ["influence", "paper:s2:abc123"])
        assert result.exit_code == 0, result.output
        for field in [
            "citation_count",
            "citation_velocity",
            "pagerank_score",
            "hub_score",
            "authority_score",
        ]:
            assert field in result.output, f"Missing field: {field}"

    def test_influence_invalid_paper_id_exits_nonzero(self, runner: CliRunner) -> None:
        result = runner.invoke(citation_app, ["influence", "bad/id"])
        assert result.exit_code != 0

    def test_influence_service_failure_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_scorer = MagicMock()
        mock_scorer.compute_for_paper = AsyncMock(side_effect=RuntimeError("DB error"))

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_scorer", lambda **kw: mock_scorer)

        result = runner.invoke(citation_app, ["influence", "paper:s2:abc123"])
        assert result.exit_code != 0

    def test_influence_json_flag(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        metrics = _make_influence_metrics(citation_count=99, pagerank_score=0.0042)
        mock_scorer = MagicMock()
        mock_scorer.compute_for_paper = AsyncMock(return_value=metrics)

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_scorer", lambda **kw: mock_scorer)

        result = runner.invoke(citation_app, ["influence", "paper:s2:abc123", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["paper_id"] == "paper:s2:abc123"
        assert data["citation_count"] == 99
        assert "pagerank_score" in data
        assert "hub_score" in data
        assert "authority_score" in data

    def test_influence_max_age_days_option(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--max-age-days passes the correct cache_ttl to _build_scorer."""
        from datetime import timedelta

        metrics = _make_influence_metrics()
        mock_scorer_instance = MagicMock()
        mock_scorer_instance.compute_for_paper = AsyncMock(return_value=metrics)
        built_kwargs: dict = {}

        def fake_build_scorer(
            *, db_path: Optional[Path] = None, cache_ttl: object = None
        ) -> MagicMock:
            built_kwargs["cache_ttl"] = cache_ttl
            return mock_scorer_instance

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_scorer", fake_build_scorer)

        result = runner.invoke(
            citation_app,
            ["influence", "paper:s2:abc123", "--max-age-days", "3"],
        )
        assert result.exit_code == 0, result.output
        assert built_kwargs.get("cache_ttl") == timedelta(days=3)

    def test_influence_db_path_option(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--db-path is forwarded to _build_scorer."""
        captured: dict = {}
        metrics = _make_influence_metrics()
        mock_scorer_instance = MagicMock()
        mock_scorer_instance.compute_for_paper = AsyncMock(return_value=metrics)

        def fake_build_scorer(
            *, db_path: Optional[Path] = None, cache_ttl: object = None
        ) -> MagicMock:
            captured["db_path"] = db_path
            return mock_scorer_instance

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_scorer", fake_build_scorer)

        result = runner.invoke(
            citation_app,
            ["influence", "paper:s2:abc123", "--db-path", "/tmp/x.db"],
        )
        assert result.exit_code == 0, result.output
        assert captured["db_path"] == Path("/tmp/x.db")


# ---------------------------------------------------------------------------
# `arisp citation path`
# ---------------------------------------------------------------------------


def _make_graph_node(node_id: str) -> MagicMock:
    n = MagicMock()
    n.node_id = node_id
    return n


class TestPathCommand:
    def test_path_happy_path(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nodes = [
            _make_graph_node("paper:s2:aaa"),
            _make_graph_node("paper:s2:bbb"),
            _make_graph_node("paper:s2:ccc"),
        ]
        mock_store = MagicMock()
        mock_store.shortest_path = MagicMock(return_value=nodes)

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_store", lambda **kw: mock_store)

        result = runner.invoke(citation_app, ["path", "paper:s2:aaa", "paper:s2:ccc"])
        assert result.exit_code == 0, result.output
        assert "paper:s2:aaa" in result.output
        assert "paper:s2:ccc" in result.output
        assert "->" in result.output
        mock_store.shortest_path.assert_called_once_with(
            "paper:s2:aaa", "paper:s2:ccc", max_depth=6
        )

    def test_path_no_path_found_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_store = MagicMock()
        mock_store.shortest_path = MagicMock(return_value=None)

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_store", lambda **kw: mock_store)

        result = runner.invoke(citation_app, ["path", "paper:s2:aaa", "paper:s2:zzz"])
        assert result.exit_code != 0
        assert "No path" in result.output

    def test_path_invalid_from_paper_id_exits_nonzero(self, runner: CliRunner) -> None:
        result = runner.invoke(citation_app, ["path", "bad/from", "paper:s2:ccc"])
        assert result.exit_code != 0

    def test_path_invalid_to_paper_id_exits_nonzero(self, runner: CliRunner) -> None:
        result = runner.invoke(citation_app, ["path", "paper:s2:aaa", "bad/to"])
        assert result.exit_code != 0

    def test_path_service_failure_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_store = MagicMock()
        mock_store.shortest_path = MagicMock(side_effect=RuntimeError("DB error"))

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_store", lambda **kw: mock_store)

        result = runner.invoke(citation_app, ["path", "paper:s2:aaa", "paper:s2:ccc"])
        assert result.exit_code != 0

    def test_path_json_flag_with_path(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nodes = [
            _make_graph_node("paper:s2:aaa"),
            _make_graph_node("paper:s2:bbb"),
        ]
        mock_store = MagicMock()
        mock_store.shortest_path = MagicMock(return_value=nodes)

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_store", lambda **kw: mock_store)

        result = runner.invoke(
            citation_app,
            ["path", "paper:s2:aaa", "paper:s2:bbb", "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["path"] == ["paper:s2:aaa", "paper:s2:bbb"]
        assert data["length"] == 1

    def test_path_json_flag_no_path(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_store = MagicMock()
        mock_store.shortest_path = MagicMock(return_value=None)

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_store", lambda **kw: mock_store)

        result = runner.invoke(
            citation_app,
            ["path", "paper:s2:aaa", "paper:s2:zzz", "--json"],
        )
        assert result.exit_code != 0
        # Output may contain structlog JSON lines first; find the line with "path"
        json_line = next(
            line for line in result.output.splitlines() if '"path"' in line
        )
        data = json.loads(json_line)
        assert data["path"] is None

    def test_path_logs_paper_not_found(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Structured event ``citation_cli_paper_not_found`` emitted on None path."""
        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "logger", structlog.get_logger())

        mock_store = MagicMock()
        mock_store.shortest_path = MagicMock(return_value=None)
        monkeypatch.setattr(citation_module, "_build_store", lambda **kw: mock_store)

        with structlog.testing.capture_logs() as logs:
            result = runner.invoke(
                citation_app, ["path", "paper:s2:aaa", "paper:s2:zzz"]
            )
        assert result.exit_code != 0
        events = [e for e in logs if e.get("event") == "citation_cli_paper_not_found"]
        assert len(events) == 1

    def test_path_length_shown_in_output(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nodes = [
            _make_graph_node("paper:s2:a"),
            _make_graph_node("paper:s2:b"),
            _make_graph_node("paper:s2:c"),
        ]
        mock_store = MagicMock()
        mock_store.shortest_path = MagicMock(return_value=nodes)

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_store", lambda **kw: mock_store)

        result = runner.invoke(citation_app, ["path", "paper:s2:a", "paper:s2:c"])
        assert result.exit_code == 0
        assert "2 hop" in result.output

    def test_path_db_path_forwarded_to_store_builder(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}
        nodes = [_make_graph_node("paper:s2:a"), _make_graph_node("paper:s2:b")]
        mock_store = MagicMock()
        mock_store.shortest_path = MagicMock(return_value=nodes)

        def fake_build_store(*, db_path: Optional[Path] = None) -> MagicMock:
            captured["db_path"] = db_path
            return mock_store

        import src.cli.citation as citation_module

        monkeypatch.setattr(citation_module, "_build_store", fake_build_store)

        result = runner.invoke(
            citation_app,
            ["path", "paper:s2:a", "paper:s2:b", "--db-path", "/tmp/q.db"],
        )
        assert result.exit_code == 0, result.output
        assert captured["db_path"] == Path("/tmp/q.db")


# ---------------------------------------------------------------------------
# Error logging: @handle_errors logs command_failed events
# ---------------------------------------------------------------------------


class TestErrorLogging:
    def test_build_service_failure_logs_error_event(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """@handle_errors catches and logs service failures via structlog."""
        import src.cli.citation as citation_module
        import src.cli.utils as utils_module

        monkeypatch.setattr(utils_module, "logger", structlog.get_logger())

        mock_gb = MagicMock()
        mock_gb.build_for_paper = AsyncMock(side_effect=RuntimeError("oops"))
        monkeypatch.setattr(
            citation_module, "_build_graph_builder", lambda **kw: mock_gb
        )

        with structlog.testing.capture_logs() as logs:
            result = runner.invoke(citation_app, ["build", "paper:s2:abc123"])

        assert result.exit_code != 0
        events = [e for e in logs if e.get("event") == "command_failed"]
        assert len(events) >= 1
        ev = events[0]
        assert "error" in ev
        assert "oops" in ev["error"]
        assert ev.get("error_type") == "RuntimeError"

    def test_handle_errors_generic_user_message(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """@handle_errors emits the generic user-facing message on failure."""
        import src.cli.citation as citation_module

        mock_gb = MagicMock()
        mock_gb.build_for_paper = AsyncMock(side_effect=RuntimeError("internal detail"))
        monkeypatch.setattr(
            citation_module, "_build_graph_builder", lambda **kw: mock_gb
        )

        result = runner.invoke(citation_app, ["build", "paper:s2:abc123"])
        assert result.exit_code != 0
        # The generic user-facing message MUST appear in the output.
        assert "Operation failed" in result.output
        # The raw exception message must NOT appear outside of any
        # structured log lines (structlog JSON contains it in the "error"
        # key, which is acceptable — the user-facing *plain text* should
        # not expose raw internals).
        non_json_lines = [
            line
            for line in result.output.splitlines()
            if not line.strip().startswith("{")
        ]
        assert not any("internal detail" in ln for ln in non_json_lines)

    def test_handle_errors_trunc_in_log(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """@handle_errors logs a truncated error string, not the full exception."""
        import src.cli.citation as citation_module
        import src.cli.utils as utils_module

        monkeypatch.setattr(utils_module, "logger", structlog.get_logger())

        long_msg = "x" * 300
        mock_gb = MagicMock()
        mock_gb.build_for_paper = AsyncMock(side_effect=ValueError(long_msg))
        monkeypatch.setattr(
            citation_module, "_build_graph_builder", lambda **kw: mock_gb
        )

        with structlog.testing.capture_logs() as logs:
            result = runner.invoke(citation_app, ["build", "paper:s2:abc123"])

        assert result.exit_code != 0
        events = [e for e in logs if e.get("event") == "command_failed"]
        assert events
        logged_error = events[0]["error"]
        # _trunc caps at 200 chars + suffix
        assert len(logged_error) <= 220
        assert "[...truncated]" in logged_error

"""``arisp citation`` CLI commands (REQ-9.2.6).

Sub-app for the citation graph intelligence milestone (Phase 9.2 Week 3).
Mirrors ``src/cli/monitor.py``'s structure: a Typer sub-app registered
against the main ``arisp`` CLI in ``src/cli/__init__.py``.

Commands:

- ``arisp citation build <paper_id>`` -- bootstrap a depth-1 citation graph
  for a seed paper using :class:`CitationGraphBuilder`.
- ``arisp citation expand <paper_id>`` -- BFS-crawl outward via
  :class:`CitationCrawler`.
- ``arisp citation related <paper_id>`` -- list top-K related papers via
  :class:`CitationRecommender` using all four strategies.
- ``arisp citation influence <paper_id>`` -- show PageRank + citation velocity
  from :class:`InfluenceScorer`.
- ``arisp citation path <from_paper_id> <to_paper_id>`` -- find shortest
  citation path via :class:`SQLiteGraphStore.shortest_path`.

All commands wire through factory helpers that are patchable at the module
boundary (DI seam for tests — mirror of PR #143 H-5 lesson).

DB path
-------
The SQLite database that hosts the citation graph is read from the
``ARISP_CITATION_DB`` environment variable (default ``./data/citation.db``).

Error handling
--------------
- Invalid paper_id format: ``ValueError`` from ``_validate_paper_id``,
  re-raised as ``typer.BadParameter`` with a matchable message.
- Missing seed paper in graph: user-friendly message + exit 1 +
  structured log event ``citation_cli_paper_not_found``.
- Empty results: "no results" (not an error).
- Service failures: structured log + exit code 1 via ``@handle_errors``.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

import structlog
import typer

from src.cli.utils import display_error, display_info, display_success, handle_errors
from src.services.intelligence.citation._id_validation import (
    CANONICAL_NODE_ID_PATTERN,
    PAPER_ID_MAX_LENGTH,
)
from src.services.intelligence.citation.models import (
    CrawlDirection,
    RecommendationStrategy,
)
from src.storage.intelligence_graph.path_utils import sanitize_storage_path

logger = structlog.get_logger()

_DEFAULT_DB_RELATIVE = Path("./data/citation.db")
_DB_ENV_VAR = "ARISP_CITATION_DB"

citation_app = typer.Typer(help="Citation graph intelligence (Phase 9.2)")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_paper_id(paper_id: str) -> None:
    """Validate a paper id against the canonical node-id pattern.

    Raises:
        typer.BadParameter: If ``paper_id`` is malformed.
    """
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise typer.BadParameter("paper_id must be a non-empty string")
    if len(paper_id) > PAPER_ID_MAX_LENGTH:
        raise typer.BadParameter(
            f"paper_id length {len(paper_id)} exceeds max {PAPER_ID_MAX_LENGTH}"
        )
    if not CANONICAL_NODE_ID_PATTERN.match(paper_id):
        raise typer.BadParameter(
            f"Invalid paper_id format: {paper_id!r}. "
            "Allowed: alphanumeric, colons, periods, hyphens, underscores."
        )


# ---------------------------------------------------------------------------
# Wiring helpers (patchable at module boundary — DI seam for tests)
# ---------------------------------------------------------------------------


def _resolve_db_path() -> Path:
    """Return the configured SQLite DB path for citation tables.

    Sanitizes the path at the CLI boundary to prevent directory traversal.
    Raises ``SecurityError`` if the resolved path is outside approved roots.
    """
    env_value = os.environ.get(_DB_ENV_VAR)
    return sanitize_storage_path(env_value or _DEFAULT_DB_RELATIVE)


def _build_graph_builder(*, db_path: Optional[Path] = None) -> Any:
    """Construct a :class:`CitationGraphBuilder` from a DB path.

    Args:
        db_path: Path to the SQLite DB. Defaults to ``_resolve_db_path()``.

    Returns:
        A ready-to-use ``CitationGraphBuilder``.
    """
    from src.services.intelligence.citation.graph_builder import CitationGraphBuilder
    from src.services.intelligence.citation.openalex_client import (
        OpenAlexCitationClient,
    )
    from src.services.intelligence.citation.semantic_scholar_client import (
        SemanticScholarCitationClient,
    )
    from src.storage.intelligence_graph.unified_graph import SQLiteGraphStore

    resolved = db_path or _resolve_db_path()
    store = SQLiteGraphStore(resolved)
    store.initialize()
    return CitationGraphBuilder(
        store=store,
        s2_client=SemanticScholarCitationClient(),
        openalex_client=OpenAlexCitationClient(),
    )


def _build_crawler(*, db_path: Optional[Path] = None) -> Any:
    """Construct a :class:`CitationCrawler` from a DB path.

    Args:
        db_path: Path to the SQLite DB. Defaults to ``_resolve_db_path()``.

    Returns:
        A ready-to-use ``CitationCrawler``.
    """
    from src.services.intelligence.citation.crawler import CitationCrawler

    resolved = db_path or _resolve_db_path()
    return CitationCrawler.from_paths(db_path=resolved)


def _build_recommender(*, db_path: Optional[Path] = None) -> Any:
    """Construct a :class:`CitationRecommender` from a DB path.

    Args:
        db_path: Path to the SQLite DB. Defaults to ``_resolve_db_path()``.

    Returns:
        A ready-to-use ``CitationRecommender``.
    """
    from src.services.intelligence.citation.recommender import CitationRecommender

    resolved = db_path or _resolve_db_path()
    return CitationRecommender.connect(db_path=resolved)


def _build_scorer(
    *,
    db_path: Optional[Path] = None,
    cache_ttl: timedelta = timedelta(days=7),
) -> Any:
    """Construct an :class:`InfluenceScorer` from a DB path.

    Args:
        db_path: Path to the SQLite DB. Defaults to ``_resolve_db_path()``.
        cache_ttl: Cache time-to-live for influence computations.
            Defaults to 7 days.

    Returns:
        A ready-to-use ``InfluenceScorer``.
    """
    from src.services.intelligence.citation.influence_scorer import InfluenceScorer

    resolved = db_path or _resolve_db_path()
    return InfluenceScorer.from_paths(db_path=resolved, cache_ttl=cache_ttl)


def _build_store(*, db_path: Optional[Path] = None) -> Any:
    """Construct a :class:`SQLiteGraphStore` from a DB path.

    Args:
        db_path: Path to the SQLite DB. Defaults to ``_resolve_db_path()``.

    Returns:
        A ready-to-use ``SQLiteGraphStore``.
    """
    from src.storage.intelligence_graph.unified_graph import SQLiteGraphStore

    resolved = db_path or _resolve_db_path()
    st = SQLiteGraphStore(resolved)
    st.initialize()
    return st


# ---------------------------------------------------------------------------
# `arisp citation build`
# ---------------------------------------------------------------------------


@citation_app.command("build")
@handle_errors
def build_command(
    paper_id: str = typer.Argument(..., help="Seed paper id"),
    depth: int = typer.Option(
        1, "--depth", min=1, max=1, help="Graph depth (currently fixed at 1)"
    ),
    db_path: Optional[Path] = typer.Option(
        None, "--db-path", help="Override citation DB path"
    ),
    emit_json: bool = typer.Option(False, "--json", help="Emit JSON output"),
) -> None:
    """Bootstrap a citation graph for a seed paper."""
    _validate_paper_id(paper_id)

    gb = _build_graph_builder(db_path=db_path)

    from src.services.intelligence.citation.models import CitationDirection

    result = asyncio.run(
        gb.build_for_paper(paper_id, depth=depth, direction=CitationDirection.BOTH)
    )

    if emit_json:
        typer.echo(
            json.dumps(
                {
                    "seed_paper_id": result.seed_paper_id,
                    "nodes_added": result.nodes_added,
                    "edges_added": result.edges_added,
                    "provider_used": str(result.provider_used),
                    "errors": result.errors,
                }
            )
        )
        return

    display_success(f"Graph built for {result.seed_paper_id}")
    display_info(f"  nodes_added: {result.nodes_added}")
    display_info(f"  edges_added: {result.edges_added}")
    display_info(f"  provider_used: {result.provider_used}")
    if result.errors:
        for err in result.errors:
            display_error(f"  warning: {err}")


# ---------------------------------------------------------------------------
# `arisp citation expand`
# ---------------------------------------------------------------------------


@citation_app.command("expand")
@handle_errors
def expand_command(
    paper_id: str = typer.Argument(..., help="Seed paper id"),
    depth: int = typer.Option(1, "--depth", min=1, max=3, help="BFS depth (1-3)"),
    max_papers: int = typer.Option(
        50, "--max-papers", min=10, max=200, help="Max papers per BFS level (10-200)"
    ),
    direction: CrawlDirection = typer.Option(
        CrawlDirection.BOTH, "--direction", help="Crawl direction"
    ),
    db_path: Optional[Path] = typer.Option(
        None, "--db-path", help="Override citation DB path"
    ),
    emit_json: bool = typer.Option(False, "--json", help="Emit JSON output"),
) -> None:
    """BFS-crawl the citation graph outward from a seed paper."""
    _validate_paper_id(paper_id)

    from src.services.intelligence.citation.crawler import CrawlConfig

    config = CrawlConfig(
        max_depth=depth,
        max_papers_per_level=max_papers,
        direction=direction,
    )

    cr = _build_crawler(db_path=db_path)
    result = asyncio.run(cr.crawl(paper_id, config=config))

    if emit_json:
        typer.echo(
            json.dumps(
                {
                    "papers_visited": result.papers_visited,
                    "levels_reached": result.levels_reached,
                    "edges_added": result.edges_added,
                    "api_calls_made": result.api_calls_made,
                    "budget_exhausted": result.budget_exhausted,
                    "persistence_aborted": result.persistence_aborted,
                }
            )
        )
        return

    display_success(f"Crawl complete for {paper_id}")
    display_info(f"  papers_visited: {result.papers_visited}")
    display_info(f"  levels_reached: {result.levels_reached}")
    display_info(f"  edges_added: {result.edges_added}")
    display_info(f"  api_calls_made: {result.api_calls_made}")
    if result.budget_exhausted:
        display_error("  warning: API budget exhausted before crawl completed")
    if result.persistence_aborted:
        display_error("  warning: Persistence failure aborted crawl")


# ---------------------------------------------------------------------------
# `arisp citation related`
# ---------------------------------------------------------------------------

_STRATEGY_ALL = "all"
_VALID_STRATEGIES = [
    RecommendationStrategy.SIMILAR.value,
    RecommendationStrategy.INFLUENTIAL_PREDECESSOR.value,
    RecommendationStrategy.ACTIVE_SUCCESSOR.value,
    RecommendationStrategy.BRIDGE.value,
    _STRATEGY_ALL,
]


@citation_app.command("related")
@handle_errors
def related_command(
    paper_id: str = typer.Argument(..., help="Seed paper id"),
    k: int = typer.Option(
        5, "--k", min=1, max=100, help="Results per strategy (1-100)"
    ),
    strategy: str = typer.Option(
        _STRATEGY_ALL,
        "--strategy",
        help=(
            "Strategy to use: similar, influential_predecessor, "
            "active_successor, bridge, all"
        ),
    ),
    db_path: Optional[Path] = typer.Option(
        None, "--db-path", help="Override citation DB path"
    ),
    emit_json: bool = typer.Option(False, "--json", help="Emit JSON output"),
) -> None:
    """List top-K related papers using citation recommendation strategies."""
    _validate_paper_id(paper_id)

    if strategy not in _VALID_STRATEGIES:
        raise typer.BadParameter(
            f"Invalid strategy {strategy!r}. "
            f"Choose from: {', '.join(_VALID_STRATEGIES)}"
        )

    rec = _build_recommender(db_path=db_path)

    if strategy == _STRATEGY_ALL:
        results_by_strategy = asyncio.run(rec.recommend_all(paper_id, k_per_strategy=k))
    else:
        strat_enum = RecommendationStrategy(strategy)
        method_map = {
            RecommendationStrategy.SIMILAR: rec.recommend_similar,
            RecommendationStrategy.INFLUENTIAL_PREDECESSOR: (
                rec.recommend_influential_predecessors
            ),
            RecommendationStrategy.ACTIVE_SUCCESSOR: rec.recommend_active_successors,
            RecommendationStrategy.BRIDGE: rec.recommend_bridge_papers,
        }
        recs = asyncio.run(method_map[strat_enum](paper_id, k=k))
        results_by_strategy = {strat_enum: recs}

    if emit_json:
        typer.echo(
            json.dumps(
                {
                    strat.value: [
                        {
                            "paper_id": r.paper_id,
                            "score": r.score,
                            "reasoning": r.reasoning,
                        }
                        for r in recs_list
                    ]
                    for strat, recs_list in results_by_strategy.items()
                }
            )
        )
        return

    any_results = False
    for strat, recs_list in results_by_strategy.items():
        typer.echo(f"\n--- {strat.value} ---")
        if not recs_list:
            typer.echo("  (no results)")
            continue
        any_results = True
        for i, rec_item in enumerate(recs_list, 1):
            typer.echo(f"  {i}. {rec_item.paper_id}  score={rec_item.score:.4f}")
            typer.echo(f"     {rec_item.reasoning}")

    if not any_results:
        display_info("No related papers found.")


# ---------------------------------------------------------------------------
# `arisp citation influence`
# ---------------------------------------------------------------------------


@citation_app.command("influence")
@handle_errors
def influence_command(
    paper_id: str = typer.Argument(..., help="Seed paper id"),
    max_age_days: int = typer.Option(7, "--max-age-days", help="Cache TTL in days"),
    db_path: Optional[Path] = typer.Option(
        None, "--db-path", help="Override citation DB path"
    ),
    emit_json: bool = typer.Option(False, "--json", help="Emit JSON output"),
) -> None:
    """Show PageRank + citation velocity for a paper."""
    _validate_paper_id(paper_id)

    sc = _build_scorer(db_path=db_path, cache_ttl=timedelta(days=max_age_days))

    metrics = asyncio.run(sc.compute_for_paper(paper_id))

    if emit_json:
        typer.echo(
            json.dumps(
                {
                    "paper_id": metrics.paper_id,
                    "citation_count": metrics.citation_count,
                    "citation_velocity": metrics.citation_velocity,
                    "pagerank_score": metrics.pagerank_score,
                    "hub_score": metrics.hub_score,
                    "authority_score": metrics.authority_score,
                }
            )
        )
        return

    typer.echo(f"paper_id:          {metrics.paper_id}")
    typer.echo(f"citation_count:    {metrics.citation_count}")
    typer.echo(f"citation_velocity: {metrics.citation_velocity:.4f}")
    typer.echo(f"pagerank_score:    {metrics.pagerank_score:.6f}")
    typer.echo(f"hub_score:         {metrics.hub_score:.6f}")
    typer.echo(f"authority_score:   {metrics.authority_score:.6f}")


# ---------------------------------------------------------------------------
# `arisp citation path`
# ---------------------------------------------------------------------------


@citation_app.command("path")
@handle_errors
def path_command(
    from_paper_id: str = typer.Argument(..., help="Source paper id"),
    to_paper_id: str = typer.Argument(..., help="Target paper id"),
    max_depth: int = typer.Option(
        6, "--max-depth", min=1, max=10, help="Max BFS depth (1-10)"
    ),
    db_path: Optional[Path] = typer.Option(
        None, "--db-path", help="Override citation DB path"
    ),
    emit_json: bool = typer.Option(False, "--json", help="Emit JSON output"),
) -> None:
    """Find shortest citation path between two papers."""
    _validate_paper_id(from_paper_id)
    _validate_paper_id(to_paper_id)

    gs = _build_store(db_path=db_path)

    path_nodes = gs.shortest_path(from_paper_id, to_paper_id, max_depth=max_depth)

    if path_nodes is None:
        logger.info(
            "citation_cli_paper_not_found",
            from_paper_id=from_paper_id,
            to_paper_id=to_paper_id,
        )
        if emit_json:
            typer.echo(
                json.dumps({"path": None, "from": from_paper_id, "to": to_paper_id})
            )
        else:
            display_info(
                f"No path found between {from_paper_id!r} and {to_paper_id!r} "
                f"(max_depth={max_depth})"
            )
        raise typer.Exit(code=1)

    path_ids = [n.node_id for n in path_nodes]

    if emit_json:
        typer.echo(json.dumps({"path": path_ids, "length": len(path_ids) - 1}))
        return

    typer.echo(" -> ".join(path_ids))
    display_info(f"Path length: {len(path_ids) - 1} hop(s)")

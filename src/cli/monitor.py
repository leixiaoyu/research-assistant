"""``arisp monitor`` CLI commands (REQ-9.1.5).

Sub-app for the proactive monitoring milestone. Mirrors
``src/cli/research.py``'s structure: a Typer ``research_app``-style
package, registered against the main ``arisp`` CLI in
``src/cli/__init__.py``.

Commands:

- ``arisp monitor add`` -- register a new ``ResearchSubscription``.
- ``arisp monitor list`` -- table view of subscriptions for one user
  (or all).
- ``arisp monitor check`` -- run one monitoring cycle and count papers
  above the per-subscription relevance threshold. Registration into
  the global RegistryService is handled by ``ArxivMonitor`` at
  discovery time, not here.
- ``arisp monitor digest`` -- generate a markdown digest for a stored
  monitoring run (by id or ``--latest``).

All commands wire through the ``MonitoringRunner.from_paths`` factory
so they can't drift from the scheduled job's wiring.

DB path
-------
The SQLite database that hosts ``subscriptions`` /
``monitoring_runs`` / ``monitoring_papers`` is read from the
``ARISP_MONITORING_DB`` environment variable (default
``./data/monitoring.db``). It is sanitized via the existing
intelligence-graph ``sanitize_storage_path`` so a hostile env var
cannot escape the storage sandbox.

Auto-ingest
-----------
``arisp monitor check`` counts papers whose relevance score is
>= the subscription's ``min_relevance_score`` (default 0.7, per the
resolved decision in ``.omc/plans/open-questions.md``).
Failures from individual paper registrations are logged but do not
abort the cycle (each paper is independent).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import structlog
import typer

from src.cli.utils import display_error, display_info, display_success, handle_errors
from src.services.intelligence.monitoring import (
    DigestGenerator,
    MonitoringRunner,
    ResearchSubscription,
    SubscriptionManager,
)
from src.services.intelligence.monitoring.run_repository import (
    MonitoringRunRepository,
)

if TYPE_CHECKING:
    from src.services.intelligence.monitoring.models import MonitoringRun

logger = structlog.get_logger()

# Where the monitoring SQLite DB lives by default. Overridable via
# the ``ARISP_MONITORING_DB`` env var so tests + ad-hoc scripts can
# point at a temp DB without modifying the CLI module.
_DEFAULT_DB_RELATIVE = Path("./data/monitoring.db")
_DB_ENV_VAR = "ARISP_MONITORING_DB"


monitor_app = typer.Typer(help="Proactive paper monitoring (Milestone 9.1)")


# ---------------------------------------------------------------------------
# Wiring helpers (small + pure so they're easy to unit-test)
# ---------------------------------------------------------------------------


def _resolve_db_path() -> Path:
    """Return the configured SQLite DB path for monitoring tables."""
    env_value = os.environ.get(_DB_ENV_VAR)
    return Path(env_value) if env_value else _DEFAULT_DB_RELATIVE


def _build_subscription_manager() -> SubscriptionManager:
    """Construct + initialize a ``SubscriptionManager``.

    Lives in its own helper so the CLI commands that don't need the
    full ``MonitoringRunner`` wiring (``add`` / ``list``) can avoid
    constructing the ArxivProvider + RegistryService.
    """
    mgr = SubscriptionManager(_resolve_db_path())
    mgr.initialize()
    return mgr


def _build_run_repo() -> MonitoringRunRepository:
    """Construct + initialize a ``MonitoringRunRepository``."""
    repo = MonitoringRunRepository(_resolve_db_path())
    repo.initialize()
    return repo


def _build_runner(
    registry: Optional[object] = None,
    arxiv: Optional[object] = None,
) -> MonitoringRunner:
    """Construct a fully-wired ``MonitoringRunner`` for ``check``.

    Imports inline so ``add`` / ``list`` / ``digest`` don't pay the
    cost (or the side-effect risk) of constructing the registry +
    arxiv provider when they don't need them.

    Tier 1 (Issue #139): when an LLM key is available we wire the
    multi-provider monitor with arXiv + Semantic Scholar + OpenAlex +
    HuggingFace, plus a :class:`QueryExpander` that turns each
    subscription's literal query into N variants via Gemini Flash. This
    dramatically broadens discovery without requiring spec changes —
    the monitor still returns ``ArxivMonitorResult`` so the runner is
    duck-type compatible. When the LLM key is missing, falls back to
    legacy single-arXiv behavior (no expansion, single provider).

    Args:
        registry: Optional ``RegistryService`` seam for testing.
            When ``None``, a default ``RegistryService()`` is built.
        arxiv: Optional ``ArxivProvider`` seam for testing.
            When ``None``, a default ``ArxivProvider()`` is built.
    """
    from src.models.llm import CostLimits, LLMConfig
    from src.services.intelligence.monitoring.models import PaperSource
    from src.services.llm.service import LLMService
    from src.services.providers.arxiv import ArxivProvider
    from src.services.registry.service import RegistryService

    resolved_registry = registry if registry is not None else RegistryService()
    resolved_arxiv = arxiv if arxiv is not None else ArxivProvider()

    # Build LLMService for relevance scoring + query expansion from env
    # (never hardcoded). If the key is absent, run without scoring or
    # expansion (graceful degradation -- legacy single-arxiv behavior).
    llm_svc = None
    llm_api_key = os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if llm_api_key and llm_api_key.strip():
        try:
            llm_config = LLMConfig(api_key=llm_api_key)
            llm_cost_limits = CostLimits()
            llm_svc = LLMService(config=llm_config, cost_limits=llm_cost_limits)
        except Exception as exc:
            logger.warning(
                "monitor_cli_llm_init_failed",
                error_type=type(exc).__name__,
                reason="scoring_and_expansion_will_be_skipped",
            )

    # Tier 1: build extra providers + query expander when LLM is wired.
    # Constructed lazily so the legacy-fallback path doesn't pay the
    # provider-construction cost.
    extra_providers = None
    query_expander = None
    if llm_svc is not None:
        try:
            from src.services.providers.huggingface import HuggingFaceProvider
            from src.services.providers.openalex import OpenAlexProvider
            from src.services.providers.semantic_scholar import (
                SemanticScholarProvider,
            )
            from src.utils.query_expander import QueryExpander

            # Semantic Scholar requires an API key; OpenAlex + HuggingFace
            # are anonymous-public. If S2 key is missing, skip S2 only --
            # the other providers still broaden discovery.
            extra_providers = {
                PaperSource.OPENALEX: OpenAlexProvider(),
                PaperSource.HUGGINGFACE: HuggingFaceProvider(),
            }
            s2_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
            if s2_key and s2_key.strip():
                extra_providers[PaperSource.SEMANTIC_SCHOLAR] = SemanticScholarProvider(
                    api_key=s2_key
                )
            query_expander = QueryExpander(llm_service=llm_svc)
        except Exception as exc:
            logger.warning(
                "monitor_cli_tier1_init_failed",
                error=str(exc),
                reason="falling_back_to_legacy_single_arxiv",
            )
            extra_providers = None
            query_expander = None

    return MonitoringRunner.from_paths(
        db_path=_resolve_db_path(),
        registry=resolved_registry,  # type: ignore[arg-type]
        arxiv_provider=resolved_arxiv,  # type: ignore[arg-type]
        llm_service=llm_svc,
        extra_providers=extra_providers,  # type: ignore[arg-type]
        query_expander=query_expander,
    )


# ---------------------------------------------------------------------------
# `arisp monitor add`
# ---------------------------------------------------------------------------


@monitor_app.command("add")
@handle_errors
def add_command(
    name: str = typer.Option(..., "--name", help="Human-readable subscription name"),
    query: str = typer.Option(
        ...,
        "--query",
        help="Base ArXiv query for the subscription",
    ),
    keywords: Optional[list[str]] = typer.Option(
        None,
        "--keyword",
        "-k",
        help="Additional keywords (repeatable)",
    ),
    user_id: str = typer.Option(
        "default",
        "--user-id",
        "-u",
        help="Owner user identifier",
    ),
    poll_interval_hours: int = typer.Option(
        6,
        "--poll-hours",
        help="Cycle interval in hours (1..168)",
    ),
) -> None:
    """Register a new monitoring subscription."""
    sub = ResearchSubscription(
        user_id=user_id,
        name=name,
        query=query,
        keywords=keywords or [],
        poll_interval_hours=poll_interval_hours,
    )
    mgr = _build_subscription_manager()
    sub_id = mgr.add_subscription(sub)
    display_success(f"Created subscription {sub_id}")
    display_info(f"  user_id: {user_id}")
    display_info(f"  name: {name}")
    display_info(f"  query: {query}")
    display_info(f"  poll_interval_hours: {poll_interval_hours}")


# ---------------------------------------------------------------------------
# `arisp monitor list`
# ---------------------------------------------------------------------------


@monitor_app.command("list")
@handle_errors
def list_command(
    user_id: Optional[str] = typer.Option(
        None,
        "--user-id",
        "-u",
        help="Filter by owner user (default: all users)",
    ),
    active_only: bool = typer.Option(
        False,
        "--active-only/--all",
        help="Only show active subscriptions",
    ),
) -> None:
    """List subscriptions in a simple text table."""
    mgr = _build_subscription_manager()
    subs = mgr.list_subscriptions(user_id=user_id, active_only=active_only)
    if not subs:
        display_info("No subscriptions found.")
        return
    # Plain-text table -- intentionally simple to keep dependencies low
    # and to avoid coupling the CLI to a specific table renderer.
    header = f"{'subscription_id':<24} {'user':<12} {'status':<8} {'name':<32} query"
    typer.echo(header)
    typer.echo("-" * len(header))
    for sub in subs:
        typer.echo(
            f"{sub.subscription_id:<24} {sub.user_id:<12} "
            f"{sub.status.value:<8} {sub.name[:32]:<32} {sub.query}"
        )


# ---------------------------------------------------------------------------
# `arisp monitor check`
# ---------------------------------------------------------------------------


def _auto_ingest_runs(
    runs: list["MonitoringRun"],
    subscriptions_by_id: Optional[dict] = None,
) -> int:
    """Count high-relevance papers from one cycle.

    Returns:
        Count of papers above the per-subscription ``min_relevance_score``
        threshold (default 0.7 from the model). Uses the subscription's own
        threshold rather than a hardcoded global constant (H-A4).

    The CLI does not invoke ``RegistryService.register_paper`` again
    for these papers -- ``ArxivMonitor.check`` already did so at
    discovery time. What this helper does is **report** how many cleared
    the threshold so the user knows to expect them in the registry.

    Args:
        runs: Monitoring runs from the current cycle.
        subscriptions_by_id: Optional map from subscription_id to
            ``ResearchSubscription``. When provided, the per-sub
            threshold is used; when absent a default 0.7 is applied.
    """
    above_threshold = 0
    for run in runs:
        # Resolve the per-subscription threshold.
        default_threshold = 0.7
        if subscriptions_by_id is not None:
            sub = subscriptions_by_id.get(run.subscription_id)
            threshold = (
                sub.min_relevance_score if sub is not None else default_threshold
            )
        else:
            threshold = default_threshold
        for paper in run.papers:
            if paper.relevance_score is not None and paper.relevance_score >= threshold:
                above_threshold += 1
    return above_threshold


@monitor_app.command("check")
@handle_errors
def check_command(
    user_id: Optional[str] = typer.Option(
        None,
        "--user-id",
        "-u",
        help="Run only this user's subscriptions",
    ),
) -> None:
    """Run one monitoring cycle and print a summary."""
    runner = _build_runner()
    runs = asyncio.run(runner.run_once(user_id=user_id))
    if not runs:
        display_info("No active subscriptions; nothing to check.")
        return

    # Build a subscription map for per-sub threshold lookup (H-A4).
    subs_by_id = {sub.subscription_id: sub for sub in runner.list_subscriptions()}
    above = _auto_ingest_runs(runs, subscriptions_by_id=subs_by_id)

    typer.echo("")
    header = f"{'subscription_id':<24} {'status':<8} {'seen':>6} {'new':>6}"
    typer.echo(header)
    typer.echo("-" * len(header))
    for run in runs:
        typer.echo(
            f"{run.subscription_id:<24} {run.status.value:<8} "
            f"{run.papers_seen:>6} {run.papers_new:>6}"
        )
    typer.echo("")
    display_info(
        f"Cycle complete: {len(runs)} run(s); "
        f"{above} paper(s) above per-subscription relevance threshold."
    )


# ---------------------------------------------------------------------------
# `arisp monitor digest`
# ---------------------------------------------------------------------------


@monitor_app.command("digest")
@handle_errors
def digest_command(
    run_id: Optional[str] = typer.Argument(
        None, help="Specific run id to digest (omit to use --latest)"
    ),
    latest: bool = typer.Option(
        False,
        "--latest",
        help="Use the most recent stored run (across all subscriptions)",
    ),
    output_root: Optional[Path] = typer.Option(
        None,
        "--output-root",
        help="Override digest output directory",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Generate digest even for FAILED runs (debug/audit use only)",
    ),
) -> None:
    """Generate the markdown digest for a stored monitoring run."""
    if run_id is None and not latest:
        display_error("Pass either a RUN_ID argument or --latest.")
        raise typer.Exit(code=1)
    if run_id is not None and latest:
        display_error("Pass RUN_ID or --latest, not both.")
        raise typer.Exit(code=1)

    repo = _build_run_repo()

    audit_run = None
    if latest:
        latest_runs = repo.list_runs(limit=1)
        if not latest_runs:
            display_error("No stored monitoring runs.")
            raise typer.Exit(code=1)
        audit_run = latest_runs[0]
    else:
        # ``run_id`` is non-None at this point (mutually-exclusive guard
        # above). Use a proper guard rather than assert (H-C4).
        if run_id is None:
            raise typer.BadParameter("internal: run_id missing despite guard")
        audit_run = repo.get_run(run_id)
        if audit_run is None:
            display_error(f"Run not found: {run_id}")
            raise typer.Exit(code=1)

    # C-2: Gate on FAILED status -- a FAILED run has no papers to digest.
    # Callers who genuinely need the empty digest for audit/debug can
    # pass ``--force`` to override.
    from src.services.intelligence.monitoring.models import MonitoringRunStatus

    if audit_run.status is MonitoringRunStatus.FAILED and not force:
        display_error(
            f"Run {audit_run.run_id} has status FAILED; digest would be empty. "
            "Pass --force to generate anyway."
        )
        raise typer.Exit(code=1)

    # Load the owning subscription so the digest header has the name +
    # query. If the sub was deleted but the audit row remains, we still
    # render with a fallback subscription so the digest is useful for
    # post-mortems.
    mgr = _build_subscription_manager()
    sub = mgr.get_subscription(audit_run.subscription_id)
    if sub is None:
        display_info(
            f"Subscription {audit_run.subscription_id} no longer exists; "
            "rendering digest with a placeholder subscription record."
        )
        sub = ResearchSubscription(
            subscription_id=audit_run.subscription_id,
            user_id=audit_run.user_id,
            name=f"(deleted) {audit_run.subscription_id}",
            query="(unknown)",
        )

    generator = DigestGenerator(output_root=output_root)
    path = generator.generate(audit_run, sub)
    display_success(f"Digest written: {path}")

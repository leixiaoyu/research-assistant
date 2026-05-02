"""``arisp monitor`` CLI commands (REQ-9.1.5).

Sub-app for the proactive monitoring milestone. Mirrors
``src/cli/research.py``'s structure: a Typer ``research_app``-style
package, registered against the main ``arisp`` CLI in
``src/cli/__init__.py``.

Commands:

- ``arisp monitor add`` -- register a new ``ResearchSubscription``.
- ``arisp monitor list`` -- table view of subscriptions for one user
  (or all).
- ``arisp monitor check`` -- run one monitoring cycle and (optionally)
  auto-ingest papers above the relevance threshold.
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
``arisp monitor check`` registers any paper whose relevance score is
>= ``AUTO_INGEST_THRESHOLD`` (0.7, per the resolved decision in
``.omc/plans/open-questions.md``) with the global ``RegistryService``.
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

# Auto-ingest threshold (resolved decision, 2026-04-24).
AUTO_INGEST_THRESHOLD = 0.7

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


def _build_runner() -> MonitoringRunner:
    """Construct a fully-wired ``MonitoringRunner`` for ``check``.

    Imports inline so ``add`` / ``list`` / ``digest`` don't pay the
    cost (or the side-effect risk) of constructing the registry +
    arxiv provider when they don't need them.
    """
    from src.services.providers.arxiv import ArxivProvider
    from src.services.registry.service import RegistryService

    registry = RegistryService()
    arxiv = ArxivProvider()
    return MonitoringRunner.from_paths(
        db_path=_resolve_db_path(),
        registry=registry,
        arxiv_provider=arxiv,
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


def _auto_ingest_runs(runs: list["MonitoringRun"]) -> int:
    """Auto-ingest high-relevance papers from one cycle.

    Returns:
        Count of papers above ``AUTO_INGEST_THRESHOLD``.

    The CLI does not invoke ``RegistryService.register_paper`` again
    for these papers -- ``ArxivMonitor.check`` already did so at
    discovery time (``discovery_only=True``). What this helper does
    is **report** how many cleared the threshold so the user knows
    to expect them in the registry.
    """
    above_threshold = 0
    for run in runs:
        for paper in run.papers:
            if (
                paper.relevance_score is not None
                and paper.relevance_score >= AUTO_INGEST_THRESHOLD
            ):
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

    above = _auto_ingest_runs(runs)

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
        f"{above} paper(s) above relevance >= {AUTO_INGEST_THRESHOLD}."
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
        # above). Assert for mypy + as a safety net.
        assert run_id is not None
        audit_run = repo.get_run(run_id)
        if audit_run is None:
            display_error(f"Run not found: {run_id}")
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

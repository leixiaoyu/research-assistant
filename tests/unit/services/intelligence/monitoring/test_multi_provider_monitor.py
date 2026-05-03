"""Tests for ``MultiProviderMonitor`` (Tier 1, Issue #139).

Covers:
- Constructor validates inputs (rejects empty providers).
- ``check`` short-circuits paused subscriptions.
- ``check`` skips query expansion when no expander configured.
- ``check`` expands queries when an expander IS configured.
- ``check`` falls back to the literal query when expander.expand raises.
- ``check`` falls back to the literal query when expander returns empty.
- ``check`` fans out across all configured providers per query variant.
- ``check`` survives a single provider failure (Fail-Soft Boundary).
- ``check`` deduplicates papers by ``paper_id``.
- ``check`` enforces ``max_papers_per_cycle`` cap.
- ``check`` registers new papers ``discovery_only=True``.
- ``check`` skips papers already in the registry.
- ``check`` survives a single registry write error (PARTIAL).
- ``check`` survives a single identity-resolution error (PARTIAL).
- ``MonitoringRunner.from_paths`` builds ``MultiProviderMonitor`` when
  extra_providers OR query_expander is provided.
- ``MonitoringRunner.from_paths`` falls back to ``ArxivMonitor`` when
  neither is provided (backward compatible).
- ``MonitoringRunner.from_paths`` rejects an attempt to override the
  arXiv provider via ``extra_providers``.

Note: ``ArxivMonitorResult`` is intentionally reused as the return DTO
so both monitors are duck-type compatible from the runner's POV.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.paper import PaperMetadata
from src.services.intelligence.monitoring.arxiv_monitor import ArxivMonitor
from src.services.intelligence.monitoring.models import (
    MonitoringRunStatus,
    PaperSource,
    ResearchSubscription,
    SubscriptionStatus,
)
from src.services.intelligence.monitoring.multi_provider_monitor import (
    MultiProviderMonitor,
    MultiProviderMonitorConfig,
)
from src.services.intelligence.monitoring.runner import MonitoringRunner

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_subscription(
    *,
    subscription_id: str = "sub-aaa",
    user_id: str = "alice",
    query: str = "tree of thoughts",
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    sources: list[PaperSource] | None = None,
) -> ResearchSubscription:
    return ResearchSubscription(
        subscription_id=subscription_id,
        user_id=user_id,
        name="Sub",
        query=query,
        status=status,
        sources=sources or [PaperSource.ARXIV],
    )


def _make_paper(paper_id: str, title: str = "Title") -> PaperMetadata:
    return PaperMetadata(
        paper_id=paper_id,
        title=title,
        url=f"https://arxiv.org/abs/{paper_id}",  # type: ignore[arg-type]
    )


def _make_provider(
    return_papers: list[PaperMetadata] | None = None,
    raise_on_search: Exception | None = None,
) -> MagicMock:
    provider = MagicMock()
    if raise_on_search is not None:
        provider.search = AsyncMock(side_effect=raise_on_search)
    else:
        provider.search = AsyncMock(return_value=return_papers or [])
    return provider


def _make_registry(
    *,
    matched_paper_ids: set[str] | None = None,
    register_side_effect: Exception | None = None,
    resolve_side_effect: Exception | None = None,
) -> MagicMock:
    """Build a registry mock that mimics ``RegistryService``'s small contract.

    - ``resolve_identity(paper)`` returns an object with a ``.matched``
      bool — True iff paper.paper_id is in ``matched_paper_ids``.
    - ``register_paper(...)`` is a no-op (or raises if configured).
    """
    registry = MagicMock()
    matched_ids = matched_paper_ids or set()

    def _resolve(paper: PaperMetadata) -> object:
        if resolve_side_effect is not None:
            raise resolve_side_effect
        m = MagicMock()
        m.matched = paper.paper_id in matched_ids
        return m

    registry.resolve_identity = MagicMock(side_effect=_resolve)
    if register_side_effect is not None:
        registry.register_paper = MagicMock(side_effect=register_side_effect)
    else:
        registry.register_paper = MagicMock()
    return registry


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_init_rejects_empty_providers() -> None:
    """Constructor must reject ``providers={}`` -- a misconfiguration
    would silently produce zero results every cycle.
    """
    with pytest.raises(ValueError, match="at least one provider"):
        MultiProviderMonitor(providers={}, registry=MagicMock())


def test_init_accepts_single_provider() -> None:
    """One provider is enough -- e.g., a deployment with only arXiv."""
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: _make_provider()},
        registry=MagicMock(),
    )
    assert monitor is not None


def test_init_defensive_copies_providers_dict() -> None:
    """Mutations to the caller's dict after construction must NOT
    affect the monitor's internal provider set.
    """
    caller_dict = {PaperSource.ARXIV: _make_provider()}
    monitor = MultiProviderMonitor(providers=caller_dict, registry=MagicMock())
    caller_dict[PaperSource.SEMANTIC_SCHOLAR] = _make_provider()
    # Internal dict was copied at construction; caller's mutation is invisible.
    assert PaperSource.SEMANTIC_SCHOLAR not in monitor._providers


def test_config_with_defaults_all_fields_set() -> None:
    """Smoke-test the config helper -- all knobs have sane defaults."""
    cfg = MultiProviderMonitorConfig.with_defaults()
    assert cfg.max_papers_per_cycle > 0
    assert cfg.max_query_variants > 0
    assert cfg.topic_slug_prefix == "monitor"


# ---------------------------------------------------------------------------
# Subscription gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_paused_subscription_short_circuits() -> None:
    """Paused subscriptions return SUCCESS without touching providers."""
    sub = _make_subscription(status=SubscriptionStatus.PAUSED)
    arxiv = _make_provider(return_papers=[_make_paper("p1")])
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
    )
    result = await monitor.check(sub)
    assert result.run.status is MonitoringRunStatus.SUCCESS
    assert result.run.papers_seen == 0
    arxiv.search.assert_not_called()


# ---------------------------------------------------------------------------
# Query expansion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_no_expander_uses_literal_query_only() -> None:
    """Without an expander, only the literal query is searched (cost-free)."""
    sub = _make_subscription(query="LLM agents")
    arxiv = _make_provider()
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
    )
    await monitor.check(sub)
    assert arxiv.search.await_count == 1
    # Verify the topic carried the literal query (the topic is the
    # first positional arg to provider.search).
    topic = arxiv.search.await_args.args[0]
    assert topic.query == "LLM agents"


@pytest.mark.asyncio
async def test_check_with_expander_searches_all_variants() -> None:
    """With an expander, each variant fans out to every provider."""
    sub = _make_subscription(query="original")
    expander = MagicMock()
    expander.expand = AsyncMock(return_value=["original", "variant1", "variant2"])
    arxiv = _make_provider()
    s2 = _make_provider()
    monitor = MultiProviderMonitor(
        providers={
            PaperSource.ARXIV: arxiv,
            PaperSource.SEMANTIC_SCHOLAR: s2,
        },
        registry=_make_registry(),
        query_expander=expander,
    )
    await monitor.check(sub)
    # 3 variants × 2 providers = 6 searches total
    assert arxiv.search.await_count == 3
    assert s2.search.await_count == 3


@pytest.mark.asyncio
async def test_check_expander_failure_falls_back_to_literal_query() -> None:
    """If expander.expand() raises, fall back to the literal query (Fail-Soft)."""
    sub = _make_subscription(query="LLM agents")
    expander = MagicMock()
    expander.expand = AsyncMock(side_effect=RuntimeError("LLM down"))
    arxiv = _make_provider()
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        query_expander=expander,
    )
    await monitor.check(sub)
    # Despite the expander failure, the cycle still searches the literal query.
    assert arxiv.search.await_count == 1
    assert arxiv.search.await_args.args[0].query == "LLM agents"


@pytest.mark.asyncio
async def test_check_expander_returns_empty_falls_back_to_literal() -> None:
    """If expander returns an empty list, fall back to literal query."""
    sub = _make_subscription(query="LLM agents")
    expander = MagicMock()
    expander.expand = AsyncMock(return_value=[])  # pathological case
    arxiv = _make_provider()
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        query_expander=expander,
    )
    await monitor.check(sub)
    assert arxiv.search.await_count == 1
    assert arxiv.search.await_args.args[0].query == "LLM agents"


# ---------------------------------------------------------------------------
# Provider fan-out + Fail-Soft Boundary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_one_provider_failure_does_not_abort_cycle() -> None:
    """A single provider raising must NOT abort the cycle (Fail-Soft).
    Status becomes PARTIAL and the surviving provider's papers land.
    """
    sub = _make_subscription()
    arxiv = _make_provider(return_papers=[_make_paper("arxiv-1")])
    s2 = _make_provider(raise_on_search=ConnectionError("S2 timeout"))
    monitor = MultiProviderMonitor(
        providers={
            PaperSource.ARXIV: arxiv,
            PaperSource.SEMANTIC_SCHOLAR: s2,
        },
        registry=_make_registry(),
    )
    result = await monitor.check(sub)
    assert result.run.status is MonitoringRunStatus.PARTIAL
    assert result.run.papers_seen == 1  # the arXiv result survived
    assert result.run.error is not None  # explained


@pytest.mark.asyncio
async def test_check_all_providers_succeed_returns_success_status() -> None:
    """If everything succeeds, status is SUCCESS (not PARTIAL)."""
    sub = _make_subscription()
    arxiv = _make_provider(return_papers=[_make_paper("p1")])
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
    )
    result = await monitor.check(sub)
    assert result.run.status is MonitoringRunStatus.SUCCESS
    assert result.run.error is None


# ---------------------------------------------------------------------------
# Deduplication + cap enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_dedups_papers_by_paper_id_across_providers() -> None:
    """If two providers return the same paper_id, it appears once."""
    sub = _make_subscription()
    shared = _make_paper("shared-id", title="Same paper, both providers")
    arxiv = _make_provider(return_papers=[shared])
    s2 = _make_provider(return_papers=[shared])
    monitor = MultiProviderMonitor(
        providers={
            PaperSource.ARXIV: arxiv,
            PaperSource.SEMANTIC_SCHOLAR: s2,
        },
        registry=_make_registry(),
    )
    result = await monitor.check(sub)
    # Only ONE paper despite both providers returning it.
    assert result.run.papers_seen == 1


@pytest.mark.asyncio
async def test_check_enforces_max_papers_per_cycle_cap() -> None:
    """The per-cycle cap clips overflow even if providers return more."""
    sub = _make_subscription()
    papers = [_make_paper(f"p{i}") for i in range(10)]
    arxiv = _make_provider(return_papers=papers)
    cfg = MultiProviderMonitorConfig(
        max_papers_per_cycle=3,
        max_query_variants=3,
        topic_slug_prefix="monitor",
    )
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        config=cfg,
    )
    result = await monitor.check(sub)
    assert result.run.papers_seen == 3


# ---------------------------------------------------------------------------
# Registry interaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_registers_new_papers_discovery_only() -> None:
    """New papers (not in registry) are registered with discovery_only=True."""
    sub = _make_subscription(subscription_id="sub-xyz")
    p = _make_paper("new-paper")
    arxiv = _make_provider(return_papers=[p])
    registry = _make_registry()  # no matched_ids → all new
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=registry,
    )
    result = await monitor.check(sub)
    assert result.run.papers_new == 1
    assert result.run.papers_deduplicated == 0
    registry.register_paper.assert_called_once()
    kwargs = registry.register_paper.call_args.kwargs
    assert kwargs["discovery_only"] is True
    assert kwargs["topic_slug"] == "monitor-sub-xyz"


@pytest.mark.asyncio
async def test_check_skips_papers_already_in_registry() -> None:
    """Papers already in the registry are tagged deduplicated, not re-registered."""
    sub = _make_subscription()
    p = _make_paper("known")
    arxiv = _make_provider(return_papers=[p])
    registry = _make_registry(matched_paper_ids={"known"})
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=registry,
    )
    result = await monitor.check(sub)
    assert result.run.papers_new == 0
    assert result.run.papers_deduplicated == 1
    registry.register_paper.assert_not_called()


@pytest.mark.asyncio
async def test_check_registry_write_error_marks_partial_and_continues() -> None:
    """If register_paper raises for one paper, status becomes PARTIAL but
    the cycle continues with the remaining papers (Fail-Soft).
    """
    sub = _make_subscription()
    p1 = _make_paper("p1")
    arxiv = _make_provider(return_papers=[p1])
    registry = _make_registry(register_side_effect=RuntimeError("disk full"))
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=registry,
    )
    result = await monitor.check(sub)
    assert result.run.status is MonitoringRunStatus.PARTIAL
    assert result.run.papers_new == 0  # the failed write was NOT counted as new


@pytest.mark.asyncio
async def test_check_identity_resolution_error_marks_partial_and_continues() -> None:
    """If resolve_identity raises for one paper, status becomes PARTIAL
    but the cycle continues -- the broken paper is skipped.
    """
    sub = _make_subscription()
    arxiv = _make_provider(return_papers=[_make_paper("p1")])
    registry = _make_registry(resolve_side_effect=RuntimeError("bad row"))
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=registry,
    )
    result = await monitor.check(sub)
    assert result.run.status is MonitoringRunStatus.PARTIAL
    assert result.run.papers_new == 0
    assert result.run.papers_deduplicated == 0


# ---------------------------------------------------------------------------
# MonitoringRunner.from_paths integration: monitor selection
# ---------------------------------------------------------------------------


def test_from_paths_with_no_extras_builds_arxiv_monitor(tmp_path) -> None:
    """Backward-compatible default: legacy ArxivMonitor when no extras
    and no expander are provided.
    """
    db_path = tmp_path / "monitoring.db"
    runner = MonitoringRunner.from_paths(
        db_path=db_path,
        registry=MagicMock(),
        arxiv_provider=MagicMock(),
    )
    assert isinstance(runner._monitor, ArxivMonitor)


def test_from_paths_with_extra_providers_builds_multi_provider_monitor(
    tmp_path,
) -> None:
    """When extra_providers is supplied, MultiProviderMonitor is selected."""
    db_path = tmp_path / "monitoring.db"
    extras = {PaperSource.SEMANTIC_SCHOLAR: _make_provider()}
    runner = MonitoringRunner.from_paths(
        db_path=db_path,
        registry=MagicMock(),
        arxiv_provider=MagicMock(),
        extra_providers=extras,
    )
    assert isinstance(runner._monitor, MultiProviderMonitor)
    # arXiv plus the one extra
    assert PaperSource.ARXIV in runner._monitor._providers
    assert PaperSource.SEMANTIC_SCHOLAR in runner._monitor._providers


def test_from_paths_with_only_query_expander_builds_multi_provider(
    tmp_path,
) -> None:
    """Even without extras, providing a query_expander promotes to
    MultiProviderMonitor (the LLM expansion is the upgrade signal).
    """
    db_path = tmp_path / "monitoring.db"
    runner = MonitoringRunner.from_paths(
        db_path=db_path,
        registry=MagicMock(),
        arxiv_provider=MagicMock(),
        query_expander=MagicMock(),
    )
    assert isinstance(runner._monitor, MultiProviderMonitor)


def test_from_paths_rejects_arxiv_in_extra_providers(tmp_path) -> None:
    """Caller must not pass arXiv via ``extra_providers`` -- the
    canonical arXiv provider goes through ``arxiv_provider`` to keep
    the wiring contract single-source.
    """
    db_path = tmp_path / "monitoring.db"
    with pytest.raises(ValueError, match="must not include PaperSource.ARXIV"):
        MonitoringRunner.from_paths(
            db_path=db_path,
            registry=MagicMock(),
            arxiv_provider=MagicMock(),
            extra_providers={PaperSource.ARXIV: _make_provider()},
        )

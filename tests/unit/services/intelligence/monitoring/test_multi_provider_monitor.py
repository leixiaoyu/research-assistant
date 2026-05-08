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
- (from_paths monitor-selection tests relocated to test_runner.py, H-M6)
- H-S1: expansion budget gate.
- H-S2: variant validation + rejection.
- H-S5: topic-build inside try/except.
- H-C5: expander failure → PARTIAL status.
- H-C6: empty-dict extra_providers builds MultiProviderMonitor.
- H-T1: capture_logs assertions on failure paths.
- H-T3: strong paper_id assertion.
- H-T5: register_paper.call_count assertion.
- H-T6: Pydantic strict-mode tests.
- L-2: exact default field values.

Note: ``ArxivMonitorResult`` is intentionally reused as the return DTO
so both monitors are duck-type compatible from the runner's POV.
"""

from __future__ import annotations

import structlog
import structlog.testing
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.paper import PaperMetadata
from src.services.intelligence.monitoring import multi_provider_monitor as mpm_module
from src.services.intelligence.monitoring.models import (
    MAX_PAPERS_PER_CYCLE,
    MonitoringRunStatus,
    PaperSource,
    ResearchSubscription,
    SubscriptionStatus,
)
from src.services.intelligence.monitoring.multi_provider_monitor import (
    MultiProviderMonitor,
    MultiProviderMonitorConfig,
    _DEFAULT_MAX_QUERY_VARIANTS,
)

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
    # H-T4: Assert specific structure instead of vacuous `is not None`
    assert PaperSource.ARXIV in monitor._providers
    assert len(monitor._providers) == 1


def test_init_defensive_copies_providers_dict() -> None:
    """Mutations to the caller's dict after construction must NOT
    affect the monitor's internal provider set.
    """
    caller_dict = {PaperSource.ARXIV: _make_provider()}
    monitor = MultiProviderMonitor(providers=caller_dict, registry=MagicMock())
    caller_dict[PaperSource.SEMANTIC_SCHOLAR] = _make_provider()
    # Internal dict was copied at construction; caller's mutation is invisible.
    assert PaperSource.SEMANTIC_SCHOLAR not in monitor._providers


def test_config_default_construction_all_fields_set() -> None:
    """Smoke-test default construction -- all knobs have sane defaults.
    L-1: with_defaults() dropped; MultiProviderMonitorConfig() is equivalent.
    L-2: pin exact default values so accidental changes trip the test.
    """
    cfg = MultiProviderMonitorConfig()
    assert cfg.max_papers_per_cycle == MAX_PAPERS_PER_CYCLE
    assert cfg.max_query_variants == _DEFAULT_MAX_QUERY_VARIANTS
    assert cfg.topic_slug_prefix == "monitor"


# ---------------------------------------------------------------------------
# Subscription gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_paused_subscription_short_circuits() -> None:
    """Paused subscriptions return SUCCESS without touching providers.
    H-M9: also assert new_papers == [] and deduplicated_papers == [].
    """
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
    # H-M9: verify empty paper lists for paused subscriptions
    assert result.new_papers == []
    assert result.deduplicated_papers == []


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
    """With an expander, each variant fans out to every allowlisted provider.

    The subscription has only PaperSource.ARXIV in sources (MVP default),
    so only the arXiv provider is searched for each of the 3 variants;
    the S2 provider is skipped by the H-S3 allowlist filter.
    """
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
    # 3 variants × 1 allowed provider (ARXIV) = 3 searches
    # expander was called with max_variants = config.max_query_variants (C-1 fix)
    assert arxiv.search.await_count == 3
    # S2 is not in subscription.sources → skipped by H-S3 filter
    assert s2.search.await_count == 0
    expander.expand.assert_awaited_once_with(
        "original", max_variants=monitor._config.max_query_variants
    )


@pytest.mark.asyncio
async def test_check_expander_failure_falls_back_to_literal_query() -> None:
    """If expander.expand() raises, fall back to the literal query (Fail-Soft).
    H-C5: expander failure sets run status to PARTIAL.
    """
    sub = _make_subscription(query="LLM agents")
    expander = MagicMock()
    expander.expand = AsyncMock(side_effect=RuntimeError("LLM down"))
    arxiv = _make_provider()
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        query_expander=expander,
    )
    result = await monitor.check(sub)
    # Despite the expander failure, the cycle still searches the literal query.
    assert arxiv.search.await_count == 1
    assert arxiv.search.await_args.args[0].query == "LLM agents"
    # H-C5: expander degradation marks the run PARTIAL.
    assert result.run.status is MonitoringRunStatus.PARTIAL


@pytest.mark.asyncio
async def test_check_expander_returns_empty_falls_back_to_literal() -> None:
    """If expander returns an empty list, fall back to literal query.
    H-C5: empty expansion is treated as degraded → PARTIAL.
    """
    sub = _make_subscription(query="LLM agents")
    expander = MagicMock()
    expander.expand = AsyncMock(return_value=[])  # pathological case
    arxiv = _make_provider()
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        query_expander=expander,
    )
    result = await monitor.check(sub)
    assert arxiv.search.await_count == 1
    assert arxiv.search.await_args.args[0].query == "LLM agents"
    # H-C5: empty result is degraded → PARTIAL.
    assert result.run.status is MonitoringRunStatus.PARTIAL


# ---------------------------------------------------------------------------
# H-S3: subscription.sources allowlist honored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_respects_subscription_sources_allowlist() -> None:
    """H-S3: Providers not in subscription.sources must not be searched.

    The MVP ResearchSubscription only allows PaperSource.ARXIV in sources.
    A multi-provider monitor configured with both ARXIV and S2 must only
    search ARXIV for subscriptions that only allow ARXIV.
    """
    sub = _make_subscription()  # sources=[PaperSource.ARXIV] by default
    assert sub.sources == [PaperSource.ARXIV]

    arxiv = _make_provider(return_papers=[_make_paper("p1")])
    s2 = _make_provider(return_papers=[_make_paper("p2")])
    monitor = MultiProviderMonitor(
        providers={
            PaperSource.ARXIV: arxiv,
            PaperSource.SEMANTIC_SCHOLAR: s2,
        },
        registry=_make_registry(),
    )
    result = await monitor.check(sub)

    # ARXIV is in sources → searched; S2 is not → skipped
    arxiv.search.assert_awaited_once()
    s2.search.assert_not_called()
    # Only the ARXIV paper landed
    assert result.run.papers_seen == 1


# ---------------------------------------------------------------------------
# Provider fan-out + Fail-Soft Boundary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_one_provider_failure_does_not_abort_cycle() -> None:
    """A single provider raising must NOT abort the cycle (Fail-Soft).
    Status becomes PARTIAL and the surviving provider's papers land.

    Since subscription.sources is [ARXIV] (MVP default), ARXIV is the only
    provider searched. We test fail-soft by having the ARXIV provider raise
    on one call in a multi-variant setup, so the second variant still proceeds.
    H-S3: S2 provider is skipped because it is not in subscription.sources.
    """
    sub = _make_subscription()
    # ARXIV raises on first call, returns papers on second
    call_count = [0]

    async def arxiv_search(topic):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ConnectionError("arxiv timeout on first variant")
        return [_make_paper("arxiv-1")]

    arxiv = MagicMock()
    arxiv.search = AsyncMock(side_effect=arxiv_search)
    expander = MagicMock()
    expander.expand = AsyncMock(return_value=["original", "variant2"])
    monitor = MultiProviderMonitor(
        providers={
            PaperSource.ARXIV: arxiv,
        },
        registry=_make_registry(),
        query_expander=expander,
    )
    result = await monitor.check(sub)
    assert result.run.status is MonitoringRunStatus.PARTIAL
    assert result.run.papers_seen == 1  # the second-variant arXiv result survived
    assert result.run.error is not None  # explained
    # H-T3: assert that the paper_id from the surviving call is present
    assert result.new_papers[0].paper_id == "arxiv-1"


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
async def test_check_dedups_same_paper_from_two_query_variants() -> None:
    """If two query variants return the same paper_id (via the same provider),
    it appears only once in the final result set (exercises the dedup continue branch).
    """
    sub = _make_subscription(query="original")
    shared = _make_paper("shared-id", title="Same paper, two variants")
    expander = MagicMock()
    expander.expand = AsyncMock(return_value=["original", "variant1"])
    # Return the same paper for both queries.
    arxiv = _make_provider(return_papers=[shared])
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        query_expander=expander,
    )
    result = await monitor.check(sub)
    # 2 queries × 1 provider = 2 search calls, each returning the same paper.
    assert arxiv.search.await_count == 2
    # Dedup yields only 1 unique paper.
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
    registry = _make_registry()
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=registry,
        config=cfg,
    )
    result = await monitor.check(sub)
    assert result.run.papers_seen == 3
    # H-T5: exactly 3 papers registered (cap enforced before registry calls)
    assert registry.register_paper.call_count == 3


@pytest.mark.asyncio
async def test_check_cap_applied_emits_log(monkeypatch) -> None:
    """L-3: monitor_per_cycle_cap_applied is logged when the cap clips results."""
    sub = _make_subscription()
    papers = [_make_paper(f"p{i}") for i in range(5)]
    arxiv = _make_provider(return_papers=papers)
    cfg = MultiProviderMonitorConfig(
        max_papers_per_cycle=2,
        max_query_variants=3,
        topic_slug_prefix="monitor",
    )
    monkeypatch.setattr(mpm_module, "logger", structlog.get_logger())
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        config=cfg,
    )
    with structlog.testing.capture_logs() as logs:
        result = await monitor.check(sub)
    cap_events = [e for e in logs if e.get("event") == "monitor_per_cycle_cap_applied"]
    assert len(cap_events) == 1
    assert cap_events[0]["papers_before_cap"] == 5
    assert cap_events[0]["cap"] == 2
    assert result.run.papers_seen == 2


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


# (from_paths monitor-selection tests have been relocated to test_runner.py
#  under TestFromPathsFactory — see H-M6)


# ---------------------------------------------------------------------------
# H-T1: capture_logs assertions on failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_query_expansion_failed_emits_log(monkeypatch) -> None:
    """H-T1: monitor_query_expansion_failed is emitted when expander raises."""
    sub = _make_subscription(query="LLM agents")
    expander = MagicMock()
    expander.expand = AsyncMock(side_effect=RuntimeError("LLM down"))
    arxiv = _make_provider()
    monkeypatch.setattr(mpm_module, "logger", structlog.get_logger())
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        query_expander=expander,
    )
    with structlog.testing.capture_logs() as logs:
        await monitor.check(sub)
    events = [e for e in logs if e.get("event") == "monitor_query_expansion_failed"]
    assert len(events) == 1
    assert events[0].get("subscription_id") == sub.subscription_id


@pytest.mark.asyncio
async def test_check_provider_search_failed_emits_log(monkeypatch) -> None:
    """H-T1: monitor_provider_search_failed is emitted on provider error."""
    sub = _make_subscription()
    arxiv = _make_provider(raise_on_search=ConnectionError("timeout"))
    monkeypatch.setattr(mpm_module, "logger", structlog.get_logger())
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
    )
    with structlog.testing.capture_logs() as logs:
        result = await monitor.check(sub)
    events = [e for e in logs if e.get("event") == "monitor_provider_search_failed"]
    assert len(events) == 1
    assert result.run.status is MonitoringRunStatus.PARTIAL


@pytest.mark.asyncio
async def test_check_identity_resolution_error_emits_log(monkeypatch) -> None:
    """H-T1: monitor_identity_resolution_error is emitted on resolve failure."""
    sub = _make_subscription()
    arxiv = _make_provider(return_papers=[_make_paper("p1")])
    registry = _make_registry(resolve_side_effect=RuntimeError("bad row"))
    monkeypatch.setattr(mpm_module, "logger", structlog.get_logger())
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=registry,
    )
    with structlog.testing.capture_logs() as logs:
        await monitor.check(sub)
    events = [e for e in logs if e.get("event") == "monitor_identity_resolution_error"]
    assert len(events) == 1
    assert events[0].get("paper_id") == "p1"
    # H-4: source field must be present so a future drop of source= is caught.
    assert events[0].get("source") == PaperSource.ARXIV.value


@pytest.mark.asyncio
async def test_check_registry_write_error_emits_log(monkeypatch) -> None:
    """H-T1: monitor_registry_write_error is emitted on register_paper failure."""
    sub = _make_subscription()
    arxiv = _make_provider(return_papers=[_make_paper("p1")])
    registry = _make_registry(register_side_effect=RuntimeError("disk full"))
    monkeypatch.setattr(mpm_module, "logger", structlog.get_logger())
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=registry,
    )
    with structlog.testing.capture_logs() as logs:
        await monitor.check(sub)
    events = [e for e in logs if e.get("event") == "monitor_registry_write_error"]
    assert len(events) == 1
    assert events[0].get("paper_id") == "p1"
    # H-4: source field must be present so a future drop of source= is caught.
    assert events[0].get("source") == PaperSource.ARXIV.value


# ---------------------------------------------------------------------------
# H-S1: LLM budget gate for query expansion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_expansion_skipped_when_budget_exhausted(monkeypatch) -> None:
    """H-S1: When llm_calls_used[0] >= max_calls, the expander is not called
    and monitor_expansion_budget_exhausted is logged.
    """
    sub = _make_subscription(query="agents")
    expander = MagicMock()
    expander.expand = AsyncMock(return_value=["agents", "variant"])
    arxiv = _make_provider()
    monkeypatch.setattr(mpm_module, "logger", structlog.get_logger())
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        query_expander=expander,
    )
    llm_calls_used = [5]  # already at limit
    with structlog.testing.capture_logs() as logs:
        result = await monitor.check(sub, llm_calls_used=llm_calls_used, max_calls=5)
    # Expander must NOT have been called.
    expander.expand.assert_not_awaited()
    # Should fall back to literal query (1 search).
    assert arxiv.search.await_count == 1
    # Status is PARTIAL due to budget degradation.
    assert result.run.status is MonitoringRunStatus.PARTIAL
    budget_events = [
        e for e in logs if e.get("event") == "monitor_expansion_budget_exhausted"
    ]
    assert len(budget_events) == 1


@pytest.mark.asyncio
async def test_check_expansion_increments_budget_counter_on_success() -> None:
    """H-S1: Successful expander call increments llm_calls_used by 1."""
    sub = _make_subscription(query="agents")
    expander = MagicMock()
    expander.expand = AsyncMock(return_value=["agents", "variant"])
    arxiv = _make_provider()
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        query_expander=expander,
    )
    llm_calls_used = [0]
    await monitor.check(sub, llm_calls_used=llm_calls_used, max_calls=100)
    # Counter incremented by 1 for the expansion call.
    assert llm_calls_used[0] == 1


# ---------------------------------------------------------------------------
# H-S2: variant validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_variant_with_injection_chars_is_rejected(monkeypatch) -> None:
    """H-S2: A variant containing injection-risk characters is dropped and
    monitor_expansion_variant_rejected is logged. The cycle continues with
    the valid variants.
    """
    sub = _make_subscription(query="agents")
    expander = MagicMock()
    # First variant is valid, second contains shell injection.
    expander.expand = AsyncMock(return_value=["agents", "agents && rm -rf /"])
    arxiv = _make_provider()
    monkeypatch.setattr(mpm_module, "logger", structlog.get_logger())
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        query_expander=expander,
    )
    with structlog.testing.capture_logs() as logs:
        result = await monitor.check(sub)

    # Only valid variant searched.
    assert arxiv.search.await_count == 1
    topic = arxiv.search.await_args.args[0]
    assert topic.query == "agents"
    # Rejection logged for the bad variant.
    reject_events = [
        e for e in logs if e.get("event") == "monitor_expansion_variant_rejected"
    ]
    assert len(reject_events) == 1
    # Cycle must succeed with the valid variant.
    assert result.run.status is MonitoringRunStatus.SUCCESS


@pytest.mark.asyncio
async def test_check_all_variants_rejected_falls_back_to_literal(monkeypatch) -> None:
    """H-S2: If ALL expanded variants fail validation, the literal query is
    used and the run is marked PARTIAL.
    """
    sub = _make_subscription(query="agents")
    expander = MagicMock()
    # All variants contain injection chars.
    expander.expand = AsyncMock(
        return_value=["agents && rm /", "agents | cat /etc/passwd"]
    )
    arxiv = _make_provider()
    monkeypatch.setattr(mpm_module, "logger", structlog.get_logger())
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        query_expander=expander,
    )
    with structlog.testing.capture_logs() as logs:
        result = await monitor.check(sub)

    # Fall back to literal query.
    assert arxiv.search.await_count == 1
    assert arxiv.search.await_args.args[0].query == "agents"
    # Both variants should have been rejected.
    reject_events = [
        e for e in logs if e.get("event") == "monitor_expansion_variant_rejected"
    ]
    assert len(reject_events) == 2
    # All rejected → degraded → PARTIAL.
    assert result.run.status is MonitoringRunStatus.PARTIAL


# ---------------------------------------------------------------------------
# H-S5: topic build inside per-provider try/except
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_topic_build_failure_treated_as_provider_failure() -> None:
    """H-S5: If _build_topic_for_query raises (e.g., because ResearchTopic
    validation fails on a bad variant), the cycle continues for other variants
    and the run is marked PARTIAL — it does NOT kill the whole subscription.

    We simulate the scenario by patching _build_topic_for_query to raise on
    the first call, then succeed on the second.
    """
    sub = _make_subscription(query="agents")
    expander = MagicMock()
    expander.expand = AsyncMock(return_value=["bad-variant", "good-variant"])
    arxiv = _make_provider(return_papers=[_make_paper("p1")])
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
        query_expander=expander,
    )

    call_count = [0]
    original_build = monitor._build_topic_for_query

    def flaky_build(subscription, variant, *, time_window=None):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ValueError("Bad ResearchTopic variant")
        return original_build(subscription, variant, time_window=time_window)

    monitor._build_topic_for_query = flaky_build  # type: ignore[method-assign]

    result = await monitor.check(sub)
    # Second variant still searched (fail-soft).
    assert arxiv.search.await_count == 1
    # Failure from topic build → partial.
    assert result.run.status is MonitoringRunStatus.PARTIAL


# ---------------------------------------------------------------------------
# H-M10: 2-paper test for registry failure continues for the other paper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_registry_write_error_continues_for_second_paper() -> None:
    """H-M10: When register_paper raises for the first paper, the cycle
    continues to process the second paper (2-paper variant of the single-paper
    test).
    """
    sub = _make_subscription()
    p1 = _make_paper("p1")
    p2 = _make_paper("p2")
    arxiv = _make_provider(return_papers=[p1, p2])

    call_count = [0]

    def selective_fail(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("disk full on first paper")
        # Second call succeeds (no return value needed for register_paper).

    registry = _make_registry()
    registry.register_paper = MagicMock(side_effect=selective_fail)

    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=registry,
    )
    result = await monitor.check(sub)
    assert result.run.status is MonitoringRunStatus.PARTIAL
    # First paper failed registry write → not in new_papers.
    # Second paper succeeded → in new_papers.
    assert result.run.papers_new == 1
    assert result.new_papers[0].paper_id == "p2"


# ---------------------------------------------------------------------------
# H-T6: Pydantic strict-mode tests for MultiProviderMonitorConfig
# ---------------------------------------------------------------------------


def test_config_rejects_extra_fields() -> None:
    """H-T6: extra='forbid' must reject unknown fields."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="Extra inputs"):
        MultiProviderMonitorConfig(unknown_field="oops")  # type: ignore[call-arg]


def test_config_rejects_non_int_strict_mode() -> None:
    """H-T6: strict=True must reject float where int is expected."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        MultiProviderMonitorConfig(max_papers_per_cycle=1.5)  # type: ignore[arg-type]


def test_config_rejects_negative_max_papers_per_cycle() -> None:
    """H-T6: ge=1 rejects zero or negative max_papers_per_cycle."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="greater than or equal"):
        MultiProviderMonitorConfig(max_papers_per_cycle=0)


def test_config_rejects_max_query_variants_below_one() -> None:
    """H-T6: ge=1 rejects zero or negative max_query_variants."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="greater than or equal"):
        MultiProviderMonitorConfig(max_query_variants=0)


def test_config_rejects_max_papers_above_cap() -> None:
    """H-T6: le=MAX_PAPERS_PER_CYCLE rejects values above the project cap."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="less than or equal"):
        MultiProviderMonitorConfig(max_papers_per_cycle=MAX_PAPERS_PER_CYCLE + 1)


def test_config_rejects_max_query_variants_above_ten() -> None:
    """H-T6: le=10 rejects max_query_variants above 10."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="less than or equal"):
        MultiProviderMonitorConfig(max_query_variants=11)


# ---------------------------------------------------------------------------
# H-C4: build_tier1_extras unit tests
# ---------------------------------------------------------------------------


def test_build_tier1_extras_returns_none_when_no_llm() -> None:
    """H-C4: build_tier1_extras returns (None, None) when llm_service is None."""
    from src.services.intelligence.monitoring._tier1_factory import build_tier1_extras

    extra_providers, query_expander = build_tier1_extras(None)
    assert extra_providers is None
    assert query_expander is None


def test_build_tier1_extras_returns_none_when_provider_construction_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2/H-C4: If a provider constructor raises, build_tier1_extras catches
    the exception, logs monitor_tier1_init_failed, and returns (None, None).

    Patches OpenAlexProvider (a *dependency* of build_tier1_extras, not the
    function under test) so the production code path is actually executed.
    """
    import structlog
    import structlog.testing

    import src.services.intelligence.monitoring._tier1_factory as factory_module
    from src.services.intelligence.monitoring._tier1_factory import build_tier1_extras

    monkeypatch.setattr(factory_module, "logger", structlog.get_logger())
    monkeypatch.setattr(
        "src.services.providers.openalex.OpenAlexProvider",
        MagicMock(side_effect=RuntimeError("network unreachable")),
    )

    with structlog.testing.capture_logs() as logs:
        extra_providers, query_expander = build_tier1_extras(MagicMock())

    assert extra_providers is None
    assert query_expander is None

    failed_events = [e for e in logs if e.get("event") == "monitor_tier1_init_failed"]
    assert len(failed_events) == 1
    assert "network unreachable" in failed_events[0].get("error", "")


def test_build_tier1_extras_happy_path_returns_providers_and_expander(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2/H-C4: When all providers construct successfully, build_tier1_extras
    returns a non-None providers dict and a QueryExpander.

    Patches OpenAlexProvider, HuggingFaceProvider, and QueryExpander so
    the real try-block (lines 60-79) is exercised without network I/O.
    SEMANTIC_SCHOLAR_API_KEY is unset so the optional S2 branch is skipped.
    """
    from src.services.intelligence.monitoring._tier1_factory import build_tier1_extras
    from src.services.intelligence.monitoring.models import PaperSource

    fake_openalex = MagicMock()
    fake_hf = MagicMock()
    fake_expander = MagicMock()

    monkeypatch.setattr(
        "src.services.providers.openalex.OpenAlexProvider",
        MagicMock(return_value=fake_openalex),
    )
    monkeypatch.setattr(
        "src.services.providers.huggingface.HuggingFaceProvider",
        MagicMock(return_value=fake_hf),
    )
    monkeypatch.setattr(
        "src.utils.query_expander.QueryExpander",
        MagicMock(return_value=fake_expander),
    )
    # Ensure no S2 key is present for this test.
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)

    extra_providers, query_expander = build_tier1_extras(MagicMock())

    assert extra_providers is not None
    assert PaperSource.OPENALEX in extra_providers
    assert PaperSource.HUGGINGFACE in extra_providers
    assert PaperSource.SEMANTIC_SCHOLAR not in extra_providers
    assert query_expander is fake_expander


def test_build_tier1_extras_includes_semantic_scholar_when_api_key_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2/H-C4: When SEMANTIC_SCHOLAR_API_KEY is set, SemanticScholarProvider
    is included in the returned providers dict (line 73 branch).
    """
    from src.services.intelligence.monitoring._tier1_factory import build_tier1_extras
    from src.services.intelligence.monitoring.models import PaperSource

    fake_s2 = MagicMock()

    monkeypatch.setattr(
        "src.services.providers.openalex.OpenAlexProvider",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        "src.services.providers.huggingface.HuggingFaceProvider",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        "src.services.providers.semantic_scholar.SemanticScholarProvider",
        MagicMock(return_value=fake_s2),
    )
    monkeypatch.setattr(
        "src.utils.query_expander.QueryExpander",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "test-key-123")

    extra_providers, _ = build_tier1_extras(MagicMock())

    assert extra_providers is not None
    assert PaperSource.SEMANTIC_SCHOLAR in extra_providers


# ---------------------------------------------------------------------------
# Issue #141: per-paper source provenance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_records_actual_source_per_paper() -> None:
    """Issue #141: ``MonitoringRun.papers`` carries the actual provider per paper.

    The MVP subscription only allows ARXIV in ``sources``, so all papers
    in this single-provider scenario must come back stamped
    ``source=PaperSource.ARXIV`` -- never the silent default the V5
    column would have given them.
    """
    sub = _make_subscription()
    arxiv = _make_provider(return_papers=[_make_paper("p1")])
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(),
    )
    result = await monitor.check(sub)
    assert result.run.papers_seen == 1
    assert result.run.papers[0].source is PaperSource.ARXIV


@pytest.mark.asyncio
async def test_check_records_per_paper_source_for_each_provider() -> None:
    """Issue #141: when a subscription allows multiple providers, each
    paper's source field reflects the provider it actually came from --
    NOT a hardcoded ``PaperSource.ARXIV`` (the lie #141 is fixing).

    Subscription is constructed with ``sources=[ARXIV, OPENALEX, ...]``
    bypassing the model-level allowlist via ``object.__setattr__`` so
    this test focuses on the monitor's per-paper source threading
    rather than the (separately-tested) model validator.
    """
    arxiv_paper = _make_paper("arxiv-paper-1", title="ArXiv paper")
    openalex_paper = _make_paper("oa-paper-1", title="OpenAlex paper")
    s2_paper = _make_paper("s2-paper-1", title="S2 paper")
    hf_paper = _make_paper("hf-paper-1", title="HF paper")

    arxiv = _make_provider(return_papers=[arxiv_paper])
    openalex = _make_provider(return_papers=[openalex_paper])
    s2 = _make_provider(return_papers=[s2_paper])
    hf = _make_provider(return_papers=[hf_paper])

    sub_base = _make_subscription()
    # Bypass the model validator (which restricts MVP subscriptions to
    # ARXIV-only) so we can exercise the multi-provider paper-tracking
    # code path. This is exactly the path Tier 1 production builds will
    # hit once the subscription validator is widened in a follow-up.
    # Use model_construct (the Pydantic API for validation-free construction)
    # rather than object.__setattr__ to avoid coupling to Pydantic internals.
    sub = ResearchSubscription.model_construct(
        **{
            **sub_base.model_dump(),
            "sources": [
                PaperSource.ARXIV,
                PaperSource.OPENALEX,
                PaperSource.SEMANTIC_SCHOLAR,
                PaperSource.HUGGINGFACE,
            ],
        }
    )

    monitor = MultiProviderMonitor(
        providers={
            PaperSource.ARXIV: arxiv,
            PaperSource.OPENALEX: openalex,
            PaperSource.SEMANTIC_SCHOLAR: s2,
            PaperSource.HUGGINGFACE: hf,
        },
        registry=_make_registry(),
    )
    result = await monitor.check(sub)

    # Index the audit rows by paper_id for an unambiguous mapping
    # assertion.
    by_id = {p.paper_id: p for p in result.run.papers}
    assert by_id["arxiv-paper-1"].source is PaperSource.ARXIV
    assert by_id["oa-paper-1"].source is PaperSource.OPENALEX
    assert by_id["s2-paper-1"].source is PaperSource.SEMANTIC_SCHOLAR
    assert by_id["hf-paper-1"].source is PaperSource.HUGGINGFACE


@pytest.mark.asyncio
async def test_check_dedup_preserves_first_seen_source() -> None:
    """When two providers return the same paper, the first-seen source wins.

    Iteration order over the providers dict is insertion order in
    Python 3.7+, so ``ARXIV`` (inserted first) is the source of the
    deduplicated row -- not OPENALEX which came second.
    """
    shared = _make_paper("shared-paper")
    arxiv = _make_provider(return_papers=[shared])
    openalex = _make_provider(return_papers=[shared])

    sub_base = _make_subscription()
    # Use model_construct to bypass the ARXIV-only validator (Pydantic API
    # rather than object.__setattr__ to avoid coupling to internals).
    sub = ResearchSubscription.model_construct(
        **{
            **sub_base.model_dump(),
            "sources": [PaperSource.ARXIV, PaperSource.OPENALEX],
        }
    )

    monitor = MultiProviderMonitor(
        providers={
            PaperSource.ARXIV: arxiv,
            PaperSource.OPENALEX: openalex,
        },
        registry=_make_registry(),
    )
    result = await monitor.check(sub)

    assert result.run.papers_seen == 1
    # First-seen wins; arXiv was iterated first.
    assert result.run.papers[0].source is PaperSource.ARXIV


@pytest.mark.asyncio
async def test_check_records_source_for_deduplicated_papers() -> None:
    """Even papers known to the registry (deduplicated) must carry their
    provider source on the audit row -- not just freshly-registered ones.
    """
    sub = _make_subscription()
    known = _make_paper("known-paper")
    arxiv = _make_provider(return_papers=[known])
    monitor = MultiProviderMonitor(
        providers={PaperSource.ARXIV: arxiv},
        registry=_make_registry(matched_paper_ids={"known-paper"}),
    )
    result = await monitor.check(sub)
    assert result.run.papers_deduplicated == 1
    assert result.run.papers[0].source is PaperSource.ARXIV
    assert result.run.papers[0].is_new is False

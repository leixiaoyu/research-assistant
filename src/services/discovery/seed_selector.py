"""Citation seed selection for Phase 9.5 REQ-9.5.2.1 (PR β).

Phase 7.2's `_discover_deep` originally seeded citation exploration with
``all_papers[:10]`` — the top 10 papers from the current run's provider
queries, ordered by aggregator preference. The Phase 9.5 spec wants
something more precise: papers extracted in the last 7 days for the
current topic with ``quality_score >= 0.7``, capped at 10 (highest
quality first). That cohort is more likely to be high-signal seeds and
less likely to drag the citation walk into unrelated noise.

This module provides :func:`select_citation_seeds`, which returns the
spec-defined cohort. When the cohort is empty (e.g. cold registry,
first-week-after-merge, or no qualified papers), callers should fall
back to the legacy ``all_papers[:10]`` behavior — the function returns
an empty list rather than raising, so the fallback is structural, not
exceptional.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Optional

import structlog

from src.models.paper import PaperMetadata

if TYPE_CHECKING:
    from src.services.registry.service import RegistryService

logger = structlog.get_logger()


# Phase 9.5 REQ-9.5.2.1 (PR β): defaults centralised here so callers
# don't drift. Quality threshold is on the 0–100 scale per the
# canonical PaperMetadata.quality_score field (NOT the 0.0–1.0 scale
# the spec prose uses — we read the as-built field, not the spec
# prose).
DEFAULT_QUALITY_THRESHOLD: float = 70.0  # spec's "0.7" on 0–100 scale
DEFAULT_LOOKBACK_DAYS: int = 7
DEFAULT_MAX_SEEDS: int = 10


@dataclass(frozen=True)
class SeedSelectionConfig:
    """Knobs for :func:`select_citation_seeds`.

    Defaults match the Phase 9.5 spec; callers override only when a
    specific run / test wants a different cohort definition.
    """

    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    max_seeds: int = DEFAULT_MAX_SEEDS


def select_citation_seeds(
    topic_slug: str,
    registry_service: "RegistryService",
    *,
    now: Optional[datetime] = None,
    config: Optional[SeedSelectionConfig] = None,
) -> List[PaperMetadata]:
    """Return the recent quality-cohort of citation seeds for a topic.

    Algorithm (Phase 9.5 REQ-9.5.2.1):

    1. Look up registry entries for ``topic_slug`` with
       ``processed_at`` within the last ``lookback_days`` days.
    2. Keep entries whose ``metadata_snapshot["quality_score"]`` is
       ``>= quality_threshold``.
    3. Sort by quality_score descending and cap at ``max_seeds``.
    4. Reconstruct ``PaperMetadata`` from each entry's snapshot.

    Returns an empty list when:

    - The registry has no recent entries for the topic (cold-start case).
    - No recent entries clear the quality threshold.
    - Snapshot reconstruction fails for every candidate.

    Callers MUST handle the empty-list case by falling back to their
    pre-9.5 seeding behavior so this function is non-regressive on
    cold caches.

    Args:
        topic_slug: Topic identifier (matches
            ``RegistryEntry.topic_affiliations``).
        registry_service: Initialized RegistryService.
        now: Override for "current time" (test-only). Defaults to
            ``datetime.now(timezone.utc)``.
        config: Cohort knobs. Defaults to spec values.

    Returns:
        Up to ``config.max_seeds`` PaperMetadata seeds, highest quality
        first. Empty list signals "no cohort available".
    """
    cfg = config or SeedSelectionConfig()
    current_time = now if now is not None else datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=cfg.lookback_days)

    entries = registry_service.get_recent_entries_for_topic(topic_slug, since=cutoff)
    if not entries:
        logger.info(
            "citation_seeds_empty_cohort",
            topic=topic_slug,
            reason="no_recent_entries",
            lookback_days=cfg.lookback_days,
        )
        return []

    # Pull (entry, quality_score) pairs, dropping anything below threshold
    # or missing the score field. The metadata_snapshot is a plain dict
    # written by RegistryService at registration time; quality_score is
    # populated by the FilterService's quality_intelligence pipeline,
    # so it should always be present when filtering ran. Defensive
    # fallback to 0.0 for older snapshots ensures we don't crash.
    qualified: List[tuple[float, dict]] = []
    for entry in entries:
        snapshot = entry.metadata_snapshot or {}
        score = snapshot.get("quality_score", 0.0)
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            continue
        if score_f >= cfg.quality_threshold:
            qualified.append((score_f, snapshot))

    if not qualified:
        logger.info(
            "citation_seeds_empty_cohort",
            topic=topic_slug,
            reason="no_qualified_entries",
            entries_examined=len(entries),
            quality_threshold=cfg.quality_threshold,
        )
        return []

    qualified.sort(key=lambda pair: pair[0], reverse=True)
    capped = qualified[: cfg.max_seeds]

    # Reconstruct PaperMetadata. Pydantic validation may fail on stale
    # snapshots written by older versions of the model; skip the bad
    # ones rather than crash the discovery phase.
    seeds: List[PaperMetadata] = []
    for _, snapshot in capped:
        try:
            seeds.append(PaperMetadata(**snapshot))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "citation_seed_snapshot_invalid",
                topic=topic_slug,
                error=type(exc).__name__,
            )

    logger.info(
        "citation_seeds_selected",
        topic=topic_slug,
        cohort_size=len(entries),
        qualified=len(qualified),
        seeds_returned=len(seeds),
        quality_threshold=cfg.quality_threshold,
        lookback_days=cfg.lookback_days,
    )
    return seeds

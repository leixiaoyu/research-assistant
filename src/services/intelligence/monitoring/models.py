"""Pydantic V2 strict models for the monitoring milestone (REQ-9.1.1).

These models describe the persistent data plane:

- ``ResearchSubscription``: a user's standing query, persisted in the
  ``subscriptions`` SQLite table created by Milestone 9.0's migrations.
- ``MonitoringRun`` / ``MonitoringRunStatus``: an audit record for a
  single execution of the monitor (subscription + cycle).
- ``MonitoringPaperRecord``: per-paper outcome of a monitoring cycle
  (matched / deduped / scored placeholder for Week 2).

All models use ``ConfigDict(extra="forbid")`` for Pydantic V2 strictness.
``@field_validator(..., mode=...)`` is decorated with ``@classmethod`` per
project convention and Pydantic V2's requirement.

Subscription limits (REQ-9.1, decided in ``.omc/plans/open-questions.md``):

- 50 subscriptions per ``user_id``
- 100 keywords per subscription
- 1000 papers checked per monitoring cycle

These limits are enforced at write time by ``SubscriptionManager``;
``MAX_KEYWORDS_PER_SUBSCRIPTION`` is also enforced at model-validation
time so a malformed in-memory construction fails fast without touching
the database.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.services.intelligence.models.monitoring import (
    PaperSource,
    SubscriptionLimitError,
)

# Limits from open-questions.md decision (2026-04-24). Kept on the model
# so the ``SubscriptionManager`` and any future REST/CLI surface use a
# single source of truth.
MAX_KEYWORDS_PER_SUBSCRIPTION = 100
MAX_EXCLUDE_KEYWORDS_PER_SUBSCRIPTION = 100
MAX_PAPERS_PER_CYCLE = 1000

# H-C2: Maximum lookback window (hours) for the TimeframeRecent model.
# ArxivProvider validates the string at construction time so we cap here.
# Both ArxivMonitor and MultiProviderMonitor import this instead of each
# defining a local ``_MAX_POLL_HOURS = 720`` copy.
MAX_POLL_HOURS = 720

# Subscription name pattern: same character class as the rest of the
# Phase 9 surface (matches ``ENTITY_NAME_PATTERN`` extended with
# underscore so existing user_id slugs keep working).
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 ._\-()]+$")
_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._\-]+$")
_KEYWORD_PATTERN = re.compile(r"^[A-Za-z0-9 ._\-+:/()]+$")

# Shared identifier/slug pattern: safe for filesystem names and SQL column
# values. Exported so ``digest_generator`` can import it rather than
# duplicating the definition (H-C2 DRY).
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._\-]+$")


class SubscriptionStatus(str, Enum):
    """Lifecycle state of a research subscription.

    ``ACTIVE`` subscriptions are picked up by the monitor on every cycle.
    ``PAUSED`` ones are persisted but skipped — useful when a user wants
    to keep the configuration around without it generating digests.
    """

    ACTIVE = "active"
    PAUSED = "paused"


class MonitoringRunStatus(str, Enum):
    """Final status of a single ``MonitoringRun``.

    ``PARTIAL`` covers the case where some papers were processed before
    a failure (e.g. ArXiv returned valid papers, then the registry write
    failed). The ``error`` field on the run captures the cause.
    """

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class ResearchSubscription(BaseModel):
    """A user-managed standing query (REQ-9.1.1).

    Persisted to the ``subscriptions`` table as JSON in the ``config``
    column. The ``subscription_id``, ``user_id``, ``name``, and lifecycle
    columns are stored as first-class columns so the monitor can filter
    without parsing JSON for every row.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "subscription_id": "sub-7c1f4e3a",
                "user_id": "default",
                "name": "PEFT Research",
                "query": "LoRA OR QLoRA OR adapter tuning",
                "keywords": ["parameter-efficient", "fine-tuning"],
                "exclude_keywords": ["survey"],
                "min_relevance_score": 0.7,
                "sources": ["arxiv"],
                "poll_interval_hours": 6,
                "status": "active",
            }
        },
    )

    subscription_id: str = Field(
        default_factory=lambda: f"sub-{uuid.uuid4().hex[:12]}",
        min_length=1,
        max_length=64,
        description="Unique subscription identifier (system-generated).",
    )
    user_id: str = Field(
        default="default",
        min_length=1,
        max_length=64,
        description="Owner identifier (Phase 10+ multi-user).",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Human-readable subscription name.",
    )
    query: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Base search query passed through to the provider.",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Additional keywords to bias scoring/filtering.",
    )
    exclude_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords whose presence excludes a paper.",
    )
    min_relevance_score: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Threshold below which papers are discarded in Week 2.",
    )
    sources: list[PaperSource] = Field(
        default_factory=lambda: [PaperSource.ARXIV],
        min_length=1,
        description="Sources to poll. MVP enforces ArXiv-only.",
    )
    poll_interval_hours: int = Field(
        default=6,
        ge=1,
        le=24 * 7,
        description="Frequency of monitoring cycles (1h .. 168h).",
    )
    filters: dict[str, str] = Field(
        default_factory=dict,
        description="Optional provider-specific filters (e.g. arxiv categories).",
    )
    status: SubscriptionStatus = Field(
        default=SubscriptionStatus.ACTIVE,
        description="Lifecycle state.",
    )
    last_checked_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of the most recent successful cycle.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Subscription creation timestamp.",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last mutation timestamp.",
    )

    @field_validator("subscription_id", "user_id")
    @classmethod
    def _validate_identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Identifier cannot be empty")
        if not _USER_ID_PATTERN.match(v):
            raise ValueError(
                f"Invalid identifier format: {v!r}. "
                "Allowed: alphanumeric, periods, underscores, hyphens."
            )
        return v

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Subscription name cannot be empty")
        if not _NAME_PATTERN.match(v):
            raise ValueError(
                f"Invalid subscription name: {v!r}. "
                "Allowed: alphanumeric, spaces, dot, underscore, hyphen, parens."
            )
        return v

    @field_validator("query")
    @classmethod
    def _validate_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Subscription query cannot be empty")
        return v

    @field_validator("keywords", "exclude_keywords")
    @classmethod
    def _validate_keywords(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_KEYWORDS_PER_SUBSCRIPTION:
            # Raise the project-wide subscription limit error rather than a
            # generic ValueError so callers can render a uniform message.
            raise SubscriptionLimitError(
                "keywords per subscription",
                len(v),
                MAX_KEYWORDS_PER_SUBSCRIPTION,
            )
        cleaned: list[str] = []
        seen: set[str] = set()
        cumulative_len = 0
        for kw in v:
            kw_stripped = kw.strip()
            if not kw_stripped:
                raise ValueError("Keywords cannot be empty strings")
            # H-S2: Cap individual keyword length to prevent DoS via enormous
            # keywords that bloat the LLM prompt.
            if len(kw_stripped) > 200:
                raise ValueError(
                    f"Keyword too long ({len(kw_stripped)} chars): "
                    f"{kw_stripped[:40]!r}... "
                    "Maximum 200 characters per keyword."
                )
            if not _KEYWORD_PATTERN.match(kw_stripped):
                raise ValueError(
                    f"Invalid keyword: {kw_stripped!r}. "
                    "Allowed: alphanumeric, spaces, ._-+:/()"
                )
            lowered = kw_stripped.lower()
            if lowered in seen:
                # Skip duplicates rather than raising to make the model
                # ergonomic when callers concat keyword lists.
                continue
            seen.add(lowered)
            # H-S2: Cap cumulative keyword length to prevent prompt DoS.
            # Adding 2 for the ", " separator between keywords.
            cumulative_len += len(kw_stripped) + (2 if cleaned else 0)
            if cumulative_len > 4096:
                raise ValueError(
                    f"Cumulative keyword list exceeds 4096 bytes "
                    f"(got {cumulative_len}). Reduce the number or length "
                    "of keywords."
                )
            cleaned.append(kw_stripped)
        return cleaned

    @field_validator("sources")
    @classmethod
    def _validate_sources_arxiv_only(cls, v: list[PaperSource]) -> list[PaperSource]:
        # MVP scope: open-questions.md decision (2026-04-22) — only ArXiv has
        # an RSS/Atom feed efficient enough for monitoring. Future polling
        # support is gated behind the resolution of that question.
        if not v:
            raise ValueError("At least one source is required")
        non_arxiv = [s for s in v if s is not PaperSource.ARXIV]
        if non_arxiv:
            raise ValueError(
                "Only PaperSource.ARXIV is supported in the MVP "
                f"(got: {[s.value for s in non_arxiv]}). "
                "Other sources will be added in a follow-up release."
            )
        # Always normalize to a single ArXiv entry.
        return [PaperSource.ARXIV]


class MonitoringPaperRecord(BaseModel):
    """Per-paper outcome of a monitoring cycle.

    Used by the digest generator (Week 2) and by anyone who wants a
    structured audit trail of "what did the monitor see this run?".

    ``relevance_score`` and ``relevance_reasoning`` are populated by the
    Week 2 ``RelevanceScorer``; for Week 1 they remain ``None``.

    ``source`` (issue #141) is REQUIRED — every record must carry the
    discovery provider the paper came from so the audit log is honest
    about provenance. The ``MultiProviderMonitor`` (PR #140) fans out
    across arXiv + OpenAlex + HuggingFace + Semantic Scholar; before
    this field existed the cycle-level ``MonitoringRun.source`` was
    hardcoded to ARXIV which silently misattributed non-arXiv papers.
    """

    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Provider paper id (e.g. ArXiv id 2301.12345).",
    )
    title: str = Field(..., min_length=1, max_length=1024)
    url: Optional[str] = Field(default=None, max_length=1024)
    pdf_url: Optional[str] = Field(default=None, max_length=1024)
    published_at: Optional[datetime] = Field(default=None)
    is_new: bool = Field(
        ...,
        description=(
            "True if the paper was unknown to the global PaperRegistry "
            "before this cycle (i.e., not deduplicated)."
        ),
    )
    source: PaperSource = Field(
        ...,
        description=(
            "Discovery provider for this paper (issue #141). REQUIRED — "
            "callers must specify the actual source rather than relying "
            "on a default so multi-provider audit rows can never silently "
            "fall back to a hardcoded value."
        ),
    )
    relevance_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Filled in by the Week 2 RelevanceScorer.",
    )
    relevance_reasoning: Optional[str] = Field(
        default=None,
        max_length=4096,
        description="Filled in by the Week 2 RelevanceScorer.",
    )


class MonitoringPaperAudit(BaseModel):
    """Persisted audit fields for a paper seen in a monitoring run.

    Distinct from :class:`MonitoringPaperRecord`, which carries the
    richer in-memory metadata (``title``, ``url``, ``pdf_url``,
    ``published_at``, ...) produced by ``ArxivMonitor``. The audit
    type carries only the columns the ``monitoring_papers`` table
    actually stores -- so the repository's read path doesn't have to
    fabricate placeholder data (e.g. PR #119 reviewed
    ``MonitoringPaperRecord(title=paper_id)`` aliasing, which would
    cause Week 2's digest generator to render arXiv ids as titles).

    Reviewed in PR #119 self-review #S6.

    Title and other rich metadata
    -----------------------------
    Audit rows do not store paper title, abstract, URL, or PDF URL.
    Consumers (e.g., the Week-2 digest generator) should look up
    ``paper_id`` against
    :class:`~src.services.registry.service.RegistryService` to retrieve
    the rich representation. Storing rich fields here would duplicate
    the registry and bloat the audit table.

    Schema evolution
    ----------------
    Adding ``Optional[...]`` fields to this DTO is forward-compatible
    with existing audit rows (Pydantic strict accepts default ``None``).
    Adding non-null fields requires a new ``MIGRATION_V4`` to backfill
    the column with a sensible default before the field is added here.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    paper_id: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Provider paper id (e.g. ArXiv id 2301.12345).",
    )
    registered: bool = Field(
        default=False,
        description=(
            "True if the paper was newly registered with the global "
            "PaperRegistry during this run. Mirrors the ``is_new`` "
            "flag on ``MonitoringPaperRecord``."
        ),
    )
    source: PaperSource = Field(
        default=PaperSource.ARXIV,
        description=(
            "Discovery provider for this paper (issue #141). "
            "Backwards-compatible default of ARXIV matches the V5 "
            "schema's column default — pre-Tier-1 audit rows that have "
            "no recorded source are arXiv by definition."
        ),
    )
    relevance_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Filled in by the Week 2 RelevanceScorer.",
    )
    relevance_reasoning: Optional[str] = Field(
        default=None,
        max_length=4096,
        description="Filled in by the Week 2 RelevanceScorer.",
    )


class MonitoringRunAudit(BaseModel):
    """Persisted audit-only view of a ``MonitoringRun`` (PR #119 #S6).

    The repository returns this from ``get_run`` / ``list_runs`` instead
    of the in-memory :class:`MonitoringRun`, so callers see only the
    columns the audit tables actually stored. Avoids the
    ``MonitoringPaperRecord(title=paper_id)`` fabrication that the
    self-review flagged as silent contract corruption.

    Carries the same ``user_id`` denormalization that the table uses,
    so per-user audit consumers (digest generator, future REST/CLI)
    don't need a JOIN to ``subscriptions`` for the common case.

    Schema evolution
    ----------------
    Adding ``Optional[...]`` fields to this DTO is forward-compatible
    with existing audit rows (Pydantic strict accepts default ``None``).
    Adding non-null fields requires a new ``MIGRATION_V4`` to backfill
    the column with a sensible default before the field is added here.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    run_id: str = Field(..., min_length=1, max_length=64)
    subscription_id: str = Field(..., min_length=1, max_length=64)
    user_id: str = Field(..., min_length=1, max_length=64)
    started_at: datetime = Field(...)
    finished_at: Optional[datetime] = Field(default=None)
    status: MonitoringRunStatus = Field(...)
    papers_seen: int = Field(default=0, ge=0)
    papers_new: int = Field(default=0, ge=0)
    error: Optional[str] = Field(default=None, max_length=2000)
    papers: list[MonitoringPaperAudit] = Field(default_factory=list)


class MonitoringRun(BaseModel):
    """Audit record for one execution of the monitor.

    Created at the start of a cycle, finalized at the end with the
    outcome and ``papers``. Persistence is the caller's responsibility
    (Week 1 keeps these in-memory; Week 2's scheduler will write them).
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(
        default_factory=lambda: f"run-{uuid.uuid4().hex[:12]}",
        min_length=1,
        max_length=64,
    )
    subscription_id: str = Field(..., min_length=1, max_length=64)
    source: PaperSource = Field(default=PaperSource.ARXIV)
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    finished_at: Optional[datetime] = Field(default=None)
    status: MonitoringRunStatus = Field(default=MonitoringRunStatus.SUCCESS)
    papers_seen: int = Field(default=0, ge=0)
    papers_new: int = Field(default=0, ge=0)
    papers_deduplicated: int = Field(default=0, ge=0)
    error: Optional[str] = Field(default=None, max_length=2000)
    papers: list[MonitoringPaperRecord] = Field(default_factory=list)
    # Reserved for Week 2 APScheduler integration so a run can be
    # correlated back to the job that triggered it.
    scheduled_job_id: Optional[str] = Field(default=None, max_length=128)

    @field_validator("papers")
    @classmethod
    def _validate_papers_within_cycle_limit(
        cls, v: list[MonitoringPaperRecord]
    ) -> list[MonitoringPaperRecord]:
        if len(v) > MAX_PAPERS_PER_CYCLE:
            raise SubscriptionLimitError(
                "papers per cycle",
                len(v),
                MAX_PAPERS_PER_CYCLE,
            )
        return v

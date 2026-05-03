"""Proactive paper monitoring (Milestone 9.1).

This package implements ARISP's push-based monitoring system. It allows
users to register research subscriptions and have new papers from
external sources (currently ArXiv only — see open-questions.md) flow
automatically into the registry for downstream processing.

Public surface (Week 1 deliverables):

- ``ResearchSubscription``, ``MonitoringRun``, ``MonitoringRunStatus``,
  ``MonitoringPaperRecord``: Pydantic V2 strict models describing the
  monitoring data plane.
- ``SubscriptionManager``: CRUD over the existing ``subscriptions``
  SQLite table with limit enforcement (50/user, 100 keywords/sub).
- ``ArxivMonitor``: ArXiv-only polling that composes the existing
  ``ArxivProvider`` and the global ``PaperRegistry`` for deduplication.

Deferred to Week 2:

- ``RelevanceScorer`` (LLM-based scoring with Gemini Flash)
- ``DigestGenerator`` (file-based digests at ``./output/digests/``)
- CLI commands (``arisp monitor add/list/check/digest``)
- ``MonitoringCheckJob(BaseJob)`` APScheduler integration

The data model keeps explicit slots for the deferred pieces (e.g.
``MonitoringRun.scheduled_job_id``, ``MonitoringPaperRecord.relevance_score``)
so the Week 2 PR can plug in without a migration.
"""

from src.services.intelligence.monitoring.arxiv_monitor import (
    ArxivMonitor,
    ArxivMonitorResult,
)
from src.services.intelligence.monitoring.multi_provider_monitor import (
    MultiProviderMonitor,
    MultiProviderMonitorConfig,
)
from src.services.intelligence.monitoring.models import (
    MonitoringPaperAudit,
    MonitoringPaperRecord,
    MonitoringRun,
    MonitoringRunAudit,
    MonitoringRunStatus,
    ResearchSubscription,
    SubscriptionStatus,
)
from src.services.intelligence.monitoring.digest_generator import (
    DEFAULT_OUTPUT_ROOT,
    DigestGenerator,
)
from src.services.intelligence.monitoring.relevance_scorer import (
    LLMResponseError,
    RelevanceScorer,
    RelevanceScoreResult,
)
from src.services.intelligence.monitoring.run_repository import (
    MonitoringRunRepository,
)
from src.services.intelligence.monitoring.runner import MonitoringRunner
from src.services.intelligence.monitoring.subscription_manager import (
    SubscriptionManager,
)

__all__ = [
    "ArxivMonitor",
    "ArxivMonitorResult",
    "DEFAULT_OUTPUT_ROOT",
    "DigestGenerator",
    "LLMResponseError",
    "MonitoringPaperAudit",
    "MonitoringPaperRecord",
    "MonitoringRun",
    "MonitoringRunAudit",
    "MonitoringRunRepository",
    "MonitoringRunStatus",
    "MonitoringRunner",
    "MultiProviderMonitor",
    "MultiProviderMonitorConfig",
    "RelevanceScorer",
    "RelevanceScoreResult",
    "ResearchSubscription",
    "SubscriptionManager",
    "SubscriptionStatus",
]

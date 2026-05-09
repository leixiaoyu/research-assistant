"""Shared factory for wiring Tier-1 multi-provider extras.

H-C4: Both ``cli/monitor.py:_build_runner`` and
``src/scheduling/jobs.py:MonitoringCheckJob.__init__`` need the same
~30-line block that constructs the extra providers dict and the
``QueryExpander``. Extracting it here gives both call sites a one-liner
and makes the logic easy to unit-test in isolation.

Usage::

    extra_providers, query_expander = build_tier1_extras(llm_service)
    runner = MonitoringRunner.from_paths(
        ...,
        extra_providers=extra_providers,
        query_expander=query_expander,
    )

Returns ``(None, None)`` when ``llm_service`` is ``None`` (graceful
degradation — caller falls back to legacy single-ArXiv behavior).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

import structlog

from src.storage.intelligence_graph.connection import _trunc

if TYPE_CHECKING:
    from src.services.providers.base import DiscoveryProvider
    from src.services.intelligence.monitoring.models import PaperSource
    from src.services.llm.service import LLMService
    from src.utils.query_expander import QueryExpander

logger = structlog.get_logger(__name__)


def build_tier1_extras(
    llm_service: Optional["LLMService"],
) -> "tuple[dict[PaperSource, DiscoveryProvider] | None, QueryExpander | None]":
    """Build the extra-providers dict and query expander for Tier-1 discovery.

    Constructs OpenAlex, HuggingFace (always) and optionally Semantic Scholar
    (when ``SEMANTIC_SCHOLAR_API_KEY`` is set) providers. Also constructs a
    :class:`QueryExpander` backed by ``llm_service``.

    Args:
        llm_service: A configured :class:`~src.services.llm.service.LLMService`
            instance. When ``None``, both outputs are ``None`` (no Tier-1
            expansion, caller uses legacy ArXiv-only behavior).

    Returns:
        A ``(extra_providers, query_expander)`` tuple.
        Both elements are ``None`` when ``llm_service`` is ``None`` **or** when
        provider construction fails (logged as a warning; caller falls back).
    """
    if llm_service is None:
        return None, None

    try:
        from src.services.intelligence.monitoring.models import PaperSource
        from src.services.providers.huggingface import HuggingFaceProvider
        from src.services.providers.openalex import OpenAlexProvider
        from src.services.providers.semantic_scholar import SemanticScholarProvider
        from src.utils.query_expander import QueryExpander

        extra_providers: dict = {
            PaperSource.OPENALEX: OpenAlexProvider(),
            PaperSource.HUGGINGFACE: HuggingFaceProvider(),
        }
        s2_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        if s2_key and s2_key.strip():
            extra_providers[PaperSource.SEMANTIC_SCHOLAR] = SemanticScholarProvider(
                api_key=s2_key
            )
        query_expander: QueryExpander = QueryExpander(  # type: ignore[arg-type]
            llm_service=llm_service
        )
        return extra_providers, query_expander

    except Exception as exc:
        logger.warning(
            "monitor_tier1_init_failed",
            error=_trunc(exc),
            reason="falling_back_to_legacy_single_arxiv",
        )
        return None, None

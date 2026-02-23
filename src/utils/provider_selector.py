"""Intelligent provider selection for Phase 3.2 multi-provider support."""

from typing import Any, List, Optional, Tuple
import structlog

from src.models.config import ProviderType, ResearchTopic

logger = structlog.get_logger()

# Provider capability matrix
PROVIDER_CAPABILITIES = {
    ProviderType.ARXIV: {
        "coverage": "physics, math, cs, q-bio, q-fin, stat, eess, econ",
        "citation_support": False,
        "pdf_access_rate": 1.0,  # 100% open access
        "api_key_required": False,
        "rate_limit": 3.0,  # requests per second
    },
    ProviderType.SEMANTIC_SCHOLAR: {
        "coverage": "broad academic (200M+ papers)",
        "citation_support": True,
        "pdf_access_rate": 0.6,  # ~60% open access
        "api_key_required": True,
        "rate_limit": 1.67,  # 100 per minute
    },
    ProviderType.HUGGINGFACE: {
        "coverage": "AI/ML trending papers (community curated)",
        "citation_support": False,  # Uses upvotes instead
        "pdf_access_rate": 1.0,  # ArXiv-based, 100% open access
        "api_key_required": False,
        "rate_limit": 0.5,  # 30 per minute (conservative)
        "trending_support": True,  # Unique: community engagement metrics
    },
}

# ArXiv-specific terms that suggest ArXiv is the best provider
ARXIV_TERMS = {
    "arxiv",
    "preprint",
    "cs.ai",
    "cs.lg",
    "cs.cl",
    "cs.cv",
    "stat.ml",
    "physics",
    "quant-ph",
    "hep-th",
    "hep-ph",
    "cond-mat",
    "astro-ph",
    "math.",
    "q-bio",
    "q-fin",
    "eess",
    "econ",
}

# Cross-disciplinary terms that suggest Semantic Scholar
CROSS_DISCIPLINARY_TERMS = {
    "medicine",
    "medical",
    "biology",
    "chemistry",
    "psychology",
    "sociology",
    "economics",
    "business",
    "law",
    "education",
    "humanities",
    "history",
    "philosophy",
    "political",
    "environmental",
    "climate",
    "health",
    "clinical",
    "biomedical",
    "neuroscience",
    "cognitive",
    "social",
    "behavioral",
}

# HuggingFace-specific terms (AI/ML trending topics)
HUGGINGFACE_TERMS = {
    "huggingface",
    "hugging face",
    "transformers",
    "llm",
    "large language model",
    "gpt",
    "claude",
    "gemini",
    "llama",
    "mistral",
    "diffusion",
    "stable diffusion",
    "trending",
    "sota",
    "state-of-the-art",
    "benchmark",
    "leaderboard",
    "fine-tuning",
    "rlhf",
    "instruction tuning",
    "chat model",
    "multimodal",
    "vision language",
    "text-to-image",
    "embedding",
    "rag",
    "retrieval augmented",
    "agent",
    "agentic",
}


class ProviderSelector:
    """Selects optimal provider based on query characteristics."""

    def __init__(
        self,
        preference_order: Optional[List[ProviderType]] = None,
    ):
        """Initialize selector with preference order.

        Args:
            preference_order: Preferred provider order for fallback.
                             Defaults to [ARXIV, SEMANTIC_SCHOLAR].
        """
        self.preference_order = preference_order or [
            ProviderType.ARXIV,
            ProviderType.SEMANTIC_SCHOLAR,
            ProviderType.HUGGINGFACE,
        ]

    def get_capability(self, provider: ProviderType, capability: str) -> Any:
        """Get a capability value for a provider.

        Args:
            provider: The provider type.
            capability: The capability name.

        Returns:
            The capability value, or None if not found.
        """
        if provider in PROVIDER_CAPABILITIES:
            return PROVIDER_CAPABILITIES[provider].get(capability)
        return None

    def select_provider(
        self,
        topic: ResearchTopic,
        available_providers: List[ProviderType],
        min_citations: Optional[int] = None,
    ) -> ProviderType:
        """Select optimal provider based on query and requirements.

        Selection priority:
        1. Explicit provider in topic (if available)
        2. min_citations requirement → Semantic Scholar (citation support)
        3. ArXiv-specific terms → ArXiv
        4. Cross-disciplinary terms → Semantic Scholar
        5. Preference order fallback

        Args:
            topic: The research topic with query and settings.
            available_providers: List of currently available providers.
            min_citations: Minimum citation count requirement.

        Returns:
            Selected provider type.

        Raises:
            ValueError: If no suitable provider is available.
        """
        if not available_providers:
            raise ValueError("No providers available")

        query_lower = topic.query.lower()

        # Priority 1: Explicit provider if available and auto_select disabled
        if not topic.auto_select_provider:
            if topic.provider in available_providers:
                logger.debug(
                    "provider_explicit_selection",
                    provider=topic.provider,
                    query=topic.query[:50],
                )
                return topic.provider
            else:
                raise ValueError(
                    f"Requested provider {topic.provider} not available. "
                    f"Available: {available_providers}"
                )

        # Priority 2: Citation requirement needs Semantic Scholar
        effective_min_citations = min_citations or topic.min_citations
        if effective_min_citations is not None and effective_min_citations > 0:
            if ProviderType.SEMANTIC_SCHOLAR in available_providers:
                logger.debug(
                    "provider_citation_selection",
                    provider=ProviderType.SEMANTIC_SCHOLAR,
                    min_citations=effective_min_citations,
                )
                return ProviderType.SEMANTIC_SCHOLAR
            else:
                logger.warning(
                    "citation_filter_unavailable",
                    reason="semantic_scholar_not_available",
                    min_citations=effective_min_citations,
                )

        # Priority 3: HuggingFace-specific terms (AI/ML trending)
        if self._has_huggingface_terms(query_lower):
            if ProviderType.HUGGINGFACE in available_providers:
                logger.debug(
                    "provider_huggingface_terms_selection",
                    provider=ProviderType.HUGGINGFACE,
                    query=topic.query[:50],
                )
                return ProviderType.HUGGINGFACE

        # Priority 4: ArXiv-specific terms
        if self._has_arxiv_terms(query_lower):
            if ProviderType.ARXIV in available_providers:
                logger.debug(
                    "provider_arxiv_terms_selection",
                    provider=ProviderType.ARXIV,
                    query=topic.query[:50],
                )
                return ProviderType.ARXIV

        # Priority 5: Cross-disciplinary terms suggest Semantic Scholar
        if self._has_cross_disciplinary_terms(query_lower):
            if ProviderType.SEMANTIC_SCHOLAR in available_providers:
                logger.debug(
                    "provider_cross_disciplinary_selection",
                    provider=ProviderType.SEMANTIC_SCHOLAR,
                    query=topic.query[:50],
                )
                return ProviderType.SEMANTIC_SCHOLAR

        # Priority 5: Use preference order
        for provider in self.preference_order:
            if provider in available_providers:
                logger.debug(
                    "provider_preference_selection",
                    provider=provider,
                    query=topic.query[:50],
                )
                return provider

        # Fallback: first available
        selected = available_providers[0]
        logger.debug(
            "provider_fallback_selection",
            provider=selected,
            query=topic.query[:50],
        )
        return selected

    def get_recommendation(
        self,
        topic: ResearchTopic,
        available_providers: List[ProviderType],
    ) -> Tuple[ProviderType, str]:
        """Get provider recommendation with reasoning.

        Args:
            topic: The research topic.
            available_providers: Available providers.

        Returns:
            Tuple of (recommended provider, reasoning string).
        """
        selected = self.select_provider(topic, available_providers)
        reason = self._get_selection_reason(topic, selected, available_providers)
        return selected, reason

    def _has_arxiv_terms(self, query_lower: str) -> bool:
        """Check if query contains ArXiv-specific terms."""
        return any(term in query_lower for term in ARXIV_TERMS)

    def _has_cross_disciplinary_terms(self, query_lower: str) -> bool:
        """Check if query contains cross-disciplinary terms."""
        return any(term in query_lower for term in CROSS_DISCIPLINARY_TERMS)

    def _has_huggingface_terms(self, query_lower: str) -> bool:
        """Check if query contains HuggingFace/AI-ML trending terms."""
        return any(term in query_lower for term in HUGGINGFACE_TERMS)

    def _get_selection_reason(
        self,
        topic: ResearchTopic,
        selected: ProviderType,
        available_providers: List[ProviderType],
    ) -> str:
        """Generate human-readable reason for selection."""
        query_lower = topic.query.lower()

        if not topic.auto_select_provider:
            return f"Explicit provider selection: {selected.value}"

        if topic.min_citations and topic.min_citations > 0:
            if selected == ProviderType.SEMANTIC_SCHOLAR:
                return (
                    f"Citation filter (min={topic.min_citations}) "
                    "requires Semantic Scholar"
                )

        if self._has_huggingface_terms(query_lower):
            if selected == ProviderType.HUGGINGFACE:
                return "Query matches AI/ML trending topics (HuggingFace)"

        if self._has_arxiv_terms(query_lower):
            if selected == ProviderType.ARXIV:
                return "Query contains ArXiv-specific terms"

        if self._has_cross_disciplinary_terms(query_lower):
            if selected == ProviderType.SEMANTIC_SCHOLAR:
                return "Query spans multiple disciplines"

        return f"Default selection based on preference order: {selected.value}"

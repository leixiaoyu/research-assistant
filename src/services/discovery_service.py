"""Discovery service with multi-provider intelligence (Phase 3.2)."""

import asyncio
import time
from typing import List, Dict, Optional, Tuple
import structlog

from src.services.providers.base import DiscoveryProvider, APIError
from src.services.providers.semantic_scholar import SemanticScholarProvider
from src.services.providers.arxiv import ArxivProvider
from src.models.config import (
    ResearchTopic,
    ProviderType,
    ProviderSelectionConfig,
)
from src.models.paper import PaperMetadata
from src.models.provider import ProviderMetrics, ProviderComparison
from src.utils.provider_selector import ProviderSelector

logger = structlog.get_logger()


class DiscoveryService:
    """Wrapper service for paper discovery with multi-provider support.

    Phase 3.2 Features:
    - Intelligent provider selection based on query characteristics
    - Automatic fallback on provider failure
    - Benchmark mode for multi-provider comparison
    - Metrics collection for performance analysis
    """

    def __init__(
        self,
        api_key: str = "",
        config: Optional[ProviderSelectionConfig] = None,
    ):
        """Initialize discovery service with providers.

        Args:
            api_key: Semantic Scholar API key (optional).
            config: Provider selection configuration.
        """
        self.config = config or ProviderSelectionConfig()
        self.providers: Dict[ProviderType, DiscoveryProvider] = {}
        self._api_key = api_key

        # Initialize ArXiv (Always available)
        self.providers[ProviderType.ARXIV] = ArxivProvider()

        # Initialize Semantic Scholar (Only if key provided)
        if api_key:
            self.providers[ProviderType.SEMANTIC_SCHOLAR] = SemanticScholarProvider(
                api_key=api_key
            )
        else:
            logger.info("semantic_scholar_disabled", reason="no_api_key")

        # Initialize provider selector
        self._selector = ProviderSelector(
            preference_order=self.config.preference_order,
        )

    @property
    def available_providers(self) -> List[ProviderType]:
        """Get list of available provider types."""
        return list(self.providers.keys())

    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search for papers using intelligent provider selection.

        Args:
            topic: Research topic with query and settings.

        Returns:
            List of paper metadata.

        Raises:
            APIError: If provider is unavailable or request fails.
            ValueError: If unknown provider type requested.
        """
        # Check for benchmark mode
        if topic.benchmark or self.config.benchmark_mode:
            return await self._benchmark_search(topic)

        # Auto-select provider if enabled
        if self.config.auto_select and topic.auto_select_provider:
            selected_provider = self._selector.select_provider(
                topic=topic,
                available_providers=self.available_providers,
                min_citations=topic.min_citations,
            )
        else:
            selected_provider = topic.provider

        # Validate provider availability
        if selected_provider not in self.providers:
            if selected_provider == ProviderType.SEMANTIC_SCHOLAR:
                logger.error(
                    "provider_unavailable",
                    provider=selected_provider,
                    reason="missing_api_key",
                )
                raise APIError(
                    f"Provider {selected_provider} is not available "
                    "(missing API key). Check .env file."
                )
            else:
                raise ValueError(f"Unknown provider type: {selected_provider}")

        provider = self.providers[selected_provider]

        # Execute search with fallback if enabled
        if self.config.fallback_enabled and len(self.providers) > 1:
            return await self._search_with_fallback(topic, provider, selected_provider)
        else:
            return await provider.search(topic)

    async def _search_with_fallback(
        self,
        topic: ResearchTopic,
        primary_provider: DiscoveryProvider,
        primary_type: ProviderType,
    ) -> List[PaperMetadata]:
        """Execute search with automatic fallback on failure.

        Args:
            topic: Research topic.
            primary_provider: Primary provider instance.
            primary_type: Primary provider type.

        Returns:
            List of paper metadata.
        """
        try:
            # Try primary provider with timeout
            result = await asyncio.wait_for(
                primary_provider.search(topic),
                timeout=self.config.fallback_timeout_seconds,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(
                "provider_timeout",
                provider=primary_type,
                timeout=self.config.fallback_timeout_seconds,
            )
        except Exception as e:
            logger.warning(
                "provider_error",
                provider=primary_type,
                error=str(e),
            )

        # Attempt fallback
        return await self._fallback_search(topic, primary_type)

    async def _fallback_search(
        self,
        topic: ResearchTopic,
        failed_provider: ProviderType,
    ) -> List[PaperMetadata]:
        """Attempt search with fallback providers.

        Args:
            topic: Research topic.
            failed_provider: The provider that failed.

        Returns:
            List of paper metadata from fallback provider.
        """
        for provider_type in self.config.preference_order:
            if provider_type == failed_provider:
                continue
            if (
                provider_type not in self.providers
            ):  # pragma: no cover (config mismatch)
                continue

            logger.info(
                "fallback_attempt",
                from_provider=failed_provider,
                to_provider=provider_type,
            )

            try:
                provider = self.providers[provider_type]
                result = await provider.search(topic)
                logger.info(
                    "fallback_success",
                    provider=provider_type,
                    result_count=len(result),
                )
                return result
            except Exception as e:
                logger.warning(
                    "fallback_failed",
                    provider=provider_type,
                    error=str(e),
                )
                continue

        logger.error("all_providers_failed", topic=topic.query[:50])
        return []

    async def _benchmark_search(
        self,
        topic: ResearchTopic,
    ) -> List[PaperMetadata]:
        """Search all providers and return deduplicated results.

        Args:
            topic: Research topic.

        Returns:
            Deduplicated list of papers from all providers.
        """
        all_papers: List[PaperMetadata] = []
        seen_ids: set = set()

        # Query all providers concurrently
        tasks = []
        provider_types = []
        for provider_type, provider in self.providers.items():
            tasks.append(provider.search(topic))
            provider_types.append(provider_type)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for provider_type, result in zip(provider_types, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "benchmark_provider_error",
                    provider=provider_type,
                    error=str(result),
                )
                continue

            # Type is now List[PaperMetadata] after BaseException check
            papers_result: List[PaperMetadata] = result
            for paper in papers_result:
                # Deduplicate by DOI or paper_id
                unique_id = paper.doi or paper.paper_id
                if unique_id and unique_id not in seen_ids:
                    seen_ids.add(unique_id)
                    all_papers.append(paper)
                elif not unique_id:
                    # No unique ID, include anyway
                    all_papers.append(paper)

        logger.info(
            "benchmark_complete",
            total_papers=len(all_papers),
            providers_queried=len(self.providers),
        )

        return all_papers

    async def search_with_metrics(
        self,
        topic: ResearchTopic,
    ) -> Tuple[List[PaperMetadata], ProviderMetrics]:
        """Search and return results with performance metrics.

        Args:
            topic: Research topic.

        Returns:
            Tuple of (papers, metrics).
        """
        # Determine which provider will be used
        if self.config.auto_select and topic.auto_select_provider:
            provider_type = self._selector.select_provider(
                topic=topic,
                available_providers=self.available_providers,
            )
        else:
            provider_type = topic.provider

        start_time = time.time()
        error_msg = None
        success = True
        papers: List[PaperMetadata] = []

        try:
            papers = await self.search(topic)
        except Exception as e:
            success = False
            error_msg = str(e)

        elapsed_ms = int((time.time() - start_time) * 1000)

        metrics = ProviderMetrics(
            provider=provider_type,
            query_time_ms=elapsed_ms,
            result_count=len(papers),
            success=success,
            error=error_msg,
        )

        return papers, metrics

    async def compare_providers(
        self,
        topic: ResearchTopic,
    ) -> ProviderComparison:
        """Compare all providers for a topic.

        Args:
            topic: Research topic.

        Returns:
            Comparison results with metrics from all providers.
        """
        metrics_list: List[ProviderMetrics] = []
        all_papers: Dict[str, PaperMetadata] = {}
        overlap_ids: set = set()

        for provider_type, provider in self.providers.items():
            start_time = time.time()
            error_msg = None
            success = True
            result_count = 0
            papers: List[PaperMetadata] = []

            try:
                papers = await provider.search(topic)
                result_count = len(papers)
            except Exception as e:
                success = False
                error_msg = str(e)

            elapsed_ms = int((time.time() - start_time) * 1000)

            metrics_list.append(
                ProviderMetrics(
                    provider=provider_type,
                    query_time_ms=elapsed_ms,
                    result_count=result_count,
                    success=success,
                    error=error_msg,
                )
            )

            # Track papers for overlap analysis
            for paper in papers:
                unique_id = paper.doi or paper.paper_id
                if unique_id:
                    if unique_id in all_papers:
                        overlap_ids.add(unique_id)
                    else:
                        all_papers[unique_id] = paper

        # Determine fastest and most results
        successful_metrics = [m for m in metrics_list if m.success]
        fastest = None
        most_results = None

        if successful_metrics:
            fastest = min(successful_metrics, key=lambda m: m.query_time_ms).provider
            most_results = max(
                successful_metrics, key=lambda m: m.result_count
            ).provider

        return ProviderComparison(
            providers_queried=list(self.providers.keys()),
            metrics=metrics_list,
            total_unique_papers=len(all_papers),
            overlap_count=len(overlap_ids),
            fastest_provider=fastest,
            most_results_provider=most_results,
        )

"""Provider metrics collection and comparison (Phase 3.2)."""

import time
from typing import List, Dict, Tuple

import structlog

from src.models.config import ResearchTopic, ProviderType
from src.models.paper import PaperMetadata
from src.models.provider import ProviderMetrics, ProviderComparison
from src.services.providers.base import DiscoveryProvider

logger = structlog.get_logger()


class MetricsCollector:
    """Collects and analyzes provider performance metrics."""

    def __init__(self):
        """Initialize metrics collector."""
        pass

    async def search_with_metrics(
        self,
        topic: ResearchTopic,
        provider_type: ProviderType,
        search_func,
    ) -> Tuple[List[PaperMetadata], ProviderMetrics]:
        """Execute search and collect performance metrics.

        Args:
            topic: Research topic.
            provider_type: Provider type being used.
            search_func: Async function that executes the search.

        Returns:
            Tuple of (papers, metrics).
        """
        start_time = time.time()
        error_msg = None
        success = True
        papers: List[PaperMetadata] = []

        try:
            papers = await search_func()
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
        providers: Dict[ProviderType, DiscoveryProvider],
    ) -> ProviderComparison:
        """Compare all providers for a topic.

        Args:
            topic: Research topic.
            providers: Dictionary of available providers.

        Returns:
            Comparison results with metrics from all providers.
        """
        metrics_list: List[ProviderMetrics] = []
        all_papers: Dict[str, PaperMetadata] = {}
        overlap_ids: set = set()

        for provider_type, provider in providers.items():
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
            providers_queried=list(providers.keys()),
            metrics=metrics_list,
            total_unique_papers=len(all_papers),
            overlap_count=len(overlap_ids),
            fastest_provider=fastest,
            most_results_provider=most_results,
        )

    def log_quality_stats(self, papers: List[PaperMetadata]) -> None:
        """Log quality and PDF availability statistics.

        Args:
            papers: Ranked papers with quality scores.
        """
        if not papers:
            return

        pdf_count = sum(1 for p in papers if p.pdf_available)
        pdf_rate = (pdf_count / len(papers)) * 100

        scores = [p.quality_score for p in papers]
        avg_score = sum(scores) / len(scores)

        # Calculate average quality for papers with/without PDF
        with_pdf_scores = [p.quality_score for p in papers if p.pdf_available]
        without_pdf_scores = [p.quality_score for p in papers if not p.pdf_available]

        avg_with_pdf = (
            sum(with_pdf_scores) / len(with_pdf_scores) if with_pdf_scores else 0
        )
        avg_without_pdf = (
            sum(without_pdf_scores) / len(without_pdf_scores)
            if without_pdf_scores
            else 0
        )

        logger.info(
            "quality_ranking_stats",
            total_papers=len(papers),
            pdf_available=pdf_count,
            pdf_rate=f"{pdf_rate:.1f}%",
            avg_quality_score=round(avg_score, 2),
            avg_quality_with_pdf=round(avg_with_pdf, 2),
            avg_quality_without_pdf=round(avg_without_pdf, 2),
            top_quality=round(papers[0].quality_score, 2) if papers else 0,
        )

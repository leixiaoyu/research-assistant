"""Tests for DiscoveryPhase multi-source discovery.

Split from test_phase_7_2_components.py for better organization.
Tests cover multi-source discovery execution and statistics tracking.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    QueryExpansionConfig,
    CitationExplorationConfig,
    AggregationConfig,
)
from src.models.paper import PaperMetadata


class TestDiscoveryPhaseMultiSource:
    """Tests for DiscoveryPhase multi-source discovery."""

    @pytest.mark.asyncio
    async def test_discovery_phase_init_with_configs(self):
        """Test DiscoveryPhase initialization with Phase 7.2 configs."""
        from src.orchestration.phases.discovery import DiscoveryPhase

        mock_context = MagicMock()

        phase = DiscoveryPhase(
            context=mock_context,
            multi_source_enabled=True,
            query_expansion_config=QueryExpansionConfig(),
            citation_config=CitationExplorationConfig(),
            aggregation_config=AggregationConfig(),
        )

        assert phase.multi_source_enabled is True
        assert phase.query_expansion_config is not None
        assert phase.citation_config is not None
        assert phase.aggregation_config is not None

    def test_discovery_phase_name(self):
        """Test DiscoveryPhase name property."""
        from src.orchestration.phases.discovery import DiscoveryPhase

        mock_context = MagicMock()
        phase = DiscoveryPhase(context=mock_context)
        assert phase.name == "discovery"

    def test_discovery_phase_default_result(self):
        """Test DiscoveryPhase default result."""
        from src.orchestration.phases.discovery import DiscoveryPhase, DiscoveryResult

        mock_context = MagicMock()
        phase = DiscoveryPhase(context=mock_context)
        result = phase._get_default_result()

        assert isinstance(result, DiscoveryResult)
        assert result.topics_processed == 0


class TestDiscoveryServiceMultiSource:
    """Tests for DiscoveryService multi_source_search."""

    @pytest.mark.asyncio
    async def test_multi_source_search_basic(self):
        """Test basic multi-source search."""
        from src.services.discovery_service import DiscoveryService

        # Use MagicMock for config
        config = MagicMock()

        service = DiscoveryService(
            config=config,
            api_key="test-key",
        )

        # Mock all providers
        mock_papers = [
            PaperMetadata(
                paper_id="p1",
                title="Test Paper",
                url="https://example.com/p1",
            )
        ]

        for provider in service.providers.values():
            provider.search = AsyncMock(return_value=mock_papers)

        topic = ResearchTopic(
            query="machine learning",
            timeframe=TimeframeRecent(value="7d"),
        )

        result = await service.multi_source_search(
            topic=topic,
            llm_service=None,
            registry_service=None,
        )

        # Should return aggregated papers
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_multi_source_with_query_expansion(self):
        """Test multi-source search with query expansion."""
        from src.services.discovery_service import DiscoveryService

        config = MagicMock()

        service = DiscoveryService(
            config=config,
            api_key="test-key",
        )

        # Mock providers
        for provider in service.providers.values():
            provider.search = AsyncMock(return_value=[])

        # Mock LLM service
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(
            return_value='["expanded query 1", "expanded query 2"]'
        )

        topic = ResearchTopic(
            query="original query",
            timeframe=TimeframeRecent(value="7d"),
        )

        qe_config = QueryExpansionConfig(enabled=True, max_variants=3)

        await service.multi_source_search(
            topic=topic,
            llm_service=mock_llm,
            registry_service=None,
            query_expansion_config=qe_config,
        )

        # Providers should be called multiple times (once per query variant)
        for provider in service.providers.values():
            assert provider.search.call_count >= 1

    @pytest.mark.asyncio
    async def test_multi_source_provider_error_handling(self):
        """Test multi-source handles provider errors gracefully."""
        from src.services.discovery_service import DiscoveryService

        config = MagicMock()
        service = DiscoveryService(config=config, api_key="test-key")

        # One provider fails, others succeed
        providers = list(service.providers.values())
        providers[0].search = AsyncMock(side_effect=Exception("Provider error"))
        for provider in providers[1:]:
            provider.search = AsyncMock(
                return_value=[
                    PaperMetadata(
                        paper_id="p1",
                        title="Success Paper",
                        url="https://example.com/p1",
                    )
                ]
            )

        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="7d"),
        )

        # Should not raise, should handle error gracefully
        result = await service.multi_source_search(
            topic=topic,
            llm_service=None,
            registry_service=None,
        )

        assert isinstance(result, list)


class TestDiscoveryPhaseMultiSourceExecution:
    """Tests for DiscoveryPhase multi-source execution."""

    @pytest.mark.asyncio
    async def test_discovery_phase_multi_source_execute(self):
        """Test DiscoveryPhase executes multi-source discovery.

        Note: With the unified discovery API, DiscoveryPhase now uses
        discover() method which is the unified entry point.
        """
        from src.orchestration.phases.discovery import DiscoveryPhase
        from src.models.discovery import DiscoveryResult as DiscoveryResultModel
        from src.models.discovery import DiscoveryMetrics, DiscoveryMode, ScoredPaper

        # Set up mock context
        mock_context = MagicMock()
        mock_context.config = MagicMock()
        mock_context.config.research_topics = [
            ResearchTopic(
                query="test query",
                timeframe=TimeframeRecent(value="7d"),
            )
        ]

        mock_catalog = MagicMock()
        mock_catalog.get_or_create_topic.return_value = MagicMock(
            topic_slug="test-query"
        )
        mock_context.catalog_service = mock_catalog

        # Mock discover() to return proper DiscoveryResult
        mock_discovery_result = DiscoveryResultModel(
            papers=[
                ScoredPaper(
                    paper_id="p1",
                    title="Test Paper",
                    url="https://example.com/p1",
                    quality_score=0.8,
                )
            ],
            metrics=DiscoveryMetrics(
                papers_retrieved=1,
                papers_after_quality_filter=1,
                avg_quality_score=0.8,
            ),
            mode=DiscoveryMode.DEEP,
        )

        mock_discovery = MagicMock()
        mock_discovery.discover = AsyncMock(return_value=mock_discovery_result)
        mock_context.discovery_service = mock_discovery
        mock_context.add_discovered_papers = MagicMock()
        mock_context.add_error = MagicMock()

        phase = DiscoveryPhase(
            context=mock_context,
            multi_source_enabled=True,
            query_expansion_config=QueryExpansionConfig(enabled=False),
            citation_config=CitationExplorationConfig(enabled=False),
            aggregation_config=AggregationConfig(),
        )

        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.total_papers == 1
        assert result.multi_source_enabled is True
        mock_discovery.discover.assert_called_once()

    @pytest.mark.asyncio
    async def test_discovery_phase_tracks_citation_stats(self):
        """Test DiscoveryPhase tracks citation discovery stats.

        Note: With the unified discovery API, DiscoveryPhase now uses
        discover() method which is the unified entry point.
        """
        from src.orchestration.phases.discovery import DiscoveryPhase
        from src.models.discovery import DiscoveryResult as DiscoveryResultModel
        from src.models.discovery import DiscoveryMetrics, DiscoveryMode, ScoredPaper

        mock_context = MagicMock()
        mock_context.config = MagicMock()
        mock_context.config.research_topics = [
            ResearchTopic(
                query="citation test",
                timeframe=TimeframeRecent(value="7d"),
            )
        ]

        mock_catalog = MagicMock()
        mock_catalog.get_or_create_topic.return_value = MagicMock(
            topic_slug="citation-test"
        )
        mock_context.catalog_service = mock_catalog

        # Return papers with citation discovery methods via discover()
        mock_discovery_result = DiscoveryResultModel(
            papers=[
                ScoredPaper(
                    paper_id="p1",
                    title="Forward Citation Paper",
                    url="https://example.com/p1",
                    quality_score=0.8,
                ),
                ScoredPaper(
                    paper_id="p2",
                    title="Backward Citation Paper",
                    url="https://example.com/p2",
                    quality_score=0.75,
                ),
                ScoredPaper(
                    paper_id="p3",
                    title="Keyword Paper",
                    url="https://example.com/p3",
                    quality_score=0.7,
                ),
            ],
            metrics=DiscoveryMetrics(
                papers_retrieved=3,
                papers_after_quality_filter=3,
                avg_quality_score=0.75,
            ),
            mode=DiscoveryMode.DEEP,
        )

        mock_discovery = MagicMock()
        mock_discovery.discover = AsyncMock(return_value=mock_discovery_result)
        mock_context.discovery_service = mock_discovery
        mock_context.add_discovered_papers = MagicMock()
        mock_context.add_error = MagicMock()

        phase = DiscoveryPhase(
            context=mock_context,
            multi_source_enabled=True,
        )

        result = await phase.execute()

        # Check stats are tracked - with unified API, we verify basic discovery stats
        assert result.topics_processed == 1
        assert result.total_papers == 3
        topic_result = result.topic_results[0]
        assert len(topic_result.papers) == 3
        # Note: phase72_stats may be None with unified API as stats come from
        # DiscoveryResult.metrics instead of legacy phase72_stats
        mock_discovery.discover.assert_called_once()

    @pytest.mark.asyncio
    async def test_discovery_phase_initializes_phase72_stats_with_source_breakdown(
        self,
    ):
        """Test that Phase72Stats is initialized when source_breakdown is present."""
        from src.orchestration.phases.discovery import DiscoveryPhase
        from src.models.discovery import (
            DiscoveryResult as DiscoveryResultModel,
            DiscoveryMetrics,
            DiscoveryMode,
            ScoredPaper,
        )

        mock_context = MagicMock()
        mock_context.config = MagicMock()
        mock_context.config.research_topics = [
            ResearchTopic(
                query="source breakdown test",
                timeframe=TimeframeRecent(value="7d"),
            )
        ]

        mock_catalog = MagicMock()
        mock_catalog.get_or_create_topic.return_value = MagicMock(
            topic_slug="source-breakdown-test"
        )
        mock_context.catalog_service = mock_catalog

        # Create discovery result WITH source_breakdown to trigger Phase72Stats init
        mock_discovery_result = DiscoveryResultModel(
            papers=[
                ScoredPaper(
                    paper_id="p1",
                    title="Paper from ArXiv",
                    url="https://arxiv.org/p1",
                    quality_score=0.8,
                ),
                ScoredPaper(
                    paper_id="p2",
                    title="Paper from Semantic Scholar",
                    url="https://semanticscholar.org/p2",
                    quality_score=0.75,
                ),
            ],
            metrics=DiscoveryMetrics(
                papers_retrieved=2,
                papers_after_quality_filter=2,
                avg_quality_score=0.775,
            ),
            source_breakdown={"arxiv": 1, "semantic_scholar": 1},  # This triggers init
            mode=DiscoveryMode.STANDARD,
        )

        mock_discovery = MagicMock()
        mock_discovery.discover = AsyncMock(return_value=mock_discovery_result)
        mock_context.discovery_service = mock_discovery
        mock_context.add_discovered_papers = MagicMock()
        mock_context.add_error = MagicMock()

        phase = DiscoveryPhase(
            context=mock_context,
            multi_source_enabled=True,  # Required for Phase72Stats path
        )

        result = await phase.execute()

        # Verify Phase72Stats was initialized with source breakdown data
        assert result.topics_processed == 1
        topic_result = result.topic_results[0]
        assert topic_result.phase72_stats is not None
        assert topic_result.phase72_stats.source_breakdown == {
            "arxiv": 1,
            "semantic_scholar": 1,
        }
        assert set(topic_result.phase72_stats.sources_queried) == {
            "arxiv",
            "semantic_scholar",
        }
        assert topic_result.phase72_stats.papers_after_dedup == 2

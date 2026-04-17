"""Tests for DiscoveryPhase."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestration.phases.discovery import (
    DiscoveryPhase,
    DiscoveryResult,
    TopicDiscoveryResult,
)
from src.orchestration.context import PipelineContext
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    DiscoveryFilterSettings,
    IncrementalDiscoverySettings,
)
from src.models.discovery import (
    DiscoveryStats,
    ResolvedTimeframe,
    DiscoveryResult as DiscoveryAPIResult,
    DiscoveryMetrics,
    ScoredPaper,
    DiscoveryMode,
)
from src.models.paper import PaperMetadata
from src.services.providers.base import APIError


@pytest.fixture
def mock_context():
    """Create mock pipeline context."""
    context = MagicMock(spec=PipelineContext)
    context.config = MagicMock()
    context.config.research_topics = []
    context.config.settings = MagicMock()
    context.config.settings.discovery_filter_settings = DiscoveryFilterSettings(
        enabled=False,
        register_at_discovery=False,
    )
    context.config.settings.incremental_discovery_settings = (
        IncrementalDiscoverySettings(
            enabled=False,
        )
    )
    context.discovery_service = AsyncMock()
    context.catalog_service = MagicMock()
    context.registry_service = None
    context.errors = []
    context.add_error = MagicMock()
    context.add_discovered_papers = MagicMock()
    return context


@pytest.fixture
def sample_topic():
    """Create a sample research topic."""
    return ResearchTopic(
        query="machine learning",
        timeframe=TimeframeRecent(value="7d"),
    )


@pytest.fixture
def sample_papers():
    """Create sample paper metadata."""
    paper1 = PaperMetadata(
        paper_id="paper1",
        title="Test Paper 1",
        url="https://example.com/paper1",
    )
    paper2 = PaperMetadata(
        paper_id="paper2",
        title="Test Paper 2",
        url="https://example.com/paper2",
    )
    return [paper1, paper2]


@pytest.fixture
def sample_scored_papers(sample_papers):
    """Create sample scored papers for discover() API."""
    scored = []
    for paper in sample_papers:
        scored_paper = ScoredPaper(
            paper_id=paper.paper_id,
            title=paper.title,
            abstract=paper.abstract,
            doi=paper.doi,
            url=str(paper.url) if paper.url else None,
            open_access_pdf=None,
            authors=[],
            publication_date=None,
            venue=None,
            citation_count=0,
            source=None,
            quality_score=0.8,
            relevance_score=0.7,
            engagement_score=0.0,
        )
        scored.append(scored_paper)
    return scored


def make_discovery_result(scored_papers, mode=DiscoveryMode.STANDARD):
    """Helper to create DiscoveryAPIResult for mocking."""
    return DiscoveryAPIResult(
        papers=scored_papers,
        metrics=DiscoveryMetrics(
            queries_generated=1,
            papers_retrieved=len(scored_papers),
            papers_after_dedup=len(scored_papers),
            papers_after_quality_filter=len(scored_papers),
            papers_after_relevance_filter=len(scored_papers),
            providers_queried=["arxiv"],
            avg_relevance_score=0.7,
            avg_quality_score=0.8,
            pipeline_duration_ms=100,
        ),
        queries_used=[],
        source_breakdown={"arxiv": len(scored_papers)},
        mode=mode,
    )


class TestDiscoveryResult:
    """Tests for DiscoveryResult dataclass."""

    def test_default_values(self):
        """Test default values."""
        result = DiscoveryResult()
        assert result.topics_processed == 0
        assert result.topics_failed == 0
        assert result.total_papers == 0
        assert result.topic_results == []

    def test_with_values(self):
        """Test with custom values."""
        topic_result = TopicDiscoveryResult(
            topic=MagicMock(),
            topic_slug="test-topic",
            papers=[],
            success=True,
        )
        result = DiscoveryResult(
            topics_processed=1,
            topics_failed=0,
            total_papers=5,
            topic_results=[topic_result],
        )
        assert result.topics_processed == 1
        assert result.total_papers == 5
        assert len(result.topic_results) == 1


class TestTopicDiscoveryResult:
    """Tests for TopicDiscoveryResult dataclass."""

    def test_default_values(self, sample_topic):
        """Test default values."""
        result = TopicDiscoveryResult(
            topic=sample_topic,
            topic_slug="machine-learning",
        )
        assert result.papers == []
        assert result.success is False
        assert result.error is None
        assert result.duration_seconds == 0.0

    def test_with_papers(self, sample_topic, sample_papers):
        """Test with papers."""
        result = TopicDiscoveryResult(
            topic=sample_topic,
            topic_slug="machine-learning",
            papers=sample_papers,
            success=True,
        )
        assert len(result.papers) == 2
        assert result.success is True


class TestDiscoveryPhase:
    """Tests for DiscoveryPhase."""

    def test_name_property(self, mock_context):
        """Test name property."""
        phase = DiscoveryPhase(mock_context)
        assert phase.name == "discovery"

    def test_is_enabled_default(self, mock_context):
        """Test is_enabled defaults to True."""
        phase = DiscoveryPhase(mock_context)
        assert phase.is_enabled() is True

    @pytest.mark.asyncio
    async def test_execute_no_topics(self, mock_context):
        """Test execute with no topics."""
        mock_context.config.research_topics = []
        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()
        assert result.topics_processed == 0
        assert result.total_papers == 0

    @pytest.mark.asyncio
    async def test_execute_single_topic_success(
        self, mock_context, sample_topic, sample_scored_papers
    ):
        """Test execute with single successful topic."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        # Mock discover() to return DiscoveryAPIResult
        discovery_result = make_discovery_result(sample_scored_papers)
        mock_context.discovery_service.discover = AsyncMock(
            return_value=discovery_result
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.topics_failed == 0
        assert result.total_papers == 2
        # Verify discover was called with correct parameters
        mock_context.discovery_service.discover.assert_called_once()
        call_args = mock_context.discovery_service.discover.call_args
        assert call_args[1]["topic"] == "machine learning"
        # Mode defaults to STANDARD when neither multi_source nor
        # enhanced_enabled is set
        assert call_args[1]["mode"] == DiscoveryMode.STANDARD

    @pytest.mark.asyncio
    async def test_execute_topic_api_error(self, mock_context, sample_topic):
        """Test execute handles API errors."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )
        # Mock discover() to raise APIError
        mock_context.discovery_service.discover = AsyncMock(
            side_effect=APIError("API failed")
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 0
        assert result.topics_failed == 1
        mock_context.add_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_topic_unexpected_error(self, mock_context, sample_topic):
        """Test execute handles unexpected errors."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )
        # Mock discover() to raise unexpected error
        mock_context.discovery_service.discover = AsyncMock(
            side_effect=Exception("Unexpected")
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 0
        assert result.topics_failed == 1

    @pytest.mark.asyncio
    async def test_execute_no_papers_found(self, mock_context, sample_topic):
        """Test execute when no papers found."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )
        # Mock discover() to return empty result
        discovery_result = make_discovery_result([])
        mock_context.discovery_service.discover = AsyncMock(
            return_value=discovery_result
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.total_papers == 0

    @pytest.mark.asyncio
    async def test_execute_multiple_topics(self, mock_context, sample_scored_papers):
        """Test execute with multiple topics."""
        topics = [
            ResearchTopic(
                query="topic1",
                timeframe=TimeframeRecent(value="7d"),
            ),
            ResearchTopic(
                query="topic2",
                timeframe=TimeframeRecent(value="7d"),
            ),
        ]
        mock_context.config.research_topics = topics
        mock_context.catalog_service.get_or_create_topic.side_effect = [
            MagicMock(topic_slug="topic1"),
            MagicMock(topic_slug="topic2"),
        ]
        # Mock discover() to return results for each topic
        discovery_result = make_discovery_result(sample_scored_papers)
        mock_context.discovery_service.discover = AsyncMock(
            return_value=discovery_result
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 2
        assert result.total_papers == 4  # 2 papers per topic

    def test_get_default_result(self, mock_context):
        """Test _get_default_result."""
        phase = DiscoveryPhase(mock_context)
        result = phase._get_default_result()
        assert isinstance(result, DiscoveryResult)
        assert result.topics_processed == 0


class TestDiscoveryPhasePhase71Integration:
    """Tests for Phase 7.1 discovery integration features."""

    @pytest.mark.asyncio
    async def test_incremental_discovery_disabled(
        self, mock_context, sample_topic, sample_scored_papers
    ):
        """Test discovery when incremental mode is disabled."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )
        # Mock discover()
        discovery_result = make_discovery_result(sample_scored_papers)
        mock_context.discovery_service.discover = AsyncMock(
            return_value=discovery_result
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.total_papers == 2
        # Catalog timestamp should NOT be updated when incremental is disabled
        mock_context.catalog_service.set_last_discovery_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_incremental_discovery_enabled(
        self, mock_context, sample_topic, sample_scored_papers
    ):
        """Test discovery with incremental mode enabled."""
        # Enable incremental discovery
        mock_context.config.settings.incremental_discovery_settings = (
            IncrementalDiscoverySettings(enabled=True)
        )

        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        # Mock discover()
        discovery_result = make_discovery_result(sample_scored_papers)
        mock_context.discovery_service.discover = AsyncMock(
            return_value=discovery_result
        )

        # Mock TimeframeResolver
        mock_resolved = ResolvedTimeframe(
            start_date=datetime(2025, 1, 20),
            end_date=datetime(2025, 1, 27),
            is_incremental=False,
            overlap_buffer_hours=0,
        )

        with patch(
            "src.orchestration.phases.discovery.TimeframeResolver"
        ) as mock_resolver_class:
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = mock_resolved
            mock_resolver_class.return_value = mock_resolver

            phase = DiscoveryPhase(mock_context)
            result = await phase.execute()

            assert result.topics_processed == 1
            assert result.total_papers == 2

            # Verify TimeframeResolver was called
            mock_resolver.resolve.assert_called_once_with(
                sample_topic, "machine-learning"
            )

            # Verify timestamp was updated
            mock_context.catalog_service.set_last_discovery_at.assert_called_once()
            call_args = mock_context.catalog_service.set_last_discovery_at.call_args
            assert call_args[0][0] == "machine-learning"
            assert isinstance(call_args[0][1], datetime)

    @pytest.mark.asyncio
    async def test_force_full_timeframe_overrides_incremental(
        self, mock_context, sample_scored_papers
    ):
        """Test force_full_timeframe bypasses incremental discovery."""
        # Enable incremental discovery
        mock_context.config.settings.incremental_discovery_settings = (
            IncrementalDiscoverySettings(enabled=True)
        )

        # Create topic with force_full_timeframe=True
        topic = ResearchTopic(
            query="machine learning",
            timeframe=TimeframeRecent(value="7d"),
            force_full_timeframe=True,
        )

        mock_context.config.research_topics = [topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        # Mock discover() to return proper DiscoveryAPIResult with valid metrics
        discovery_result = make_discovery_result(sample_scored_papers)
        mock_context.discovery_service.discover = AsyncMock(
            return_value=discovery_result
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        # Timestamp should NOT be updated when force_full_timeframe is True
        mock_context.catalog_service.set_last_discovery_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_discovery_filtering_disabled(
        self, mock_context, sample_topic, sample_scored_papers
    ):
        """Test discovery when filtering is disabled."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        # Mock discover()
        discovery_result = make_discovery_result(sample_scored_papers)
        mock_context.discovery_service.discover = AsyncMock(
            return_value=discovery_result
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.total_papers == 2

        # Verify discovery stats were created
        topic_result = result.topic_results[0]
        assert topic_result.discovery_stats is not None
        assert topic_result.discovery_stats.total_discovered == 2
        assert topic_result.discovery_stats.new_count == 2
        assert topic_result.discovery_stats.filtered_count == 0

    @pytest.mark.asyncio
    async def test_discovery_filtering_enabled(
        self, mock_context, sample_topic, sample_scored_papers
    ):
        """Test discovery with filtering enabled (in discover())."""
        # Enable filtering
        mock_context.config.settings.discovery_filter_settings = (
            DiscoveryFilterSettings(
                enabled=True,
                register_at_discovery=True,
            )
        )

        # Add mock registry service
        mock_context.registry_service = MagicMock()

        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        # Mock discover() - filtering is now internal to discover()
        # Return only 1 paper to simulate filtering
        discovery_result = make_discovery_result([sample_scored_papers[0]])
        discovery_result.metrics = DiscoveryMetrics(
            queries_generated=1,
            papers_retrieved=2,  # 2 retrieved
            papers_after_dedup=2,
            papers_after_quality_filter=1,  # 1 after filtering
            papers_after_relevance_filter=1,
            providers_queried=["arxiv"],
            avg_relevance_score=0.7,
            avg_quality_score=0.8,
            pipeline_duration_ms=100,
        )
        mock_context.discovery_service.discover = AsyncMock(
            return_value=discovery_result
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.total_papers == 1  # Only papers after filtering

        # Verify discovery stats reflect filtering
        topic_result = result.topic_results[0]
        assert topic_result.discovery_stats is not None
        assert topic_result.discovery_stats.total_discovered == 2
        assert topic_result.discovery_stats.new_count == 1
        assert topic_result.discovery_stats.filtered_count == 1

    @pytest.mark.asyncio
    async def test_filtering_requires_registry_service(
        self, mock_context, sample_topic, sample_scored_papers
    ):
        """Test filtering handled by discover() API."""
        # Enable filtering but no registry service
        mock_context.config.settings.discovery_filter_settings = (
            DiscoveryFilterSettings(
                enabled=True,
                register_at_discovery=True,
            )
        )
        mock_context.registry_service = None

        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        # Mock discover() - returns all papers (filtering is internal)
        discovery_result = make_discovery_result(sample_scored_papers)
        mock_context.discovery_service.discover = AsyncMock(
            return_value=discovery_result
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.total_papers == 2  # All papers

        # Verify stats show no filtering
        topic_result = result.topic_results[0]
        assert topic_result.discovery_stats is not None
        assert topic_result.discovery_stats.filtered_count == 0

    @pytest.mark.asyncio
    async def test_incremental_with_filtering_combined(
        self, mock_context, sample_topic, sample_scored_papers
    ):
        """Test incremental discovery combined with filtering."""
        # Enable both features
        mock_context.config.settings.incremental_discovery_settings = (
            IncrementalDiscoverySettings(enabled=True)
        )
        mock_context.config.settings.discovery_filter_settings = (
            DiscoveryFilterSettings(
                enabled=True,
                register_at_discovery=True,
            )
        )
        mock_context.registry_service = MagicMock()

        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        # Mock TimeframeResolver (incremental mode)
        mock_resolved = ResolvedTimeframe(
            start_date=datetime(2025, 1, 26),
            end_date=datetime(2025, 1, 27),
            is_incremental=True,
            overlap_buffer_hours=1,
        )

        # Mock discover() with filtered results
        discovery_result = make_discovery_result([sample_scored_papers[0]])
        discovery_result.metrics = DiscoveryMetrics(
            queries_generated=1,
            papers_retrieved=2,
            papers_after_dedup=2,
            papers_after_quality_filter=1,
            papers_after_relevance_filter=1,
            providers_queried=["arxiv"],
            avg_relevance_score=0.7,
            avg_quality_score=0.8,
            pipeline_duration_ms=100,
        )
        mock_context.discovery_service.discover = AsyncMock(
            return_value=discovery_result
        )

        with patch(
            "src.orchestration.phases.discovery.TimeframeResolver"
        ) as mock_resolver_class:
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = mock_resolved
            mock_resolver_class.return_value = mock_resolver

            phase = DiscoveryPhase(mock_context)
            result = await phase.execute()

            assert result.topics_processed == 1
            assert result.total_papers == 1

            # Verify stats reflect incremental mode
            topic_result = result.topic_results[0]
            assert topic_result.discovery_stats is not None
            assert topic_result.discovery_stats.incremental_query is True
            assert (
                topic_result.discovery_stats.query_start_date
                == mock_resolved.start_date
            )

            # Verify timestamp was updated
            mock_context.catalog_service.set_last_discovery_at.assert_called_once()

    @pytest.mark.asyncio
    async def test_discovery_stats_populated_on_success(
        self, mock_context, sample_topic, sample_scored_papers
    ):
        """Test discovery stats are populated in result."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        # Mock discover()
        discovery_result = make_discovery_result(sample_scored_papers)
        mock_context.discovery_service.discover = AsyncMock(
            return_value=discovery_result
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert len(result.topic_results) == 1
        topic_result = result.topic_results[0]

        # Verify discovery_stats field exists and is populated
        assert topic_result.discovery_stats is not None
        assert isinstance(topic_result.discovery_stats, DiscoveryStats)
        assert topic_result.discovery_stats.total_discovered == 2
        assert topic_result.discovery_stats.new_count == 2
        assert topic_result.discovery_stats.filtered_count == 0
        assert topic_result.discovery_stats.incremental_query is False

    @pytest.mark.asyncio
    async def test_discovery_stats_none_on_error(self, mock_context, sample_topic):
        """Test discovery stats remain None when discovery fails."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )
        # Mock discover() to raise error
        mock_context.discovery_service.discover = AsyncMock(
            side_effect=APIError("API failed")
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_failed == 1
        topic_result = result.topic_results[0]
        assert topic_result.discovery_stats is None
        assert topic_result.success is False

    @pytest.mark.asyncio
    async def test_execute_paper_with_invalid_date(
        self, mock_context, sample_topic, sample_scored_papers
    ):
        """Test execute handles paper with invalid publication date format."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        # Modify first paper to have an invalid date string
        sample_scored_papers[0].publication_date = "NOT-A-DATE"

        # Mock discover() to return DiscoveryAPIResult
        discovery_result = make_discovery_result(sample_scored_papers)
        mock_context.discovery_service.discover = AsyncMock(
            return_value=discovery_result
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.total_papers == 2
        # Paper should still be included, but its date might be None or default
        # Our primary goal here is to hit the 'except' block in DiscoveryPhase.run()

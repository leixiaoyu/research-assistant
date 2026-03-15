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
    DiscoveryFilterResult,
    ResolvedTimeframe,
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
        self, mock_context, sample_topic, sample_papers
    ):
        """Test execute with single successful topic."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.discovery_service.search.return_value = sample_papers
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.topics_failed == 0
        assert result.total_papers == 2
        mock_context.add_discovered_papers.assert_called_once_with(
            "machine-learning", sample_papers
        )

    @pytest.mark.asyncio
    async def test_execute_topic_api_error(self, mock_context, sample_topic):
        """Test execute handles API errors."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.discovery_service.search.side_effect = APIError("API failed")
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
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
        mock_context.discovery_service.search.side_effect = Exception("Unexpected")
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 0
        assert result.topics_failed == 1

    @pytest.mark.asyncio
    async def test_execute_no_papers_found(self, mock_context, sample_topic):
        """Test execute when no papers found."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.discovery_service.search.return_value = []
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.total_papers == 0

    @pytest.mark.asyncio
    async def test_execute_multiple_topics(self, mock_context, sample_papers):
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
        mock_context.discovery_service.search.return_value = sample_papers
        mock_context.catalog_service.get_or_create_topic.side_effect = [
            MagicMock(topic_slug="topic1"),
            MagicMock(topic_slug="topic2"),
        ]

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
        self, mock_context, sample_topic, sample_papers
    ):
        """Test discovery when incremental mode is disabled."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.discovery_service.search.return_value = sample_papers
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.total_papers == 2
        # Catalog timestamp should NOT be updated when incremental is disabled
        mock_context.catalog_service.set_last_discovery_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_incremental_discovery_enabled(
        self, mock_context, sample_topic, sample_papers
    ):
        """Test discovery with incremental mode enabled."""
        # Enable incremental discovery
        mock_context.config.settings.incremental_discovery_settings = (
            IncrementalDiscoverySettings(enabled=True)
        )

        mock_context.config.research_topics = [sample_topic]
        mock_context.discovery_service.search.return_value = sample_papers
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
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
        self, mock_context, sample_papers
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
        mock_context.discovery_service.search.return_value = sample_papers
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        # Timestamp should NOT be updated when force_full_timeframe is True
        mock_context.catalog_service.set_last_discovery_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_discovery_filtering_disabled(
        self, mock_context, sample_topic, sample_papers
    ):
        """Test discovery when filtering is disabled."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.discovery_service.search.return_value = sample_papers
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
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
        self, mock_context, sample_topic, sample_papers
    ):
        """Test discovery with filtering enabled."""
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
        mock_context.discovery_service.search.return_value = sample_papers
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        # Mock DiscoveryFilter
        mock_filter_result = DiscoveryFilterResult(
            new_papers=[sample_papers[0]],  # 1 new paper
            filtered_papers=[],  # 1 filtered
            stats=DiscoveryStats(
                total_discovered=2,
                new_count=1,
                filtered_count=1,
                filter_breakdown={"doi": 1},
                incremental_query=False,
            ),
        )

        with patch(
            "src.orchestration.phases.discovery.DiscoveryFilter"
        ) as mock_filter_class:
            mock_filter = MagicMock()
            mock_filter.filter_papers = AsyncMock(return_value=mock_filter_result)
            mock_filter_class.return_value = mock_filter

            phase = DiscoveryPhase(mock_context)
            result = await phase.execute()

            assert result.topics_processed == 1
            assert result.total_papers == 1  # Only new papers

            # Verify filter was called
            mock_filter.filter_papers.assert_called_once_with(
                papers=sample_papers,
                topic_slug="machine-learning",
                register_new=True,
            )

            # Verify discovery stats
            topic_result = result.topic_results[0]
            assert topic_result.discovery_stats is not None
            assert topic_result.discovery_stats.total_discovered == 2
            assert topic_result.discovery_stats.new_count == 1
            assert topic_result.discovery_stats.filtered_count == 1

    @pytest.mark.asyncio
    async def test_filtering_requires_registry_service(
        self, mock_context, sample_topic, sample_papers
    ):
        """Test filtering is skipped when registry_service is None."""
        # Enable filtering but no registry service
        mock_context.config.settings.discovery_filter_settings = (
            DiscoveryFilterSettings(
                enabled=True,
                register_at_discovery=True,
            )
        )
        mock_context.registry_service = None

        mock_context.config.research_topics = [sample_topic]
        mock_context.discovery_service.search.return_value = sample_papers
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.total_papers == 2  # All papers (no filtering)

        # Verify stats show no filtering
        topic_result = result.topic_results[0]
        assert topic_result.discovery_stats is not None
        assert topic_result.discovery_stats.filtered_count == 0

    @pytest.mark.asyncio
    async def test_incremental_with_filtering_combined(
        self, mock_context, sample_topic, sample_papers
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
        mock_context.discovery_service.search.return_value = sample_papers
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

        # Mock DiscoveryFilter
        mock_filter_result = DiscoveryFilterResult(
            new_papers=[sample_papers[0]],
            filtered_papers=[],
            stats=DiscoveryStats(
                total_discovered=2,
                new_count=1,
                filtered_count=1,
                filter_breakdown={"doi": 1},
                incremental_query=False,  # Will be updated
            ),
        )

        with (
            patch(
                "src.orchestration.phases.discovery.TimeframeResolver"
            ) as mock_resolver_class,
            patch(
                "src.orchestration.phases.discovery.DiscoveryFilter"
            ) as mock_filter_class,
        ):
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = mock_resolved
            mock_resolver_class.return_value = mock_resolver

            mock_filter = MagicMock()
            mock_filter.filter_papers = AsyncMock(return_value=mock_filter_result)
            mock_filter_class.return_value = mock_filter

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
        self, mock_context, sample_topic, sample_papers
    ):
        """Test discovery stats are populated in result."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.discovery_service.search.return_value = sample_papers
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
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
        mock_context.discovery_service.search.side_effect = APIError("API failed")
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        phase = DiscoveryPhase(mock_context)
        result = await phase.execute()

        assert result.topics_failed == 1
        topic_result = result.topic_results[0]
        assert topic_result.discovery_stats is None
        assert topic_result.success is False

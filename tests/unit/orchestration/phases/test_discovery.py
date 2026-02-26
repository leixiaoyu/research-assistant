"""Tests for DiscoveryPhase."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.orchestration.phases.discovery import (
    DiscoveryPhase,
    DiscoveryResult,
    TopicDiscoveryResult,
)
from src.orchestration.context import PipelineContext
from src.models.config import ResearchTopic, TimeframeRecent
from src.services.providers.base import APIError


@pytest.fixture
def mock_context():
    """Create mock pipeline context."""
    context = MagicMock(spec=PipelineContext)
    context.config = MagicMock()
    context.config.research_topics = []
    context.discovery_service = AsyncMock()
    context.catalog_service = MagicMock()
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
    """Create sample paper metadata (mocked)."""
    paper1 = MagicMock()
    paper1.paper_id = "paper1"
    paper1.title = "Test Paper 1"
    paper2 = MagicMock()
    paper2.paper_id = "paper2"
    paper2.title = "Test Paper 2"
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

"""Unit tests for FeedbackService."""

from unittest.mock import AsyncMock, Mock

import pytest

from src.models.feedback import (
    FeedbackEntry,
    FeedbackRating,
    FeedbackReason,
)
from src.services.feedback.feedback_service import FeedbackService
from src.services.feedback.storage import FeedbackStorage


@pytest.fixture
def mock_storage():
    """Create mock storage."""
    storage = Mock(spec=FeedbackStorage)
    storage.save = AsyncMock()
    storage.load_all = AsyncMock(return_value=[])
    storage.get_by_paper_id = AsyncMock(return_value=None)
    storage.get_by_topic = AsyncMock(return_value=[])
    storage.query = AsyncMock(return_value=[])
    storage.delete = AsyncMock(return_value=True)
    storage.export = AsyncMock(return_value="{}")
    return storage


@pytest.fixture
def mock_registry():
    """Create mock registry service."""
    registry = Mock()
    registry.resolve_identity = AsyncMock(return_value=None)
    return registry


@pytest.fixture
def service(mock_storage):
    """Create FeedbackService with mock storage."""
    return FeedbackService(storage=mock_storage)


@pytest.fixture
def service_with_registry(mock_storage, mock_registry):
    """Create FeedbackService with mock storage and registry."""
    return FeedbackService(storage=mock_storage, registry_service=mock_registry)


class TestFeedbackServiceInit:
    """Tests for FeedbackService initialization."""

    def test_init_with_storage(self, mock_storage):
        """Test initialization with storage only."""
        service = FeedbackService(storage=mock_storage)
        assert service.storage == mock_storage
        assert service.registry_service is None

    def test_init_with_registry(self, mock_storage, mock_registry):
        """Test initialization with storage and registry."""
        service = FeedbackService(storage=mock_storage, registry_service=mock_registry)
        assert service.storage == mock_storage
        assert service.registry_service == mock_registry


class TestFeedbackServiceSubmit:
    """Tests for submit_feedback method."""

    @pytest.mark.asyncio
    async def test_submit_new_feedback(self, service, mock_storage):
        """Test submitting new feedback."""
        entry = await service.submit_feedback(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
        )

        assert entry.paper_id == "test-paper"
        assert entry.rating == "thumbs_up"
        mock_storage.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_with_reasons(self, service, mock_storage):
        """Test submitting feedback with reasons."""
        entry = await service.submit_feedback(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
            reasons=[FeedbackReason.METHODOLOGY, FeedbackReason.NOVELTY],
        )

        assert entry.reasons == ["methodology", "novelty"]

    @pytest.mark.asyncio
    async def test_submit_with_free_text(self, service, mock_storage):
        """Test submitting feedback with free text."""
        entry = await service.submit_feedback(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
            free_text="Great paper!",
        )

        assert entry.free_text == "Great paper!"

    @pytest.mark.asyncio
    async def test_submit_with_topic(self, service, mock_storage):
        """Test submitting feedback with topic."""
        entry = await service.submit_feedback(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
            topic_slug="test-topic",
        )

        assert entry.topic_slug == "test-topic"

    @pytest.mark.asyncio
    async def test_submit_empty_paper_id_raises(self, service):
        """Test that empty paper_id raises ValueError."""
        with pytest.raises(ValueError, match="paper_id cannot be empty"):
            await service.submit_feedback(
                paper_id="",
                rating=FeedbackRating.THUMBS_UP,
            )

    @pytest.mark.asyncio
    async def test_submit_whitespace_paper_id_raises(self, service):
        """Test that whitespace paper_id raises ValueError."""
        with pytest.raises(ValueError, match="paper_id cannot be empty"):
            await service.submit_feedback(
                paper_id="   ",
                rating=FeedbackRating.THUMBS_UP,
            )

    @pytest.mark.asyncio
    async def test_submit_updates_existing(self, service, mock_storage):
        """Test that submit updates existing feedback."""
        existing = FeedbackEntry(
            id="existing-id",
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_DOWN,
            topic_slug="old-topic",
        )
        mock_storage.get_by_paper_id = AsyncMock(return_value=existing)

        entry = await service.submit_feedback(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
        )

        assert entry.id == "existing-id"
        assert entry.rating == "thumbs_up"
        assert entry.topic_slug == "old-topic"  # Preserved from existing

    @pytest.mark.asyncio
    async def test_submit_with_registry_validation(
        self, service_with_registry, mock_registry
    ):
        """Test submit with registry validation."""
        mock_registry.resolve_identity = AsyncMock(return_value=Mock())

        await service_with_registry.submit_feedback(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
        )

        mock_registry.resolve_identity.assert_called_once_with("test-paper")

    @pytest.mark.asyncio
    async def test_submit_registry_error_continues(
        self, service_with_registry, mock_registry, mock_storage
    ):
        """Test submit continues when registry errors."""
        mock_registry.resolve_identity = AsyncMock(
            side_effect=Exception("Registry error")
        )

        # Should not raise
        entry = await service_with_registry.submit_feedback(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
        )

        assert entry.paper_id == "test-paper"
        mock_storage.save.assert_called_once()


class TestFeedbackServiceGetMethods:
    """Tests for get methods."""

    @pytest.mark.asyncio
    async def test_get_feedback_for_paper_found(self, service, mock_storage):
        """Test getting feedback for existing paper."""
        existing = FeedbackEntry(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
        )
        mock_storage.get_by_paper_id = AsyncMock(return_value=existing)

        result = await service.get_feedback_for_paper("test-paper")

        assert result == existing

    @pytest.mark.asyncio
    async def test_get_feedback_for_paper_not_found(self, service, mock_storage):
        """Test getting feedback for non-existent paper."""
        mock_storage.get_by_paper_id = AsyncMock(return_value=None)

        result = await service.get_feedback_for_paper("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_feedback_for_topic(self, service, mock_storage):
        """Test getting feedback for topic."""
        entries = [
            FeedbackEntry(paper_id="p1", rating=FeedbackRating.THUMBS_UP),
            FeedbackEntry(paper_id="p2", rating=FeedbackRating.THUMBS_DOWN),
        ]
        mock_storage.get_by_topic = AsyncMock(return_value=entries)

        result = await service.get_feedback_for_topic("test-topic")

        assert len(result) == 2
        mock_storage.get_by_topic.assert_called_once_with("test-topic", None)

    @pytest.mark.asyncio
    async def test_get_feedback_for_topic_with_filter(self, service, mock_storage):
        """Test getting feedback for topic with rating filter."""
        await service.get_feedback_for_topic("test-topic", FeedbackRating.THUMBS_UP)

        mock_storage.get_by_topic.assert_called_once_with(
            "test-topic", FeedbackRating.THUMBS_UP
        )

    @pytest.mark.asyncio
    async def test_get_positive_feedback(self, service, mock_storage):
        """Test getting positive feedback."""
        await service.get_positive_feedback()
        mock_storage.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_negative_feedback(self, service, mock_storage):
        """Test getting negative feedback."""
        await service.get_negative_feedback()
        mock_storage.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_paper_ids_by_rating(self, service, mock_storage):
        """Test getting paper IDs by rating."""
        entries = [
            FeedbackEntry(paper_id="p1", rating=FeedbackRating.THUMBS_UP),
            FeedbackEntry(paper_id="p2", rating=FeedbackRating.THUMBS_UP),
        ]
        mock_storage.query = AsyncMock(return_value=entries)

        result = await service.get_paper_ids_by_rating(FeedbackRating.THUMBS_UP)

        assert result == ["p1", "p2"]


class TestFeedbackServiceAnalytics:
    """Tests for analytics methods."""

    @pytest.mark.asyncio
    async def test_get_analytics_empty(self, service, mock_storage):
        """Test getting analytics with no data."""
        mock_storage.load_all = AsyncMock(return_value=[])

        analytics = await service.get_analytics()

        assert analytics.total_ratings == 0

    @pytest.mark.asyncio
    async def test_get_analytics_with_data(self, service, mock_storage):
        """Test getting analytics with data."""
        entries = [
            FeedbackEntry(
                paper_id="p1",
                rating=FeedbackRating.THUMBS_UP,
                topic_slug="topic-a",
                reasons=[FeedbackReason.METHODOLOGY],
            ),
            FeedbackEntry(
                paper_id="p2",
                rating=FeedbackRating.THUMBS_DOWN,
                topic_slug="topic-a",
            ),
            FeedbackEntry(
                paper_id="p3",
                rating=FeedbackRating.THUMBS_UP,
                topic_slug="topic-b",
            ),
        ]
        mock_storage.load_all = AsyncMock(return_value=entries)

        analytics = await service.get_analytics()

        assert analytics.total_ratings == 3
        assert analytics.rating_distribution["thumbs_up"] == 2
        assert analytics.rating_distribution["thumbs_down"] == 1
        assert "topic-a" in analytics.topic_breakdown
        assert "topic-b" in analytics.topic_breakdown

    @pytest.mark.asyncio
    async def test_get_analytics_for_topic(self, service, mock_storage):
        """Test getting analytics for specific topic."""
        entries = [
            FeedbackEntry(
                paper_id="p1",
                rating=FeedbackRating.THUMBS_UP,
                topic_slug="topic-a",
            ),
        ]
        mock_storage.get_by_topic = AsyncMock(return_value=entries)

        analytics = await service.get_analytics(topic_slug="topic-a")

        assert analytics.total_ratings == 1
        mock_storage.get_by_topic.assert_called_once_with("topic-a")

    @pytest.mark.asyncio
    async def test_has_sufficient_feedback_true(self, service, mock_storage):
        """Test has_sufficient_feedback returns True when enough."""
        entries = [
            FeedbackEntry(paper_id=f"p{i}", rating=FeedbackRating.THUMBS_UP)
            for i in range(25)
        ]
        mock_storage.get_by_topic = AsyncMock(return_value=entries)

        result = await service.has_sufficient_feedback("topic", min_feedback=20)

        assert result is True

    @pytest.mark.asyncio
    async def test_has_sufficient_feedback_false(self, service, mock_storage):
        """Test has_sufficient_feedback returns False when not enough."""
        entries = [
            FeedbackEntry(paper_id=f"p{i}", rating=FeedbackRating.THUMBS_UP)
            for i in range(10)
        ]
        mock_storage.get_by_topic = AsyncMock(return_value=entries)

        result = await service.has_sufficient_feedback("topic", min_feedback=20)

        assert result is False


class TestFeedbackServiceDelete:
    """Tests for delete methods."""

    @pytest.mark.asyncio
    async def test_delete_feedback_found(self, service, mock_storage):
        """Test deleting existing feedback."""
        existing = FeedbackEntry(
            id="entry-id",
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
        )
        mock_storage.get_by_paper_id = AsyncMock(return_value=existing)
        mock_storage.delete = AsyncMock(return_value=True)

        result = await service.delete_feedback("test-paper")

        assert result is True
        mock_storage.delete.assert_called_once_with("entry-id")

    @pytest.mark.asyncio
    async def test_delete_feedback_not_found(self, service, mock_storage):
        """Test deleting non-existent feedback."""
        mock_storage.get_by_paper_id = AsyncMock(return_value=None)

        result = await service.delete_feedback("nonexistent")

        assert result is False


class TestFeedbackServiceExport:
    """Tests for export methods."""

    @pytest.mark.asyncio
    async def test_export_json(self, service, mock_storage):
        """Test exporting as JSON."""
        mock_storage.export = AsyncMock(return_value='[{"paper_id": "p1"}]')

        result = await service.export_feedback(format="json")

        assert "paper_id" in result
        mock_storage.export.assert_called_once()

    @pytest.mark.asyncio
    async def test_export_csv(self, service, mock_storage):
        """Test exporting as CSV."""
        await service.export_feedback(format="csv")

        mock_storage.export.assert_called_once()

    @pytest.mark.asyncio
    async def test_export_to_file(self, service, mock_storage, tmp_path):
        """Test exporting to file."""
        output = str(tmp_path / "export.json")

        await service.export_feedback(format="json", output_path=output)

        mock_storage.export.assert_called_once()


class TestFeedbackServiceRegistryValidation:
    """Tests for registry validation edge cases."""

    @pytest.mark.asyncio
    async def test_submit_registry_returns_none(
        self, service_with_registry, mock_registry, mock_storage
    ):
        """Test submit when registry resolve_identity returns None."""
        # Registry returns None (paper not found)
        mock_registry.resolve_identity = AsyncMock(return_value=None)

        # Should still succeed with warning logged
        entry = await service_with_registry.submit_feedback(
            paper_id="unknown-paper",
            rating=FeedbackRating.THUMBS_UP,
        )

        assert entry.paper_id == "unknown-paper"
        mock_storage.save.assert_called_once()
        mock_registry.resolve_identity.assert_called_once_with("unknown-paper")

    @pytest.mark.asyncio
    async def test_submit_registry_without_resolve_method(self, mock_storage):
        """Test submit with registry that doesn't have resolve_identity."""
        # Create mock registry without resolve_identity
        mock_registry = Mock(spec=[])

        service = FeedbackService(storage=mock_storage, registry_service=mock_registry)

        # Should succeed without calling resolve_identity
        entry = await service.submit_feedback(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
        )

        assert entry.paper_id == "test-paper"

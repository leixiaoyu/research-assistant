"""Unit tests for NotificationDeduplicator (Phase 3.8).

Tests paper categorization for deduplication-aware notifications:
- New papers (not in registry)
- Retry papers (FAILED/SKIPPED status)
- Duplicate papers (PROCESSED/MAPPED status)
- Graceful fallback when registry unavailable
"""

import pytest
from unittest.mock import MagicMock

from src.services.notification.deduplicator import NotificationDeduplicator
from src.models.notification import DeduplicationResult
from src.models.paper import PaperMetadata
from src.models.registry import (
    IdentityMatch,
    RegistryEntry,
    ProcessingAction,
)


class TestNotificationDeduplicator:
    """Tests for NotificationDeduplicator class."""

    @pytest.fixture
    def mock_registry_service(self) -> MagicMock:
        """Create a mock registry service."""
        return MagicMock()

    @pytest.fixture
    def deduplicator(
        self, mock_registry_service: MagicMock
    ) -> NotificationDeduplicator:
        """Create a deduplicator with mock registry."""
        return NotificationDeduplicator(mock_registry_service)

    @pytest.fixture
    def sample_papers(self) -> list:
        """Create sample papers for testing."""
        return [
            PaperMetadata(
                paper_id="paper-1-id",
                title="Paper 1",
                doi="10.1234/paper1",
                abstract="Abstract 1",
                url="https://example.com/paper1",
            ),
            PaperMetadata(
                paper_id="paper-2-id",
                title="Paper 2",
                doi="10.1234/paper2",
                abstract="Abstract 2",
                url="https://example.com/paper2",
            ),
            PaperMetadata(
                paper_id="paper-3-id",
                title="Paper 3",
                doi="10.1234/paper3",
                abstract="Abstract 3",
                url="https://example.com/paper3",
            ),
        ]

    def test_init_with_registry(self, mock_registry_service: MagicMock) -> None:
        """Test initialization with registry service."""
        deduplicator = NotificationDeduplicator(mock_registry_service)

        assert deduplicator.registry_service is mock_registry_service

    def test_init_without_registry(self) -> None:
        """Test initialization without registry service."""
        deduplicator = NotificationDeduplicator(None)

        assert deduplicator.registry_service is None

    def test_categorize_all_new_papers(
        self,
        deduplicator: NotificationDeduplicator,
        mock_registry_service: MagicMock,
        sample_papers: list,
    ) -> None:
        """Test categorization when all papers are new (not in registry)."""
        # Mock: no papers found in registry
        mock_registry_service.resolve_identity.return_value = IdentityMatch(
            matched=False
        )

        result = deduplicator.categorize_papers(sample_papers)

        assert isinstance(result, DeduplicationResult)
        assert result.new_count == 3
        assert result.retry_count == 0
        assert result.duplicate_count == 0
        assert result.total_checked == 3

    def test_categorize_all_duplicates(
        self,
        deduplicator: NotificationDeduplicator,
        mock_registry_service: MagicMock,
        sample_papers: list,
    ) -> None:
        """Test categorization when all papers are duplicates (PROCESSED status)."""
        # Mock: all papers found with SKIP action (already processed)
        mock_entry = MagicMock(spec=RegistryEntry)
        mock_registry_service.resolve_identity.return_value = IdentityMatch(
            matched=True,
            entry=mock_entry,
            match_method="doi",
        )
        mock_registry_service.determine_action.return_value = (
            ProcessingAction.SKIP,
            mock_entry,
        )

        result = deduplicator.categorize_papers(sample_papers)

        assert result.new_count == 0
        assert result.retry_count == 0
        assert result.duplicate_count == 3
        assert result.total_checked == 3

    def test_categorize_all_retry(
        self,
        deduplicator: NotificationDeduplicator,
        mock_registry_service: MagicMock,
        sample_papers: list,
    ) -> None:
        """Test categorization when all papers are retry (BACKFILL status)."""
        # Mock: all papers found with BACKFILL action (extraction targets changed)
        mock_entry = MagicMock(spec=RegistryEntry)
        mock_registry_service.resolve_identity.return_value = IdentityMatch(
            matched=True,
            entry=mock_entry,
            match_method="doi",
        )
        mock_registry_service.determine_action.return_value = (
            ProcessingAction.BACKFILL,
            mock_entry,
        )

        result = deduplicator.categorize_papers(sample_papers)

        assert result.new_count == 0
        assert result.retry_count == 3
        assert result.duplicate_count == 0
        assert result.total_checked == 3

    def test_categorize_mixed_papers(
        self,
        deduplicator: NotificationDeduplicator,
        mock_registry_service: MagicMock,
        sample_papers: list,
    ) -> None:
        """Test categorization with mixed paper statuses."""
        mock_entry = MagicMock(spec=RegistryEntry)

        # Setup different responses for each paper
        def resolve_side_effect(paper: PaperMetadata) -> IdentityMatch:
            if paper.doi == "10.1234/paper1":
                return IdentityMatch(matched=False)  # New
            return IdentityMatch(matched=True, entry=mock_entry, match_method="doi")

        def action_side_effect(paper, topic_slug, extraction_targets):
            if paper.doi == "10.1234/paper2":
                return ProcessingAction.BACKFILL, mock_entry  # Retry
            return ProcessingAction.SKIP, mock_entry  # Duplicate

        mock_registry_service.resolve_identity.side_effect = resolve_side_effect
        mock_registry_service.determine_action.side_effect = action_side_effect

        result = deduplicator.categorize_papers(sample_papers)

        assert result.new_count == 1  # paper1
        assert result.retry_count == 1  # paper2
        assert result.duplicate_count == 1  # paper3
        assert result.total_checked == 3

    def test_categorize_map_only_as_duplicate(
        self,
        deduplicator: NotificationDeduplicator,
        mock_registry_service: MagicMock,
        sample_papers: list,
    ) -> None:
        """Test MAP_ONLY action is categorized as duplicate."""
        mock_entry = MagicMock(spec=RegistryEntry)
        mock_registry_service.resolve_identity.return_value = IdentityMatch(
            matched=True,
            entry=mock_entry,
            match_method="doi",
        )
        mock_registry_service.determine_action.return_value = (
            ProcessingAction.MAP_ONLY,
            mock_entry,
        )

        result = deduplicator.categorize_papers(sample_papers)

        assert result.new_count == 0
        assert result.duplicate_count == 3

    def test_categorize_full_process_as_new(
        self,
        deduplicator: NotificationDeduplicator,
        mock_registry_service: MagicMock,
        sample_papers: list,
    ) -> None:
        """Test FULL_PROCESS action is categorized as new."""
        mock_entry = MagicMock(spec=RegistryEntry)
        mock_registry_service.resolve_identity.return_value = IdentityMatch(
            matched=True,
            entry=mock_entry,
            match_method="doi",
        )
        mock_registry_service.determine_action.return_value = (
            ProcessingAction.FULL_PROCESS,
            None,
        )

        result = deduplicator.categorize_papers(sample_papers)

        assert result.new_count == 3

    def test_graceful_fallback_no_registry(
        self,
        sample_papers: list,
    ) -> None:
        """Test all papers treated as new when registry unavailable."""
        deduplicator = NotificationDeduplicator(None)

        result = deduplicator.categorize_papers(sample_papers)

        assert result.new_count == 3
        assert result.retry_count == 0
        assert result.duplicate_count == 0

    def test_graceful_fallback_registry_error(
        self,
        deduplicator: NotificationDeduplicator,
        mock_registry_service: MagicMock,
        sample_papers: list,
    ) -> None:
        """Test papers treated as new on registry error."""
        mock_registry_service.resolve_identity.side_effect = Exception("Registry error")

        result = deduplicator.categorize_papers(sample_papers)

        # All papers should be treated as new due to error
        assert result.new_count == 3
        assert result.retry_count == 0
        assert result.duplicate_count == 0

    def test_empty_paper_list(
        self,
        deduplicator: NotificationDeduplicator,
    ) -> None:
        """Test categorization with empty paper list."""
        result = deduplicator.categorize_papers([])

        assert result.new_count == 0
        assert result.retry_count == 0
        assert result.duplicate_count == 0
        assert result.total_checked == 0

    def test_matched_but_no_entry_treated_as_new(
        self,
        deduplicator: NotificationDeduplicator,
        mock_registry_service: MagicMock,
        sample_papers: list,
    ) -> None:
        """Test edge case where match.matched=True but entry is None."""
        mock_registry_service.resolve_identity.return_value = IdentityMatch(
            matched=True,
            entry=None,  # Edge case: matched but no entry
        )

        result = deduplicator.categorize_papers(sample_papers)

        # Should be treated as new
        assert result.new_count == 3

    def test_paper_data_preserved_in_result(
        self,
        deduplicator: NotificationDeduplicator,
        mock_registry_service: MagicMock,
    ) -> None:
        """Test paper data is correctly preserved in result."""
        paper = PaperMetadata(
            paper_id="test-paper-id",
            title="Test Paper",
            doi="10.1234/test",
            abstract="Test abstract",
            url="https://example.com/test",
        )
        mock_registry_service.resolve_identity.return_value = IdentityMatch(
            matched=False
        )

        result = deduplicator.categorize_papers([paper])

        assert len(result.new_papers) == 1
        assert result.new_papers[0]["title"] == "Test Paper"
        assert result.new_papers[0]["doi"] == "10.1234/test"

    def test_partial_error_handling(
        self,
        deduplicator: NotificationDeduplicator,
        mock_registry_service: MagicMock,
        sample_papers: list,
    ) -> None:
        """Test partial errors don't break entire categorization."""
        call_count = 0

        def resolve_with_partial_error(paper: PaperMetadata) -> IdentityMatch:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Partial error")
            return IdentityMatch(matched=False)

        mock_registry_service.resolve_identity.side_effect = resolve_with_partial_error

        result = deduplicator.categorize_papers(sample_papers)

        # All should be treated as new (including the one with error)
        assert result.new_count == 3
        assert result.total_checked == 3

    def test_unknown_action_treated_as_new(
        self,
        deduplicator: NotificationDeduplicator,
        mock_registry_service: MagicMock,
        sample_papers: list,
    ) -> None:
        """Test unknown/unexpected action is treated as new (defensive code)."""
        mock_entry = MagicMock(spec=RegistryEntry)
        mock_registry_service.resolve_identity.return_value = IdentityMatch(
            matched=True,
            entry=mock_entry,
            match_method="doi",
        )
        # Return a mock action that's not a valid ProcessingAction
        mock_unknown_action = MagicMock()
        mock_unknown_action.__eq__ = lambda self, other: False
        mock_registry_service.determine_action.return_value = (
            mock_unknown_action,
            mock_entry,
        )

        result = deduplicator.categorize_papers(sample_papers)

        # Unknown action should be treated as new (fail-safe)
        assert result.new_count == 3

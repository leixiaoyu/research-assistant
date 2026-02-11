"""Tests for Phase 3.5 Registry models."""

import pytest

from src.models.registry import (
    ProcessingAction,
    RegistryEntry,
    IdentityMatch,
    RegistryState,
)


class TestProcessingAction:
    """Tests for ProcessingAction enum."""

    def test_full_process_value(self):
        """Test FULL_PROCESS enum value."""
        assert ProcessingAction.FULL_PROCESS.value == "full_process"

    def test_backfill_value(self):
        """Test BACKFILL enum value."""
        assert ProcessingAction.BACKFILL.value == "backfill"

    def test_map_only_value(self):
        """Test MAP_ONLY enum value."""
        assert ProcessingAction.MAP_ONLY.value == "map_only"

    def test_skip_value(self):
        """Test SKIP enum value."""
        assert ProcessingAction.SKIP.value == "skip"


class TestRegistryEntry:
    """Tests for RegistryEntry model."""

    def test_create_minimal_entry(self):
        """Test creating entry with minimal fields."""
        entry = RegistryEntry(
            title_normalized="test paper title",
            extraction_target_hash="sha256:abc123",
        )

        assert entry.title_normalized == "test paper title"
        assert entry.extraction_target_hash == "sha256:abc123"
        assert entry.paper_id is not None  # UUID generated
        assert entry.identifiers == {}
        assert entry.topic_affiliations == []

    def test_create_full_entry(self):
        """Test creating entry with all fields."""
        entry = RegistryEntry(
            paper_id="test-uuid",
            identifiers={
                "doi": "10.1234/test",
                "arxiv": "2301.12345",
            },
            title_normalized="attention is all you need",
            extraction_target_hash="sha256:def456",
            topic_affiliations=["nlp-research", "transformers"],
            pdf_path="/data/pdfs/test.pdf",
            markdown_path="/data/md/test.md",
        )

        assert entry.paper_id == "test-uuid"
        assert entry.identifiers["doi"] == "10.1234/test"
        assert entry.identifiers["arxiv"] == "2301.12345"
        assert "nlp-research" in entry.topic_affiliations

    def test_doi_validation_valid(self):
        """Test valid DOI format."""
        entry = RegistryEntry(
            identifiers={"doi": "10.1234/example.123"},
            title_normalized="test",
            extraction_target_hash="sha256:abc",
        )
        assert entry.identifiers["doi"] == "10.1234/example.123"

    def test_doi_validation_invalid(self):
        """Test invalid DOI format raises error."""
        with pytest.raises(ValueError, match="Invalid DOI format"):
            RegistryEntry(
                identifiers={"doi": "invalid-doi"},
                title_normalized="test",
                extraction_target_hash="sha256:abc",
            )

    def test_arxiv_validation_valid_new_format(self):
        """Test valid ArXiv ID (new format)."""
        entry = RegistryEntry(
            identifiers={"arxiv": "2301.12345"},
            title_normalized="test",
            extraction_target_hash="sha256:abc",
        )
        assert entry.identifiers["arxiv"] == "2301.12345"

    def test_arxiv_validation_valid_old_format(self):
        """Test valid ArXiv ID (old format)."""
        entry = RegistryEntry(
            identifiers={"arxiv": "cs/0601001"},
            title_normalized="test",
            extraction_target_hash="sha256:abc",
        )
        assert entry.identifiers["arxiv"] == "cs/0601001"

    def test_arxiv_validation_invalid(self):
        """Test invalid ArXiv ID raises error."""
        with pytest.raises(ValueError, match="Invalid ArXiv ID format"):
            RegistryEntry(
                identifiers={"arxiv": "invalid-arxiv"},
                title_normalized="test",
                extraction_target_hash="sha256:abc",
            )

    def test_topic_affiliation_validation_valid(self):
        """Test valid topic slug."""
        entry = RegistryEntry(
            title_normalized="test",
            extraction_target_hash="sha256:abc",
            topic_affiliations=["nlp-research", "deep-learning"],
        )
        assert len(entry.topic_affiliations) == 2

    def test_topic_affiliation_validation_invalid(self):
        """Test invalid topic slug (uppercase) raises error."""
        with pytest.raises(ValueError, match="Invalid topic slug"):
            RegistryEntry(
                title_normalized="test",
                extraction_target_hash="sha256:abc",
                topic_affiliations=["Invalid_Slug"],
            )

    def test_add_topic_affiliation_new(self):
        """Test adding a new topic affiliation."""
        entry = RegistryEntry(
            title_normalized="test",
            extraction_target_hash="sha256:abc",
            topic_affiliations=["existing-topic"],
        )

        result = entry.add_topic_affiliation("new-topic")

        assert result is True
        assert "new-topic" in entry.topic_affiliations
        assert len(entry.topic_affiliations) == 2

    def test_add_topic_affiliation_duplicate(self):
        """Test adding duplicate topic affiliation."""
        entry = RegistryEntry(
            title_normalized="test",
            extraction_target_hash="sha256:abc",
            topic_affiliations=["existing-topic"],
        )

        result = entry.add_topic_affiliation("existing-topic")

        assert result is False
        assert len(entry.topic_affiliations) == 1

    def test_empty_identifier_values_skipped(self):
        """Test that empty identifier values are skipped."""
        entry = RegistryEntry(
            identifiers={"doi": "", "arxiv": "  "},
            title_normalized="test",
            extraction_target_hash="sha256:abc",
        )
        assert entry.identifiers == {}


class TestIdentityMatch:
    """Tests for IdentityMatch model."""

    def test_no_match(self):
        """Test creating a no-match result."""
        match = IdentityMatch(matched=False)

        assert match.matched is False
        assert match.entry is None
        assert match.match_method is None

    def test_doi_match(self):
        """Test creating a DOI match result."""
        entry = RegistryEntry(
            title_normalized="test",
            extraction_target_hash="sha256:abc",
        )

        match = IdentityMatch(
            matched=True,
            entry=entry,
            match_method="doi",
        )

        assert match.matched is True
        assert match.entry is not None
        assert match.match_method == "doi"

    def test_title_match_with_similarity(self):
        """Test creating a title match result with similarity score."""
        entry = RegistryEntry(
            title_normalized="test",
            extraction_target_hash="sha256:abc",
        )

        match = IdentityMatch(
            matched=True,
            entry=entry,
            match_method="title",
            similarity_score=0.97,
        )

        assert match.match_method == "title"
        assert match.similarity_score == 0.97


class TestRegistryState:
    """Tests for RegistryState model."""

    def test_create_empty_state(self):
        """Test creating empty registry state."""
        state = RegistryState()

        assert state.version == "1.0"
        assert state.get_entry_count() == 0
        assert len(state.doi_index) == 0
        assert len(state.provider_id_index) == 0

    def test_add_entry_with_doi(self):
        """Test adding entry with DOI updates indexes."""
        state = RegistryState()
        entry = RegistryEntry(
            identifiers={"doi": "10.1234/test"},
            title_normalized="test",
            extraction_target_hash="sha256:abc",
        )

        state.add_entry(entry)

        assert state.get_entry_count() == 1
        assert "10.1234/test" in state.doi_index
        assert state.doi_index["10.1234/test"] == entry.paper_id

    def test_add_entry_with_arxiv(self):
        """Test adding entry with ArXiv ID updates indexes."""
        state = RegistryState()
        entry = RegistryEntry(
            identifiers={"arxiv": "2301.12345"},
            title_normalized="test",
            extraction_target_hash="sha256:abc",
        )

        state.add_entry(entry)

        assert "arxiv:2301.12345" in state.provider_id_index
        assert state.provider_id_index["arxiv:2301.12345"] == entry.paper_id

    def test_add_entry_with_semantic_scholar(self):
        """Test adding entry with Semantic Scholar ID updates indexes."""
        state = RegistryState()
        entry = RegistryEntry(
            identifiers={"semantic_scholar": "abc123def456"},
            title_normalized="test",
            extraction_target_hash="sha256:abc",
        )

        state.add_entry(entry)

        assert "semantic_scholar:abc123def456" in state.provider_id_index

    def test_add_multiple_entries(self):
        """Test adding multiple entries."""
        state = RegistryState()

        for i in range(3):
            entry = RegistryEntry(
                identifiers={"doi": f"10.1234/test{i}"},
                title_normalized=f"test paper {i}",
                extraction_target_hash=f"sha256:hash{i}",
            )
            state.add_entry(entry)

        assert state.get_entry_count() == 3
        assert len(state.doi_index) == 3

    def test_updated_at_changes_on_add(self):
        """Test that updated_at changes when adding entries."""
        state = RegistryState()
        original_time = state.updated_at

        import time

        time.sleep(0.01)

        entry = RegistryEntry(
            title_normalized="test",
            extraction_target_hash="sha256:abc",
        )
        state.add_entry(entry)

        assert state.updated_at > original_time

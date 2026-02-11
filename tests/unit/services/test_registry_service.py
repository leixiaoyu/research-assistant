"""Tests for Phase 3.5 Registry Service."""

import pytest
import json

from src.services.registry_service import RegistryService
from src.models.registry import ProcessingAction
from src.models.paper import PaperMetadata
from src.models.extraction import ExtractionTarget


@pytest.fixture
def temp_registry_path(tmp_path):
    """Create a temporary registry path."""
    return tmp_path / "registry.json"


@pytest.fixture
def service(temp_registry_path):
    """Create a registry service with temporary path."""
    return RegistryService(registry_path=temp_registry_path)


@pytest.fixture
def sample_paper():
    """Create a sample paper metadata."""
    return PaperMetadata(
        paper_id="2301.12345",
        title="Attention Is All You Need",
        abstract="We propose a new transformer architecture...",
        url="https://arxiv.org/abs/2301.12345",
        doi="10.1234/attention",
    )


@pytest.fixture
def sample_targets():
    """Create sample extraction targets."""
    return [
        ExtractionTarget(
            name="prompts",
            description="Extract system prompts",
            output_format="list",
        ),
        ExtractionTarget(
            name="code",
            description="Extract code snippets",
            output_format="code",
        ),
    ]


class TestRegistryServiceLoad:
    """Tests for registry loading."""

    def test_load_creates_new_registry(self, service, temp_registry_path):
        """Test loading creates new registry if file doesn't exist."""
        state = service.load()

        assert state is not None
        assert state.get_entry_count() == 0

    def test_load_existing_registry(self, service, temp_registry_path):
        """Test loading existing registry file."""
        # Create a registry file
        data = {
            "version": "1.0",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "entries": {},
            "doi_index": {},
            "provider_id_index": {},
        }
        temp_registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp_registry_path.write_text(json.dumps(data))

        state = service.load()

        assert state.version == "1.0"

    def test_load_corrupted_creates_backup(self, service, temp_registry_path):
        """Test loading corrupted file creates backup and new registry."""
        # Create a corrupted registry file
        temp_registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp_registry_path.write_text("{ invalid json")

        state = service.load()

        # Should create new empty registry
        assert state.get_entry_count() == 0

        # Should create backup
        backup_path = temp_registry_path.with_suffix(".json.backup")
        assert backup_path.exists()

    def test_load_caches_state(self, service, temp_registry_path):
        """Test that load caches state for subsequent calls."""
        state1 = service.load()
        state2 = service.load()

        assert state1 is state2


class TestRegistryServiceSave:
    """Tests for registry saving."""

    def test_save_creates_file(self, service, temp_registry_path):
        """Test save creates registry file."""
        service.load()
        result = service.save()

        assert result is True
        assert temp_registry_path.exists()

    def test_save_atomic(self, service, temp_registry_path):
        """Test save is atomic (no temp file left on success)."""
        service.load()
        service.save()

        # No temp files should exist
        temp_files = list(temp_registry_path.parent.glob(".registry_*.tmp"))
        assert len(temp_files) == 0

    def test_save_preserves_entries(self, service, temp_registry_path, sample_paper):
        """Test save preserves all entries."""
        service.load()
        service.register_paper(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=[],
        )

        # Force reload
        service._state = None
        state = service.load()

        assert state.get_entry_count() == 1

    def test_save_without_load_returns_false(self, temp_registry_path):
        """Test save without load returns False."""
        service = RegistryService(registry_path=temp_registry_path)
        result = service.save()

        assert result is False


class TestRegistryServiceIdentityResolution:
    """Tests for identity resolution."""

    def test_resolve_by_doi(self, service, sample_paper):
        """Test identity resolution by DOI."""
        # Register a paper
        entry = service.register_paper(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=[],
        )

        # Create a new paper with same DOI but different paper_id
        new_paper = PaperMetadata(
            paper_id="different-id",
            title="Different Title",
            doi="10.1234/attention",  # Same DOI
            url="https://example.com",
        )

        match = service.resolve_identity(new_paper)

        assert match.matched is True
        assert match.entry.paper_id == entry.paper_id
        assert match.match_method == "doi"

    def test_resolve_by_arxiv_id(self, service):
        """Test identity resolution by ArXiv ID."""
        paper1 = PaperMetadata(
            paper_id="2301.12345",
            title="Test Paper",
            url="https://arxiv.org/abs/2301.12345",
        )

        entry = service.register_paper(
            paper1,
            topic_slug="test-topic",
            extraction_targets=[],
        )

        # Paper with same ArXiv ID
        paper2 = PaperMetadata(
            paper_id="2301.12345",
            title="Different Title",
            url="https://example.com",
        )

        match = service.resolve_identity(paper2)

        assert match.matched is True
        assert match.entry.paper_id == entry.paper_id
        assert match.match_method == "arxiv"

    def test_resolve_by_fuzzy_title(self, service):
        """Test identity resolution by fuzzy title matching."""
        paper1 = PaperMetadata(
            paper_id="paper1",
            title="Attention Is All You Need",
            url="https://example.com/1",
        )

        entry = service.register_paper(
            paper1,
            topic_slug="test-topic",
            extraction_targets=[],
        )

        # Paper with very similar title (normalized: "attention is all you need")
        paper2 = PaperMetadata(
            paper_id="paper2",
            title="ATTENTION IS ALL YOU NEED",  # Same when normalized
            url="https://example.com/2",
        )

        match = service.resolve_identity(paper2)

        assert match.matched is True
        assert match.entry.paper_id == entry.paper_id
        assert match.match_method == "title"
        assert match.similarity_score == 1.0

    def test_no_match_for_different_paper(self, service, sample_paper):
        """Test no match for completely different paper."""
        service.register_paper(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=[],
        )

        different_paper = PaperMetadata(
            paper_id="completely-different",
            title="Completely Different Paper Title",
            url="https://example.com/different",
        )

        match = service.resolve_identity(different_paper)

        assert match.matched is False


class TestRegistryServiceDetermineAction:
    """Tests for action determination."""

    def test_new_paper_full_process(self, service, sample_paper, sample_targets):
        """Test new paper returns FULL_PROCESS."""
        action, entry = service.determine_action(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=sample_targets,
        )

        assert action == ProcessingAction.FULL_PROCESS
        assert entry is None

    def test_existing_paper_same_targets_same_topic_skip(
        self, service, sample_paper, sample_targets
    ):
        """Test existing paper with same targets and topic returns SKIP."""
        # Register paper
        service.register_paper(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=sample_targets,
        )

        action, entry = service.determine_action(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=sample_targets,
        )

        assert action == ProcessingAction.SKIP
        assert entry is not None

    def test_existing_paper_same_targets_different_topic_map_only(
        self, service, sample_paper, sample_targets
    ):
        """Test paper with same targets but different topic returns MAP_ONLY."""
        # Register paper for first topic
        service.register_paper(
            sample_paper,
            topic_slug="first-topic",
            extraction_targets=sample_targets,
        )

        action, entry = service.determine_action(
            sample_paper,
            topic_slug="second-topic",
            extraction_targets=sample_targets,
        )

        assert action == ProcessingAction.MAP_ONLY
        assert entry is not None

    def test_existing_paper_different_targets_backfill(
        self, service, sample_paper, sample_targets
    ):
        """Test existing paper with different targets returns BACKFILL."""
        # Register paper with original targets
        service.register_paper(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=sample_targets,
        )

        # New targets with additional extraction
        new_targets = sample_targets + [
            ExtractionTarget(
                name="metrics",
                description="Extract evaluation metrics",
                output_format="json",
            )
        ]

        action, entry = service.determine_action(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=new_targets,
        )

        assert action == ProcessingAction.BACKFILL
        assert entry is not None


class TestRegistryServiceRegisterPaper:
    """Tests for paper registration."""

    def test_register_new_paper(self, service, sample_paper, sample_targets):
        """Test registering a new paper."""
        entry = service.register_paper(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=sample_targets,
            pdf_path="/data/pdfs/test.pdf",
            markdown_path="/data/md/test.md",
        )

        assert entry is not None
        assert entry.paper_id is not None
        assert "test-topic" in entry.topic_affiliations
        assert entry.pdf_path == "/data/pdfs/test.pdf"
        assert entry.markdown_path == "/data/md/test.md"

    def test_register_updates_indexes(self, service, sample_paper, sample_targets):
        """Test registering paper updates indexes."""
        entry = service.register_paper(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=sample_targets,
        )

        state = service.load()

        # DOI should be indexed
        assert sample_paper.doi in state.doi_index
        assert state.doi_index[sample_paper.doi] == entry.paper_id

    def test_register_existing_paper_updates(
        self, service, sample_paper, sample_targets
    ):
        """Test registering existing paper updates it."""
        # First registration
        entry1 = service.register_paper(
            sample_paper,
            topic_slug="topic-one",
            extraction_targets=sample_targets,
        )

        # Update with new topic
        entry2 = service.register_paper(
            sample_paper,
            topic_slug="topic-two",
            extraction_targets=sample_targets,
            existing_entry=entry1,
        )

        assert entry2.paper_id == entry1.paper_id
        assert "topic-one" in entry2.topic_affiliations
        assert "topic-two" in entry2.topic_affiliations


class TestRegistryServiceTopicAffiliation:
    """Tests for topic affiliation management."""

    def test_add_topic_affiliation(self, service, sample_paper):
        """Test adding topic affiliation."""
        entry = service.register_paper(
            sample_paper,
            topic_slug="first-topic",
            extraction_targets=[],
        )

        result = service.add_topic_affiliation(entry, "second-topic")

        assert result is True

        # Reload and verify
        service._state = None
        updated_entry = service.get_entry(entry.paper_id)
        assert "second-topic" in updated_entry.topic_affiliations

    def test_add_duplicate_affiliation_returns_false(self, service, sample_paper):
        """Test adding duplicate affiliation returns False."""
        entry = service.register_paper(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=[],
        )

        result = service.add_topic_affiliation(entry, "test-topic")

        assert result is False


class TestRegistryServiceQueries:
    """Tests for registry queries."""

    def test_get_entry(self, service, sample_paper):
        """Test getting entry by paper ID."""
        entry = service.register_paper(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=[],
        )

        retrieved = service.get_entry(entry.paper_id)

        assert retrieved is not None
        assert retrieved.paper_id == entry.paper_id

    def test_get_entry_not_found(self, service):
        """Test getting non-existent entry returns None."""
        service.load()
        result = service.get_entry("non-existent-id")
        assert result is None

    def test_get_entries_for_topic(self, service):
        """Test getting entries for a topic."""
        # Register multiple papers
        for i in range(3):
            paper = PaperMetadata(
                paper_id=f"paper{i}",
                title=f"Paper {i}",
                url=f"https://example.com/{i}",
            )
            service.register_paper(
                paper,
                topic_slug="shared-topic",
                extraction_targets=[],
            )

        # Register one paper for different topic
        other_paper = PaperMetadata(
            paper_id="other",
            title="Other Paper",
            url="https://example.com/other",
        )
        service.register_paper(
            other_paper,
            topic_slug="other-topic",
            extraction_targets=[],
        )

        entries = service.get_entries_for_topic("shared-topic")

        assert len(entries) == 3

    def test_get_stats(self, service, sample_paper):
        """Test getting registry statistics."""
        service.register_paper(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=[],
        )

        stats = service.get_stats()

        assert stats["total_entries"] == 1
        assert stats["total_dois"] == 1
        assert "created_at" in stats
        assert "updated_at" in stats


class TestRegistryServiceClear:
    """Tests for registry clearing."""

    def test_clear_removes_all_entries(self, service, sample_paper):
        """Test clear removes all entries."""
        service.register_paper(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=[],
        )

        service.clear()

        state = service.load()
        assert state.get_entry_count() == 0


class TestRegistryServiceErrorHandling:
    """Tests for error handling paths."""

    def test_chmod_dir_failure_logs_warning(self, temp_registry_path, mocker):
        """Test chmod failure on directory logs warning."""
        service = RegistryService(registry_path=temp_registry_path)

        # Mock os.chmod to raise OSError
        mocker.patch("os.chmod", side_effect=OSError("Permission denied"))

        # Should not raise, just log warning
        service._ensure_directory()

    def test_chmod_file_failure_logs_warning(self, temp_registry_path, mocker):
        """Test chmod failure on file logs warning."""
        service = RegistryService(registry_path=temp_registry_path)
        temp_registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp_registry_path.write_text("{}")

        # Mock os.chmod to raise OSError
        mocker.patch("os.chmod", side_effect=OSError("Permission denied"))

        # Should not raise, just log warning
        service._set_file_permissions()

    def test_load_non_json_file_creates_backup(self, temp_registry_path):
        """Test loading non-JSON file creates backup."""
        temp_registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp_registry_path.write_text("not valid json {{{")

        service = RegistryService(registry_path=temp_registry_path)
        state = service.load()

        # Should return empty state
        assert state.get_entry_count() == 0
        # Backup should exist
        backup_path = temp_registry_path.with_suffix(".json.backup")
        assert backup_path.exists()

    def test_load_other_error_returns_empty_state(self, temp_registry_path, mocker):
        """Test other load errors return empty state."""
        temp_registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp_registry_path.write_text('{"version": "1.0"}')

        # Mock RegistryState.model_validate to raise
        from src.models.registry import RegistryState

        mocker.patch.object(
            RegistryState,
            "model_validate",
            side_effect=RuntimeError("Validation failed"),
        )

        service = RegistryService(registry_path=temp_registry_path)
        state = service.load()

        # Should return empty state
        assert state.get_entry_count() == 0

    def test_save_temp_file_error_cleanup(self, temp_registry_path, mocker):
        """Test save cleans up temp file on error."""
        service = RegistryService(registry_path=temp_registry_path)
        service.load()

        # Mock os.fdopen to raise after temp file is created
        mocker.patch("os.fdopen", side_effect=OSError("Write failed"))

        result = service.save()

        # Should return False on error
        assert result is False

    def test_add_topic_affiliation_entry_not_in_state(self, service, sample_paper):
        """Test adding affiliation to entry not in state."""
        # Create a detached entry
        from src.models.registry import RegistryEntry

        detached_entry = RegistryEntry(
            paper_id="not-in-state",
            title_normalized="test",
            extraction_target_hash="sha256:abc",
        )

        service.load()  # Initialize state
        result = service.add_topic_affiliation(detached_entry, "new-topic")

        assert result is False

    def test_resolve_by_semantic_scholar_id(self, service):
        """Test identity resolution by Semantic Scholar ID."""
        paper1 = PaperMetadata(
            paper_id="abc123def456",  # Non-ArXiv format = Semantic Scholar
            title="Test Paper",
            url="https://semanticscholar.org/paper/abc123def456",
        )

        entry = service.register_paper(
            paper1,
            topic_slug="test-topic",
            extraction_targets=[],
        )

        # Paper with same Semantic Scholar ID
        paper2 = PaperMetadata(
            paper_id="abc123def456",
            title="Different Title",
            url="https://example.com",
        )

        match = service.resolve_identity(paper2)

        assert match.matched is True
        assert match.entry.paper_id == entry.paper_id
        assert match.match_method == "semantic_scholar"

    def test_register_paper_with_paths(self, service, sample_paper, sample_targets):
        """Test registering paper with PDF and markdown paths."""
        entry = service.register_paper(
            sample_paper,
            topic_slug="test-topic",
            extraction_targets=sample_targets,
            pdf_path="/data/pdfs/test.pdf",
            markdown_path="/data/md/test.md",
        )

        assert entry.pdf_path == "/data/pdfs/test.pdf"
        assert entry.markdown_path == "/data/md/test.md"

    def test_register_existing_entry_updates_paths(
        self, service, sample_paper, sample_targets
    ):
        """Test updating existing entry with new paths."""
        # First registration without paths
        entry1 = service.register_paper(
            sample_paper,
            topic_slug="topic-one",
            extraction_targets=sample_targets,
        )

        assert entry1.pdf_path is None
        assert entry1.markdown_path is None

        # Update with paths
        entry2 = service.register_paper(
            sample_paper,
            topic_slug="topic-two",
            extraction_targets=sample_targets,
            pdf_path="/data/pdfs/new.pdf",
            markdown_path="/data/md/new.md",
            existing_entry=entry1,
        )

        assert entry2.pdf_path == "/data/pdfs/new.pdf"
        assert entry2.markdown_path == "/data/md/new.md"

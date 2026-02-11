"""Tests for Phase 3.6 SynthesisEngine."""

import pytest
from pathlib import Path

from src.output.synthesis_engine import (
    SynthesisEngine,
    KNOWLEDGE_BASE_FILENAME,
)
from src.models.synthesis import (
    KnowledgeBaseEntry,
    UserNoteAnchor,
)
from src.models.registry import RegistryEntry


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create temporary output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


@pytest.fixture
def mock_registry_service(mocker):
    """Create mock registry service."""
    mock = mocker.MagicMock()
    mock.get_entries_for_topic.return_value = []
    mock.load.return_value = mocker.MagicMock(entries={})
    return mock


@pytest.fixture
def engine(temp_output_dir, mock_registry_service):
    """Create SynthesisEngine with mocked dependencies."""
    return SynthesisEngine(
        registry_service=mock_registry_service,
        output_base_dir=temp_output_dir,
    )


@pytest.fixture
def sample_registry_entry():
    """Create a sample registry entry."""
    return RegistryEntry(
        paper_id="test-paper-id",
        identifiers={"doi": "10.1234/test", "arxiv": "2301.12345"},
        title_normalized="test paper title",
        extraction_target_hash="sha256:abc123",
        topic_affiliations=["test-topic"],
        pdf_path="/data/test.pdf",
        metadata_snapshot={
            "title": "Test Paper Title",
            "authors": ["Author A", "Author B"],
            "abstract": "This is a test abstract.",
            "url": "https://example.com/paper",
            "quality_score": 85.0,
            "publication_date": "2025-01-15",
        },
    )


class TestSynthesisEngineInit:
    """Tests for SynthesisEngine initialization."""

    def test_init_creates_engine(self, temp_output_dir, mock_registry_service):
        """Test engine initialization."""
        engine = SynthesisEngine(
            registry_service=mock_registry_service,
            output_base_dir=temp_output_dir,
        )

        assert engine.registry_service == mock_registry_service
        assert engine.output_base_dir == temp_output_dir

    def test_init_with_defaults(self):
        """Test engine initialization with defaults."""
        engine = SynthesisEngine()

        assert engine.registry_service is not None
        assert engine.output_base_dir == Path("output")


class TestEnsureTopicDirectory:
    """Tests for topic directory creation."""

    def test_creates_directory_structure(self, engine, temp_output_dir):
        """Test that directory structure is created."""
        topic_dir = engine._ensure_topic_directory("test-topic")

        assert topic_dir.exists()
        assert (topic_dir / "runs").exists()
        assert (topic_dir / "papers").exists()

    def test_sanitizes_topic_slug(self, engine, temp_output_dir):
        """Test that topic slug is sanitized."""
        # Attempt directory traversal
        topic_dir = engine._ensure_topic_directory("../malicious")

        # Should not create directory outside output
        assert (
            temp_output_dir in topic_dir.parents or topic_dir.parent == temp_output_dir
        )


class TestEntryToKBEntry:
    """Tests for registry entry conversion."""

    def test_converts_full_entry(self, engine, sample_registry_entry):
        """Test converting a full registry entry."""
        kb_entry = engine._entry_to_kb_entry(sample_registry_entry)

        assert kb_entry.paper_id == "test-paper-id"
        assert kb_entry.title == "Test Paper Title"
        assert kb_entry.authors == ["Author A", "Author B"]
        assert kb_entry.quality_score == 85.0
        assert kb_entry.doi == "10.1234/test"
        assert kb_entry.arxiv_id == "2301.12345"
        assert kb_entry.pdf_available is True

    def test_handles_missing_metadata(self, engine):
        """Test converting entry with missing metadata."""
        entry = RegistryEntry(
            paper_id="minimal-id",
            title_normalized="minimal paper",
            extraction_target_hash="sha256:def",
            metadata_snapshot=None,
        )

        kb_entry = engine._entry_to_kb_entry(entry)

        assert kb_entry.paper_id == "minimal-id"
        assert kb_entry.title == "minimal paper"
        assert kb_entry.quality_score == 0.0
        assert kb_entry.authors == []

    def test_handles_authors_as_string(self, engine):
        """Test converting entry with authors as a single string."""
        entry = RegistryEntry(
            paper_id="string-author-id",
            title_normalized="paper with string author",
            extraction_target_hash="sha256:ghi",
            metadata_snapshot={
                "title": "Paper With String Author",
                "authors": "Single Author Name",  # String instead of list
                "quality_score": 70.0,
            },
        )

        kb_entry = engine._entry_to_kb_entry(entry)

        assert kb_entry.authors == ["Single Author Name"]
        assert kb_entry.quality_score == 70.0


class TestExtractUserNotes:
    """Tests for user note extraction."""

    def test_extracts_single_note(self, engine, temp_output_dir):
        """Test extracting a single user note."""
        topic_dir = temp_output_dir / "test-topic"
        topic_dir.mkdir()
        kb_path = topic_dir / KNOWLEDGE_BASE_FILENAME

        content = """# Knowledge Base

### Paper Title
Some content here.

<!-- USER_NOTES_START:paper-123 -->
My personal notes about this paper.
<!-- USER_NOTES_END:paper-123 -->

More content.
"""
        kb_path.write_text(content)

        notes = engine._extract_user_notes(kb_path)

        assert "paper-123" in notes
        assert notes["paper-123"].content == "My personal notes about this paper."

    def test_extracts_multiple_notes(self, engine, temp_output_dir):
        """Test extracting multiple user notes."""
        topic_dir = temp_output_dir / "test-topic"
        topic_dir.mkdir()
        kb_path = topic_dir / KNOWLEDGE_BASE_FILENAME

        content = """# Knowledge Base

<!-- USER_NOTES_START:paper-1 -->
Note for paper 1.
<!-- USER_NOTES_END:paper-1 -->

<!-- USER_NOTES_START:paper-2 -->
Note for paper 2.
<!-- USER_NOTES_END:paper-2 -->
"""
        kb_path.write_text(content)

        notes = engine._extract_user_notes(kb_path)

        assert len(notes) == 2
        assert "paper-1" in notes
        assert "paper-2" in notes

    def test_handles_empty_notes(self, engine, temp_output_dir):
        """Test handling empty note anchors."""
        topic_dir = temp_output_dir / "test-topic"
        topic_dir.mkdir()
        kb_path = topic_dir / KNOWLEDGE_BASE_FILENAME

        content = """<!-- USER_NOTES_START:paper-1 -->
<!-- USER_NOTES_END:paper-1 -->"""
        kb_path.write_text(content)

        notes = engine._extract_user_notes(kb_path)

        # Empty notes should not be included
        assert len(notes) == 0

    def test_returns_empty_for_nonexistent_file(self, engine, temp_output_dir):
        """Test returns empty dict for nonexistent file."""
        kb_path = temp_output_dir / "nonexistent" / KNOWLEDGE_BASE_FILENAME

        notes = engine._extract_user_notes(kb_path)

        assert notes == {}

    def test_handles_read_exception(self, engine, temp_output_dir, mocker):
        """Test handling exception when reading file."""
        topic_dir = temp_output_dir / "test-topic"
        topic_dir.mkdir()
        kb_path = topic_dir / KNOWLEDGE_BASE_FILENAME
        kb_path.write_text("some content")

        # Mock read_text to raise an exception
        mocker.patch.object(Path, "read_text", side_effect=IOError("Read error"))

        notes = engine._extract_user_notes(kb_path)

        # Should return empty dict on error
        assert notes == {}


class TestQualityBadge:
    """Tests for quality badge generation."""

    def test_excellent_badge(self, engine):
        """Test excellent quality badge."""
        badge = engine._quality_badge(85.0)
        assert "⭐⭐⭐" in badge
        assert "Excellent" in badge

    def test_good_badge(self, engine):
        """Test good quality badge."""
        badge = engine._quality_badge(65.0)
        assert "⭐⭐" in badge
        assert "Good" in badge

    def test_fair_badge(self, engine):
        """Test fair quality badge."""
        badge = engine._quality_badge(45.0)
        assert "⭐" in badge
        assert "Fair" in badge

    def test_low_badge(self, engine):
        """Test low quality badge."""
        badge = engine._quality_badge(25.0)
        assert "○" in badge
        assert "Low" in badge


class TestRenderPaperSection:
    """Tests for paper section rendering."""

    def test_renders_complete_section(self, engine):
        """Test rendering a complete paper section."""
        entry = KnowledgeBaseEntry(
            paper_id="test-id",
            title="Test Paper",
            authors=["Author A"],
            abstract="Test abstract.",
            quality_score=80.0,
            pdf_available=True,
            doi="10.1234/test",
        )

        section = engine._render_paper_section(entry)

        assert "### Test Paper" in section
        assert "⭐⭐⭐" in section
        assert "📄 PDF" in section
        assert "Author A" in section
        assert "10.1234/test" in section
        assert "USER_NOTES_START:test-id" in section
        assert "USER_NOTES_END:test-id" in section

    def test_preserves_user_notes(self, engine):
        """Test that user notes are preserved."""
        entry = KnowledgeBaseEntry(
            paper_id="test-id",
            title="Test Paper",
            quality_score=50.0,
        )
        user_note = UserNoteAnchor(
            paper_id="test-id",
            content="My preserved notes.",
        )

        section = engine._render_paper_section(entry, user_note)

        assert "My preserved notes." in section

    def test_renders_extraction_results(self, engine):
        """Test rendering paper with extraction results."""
        entry = KnowledgeBaseEntry(
            paper_id="test-id",
            title="Test Paper",
            quality_score=75.0,
            extraction_results={
                "main_findings": "Key research findings here",
                "methodology": "ML-based approach",
                "empty_field": "",  # Should be skipped
            },
        )

        section = engine._render_paper_section(entry)

        assert "**Extracted Insights:**" in section
        assert "**Main Findings:**" in section
        assert "Key research findings here" in section
        assert "**Methodology:**" in section
        assert "ML-based approach" in section
        # Empty field should not appear
        assert "Empty Field" not in section

    def test_renders_topic_affiliations(self, engine):
        """Test rendering paper with multiple topic affiliations."""
        entry = KnowledgeBaseEntry(
            paper_id="test-id",
            title="Test Paper",
            quality_score=60.0,
            topic_affiliations=["topic-a", "topic-b", "topic-c"],
        )

        section = engine._render_paper_section(entry)

        assert "Also appears in:" in section
        # Should show other topics (excluding the paper_id which isn't a topic here)
        assert "topic-a" in section or "topic-b" in section or "topic-c" in section


class TestSynthesize:
    """Tests for synthesis operation."""

    def test_synthesize_empty_topic(self, engine, mock_registry_service):
        """Test synthesizing topic with no papers."""
        mock_registry_service.get_entries_for_topic.return_value = []

        stats = engine.synthesize("empty-topic")

        assert stats.topic_slug == "empty-topic"
        assert stats.total_papers == 0

    def test_synthesize_creates_kb_file(
        self, engine, mock_registry_service, sample_registry_entry, temp_output_dir
    ):
        """Test that synthesis creates Knowledge Base file."""
        mock_registry_service.get_entries_for_topic.return_value = [
            sample_registry_entry
        ]

        stats = engine.synthesize("test-topic")

        kb_path = temp_output_dir / "test-topic" / KNOWLEDGE_BASE_FILENAME
        assert kb_path.exists()
        assert stats.total_papers == 1

    def test_synthesize_sorts_by_quality(
        self, engine, mock_registry_service, temp_output_dir
    ):
        """Test that papers are sorted by quality."""
        # Create entries with different quality scores
        high_quality = RegistryEntry(
            paper_id="high",
            title_normalized="high quality",
            extraction_target_hash="sha256:1",
            topic_affiliations=["test-topic"],
            metadata_snapshot={"title": "High Quality", "quality_score": 90.0},
        )
        low_quality = RegistryEntry(
            paper_id="low",
            title_normalized="low quality",
            extraction_target_hash="sha256:2",
            topic_affiliations=["test-topic"],
            metadata_snapshot={"title": "Low Quality", "quality_score": 30.0},
        )

        mock_registry_service.get_entries_for_topic.return_value = [
            low_quality,
            high_quality,
        ]

        engine.synthesize("test-topic")

        kb_path = temp_output_dir / "test-topic" / KNOWLEDGE_BASE_FILENAME
        content = kb_path.read_text()

        # High quality should appear before low quality
        high_pos = content.find("High Quality")
        low_pos = content.find("Low Quality")
        assert high_pos < low_pos

    def test_synthesize_creates_backup(
        self, engine, mock_registry_service, sample_registry_entry, temp_output_dir
    ):
        """Test that backup is created before overwrite."""
        mock_registry_service.get_entries_for_topic.return_value = [
            sample_registry_entry
        ]

        # First synthesis
        engine.synthesize("test-topic")

        # Second synthesis should create backup
        engine.synthesize("test-topic")

        backup_path = (
            temp_output_dir / "test-topic" / (KNOWLEDGE_BASE_FILENAME + ".bak")
        )
        assert backup_path.exists()

    def test_synthesize_returns_stats(
        self, engine, mock_registry_service, sample_registry_entry
    ):
        """Test that synthesis returns correct statistics."""
        mock_registry_service.get_entries_for_topic.return_value = [
            sample_registry_entry
        ]

        stats = engine.synthesize("test-topic")

        assert stats.total_papers == 1
        assert stats.papers_with_pdf == 1
        assert stats.average_quality == 85.0
        assert stats.synthesis_duration_ms >= 0

    def test_synthesize_handles_backup_failure(
        self,
        engine,
        mock_registry_service,
        sample_registry_entry,
        temp_output_dir,
        mocker,
    ):
        """Test that synthesis continues even if backup fails."""
        mock_registry_service.get_entries_for_topic.return_value = [
            sample_registry_entry
        ]

        # First synthesis to create the file
        engine.synthesize("test-topic")

        # Mock shutil.copy2 to fail on second synthesis
        import shutil

        mocker.patch.object(shutil, "copy2", side_effect=OSError("Backup failed"))

        # Second synthesis should still succeed even if backup fails
        stats = engine.synthesize("test-topic")

        assert stats.total_papers == 1
        kb_path = temp_output_dir / "test-topic" / KNOWLEDGE_BASE_FILENAME
        assert kb_path.exists()

    def test_synthesize_handles_write_failure(
        self, engine, mock_registry_service, sample_registry_entry, mocker
    ):
        """Test that synthesis returns empty stats on write failure."""
        mock_registry_service.get_entries_for_topic.return_value = [
            sample_registry_entry
        ]

        # Mock atomic write to fail
        mocker.patch.object(engine, "_atomic_write", return_value=False)

        stats = engine.synthesize("test-topic")

        # Should return stats with 0 papers on failure
        assert stats.total_papers == 0


class TestAtomicWrite:
    """Tests for atomic file write operation."""

    def test_atomic_write_failure_cleanup(self, engine, temp_output_dir, mocker):
        """Test that temp file is cleaned up on write failure."""
        import os

        topic_dir = temp_output_dir / "test-topic"
        topic_dir.mkdir(parents=True)
        file_path = topic_dir / "test.md"

        # Mock os.rename to fail
        mocker.patch.object(os, "rename", side_effect=OSError("Rename failed"))

        result = engine._atomic_write(file_path, "test content")

        assert result is False
        # Verify no temp files left behind
        temp_files = list(topic_dir.glob(".kb_*.tmp"))
        assert len(temp_files) == 0


class TestSynthesizeAllTopics:
    """Tests for synthesizing all topics."""

    def test_synthesizes_all_topics(self, engine, mock_registry_service):
        """Test synthesizing all topics in registry."""
        # Setup mock state with multiple topics
        mock_state = mock_registry_service.load.return_value
        mock_state.entries = {
            "paper1": RegistryEntry(
                paper_id="paper1",
                title_normalized="paper 1",
                extraction_target_hash="sha256:1",
                topic_affiliations=["topic-a", "topic-b"],
            ),
        }
        mock_registry_service.get_entries_for_topic.return_value = []

        results = engine.synthesize_all_topics()

        assert "topic-a" in results
        assert "topic-b" in results

    def test_continues_on_topic_failure(self, engine, mock_registry_service, mocker):
        """Test that synthesis continues if one topic fails."""
        mock_state = mock_registry_service.load.return_value
        mock_state.entries = {
            "paper1": RegistryEntry(
                paper_id="paper1",
                title_normalized="paper 1",
                extraction_target_hash="sha256:1",
                topic_affiliations=["topic-a", "topic-b"],
            ),
        }

        # Make first topic fail
        call_count = [0]
        original_synthesize = engine.synthesize

        def mock_synthesize(topic_slug):
            call_count[0] += 1
            if topic_slug == "topic-a":
                raise RuntimeError("Simulated failure")
            return original_synthesize(topic_slug)

        mocker.patch.object(engine, "synthesize", side_effect=mock_synthesize)

        results = engine.synthesize_all_topics()

        # Both topics should have results (even if one failed)
        assert len(results) == 2

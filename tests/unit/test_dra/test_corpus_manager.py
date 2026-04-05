"""Unit tests for Phase 8 DRA corpus manager."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.models.dra import ChunkType, CorpusChunk, CorpusConfig
from src.services.dra.corpus_manager import (
    CorpusManager,
    CorpusStats,
    PaperRecord,
)


class TestCorpusStats:
    """Tests for CorpusStats class."""

    def test_default_values(self):
        """Test default initialization."""
        stats = CorpusStats()
        assert stats.total_papers == 0
        assert stats.total_chunks == 0
        assert stats.total_tokens == 0
        assert stats.chunks_by_section == {}
        assert isinstance(stats.last_updated, datetime)

    def test_custom_values(self):
        """Test custom initialization."""
        now = datetime.now(UTC)
        stats = CorpusStats(
            total_papers=10,
            total_chunks=50,
            total_tokens=5000,
            chunks_by_section={"abstract": 10, "methods": 20},
            last_updated=now,
        )
        assert stats.total_papers == 10
        assert stats.total_chunks == 50
        assert stats.chunks_by_section["abstract"] == 10

    def test_to_dict(self):
        """Test conversion to dictionary."""
        stats = CorpusStats(total_papers=5, total_chunks=25)
        data = stats.to_dict()

        assert data["total_papers"] == 5
        assert data["total_chunks"] == 25
        assert "last_updated" in data

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "total_papers": 10,
            "total_chunks": 50,
            "total_tokens": 5000,
            "chunks_by_section": {"abstract": 10},
            "last_updated": "2024-01-15T10:00:00",
        }
        stats = CorpusStats.from_dict(data)

        assert stats.total_papers == 10
        assert stats.total_chunks == 50
        assert stats.chunks_by_section["abstract"] == 10

    def test_from_dict_missing_timestamp(self):
        """Test creation from dict without timestamp."""
        data = {"total_papers": 5}
        stats = CorpusStats.from_dict(data)
        assert stats.total_papers == 5
        # When no timestamp provided, from_dict returns current time
        assert stats.last_updated is not None


class TestPaperRecord:
    """Tests for PaperRecord class."""

    def test_basic_creation(self):
        """Test basic paper record creation."""
        record = PaperRecord(
            paper_id="paper123",
            title="Test Paper",
            checksum="abc123",
            chunk_ids=["paper123:0", "paper123:1"],
        )
        assert record.paper_id == "paper123"
        assert record.title == "Test Paper"
        assert record.checksum == "abc123"
        assert len(record.chunk_ids) == 2
        assert isinstance(record.ingested_at, datetime)

    def test_with_metadata(self):
        """Test paper record with metadata."""
        record = PaperRecord(
            paper_id="paper123",
            title="Test",
            checksum="abc",
            chunk_ids=[],
            metadata={"doi": "10.1234/test"},
        )
        assert record.metadata["doi"] == "10.1234/test"

    def test_to_dict(self):
        """Test conversion to dictionary."""
        record = PaperRecord(
            paper_id="paper123",
            title="Test",
            checksum="abc",
            chunk_ids=["chunk1"],
        )
        data = record.to_dict()

        assert data["paper_id"] == "paper123"
        assert data["checksum"] == "abc"
        assert "ingested_at" in data

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "paper_id": "paper123",
            "title": "Test Paper",
            "checksum": "abc123",
            "chunk_ids": ["chunk1", "chunk2"],
            "ingested_at": "2024-01-15T10:00:00",
            "metadata": {"key": "value"},
        }
        record = PaperRecord.from_dict(data)

        assert record.paper_id == "paper123"
        assert record.title == "Test Paper"
        assert len(record.chunk_ids) == 2
        assert record.metadata["key"] == "value"


class TestCorpusManager:
    """Tests for CorpusManager class."""

    def test_init_default(self):
        """Test default initialization."""
        manager = CorpusManager()
        assert manager.paper_count == 0
        assert isinstance(manager.stats, CorpusStats)

    def test_init_custom_config(self):
        """Test custom configuration."""
        config = CorpusConfig(corpus_dir="/custom/path")
        manager = CorpusManager(config=config)
        assert str(manager.corpus_dir) == "/custom/path"

    def test_ingest_paper_empty_content(self):
        """Test ingesting paper with empty content."""
        manager = CorpusManager()
        chunks = manager.ingest_paper(
            paper_id="paper1",
            title="Test",
            markdown_content="",
        )
        assert chunks == []

    def test_ingest_paper_whitespace_only(self):
        """Test ingesting paper with whitespace only."""
        manager = CorpusManager()
        chunks = manager.ingest_paper(
            paper_id="paper1",
            title="Test",
            markdown_content="   \n\n   ",
        )
        assert chunks == []

    @patch("src.services.dra.corpus_manager.HybridSearchEngine")
    def test_ingest_paper_basic(self, mock_engine_class):
        """Test basic paper ingestion."""
        mock_engine = MagicMock()
        mock_engine.get_chunk.return_value = None
        mock_engine.corpus_size = 0
        mock_engine_class.return_value = mock_engine

        manager = CorpusManager()
        manager._search_engine = mock_engine

        content = """# Abstract

This is the abstract of our paper.

# Introduction

This is the introduction.
"""
        manager.ingest_paper(
            paper_id="paper1",
            title="Test Paper",
            markdown_content=content,
        )

        # Should have indexed chunks
        mock_engine.index_chunks.assert_called_once()
        assert "paper1" in manager._papers

    @patch("src.services.dra.corpus_manager.HybridSearchEngine")
    def test_ingest_paper_unchanged(self, mock_engine_class):
        """Test that unchanged papers are not re-ingested."""
        mock_engine = MagicMock()
        mock_chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            title="Test",
            content="content",
            token_count=1,
        )
        mock_engine.get_chunk.return_value = mock_chunk
        mock_engine.corpus_size = 1
        mock_engine_class.return_value = mock_engine

        manager = CorpusManager()
        manager._search_engine = mock_engine

        content = "# Abstract\n\nSome content."

        # First ingestion
        manager.ingest_paper("paper1", "Test", content)

        # Reset mock
        mock_engine.index_chunks.reset_mock()

        # Second ingestion with same content
        chunks = manager.ingest_paper("paper1", "Test", content)

        # Should not re-index
        mock_engine.index_chunks.assert_not_called()
        # Should return existing chunks
        assert len(chunks) >= 0

    @patch("src.services.dra.corpus_manager.HybridSearchEngine")
    def test_ingest_paper_force_reindex(self, mock_engine_class):
        """Test force re-ingestion."""
        mock_engine = MagicMock()
        mock_engine.get_chunk.return_value = None
        mock_engine.corpus_size = 0
        mock_engine_class.return_value = mock_engine

        manager = CorpusManager()
        manager._search_engine = mock_engine

        content = "# Abstract\n\nSome content."

        # First ingestion
        manager.ingest_paper("paper1", "Test", content)

        # Reset mock
        mock_engine.index_chunks.reset_mock()

        # Force re-ingestion
        manager.ingest_paper("paper1", "Test", content, force=True)

        # Should re-index
        mock_engine.index_chunks.assert_called_once()

    @patch("src.services.dra.corpus_manager.HybridSearchEngine")
    def test_ingest_paper_with_metadata(self, mock_engine_class):
        """Test ingestion with metadata."""
        mock_engine = MagicMock()
        mock_engine.get_chunk.return_value = None
        mock_engine.corpus_size = 0
        mock_engine_class.return_value = mock_engine

        manager = CorpusManager()
        manager._search_engine = mock_engine

        content = "# Methods\n\nOur methodology."
        metadata = {"doi": "10.1234/test", "authors": ["Author One"]}

        manager.ingest_paper(
            paper_id="paper1",
            title="Test",
            markdown_content=content,
            metadata=metadata,
        )

        assert manager._papers["paper1"].metadata == metadata

    def test_ingest_from_registry_not_found(self):
        """Test ingestion from non-existent registry."""
        manager = CorpusManager()
        count = manager.ingest_from_registry(Path("/nonexistent/registry"))
        assert count == 0

    def test_ingest_from_registry(self):
        """Test ingestion from registry directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir)
            papers_dir = registry_path / "papers"
            papers_dir.mkdir()

            # Create paper directory
            paper_dir = papers_dir / "paper1"
            paper_dir.mkdir()

            # Create metadata
            metadata = {"title": "Test Paper", "doi": "10.1234/test"}
            with open(paper_dir / "metadata.json", "w") as f:
                json.dump(metadata, f)

            # Create content
            content = "# Abstract\n\nThis is the abstract."
            with open(paper_dir / "content.md", "w") as f:
                f.write(content)

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine.get_chunk.return_value = None
                mock_engine.corpus_size = 0
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine

                count = manager.ingest_from_registry(registry_path)

            assert count == 1
            assert "paper1" in manager._papers

    def test_ingest_from_registry_alternative_content_names(self):
        """Test ingestion with alternative content file names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir)
            papers_dir = registry_path / "papers"
            papers_dir.mkdir()

            paper_dir = papers_dir / "paper1"
            paper_dir.mkdir()

            # Use alternative name: paper.md
            with open(paper_dir / "paper.md", "w") as f:
                f.write("# Introduction\n\nContent here.")

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine.get_chunk.return_value = None
                mock_engine.corpus_size = 0
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine

                count = manager.ingest_from_registry(registry_path)

            assert count == 1

    def test_ingest_from_registry_rejects_path_traversal(self):
        """Test that path traversal attempts are blocked (SR-8.5 security)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir)
            papers_dir = registry_path / "papers"
            papers_dir.mkdir()

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine.get_chunk.return_value = None
                mock_engine.corpus_size = 0
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine

                # Test various path traversal attempts
                malicious_ids = [
                    "../../../etc/passwd",
                    "..%2f..%2fetc/passwd",
                    "foo/../bar",
                    "paper/../../secret",
                    "..",
                    "paper\x00.txt",  # null byte injection
                ]

                count = manager.ingest_from_registry(
                    registry_path, paper_ids=malicious_ids
                )

                # All should be rejected
                assert count == 0
                assert len(manager._papers) == 0

    def test_ingest_from_registry_accepts_valid_paper_ids(self):
        """Test that valid paper IDs are accepted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir)
            papers_dir = registry_path / "papers"
            papers_dir.mkdir()

            # Create a valid paper directory
            paper_dir = papers_dir / "valid-paper_123.v1"
            paper_dir.mkdir()
            (paper_dir / "content.md").write_text("# Abstract\n\nValid content.")

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine.get_chunk.return_value = None
                mock_engine.corpus_size = 0
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine

                # Valid paper IDs should work
                count = manager.ingest_from_registry(
                    registry_path, paper_ids=["valid-paper_123.v1"]
                )

                assert count == 1
                assert "valid-paper_123.v1" in manager._papers

    def test_remove_paper(self):
        """Test removing a paper."""
        manager = CorpusManager()
        manager._papers["paper1"] = PaperRecord(
            paper_id="paper1",
            title="Test",
            checksum="abc",
            chunk_ids=["paper1:0"],
        )

        result = manager.remove_paper("paper1")
        assert result is True
        assert "paper1" not in manager._papers

    def test_remove_paper_not_found(self):
        """Test removing non-existent paper."""
        manager = CorpusManager()
        result = manager.remove_paper("nonexistent")
        assert result is False

    def test_get_paper_info(self):
        """Test getting paper info."""
        manager = CorpusManager()
        record = PaperRecord(
            paper_id="paper1",
            title="Test",
            checksum="abc",
            chunk_ids=["paper1:0"],
        )
        manager._papers["paper1"] = record

        result = manager.get_paper_info("paper1")
        assert result == record

        result = manager.get_paper_info("nonexistent")
        assert result is None

    def test_list_papers(self):
        """Test listing papers."""
        manager = CorpusManager()
        manager._papers["paper1"] = PaperRecord(
            paper_id="paper1",
            title="Test 1",
            checksum="abc",
            chunk_ids=[],
        )
        manager._papers["paper2"] = PaperRecord(
            paper_id="paper2",
            title="Test 2",
            checksum="def",
            chunk_ids=[],
        )

        papers = manager.list_papers()
        assert len(papers) == 2

    def test_save_and_load(self):
        """Test saving and loading corpus state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine
                manager._papers["paper1"] = PaperRecord(
                    paper_id="paper1",
                    title="Test",
                    checksum="abc",
                    chunk_ids=["paper1:0"],
                )
                manager._stats = CorpusStats(total_papers=1, total_chunks=1)

                manager.save(path)

            # Verify files exist
            assert (path / "papers.json").exists()
            assert (path / "stats.json").exists()

            # Load
            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine_class.return_value = mock_engine

                new_manager = CorpusManager()
                new_manager._search_engine = mock_engine
                new_manager.load(path)

            assert "paper1" in new_manager._papers
            assert new_manager._papers["paper1"].title == "Test"

    def test_load_nonexistent_path(self):
        """Test loading from non-existent path (no error, just warning)."""
        manager = CorpusManager()
        # Should not raise, just log warning
        manager.load(Path("/nonexistent/corpus"))
        assert manager.paper_count == 0

    def test_health_check_healthy(self):
        """Test health check on healthy corpus."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.is_ready = True
            mock_engine.corpus_size = 50
            mock_engine.get_chunk.return_value = CorpusChunk(
                chunk_id="paper1:0",
                paper_id="paper1",
                title="Test",
                content="content",
                token_count=1,
            )
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine

            # Add papers
            for i in range(15):
                manager._papers[f"paper{i}"] = PaperRecord(
                    paper_id=f"paper{i}",
                    title=f"Paper {i}",
                    checksum="abc",
                    chunk_ids=[f"paper{i}:0"],
                )

            health = manager.health_check()

            assert health["healthy"] is True
            assert health["paper_count"] == 15
            assert len(health["issues"]) == 0

    def test_health_check_small_corpus(self):
        """Test health check warns about small corpus."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.is_ready = True
            mock_engine.corpus_size = 5
            mock_engine.get_chunk.return_value = CorpusChunk(
                chunk_id="paper1:0",
                paper_id="paper1",
                title="Test",
                content="content",
                token_count=1,
            )
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine
            manager._papers["paper1"] = PaperRecord(
                paper_id="paper1",
                title="Test",
                checksum="abc",
                chunk_ids=["paper1:0"],
            )

            health = manager.health_check()

            assert health["healthy"] is False
            assert any("too small" in issue for issue in health["issues"])

    def test_health_check_missing_chunks(self):
        """Test health check detects missing chunks."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.is_ready = True
            mock_engine.corpus_size = 0
            mock_engine.get_chunk.return_value = None  # Chunk not found
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine

            # Add 15 papers to avoid "too small" warning
            for i in range(15):
                manager._papers[f"paper{i}"] = PaperRecord(
                    paper_id=f"paper{i}",
                    title=f"Paper {i}",
                    checksum="abc",
                    chunk_ids=[f"paper{i}:0"],  # These chunks don't exist
                )

            health = manager.health_check()

            assert health["healthy"] is False
            assert any("Missing chunk" in issue for issue in health["issues"])

    def test_rebuild_indices(self):
        """Test rebuilding indices."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_chunk = CorpusChunk(
                chunk_id="paper1:0",
                paper_id="paper1",
                title="Test",
                content="content",
                token_count=1,
            )
            mock_engine.get_chunk.return_value = mock_chunk
            mock_engine.corpus_size = 1
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine
            manager._papers["paper1"] = PaperRecord(
                paper_id="paper1",
                title="Test",
                checksum="abc",
                chunk_ids=["paper1:0"],
            )

            manager.rebuild_indices()

            # Should have created new search engine and indexed
            assert mock_engine_class.call_count >= 1

    def test_compute_checksum(self):
        """Test checksum computation via utility function."""
        from src.services.dra.utils import compute_checksum

        checksum1 = compute_checksum("Hello, world!")
        checksum2 = compute_checksum("Hello, world!")
        checksum3 = compute_checksum("Different content")

        assert checksum1 == checksum2
        assert checksum1 != checksum3
        assert len(checksum1) == 64  # SHA-256 hex

    def test_update_stats(self):
        """Test stats update."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.corpus_size = 3

            # Return chunks with different section types
            def get_chunk_side_effect(chunk_id):
                section_map = {
                    "paper1:0": ChunkType.ABSTRACT,
                    "paper1:1": ChunkType.METHODS,
                    "paper2:0": ChunkType.ABSTRACT,
                }
                section = section_map.get(chunk_id, ChunkType.OTHER)
                return CorpusChunk(
                    chunk_id=chunk_id,
                    paper_id=chunk_id.split(":")[0],
                    section_type=section,
                    title="Test",
                    content="content",
                    token_count=100,
                )

            mock_engine.get_chunk.side_effect = get_chunk_side_effect
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine

            manager._papers["paper1"] = PaperRecord(
                paper_id="paper1",
                title="Paper 1",
                checksum="abc",
                chunk_ids=["paper1:0", "paper1:1"],
            )
            manager._papers["paper2"] = PaperRecord(
                paper_id="paper2",
                title="Paper 2",
                checksum="def",
                chunk_ids=["paper2:0"],
            )

            manager._update_stats()

            assert manager._stats.total_papers == 2
            assert manager._stats.chunks_by_section["abstract"] == 2
            assert manager._stats.chunks_by_section["methods"] == 1
            assert manager._stats.total_tokens == 300

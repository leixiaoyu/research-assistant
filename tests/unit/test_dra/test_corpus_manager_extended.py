"""Extended tests for corpus manager to achieve ≥99% coverage."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.services.dra.corpus_manager import (
    CorpusManager,
    CorpusStats,
    PaperRecord,
)


class TestCorpusStatsExtended:
    """Extended tests for CorpusStats."""

    def test_round_trip_serialization(self):
        """Test model_dump and model_validate round trip (Pydantic v2)."""
        original = CorpusStats(
            total_papers=42,
            total_chunks=210,
            total_tokens=50000,
            chunks_by_section={"abstract": 42, "methods": 84, "results": 84},
            last_updated=datetime.now(UTC),
        )

        data = original.model_dump(mode="json")
        restored = CorpusStats.model_validate(data)

        assert restored.total_papers == original.total_papers
        assert restored.total_chunks == original.total_chunks
        assert restored.chunks_by_section == original.chunks_by_section


class TestPaperRecordExtended:
    """Extended tests for PaperRecord."""

    def test_round_trip_serialization(self):
        """Test model_dump and model_validate round trip (Pydantic v2)."""
        original = PaperRecord(
            paper_id="arxiv:2301.00001",
            title="A Great Paper on ML",
            checksum="abc123def456",
            chunk_ids=["arxiv:2301.00001:0", "arxiv:2301.00001:1"],
            metadata={"doi": "10.1234/test", "authors": ["Alice", "Bob"]},
        )

        data = original.model_dump(mode="json")
        restored = PaperRecord.model_validate(data)

        assert restored.paper_id == original.paper_id
        assert restored.title == original.title
        assert restored.chunk_ids == original.chunk_ids
        assert restored.metadata == original.metadata

    def test_model_validate_without_metadata(self):
        """Test model_validate when metadata is missing."""
        data = {
            "paper_id": "paper1",
            "title": "Test",
            "checksum": "abc",
            "chunk_ids": [],
            "ingested_at": "2024-01-15T10:00:00",
        }
        record = PaperRecord.model_validate(data)
        assert record.metadata == {}


class TestCorpusManagerExtended:
    """Extended tests for CorpusManager."""

    def test_search_engine_lazy_creation(self):
        """Test search engine is created lazily."""
        manager = CorpusManager()

        # Access search_engine property
        engine = manager.search_engine

        assert engine is not None
        # Accessing again returns same instance
        assert manager.search_engine is engine

    def test_ingest_paper_no_sections_creates_other(self):
        """Test ingesting paper with no section headers."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.get_chunk.return_value = None
            mock_engine.corpus_size = 0
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine

            # Content without any headers
            content = "This is plain text without headers. It has multiple sentences."

            manager.ingest_paper(
                paper_id="paper1",
                title="Test",
                markdown_content=content,
            )

            # Should still create chunks
            mock_engine.index_chunks.assert_called_once()

    def test_ingest_from_registry_skips_non_directories(self):
        """Test registry ingestion skips non-directory files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir)
            papers_dir = registry_path / "papers"
            papers_dir.mkdir()

            # Create a file instead of directory
            (papers_dir / "not_a_paper.txt").write_text("Just a file")

            # Create a valid paper directory
            paper_dir = papers_dir / "real_paper"
            paper_dir.mkdir()
            (paper_dir / "content.md").write_text("# Abstract\n\nReal content.")

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

            # Should only ingest the real paper
            assert count == 1

    def test_ingest_from_registry_specific_paper_ids(self):
        """Test registry ingestion with specific paper IDs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir)
            papers_dir = registry_path / "papers"
            papers_dir.mkdir()

            # Create multiple papers
            for pid in ["paper1", "paper2", "paper3"]:
                paper_dir = papers_dir / pid
                paper_dir.mkdir()
                (paper_dir / "content.md").write_text(
                    f"# Abstract\n\nContent for {pid}."
                )

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine.get_chunk.return_value = None
                mock_engine.corpus_size = 0
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine

                # Only ingest specific papers
                count = manager.ingest_from_registry(
                    registry_path, paper_ids=["paper1", "paper3"]
                )

            assert count == 2
            assert "paper1" in manager._papers
            assert "paper3" in manager._papers
            assert "paper2" not in manager._papers

    def test_ingest_from_registry_handles_ingestion_error(self):
        """Test registry ingestion handles errors gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir)
            papers_dir = registry_path / "papers"
            papers_dir.mkdir()

            # Create paper with no content file
            paper_dir = papers_dir / "broken_paper"
            paper_dir.mkdir()
            # No content.md file

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine.get_chunk.return_value = None
                mock_engine.corpus_size = 0
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine

                # Should not raise, just log warning
                count = manager.ingest_from_registry(registry_path)

            assert count == 0

    def test_ingest_paper_content_changed(self):
        """Test that changed content triggers re-ingestion."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.get_chunk.return_value = None
            mock_engine.corpus_size = 0
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine

            content1 = "# Abstract\n\nOriginal content."
            content2 = "# Abstract\n\nUpdated content with changes."

            # First ingestion
            manager.ingest_paper("paper1", "Test", content1)
            assert mock_engine.index_chunks.call_count == 1

            # Second ingestion with different content
            manager.ingest_paper("paper1", "Test", content2)
            assert mock_engine.index_chunks.call_count == 2

    def test_health_check_search_not_ready(self):
        """Test health check when search engine is not ready."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.is_ready = False
            mock_engine.corpus_size = 0
            mock_engine.get_chunk.return_value = None
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

            assert health["healthy"] is False
            assert any("not ready" in issue for issue in health["issues"])

    def test_save_creates_directories(self):
        """Test save creates necessary directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "corpus"

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine

                manager.save(path)

            assert path.exists()
            assert (path / "papers.json").exists()
            assert (path / "stats.json").exists()

    def test_load_with_existing_data(self):
        """Test load restores all state correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)

            # Create papers.json
            papers_data = {
                "paper1": {
                    "paper_id": "paper1",
                    "title": "Test Paper",
                    "checksum": "abc123",
                    "chunk_ids": ["paper1:0", "paper1:1"],
                    "ingested_at": "2024-01-15T10:00:00",
                    "metadata": {"doi": "10.1234"},
                }
            }
            with open(path / "papers.json", "w") as f:
                json.dump(papers_data, f)

            # Create stats.json
            stats_data = {
                "total_papers": 1,
                "total_chunks": 2,
                "total_tokens": 100,
                "chunks_by_section": {"abstract": 1, "methods": 1},
                "last_updated": "2024-01-15T10:00:00",
            }
            with open(path / "stats.json", "w") as f:
                json.dump(stats_data, f)

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine
                manager.load(path)

            assert "paper1" in manager._papers
            assert manager._papers["paper1"].metadata["doi"] == "10.1234"
            assert manager._stats.total_papers == 1

    def test_rebuild_indices_empty_corpus(self):
        """Test rebuild with empty corpus."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.get_chunk.return_value = None
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine

            # No papers, should complete without error
            manager.rebuild_indices()

    def test_update_stats_handles_missing_chunks(self):
        """Test stats update when chunks are missing."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.corpus_size = 0
            mock_engine.get_chunk.return_value = None  # All chunks missing
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine

            manager._papers["paper1"] = PaperRecord(
                paper_id="paper1",
                title="Test",
                checksum="abc",
                chunk_ids=["paper1:0", "paper1:1"],
            )

            manager._update_stats()

            # Stats should still work, just with zero tokens
            assert manager._stats.total_papers == 1
            assert manager._stats.total_tokens == 0


class TestCorpusManagerCoverageGaps:
    """Tests targeting specific coverage gaps in corpus_manager.py."""

    def test_ingest_paper_no_sections_fallback(self):
        """Test line 234: fallback when parser returns no sections."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.get_chunk.return_value = None
            mock_engine.corpus_size = 0
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine

            # Mock section parser to return empty list
            with patch.object(manager._section_parser, "parse", return_value=[]):
                content = "Plain text content without any markdown headers at all."
                manager.ingest_paper("paper1", "Test", content)

            # Should still have indexed (with fallback to OTHER section)
            mock_engine.index_chunks.assert_called_once()

    def test_ingest_paper_no_chunks_after_building(self):
        """Test lines 245-246: when chunk builder returns empty list."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.get_chunk.return_value = None
            mock_engine.corpus_size = 0
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine

            # Mock chunk builder to return empty list
            with patch.object(manager._chunk_builder, "build_chunks", return_value=[]):
                content = "# Abstract\n\nSome content."
                result = manager.ingest_paper("paper1", "Test", content)

            # Should return empty and NOT call index_chunks
            assert result == []
            mock_engine.index_chunks.assert_not_called()

    def test_ingest_from_registry_skips_existing(self):
        """Test line 313: skip already ingested papers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir)
            papers_dir = registry_path / "papers"
            papers_dir.mkdir()

            # Create paper directory
            paper_dir = papers_dir / "existing_paper"
            paper_dir.mkdir()
            (paper_dir / "content.md").write_text("# Abstract\n\nContent.")

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine.get_chunk.return_value = None
                mock_engine.corpus_size = 0
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine

                # Pre-add the paper to simulate it's already ingested
                manager._papers["existing_paper"] = PaperRecord(
                    paper_id="existing_paper",
                    title="Existing",
                    checksum="abc",
                    chunk_ids=["existing_paper:0"],
                )

                # Without force, should skip
                count = manager.ingest_from_registry(registry_path, force=False)

            assert count == 0
            # index_chunks should not be called since paper was skipped
            mock_engine.index_chunks.assert_not_called()

    def test_ingest_from_registry_exception_handling(self):
        """Test lines 319-320: exception handling during ingestion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir)
            papers_dir = registry_path / "papers"
            papers_dir.mkdir()

            # Create paper directory
            paper_dir = papers_dir / "error_paper"
            paper_dir.mkdir()
            (paper_dir / "content.md").write_text("# Abstract\n\nContent.")

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine

                # Make _ingest_registry_paper raise a specific handled exception
                with patch.object(
                    manager,
                    "_ingest_registry_paper",
                    side_effect=ValueError("Test error"),
                ):
                    count = manager.ingest_from_registry(registry_path)

            # Should return 0 and not crash
            assert count == 0


class TestBranchCoverage:
    """Tests for branch coverage gaps."""

    def test_rebuild_indices_chunk_not_found(self):
        """Test rebuild_indices when some chunks are not found."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            # get_chunk returns None for missing chunks
            mock_engine.get_chunk.return_value = None
            mock_engine.corpus_size = 0
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine

            # Add paper with chunk IDs that don't exist
            manager._papers["paper1"] = PaperRecord(
                paper_id="paper1",
                title="Test",
                checksum="abc",
                chunk_ids=["paper1:0", "paper1:1"],  # These won't be found
            )

            manager.rebuild_indices()

            # Should complete without error, just with empty chunks

    def test_load_without_papers_file(self):
        """Test load when papers.json doesn't exist (line 536 false branch)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)

            # Only create stats.json, no papers.json
            stats_data = {"total_papers": 0, "total_chunks": 0, "total_tokens": 0}
            with open(path / "stats.json", "w") as f:
                json.dump(stats_data, f)

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine
                manager.load(path)

            # Should have loaded stats but no papers
            assert manager._stats.total_papers == 0
            assert len(manager._papers) == 0

    def test_load_without_stats_file(self):
        """Test load when stats.json doesn't exist (line 546 false branch)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)

            # Only create papers.json, no stats.json
            papers_data = {}
            with open(path / "papers.json", "w") as f:
                json.dump(papers_data, f)

            with patch(
                "src.services.dra.corpus_manager.HybridSearchEngine"
            ) as mock_engine_class:
                mock_engine = MagicMock()
                mock_engine_class.return_value = mock_engine

                manager = CorpusManager()
                manager._search_engine = mock_engine
                manager.load(path)

            # Should complete without error


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_ingest_paper_with_unicode_content(self):
        """Test ingesting paper with unicode characters."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.get_chunk.return_value = None
            mock_engine.corpus_size = 0
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine

            content = """# Abstract

研究表明，深度学习在机器翻译中表现优异。

# Methods

我们使用了 Transformer 架构。
"""
            manager.ingest_paper(
                paper_id="chinese_paper",
                title="中文论文",
                markdown_content=content,
            )

            mock_engine.index_chunks.assert_called_once()

    def test_ingest_paper_with_special_characters(self):
        """Test ingesting paper with special characters in title."""
        with patch(
            "src.services.dra.corpus_manager.HybridSearchEngine"
        ) as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.get_chunk.return_value = None
            mock_engine.corpus_size = 0
            mock_engine_class.return_value = mock_engine

            manager = CorpusManager()
            manager._search_engine = mock_engine

            content = "# Abstract\n\nContent here."
            manager.ingest_paper(
                paper_id="paper/with/slashes",
                title="Paper: A Study (Part 1) [Draft]",
                markdown_content=content,
            )

            assert "paper/with/slashes" in manager._papers

    def test_corpus_stats_empty_sections(self):
        """Test CorpusStats with empty chunks_by_section (Pydantic v2)."""
        stats = CorpusStats(
            total_papers=0,
            total_chunks=0,
            total_tokens=0,
        )
        data = stats.model_dump(mode="json")
        restored = CorpusStats.model_validate(data)

        assert restored.chunks_by_section == {}

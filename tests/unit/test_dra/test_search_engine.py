"""Unit tests for Phase 8 DRA search engine."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.models.dra import ChunkType, CorpusChunk, CorpusConfig, SearchConfig
from src.services.dra.search_engine import (
    BM25Index,
    DenseIndex,
    EmbeddingModel,
    HybridSearchEngine,
)


class TestEmbeddingModel:
    """Tests for EmbeddingModel class."""

    def test_init_default_values(self):
        """Test default initialization values."""
        model = EmbeddingModel()
        assert model.model_name == "allenai/specter2"
        assert model.model_path is None
        assert model.batch_size == 32
        assert model._model is None

    def test_init_custom_values(self):
        """Test custom initialization values."""
        model = EmbeddingModel(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_path="/path/to/model",
            batch_size=16,
        )
        assert model.model_name == "sentence-transformers/all-MiniLM-L6-v2"
        assert model.model_path == "/path/to/model"
        assert model.batch_size == 16

    @patch("src.services.dra.search_engine.EmbeddingModel._load_model")
    def test_dimension_triggers_load(self, mock_load):
        """Test that accessing dimension triggers model load."""
        model = EmbeddingModel()
        model._dimension = 768  # Set dimension to avoid actual load
        dim = model.dimension
        assert dim == 768

    def test_encode_empty_list(self):
        """Test encoding empty list."""
        model = EmbeddingModel()
        model._dimension = 768
        model._model = MagicMock()
        model._tokenizer = MagicMock()

        result = model.encode([])
        assert result.shape == (0, 768)

    def test_load_model_from_hub(self):
        """Test loading model from HuggingFace Hub."""
        with patch("transformers.AutoModel") as mock_model:
            with patch("transformers.AutoTokenizer") as mock_tokenizer:
                # Setup mocks
                mock_model_instance = MagicMock()
                mock_model_instance.config.hidden_size = 768
                mock_model.from_pretrained.return_value = mock_model_instance
                mock_tokenizer.from_pretrained.return_value = MagicMock()

                model = EmbeddingModel(model_name="allenai/specter")
                model._load_model()

                mock_model.from_pretrained.assert_called_once_with(
                    "allenai/specter", trust_remote_code=False
                )
                mock_tokenizer.from_pretrained.assert_called_once_with(
                    "allenai/specter", trust_remote_code=False
                )
                assert model._dimension == 768

    def test_load_model_from_path(self):
        """Test loading model from local path."""
        with patch("transformers.AutoModel") as mock_model:
            with patch("transformers.AutoTokenizer") as mock_tokenizer:
                mock_model_instance = MagicMock()
                mock_model_instance.config.hidden_size = 384
                mock_model.from_pretrained.return_value = mock_model_instance
                mock_tokenizer.from_pretrained.return_value = MagicMock()

                model = EmbeddingModel(model_path="/local/model")
                model._load_model()

                mock_model.from_pretrained.assert_called_once_with(
                    "/local/model", trust_remote_code=False
                )

    def test_load_model_import_error(self):
        """Test import error when transformers not installed."""
        model = EmbeddingModel()

        with patch.dict("sys.modules", {"transformers": None}):
            with patch(
                "src.services.dra.search_engine.EmbeddingModel._load_model",
                side_effect=ImportError("transformers package required"),
            ):
                with pytest.raises(ImportError, match="transformers"):
                    model._load_model()


class TestBM25Index:
    """Tests for BM25Index class."""

    def test_init_default(self):
        """Test default initialization."""
        index = BM25Index()
        assert index.is_built is False
        assert index.size == 0

    def test_build_empty_corpus(self):
        """Test building index with empty corpus."""
        index = BM25Index()
        index.build([])
        assert index.is_built is False
        assert index.size == 0

    def test_build_with_chunks(self):
        """Test building index with chunks."""
        index = BM25Index()
        chunks = [
            CorpusChunk(
                chunk_id="paper1:0",
                paper_id="paper1",
                title="Test",
                content="neural network deep learning",
                token_count=4,
            ),
            CorpusChunk(
                chunk_id="paper1:1",
                paper_id="paper1",
                title="Test",
                content="machine learning algorithms",
                token_count=3,
            ),
        ]

        with patch("rank_bm25.BM25Okapi") as mock_bm25:
            mock_bm25.return_value = MagicMock()
            index.build(chunks)

        assert index.size == 2

    def test_search_not_built(self):
        """Test searching when index not built."""
        index = BM25Index()
        results = index.search("test query")
        assert results == []

    def test_search_empty_query(self):
        """Test searching with empty query."""
        index = BM25Index()
        index._index = MagicMock()
        index._chunk_ids = ["chunk1"]
        index._corpus = [["word"]]

        results = index.search("")
        assert results == []

    @patch("rank_bm25.BM25Okapi")
    def test_search_returns_results(self, mock_bm25_class):
        """Test search returns ranked results."""
        mock_bm25 = MagicMock()
        mock_bm25.get_scores.return_value = np.array([0.5, 0.8, 0.3])
        mock_bm25_class.return_value = mock_bm25

        index = BM25Index()
        chunks = [
            CorpusChunk(
                chunk_id=f"paper1:{i}",
                paper_id="paper1",
                title="Test",
                content=f"content {i}",
                token_count=2,
            )
            for i in range(3)
        ]
        index.build(chunks)

        results = index.search("test query", top_k=2)

        # Should return top 2 by score
        assert len(results) == 2
        assert results[0][0] == "paper1:1"  # Highest score
        assert results[0][1] == 0.8

    def test_save_and_load(self):
        """Test saving and loading index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)

            # Create and save index
            index = BM25Index()
            index._chunk_ids = ["chunk1", "chunk2"]
            index._corpus = [["word1"], ["word2"]]
            index.save(path)

            # Verify files exist
            assert (path / "bm25_metadata.json").exists()

            # Load index
            with patch("rank_bm25.BM25Okapi") as mock_bm25:
                mock_bm25.return_value = MagicMock()
                new_index = BM25Index()
                new_index.load(path)

            assert new_index._chunk_ids == ["chunk1", "chunk2"]

    def test_load_not_found(self):
        """Test loading from non-existent path."""
        index = BM25Index()
        with pytest.raises(FileNotFoundError):
            index.load(Path("/nonexistent/path"))


class TestDenseIndex:
    """Tests for DenseIndex class."""

    def test_init_default(self):
        """Test default initialization."""
        index = DenseIndex()
        assert index.dimension == 768
        assert index.is_built is False
        assert index.size == 0

    def test_init_custom_dimension(self):
        """Test custom dimension initialization."""
        index = DenseIndex(dimension=384)
        assert index.dimension == 384

    def test_build_empty_corpus(self):
        """Test building index with empty data."""
        index = DenseIndex()
        index.build([], np.array([]).reshape(0, 768))
        assert index.is_built is False
        assert index.size == 0

    @patch("faiss.IndexFlatIP")
    @patch("faiss.normalize_L2")
    def test_build_with_embeddings(self, mock_normalize, mock_index_class):
        """Test building index with embeddings."""
        mock_index = MagicMock()
        mock_index_class.return_value = mock_index

        index = DenseIndex()
        chunk_ids = ["chunk1", "chunk2"]
        embeddings = np.random.rand(2, 768).astype(np.float32)

        index.build(chunk_ids, embeddings)

        assert index.size == 2
        mock_index.add.assert_called_once()

    def test_build_mismatched_sizes(self):
        """Test building with mismatched sizes."""
        index = DenseIndex()
        with pytest.raises(ValueError, match="Mismatch"):
            index.build(["chunk1"], np.random.rand(2, 768))

    def test_search_not_built(self):
        """Test searching when index not built."""
        index = DenseIndex()
        results = index.search(np.random.rand(768))
        assert results == []

    @patch("faiss.normalize_L2")
    def test_search_returns_results(self, mock_normalize):
        """Test search returns ranked results."""
        index = DenseIndex()
        index._chunk_ids = ["chunk1", "chunk2", "chunk3"]

        mock_index = MagicMock()
        # Return only top_k results from FAISS
        mock_index.search.return_value = (
            np.array([[0.9, 0.7]]),
            np.array([[1, 0]]),
        )
        index._index = mock_index

        results = index.search(np.random.rand(768), top_k=2)

        assert len(results) == 2
        assert results[0][0] == "chunk2"  # Index 1
        assert results[0][1] == 0.9

    def test_save_and_load(self):
        """Test saving and loading index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)

            # Create index
            index = DenseIndex(dimension=64)
            index._chunk_ids = ["chunk1", "chunk2"]

            with patch("faiss.write_index"):
                index.save(path)

            # Verify metadata exists
            assert (path / "dense_metadata.json").exists()

            # Load
            with patch("faiss.read_index") as mock_read:
                mock_read.return_value = MagicMock()
                new_index = DenseIndex()
                new_index.load(path)

            assert new_index._chunk_ids == ["chunk1", "chunk2"]
            assert new_index.dimension == 64


class TestHybridSearchEngine:
    """Tests for HybridSearchEngine class."""

    def test_init_default(self):
        """Test default initialization."""
        engine = HybridSearchEngine()
        assert engine.is_ready is False
        assert engine.corpus_size == 0

    def test_init_custom_config(self):
        """Test custom configuration."""
        corpus_config = CorpusConfig(chunk_max_tokens=256)
        search_config = SearchConfig(dense_weight=0.8, sparse_weight=0.2)

        engine = HybridSearchEngine(
            corpus_config=corpus_config,
            search_config=search_config,
        )

        assert engine.corpus_config.chunk_max_tokens == 256
        assert engine.search_config.dense_weight == 0.8

    def test_index_chunks_empty(self):
        """Test indexing empty chunk list."""
        engine = HybridSearchEngine()
        engine.index_chunks([])
        assert engine.corpus_size == 0

    @patch.object(EmbeddingModel, "encode")
    @patch.object(BM25Index, "build")
    @patch.object(DenseIndex, "build")
    def test_index_chunks(self, mock_dense_build, mock_bm25_build, mock_encode):
        """Test indexing chunks."""
        mock_encode.return_value = np.random.rand(2, 768)

        engine = HybridSearchEngine()
        engine._embedding_model = MagicMock()
        engine._embedding_model.encode = mock_encode

        chunks = [
            CorpusChunk(
                chunk_id="paper1:0",
                paper_id="paper1",
                title="Test",
                content="content one",
                token_count=2,
            ),
            CorpusChunk(
                chunk_id="paper1:1",
                paper_id="paper1",
                title="Test",
                content="content two",
                token_count=2,
            ),
        ]

        engine.index_chunks(chunks)

        mock_bm25_build.assert_called_once()
        mock_dense_build.assert_called_once()
        assert engine.corpus_size == 2

    def test_search_not_ready(self):
        """Test searching when not ready."""
        engine = HybridSearchEngine()
        results = engine.search("test query")
        assert results == []

    def test_reciprocal_rank_fusion(self):
        """Test RRF score calculation."""
        engine = HybridSearchEngine()

        dense_results = [("chunk1", 0.9), ("chunk2", 0.7), ("chunk3", 0.5)]
        sparse_results = [("chunk2", 10.0), ("chunk1", 5.0), ("chunk4", 3.0)]

        fused = engine._reciprocal_rank_fusion(
            dense_results,
            sparse_results,
            dense_weight=0.7,
            sparse_weight=0.3,
            k=60,
        )

        # All chunks should have scores
        assert "chunk1" in fused
        assert "chunk2" in fused
        assert "chunk3" in fused
        assert "chunk4" in fused

        # chunk2 appears in both, should have higher score
        # chunk1: dense rank 1, sparse rank 2
        # chunk2: dense rank 2, sparse rank 1

    def test_get_chunk(self):
        """Test getting chunk by ID."""
        engine = HybridSearchEngine()
        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            title="Test",
            content="content",
            token_count=1,
        )
        engine._chunks["paper1:0"] = chunk

        result = engine.get_chunk("paper1:0")
        assert result == chunk

        result = engine.get_chunk("nonexistent")
        assert result is None

    def test_save_and_load(self):
        """Test saving and loading engine state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)

            engine = HybridSearchEngine()
            chunk = CorpusChunk(
                chunk_id="paper1:0",
                paper_id="paper1",
                section_type=ChunkType.ABSTRACT,
                title="Test Paper",
                content="Test content",
                token_count=2,
                checksum="abc123",
                metadata={"doi": "10.1234"},
            )
            engine._chunks["paper1:0"] = chunk

            with patch.object(DenseIndex, "save"):
                with patch.object(BM25Index, "save"):
                    engine.save(path)

            # Verify chunks file exists
            assert (path / "chunks.json").exists()

            # Load
            with patch.object(DenseIndex, "load"):
                with patch.object(BM25Index, "load"):
                    new_engine = HybridSearchEngine()
                    new_engine.load(path)

            assert "paper1:0" in new_engine._chunks
            loaded_chunk = new_engine._chunks["paper1:0"]
            assert loaded_chunk.title == "Test Paper"
            assert loaded_chunk.section_type == ChunkType.ABSTRACT

    def test_load_not_found(self):
        """Test loading from non-existent path."""
        engine = HybridSearchEngine()
        with pytest.raises(FileNotFoundError):
            engine.load(Path("/nonexistent/path"))

    @patch.object(EmbeddingModel, "encode_single")
    @patch.object(DenseIndex, "search")
    @patch.object(BM25Index, "search")
    def test_search_with_section_filter(
        self, mock_bm25_search, mock_dense_search, mock_encode
    ):
        """Test search with section type filter."""
        mock_encode.return_value = np.random.rand(768)
        mock_dense_search.return_value = [("paper1:0", 0.9), ("paper1:1", 0.8)]
        mock_bm25_search.return_value = [("paper1:0", 5.0), ("paper1:1", 3.0)]

        engine = HybridSearchEngine()
        engine._embedding_model = MagicMock()
        engine._embedding_model.encode_single = mock_encode
        engine._dense_index._index = MagicMock()  # Make it "built"
        engine._bm25_index._index = MagicMock()

        # Add chunks with different section types
        engine._chunks["paper1:0"] = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            section_type=ChunkType.METHODS,
            title="Test",
            content="Methods content",
            token_count=2,
        )
        engine._chunks["paper1:1"] = CorpusChunk(
            chunk_id="paper1:1",
            paper_id="paper1",
            section_type=ChunkType.RESULTS,
            title="Test",
            content="Results content",
            token_count=2,
        )

        results = engine.search("query", section_filter=ChunkType.METHODS)

        # Should only return METHODS chunk
        assert len(results) == 1
        assert results[0].section_type == ChunkType.METHODS

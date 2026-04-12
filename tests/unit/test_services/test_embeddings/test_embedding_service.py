"""Unit tests for EmbeddingService."""

from typing import Optional
from unittest.mock import Mock, patch

import numpy as np
import pytest

from src.services.embeddings.embedding_service import EmbeddingService


class MockPaper:
    """Mock paper for testing."""

    def __init__(self, paper_id: str, title: str, abstract: Optional[str] = None):
        self.paper_id = paper_id
        self.title = title
        self.abstract = abstract


@pytest.fixture
def embedding_service(tmp_path):
    """Create EmbeddingService with temp cache dir."""
    return EmbeddingService(
        model_name="allenai/specter2",
        cache_dir=tmp_path / "embeddings",
        fallback="tfidf",
    )


@pytest.fixture
def sample_paper():
    """Create a sample paper."""
    return MockPaper(
        paper_id="arxiv:2401.12345",
        title="Attention Is All You Need",
        abstract="We propose a new simple network architecture.",
    )


class TestEmbeddingServiceInit:
    """Tests for EmbeddingService initialization."""

    def test_init_default(self, tmp_path):
        """Test default initialization."""
        service = EmbeddingService(cache_dir=tmp_path)
        assert service.model_name == "allenai/specter2"
        assert service.fallback == "tfidf"
        assert service.batch_size == 32

    def test_init_custom(self, tmp_path):
        """Test custom initialization."""
        service = EmbeddingService(
            model_name="allenai/specter",
            cache_dir=tmp_path,
            fallback="none",
            batch_size=64,
        )
        assert service.model_name == "allenai/specter"
        assert service.fallback == "none"
        assert service.batch_size == 64

    def test_init_invalid_model_raises(self, tmp_path):
        """Test that invalid model raises ValueError."""
        with pytest.raises(ValueError, match="not in approved list"):
            EmbeddingService(
                model_name="invalid-model",
                cache_dir=tmp_path,
            )

    def test_init_creates_cache_dir(self, tmp_path):
        """Test that cache dir is created."""
        cache_dir = tmp_path / "subdir" / "embeddings"
        EmbeddingService(cache_dir=cache_dir)
        assert cache_dir.exists()


class TestEmbeddingServiceCaching:
    """Tests for embedding caching."""

    def test_get_cache_path(self, embedding_service):
        """Test cache path generation."""
        path = embedding_service._get_cache_path("test-paper-id")
        assert path.suffix == ".npy"
        assert path.parent == embedding_service.cache_dir

    def test_cache_path_uses_hash(self, embedding_service):
        """Test that cache path uses hash for safety."""
        path1 = embedding_service._get_cache_path("paper/with/slashes")
        path2 = embedding_service._get_cache_path("paper:with:colons")
        # Should not contain problematic characters
        assert "/" not in path1.name
        assert ":" not in path2.name


class TestEmbeddingServicePrepareText:
    """Tests for text preparation."""

    def test_prepare_text_with_abstract(self, embedding_service, sample_paper):
        """Test text preparation with abstract."""
        text = embedding_service._prepare_text(sample_paper)
        assert "[SEP]" in text
        assert sample_paper.title in text
        assert sample_paper.abstract in text

    def test_prepare_text_without_abstract(self, embedding_service):
        """Test text preparation without abstract."""
        paper = MockPaper(paper_id="test", title="Test Title", abstract=None)
        text = embedding_service._prepare_text(paper)
        assert "Test Title" in text
        assert "[SEP]" in text


class TestEmbeddingServiceGetEmbedding:
    """Tests for get_embedding method."""

    @pytest.mark.asyncio
    async def test_get_embedding_returns_array(self, embedding_service, sample_paper):
        """Test that get_embedding returns numpy array."""
        # Will use TF-IDF fallback since model not installed
        embedding = await embedding_service.get_embedding(sample_paper)

        assert isinstance(embedding, np.ndarray)
        assert embedding.shape == (EmbeddingService.EMBEDDING_DIM,)
        assert embedding.dtype == np.float32

    @pytest.mark.asyncio
    async def test_get_embedding_caches_result(self, embedding_service, sample_paper):
        """Test that embedding is cached."""
        # First call
        embedding1 = await embedding_service.get_embedding(sample_paper)

        # Check cache file exists
        cache_path = embedding_service._get_cache_path(sample_paper.paper_id)
        assert cache_path.exists()

        # Second call should return same result from cache
        embedding2 = await embedding_service.get_embedding(sample_paper)
        np.testing.assert_array_equal(embedding1, embedding2)

    @pytest.mark.asyncio
    async def test_get_embedding_skip_cache(self, embedding_service, sample_paper):
        """Test get_embedding with cache disabled."""
        embedding = await embedding_service.get_embedding(sample_paper, use_cache=False)

        # Should still work
        assert isinstance(embedding, np.ndarray)

        # Cache file should not exist
        cache_path = embedding_service._get_cache_path(sample_paper.paper_id)
        assert not cache_path.exists()

    @pytest.mark.asyncio
    async def test_get_embedding_with_model(self, embedding_service, sample_paper):
        """Test get_embedding with mocked model."""
        # Mock the model
        mock_model = Mock()
        mock_embedding = np.random.randn(EmbeddingService.EMBEDDING_DIM).astype(
            np.float32
        )
        mock_model.encode = Mock(return_value=mock_embedding)
        embedding_service._model = mock_model

        embedding = await embedding_service.get_embedding(sample_paper, use_cache=False)

        np.testing.assert_array_equal(embedding, mock_embedding)
        mock_model.encode.assert_called_once()


class TestEmbeddingServiceBatch:
    """Tests for batch embedding computation."""

    @pytest.mark.asyncio
    async def test_compute_embeddings_batch_empty(self, embedding_service):
        """Test batch computation with empty list."""
        result = await embedding_service.compute_embeddings_batch([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_compute_embeddings_batch(self, embedding_service):
        """Test batch computation."""
        papers = [
            MockPaper(f"paper-{i}", f"Title {i}", f"Abstract {i}") for i in range(3)
        ]

        result = await embedding_service.compute_embeddings_batch(papers)

        assert len(result) == 3
        for paper in papers:
            assert paper.paper_id in result
            assert result[paper.paper_id].shape == (EmbeddingService.EMBEDDING_DIM,)

    @pytest.mark.asyncio
    async def test_compute_embeddings_batch_uses_cache(self, embedding_service):
        """Test that batch computation uses cache."""
        paper = MockPaper("cached-paper", "Title", "Abstract")

        # First compute to cache
        await embedding_service.get_embedding(paper)

        # Batch should use cached
        result = await embedding_service.compute_embeddings_batch([paper])

        assert "cached-paper" in result


class TestEmbeddingServiceIndex:
    """Tests for FAISS index operations."""

    @pytest.mark.asyncio
    async def test_build_index_empty(self, embedding_service):
        """Test building index with empty list."""
        await embedding_service.build_index([])
        assert embedding_service.index_size == 0

    @pytest.mark.asyncio
    async def test_build_index(self, embedding_service):
        """Test building FAISS index."""
        papers = [
            MockPaper(f"paper-{i}", f"Title {i}", f"Abstract {i}") for i in range(5)
        ]

        # This will fail if faiss not installed, which is expected
        try:
            import faiss  # noqa: F401

            await embedding_service.build_index(papers)
            assert embedding_service.index_size == 5
        except ImportError:
            pytest.skip("FAISS not installed")

    @pytest.mark.asyncio
    async def test_search_similar_no_index(self, embedding_service):
        """Test search with no index built."""
        query = np.random.randn(EmbeddingService.EMBEDDING_DIM).astype(np.float32)
        results = await embedding_service.search_similar(query)
        assert results == []


class TestEmbeddingServiceTFIDFFallback:
    """Tests for TF-IDF fallback."""

    @pytest.mark.asyncio
    async def test_tfidf_fallback_works(self, embedding_service, sample_paper):
        """Test TF-IDF fallback produces valid embedding."""
        # Ensure model is not loaded
        embedding_service._model = None

        embedding = await embedding_service.get_embedding(sample_paper, use_cache=False)

        assert isinstance(embedding, np.ndarray)
        assert embedding.shape == (EmbeddingService.EMBEDDING_DIM,)

    @pytest.mark.asyncio
    async def test_tfidf_fallback_disabled(self, tmp_path, sample_paper):
        """Test when TF-IDF fallback is disabled."""
        service = EmbeddingService(
            cache_dir=tmp_path,
            fallback="none",
        )
        service._model = None

        embedding = await service.get_embedding(sample_paper, use_cache=False)

        # Should return zero vector
        assert np.allclose(embedding, np.zeros(EmbeddingService.EMBEDDING_DIM))


class TestEmbeddingServiceProperties:
    """Tests for service properties."""

    def test_index_size_no_index(self, embedding_service):
        """Test index_size with no index."""
        assert embedding_service.index_size == 0

    def test_is_model_available_false(self, embedding_service):
        """Test is_model_available when model not loaded."""
        assert embedding_service.is_model_available is False

    def test_is_model_available_true(self, embedding_service):
        """Test is_model_available when model loaded."""
        embedding_service._model = Mock()
        assert embedding_service.is_model_available is True


class TestEmbeddingServiceClearCache:
    """Tests for cache clearing."""

    @pytest.mark.asyncio
    async def test_clear_cache(self, embedding_service, sample_paper):
        """Test clearing the cache."""
        # Create some cached embeddings
        await embedding_service.get_embedding(sample_paper)

        # Verify cache exists
        cache_files = list(embedding_service.cache_dir.glob("*.npy"))
        assert len(cache_files) > 0

        # Clear cache
        count = await embedding_service.clear_cache()

        assert count > 0
        cache_files = list(embedding_service.cache_dir.glob("*.npy"))
        assert len(cache_files) == 0


class TestEmbeddingServiceModelLoading:
    """Tests for model loading paths."""

    @pytest.mark.asyncio
    async def test_load_model_already_loaded(self, embedding_service):
        """Test model load when already loaded."""
        embedding_service._model = Mock()
        result = await embedding_service._load_model()
        assert result is True

    @pytest.mark.asyncio
    async def test_load_model_import_error(self, embedding_service):
        """Test model load with ImportError."""
        embedding_service._model = None
        result = await embedding_service._load_model()
        # Will return False if sentence_transformers not installed
        assert result is False

    @pytest.mark.asyncio
    async def test_use_fallback_true(self, embedding_service):
        """Test _use_fallback returns True when model is None and fallback enabled."""
        embedding_service._model = None
        embedding_service.fallback = "tfidf"
        assert embedding_service._use_fallback() is True

    @pytest.mark.asyncio
    async def test_use_fallback_false_model_loaded(self, embedding_service):
        """Test _use_fallback returns False when model is loaded."""
        embedding_service._model = Mock()
        assert embedding_service._use_fallback() is False

    @pytest.mark.asyncio
    async def test_use_fallback_false_no_fallback(self, tmp_path):
        """Test _use_fallback returns False when fallback is none."""
        service = EmbeddingService(cache_dir=tmp_path, fallback="none")
        service._model = None
        assert service._use_fallback() is False


class TestEmbeddingServiceExceptionHandling:
    """Tests for exception handling in embedding service."""

    @pytest.mark.asyncio
    async def test_cache_load_exception(self, embedding_service, sample_paper):
        """Test cache load exception handling."""
        # Create a corrupted cache file
        cache_path = embedding_service._get_cache_path(sample_paper.paper_id)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(b"corrupted data")

        # Should handle exception and recompute
        embedding = await embedding_service.get_embedding(sample_paper)
        assert isinstance(embedding, np.ndarray)

    @pytest.mark.asyncio
    async def test_cache_save_exception(self, embedding_service, sample_paper):
        """Test cache save exception handling."""
        # Make cache dir read-only to cause save failure
        embedding_service.cache_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(np, "save", side_effect=OSError("Permission denied")):
            # Should still return embedding even if save fails
            embedding = await embedding_service.get_embedding(sample_paper)
            assert isinstance(embedding, np.ndarray)

    @pytest.mark.asyncio
    async def test_model_encode_exception_with_fallback(
        self, embedding_service, sample_paper
    ):
        """Test model encode exception falls back to TF-IDF."""
        mock_model = Mock()
        mock_model.encode = Mock(side_effect=Exception("Encode failed"))
        embedding_service._model = mock_model

        embedding = await embedding_service.get_embedding(sample_paper, use_cache=False)

        # Should fall back to TF-IDF
        assert isinstance(embedding, np.ndarray)
        assert embedding.shape == (EmbeddingService.EMBEDDING_DIM,)

    @pytest.mark.asyncio
    async def test_model_encode_exception_no_fallback(self, tmp_path, sample_paper):
        """Test model encode exception with no fallback returns zero."""
        service = EmbeddingService(cache_dir=tmp_path, fallback="none")
        mock_model = Mock()
        mock_model.encode = Mock(side_effect=Exception("Encode failed"))
        service._model = mock_model

        embedding = await service.get_embedding(sample_paper, use_cache=False)

        # Should return zero vector
        assert np.allclose(embedding, np.zeros(EmbeddingService.EMBEDDING_DIM))

    @pytest.mark.asyncio
    async def test_tfidf_fallback_returns_embedding(
        self, embedding_service, sample_paper
    ):
        """Test TF-IDF fallback returns valid embedding."""
        embedding_service._model = None
        embedding_service._tfidf_vectorizer = None

        embedding = await embedding_service.get_embedding(sample_paper, use_cache=False)

        # Should use TF-IDF fallback and return valid embedding
        assert isinstance(embedding, np.ndarray)
        assert embedding.shape == (EmbeddingService.EMBEDDING_DIM,)

    @pytest.mark.asyncio
    async def test_tfidf_transform_exception(self, embedding_service, sample_paper):
        """Test TF-IDF transform exception handling."""
        embedding_service._model = None

        # Create a TF-IDF vectorizer that raises on transform
        mock_vectorizer = Mock()
        mock_vectorizer.transform = Mock(side_effect=Exception("Transform failed"))
        embedding_service._tfidf_vectorizer = mock_vectorizer

        embedding = await embedding_service._compute_tfidf_embedding("test text")

        # Should return zeros on exception
        assert np.allclose(embedding, np.zeros(EmbeddingService.EMBEDDING_DIM))


class TestEmbeddingServiceBatchWithModel:
    """Tests for batch embedding with model."""

    @pytest.mark.asyncio
    async def test_batch_with_model(self, embedding_service):
        """Test batch computation with mocked model."""
        papers = [
            MockPaper(f"paper-{i}", f"Title {i}", f"Abstract {i}") for i in range(3)
        ]

        mock_embeddings = np.random.randn(3, EmbeddingService.EMBEDDING_DIM).astype(
            np.float32
        )
        mock_model = Mock()
        mock_model.encode = Mock(return_value=mock_embeddings)
        embedding_service._model = mock_model

        result = await embedding_service.compute_embeddings_batch(papers)

        assert len(result) == 3
        mock_model.encode.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_model_exception_fallback(self, embedding_service):
        """Test batch computation falls back on model exception."""
        papers = [MockPaper("paper-1", "Title 1", "Abstract 1")]

        mock_model = Mock()
        mock_model.encode = Mock(side_effect=Exception("Batch encode failed"))
        embedding_service._model = mock_model

        result = await embedding_service.compute_embeddings_batch(papers)

        # Should fall back to individual computation
        assert len(result) == 1
        assert "paper-1" in result

    @pytest.mark.asyncio
    async def test_batch_cache_load_exception(self, embedding_service):
        """Test batch ignores cache load exceptions."""
        papers = [MockPaper("paper-1", "Title 1", "Abstract 1")]

        # Create corrupted cache
        cache_path = embedding_service._get_cache_path("paper-1")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(b"corrupted")

        result = await embedding_service.compute_embeddings_batch(papers)

        assert len(result) == 1


class TestEmbeddingServiceFAISS:
    """Tests for FAISS operations with mocking."""

    @pytest.mark.asyncio
    async def test_build_index_with_papers(self, embedding_service):
        """Test build_index with mocked FAISS."""
        papers = [
            MockPaper(f"paper-{i}", f"Title {i}", f"Abstract {i}") for i in range(3)
        ]

        # Mock faiss module
        mock_faiss = Mock()
        mock_index = Mock()
        mock_index.ntotal = 3
        mock_faiss.IndexFlatIP = Mock(return_value=mock_index)
        mock_faiss.normalize_L2 = Mock()

        with patch.dict("sys.modules", {"faiss": mock_faiss}):
            await embedding_service.build_index(papers)

            # Verify FAISS was called
            mock_faiss.IndexFlatIP.assert_called_once_with(
                EmbeddingService.EMBEDDING_DIM
            )
            mock_faiss.normalize_L2.assert_called_once()
            mock_index.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_index_no_embeddings(self, embedding_service):
        """Test build_index with no embeddings computed."""
        papers = [MockPaper("paper-1", "Title 1")]

        # Mock compute_embeddings_batch to return empty
        async def mock_batch(papers):
            return {}

        embedding_service.compute_embeddings_batch = mock_batch

        mock_faiss = Mock()
        with patch.dict("sys.modules", {"faiss": mock_faiss}):
            await embedding_service.build_index(papers)
            # Should not create index with no embeddings

    @pytest.mark.asyncio
    async def test_search_similar_with_faiss(self, embedding_service):
        """Test search_similar with mocked FAISS index."""
        # Set up mock FAISS index
        mock_index = Mock()
        mock_index.search = Mock(
            return_value=(
                np.array([[0.9, 0.8, 0.7]]),  # distances
                np.array([[0, 1, 2]]),  # indices
            )
        )
        embedding_service._faiss_index = mock_index
        embedding_service._idx_to_paper_id = {0: "p1", 1: "p2", 2: "p3"}

        mock_faiss = Mock()
        mock_faiss.normalize_L2 = Mock()

        query = np.random.randn(EmbeddingService.EMBEDDING_DIM).astype(np.float32)

        with patch.dict("sys.modules", {"faiss": mock_faiss}):
            results = await embedding_service.search_similar(query, top_k=3)

        assert len(results) == 3
        assert results[0][0] == "p1"

    @pytest.mark.asyncio
    async def test_search_similar_excludes_ids(self, embedding_service):
        """Test search_similar excludes specified IDs."""
        mock_index = Mock()
        mock_index.search = Mock(
            return_value=(
                np.array([[0.9, 0.8, 0.7]]),
                np.array([[0, 1, 2]]),
            )
        )
        embedding_service._faiss_index = mock_index
        embedding_service._idx_to_paper_id = {0: "p1", 1: "p2", 2: "p3"}

        mock_faiss = Mock()
        mock_faiss.normalize_L2 = Mock()

        query = np.random.randn(EmbeddingService.EMBEDDING_DIM).astype(np.float32)

        with patch.dict("sys.modules", {"faiss": mock_faiss}):
            results = await embedding_service.search_similar(
                query, top_k=3, exclude_ids=["p1"]
            )

        # p1 should be excluded
        result_ids = [r[0] for r in results]
        assert "p1" not in result_ids

    @pytest.mark.asyncio
    async def test_search_similar_handles_invalid_indices(self, embedding_service):
        """Test search_similar handles invalid indices gracefully."""
        mock_index = Mock()
        mock_index.search = Mock(
            return_value=(
                np.array([[0.9, 0.8, 0.7]]),
                np.array([[-1, 1, 999]]),  # -1 and 999 are invalid
            )
        )
        embedding_service._faiss_index = mock_index
        embedding_service._idx_to_paper_id = {1: "p2"}

        mock_faiss = Mock()
        mock_faiss.normalize_L2 = Mock()

        query = np.random.randn(EmbeddingService.EMBEDDING_DIM).astype(np.float32)

        with patch.dict("sys.modules", {"faiss": mock_faiss}):
            results = await embedding_service.search_similar(query, top_k=3)

        # Only valid index (1) should be in results
        assert len(results) == 1
        assert results[0][0] == "p2"

    @pytest.mark.asyncio
    async def test_search_similar_faiss_import_error(self, embedding_service):
        """Test search_similar when faiss not installed."""
        mock_index = Mock()
        embedding_service._faiss_index = mock_index

        with patch.dict("sys.modules", {"faiss": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("faiss not found"),
            ):
                query = np.random.randn(EmbeddingService.EMBEDDING_DIM).astype(
                    np.float32
                )
                results = await embedding_service.search_similar(query)
                assert results == []

    @pytest.mark.asyncio
    async def test_index_size_with_faiss(self, embedding_service):
        """Test index_size property with FAISS index."""
        mock_index = Mock()
        mock_index.ntotal = 42
        embedding_service._faiss_index = mock_index

        assert embedding_service.index_size == 42

    @pytest.mark.asyncio
    async def test_build_index_empty_papers_warning(self, embedding_service):
        """Test build_index logs warning for empty papers."""
        mock_faiss = Mock()

        with patch.dict("sys.modules", {"faiss": mock_faiss}):
            await embedding_service.build_index([])

        # Should not create index
        assert embedding_service._faiss_index is None


class TestEmbeddingServiceAdditionalCoverage:
    """Additional tests for full coverage."""

    @pytest.mark.asyncio
    async def test_tfidf_vector_truncation(self, embedding_service):
        """Test TF-IDF with vector that needs truncation."""
        embedding_service._model = None
        embedding_service._tfidf_vectorizer = None

        # Create a long text to generate more TF-IDF features
        long_text = " ".join([f"word{i}" for i in range(1000)])

        embedding = await embedding_service._compute_tfidf_embedding(long_text)

        assert embedding.shape == (EmbeddingService.EMBEDDING_DIM,)
        assert embedding.dtype == np.float32

    @pytest.mark.asyncio
    async def test_batch_with_model_cache_save_exception(self, embedding_service):
        """Test batch compute continues when cache save fails."""
        papers = [MockPaper("paper-1", "Title 1", "Abstract 1")]

        mock_embeddings = np.random.randn(1, EmbeddingService.EMBEDDING_DIM).astype(
            np.float32
        )
        mock_model = Mock()
        mock_model.encode = Mock(return_value=mock_embeddings)
        embedding_service._model = mock_model

        # Make cache save fail
        def failing_save(path, arr):
            raise OSError("Save failed")

        with patch.object(np, "save", side_effect=failing_save):
            result = await embedding_service.compute_embeddings_batch(papers)

        # Should still return result despite save failure
        assert len(result) == 1
        assert "paper-1" in result

    @pytest.mark.asyncio
    async def test_get_embedding_model_exception_no_fallback(self, tmp_path):
        """Test model exception returns zeros when no fallback."""
        service = EmbeddingService(cache_dir=tmp_path, fallback="none")
        mock_model = Mock()
        mock_model.encode = Mock(side_effect=Exception("Encode error"))
        service._model = mock_model

        paper = MockPaper("test", "Title", "Abstract")
        embedding = await service.get_embedding(paper, use_cache=False)

        assert np.allclose(embedding, np.zeros(EmbeddingService.EMBEDDING_DIM))

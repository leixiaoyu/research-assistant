"""Embedding service for Phase 7.3 Human Feedback Loop.

This module provides paper embedding computation using SPECTER2
with fallback to TF-IDF when the model is unavailable.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Protocol, runtime_checkable

import numpy as np

logger = logging.getLogger(__name__)


# Type alias for paper-like objects
@runtime_checkable
class PaperLike(Protocol):
    """Protocol for paper-like objects with title and abstract."""

    paper_id: str
    title: str
    abstract: Optional[str]


class EmbeddingService:
    """Service for computing and caching paper embeddings.

    Supports SPECTER2 for academic paper embeddings with
    TF-IDF fallback when the model is unavailable.

    Attributes:
        model_name: Name of the embedding model.
        cache_dir: Directory for embedding cache.
        fallback: Fallback method (tfidf or none).
        batch_size: Batch size for embedding computation.
    """

    # SPECTER2 embedding dimension
    EMBEDDING_DIM = 768

    # Approved embedding models (security requirement)
    APPROVED_MODELS = {
        "allenai/specter2",
        "allenai/specter",
        "sentence-transformers/all-MiniLM-L6-v2",
    }

    def __init__(
        self,
        model_name: str = "allenai/specter2",
        cache_dir: Path | str = ".cache/embeddings",
        fallback: str = "tfidf",
        batch_size: int = 32,
    ) -> None:
        """Initialize embedding service.

        Args:
            model_name: Name of the embedding model.
            cache_dir: Directory for embedding cache.
            fallback: Fallback method when model unavailable.
            batch_size: Batch size for embedding computation.

        Raises:
            ValueError: If model is not in approved list.
        """
        if model_name not in self.APPROVED_MODELS:
            raise ValueError(
                f"Model '{model_name}' not in approved list: {self.APPROVED_MODELS}"
            )

        self.model_name = model_name
        self.cache_dir = Path(cache_dir)
        self.fallback = fallback
        self.batch_size = batch_size

        self._model = None
        self._tokenizer = None
        self._tfidf_vectorizer = None
        self._faiss_index = None
        self._paper_id_to_idx: Dict[str, int] = {}
        self._idx_to_paper_id: Dict[int, str] = {}

        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, paper_id: str) -> Path:
        """Get cache file path for a paper's embedding."""
        # Use hash to avoid filesystem issues with paper IDs
        hash_id = hashlib.sha256(paper_id.encode()).hexdigest()[:16]
        return self.cache_dir / f"{hash_id}.npy"

    async def _load_model(self) -> bool:
        """Load the embedding model.

        Returns:
            True if model loaded successfully, False otherwise.
        """
        if self._model is not None:
            return True

        try:  # pragma: no cover - external model loading
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            logger.info(f"Loaded embedding model: {self.model_name}")
            return True
        except ImportError:
            logger.warning("sentence-transformers not installed, using fallback")
            return False
        except Exception as e:  # pragma: no cover - external library error
            logger.warning(f"Failed to load model {self.model_name}: {e}")
            return False

    def _use_fallback(self) -> bool:
        """Check if fallback mode should be used."""
        return self._model is None and self.fallback != "none"

    async def _compute_tfidf_embedding(self, text: str) -> np.ndarray:
        """Compute TF-IDF based embedding as fallback.

        Args:
            text: Text to embed.

        Returns:
            TF-IDF vector padded/truncated to EMBEDDING_DIM.
        """
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError:  # pragma: no cover - external library check
            logger.error(
                "sklearn not installed for TF-IDF fallback"
            )  # pragma: no cover
            return np.zeros(self.EMBEDDING_DIM, dtype=np.float32)  # pragma: no cover

        if self._tfidf_vectorizer is None:
            vectorizer = TfidfVectorizer(
                max_features=self.EMBEDDING_DIM,
                stop_words="english",
            )
            # Fit on the text (will be refitted as more texts come in)
            vectorizer.fit([text])
            self._tfidf_vectorizer = vectorizer
        else:
            vectorizer = self._tfidf_vectorizer

        try:
            # Transform text to TF-IDF vector
            tfidf_vec = vectorizer.transform([text]).toarray()[0]

            # Pad or truncate to match EMBEDDING_DIM
            if len(tfidf_vec) < self.EMBEDDING_DIM:
                padded = np.zeros(self.EMBEDDING_DIM, dtype=np.float32)
                padded[: len(tfidf_vec)] = tfidf_vec
                return padded
            result: np.ndarray = tfidf_vec[: self.EMBEDDING_DIM].astype(np.float32)
            return result
        except Exception as e:
            logger.error(f"TF-IDF embedding failed: {e}")
            return np.zeros(self.EMBEDDING_DIM, dtype=np.float32)

    def _prepare_text(self, paper: PaperLike) -> str:
        """Prepare paper text for embedding.

        SPECTER2 expects format: "title [SEP] abstract"
        """
        title = paper.title or ""
        abstract = paper.abstract or ""
        return f"{title} [SEP] {abstract}"

    async def get_embedding(
        self,
        paper: PaperLike,
        use_cache: bool = True,
    ) -> np.ndarray:
        """Get embedding for a paper.

        Args:
            paper: Paper object with title and abstract.
            use_cache: Whether to use cached embeddings.

        Returns:
            Embedding vector of shape (EMBEDDING_DIM,).
        """
        cache_path = self._get_cache_path(paper.paper_id)
        embedding: np.ndarray

        # Check cache first
        if use_cache and cache_path.exists():
            try:
                cached: np.ndarray = np.load(cache_path)
                logger.debug(f"Cache hit for paper {paper.paper_id}")
                return cached
            except Exception as e:
                logger.warning(f"Cache load failed: {e}")

        # Compute embedding
        text = self._prepare_text(paper)

        model_loaded = await self._load_model()

        if model_loaded and self._model is not None:
            try:
                embedding = self._model.encode(
                    text,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
                embedding = embedding.astype(np.float32)
            except Exception as e:
                logger.error(f"Model embedding failed: {e}")
                # Note: _use_fallback() is False here since _model is not None
                if (
                    self._use_fallback()
                ):  # pragma: no cover - unreachable when model loaded
                    embedding = await self._compute_tfidf_embedding(
                        text
                    )  # pragma: no cover
                else:
                    embedding = np.zeros(self.EMBEDDING_DIM, dtype=np.float32)
        elif self._use_fallback():
            embedding = await self._compute_tfidf_embedding(text)
        else:
            logger.warning(f"No embedding method available for {paper.paper_id}")
            embedding = np.zeros(self.EMBEDDING_DIM, dtype=np.float32)

        # Cache the embedding
        if use_cache:
            try:
                np.save(cache_path, embedding)
            except Exception as e:
                logger.warning(f"Cache save failed: {e}")

        return embedding

    async def compute_embeddings_batch(
        self,
        papers: List[PaperLike],
        use_cache: bool = True,
    ) -> Dict[str, np.ndarray]:
        """Compute embeddings for multiple papers.

        Args:
            papers: List of paper objects.
            use_cache: Whether to use cached embeddings.

        Returns:
            Dictionary mapping paper_id to embedding.
        """
        result: Dict[str, np.ndarray] = {}
        to_compute: List[PaperLike] = []

        # Check cache for each paper
        for paper in papers:
            cache_path = self._get_cache_path(paper.paper_id)
            if use_cache and cache_path.exists():
                try:
                    result[paper.paper_id] = np.load(cache_path)
                    continue
                except Exception:
                    pass
            to_compute.append(paper)

        if not to_compute:
            return result

        logger.info(f"Computing embeddings for {len(to_compute)} papers")

        model_loaded = await self._load_model()

        if model_loaded and self._model is not None:
            # Batch compute with model
            texts = [self._prepare_text(p) for p in to_compute]

            for i in range(0, len(texts), self.batch_size):
                batch_texts = texts[i : i + self.batch_size]
                batch_papers = to_compute[i : i + self.batch_size]

                try:
                    embeddings = self._model.encode(
                        batch_texts,
                        convert_to_numpy=True,
                        show_progress_bar=False,
                        batch_size=self.batch_size,
                    )

                    for paper, embedding in zip(batch_papers, embeddings):
                        emb = embedding.astype(np.float32)
                        result[paper.paper_id] = emb

                        if use_cache:
                            cache_path = self._get_cache_path(paper.paper_id)
                            try:
                                np.save(cache_path, emb)
                            except Exception:
                                pass
                except Exception as e:
                    logger.error(f"Batch embedding failed: {e}")
                    # Fall back to individual computation
                    for paper in batch_papers:
                        result[paper.paper_id] = await self.get_embedding(
                            paper, use_cache
                        )
        else:
            # Fall back to individual computation
            for paper in to_compute:
                result[paper.paper_id] = await self.get_embedding(paper, use_cache)

        return result

    async def build_index(
        self,
        papers: List[PaperLike],
    ) -> None:
        """Build FAISS index for similarity search.

        Args:
            papers: List of papers to index.
        """
        try:
            import faiss
        except ImportError:
            logger.error("faiss not installed, cannot build index")
            return

        if not papers:
            logger.warning("No papers to index")
            return

        # Compute embeddings
        embeddings_dict = await self.compute_embeddings_batch(papers)

        # Build index
        embeddings_list = []
        self._paper_id_to_idx = {}
        self._idx_to_paper_id = {}

        for idx, paper in enumerate(papers):
            if paper.paper_id in embeddings_dict:
                embeddings_list.append(embeddings_dict[paper.paper_id])
                self._paper_id_to_idx[paper.paper_id] = idx
                self._idx_to_paper_id[idx] = paper.paper_id

        if not embeddings_list:
            logger.warning("No embeddings computed")
            return

        embeddings_matrix = np.vstack(embeddings_list).astype(np.float32)

        # Create FAISS index (Flat L2 for small corpora)
        faiss_index = faiss.IndexFlatIP(self.EMBEDDING_DIM)  # Inner product
        # Normalize for cosine similarity
        faiss.normalize_L2(embeddings_matrix)
        faiss_index.add(embeddings_matrix)
        self._faiss_index = faiss_index

        logger.info(f"Built FAISS index with {len(embeddings_list)} papers")

        # Save index metadata
        metadata_path = self.cache_dir / "index_metadata.json"
        metadata = {
            "paper_id_to_idx": self._paper_id_to_idx,
            "idx_to_paper_id": {str(k): v for k, v in self._idx_to_paper_id.items()},
            "count": len(embeddings_list),
        }
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    async def search_similar(
        self,
        query_embedding: np.ndarray,
        top_k: int = 20,
        exclude_ids: Optional[List[str]] = None,
    ) -> List[tuple]:
        """Search for similar papers using FAISS index.

        Args:
            query_embedding: Query embedding vector.
            top_k: Number of results to return.
            exclude_ids: Paper IDs to exclude from results.

        Returns:
            List of (paper_id, similarity_score) tuples.
        """
        if self._faiss_index is None:
            logger.warning("FAISS index not built")
            return []

        try:
            import faiss
        except ImportError:
            return []

        # Normalize query for cosine similarity
        query = query_embedding.reshape(1, -1).astype(np.float32)
        faiss.normalize_L2(query)

        # Search
        distances, indices = self._faiss_index.search(query, top_k * 2)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:
                continue
            paper_id = self._idx_to_paper_id.get(idx)
            if paper_id is None:
                continue
            if exclude_ids and paper_id in exclude_ids:
                continue

            # Convert inner product to similarity score (0-1)
            similarity = float(max(0, min(1, (dist + 1) / 2)))
            results.append((paper_id, similarity))

            if len(results) >= top_k:
                break

        return results

    async def clear_cache(self) -> int:
        """Clear the embedding cache.

        Returns:
            Number of cache files deleted.
        """
        count = 0
        for cache_file in self.cache_dir.glob("*.npy"):
            cache_file.unlink()
            count += 1
        logger.info(f"Cleared {count} cached embeddings")
        return count

    @property
    def index_size(self) -> int:
        """Get the number of papers in the FAISS index."""
        if self._faiss_index is None:
            return 0
        return self._faiss_index.ntotal

    @property
    def is_model_available(self) -> bool:
        """Check if the embedding model is available."""
        return self._model is not None

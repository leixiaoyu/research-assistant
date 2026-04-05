"""Hybrid search engine combining dense (FAISS) and sparse (BM25) retrieval.

This module provides:
- FAISS-based dense vector search with SPECTER2 embeddings
- BM25-based sparse keyword search
- Reciprocal Rank Fusion (RRF) for result combination
- Configurable weighting between dense and sparse results
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import structlog

from src.models.dra import (
    ChunkType,
    CorpusChunk,
    CorpusConfig,
    SearchConfig,
    SearchResult,
)
from src.services.dra.utils import TextNormalizer

logger = structlog.get_logger()

# Type alias for FAISS index (lazy import)
FAISSIndex = object

# SR-8.5: Approved embedding models allowlist
APPROVED_EMBEDDING_MODELS: frozenset[str] = frozenset(
    {
        "allenai/specter2",
        "allenai/specter",
        "sentence-transformers/all-MiniLM-L6-v2",
        "sentence-transformers/all-mpnet-base-v2",
    }
)


class EmbeddingModel:
    """Wrapper for SPECTER2 embedding model.

    Supports both HuggingFace Hub download and local model path.
    """

    def __init__(
        self,
        model_name: str = "allenai/specter2",
        model_path: Optional[str] = None,
        batch_size: int = 32,
    ):
        """Initialize embedding model.

        Args:
            model_name: HuggingFace model name (must be in APPROVED_EMBEDDING_MODELS)
            model_path: Optional local path for offline use
            batch_size: Batch size for encoding

        Raises:
            ValueError: If model_name is not in the approved allowlist
        """
        # SR-8.5: Validate model is in approved allowlist
        if model_name not in APPROVED_EMBEDDING_MODELS:
            raise ValueError(
                f"Unapproved embedding model: {model_name}. "
                f"Allowed models: {sorted(APPROVED_EMBEDDING_MODELS)}"
            )

        self.model_name = model_name
        self.model_path = model_path
        self.batch_size = batch_size
        self._model = None
        self._tokenizer = None
        self._dimension: Optional[int] = None

    @property
    def dimension(self) -> int:
        """Get embedding dimension (loads model if needed)."""
        if self._dimension is None:
            self._load_model()
        return self._dimension  # type: ignore[return-value]

    def _load_model(self) -> None:
        """Lazy load the transformer model."""
        if self._model is not None:
            return

        try:
            from transformers import AutoModel, AutoTokenizer
        except (
            ImportError
        ) as e:  # pragma: no cover - defensive code for missing dependency
            raise ImportError(
                "transformers package required. Install with: pip install transformers"
            ) from e

        model_source = self.model_path or self.model_name

        logger.info("loading_embedding_model", model=model_source)

        # Security: Disable trust_remote_code to prevent arbitrary code execution
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_source, trust_remote_code=False
        )
        self._model = AutoModel.from_pretrained(model_source, trust_remote_code=False)
        self._model.eval()  # type: ignore[attr-defined]

        # Get dimension from model config
        self._dimension = self._model.config.hidden_size  # type: ignore[attr-defined]

        logger.info(
            "embedding_model_loaded",
            model=model_source,
            dimension=self._dimension,
        )

    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts to embeddings.

        Args:
            texts: List of text strings

        Returns:
            numpy array of shape (len(texts), dimension)
        """
        import torch

        self._load_model()

        if not texts:
            return np.array([]).reshape(0, self.dimension)

        all_embeddings = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]

            inputs = self._tokenizer(  # type: ignore[misc]
                batch,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )

            with torch.no_grad():
                outputs = self._model(**inputs)  # type: ignore[misc]
                # Use CLS token embedding
                embeddings = outputs.last_hidden_state[:, 0, :].numpy()
                all_embeddings.append(embeddings)

        return np.vstack(all_embeddings)

    def encode_single(self, text: str) -> np.ndarray:
        """Encode a single text.

        Args:
            text: Input text

        Returns:
            1D numpy array of shape (dimension,)
        """
        return self.encode([text])[0]  # type: ignore[no-any-return]


class BM25Index:
    """BM25 sparse retrieval index."""

    def __init__(self, normalizer: Optional[TextNormalizer] = None):
        """Initialize BM25 index.

        Args:
            normalizer: Text normalizer for preprocessing
        """
        self.normalizer = normalizer or TextNormalizer()
        self._index = None
        self._chunk_ids: list[str] = []
        self._corpus: list[list[str]] = []

    @property
    def is_built(self) -> bool:
        """Check if index is built."""
        return self._index is not None

    @property
    def size(self) -> int:
        """Get number of indexed documents."""
        return len(self._chunk_ids)

    def build(self, chunks: list[CorpusChunk]) -> None:
        """Build BM25 index from chunks.

        Args:
            chunks: List of corpus chunks to index
        """
        try:
            from rank_bm25 import BM25Okapi
        except (
            ImportError
        ) as e:  # pragma: no cover - defensive code for missing dependency
            raise ImportError(
                "rank_bm25 package required. Install with: pip install rank-bm25"
            ) from e

        if not chunks:
            logger.warning("bm25_build_empty_corpus")
            self._index = None
            self._chunk_ids = []
            self._corpus = []
            return

        self._chunk_ids = [c.chunk_id for c in chunks]
        self._corpus = [self.normalizer.tokenize(c.content) for c in chunks]

        self._index = BM25Okapi(self._corpus)

        logger.info("bm25_index_built", document_count=len(chunks))

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Search the BM25 index.

        Args:
            query: Search query
            top_k: Number of results to return

        Returns:
            List of (chunk_id, score) tuples sorted by score descending
        """
        if not self.is_built:
            return []

        tokenized_query = self.normalizer.tokenize(query)
        if not tokenized_query:
            return []

        scores = self._index.get_scores(tokenized_query)  # type: ignore[attr-defined]

        # Get top-k indices
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append((self._chunk_ids[idx], float(scores[idx])))

        return results

    def save(self, path: Path) -> None:
        """Save BM25 index to disk.

        Args:
            path: Directory to save index
        """
        path.mkdir(parents=True, exist_ok=True)

        # Save metadata
        metadata = {
            "chunk_ids": self._chunk_ids,
            "corpus": self._corpus,
        }
        with open(path / "bm25_metadata.json", "w") as f:
            json.dump(metadata, f)

        logger.debug("bm25_index_saved", path=str(path))

    def load(self, path: Path) -> None:
        """Load BM25 index from disk.

        Args:
            path: Directory containing saved index
        """
        try:
            from rank_bm25 import BM25Okapi
        except (
            ImportError
        ) as e:  # pragma: no cover - defensive code for missing dependency
            raise ImportError(
                "rank_bm25 package required. Install with: pip install rank-bm25"
            ) from e

        metadata_path = path / "bm25_metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"BM25 metadata not found: {metadata_path}")

        with open(metadata_path) as f:
            metadata = json.load(f)

        self._chunk_ids = metadata["chunk_ids"]
        self._corpus = metadata["corpus"]

        if self._corpus:
            self._index = BM25Okapi(self._corpus)
        else:
            self._index = None

        logger.debug("bm25_index_loaded", path=str(path), size=self.size)


class DenseIndex:
    """FAISS-based dense vector index."""

    def __init__(self, dimension: int = 768):
        """Initialize dense index.

        Args:
            dimension: Embedding dimension
        """
        self.dimension = dimension
        self._index = None
        self._chunk_ids: list[str] = []

    @property
    def is_built(self) -> bool:
        """Check if index is built."""
        return self._index is not None

    @property
    def size(self) -> int:
        """Get number of indexed vectors."""
        return len(self._chunk_ids)

    def build(self, chunk_ids: list[str], embeddings: np.ndarray) -> None:
        """Build FAISS index from embeddings.

        Args:
            chunk_ids: List of chunk IDs
            embeddings: numpy array of shape (n, dimension)
        """
        try:
            import faiss
        except (
            ImportError
        ) as e:  # pragma: no cover - defensive code for missing dependency
            raise ImportError(
                "faiss-cpu package required. Install with: pip install faiss-cpu"
            ) from e

        if len(chunk_ids) == 0:
            logger.warning("dense_build_empty_corpus")
            self._index = None
            self._chunk_ids = []
            return

        if embeddings.shape[0] != len(chunk_ids):
            n_ids, n_emb = len(chunk_ids), embeddings.shape[0]
            raise ValueError(f"Mismatch: {n_ids} chunk_ids, {n_emb} embeddings")

        self.dimension = embeddings.shape[1]
        self._chunk_ids = list(chunk_ids)

        # Create flat L2 index (exact search, suitable for <100K vectors)
        self._index = faiss.IndexFlatIP(self.dimension)

        # Normalize embeddings for cosine similarity via inner product
        faiss.normalize_L2(embeddings)
        self._index.add(embeddings.astype(np.float32))  # type: ignore[attr-defined]

        logger.info(
            "dense_index_built",
            document_count=len(chunk_ids),
            dimension=self.dimension,
        )

    def search(
        self, query_embedding: np.ndarray, top_k: int = 10
    ) -> list[tuple[str, float]]:
        """Search the FAISS index.

        Args:
            query_embedding: Query vector of shape (dimension,)
            top_k: Number of results to return

        Returns:
            List of (chunk_id, score) tuples sorted by score descending
        """
        try:
            import faiss
        except (
            ImportError
        ) as e:  # pragma: no cover - defensive code for missing dependency
            raise ImportError(
                "faiss-cpu package required. Install with: pip install faiss-cpu"
            ) from e

        if not self.is_built:
            return []

        # Reshape and normalize query
        query = query_embedding.reshape(1, -1).astype(np.float32)
        faiss.normalize_L2(query)

        # Search
        scores, indices = self._index.search(  # type: ignore[attr-defined]
            query, min(top_k, self.size)
        )

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0:  # -1 indicates no result
                results.append((self._chunk_ids[idx], float(score)))

        return results

    def save(self, path: Path) -> None:
        """Save FAISS index to disk.

        Args:
            path: Directory to save index
        """
        try:
            import faiss
        except (
            ImportError
        ) as e:  # pragma: no cover - defensive code for missing dependency
            raise ImportError(
                "faiss-cpu package required. Install with: pip install faiss-cpu"
            ) from e

        path.mkdir(parents=True, exist_ok=True)

        if self._index is not None:
            faiss.write_index(self._index, str(path / "faiss.index"))

        # Save metadata
        metadata = {
            "chunk_ids": self._chunk_ids,
            "dimension": self.dimension,
        }
        with open(path / "dense_metadata.json", "w") as f:
            json.dump(metadata, f)

        logger.debug("dense_index_saved", path=str(path))

    def load(self, path: Path) -> None:
        """Load FAISS index from disk.

        Args:
            path: Directory containing saved index
        """
        try:
            import faiss
        except (
            ImportError
        ) as e:  # pragma: no cover - defensive code for missing dependency
            raise ImportError(
                "faiss-cpu package required. Install with: pip install faiss-cpu"
            ) from e

        index_path = path / "faiss.index"
        metadata_path = path / "dense_metadata.json"

        if not metadata_path.exists():
            raise FileNotFoundError(f"Dense index metadata not found: {metadata_path}")

        with open(metadata_path) as f:
            metadata = json.load(f)

        self._chunk_ids = metadata["chunk_ids"]
        self.dimension = metadata["dimension"]

        if index_path.exists():
            self._index = faiss.read_index(str(index_path))
        else:
            self._index = None

        logger.debug("dense_index_loaded", path=str(path), size=self.size)


class HybridSearchEngine:
    """Hybrid search engine combining dense and sparse retrieval.

    Uses Reciprocal Rank Fusion (RRF) to combine results from:
    - FAISS dense vector search (semantic similarity)
    - BM25 sparse keyword search (lexical matching)
    """

    def __init__(
        self,
        corpus_config: Optional[CorpusConfig] = None,
        search_config: Optional[SearchConfig] = None,
    ):
        """Initialize hybrid search engine.

        Args:
            corpus_config: Corpus configuration
            search_config: Search configuration
        """
        self.corpus_config = corpus_config or CorpusConfig()
        self.search_config = search_config or SearchConfig()

        self._embedding_model: Optional[EmbeddingModel] = None
        self._dense_index = DenseIndex()
        self._bm25_index = BM25Index()
        self._chunks: dict[str, CorpusChunk] = {}

    @property
    def is_ready(self) -> bool:
        """Check if search engine is ready for queries."""
        return self._dense_index.is_built and self._bm25_index.is_built

    @property
    def corpus_size(self) -> int:
        """Get number of indexed chunks."""
        return len(self._chunks)

    def _get_embedding_model(self) -> EmbeddingModel:
        """Get or create embedding model (lazy initialization)."""
        if self._embedding_model is None:
            self._embedding_model = EmbeddingModel(
                model_name=self.corpus_config.embedding_model,
                model_path=self.corpus_config.embedding_model_path,
                batch_size=self.corpus_config.embedding_batch_size,
            )
        return self._embedding_model

    def index_chunks(self, chunks: list[CorpusChunk]) -> None:
        """Index a list of chunks for search.

        Args:
            chunks: List of corpus chunks to index
        """
        if not chunks:
            logger.warning("index_chunks_empty")
            return

        logger.info("indexing_chunks", count=len(chunks))

        # Store chunks for later retrieval
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

        # Build BM25 index
        self._bm25_index.build(chunks)

        # Build dense index
        embedding_model = self._get_embedding_model()
        texts = [c.content for c in chunks]
        embeddings = embedding_model.encode(texts)

        chunk_ids = [c.chunk_id for c in chunks]
        self._dense_index.build(chunk_ids, embeddings)

        logger.info(
            "chunks_indexed",
            total=len(chunks),
            dense_size=self._dense_index.size,
            bm25_size=self._bm25_index.size,
        )

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        section_filter: Optional[ChunkType] = None,
    ) -> list[SearchResult]:
        """Search the corpus with hybrid retrieval.

        Args:
            query: Search query
            top_k: Number of results (default from config)
            section_filter: Optional section type filter

        Returns:
            List of SearchResult objects sorted by relevance
        """
        if not self.is_ready:
            logger.warning("search_engine_not_ready")
            return []

        top_k = top_k or self.search_config.default_top_k
        top_k = min(top_k, self.search_config.max_top_k)

        # Get more candidates for filtering and fusion
        candidate_k = min(top_k * 3, self.corpus_size)

        # Dense search
        embedding_model = self._get_embedding_model()
        query_embedding = embedding_model.encode_single(query)
        dense_results = self._dense_index.search(query_embedding, candidate_k)

        # Sparse search
        sparse_results = self._bm25_index.search(query, candidate_k)

        # Reciprocal Rank Fusion
        fused_scores = self._reciprocal_rank_fusion(
            dense_results,
            sparse_results,
            dense_weight=self.search_config.dense_weight,
            sparse_weight=self.search_config.sparse_weight,
        )

        # Apply section filter if specified
        if section_filter:
            fused_scores = {
                cid: score
                for cid, score in fused_scores.items()
                if (chunk := self._chunks.get(cid)) is not None
                and chunk.section_type == section_filter
            }

        # Sort by score and take top_k
        sorted_results = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[
            :top_k
        ]

        # Convert to SearchResult objects
        search_results = []
        for chunk_id, score in sorted_results:
            chunk = self._chunks.get(chunk_id)
            if chunk:
                # Create snippet (first 1000 chars)
                snippet = chunk.content[:1000]

                search_results.append(
                    SearchResult(
                        chunk_id=chunk_id,
                        paper_id=chunk.paper_id,
                        paper_title=chunk.title,
                        section_type=chunk.section_type,
                        snippet=snippet,
                        relevance_score=min(score, 1.0),  # Clamp to [0, 1]
                    )
                )

        logger.debug(
            "search_completed",
            query=query[:50],
            results=len(search_results),
        )

        return search_results

    def _reciprocal_rank_fusion(
        self,
        dense_results: list[tuple[str, float]],
        sparse_results: list[tuple[str, float]],
        dense_weight: float = 0.7,
        sparse_weight: float = 0.3,
        k: int = 60,
    ) -> dict[str, float]:
        """Combine rankings using Reciprocal Rank Fusion.

        RRF score = sum(weight / (k + rank)) for each ranking

        Args:
            dense_results: Dense search results (chunk_id, score)
            sparse_results: Sparse search results (chunk_id, score)
            dense_weight: Weight for dense results
            sparse_weight: Weight for sparse results
            k: RRF constant (default 60)

        Returns:
            Dict mapping chunk_id to fused score
        """
        fused_scores: dict[str, float] = {}

        # Add dense scores
        for rank, (chunk_id, _) in enumerate(dense_results, start=1):
            rrf_score = dense_weight / (k + rank)
            fused_scores[chunk_id] = fused_scores.get(chunk_id, 0) + rrf_score

        # Add sparse scores
        for rank, (chunk_id, _) in enumerate(sparse_results, start=1):
            rrf_score = sparse_weight / (k + rank)
            fused_scores[chunk_id] = fused_scores.get(chunk_id, 0) + rrf_score

        return fused_scores

    def get_chunk(self, chunk_id: str) -> Optional[CorpusChunk]:
        """Get a chunk by ID.

        Args:
            chunk_id: Chunk identifier

        Returns:
            CorpusChunk if found, None otherwise
        """
        return self._chunks.get(chunk_id)

    def save(self, path: Optional[Path] = None) -> None:
        """Save search engine state to disk with atomic writes.

        SR-8.1: Uses atomic write pattern (write to temp -> rename) to ensure
        corpus integrity and prevent partial writes.

        Args:
            path: Directory to save state (default from config)
        """
        save_path = path or Path(self.corpus_config.corpus_dir)
        save_path.mkdir(parents=True, exist_ok=True)

        # SR-8.1: Restrict corpus directory permissions to 0700
        try:
            os.chmod(save_path, 0o700)
        except OSError as e:
            logger.warning("chmod_failed", path=str(save_path), error=str(e))

        # Save indices
        self._dense_index.save(save_path / "dense")
        self._bm25_index.save(save_path / "bm25")

        # Save chunks with atomic write
        chunks_data = {
            cid: {
                "chunk_id": c.chunk_id,
                "paper_id": c.paper_id,
                "section_type": c.section_type.value,
                "title": c.title,
                "content": c.content,
                "token_count": c.token_count,
                "checksum": c.checksum,
                "metadata": c.metadata,
            }
            for cid, c in self._chunks.items()
        }
        self._atomic_write_json(save_path / "chunks.json", chunks_data)

        logger.info("search_engine_saved", path=str(save_path))

    def _atomic_write_json(self, target_path: Path, data: dict) -> None:
        """Write JSON data atomically using temp file + rename.

        SR-8.1: Ensures corpus integrity by preventing partial writes.

        Args:
            target_path: Final destination path
            data: Dictionary to serialize as JSON
        """
        # Write to temp file in same directory (required for atomic rename)
        temp_fd, temp_path_str = tempfile.mkstemp(
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(temp_fd, "w") as f:
                json.dump(data, f)
            # Atomic rename (POSIX guarantees atomicity on same filesystem)
            Path(temp_path_str).rename(target_path)
        except Exception:
            # Clean up temp file on error
            try:
                Path(temp_path_str).unlink()
            except OSError:
                pass
            raise

    def load(self, path: Optional[Path] = None) -> None:
        """Load search engine state from disk.

        Args:
            path: Directory containing saved state (default from config)
        """
        load_path = path or Path(self.corpus_config.corpus_dir)

        if not load_path.exists():
            raise FileNotFoundError(f"Corpus directory not found: {load_path}")

        # Load chunks
        chunks_path = load_path / "chunks.json"
        if chunks_path.exists():
            with open(chunks_path) as f:
                chunks_data = json.load(f)

            self._chunks = {
                cid: CorpusChunk(
                    chunk_id=data["chunk_id"],
                    paper_id=data["paper_id"],
                    section_type=ChunkType(data["section_type"]),
                    title=data["title"],
                    content=data["content"],
                    token_count=data["token_count"],
                    checksum=data.get("checksum"),
                    metadata=data.get("metadata", {}),
                )
                for cid, data in chunks_data.items()
            }

        # Load indices
        dense_path = load_path / "dense"
        if dense_path.exists():
            self._dense_index.load(dense_path)

        bm25_path = load_path / "bm25"
        if bm25_path.exists():
            self._bm25_index.load(bm25_path)

        logger.info(
            "search_engine_loaded",
            path=str(load_path),
            chunks=len(self._chunks),
        )

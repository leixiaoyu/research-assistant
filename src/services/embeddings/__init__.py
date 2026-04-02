"""Embedding services for Phase 7.3 Human Feedback Loop.

This package provides services for computing paper embeddings
and similarity search using SPECTER2 or TF-IDF fallback.
"""

from src.services.embeddings.embedding_service import EmbeddingService
from src.services.embeddings.similarity_searcher import SimilaritySearcher

__all__ = ["EmbeddingService", "SimilaritySearcher"]

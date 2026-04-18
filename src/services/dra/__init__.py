"""Deep Research Agent (DRA) services package.

This package provides:
- Corpus management and ingestion
- Hybrid search (FAISS + BM25)
- Text utilities (chunking, tokenization, normalization)
"""

from src.services.dra.corpus_manager import CorpusManager, CorpusStats, PaperRecord
from src.services.dra.search_engine import (
    BM25Index,
    DenseIndex,
    EmbeddingModel,
    HybridSearchEngine,
)
from src.services.dra.utils import (
    ChunkBuilder,
    SectionParser,
    TextNormalizer,
    TokenCounter,
    compute_checksum,
    validate_chunk_integrity,
)
from src.services.dra.prompts import (
    BASE_SYSTEM_PROMPT,
    EXAMPLE_TURNS,
    SUMMARIZATION_PROMPT,
    TIP_GENERATION_PROMPT,
    build_system_prompt,
    build_user_prompt,
)

__all__ = [
    # Corpus management
    "CorpusManager",
    "CorpusStats",
    "PaperRecord",
    # Search engine
    "HybridSearchEngine",
    "DenseIndex",
    "BM25Index",
    "EmbeddingModel",
    # Utilities
    "ChunkBuilder",
    "SectionParser",
    "TextNormalizer",
    "TokenCounter",
    "compute_checksum",
    "validate_chunk_integrity",
]

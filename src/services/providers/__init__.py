"""Discovery providers for research paper retrieval.

Providers:
- ArxivProvider: ArXiv preprint server
- SemanticScholarProvider: Semantic Scholar API
- HuggingFaceProvider: HuggingFace Daily Papers
- OpenAlexProvider: OpenAlex open scholarly database (Phase 6)
- PaperSearchMCPProvider: Multi-source MCP aggregator (Phase 7.2)
"""

from src.services.providers.base import (
    DiscoveryProvider,
    APIError,
    RateLimitError,
    APIParameterError,
)
from src.services.providers.arxiv import ArxivProvider
from src.services.providers.semantic_scholar import SemanticScholarProvider
from src.services.providers.huggingface import HuggingFaceProvider
from src.services.providers.openalex import OpenAlexProvider
from src.services.providers.paper_search_mcp import PaperSearchMCPProvider

__all__ = [
    "DiscoveryProvider",
    "APIError",
    "RateLimitError",
    "APIParameterError",
    "ArxivProvider",
    "SemanticScholarProvider",
    "HuggingFaceProvider",
    "OpenAlexProvider",
    "PaperSearchMCPProvider",
]

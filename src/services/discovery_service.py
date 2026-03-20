"""Discovery service with multi-provider intelligence (Phase 3.2, 3.4 & 6).

BACKWARD COMPATIBILITY WRAPPER:
This module re-exports DiscoveryService from the modular discovery package.
All imports continue to work as before:

    from src.services.discovery_service import DiscoveryService

Internal implementation has been refactored into:
    src/services/discovery/
    ├── service.py         # Main orchestration
    ├── metrics.py         # Performance metrics
    ├── result_merger.py   # Result merging and deduplication
    └── __init__.py        # Public API

See src/services/discovery/README.md for details.
"""

# Re-export DiscoveryService for backward compatibility
from src.services.discovery import DiscoveryService

# Re-export dependencies that tests may patch
# (These are imported in the internal modules but need to be accessible
# at the old module path for existing test mocks to work)
from src.services.providers.arxiv import ArxivProvider
from src.services.providers.semantic_scholar import SemanticScholarProvider
from src.services.providers.huggingface import HuggingFaceProvider
from src.services.providers.openalex import OpenAlexProvider
import structlog

# Re-export logger for test patching
logger = structlog.get_logger()

__all__ = [
    "DiscoveryService",
    "ArxivProvider",
    "SemanticScholarProvider",
    "HuggingFaceProvider",
    "OpenAlexProvider",
    "logger",
]

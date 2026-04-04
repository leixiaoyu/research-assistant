"""Discovery service package with multi-provider intelligence.

This package provides modular discovery services with:
- Service orchestration (service.py)
- Performance metrics collection (metrics.py)
- Result merging and deduplication (result_merger.py)
- Relevance filtering (relevance_filter.py) - Phase 7 Fix I2

Public API:
    DiscoveryService: Main orchestration service (backward compatible)
    RelevanceFilter: Embedding-based relevance filtering
"""

from .service import DiscoveryService
from .relevance_filter import RelevanceFilter

__all__ = ["DiscoveryService", "RelevanceFilter"]

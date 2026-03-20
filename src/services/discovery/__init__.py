"""Discovery service package with multi-provider intelligence.

This package provides modular discovery services with:
- Service orchestration (service.py)
- Performance metrics collection (metrics.py)
- Result merging and deduplication (result_merger.py)

Public API:
    DiscoveryService: Main orchestration service (backward compatible)
"""

from .service import DiscoveryService

__all__ = ["DiscoveryService"]

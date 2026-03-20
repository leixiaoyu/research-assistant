"""Registry service package - modular paper identity and persistence management.

This package provides:
- RegistryService: Main orchestration API
- RegistryPersistence: Safe JSON file I/O with locking
- PaperRegistry: Core identity resolution and registration
- RegistryQueries: Search and filter operations

Public API:
- RegistryService (re-exported for backward compatibility)
"""

from .service import RegistryService

__all__ = ["RegistryService"]

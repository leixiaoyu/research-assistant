"""Registry Service - Backward compatibility shim.

This module maintains backward compatibility by re-exporting RegistryService
from the new modular registry package.

DEPRECATED: Import from src.services.registry instead.
"""

from src.services.registry import RegistryService

# Re-export models for backward compatibility
# (these were previously imported alongside RegistryService)
from src.models.registry import (
    RegistryEntry,
    RegistryState,
    IdentityMatch,
    ProcessingAction,
)

__all__ = [
    "RegistryService",
    "RegistryEntry",
    "RegistryState",
    "IdentityMatch",
    "ProcessingAction",
]

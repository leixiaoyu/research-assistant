"""CLI Module - Deprecation Stub.

This module is deprecated. Import from src.cli package instead.

DEPRECATED: This file will be removed in Phase 6.
Use 'from src.cli import app' instead.
"""

import warnings

# Emit deprecation warning on import
warnings.warn(
    "Importing from src.cli (file) is deprecated. "
    "Use 'from src.cli import app' (package) instead. "
    "This import path will be removed in Phase 6.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export everything from the new package for backward compatibility
from src.cli import (  # noqa: F401, E402
    app,
    run_command,
    validate_command,
    catalog_app,
    catalog_command,
    schedule_app,
    schedule_command,
    health_command,
    synthesize_command,
)

# Re-export legacy imports for backward compatibility
from src.services.discovery_service import APIError  # noqa: F401, E402
from src.models.catalog import CatalogRun  # noqa: F401, E402

__all__ = [
    "app",
    "run_command",
    "validate_command",
    "catalog_app",
    "catalog_command",
    "schedule_app",
    "schedule_command",
    "health_command",
    "synthesize_command",
    "APIError",
    "CatalogRun",
]

if __name__ == "__main__":
    app()

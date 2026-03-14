"""Pytest configuration for ARISP test suite.

This file provides shared fixtures and path configuration for all tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add scripts directory to path for validate_phase_specs imports
# This is done here rather than in individual test files per pytest best practices
scripts_path = Path(__file__).parent.parent / "scripts"
if str(scripts_path) not in sys.path:
    sys.path.insert(0, str(scripts_path))

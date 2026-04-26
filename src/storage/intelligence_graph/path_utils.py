"""Path sanitization helper for intelligence storage.

This module provides a thin wrapper over ``PathSanitizer`` for use by the
intelligence storage layer (SQLiteGraphStore, TimeSeriesStore,
MigrationManager). It enforces that database files live under approved
roots (``data/`` or ``cache/`` under the project root, or any system-supplied
temp directory).

Why a wrapper?
- ``PathSanitizer.safe_path`` requires both a ``base_dir`` and a relative
  ``user_input``. Storage constructors typically receive a single ``db_path``
  (which may be absolute or relative), so we adapt the API here.
- Tests frequently use ``tempfile.NamedTemporaryFile`` paths under the OS
  temp dir, which must also be allowed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import structlog

from src.utils.security import PathSanitizer, SecurityError

logger = structlog.get_logger()


def _project_root() -> Path:
    """Return the repository root (3 levels up from this file)."""
    # path_utils.py -> storage -> intelligence -> services -> src -> repo
    return Path(__file__).resolve().parents[4]


def _allowed_bases() -> list[Path]:
    """Return the directories under which storage DB files are permitted.

    Approved bases:
    - ``<project_root>/data`` and ``<project_root>/cache`` for production data
    - The system temp directory (resolved) for unit tests using
      ``tempfile.NamedTemporaryFile``
    """
    root = _project_root()
    bases = [
        root / "data",
        root / "cache",
        Path(tempfile.gettempdir()).resolve(),
    ]
    # Ensure data and cache exist so PathSanitizer can resolve them
    for b in bases[:2]:
        b.mkdir(parents=True, exist_ok=True)
    return bases


def sanitize_storage_path(db_path: Path | str) -> Path:
    """Validate ``db_path`` and return a resolved absolute Path.

    The path must lie within one of the approved bases (``data/``, ``cache/``,
    or the system temp directory). Directory traversal attempts (``..``) and
    paths outside the approved roots are rejected with ``SecurityError``.

    Args:
        db_path: Caller-supplied database path (absolute or relative).

    Returns:
        Resolved absolute Path safe for use by storage backends.

    Raises:
        SecurityError: If the path is not under any approved base.
    """
    candidate = Path(db_path)
    # Resolve without requiring existence (parent dir need not exist yet)
    resolved = (
        candidate if candidate.is_absolute() else (Path.cwd() / candidate).resolve()
    )
    if candidate.is_absolute():
        resolved = candidate.resolve()

    bases = [b.resolve() for b in _allowed_bases()]
    sanitizer = PathSanitizer(allowed_bases=bases)

    # Find which base contains the resolved path; safe_path will validate
    # traversal against that base.
    for base in bases:
        try:
            relative = resolved.relative_to(base)
        except ValueError:
            continue
        # safe_path enforces the no-traversal invariant
        return sanitizer.safe_path(base, str(relative), must_exist=False)

    logger.warning(
        "intelligence_storage_path_rejected",
        db_path=str(db_path),
        resolved=str(resolved),
    )
    raise SecurityError(f"Database path is outside approved storage roots: {db_path!r}")

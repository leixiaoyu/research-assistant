"""Tests for ``src.storage.intelligence_graph.path_utils``.

Regression coverage for the off-by-one bug where ``_project_root()``
walked one level too many parents (a residue from PR #105's
architectural relocation of this module from ``src/services/intelligence/storage/``
to ``src/storage/intelligence_graph/``). The original test suite passed
because it exclusively used ``tempfile.gettempdir()`` paths (also an
approved base), masking the production-only failure where ``data/`` and
``cache/`` were resolved against the wrong directory.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from src.storage.intelligence_graph.path_utils import (
    _allowed_bases,
    _project_root,
    sanitize_storage_path,
)
from src.utils.security import SecurityError

# ---------------------------------------------------------------------------
# Project root + allowed bases
# ---------------------------------------------------------------------------


def test_project_root_resolves_to_repo() -> None:
    """``_project_root`` must point at the actual repo, not its parent.

    Repo identity check: the directory must contain BOTH ``pyproject.toml``
    and ``verify.sh`` — markers that uniquely identify this repository.
    Catches off-by-one ancestor-walk bugs (which would land us in a parent
    directory that lacks both files).
    """
    root = _project_root()
    assert root.is_dir(), f"_project_root returned a non-directory: {root}"
    assert (root / "pyproject.toml").is_file(), (
        f"_project_root returned {root!r}, which lacks pyproject.toml — "
        f"likely an off-by-one ancestor walk in path_utils._project_root()"
    )
    assert (
        root / "verify.sh"
    ).is_file(), f"_project_root returned {root!r}, which lacks verify.sh"


def test_project_root_contains_src_storage_intelligence_graph() -> None:
    """``_project_root`` must locate the dir that contains this very module."""
    root = _project_root()
    expected_module = root / "src" / "storage" / "intelligence_graph" / "path_utils.py"
    assert expected_module.is_file(), (
        f"_project_root returned {root!r}, which does not contain the "
        f"path_utils.py module the function is defined in. Bug in "
        f"the parents[N] index."
    )


def test_allowed_bases_contains_data_and_cache_under_project_root() -> None:
    """``_allowed_bases`` must produce ``data/`` and ``cache/`` rooted at the
    actual project root (where they get created by setup.sh) — not at any
    sibling directory.
    """
    root = _project_root()
    bases = _allowed_bases()
    assert (root / "data").resolve() in [b.resolve() for b in bases]
    assert (root / "cache").resolve() in [b.resolve() for b in bases]


def test_allowed_bases_includes_system_temp_dir() -> None:
    """Tests rely on temp paths being approved; pin that contract."""
    bases = [b.resolve() for b in _allowed_bases()]
    assert Path(tempfile.gettempdir()).resolve() in bases


# ---------------------------------------------------------------------------
# sanitize_storage_path — regression for the production failure mode
# ---------------------------------------------------------------------------


def test_sanitize_storage_path_accepts_relative_data_path() -> None:
    """``data/<file>.db`` (relative) MUST resolve under the project's
    ``data/`` dir and pass sanitization.

    This is the exact code path the production CLI uses
    (``arisp monitor list`` → ``SubscriptionManager(_resolve_db_path())``
    → ``sanitize_storage_path(Path("data/monitoring.db"))``). Before the
    ``_project_root`` fix, this raised ``SecurityError: Database path is
    outside approved storage roots``, fully blocking Phase 9.1 monitoring
    in production.
    """
    # Run from the project root so ``Path.cwd() / "data/test.db"`` resolves
    # under <repo>/data/ — the production invariant the launcher relies on.
    import os

    original_cwd = os.getcwd()
    try:
        os.chdir(_project_root())
        result = sanitize_storage_path("data/regression_test.db")
        assert result.is_absolute()
        # Must be inside the repo's data/ dir
        assert _project_root() / "data" in result.parents
    finally:
        os.chdir(original_cwd)


def test_sanitize_storage_path_accepts_relative_cache_path() -> None:
    import os

    original_cwd = os.getcwd()
    try:
        os.chdir(_project_root())
        result = sanitize_storage_path("cache/regression_test.db")
        assert result.is_absolute()
        assert _project_root() / "cache" in result.parents
    finally:
        os.chdir(original_cwd)


def test_sanitize_storage_path_accepts_temp_path() -> None:
    """Temp paths (used by tests) remain approved post-fix."""
    temp_db = Path(tempfile.gettempdir()) / "regression_test.db"
    result = sanitize_storage_path(temp_db)
    assert result == temp_db.resolve()


def test_sanitize_storage_path_rejects_path_outside_approved_roots(
    tmp_path: Path,
) -> None:
    """A path under a non-approved directory (here: pytest's ``tmp_path``,
    which is *not* one of the approved bases — ``tempfile.gettempdir()`` is
    approved but ``tmp_path`` is a child of it on some systems and a sibling
    on others) must be rejected.

    Use a guaranteed-outside path instead: the user's home directory.
    """
    outside_path = Path.home() / ".never_an_approved_storage_root.db"
    with pytest.raises(SecurityError, match="outside approved storage roots"):
        sanitize_storage_path(outside_path)


def test_sanitize_storage_path_rejects_traversal_attempt() -> None:
    """``..`` segments must be rejected to prevent traversal."""
    with pytest.raises(SecurityError):
        sanitize_storage_path("data/../../../etc/passwd")


def test_sanitize_storage_path_rejects_absolute_etc_path() -> None:
    """Absolute paths outside approved bases must be rejected."""
    with pytest.raises(SecurityError, match="outside approved storage roots"):
        sanitize_storage_path("/etc/passwd")


# ---------------------------------------------------------------------------
# Belt + braces: compile-time safety net for the parents[N] index
# ---------------------------------------------------------------------------


def test_path_utils_module_is_three_levels_under_src() -> None:
    """If anyone moves ``path_utils.py`` again, this test reminds them to
    re-verify the ``parents[N]`` index in ``_project_root()``.

    The current location is ``src/storage/intelligence_graph/path_utils.py``
    — exactly 3 levels deep from the repo root. ``_project_root`` uses
    ``parents[3]`` to compensate. Any move to a different depth requires
    updating that index.
    """
    from src.storage.intelligence_graph import path_utils

    module_file = Path(path_utils.__file__).resolve()
    # parents[3] = repo root, so module_file's relative path from repo root
    # should have exactly 4 parts: src / storage / intelligence_graph / path_utils.py
    repo_root = _project_root()
    relative = module_file.relative_to(repo_root)
    assert len(relative.parts) == 4, (
        f"path_utils.py is at {relative} ({len(relative.parts)} parts) — "
        f"if this changed, _project_root()'s parents[3] index needs to "
        f"change to match the new depth."
    )
    assert relative.parts == (
        "src",
        "storage",
        "intelligence_graph",
        "path_utils.py",
    )


# ---------------------------------------------------------------------------
# Defensive: ensure module is importable from a clean sys.path
# ---------------------------------------------------------------------------


def test_module_importable() -> None:
    """Smoke test that the module loads cleanly (catches syntax regressions)."""
    assert "src.storage.intelligence_graph.path_utils" in sys.modules

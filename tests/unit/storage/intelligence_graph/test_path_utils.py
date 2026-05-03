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

import tempfile
from pathlib import Path

import pytest
import structlog
import structlog.testing

from src.storage.intelligence_graph import path_utils as path_utils_module
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


def test_sanitize_storage_path_accepts_relative_data_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``data/<file>.db`` (relative) MUST resolve under the project's
    ``data/`` dir and pass sanitization.

    This is the exact code path the production CLI uses
    (``arisp monitor list`` → ``SubscriptionManager(_resolve_db_path())``
    → ``sanitize_storage_path(Path("data/monitoring.db"))``). Before the
    ``_project_root`` fix, this raised ``SecurityError: Database path is
    outside approved storage roots``, fully blocking Phase 9.1 monitoring
    in production.
    """
    # ``monkeypatch.chdir`` auto-restores cwd even on hard failures and is
    # safe under pytest-xdist (each worker has its own process).
    monkeypatch.chdir(_project_root())
    result = sanitize_storage_path("data/regression_test.db")
    assert result.is_absolute()
    # Must be inside the repo's data/ dir
    assert _project_root() / "data" in result.parents


def test_sanitize_storage_path_accepts_relative_cache_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same regression guard as the data/ path test, for ``cache/``."""
    monkeypatch.chdir(_project_root())
    result = sanitize_storage_path("cache/regression_test.db")
    assert result.is_absolute()
    assert _project_root() / "cache" in result.parents


def test_sanitize_storage_path_accepts_temp_path() -> None:
    """Temp paths (used by tests) remain approved post-fix."""
    temp_db = Path(tempfile.gettempdir()) / "regression_test.db"
    result = sanitize_storage_path(temp_db)
    assert result == temp_db.resolve()


def test_sanitize_storage_path_rejects_path_outside_approved_roots() -> None:
    """A path that is provably outside every approved base must be rejected.

    Use the *parent* of the project root — invariant across all hosts (a
    container with ``$HOME=/tmp`` would otherwise make ``Path.home()``
    resolve under tempdir and accidentally pass sanitization).
    """
    outside_path = (
        _project_root().parent / "definitely_not_approved_storage_root" / "x.db"
    )
    with pytest.raises(SecurityError, match="outside approved storage roots"):
        sanitize_storage_path(outside_path)


def test_sanitize_storage_path_rejects_relative_traversal_to_outside_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``..``-laden relative path that resolves outside any approved base
    must be rejected via the *outside-roots* branch.

    NOTE: ``sanitize_storage_path`` resolves the candidate before checking,
    so the literal ``..`` segments are collapsed by ``Path.resolve()``. The
    rejection therefore fires from the outer "outside approved roots" loop,
    NOT from ``PathSanitizer.safe_path``'s internal traversal check (which
    is unreachable via this entry point — the resolved path never carries
    ``..`` segments).
    """
    monkeypatch.chdir(_project_root())
    with pytest.raises(SecurityError, match="outside approved storage roots"):
        sanitize_storage_path("data/../../../etc/passwd")


def test_sanitize_storage_path_rejects_absolute_etc_path() -> None:
    """Absolute paths outside approved bases must be rejected."""
    with pytest.raises(SecurityError, match="outside approved storage roots"):
        sanitize_storage_path("/etc/passwd")


def test_sanitize_storage_path_emits_structured_log_on_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rejection path emits ``intelligence_storage_path_rejected`` —
    the structured event ops grep for when investigating CLI failures.
    Verifies the observable contract of the security boundary.

    ``cache_logger_on_first_use=True`` (in ``src/utils/logging.py``)
    freezes the bound logger at first call, so we rebind the module-level
    ``logger`` to a fresh proxy before entering ``capture_logs()`` — same
    pattern as ``tests/unit/test_scheduling/test_monitoring_check_job.py``.
    """
    monkeypatch.setattr(path_utils_module, "logger", structlog.get_logger())

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(SecurityError):
            sanitize_storage_path("/etc/passwd")

    rejection_events = [
        e for e in logs if e.get("event") == "intelligence_storage_path_rejected"
    ]
    assert len(rejection_events) == 1
    # Bound fields the production code emits (db_path + resolved) — pin
    # them so a future refactor that drops one trips the test.
    event = rejection_events[0]
    assert "db_path" in event
    assert "resolved" in event


# ---------------------------------------------------------------------------
# Belt + braces: compile-time safety net for the parents[N] index
# ---------------------------------------------------------------------------


def test_project_root_index_matches_module_depth() -> None:
    """If anyone moves ``path_utils.py`` to a different depth, this test
    fires *before* ``_project_root()`` silently returns the wrong directory.

    The current location is ``src/storage/intelligence_graph/path_utils.py``
    — exactly 4 path parts (``src/storage/intelligence_graph/path_utils.py``)
    relative to the repo root. ``_project_root()`` uses ``parents[3]`` to
    compensate. Any move to a different depth requires updating that index.

    Wraps ``relative_to`` in an explicit failure path: if ``_project_root()``
    is itself wrong, ``relative_to`` raises ``ValueError``, which we convert
    to ``pytest.fail`` with a self-diagnostic message — otherwise the user
    sees an opaque ``"... is not in the subpath of ..."`` traceback.
    """
    module_file = Path(path_utils_module.__file__).resolve()
    repo_root = _project_root()
    try:
        relative = module_file.relative_to(repo_root)
    except ValueError:
        pytest.fail(
            f"_project_root() returned {repo_root!r}, which is not an "
            f"ancestor of {module_file!r}. Likely an off-by-one parents[N] "
            f"index in path_utils._project_root()."
        )
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

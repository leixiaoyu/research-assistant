"""Shared SQLite connection helper for the intelligence-graph layer.

Why this exists
---------------
Three call sites in the intelligence-graph layer (``MigrationManager``,
``SQLiteGraphStore``, ``TimeSeriesStore``) — and now the monitoring
layer (``SubscriptionManager``, ``MonitoringRunRepository``) — each
hand-roll the same four PRAGMAs every time they open a connection:

- ``foreign_keys=ON`` (referential integrity, including ``ON DELETE CASCADE``)
- ``journal_mode=WAL`` (writers don't block readers)
- ``synchronous=NORMAL`` (durability vs. throughput trade-off)
- ``busy_timeout=5000`` (wait up to 5s for locks before failing)

The duplication is small but meaningful: changing any one PRAGMA (e.g.
flipping to ``synchronous=FULL`` for a high-stakes operation) requires
finding and updating every call site. This helper provides one source
of truth.

Why a context manager
---------------------
SQLite's ``Connection.__exit__`` commits / rolls back but **does not
close** the connection. Under a long-running scheduler that opens a
fresh connection per logical operation, that leaks one file descriptor
per call. The helper wraps the connection in a ``contextmanager`` with
an explicit ``finally: conn.close()`` so callers can write::

    with open_connection(db_path) as conn:
        conn.execute(...)

without thinking about it.

Scope (Phase 9.1)
-----------------
This helper is wired into:

- ``SubscriptionManager._connect`` (monitoring CRUD)
- ``MonitoringRunRepository._connect`` (run audit storage)

The three intelligence-graph stores (``unified_graph.py``,
``time_series.py``, ``migrations.py``) keep their existing
``_get_connection()`` helpers for now. Those code paths use slightly
different patterns (manual ``try/finally``, multiple commits per
operation, etc.) that need a separate refactor pass tracked under
``# TODO(phase-10): consolidate onto open_connection``.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def open_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection with the standard intelligence-graph PRAGMAs.

    Sets:

    - ``foreign_keys=ON`` so ``FOREIGN KEY ... ON DELETE CASCADE`` and
      other referential constraints are enforced.
    - ``journal_mode=WAL`` so concurrent readers don't block writers.
    - ``synchronous=NORMAL`` for the WAL mode's preferred durability /
      throughput balance.
    - ``busy_timeout=5000`` so a contended lock waits up to 5 seconds
      before raising ``OperationalError("database is locked")``.

    Also sets ``conn.row_factory = sqlite3.Row`` so callers can read
    columns by name (``row["subscription_id"]``) instead of position.

    The connection is **always closed** on exit, even on exception.
    SQLite's own ``Connection.__exit__`` only commits / rolls back —
    leaving file descriptors open under a long-running scheduler is the
    bug this wrapper fixes.

    Args:
        db_path: Path to the SQLite database file. The caller is
            responsible for path sanitization (this helper does not
            re-validate; intelligence-graph callers go through
            :func:`sanitize_storage_path` at construction time).

    Yields:
        A ready-to-use ``sqlite3.Connection``.

    Raises:
        sqlite3.OperationalError: If ``db_path`` is unusable (e.g.
            parent directory does not exist, permission denied).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()

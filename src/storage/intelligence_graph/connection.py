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
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")

# SQLite extended result codes for the lock contention family. Python
# 3.11+ exposes ``OperationalError.sqlite_errorcode`` so we can
# distinguish lock contention from semantically-distinct
# ``OperationalError`` cases (disk full, schema drift, ...) without
# grepping the message. The numeric values mirror sqlite3.h:
#
#   SQLITE_BUSY   = 5  (another process holds an incompatible lock)
#   SQLITE_LOCKED = 6  (a table in the same connection is locked)
#
# Substring fallback covers older sqlite builds whose binding does not
# populate ``sqlite_errorcode`` (PR #123 review #S1).
_SQLITE_BUSY = 5
_SQLITE_LOCKED = 6
_RETRYABLE_SQLITE_CODES = frozenset({_SQLITE_BUSY, _SQLITE_LOCKED})


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


def retry_on_lock_contention(
    operation: Callable[[], T],
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 0.05,
    operation_name: str = "sqlite_operation",
) -> T:
    """Retry a SQLite operation on lock contention (BUSY/LOCKED).

    Uses ``sqlite3.OperationalError.sqlite_errorcode`` introspection
    (codes 5 = SQLITE_BUSY, 6 = SQLITE_LOCKED) with substring fallback
    for older SQLite versions whose binding does not populate the
    ``sqlite_errorcode`` attribute. Sleeps ``backoff_seconds * attempt``
    between retries (linear, not exponential -- contention is
    short-lived). Re-raises immediately on any non-contention error or
    after ``max_attempts`` is exhausted.

    The helper is the canonical way to wrap any ``BEGIN IMMEDIATE``
    write in the intelligence-graph and monitoring layers. WAL +
    ``busy_timeout`` already buys 5s on the connection level; the
    application-level retries here are an additional safety margin so
    a colliding writer does not silently drop a critical row.

    Async callers MUST wrap this call in ``asyncio.to_thread(...)`` --
    the retry loop uses ``time.sleep`` which would block the event loop
    for the full backoff budget on every contended write. (See
    ``MonitoringRunner._run_one`` for the canonical async wrapping.)

    Args:
        operation: Zero-arg callable that performs the SQLite write.
            Wrap your statement(s) in a lambda or function so the helper
            can re-invoke them per attempt.
        max_attempts: Total attempts including the initial call. Must
            be >= 1.
        backoff_seconds: Base sleep interval between attempts. Linear
            backoff (attempt * base) is used.
        operation_name: Used in log events for traceability so a single
            log stream can distinguish e.g. ``monitoring_record_run``
            from ``influence_write_cache`` contention.

    Returns:
        Whatever ``operation()`` returns on the first successful
        attempt.

    Raises:
        sqlite3.OperationalError: After ``max_attempts`` on lock
            contention, OR on the first attempt for any non-contention
            ``OperationalError`` (disk full, schema drift, syntax
            error, ...).
    """
    attempt = 0
    while True:
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            # Prefer ``sqlite_errorcode`` (Python 3.11+, set by the C
            # binding) to message substring matching: it is
            # locale-independent, immune to upstream wording changes,
            # and covers both SQLITE_BUSY and SQLITE_LOCKED variants.
            # Fall back to the substring check when the code is
            # unavailable (older bindings, synthesized exceptions in
            # tests). Match both "locked" and "busy" wording SQLite has
            # used historically. (PR #123 review #S1.)
            sqlite_code = getattr(exc, "sqlite_errorcode", None)
            if sqlite_code is not None:
                is_lock_error = sqlite_code in _RETRYABLE_SQLITE_CODES
            else:
                msg = str(exc).lower()
                is_lock_error = "locked" in msg or "busy" in msg
            is_last_attempt = attempt >= max_attempts - 1
            if not is_lock_error:
                # Non-contention OperationalError -- propagate
                # immediately so the caller sees the real bug.
                raise
            if is_last_attempt:
                # Contention persisted past the retry budget. Emit a
                # structured error event so ops can grep for
                # audit-trail gaps (matches the orchestration pattern
                # of "audit-write the failure paths too").
                logger.error(
                    "sqlite_lock_contention_exhausted",
                    operation_name=operation_name,
                    attempts=max_attempts,
                    error=str(exc),
                )
                raise
            backoff = backoff_seconds * (attempt + 1)
            logger.warning(
                "sqlite_lock_contention_retry",
                operation_name=operation_name,
                attempt=attempt + 1,
                max_attempts=max_attempts,
                backoff_seconds=backoff,
                error=str(exc),
            )
            time.sleep(backoff)
            attempt += 1

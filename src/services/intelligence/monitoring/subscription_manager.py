"""Subscription CRUD over the existing intelligence-graph SQLite store.

The ``subscriptions`` table is created by the Week 0 migration
(``src/storage/intelligence_graph/migrations.py:MIGRATION_V1_INITIAL``).
Schema:

    subscription_id TEXT PRIMARY KEY
    user_id         TEXT NOT NULL DEFAULT 'default'
    name            TEXT NOT NULL
    config          TEXT NOT NULL  -- JSON-encoded ResearchSubscription
    last_checked    TEXT
    is_active       INTEGER NOT NULL DEFAULT 1
    created_at      TEXT NOT NULL
    updated_at      TEXT NOT NULL

The model fields beyond what's column-promoted (query, keywords,
sources, etc.) live inside the ``config`` JSON blob — same pattern the
graph store uses for ``properties``.

Concurrency model
-----------------
``_connect()`` is a context manager that opens a fresh
``sqlite3.Connection`` per logical operation, applies the standard
intelligence-graph PRAGMAs (``foreign_keys=ON``, ``journal_mode=WAL``,
``synchronous=NORMAL``, ``busy_timeout=5000``), and **closes the
connection on exit** (sqlite3's own ``__exit__`` only commits/rolls
back — it does not close, which leaks file descriptors under a
long-running scheduler).

Mutations that combine a read with a write (most notably
``add_subscription``, which checks the per-user cap before INSERT)
issue ``BEGIN IMMEDIATE`` at the start of the transaction so the
read+write pair is serialized against concurrent writers. Without
this, two concurrent ``add_subscription`` calls could both observe
``count==MAX-1`` and both insert, breaking the cap. ``BEGIN IMMEDIATE``
acquires the SQLite write lock up-front; the second writer blocks for
up to ``busy_timeout`` and then either succeeds or raises
``OperationalError("database is locked")`` (which our retry policy
upstream is responsible for translating into a user-visible error).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import structlog

from src.services.intelligence.models.monitoring import SubscriptionLimitError
from src.services.intelligence.monitoring.models import (
    MAX_KEYWORDS_PER_SUBSCRIPTION,
    ResearchSubscription,
    SubscriptionStatus,
)
from src.storage.intelligence_graph.connection import open_connection
from src.storage.intelligence_graph.migrations import MigrationManager
from src.storage.intelligence_graph.path_utils import sanitize_storage_path

logger = structlog.get_logger()


class SubscriptionManager:
    """CRUD facade for ``ResearchSubscription`` records.

    Limits enforced (open-questions.md, 2026-04-24):

    - Max ``MAX_SUBSCRIPTIONS_PER_USER`` subscriptions per ``user_id``
    - Max ``MAX_KEYWORDS_PER_SUBSCRIPTION`` keywords per subscription
      (also enforced inside ``ResearchSubscription``)

    Both limits raise :class:`SubscriptionLimitError` *before* writing.
    """

    MAX_SUBSCRIPTIONS_PER_USER = 50
    MAX_KEYWORDS_PER_SUBSCRIPTION = MAX_KEYWORDS_PER_SUBSCRIPTION

    def __init__(self, db_path: Path | str):
        """Initialize the manager.

        Args:
            db_path: SQLite database path. Must lie under one of the
                approved storage roots (``data/``, ``cache/``, or the
                system temp directory) — enforced by
                :func:`sanitize_storage_path`.
        """
        self.db_path = sanitize_storage_path(db_path)
        self._migrations = MigrationManager(self.db_path)
        self._initialized = False

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------
    def initialize(self) -> None:
        """Apply pending schema migrations.

        Idempotent — safe to call multiple times. Must be called before
        any CRUD operation.
        """
        applied = self._migrations.migrate()
        if applied > 0:
            logger.info(
                "subscription_manager_migrations_applied",
                count=applied,
                db_path=str(self.db_path),
            )
        self._initialized = True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open + auto-close a SQLite connection with the standard PRAGMAs.

        Delegates to :func:`open_connection` so the PRAGMA set is
        defined exactly once across the intelligence-graph layer. The
        ``BEGIN IMMEDIATE`` write-lock acquisition used by
        :meth:`add_subscription` stays at the call site — that is
        operation-level (not connection-level) behavior.
        """
        if not self._initialized:
            raise RuntimeError(
                "SubscriptionManager not initialized. Call initialize() first."
            )
        with open_connection(self.db_path) as conn:
            yield conn

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    @staticmethod
    def _serialize(sub: ResearchSubscription) -> str:
        """Serialize the non-column fields into the ``config`` blob."""
        payload = sub.model_dump(mode="json")
        # Drop fields that are persisted as columns to avoid duplication
        # and accidental skew between row and blob.
        for col in (
            "subscription_id",
            "user_id",
            "name",
            "status",
            "last_checked_at",
            "created_at",
            "updated_at",
        ):
            payload.pop(col, None)
        return json.dumps(payload, default=str, sort_keys=True)

    @staticmethod
    def _deserialize(row: sqlite3.Row) -> ResearchSubscription:
        config = json.loads(row["config"])
        # Re-stitch the column-promoted fields back into the dict so we
        # round-trip via the model validator.
        is_active = bool(row["is_active"])
        last_checked = row["last_checked"]
        return ResearchSubscription(
            subscription_id=row["subscription_id"],
            user_id=row["user_id"],
            name=row["name"],
            status=(
                SubscriptionStatus.ACTIVE if is_active else SubscriptionStatus.PAUSED
            ),
            last_checked_at=(
                datetime.fromisoformat(last_checked) if last_checked else None
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            **config,
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def add_subscription(self, subscription: ResearchSubscription) -> str:
        """Persist a new subscription.

        Returns:
            The ``subscription_id``.

        Raises:
            SubscriptionLimitError: If the user is at the per-user cap or
                the subscription has too many keywords.
            ValueError: If a subscription with the same id already
                exists.
        """
        # Defensive double-check on keywords. The model validator already
        # enforces this, but we keep the explicit guard so failures
        # before INSERT are uniform with the per-user cap below.
        if len(subscription.keywords) > self.MAX_KEYWORDS_PER_SUBSCRIPTION:
            raise SubscriptionLimitError(
                "keywords per subscription",
                len(subscription.keywords),
                self.MAX_KEYWORDS_PER_SUBSCRIPTION,
            )

        with self._connect() as conn:
            # Acquire write lock UP FRONT so the count check + INSERT
            # are atomic against concurrent writers. Without this, two
            # callers can both observe count==MAX-1 and both insert,
            # silently breaking the per-user cap.
            # TODO(#134): wrap in retry_on_lock_contention
            conn.execute("BEGIN IMMEDIATE")
            current = self._count_user_subscriptions(conn, subscription.user_id)
            if current >= self.MAX_SUBSCRIPTIONS_PER_USER:
                raise SubscriptionLimitError(
                    "subscriptions per user",
                    current,
                    self.MAX_SUBSCRIPTIONS_PER_USER,
                )

            cursor = conn.execute(
                "SELECT 1 FROM subscriptions WHERE subscription_id = ?",
                (subscription.subscription_id,),
            )
            if cursor.fetchone() is not None:
                raise ValueError(
                    f"Subscription already exists: {subscription.subscription_id!r}"
                )

            now = datetime.now(timezone.utc)
            # Honor caller-provided timestamps if they were set
            # explicitly; otherwise stamp ``now`` on both.
            created_at = subscription.created_at or now
            updated_at = now
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, config,
                    last_checked, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription.subscription_id,
                    subscription.user_id,
                    subscription.name,
                    self._serialize(subscription),
                    (
                        subscription.last_checked_at.isoformat()
                        if subscription.last_checked_at
                        else None
                    ),
                    1 if subscription.status is SubscriptionStatus.ACTIVE else 0,
                    created_at.isoformat(),
                    updated_at.isoformat(),
                ),
            )
            conn.commit()

        logger.info(
            "subscription_added",
            subscription_id=subscription.subscription_id,
            user_id=subscription.user_id,
            name=subscription.name,
        )
        return subscription.subscription_id

    def get_subscription(self, subscription_id: str) -> Optional[ResearchSubscription]:
        """Fetch one subscription, or ``None`` if not found."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT subscription_id, user_id, name, config,
                       last_checked, is_active, created_at, updated_at
                FROM subscriptions WHERE subscription_id = ?
                """,
                (subscription_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._deserialize(row)

    def list_subscriptions(
        self,
        user_id: Optional[str] = None,
        active_only: bool = False,
    ) -> list[ResearchSubscription]:
        """List subscriptions, optionally filtered by user/active flag."""
        clauses: list[str] = []
        params: list[object] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if active_only:
            clauses.append("is_active = 1")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                SELECT subscription_id, user_id, name, config,
                       last_checked, is_active, created_at, updated_at
                FROM subscriptions
                {where}
                ORDER BY created_at ASC
                """,
                tuple(params),
            )
            return [self._deserialize(r) for r in cursor.fetchall()]

    def update_subscription(self, subscription: ResearchSubscription) -> None:
        """Replace an existing subscription's mutable fields.

        Raises:
            KeyError: If no row matches ``subscription.subscription_id``.
            SubscriptionLimitError: If keyword count exceeds the cap.
        """
        if len(subscription.keywords) > self.MAX_KEYWORDS_PER_SUBSCRIPTION:
            raise SubscriptionLimitError(
                "keywords per subscription",
                len(subscription.keywords),
                self.MAX_KEYWORDS_PER_SUBSCRIPTION,
            )
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE subscriptions SET
                    name = ?, config = ?, last_checked = ?,
                    is_active = ?, updated_at = ?
                WHERE subscription_id = ?
                """,
                (
                    subscription.name,
                    self._serialize(subscription),
                    (
                        subscription.last_checked_at.isoformat()
                        if subscription.last_checked_at
                        else None
                    ),
                    1 if subscription.status is SubscriptionStatus.ACTIVE else 0,
                    now.isoformat(),
                    subscription.subscription_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(
                    f"Subscription not found: {subscription.subscription_id!r}"
                )
            conn.commit()
        logger.info(
            "subscription_updated", subscription_id=subscription.subscription_id
        )

    def delete_subscription(self, subscription_id: str) -> bool:
        """Delete one subscription. Returns True if a row was removed."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM subscriptions WHERE subscription_id = ?",
                (subscription_id,),
            )
            removed = cursor.rowcount > 0
            conn.commit()
        if removed:
            logger.info("subscription_deleted", subscription_id=subscription_id)
        return removed

    def set_status(self, subscription_id: str, status: SubscriptionStatus) -> None:
        """Pause or resume a subscription without rewriting its config.

        Raises:
            KeyError: If no row matches ``subscription_id``.
        """
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE subscriptions
                SET is_active = ?, updated_at = ?
                WHERE subscription_id = ?
                """,
                (
                    1 if status is SubscriptionStatus.ACTIVE else 0,
                    now.isoformat(),
                    subscription_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Subscription not found: {subscription_id!r}")
            conn.commit()
        logger.info(
            "subscription_status_changed",
            subscription_id=subscription_id,
            status=status.value,
        )

    def mark_checked(
        self, subscription_id: str, when: Optional[datetime] = None
    ) -> None:
        """Record a successful monitoring cycle's timestamp.

        ``when`` defaults to "now" in UTC. Tests pass an explicit
        timestamp so cycle behavior is deterministic.

        Raises:
            KeyError: If no row matches ``subscription_id``.
        """
        timestamp = when or datetime.now(timezone.utc)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE subscriptions
                SET last_checked = ?, updated_at = ?
                WHERE subscription_id = ?
                """,
                (
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                    subscription_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Subscription not found: {subscription_id!r}")
            conn.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _count_user_subscriptions(conn: sqlite3.Connection, user_id: str) -> int:
        cursor = conn.execute(
            "SELECT COUNT(*) AS c FROM subscriptions WHERE user_id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        return int(row["c"]) if row else 0

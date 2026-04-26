"""Tests for ``SubscriptionManager`` (Milestone 9.1).

Covers:
- CRUD happy paths (add, get, list, update, delete, set_status, mark_checked)
- Limit enforcement (per-user cap and per-subscription keyword cap)
- ``KeyError`` on missing rows for update/set_status/mark_checked
- ``ValueError`` on duplicate ``subscription_id`` insert
- ``RuntimeError`` when methods are called before ``initialize``
- Filtering by ``user_id`` and active flag in ``list_subscriptions``
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.services.intelligence.models.monitoring import (
    PaperSource,
    SubscriptionLimitError,
)
from src.services.intelligence.monitoring.models import (
    MAX_KEYWORDS_PER_SUBSCRIPTION,
    ResearchSubscription,
    SubscriptionStatus,
)
from src.services.intelligence.monitoring.subscription_manager import (
    SubscriptionManager,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path() -> Path:
    """Return a unique sqlite db path under the system temp dir."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    # Remove the empty file so MigrationManager creates it fresh.
    path.unlink(missing_ok=True)
    return path


@pytest.fixture
def manager(db_path: Path) -> SubscriptionManager:
    mgr = SubscriptionManager(db_path)
    mgr.initialize()
    return mgr


def _make_subscription(
    *,
    subscription_id: str = "sub-test001",
    user_id: str = "alice",
    name: str = "Test Sub",
    query: str = "tree of thoughts",
    keywords: list[str] | None = None,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> ResearchSubscription:
    return ResearchSubscription(
        subscription_id=subscription_id,
        user_id=user_id,
        name=name,
        query=query,
        keywords=keywords or [],
        status=status,
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialize:
    def test_initialize_applies_migrations(self, db_path: Path) -> None:
        mgr = SubscriptionManager(db_path)
        mgr.initialize()
        # After init, the subscriptions table exists and is queryable.
        with sqlite3.connect(str(db_path)) as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='subscriptions'"
            )
            assert cur.fetchone() is not None

    def test_initialize_idempotent(self, db_path: Path) -> None:
        mgr = SubscriptionManager(db_path)
        mgr.initialize()
        # Second call is a no-op; should not raise.
        mgr.initialize()
        assert mgr._initialized is True

    def test_method_before_initialize_raises(self, db_path: Path) -> None:
        mgr = SubscriptionManager(db_path)
        with pytest.raises(RuntimeError, match="not initialized"):
            mgr.add_subscription(_make_subscription())


# ---------------------------------------------------------------------------
# CRUD happy paths
# ---------------------------------------------------------------------------


class TestAdd:
    def test_add_returns_subscription_id(self, manager: SubscriptionManager) -> None:
        sub = _make_subscription()
        result = manager.add_subscription(sub)
        assert result == "sub-test001"

    def test_add_persists_all_fields(self, manager: SubscriptionManager) -> None:
        sub = _make_subscription(
            keywords=["lora", "qlora"], status=SubscriptionStatus.PAUSED
        )
        manager.add_subscription(sub)
        fetched = manager.get_subscription("sub-test001")
        assert fetched is not None
        assert fetched.subscription_id == sub.subscription_id
        assert fetched.user_id == sub.user_id
        assert fetched.name == sub.name
        assert fetched.query == sub.query
        assert fetched.keywords == sub.keywords
        assert fetched.status == SubscriptionStatus.PAUSED
        assert fetched.sources == [PaperSource.ARXIV]

    def test_add_with_last_checked_at_persists(
        self, manager: SubscriptionManager
    ) -> None:
        when = datetime(2024, 1, 1, tzinfo=timezone.utc)
        sub = ResearchSubscription(
            subscription_id="sub-lc",
            name="n",
            query="q",
            last_checked_at=when,
        )
        manager.add_subscription(sub)
        fetched = manager.get_subscription("sub-lc")
        assert fetched is not None
        assert fetched.last_checked_at == when

    def test_add_duplicate_id_raises_value_error(
        self, manager: SubscriptionManager
    ) -> None:
        sub = _make_subscription()
        manager.add_subscription(sub)
        with pytest.raises(ValueError, match="already exists"):
            manager.add_subscription(sub)


class TestGet:
    def test_get_returns_none_for_missing(self, manager: SubscriptionManager) -> None:
        assert manager.get_subscription("sub-missing") is None

    def test_get_returns_existing(self, manager: SubscriptionManager) -> None:
        sub = _make_subscription()
        manager.add_subscription(sub)
        fetched = manager.get_subscription(sub.subscription_id)
        assert fetched is not None
        assert fetched.subscription_id == sub.subscription_id


class TestList:
    def test_list_empty(self, manager: SubscriptionManager) -> None:
        assert manager.list_subscriptions() == []

    def test_list_all(self, manager: SubscriptionManager) -> None:
        manager.add_subscription(_make_subscription(subscription_id="sub-a"))
        manager.add_subscription(_make_subscription(subscription_id="sub-b"))
        all_subs = manager.list_subscriptions()
        assert {s.subscription_id for s in all_subs} == {"sub-a", "sub-b"}

    def test_list_filter_by_user(self, manager: SubscriptionManager) -> None:
        manager.add_subscription(
            _make_subscription(subscription_id="sub-a", user_id="alice")
        )
        manager.add_subscription(
            _make_subscription(subscription_id="sub-b", user_id="bob")
        )
        alice = manager.list_subscriptions(user_id="alice")
        assert [s.subscription_id for s in alice] == ["sub-a"]

    def test_list_active_only(self, manager: SubscriptionManager) -> None:
        manager.add_subscription(
            _make_subscription(
                subscription_id="sub-a", status=SubscriptionStatus.ACTIVE
            )
        )
        manager.add_subscription(
            _make_subscription(
                subscription_id="sub-b", status=SubscriptionStatus.PAUSED
            )
        )
        actives = manager.list_subscriptions(active_only=True)
        assert [s.subscription_id for s in actives] == ["sub-a"]

    def test_list_combined_filters(self, manager: SubscriptionManager) -> None:
        manager.add_subscription(
            _make_subscription(
                subscription_id="sub-a",
                user_id="alice",
                status=SubscriptionStatus.ACTIVE,
            )
        )
        manager.add_subscription(
            _make_subscription(
                subscription_id="sub-b",
                user_id="alice",
                status=SubscriptionStatus.PAUSED,
            )
        )
        manager.add_subscription(
            _make_subscription(
                subscription_id="sub-c",
                user_id="bob",
                status=SubscriptionStatus.ACTIVE,
            )
        )
        result = manager.list_subscriptions(user_id="alice", active_only=True)
        assert [s.subscription_id for s in result] == ["sub-a"]


class TestUpdate:
    def test_update_persists_changes(self, manager: SubscriptionManager) -> None:
        sub = _make_subscription()
        manager.add_subscription(sub)
        sub.name = "Renamed"
        sub.keywords = ["new"]
        sub.status = SubscriptionStatus.PAUSED
        manager.update_subscription(sub)
        fetched = manager.get_subscription(sub.subscription_id)
        assert fetched is not None
        assert fetched.name == "Renamed"
        assert fetched.keywords == ["new"]
        assert fetched.status == SubscriptionStatus.PAUSED

    def test_update_missing_raises_keyerror(self, manager: SubscriptionManager) -> None:
        ghost = _make_subscription(subscription_id="sub-ghost")
        with pytest.raises(KeyError, match="Subscription not found"):
            manager.update_subscription(ghost)

    def test_update_with_last_checked(self, manager: SubscriptionManager) -> None:
        sub = _make_subscription()
        manager.add_subscription(sub)
        sub.last_checked_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        manager.update_subscription(sub)
        fetched = manager.get_subscription(sub.subscription_id)
        assert fetched is not None
        assert fetched.last_checked_at == sub.last_checked_at


class TestDelete:
    def test_delete_existing_returns_true(self, manager: SubscriptionManager) -> None:
        sub = _make_subscription()
        manager.add_subscription(sub)
        assert manager.delete_subscription(sub.subscription_id) is True
        assert manager.get_subscription(sub.subscription_id) is None

    def test_delete_missing_returns_false(self, manager: SubscriptionManager) -> None:
        assert manager.delete_subscription("sub-missing") is False


class TestSetStatus:
    def test_set_status_pauses(self, manager: SubscriptionManager) -> None:
        sub = _make_subscription()
        manager.add_subscription(sub)
        manager.set_status(sub.subscription_id, SubscriptionStatus.PAUSED)
        fetched = manager.get_subscription(sub.subscription_id)
        assert fetched is not None
        assert fetched.status == SubscriptionStatus.PAUSED

    def test_set_status_activates(self, manager: SubscriptionManager) -> None:
        sub = _make_subscription(status=SubscriptionStatus.PAUSED)
        manager.add_subscription(sub)
        manager.set_status(sub.subscription_id, SubscriptionStatus.ACTIVE)
        fetched = manager.get_subscription(sub.subscription_id)
        assert fetched is not None
        assert fetched.status == SubscriptionStatus.ACTIVE

    def test_set_status_missing_raises_keyerror(
        self, manager: SubscriptionManager
    ) -> None:
        with pytest.raises(KeyError, match="Subscription not found"):
            manager.set_status("sub-missing", SubscriptionStatus.PAUSED)


class TestMarkChecked:
    def test_mark_checked_explicit_timestamp(
        self, manager: SubscriptionManager
    ) -> None:
        sub = _make_subscription()
        manager.add_subscription(sub)
        when = datetime(2024, 3, 15, 12, 0, tzinfo=timezone.utc)
        manager.mark_checked(sub.subscription_id, when=when)
        fetched = manager.get_subscription(sub.subscription_id)
        assert fetched is not None
        assert fetched.last_checked_at == when

    def test_mark_checked_default_now(self, manager: SubscriptionManager) -> None:
        sub = _make_subscription()
        manager.add_subscription(sub)
        before = datetime.now(timezone.utc)
        manager.mark_checked(sub.subscription_id)
        after = datetime.now(timezone.utc) + timedelta(seconds=1)
        fetched = manager.get_subscription(sub.subscription_id)
        assert fetched is not None
        assert fetched.last_checked_at is not None
        assert before - timedelta(seconds=1) <= fetched.last_checked_at <= after

    def test_mark_checked_missing_raises_keyerror(
        self, manager: SubscriptionManager
    ) -> None:
        with pytest.raises(KeyError, match="Subscription not found"):
            manager.mark_checked("sub-missing")


# ---------------------------------------------------------------------------
# Limit enforcement
# ---------------------------------------------------------------------------


class TestLimits:
    def test_per_user_subscription_cap(
        self, manager: SubscriptionManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Lower the cap to keep the test fast and deterministic.
        monkeypatch.setattr(SubscriptionManager, "MAX_SUBSCRIPTIONS_PER_USER", 3)
        for i in range(3):
            manager.add_subscription(
                _make_subscription(subscription_id=f"sub-{i:03d}", user_id="alice")
            )
        with pytest.raises(SubscriptionLimitError) as excinfo:
            manager.add_subscription(
                _make_subscription(subscription_id="sub-overflow", user_id="alice")
            )
        assert excinfo.value.limit_type == "subscriptions per user"
        assert excinfo.value.current == 3
        assert excinfo.value.max_allowed == 3

    def test_per_user_cap_isolated_by_user(
        self, manager: SubscriptionManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Other users should not be affected.
        monkeypatch.setattr(SubscriptionManager, "MAX_SUBSCRIPTIONS_PER_USER", 2)
        for i in range(2):
            manager.add_subscription(
                _make_subscription(subscription_id=f"a-{i}", user_id="alice")
            )
        # Bob can still add up to his own cap.
        manager.add_subscription(
            _make_subscription(subscription_id="b-0", user_id="bob")
        )
        assert len(manager.list_subscriptions(user_id="bob")) == 1

    def test_add_keyword_limit_raises_before_db(
        self, manager: SubscriptionManager
    ) -> None:
        # The model validator enforces the cap, but the manager keeps a
        # defensive guard. We exercise it by constructing a subscription
        # with a maxed-out keyword list, then mutating it past the cap
        # to bypass model validation.
        sub = _make_subscription(
            keywords=[f"k-{i}" for i in range(MAX_KEYWORDS_PER_SUBSCRIPTION)]
        )
        # Bypass validation by directly mutating the underlying list.
        sub.keywords.append("overflow-kw")
        with pytest.raises(SubscriptionLimitError) as excinfo:
            manager.add_subscription(sub)
        assert excinfo.value.limit_type == "keywords per subscription"
        assert excinfo.value.current == MAX_KEYWORDS_PER_SUBSCRIPTION + 1

    def test_update_keyword_limit_raises(self, manager: SubscriptionManager) -> None:
        sub = _make_subscription()
        manager.add_subscription(sub)
        # Push past the cap directly on the model to bypass validation.
        sub.keywords = [f"k-{i}" for i in range(MAX_KEYWORDS_PER_SUBSCRIPTION + 1)]
        with pytest.raises(SubscriptionLimitError):
            manager.update_subscription(sub)


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    def test_rejects_path_outside_approved_roots(self) -> None:
        from src.utils.security import SecurityError

        with pytest.raises(SecurityError):
            SubscriptionManager("/etc/forbidden.db")

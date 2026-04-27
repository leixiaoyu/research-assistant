"""Tests for monitoring Pydantic V2 models (Milestone 9.1).

Covers:
- All enums (``SubscriptionStatus``, ``MonitoringRunStatus``)
- Every field validator on ``ResearchSubscription``
- ``MonitoringPaperRecord`` + ``MonitoringRun`` construction & limit enforcement
- ``SubscriptionLimitError`` raising at the documented thresholds
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.services.intelligence.models.monitoring import (
    PaperSource,
    SubscriptionLimitError,
)
from src.services.intelligence.monitoring.models import (
    MAX_KEYWORDS_PER_SUBSCRIPTION,
    MAX_PAPERS_PER_CYCLE,
    MonitoringPaperRecord,
    MonitoringRun,
    MonitoringRunStatus,
    ResearchSubscription,
    SubscriptionStatus,
)

# ---------------------------------------------------------------------------
# Enum surface
# ---------------------------------------------------------------------------


class TestSubscriptionStatusEnum:
    def test_subscription_status_values(self) -> None:
        assert SubscriptionStatus.ACTIVE.value == "active"
        assert SubscriptionStatus.PAUSED.value == "paused"

    def test_subscription_status_str_subclass(self) -> None:
        # str-Enum interop: comparison with raw string works via ``.value``.
        assert SubscriptionStatus.ACTIVE == "active"
        assert SubscriptionStatus("paused") is SubscriptionStatus.PAUSED


class TestMonitoringRunStatusEnum:
    def test_monitoring_run_status_values(self) -> None:
        assert MonitoringRunStatus.SUCCESS.value == "success"
        assert MonitoringRunStatus.PARTIAL.value == "partial"
        assert MonitoringRunStatus.FAILED.value == "failed"


# ---------------------------------------------------------------------------
# ResearchSubscription
# ---------------------------------------------------------------------------


class TestResearchSubscriptionConstruction:
    def test_construction_minimal_defaults(self) -> None:
        sub = ResearchSubscription(name="x", query="q")
        assert sub.subscription_id.startswith("sub-")
        assert sub.user_id == "default"
        assert sub.keywords == []
        assert sub.exclude_keywords == []
        assert sub.min_relevance_score == 0.7
        assert sub.sources == [PaperSource.ARXIV]
        assert sub.poll_interval_hours == 6
        assert sub.status is SubscriptionStatus.ACTIVE
        assert sub.last_checked_at is None
        assert isinstance(sub.created_at, datetime)
        assert isinstance(sub.updated_at, datetime)

    def test_construction_explicit_fields(self) -> None:
        sub = ResearchSubscription(
            subscription_id="sub-abc123",
            user_id="alice",
            name="PEFT Research",
            query="LoRA OR QLoRA",
            keywords=["lora", "qlora"],
            exclude_keywords=["survey"],
            min_relevance_score=0.5,
            poll_interval_hours=12,
            sources=[PaperSource.ARXIV],
            status=SubscriptionStatus.PAUSED,
        )
        assert sub.subscription_id == "sub-abc123"
        assert sub.user_id == "alice"
        assert sub.keywords == ["lora", "qlora"]
        assert sub.exclude_keywords == ["survey"]
        assert sub.status is SubscriptionStatus.PAUSED

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSubscription(
                name="x", query="q", junk="bad"  # type: ignore[call-arg]
            )


class TestIdentifierValidators:
    def test_subscription_id_strip_whitespace(self) -> None:
        sub = ResearchSubscription(
            subscription_id=" sub-x ",
            name="n",
            query="q",
        )
        assert sub.subscription_id == "sub-x"

    def test_subscription_id_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSubscription(subscription_id="   ", name="n", query="q")

    def test_subscription_id_rejects_invalid_chars(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            ResearchSubscription(subscription_id="bad id!", name="n", query="q")
        assert "Invalid identifier format" in str(excinfo.value)

    def test_user_id_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSubscription(user_id=" ", name="n", query="q")

    def test_user_id_rejects_invalid_chars(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSubscription(user_id="alice@host", name="n", query="q")


class TestNameValidator:
    def test_name_strip_whitespace(self) -> None:
        sub = ResearchSubscription(name="  My Sub ", query="q")
        assert sub.name == "My Sub"

    def test_name_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSubscription(name="   ", query="q")

    def test_name_rejects_invalid_chars(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            ResearchSubscription(name="bad/name", query="q")
        assert "Invalid subscription name" in str(excinfo.value)

    def test_name_accepts_allowed_chars(self) -> None:
        sub = ResearchSubscription(name="My-Sub_1.0 (v2)", query="q")
        assert sub.name == "My-Sub_1.0 (v2)"


class TestQueryValidator:
    def test_query_strip_whitespace(self) -> None:
        sub = ResearchSubscription(name="n", query="  some query  ")
        assert sub.query == "some query"

    def test_query_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSubscription(name="n", query="   ")


class TestKeywordsValidator:
    def test_keywords_lowercase_dedup(self) -> None:
        sub = ResearchSubscription(name="n", query="q", keywords=["Foo", "foo", "BAR"])
        # First-seen casing preserved; duplicate (lowered) dropped.
        assert sub.keywords == ["Foo", "BAR"]

    def test_keywords_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            ResearchSubscription(name="n", query="q", keywords=["valid", "  "])
        assert "Keywords cannot be empty" in str(excinfo.value)

    def test_keywords_rejects_invalid_chars(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            ResearchSubscription(name="n", query="q", keywords=["bad@kw"])
        assert "Invalid keyword" in str(excinfo.value)

    def test_keywords_accepts_allowed_chars(self) -> None:
        sub = ResearchSubscription(
            name="n",
            query="q",
            keywords=["foo+bar", "baz/qux", "a:b", "c.d-e_f", "(group)"],
        )
        assert len(sub.keywords) == 5

    def test_keywords_limit_raises_subscription_limit_error(self) -> None:
        too_many = [f"kw-{i}" for i in range(MAX_KEYWORDS_PER_SUBSCRIPTION + 1)]
        with pytest.raises(ValidationError) as excinfo:
            ResearchSubscription(name="n", query="q", keywords=too_many)
        # SubscriptionLimitError is a ValueError subclass; Pydantic wraps
        # it into ValidationError, but the chained cause is preserved.
        cause = excinfo.value.errors()[0]
        assert "Subscription limit exceeded" in cause["msg"]
        assert "keywords per subscription" in cause["msg"]

    def test_keywords_at_limit_accepted(self) -> None:
        # Exactly at the limit must succeed.
        kws = [f"kw-{i}" for i in range(MAX_KEYWORDS_PER_SUBSCRIPTION)]
        sub = ResearchSubscription(name="n", query="q", keywords=kws)
        assert len(sub.keywords) == MAX_KEYWORDS_PER_SUBSCRIPTION

    def test_exclude_keywords_share_validator(self) -> None:
        # Same validator runs for both fields.
        with pytest.raises(ValidationError):
            ResearchSubscription(name="n", query="q", exclude_keywords=["bad@kw"])


class TestSourcesValidator:
    def test_sources_default_arxiv(self) -> None:
        sub = ResearchSubscription(name="n", query="q")
        assert sub.sources == [PaperSource.ARXIV]

    def test_sources_explicit_arxiv_normalized(self) -> None:
        sub = ResearchSubscription(
            name="n", query="q", sources=[PaperSource.ARXIV, PaperSource.ARXIV]
        )
        # Normalized to single ArXiv entry.
        assert sub.sources == [PaperSource.ARXIV]

    def test_sources_rejects_non_arxiv(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            ResearchSubscription(
                name="n", query="q", sources=[PaperSource.SEMANTIC_SCHOLAR]
            )
        assert "Only PaperSource.ARXIV is supported" in str(excinfo.value)

    def test_sources_rejects_mixed(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSubscription(
                name="n",
                query="q",
                sources=[PaperSource.ARXIV, PaperSource.OPENALEX],
            )

    def test_sources_validator_rejects_empty_directly(self) -> None:
        # ``min_length=1`` on the field already catches empty lists, but
        # the inner validator has its own defensive guard. Exercise it
        # directly so the branch isn't dead code.
        with pytest.raises(ValueError, match="At least one source is required"):
            ResearchSubscription._validate_sources_arxiv_only([])


class TestRangeValidators:
    def test_min_relevance_score_out_of_range_low(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSubscription(name="n", query="q", min_relevance_score=-0.01)

    def test_min_relevance_score_out_of_range_high(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSubscription(name="n", query="q", min_relevance_score=1.5)

    def test_poll_interval_too_low(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSubscription(name="n", query="q", poll_interval_hours=0)

    def test_poll_interval_too_high(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSubscription(name="n", query="q", poll_interval_hours=24 * 7 + 1)


# ---------------------------------------------------------------------------
# MonitoringPaperRecord
# ---------------------------------------------------------------------------


class TestMonitoringPaperRecord:
    def test_paper_record_minimal(self) -> None:
        rec = MonitoringPaperRecord(paper_id="2301.12345", title="A Paper", is_new=True)
        assert rec.paper_id == "2301.12345"
        assert rec.title == "A Paper"
        assert rec.is_new is True
        assert rec.url is None
        assert rec.pdf_url is None
        assert rec.published_at is None
        assert rec.relevance_score is None
        assert rec.relevance_reasoning is None

    def test_paper_record_full(self) -> None:
        rec = MonitoringPaperRecord(
            paper_id="2301.12345",
            title="A Paper",
            url="https://arxiv.org/abs/2301.12345",
            pdf_url="https://arxiv.org/pdf/2301.12345",
            published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            is_new=False,
            relevance_score=0.9,
            relevance_reasoning="strong match",
        )
        assert rec.url == "https://arxiv.org/abs/2301.12345"
        assert rec.relevance_score == 0.9

    def test_paper_record_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            MonitoringPaperRecord(
                paper_id="x",
                title="t",
                is_new=True,
                junk="bad",  # type: ignore[call-arg]
            )

    def test_paper_record_relevance_score_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            MonitoringPaperRecord(
                paper_id="x", title="t", is_new=True, relevance_score=1.5
            )


# ---------------------------------------------------------------------------
# MonitoringRun
# ---------------------------------------------------------------------------


class TestMonitoringRun:
    def test_monitoring_run_defaults(self) -> None:
        run = MonitoringRun(subscription_id="sub-1")
        assert run.run_id.startswith("run-")
        assert run.source is PaperSource.ARXIV
        assert run.status is MonitoringRunStatus.SUCCESS
        assert run.papers == []
        assert run.papers_seen == 0
        assert run.error is None
        assert run.scheduled_job_id is None

    def test_monitoring_run_below_paper_cap(self) -> None:
        records = [
            MonitoringPaperRecord(paper_id=f"p-{i}", title="t", is_new=True)
            for i in range(3)
        ]
        run = MonitoringRun(subscription_id="sub-1", papers=records)
        assert len(run.papers) == 3

    def test_monitoring_run_at_paper_cap_accepted(self) -> None:
        records = [
            MonitoringPaperRecord(paper_id=f"p-{i}", title="t", is_new=True)
            for i in range(MAX_PAPERS_PER_CYCLE)
        ]
        run = MonitoringRun(subscription_id="sub-1", papers=records)
        assert len(run.papers) == MAX_PAPERS_PER_CYCLE

    def test_monitoring_run_above_paper_cap_raises(self) -> None:
        records = [
            MonitoringPaperRecord(paper_id=f"p-{i}", title="t", is_new=True)
            for i in range(MAX_PAPERS_PER_CYCLE + 1)
        ]
        with pytest.raises(ValidationError) as excinfo:
            MonitoringRun(subscription_id="sub-1", papers=records)
        cause = excinfo.value.errors()[0]
        assert "papers per cycle" in cause["msg"]

    def test_monitoring_run_negative_counts_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MonitoringRun(subscription_id="sub-1", papers_seen=-1)


# ---------------------------------------------------------------------------
# SubscriptionLimitError surface
# ---------------------------------------------------------------------------


class TestSubscriptionLimitErrorIntegration:
    def test_subscription_limit_error_attributes(self) -> None:
        # Check attributes set on the canonical exception so callers can
        # render structured error responses.
        err = SubscriptionLimitError("keywords per subscription", 105, 100)
        assert err.limit_type == "keywords per subscription"
        assert err.current == 105
        assert err.max_allowed == 100
        assert "Subscription limit exceeded" in str(err)

    def test_subscription_limit_error_is_value_error(self) -> None:
        # ValueError ancestry is what lets Pydantic wrap it cleanly.
        assert issubclass(SubscriptionLimitError, ValueError)

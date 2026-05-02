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
    MonitoringPaperAudit,
    MonitoringPaperRecord,
    MonitoringRun,
    MonitoringRunAudit,
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

    def test_keyword_oversize_single_rejected(self) -> None:
        """H-S2: A single keyword exceeding 200 chars is rejected."""
        oversize_kw = "a" * 201
        with pytest.raises(ValidationError) as excinfo:
            ResearchSubscription(name="n", query="q", keywords=[oversize_kw])
        assert "too long" in str(excinfo.value)

    def test_keyword_exactly_200_chars_accepted(self) -> None:
        """H-S2: A keyword of exactly 200 chars is accepted."""
        # Must contain only allowed chars (alphanumeric for simplicity).
        ok_kw = "a" * 200
        sub = ResearchSubscription(name="n", query="q", keywords=[ok_kw])
        assert len(sub.keywords) == 1

    def test_exclude_keyword_oversize_single_rejected(self) -> None:
        """H-S2: Same 200-char cap applies to exclude_keywords."""
        oversize_kw = "b" * 201
        with pytest.raises(ValidationError) as excinfo:
            ResearchSubscription(name="n", query="q", exclude_keywords=[oversize_kw])
        assert "too long" in str(excinfo.value)

    def test_keyword_cumulative_oversize_rejected(self) -> None:
        """H-S2: Cumulative keyword list exceeding 4096 bytes is rejected."""
        # Each keyword is 100 chars; 42 keywords -> 42*100 + 41*2 = 4282 bytes.
        kws = [f"{'a' * 98}{i:02d}" for i in range(42)]
        with pytest.raises(ValidationError) as excinfo:
            ResearchSubscription(name="n", query="q", keywords=kws)
        assert "Cumulative keyword" in str(excinfo.value)

    def test_keyword_cumulative_within_limit_accepted(self) -> None:
        """H-S2: Cumulative keyword list within 4096 bytes is accepted."""
        # 20 keywords of 10 chars each = 200 + 38*2 = 276 bytes -- well within limit.
        kws = [f"{'a' * 9}{i:01d}" for i in range(20)]
        sub = ResearchSubscription(name="n", query="q", keywords=kws)
        assert len(sub.keywords) == 20


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


# ---------------------------------------------------------------------------
# MonitoringPaperAudit (PR #124 #C5)
# ---------------------------------------------------------------------------
#
# CLAUDE.md requires Pydantic validators to be behaviorally tested. The
# audit DTOs were added in PR #124 with field caps + ``extra="forbid"``
# but no per-field validator coverage; this block adds happy/reject
# cases that pin every constraint on ``MonitoringPaperAudit`` and
# ``MonitoringRunAudit``.


class TestMonitoringPaperAudit:
    """Validator + boundary coverage for ``MonitoringPaperAudit``.

    Pinned constraints:
    - ``paper_id``: min_length=1, max_length=512 (post-#S6 alignment)
    - ``relevance_score``: range [0.0, 1.0], Optional, default None
    - ``relevance_reasoning``: max_length=4096 (post-#S7 alignment),
      Optional, default None
    - ``registered``: bool, default False
    - ``extra="forbid"``: unknown fields rejected
    """

    def test_audit_minimal_defaults(self) -> None:
        rec = MonitoringPaperAudit(paper_id="2301.12345")
        assert rec.paper_id == "2301.12345"
        assert rec.registered is False
        assert rec.relevance_score is None
        assert rec.relevance_reasoning is None

    def test_audit_full_construction(self) -> None:
        rec = MonitoringPaperAudit(
            paper_id="2301.12345",
            registered=True,
            relevance_score=0.9,
            relevance_reasoning="strong match",
        )
        assert rec.paper_id == "2301.12345"
        assert rec.registered is True
        assert rec.relevance_score == 0.9
        assert rec.relevance_reasoning == "strong match"

    def test_audit_paper_id_rejects_empty(self) -> None:
        with pytest.raises(ValidationError, match="at least 1 character"):
            MonitoringPaperAudit(paper_id="")

    def test_audit_paper_id_at_boundary_accepted(self) -> None:
        # 512 chars exactly -- the post-#S6 cap.
        rec = MonitoringPaperAudit(paper_id="x" * 512)
        assert len(rec.paper_id) == 512

    def test_audit_paper_id_above_boundary_rejected(self) -> None:
        # 513 chars -- one over the max_length boundary.
        with pytest.raises(ValidationError, match="at most 512 character"):
            MonitoringPaperAudit(paper_id="x" * 513)

    def test_audit_relevance_score_below_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MonitoringPaperAudit(paper_id="x", relevance_score=-0.01)

    def test_audit_relevance_score_above_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MonitoringPaperAudit(paper_id="x", relevance_score=1.01)

    def test_audit_relevance_reasoning_at_boundary_accepted(self) -> None:
        rec = MonitoringPaperAudit(paper_id="x", relevance_reasoning="r" * 4096)
        assert len(rec.relevance_reasoning or "") == 4096

    def test_audit_relevance_reasoning_above_boundary_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at most 4096 character"):
            MonitoringPaperAudit(paper_id="x", relevance_reasoning="r" * 4097)

    def test_audit_extra_field_forbidden(self) -> None:
        # Pinning ``extra="forbid"`` -- unknown fields like ``unknown=...``
        # must raise so callers can't silently smuggle data the audit
        # table cannot store.
        with pytest.raises(ValidationError):
            MonitoringPaperAudit(paper_id="x", unknown="y")  # type: ignore[call-arg]


class TestMonitoringRunAudit:
    """Validator + composition coverage for ``MonitoringRunAudit``.

    Pinned constraints:
    - String fields capped at 64 chars; ``error`` capped at 2000.
    - ``papers``: list of ``MonitoringPaperAudit`` only, defaults to [].
    - ``papers_seen`` / ``papers_new``: ge=0.
    - ``extra="forbid"``: unknown fields rejected.
    - Round-trip via ``model_dump`` / ``model_validate``.
    """

    def _audit(
        self, *, papers: list[MonitoringPaperAudit] | None = None
    ) -> MonitoringRunAudit:
        return MonitoringRunAudit(
            run_id="run-001",
            subscription_id="sub-001",
            user_id="alice",
            started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            status=MonitoringRunStatus.SUCCESS,
            papers=papers or [],
        )

    def test_audit_run_minimal_no_papers(self) -> None:
        run = self._audit()
        assert run.papers == []
        assert run.papers_seen == 0
        assert run.papers_new == 0
        assert run.finished_at is None
        assert run.error is None

    def test_audit_run_with_one_paper(self) -> None:
        papers = [MonitoringPaperAudit(paper_id="2301.0001", registered=True)]
        run = self._audit(papers=papers)
        assert len(run.papers) == 1
        assert run.papers[0].paper_id == "2301.0001"

    def test_audit_run_with_many_papers(self) -> None:
        papers = [MonitoringPaperAudit(paper_id=f"p-{i}") for i in range(5)]
        run = self._audit(papers=papers)
        assert len(run.papers) == 5

    def test_audit_run_papers_must_be_audit_instances(self) -> None:
        # Composition guard: passing a MonitoringPaperRecord (the rich
        # in-memory type) must fail. Pydantic will try to coerce dict
        # values, but a record carries fields like ``title`` that the
        # audit type forbids -- so the coercion fails.
        record = MonitoringPaperRecord(
            paper_id="2301.0001", title="Some Paper", is_new=True
        )
        with pytest.raises(ValidationError):
            MonitoringRunAudit(
                run_id="run-001",
                subscription_id="sub-001",
                user_id="alice",
                started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                status=MonitoringRunStatus.SUCCESS,
                papers=[record.model_dump()],  # type: ignore[list-item]
            )

    def test_audit_run_negative_paper_counts_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MonitoringRunAudit(
                run_id="run-001",
                subscription_id="sub-001",
                user_id="alice",
                started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                status=MonitoringRunStatus.SUCCESS,
                papers_seen=-1,
            )

    def test_audit_run_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            MonitoringRunAudit(
                run_id="run-001",
                subscription_id="sub-001",
                user_id="alice",
                started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                status=MonitoringRunStatus.SUCCESS,
                junk="bad",  # type: ignore[call-arg]
            )

    def test_audit_run_round_trip_via_model_dump(self) -> None:
        original = self._audit(
            papers=[
                MonitoringPaperAudit(paper_id="p-1", registered=True),
                MonitoringPaperAudit(
                    paper_id="p-2",
                    relevance_score=0.5,
                    relevance_reasoning="ok",
                ),
            ]
        )
        rebuilt = MonitoringRunAudit.model_validate(original.model_dump())
        assert rebuilt == original
        assert isinstance(rebuilt, MonitoringRunAudit)
        for p in rebuilt.papers:
            assert isinstance(p, MonitoringPaperAudit)

    def test_audit_run_run_id_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            MonitoringRunAudit(
                run_id="",
                subscription_id="sub-001",
                user_id="alice",
                started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                status=MonitoringRunStatus.SUCCESS,
            )

    def test_audit_run_status_must_be_enum_member(self) -> None:
        # Strict mode -- arbitrary string is not coerced.
        with pytest.raises(ValidationError):
            MonitoringRunAudit(
                run_id="run-001",
                subscription_id="sub-001",
                user_id="alice",
                started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                status="bogus",  # type: ignore[arg-type]
            )

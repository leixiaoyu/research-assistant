"""Tests for ``DigestGenerator`` (Milestone 9.1, Week 2).

Covers:
- Construction validation (top_n > 0; output_root sanitized).
- Output path follows ``{YYYY-MM-DD}_{subscription_id}_digest.md``.
- Markdown frontmatter + sections rendered correctly.
- Top-N truncation by descending relevance_score (stable secondary key).
- Empty papers list -> minimal digest with explicit "no papers" line.
- Reasoning truncation at 280 chars.
- Registry hit -> uses snapshot title + URL.
- Registry miss + no metadata snapshot -> falls back to paper_id.
- Registry exception -> graceful fallback to paper_id (does not raise).
- Provider-id lookup against ``provider_id_index`` for ArXiv ids.
- Path traversal in subscription_id rejected (SecurityError).
- Path traversal via output_root rejected (SecurityError).
- Atomic write: tmp file removed after rename, target exists.
- Snapshot-style assertion on the rendered markdown for a known input.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from src.services.intelligence.monitoring.digest_generator import (
    DEFAULT_OUTPUT_ROOT,
    DigestGenerator,
    REASONING_TRUNCATE_CHARS,
)
from src.services.intelligence.monitoring.models import (
    MonitoringPaperAudit,
    MonitoringRunAudit,
    MonitoringRunStatus,
    ResearchSubscription,
)
from src.utils.security import SecurityError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_subscription(
    *,
    subscription_id: str = "sub-test12345",
    name: str = "PEFT Research",
) -> ResearchSubscription:
    return ResearchSubscription(
        subscription_id=subscription_id,
        user_id="alice",
        name=name,
        query="parameter efficient fine tuning",
    )


def _make_paper_audit(
    *,
    paper_id: str = "2401.00001",
    relevance_score: Optional[float] = 0.8,
    relevance_reasoning: Optional[str] = "Highly relevant",
    registered: bool = False,
) -> MonitoringPaperAudit:
    return MonitoringPaperAudit(
        paper_id=paper_id,
        registered=registered,
        relevance_score=relevance_score,
        relevance_reasoning=relevance_reasoning,
    )


def _make_run(
    *,
    run_id: str = "run-test1234",
    subscription_id: str = "sub-test12345",
    user_id: str = "alice",
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    status: MonitoringRunStatus = MonitoringRunStatus.SUCCESS,
    papers_seen: int = 0,
    papers_new: int = 0,
    papers: Optional[list[MonitoringPaperAudit]] = None,
) -> MonitoringRunAudit:
    return MonitoringRunAudit(
        run_id=run_id,
        subscription_id=subscription_id,
        user_id=user_id,
        started_at=started_at or datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        finished_at=finished_at,
        status=status,
        papers_seen=papers_seen,
        papers_new=papers_new,
        papers=papers or [],
    )


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    """Return a temp dir for digest output (within the system temp sandbox)."""
    out = tmp_path / "digests"
    out.mkdir()
    return out


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestDigestGeneratorInit:
    """Construction validates inputs + creates the output dir."""

    def test_invalid_top_n_rejected(self, tmp_output: Path) -> None:
        with pytest.raises(ValueError, match="top_n must be positive"):
            DigestGenerator(tmp_output, top_n=0)

    def test_negative_top_n_rejected(self, tmp_output: Path) -> None:
        with pytest.raises(ValueError, match="top_n must be positive"):
            DigestGenerator(tmp_output, top_n=-5)

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        # Use a non-existent subdir under the system temp dir.
        sub = tmp_path / "new_dir"
        assert not sub.exists()
        DigestGenerator(sub)
        assert sub.exists() and sub.is_dir()

    def test_default_output_root_constant(self) -> None:
        # The module exposes the default for downstream consumers.
        assert DEFAULT_OUTPUT_ROOT == Path("./output/digests")

    def test_output_root_outside_sandbox_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pick a path that is neither under cwd/output nor system temp.
        monkeypatch.chdir("/")  # cwd = "/"
        with pytest.raises(SecurityError):
            DigestGenerator(Path("/etc/whatever"))


# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------


class TestSubscriptionSlugValidation:
    """Slug validation guards the filesystem."""

    def test_slash_in_id_rejected(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        sub = _make_subscription(subscription_id="sub-aaa")
        # Replace the validated id post-construction so we exercise the
        # generate-time check (the model itself rejects slashes).
        sub_dict = sub.model_dump()
        sub_dict["subscription_id"] = "..%2Fmalicious"
        # Build an attacker-shaped sub by passing through model_construct
        # to skip validation -- the digest generator must still reject.
        bad_sub = sub.model_copy()
        object.__setattr__(bad_sub, "subscription_id", "../malicious")
        run = _make_run(subscription_id="../malicious")
        with pytest.raises(SecurityError):
            gen.generate(run, bad_sub)

    def test_empty_id_rejected(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        sub = _make_subscription()
        bad_sub = sub.model_copy()
        object.__setattr__(bad_sub, "subscription_id", "")
        run = _make_run()
        with pytest.raises(SecurityError):
            gen.generate(run, bad_sub)


# ---------------------------------------------------------------------------
# Filename + atomic write
# ---------------------------------------------------------------------------


class TestGenerateFilenameAndWrite:
    """Filename derivation + atomic write semantics."""

    def test_filename_format(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        sub = _make_subscription(subscription_id="sub-mysub")
        run = _make_run(
            started_at=datetime(2026, 4, 24, 6, 0, tzinfo=timezone.utc),
        )
        path = gen.generate(run, sub)

        assert path.name == "2026-04-24_sub-mysub_digest.md"
        assert path.parent == tmp_output

    def test_target_file_exists_after_write(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        path = gen.generate(_make_run(), _make_subscription())
        assert path.exists()
        # The tmp file from the atomic-write step must be cleaned up
        # via os.replace (which renames it onto the target).
        assert not (path.parent / (path.name + ".tmp")).exists()

    def test_overwrites_existing(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        path1 = gen.generate(_make_run(), _make_subscription())
        # Write a second time with different content; must replace.
        run2 = _make_run(papers_seen=10)
        path2 = gen.generate(run2, _make_subscription())
        assert path1 == path2
        assert "papers_seen: 10" in path2.read_text()

    def test_writes_utf8(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        sub = _make_subscription(name="PEFT Research")
        path = gen.generate(_make_run(), sub)
        # Ensure read-back as UTF-8 works (no BOM, no encoding errors).
        text = path.read_text(encoding="utf-8")
        assert text  # non-empty


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


class TestMarkdownRendering:
    """Rendered markdown content under various inputs."""

    def test_frontmatter_and_sections_present(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        sub = _make_subscription()
        run = _make_run(
            finished_at=datetime(2026, 4, 24, 12, 30, tzinfo=timezone.utc),
            papers_seen=2,
            papers_new=1,
            papers=[
                _make_paper_audit(
                    paper_id="2401.00001",
                    relevance_score=0.9,
                    relevance_reasoning="Strong match",
                    registered=True,
                ),
                _make_paper_audit(
                    paper_id="2401.00002",
                    relevance_score=0.4,
                    relevance_reasoning="Weak match",
                ),
            ],
        )
        text = gen.generate(run, sub).read_text()

        # Frontmatter
        assert text.startswith("---\n")
        assert "subscription_id: sub-test12345" in text
        assert "name: PEFT Research" in text
        assert f"run_id: {run.run_id}" in text
        # Sections
        assert "# Monitoring Digest: PEFT Research" in text
        assert "## Top Papers" in text
        assert "## Reasoning Highlights" in text
        assert "## Stats" in text
        # Top-papers ordering (0.9 before 0.4)
        idx_high = text.index("0.90")
        idx_low = text.index("0.40")
        assert idx_high < idx_low
        # `(new)` marker on the registered paper
        assert "(new)" in text
        # Stats numbers
        assert "Papers seen: 2" in text
        assert "Papers new (registered this run): 1" in text

    def test_empty_papers_minimal_digest(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        text = gen.generate(_make_run(), _make_subscription()).read_text()
        assert "_No papers were seen in this run._" in text
        assert "_No reasoning provided for the featured papers._" in text
        assert "Papers seen: 0" in text

    def test_top_n_truncation(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output, top_n=2)
        papers = [
            _make_paper_audit(
                paper_id=f"id-{i}",
                relevance_score=1.0 - i * 0.1,
                relevance_reasoning=f"r{i}",
            )
            for i in range(5)
        ]
        run = _make_run(papers_seen=5, papers=papers)
        text = gen.generate(run, _make_subscription()).read_text()
        # Top-2 by score: id-0 (1.0) and id-1 (0.9)
        assert "id-0" in text
        assert "id-1" in text
        # id-2..id-4 omitted from Top Papers section but counted in Stats
        # (stats rolls all five up)
        assert "Papers seen: 5" in text

    def test_none_score_papers_sorted_to_bottom(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        papers = [
            _make_paper_audit(paper_id="scored", relevance_score=0.3),
            _make_paper_audit(paper_id="unscored", relevance_score=None),
        ]
        run = _make_run(papers=papers)
        text = gen.generate(run, _make_subscription()).read_text()
        # The scored one should appear first.
        assert text.index("scored") < text.index("unscored")
        # And the unscored one renders score "n/a".
        assert "n/a" in text

    def test_reasoning_truncation_at_cap(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        # 500-char reasoning -> truncated to 280 with "..." ending.
        long_reasoning = "x" * 500
        papers = [
            _make_paper_audit(
                paper_id="2401.00001",
                relevance_score=0.5,
                relevance_reasoning=long_reasoning,
            )
        ]
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()
        assert ("x" * (REASONING_TRUNCATE_CHARS - 3) + "...") in text
        assert ("x" * 500) not in text

    def test_papers_without_reasoning_skipped_in_highlights(
        self, tmp_output: Path
    ) -> None:
        gen = DigestGenerator(tmp_output)
        papers = [
            _make_paper_audit(
                paper_id="no-reason",
                relevance_score=0.7,
                relevance_reasoning=None,
            )
        ]
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()
        assert "_No reasoning provided for the featured papers._" in text

    def test_stats_average_score(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        papers = [
            _make_paper_audit(paper_id="a", relevance_score=0.8),
            _make_paper_audit(paper_id="b", relevance_score=0.4),
            _make_paper_audit(paper_id="c", relevance_score=None),
        ]
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()
        # avg of 0.8 + 0.4 = 0.6
        assert "Average relevance score: 0.600" in text

    def test_stats_average_score_none_when_no_scored(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        papers = [
            _make_paper_audit(paper_id="x", relevance_score=None),
        ]
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()
        assert "Average relevance score: n/a" in text

    def test_summary_paragraph_includes_status(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        run = _make_run(status=MonitoringRunStatus.PARTIAL)
        text = gen.generate(run, _make_subscription()).read_text()
        assert "Status: **partial**" in text

    def test_summary_paragraph_handles_unfinished_run(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        run = _make_run(finished_at=None)
        text = gen.generate(run, _make_subscription()).read_text()
        assert "(in progress)" in text


# ---------------------------------------------------------------------------
# Registry lookup
# ---------------------------------------------------------------------------


class TestRegistryLookup:
    """Title/URL resolution via the optional RegistryService."""

    def test_no_registry_falls_back_to_paper_id(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)  # no registry
        papers = [_make_paper_audit(paper_id="2401.99999")]
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()
        # Title in the Top Papers list is the paper_id (no link).
        assert "2401.99999" in text

    def test_registry_hit_uses_snapshot_title(self, tmp_output: Path) -> None:
        registry = MagicMock()
        # First call: get_entry returns an entry with metadata_snapshot.
        entry = MagicMock()
        entry.metadata_snapshot = {
            "title": "Awesome Paper Title",
            "url": "https://arxiv.org/abs/2401.99999",
        }
        entry.title_normalized = "awesome paper title"
        registry.get_entry.return_value = entry

        gen = DigestGenerator(tmp_output, registry=registry)
        papers = [_make_paper_audit(paper_id="2401.99999")]
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()

        assert "Awesome Paper Title" in text
        assert "https://arxiv.org/abs/2401.99999" in text

    def test_registry_falls_back_to_title_normalized(self, tmp_output: Path) -> None:
        # No metadata_snapshot -> title_normalized used.
        registry = MagicMock()
        entry = MagicMock()
        entry.metadata_snapshot = None
        entry.title_normalized = "fallback normalized title"
        registry.get_entry.return_value = entry

        gen = DigestGenerator(tmp_output, registry=registry)
        papers = [_make_paper_audit(paper_id="canon-uuid")]
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()
        assert "fallback normalized title" in text

    def test_registry_url_non_string_coerced(self, tmp_output: Path) -> None:
        registry = MagicMock()
        entry = MagicMock()

        # HttpUrl from pydantic returns a non-str object; fake it.
        class _FakeUrl:
            def __str__(self) -> str:
                return "https://example.com/x"

        url_obj = _FakeUrl()
        entry.metadata_snapshot = {"title": "T", "url": url_obj}
        entry.title_normalized = "t"
        registry.get_entry.return_value = entry

        gen = DigestGenerator(tmp_output, registry=registry)
        papers = [_make_paper_audit(paper_id="abc")]
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()
        # Assert the rendered text contains the URL via __str__ path.
        assert str(url_obj) in text
        assert "https://example.com/x" in text

    def test_registry_miss_falls_back_to_paper_id(self, tmp_output: Path) -> None:
        registry = MagicMock()
        registry.get_entry.return_value = None
        # Provider-id lookup also misses.
        state = MagicMock()
        state.provider_id_index = {}
        state.entries = {}
        registry.load.return_value = state

        gen = DigestGenerator(tmp_output, registry=registry)
        papers = [_make_paper_audit(paper_id="missing-id")]
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()
        assert "missing-id" in text

    def test_registry_provider_id_lookup_succeeds(self, tmp_output: Path) -> None:
        registry = MagicMock()
        registry.get_entry.return_value = None  # canonical lookup misses
        # Provider-id lookup finds it under "arxiv:2401.00001".
        entry = MagicMock()
        entry.metadata_snapshot = {"title": "Found Via Provider"}
        entry.title_normalized = "found via provider"
        state = MagicMock()
        state.provider_id_index = {"arxiv:2401.00001": "canon-uuid"}
        state.entries = {"canon-uuid": entry}
        registry.load.return_value = state

        gen = DigestGenerator(tmp_output, registry=registry)
        papers = [_make_paper_audit(paper_id="2401.00001")]
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()
        assert "Found Via Provider" in text

    def test_registry_provider_id_with_prefix_passed_through(
        self, tmp_output: Path
    ) -> None:
        # If the audit already has "arxiv:..." prefix, we look up that
        # exact key (no second "arxiv:arxiv:" attempt).
        registry = MagicMock()
        registry.get_entry.return_value = None
        entry = MagicMock()
        entry.metadata_snapshot = {"title": "Direct Hit"}
        entry.title_normalized = "direct hit"
        state = MagicMock()
        state.provider_id_index = {"arxiv:2401.00001": "canon-uuid"}
        state.entries = {"canon-uuid": entry}
        registry.load.return_value = state

        gen = DigestGenerator(tmp_output, registry=registry)
        papers = [_make_paper_audit(paper_id="arxiv:2401.00001")]
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()
        assert "Direct Hit" in text

    def test_registry_get_entry_exception_falls_back(self, tmp_output: Path) -> None:
        registry = MagicMock()
        registry.get_entry.side_effect = RuntimeError("registry unhealthy")

        gen = DigestGenerator(tmp_output, registry=registry)
        papers = [_make_paper_audit(paper_id="boom")]
        # Must not raise; falls back to paper_id.
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()
        assert "boom" in text

    def test_registry_load_exception_falls_back(self, tmp_output: Path) -> None:
        registry = MagicMock()
        registry.get_entry.return_value = None
        registry.load.side_effect = RuntimeError("disk busy")

        gen = DigestGenerator(tmp_output, registry=registry)
        papers = [_make_paper_audit(paper_id="boom2")]
        text = gen.generate(_make_run(papers=papers), _make_subscription()).read_text()
        assert "boom2" in text

    def test_lookup_by_provider_id_returns_none_with_no_registry(
        self, tmp_output: Path
    ) -> None:
        # Internal helper guard: if invoked without a registry, returns None.
        gen = DigestGenerator(tmp_output)
        assert gen._lookup_by_provider_id("anything") is None

    def test_lookup_by_provider_id_no_match_returns_none(
        self, tmp_output: Path
    ) -> None:
        registry = MagicMock()
        state = MagicMock()
        state.provider_id_index = {"arxiv:9999.99999": "uuid"}
        state.entries = {}  # entry removed
        registry.load.return_value = state

        gen = DigestGenerator(tmp_output, registry=registry)
        # Provider-id index hits but entries dict misses.
        assert gen._lookup_by_provider_id("9999.99999") is None


# ---------------------------------------------------------------------------
# Snapshot-style assertion
# ---------------------------------------------------------------------------


class TestRenderedSnapshot:
    """Locked-in markdown shape for a deterministic input."""

    def test_known_input_renders_expected_shape(self, tmp_output: Path) -> None:
        gen = DigestGenerator(tmp_output)
        sub = _make_subscription(
            subscription_id="sub-snapshot1",
            name="Snapshot Sub",
        )
        run = _make_run(
            run_id="run-snap1",
            subscription_id="sub-snapshot1",
            started_at=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
            finished_at=datetime(2026, 1, 2, 3, 5, tzinfo=timezone.utc),
            papers_seen=1,
            papers_new=1,
            papers=[
                _make_paper_audit(
                    paper_id="2401.00007",
                    relevance_score=0.77,
                    relevance_reasoning="Direct match on PEFT keyword.",
                    registered=True,
                )
            ],
        )
        text = gen.generate(run, sub).read_text()

        # Spot-check key invariants -- not byte-for-byte (the user_id /
        # other timestamps would over-couple the snapshot to today's
        # rendering). These pin the shape contract.
        assert text.startswith("---\n")
        assert "subscription_id: sub-snapshot1\n" in text
        assert "started_at: 2026-01-02T03:04:00+00:00\n" in text
        assert "## Top Papers\n\n1. **0.77** -- 2401.00007 (new)" in text
        assert "## Reasoning Highlights\n" in text
        assert "Direct match on PEFT keyword." in text
        assert "## Stats\n" in text
        assert text.endswith("\n")


# ---------------------------------------------------------------------------
# H-S4: ARISP_OUTPUT_ROOT env var sandbox
# ---------------------------------------------------------------------------


class TestOutputRootEnvVar:
    """H-S4: Env-var override for output root is accepted and traversal blocked."""

    def test_env_var_override_accepted(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ARISP_OUTPUT_ROOT allows a custom approved base."""
        custom_root = tmp_path / "custom_output"
        custom_root.mkdir()
        monkeypatch.setenv("ARISP_OUTPUT_ROOT", str(custom_root))

        gen = DigestGenerator(custom_root / "sub")
        # DigestGenerator should construct without error -- the env var
        # makes ``custom_root`` an approved base.
        assert gen is not None

    def test_env_var_traversal_still_blocked(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Setting ARISP_OUTPUT_ROOT does not allow paths outside it."""
        custom_root = tmp_path / "allowed"
        custom_root.mkdir()
        monkeypatch.setenv("ARISP_OUTPUT_ROOT", str(custom_root))
        # Try to escape to /etc (not under custom_root OR other approved bases)
        monkeypatch.chdir(str(tmp_path))  # ensure cwd/output is not /etc

        with pytest.raises(SecurityError):
            DigestGenerator(Path("/etc/malicious"))

    def test_structlog_monitoring_digest_written(
        self,
        tmp_output: Path,
    ) -> None:
        """H-T1: ``monitoring_digest_written`` is logged by DigestGenerator."""
        import structlog.testing

        gen = DigestGenerator(tmp_output)
        sub = _make_subscription()
        run = _make_run()
        with structlog.testing.capture_logs() as logs:
            gen.generate(run, sub)

        written_events = [
            e for e in logs if e.get("event") == "monitoring_digest_written"
        ]
        assert len(written_events) == 1
        assert written_events[0].get("run_id") == run.run_id
        assert written_events[0].get("subscription_id") == sub.subscription_id

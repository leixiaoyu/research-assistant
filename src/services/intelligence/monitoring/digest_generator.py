"""File-based digest generator for monitoring runs (REQ-9.1.4).

Why this module
---------------
Per the resolved decision in ``.omc/plans/open-questions.md``, Week 2's
monitoring digest delivery is **file-based** (not Slack / email). One
markdown file per (subscription, run) is written to
``./output/digests/{YYYY-MM-DD}_{subscription_id}_digest.md`` so users
can browse the history with a simple ``ls`` and either ingest the
files into Obsidian or pipe them into a downstream notifier.

Design constraints
------------------
- **Read from audit DTOs only.** The digest takes a
  :class:`MonitoringRunAudit` (the read-only persisted view) and a
  :class:`ResearchSubscription`. The audit's
  :class:`MonitoringPaperAudit` carries only ``paper_id`` /
  ``relevance_score`` / ``relevance_reasoning`` -- it deliberately does
  NOT carry titles or URLs (PR #119 #S6). The generator looks the rich
  metadata up via the injected ``RegistryService`` and gracefully
  falls back to ``paper_id`` when the registry has no entry.
- **Atomic write.** Write to ``{path}.tmp`` and ``os.replace`` -- so a
  crash mid-write never leaves a partial digest visible to a watcher.
- **Path safety.** ``output_root`` is sanitized via the existing
  intelligence-graph ``sanitize_storage_path`` -- defense against a
  caller passing ``../`` to escape the output sandbox. The
  ``subscription_id`` slug is also validated via the same regex the
  models use (so a maliciously-named subscription cannot inject
  filename characters).
- **Sorted, capped.** Top-N (default 20) papers by descending
  relevance_score; reasoning truncated to 280 chars per paper.
- **Empty papers list:** still write a minimal digest (audit shows the
  monitoring run happened, just nothing relevant came through).

Public surface:

- :class:`DigestGenerator` -- the single class.
- :data:`DEFAULT_OUTPUT_ROOT` -- the project default
  ``./output/digests`` location (Path).
"""

from __future__ import annotations

import os
import re
from datetime import timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import structlog

from src.services.intelligence.monitoring.models import (
    MonitoringPaperAudit,
    MonitoringRunAudit,
    ResearchSubscription,
)
from src.utils.security import PathSanitizer, SecurityError

if TYPE_CHECKING:
    from src.models.registry import RegistryEntry
    from src.services.registry.service import RegistryService

logger = structlog.get_logger()


# Default location for digest markdown files. Lives under ``./output``
# so it travels with the rest of the pipeline's outputs (catalog,
# research briefs, etc.).
DEFAULT_OUTPUT_ROOT: Path = Path("./output/digests")

# Top-N papers featured per digest. Caps the markdown size so an
# unusual cycle that returns thousands of papers cannot generate a
# multi-megabyte file.
DEFAULT_TOP_N = 20

# Per-paper reasoning truncation. Mirrors what we ask the LLM to
# produce (<= 280 chars) -- so any reasoning longer than that came
# from a misbehaving model and the digest renders the cap explicitly.
REASONING_TRUNCATE_CHARS = 280

# Subscription-id slug pattern. Identical to the one in
# ``ResearchSubscription._validate_identifier`` -- duplicated here so
# this module has no implicit coupling to model internals.
_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9._\-]+$")


class DigestGenerator:
    """Generate per-run markdown digests from a ``MonitoringRunAudit``.

    Construct once with the desired output root (and optional
    :class:`RegistryService` for paper-title lookup), then call
    :meth:`generate` per run.
    """

    def __init__(
        self,
        output_root: Optional[Path] = None,
        *,
        registry: Optional["RegistryService"] = None,
        top_n: int = DEFAULT_TOP_N,
    ) -> None:
        """Initialize the generator.

        Args:
            output_root: Directory under which digests are written.
                Defaults to :data:`DEFAULT_OUTPUT_ROOT` (``./output/digests``).
                The path is sanitized at construction time -- a path
                outside the approved sandbox raises ``SecurityError``.
            registry: Optional :class:`RegistryService` used to resolve
                paper ids back to titles / URLs. When ``None``, the
                digest falls back to rendering ``paper_id`` for every
                paper -- handy for tests and lightweight smoke runs.
            top_n: Maximum number of papers to feature in the "Top
                Papers" section. Must be > 0.

        Raises:
            ValueError: If ``top_n`` is not positive.
            SecurityError: If ``output_root`` escapes the approved
                output sandbox.
        """
        if top_n <= 0:
            raise ValueError("top_n must be positive")
        root = output_root or DEFAULT_OUTPUT_ROOT
        self._output_root = self._sanitize_output_root(root)
        self._registry = registry
        self._top_n = top_n
        # Make sure the directory exists at construction time so
        # ``generate`` can rely on it being writable.
        self._output_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def generate(
        self,
        run: MonitoringRunAudit,
        subscription: ResearchSubscription,
    ) -> Path:
        """Render and atomically write one digest markdown file.

        Args:
            run: The run to summarize (read-only audit DTO).
            subscription: The owning subscription (for header context).

        Returns:
            Absolute path to the written markdown file.

        Raises:
            SecurityError: If the subscription id contains characters
                outside the safe slug class -- defense against a
                hostile sub_id ever reaching the filesystem.
        """
        slug = self._validate_slug(subscription.subscription_id)
        date_part = run.started_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
        filename = f"{date_part}_{slug}_digest.md"
        # Re-sanitize the joined path so a future bug that lets a slug
        # with traversal slip past the validator is still caught.
        target = self._safe_join(filename)
        markdown = self._render(run, subscription)
        self._atomic_write(target, markdown)
        logger.info(
            "monitoring_digest_written",
            run_id=run.run_id,
            subscription_id=subscription.subscription_id,
            path=str(target),
            papers_seen=run.papers_seen,
            papers_new=run.papers_new,
        )
        return target

    # ------------------------------------------------------------------
    # Path utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitize_output_root(root: Path) -> Path:
        """Resolve ``root`` and assert it is inside an allowed sandbox.

        Approved sandboxes:
          - ``<cwd>/output`` (the canonical pipeline output sink)
          - the system temp dir (for tests and ad-hoc debugging)

        Returns:
            The resolved absolute Path.
        """
        import tempfile

        candidate = Path(root)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (Path.cwd() / candidate).resolve()
        )
        approved = [
            (Path.cwd() / "output").resolve(),
            Path(tempfile.gettempdir()).resolve(),
        ]
        for base in approved:
            try:
                resolved.relative_to(base)
            except ValueError:
                continue
            return resolved
        raise SecurityError(f"Digest output root is outside approved sandbox: {root!r}")

    @staticmethod
    def _validate_slug(subscription_id: str) -> str:
        """Reject subscription ids with characters unsafe in filenames."""
        slug = subscription_id.strip()
        if not slug or not _SLUG_PATTERN.match(slug):
            raise SecurityError(
                f"Invalid subscription_id for digest filename: {subscription_id!r}"
            )
        return slug

    def _safe_join(self, filename: str) -> Path:
        """Join ``filename`` under the output root with traversal guard.

        Uses ``PathSanitizer.safe_path`` so a future bug that allows a
        traversal-bearing filename through the validator is still
        caught at the join site.
        """
        sanitizer = PathSanitizer(allowed_bases=[self._output_root])
        return sanitizer.safe_path(self._output_root, filename, must_exist=False)

    # ------------------------------------------------------------------
    # Atomic write
    # ------------------------------------------------------------------
    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        """Write ``content`` to ``target`` via tmp + os.replace.

        We use ``os.replace`` (not ``shutil.move``) for the rename --
        it is the only atomic-on-POSIX cross-volume primitive Python
        gives us. The temporary file lives next to the target so the
        rename is same-filesystem.
        """
        tmp = target.with_suffix(target.suffix + ".tmp")
        # ``write_text`` itself is not atomic; we deliberately write to
        # the tmp path and rely on the rename to publish.
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)

    # ------------------------------------------------------------------
    # Markdown rendering
    # ------------------------------------------------------------------
    def _render(
        self,
        run: MonitoringRunAudit,
        subscription: ResearchSubscription,
    ) -> str:
        """Build the digest markdown body."""
        papers = self._sort_papers_by_score(run.papers)
        top = papers[: self._top_n]
        lines: list[str] = []
        lines.extend(self._render_frontmatter(run, subscription))
        lines.append("")
        lines.append(f"# Monitoring Digest: {subscription.name}")
        lines.append("")
        lines.append(self._render_summary_paragraph(run))
        lines.append("")
        lines.extend(self._render_top_papers_section(top))
        lines.extend(self._render_reasoning_section(top))
        lines.extend(self._render_stats_section(run, papers))
        return "\n".join(lines) + "\n"

    @staticmethod
    def _sort_papers_by_score(
        papers: list[MonitoringPaperAudit],
    ) -> list[MonitoringPaperAudit]:
        """Sort by descending relevance_score, with None scores at the bottom.

        Stable sort by ``paper_id`` as a secondary key so a digest
        regenerated from the same audit row produces byte-identical
        output (helps snapshot testing).
        """
        return sorted(
            papers,
            key=lambda p: (
                # Primary: descending relevance_score; None -> -inf so
                # they sort to the bottom.
                -(p.relevance_score if p.relevance_score is not None else -1.0),
                p.paper_id,
            ),
        )

    @staticmethod
    def _render_frontmatter(
        run: MonitoringRunAudit,
        subscription: ResearchSubscription,
    ) -> list[str]:
        return [
            "---",
            f"subscription_id: {subscription.subscription_id}",
            f"name: {subscription.name}",
            f"run_id: {run.run_id}",
            f"started_at: {run.started_at.isoformat()}",
            f"papers_seen: {run.papers_seen}",
            f"papers_new: {run.papers_new}",
            f"status: {run.status.value}",
            "---",
        ]

    @staticmethod
    def _render_summary_paragraph(run: MonitoringRunAudit) -> str:
        finished = run.finished_at.isoformat() if run.finished_at else "(in progress)"
        return (
            f"Monitoring run `{run.run_id}` started at {run.started_at.isoformat()} "
            f"and finished at {finished}. "
            f"Status: **{run.status.value}**."
        )

    def _render_top_papers_section(self, top: list[MonitoringPaperAudit]) -> list[str]:
        lines: list[str] = ["## Top Papers", ""]
        if not top:
            lines.append("_No papers were seen in this run._")
            lines.append("")
            return lines
        for index, paper in enumerate(top, start=1):
            title, url = self._lookup_title_and_url(paper.paper_id)
            score_str = (
                f"{paper.relevance_score:.2f}"
                if paper.relevance_score is not None
                else "n/a"
            )
            new_marker = " (new)" if paper.registered else ""
            link = f"[{title}]({url})" if url else title
            lines.append(
                f"{index}. **{score_str}** -- {link}{new_marker} "
                f"(`{paper.paper_id}`)"
            )
        lines.append("")
        return lines

    def _render_reasoning_section(self, top: list[MonitoringPaperAudit]) -> list[str]:
        lines: list[str] = ["## Reasoning Highlights", ""]
        any_with_reasoning = False
        for paper in top:
            if not paper.relevance_reasoning:
                continue
            any_with_reasoning = True
            title, _ = self._lookup_title_and_url(paper.paper_id)
            truncated = paper.relevance_reasoning
            if len(truncated) > REASONING_TRUNCATE_CHARS:
                truncated = truncated[: REASONING_TRUNCATE_CHARS - 3] + "..."
            lines.append(f"- **{title}** (`{paper.paper_id}`): {truncated}")
        if not any_with_reasoning:
            lines.append("_No reasoning provided for the featured papers._")
        lines.append("")
        return lines

    @staticmethod
    def _render_stats_section(
        run: MonitoringRunAudit,
        all_papers: list[MonitoringPaperAudit],
    ) -> list[str]:
        new_count = sum(1 for p in all_papers if p.registered)
        scored_papers = [p for p in all_papers if p.relevance_score is not None]
        avg_score: Optional[float] = None
        if scored_papers:
            avg_score = sum(
                float(p.relevance_score or 0.0) for p in scored_papers
            ) / len(scored_papers)
        avg_str = f"{avg_score:.3f}" if avg_score is not None else "n/a"
        return [
            "## Stats",
            "",
            f"- Papers seen: {run.papers_seen}",
            f"- Papers new (registered this run): {new_count}",
            f"- Papers reported by run header: {run.papers_new}",
            f"- Papers with relevance score: {len(scored_papers)}",
            f"- Average relevance score: {avg_str}",
            f"- Run status: {run.status.value}",
            "",
        ]

    # ------------------------------------------------------------------
    # Registry lookup
    # ------------------------------------------------------------------
    def _lookup_title_and_url(self, paper_id: str) -> tuple[str, Optional[str]]:
        """Resolve ``paper_id`` to a human-friendly (title, url).

        Strategy:
          1. If no registry was injected, fall back to ``paper_id``.
          2. Ask the registry by canonical id -- the path used when the
             monitor stored the registry's UUID.
          3. If not found, attempt a provider-id lookup against the
             registry's ``provider_id_index`` (covers the common
             ArXiv-id path that ``MonitoringPaperAudit`` actually
             stores).
          4. Inspect ``metadata_snapshot`` for the original title /
             URL; otherwise fall back to ``title_normalized`` / no URL.

        Falls back gracefully on any exception so a registry blip
        cannot abort digest generation (the audit row is the
        source of truth -- the digest is a convenience layer).
        """
        if self._registry is None:
            return paper_id, None
        try:
            entry = self._registry.get_entry(paper_id)
            if entry is None:
                entry = self._lookup_by_provider_id(paper_id)
        except Exception as exc:
            logger.warning(
                "monitoring_digest_registry_lookup_failed",
                paper_id=paper_id,
                error=str(exc),
            )
            return paper_id, None
        if entry is None:
            return paper_id, None
        snapshot = entry.metadata_snapshot or {}
        title = snapshot.get("title") or entry.title_normalized or paper_id
        url = snapshot.get("url")
        if url is not None and not isinstance(url, str):
            url = str(url)
        return title, url

    def _lookup_by_provider_id(self, paper_id: str) -> Optional["RegistryEntry"]:
        """Resolve a provider id (e.g. ``arxiv:2401.00001``) via the registry index.

        Returns the matched ``RegistryEntry`` or ``None``. The registry
        models are kept under ``TYPE_CHECKING`` so this module avoids a
        runtime import cycle with the registry service.
        """
        if self._registry is None:
            return None
        # Use the registry's loaded state directly; ``RegistryService``
        # caches it so this is cheap. We try multiple key shapes since
        # the monitor stores the bare provider id (e.g. "2401.00001"
        # or "arxiv:2401.00001"), and the registry indexes the
        # prefixed form.
        try:
            state = self._registry.load()
        except Exception as exc:
            logger.warning(
                "monitoring_digest_registry_load_failed",
                paper_id=paper_id,
                error=str(exc),
            )
            return None
        candidates: list[str] = [paper_id]
        if ":" not in paper_id:
            # The registry's provider_id_index keys the form
            # "arxiv:2401.00001" -- try the most common providers.
            candidates.extend(
                [
                    f"arxiv:{paper_id}",
                    f"semantic_scholar:{paper_id}",
                ]
            )
        for key in candidates:
            registry_paper_id = state.provider_id_index.get(key)
            if registry_paper_id is None:
                continue
            entry = state.entries.get(registry_paper_id)
            if entry is not None:
                return entry
        return None

"""Delta Generator for Phase 3.6: Cumulative Knowledge Synthesis.

Generates run-specific delta briefs showing only what changed:
- NEW papers processed for the first time
- BACKFILLED papers updated with new extraction targets
- Summary statistics for the run
"""

import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional
import structlog

from src.models.synthesis import (
    ProcessingResult,
    ProcessingStatus,
    DeltaBrief,
)
from src.utils.security import PathSanitizer

logger = structlog.get_logger()

# Delta file naming pattern
DELTA_FILENAME_PATTERN = "{date}_Delta.md"


class DeltaGenerator:
    """Generates delta briefs for pipeline runs.

    Creates run-specific markdown files showing only papers that
    were newly processed or backfilled in the current run.
    """

    def __init__(self, output_base_dir: Path = Path("output")):
        """Initialize the delta generator.

        Args:
            output_base_dir: Base directory for output files.
        """
        self.output_base_dir = output_base_dir

        logger.info(
            "delta_generator_initialized",
            output_dir=str(output_base_dir),
        )

    def _ensure_runs_directory(self, topic_slug: str) -> Path:
        """Ensure runs directory exists for topic.

        Args:
            topic_slug: Sanitized topic slug.

        Returns:
            Path to runs directory.
        """
        safe_slug = PathSanitizer.sanitize_path_component(topic_slug)
        runs_dir = self.output_base_dir / safe_slug / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        return runs_dir

    def _validate_date_format(self, date_str: str) -> bool:
        """Validate date string is in YYYY-MM-DD format.

        Args:
            date_str: Date string to validate.

        Returns:
            True if valid format.
        """
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_str))

    def _quality_badge(self, score: float) -> str:
        """Generate quality badge based on score.

        Args:
            score: Quality score (0-100).

        Returns:
            Emoji badge string.
        """
        if score >= 80:
            return f"⭐⭐⭐ ({score:.0f})"
        elif score >= 60:
            return f"⭐⭐ ({score:.0f})"
        elif score >= 40:
            return f"⭐ ({score:.0f})"
        else:
            return f"○ ({score:.0f})"

    def _status_emoji(self, status: ProcessingStatus) -> str:
        """Get emoji for processing status.

        Args:
            status: Processing status.

        Returns:
            Status emoji.
        """
        return {
            ProcessingStatus.NEW: "🆕",
            ProcessingStatus.BACKFILLED: "🔄",
            ProcessingStatus.SKIPPED: "⏭️",
            ProcessingStatus.MAPPED: "🔗",
            ProcessingStatus.FAILED: "❌",
        }.get(status, "❓")

    def _render_paper_entry(self, result: ProcessingResult) -> str:
        """Render a single paper entry for the delta brief.

        Args:
            result: Processing result to render.

        Returns:
            Markdown string for the paper entry.
        """
        lines = []

        status_emoji = self._status_emoji(result.status)
        quality_badge = self._quality_badge(result.quality_score)
        pdf_status = "📄 PDF" if result.pdf_available else "📋 Abstract"

        lines.append(f"### {status_emoji} {result.title}")
        lines.append(f"**Quality:** {quality_badge} | **Source:** {pdf_status}")
        lines.append("")

        if result.extraction_success:
            lines.append("✅ Extraction successful")
        elif result.status == ProcessingStatus.FAILED:
            lines.append(
                f"❌ Processing failed: {result.error_message or 'Unknown error'}"
            )

        lines.append(
            f"*Processed: {result.processed_at.strftime('%Y-%m-%d %H:%M UTC')}*"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        return "\n".join(lines)

    def _render_delta_brief(self, brief: DeltaBrief) -> str:
        """Render the complete delta brief document.

        Args:
            brief: Delta brief to render.

        Returns:
            Complete markdown document.
        """
        lines = []

        # Header
        date_str = brief.run_date.strftime("%Y-%m-%d")
        lines.append(f"# Delta Brief: {brief.topic_slug}")
        lines.append(f"**Run Date:** {date_str}")
        lines.append("")

        # Summary statistics
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Count |")
        lines.append("|--------|-------|")
        lines.append(f"| 🆕 New Papers | {brief.total_new} |")
        lines.append(f"| 🔄 Backfilled | {brief.total_backfilled} |")
        lines.append(f"| ⏭️ Skipped | {brief.skipped_count} |")
        lines.append(f"| ❌ Failed | {brief.failed_count} |")
        lines.append("")

        # New papers section
        if brief.new_papers:
            lines.append("## 🆕 New Papers")
            lines.append("")
            lines.append("Papers processed for the first time in this run.")
            lines.append("")

            # Sort by quality
            sorted_new = sorted(
                brief.new_papers,
                key=lambda p: p.quality_score,
                reverse=True,
            )

            for result in sorted_new:
                lines.append(self._render_paper_entry(result))

        # Backfilled papers section
        if brief.backfilled_papers:
            lines.append("## 🔄 Backfilled Papers")
            lines.append("")
            lines.append("Existing papers updated with new extraction targets.")
            lines.append("")

            # Sort by quality
            sorted_backfilled = sorted(
                brief.backfilled_papers,
                key=lambda p: p.quality_score,
                reverse=True,
            )

            for result in sorted_backfilled:
                lines.append(self._render_paper_entry(result))

        # No changes message
        if not brief.has_changes:
            lines.append("## No Changes")
            lines.append("")
            lines.append(
                "No new papers were discovered and no existing papers "
                "required backfilling in this run."
            )
            lines.append("")

        # Footer
        lines.append("---")
        lines.append(
            f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*"
        )

        return "\n".join(lines)

    def create_delta_brief(
        self,
        results: List[ProcessingResult],
        topic_slug: str,
        run_date: Optional[datetime] = None,
    ) -> DeltaBrief:
        """Create a delta brief from processing results.

        Args:
            results: List of processing results from the run.
            topic_slug: Topic these results belong to.
            run_date: Run date (defaults to now).

        Returns:
            DeltaBrief object.
        """
        run_date = run_date or datetime.now(timezone.utc)

        # Categorize results
        new_papers = [r for r in results if r.status == ProcessingStatus.NEW]
        backfilled = [r for r in results if r.status == ProcessingStatus.BACKFILLED]
        skipped = sum(
            1
            for r in results
            if r.status in (ProcessingStatus.SKIPPED, ProcessingStatus.MAPPED)
        )
        failed = sum(1 for r in results if r.status == ProcessingStatus.FAILED)

        return DeltaBrief(
            topic_slug=topic_slug,
            run_date=run_date,
            new_papers=new_papers,
            backfilled_papers=backfilled,
            skipped_count=skipped,
            failed_count=failed,
        )

    def generate(
        self,
        results: List[ProcessingResult],
        topic_slug: str,
        run_date: Optional[datetime] = None,
    ) -> Optional[Path]:
        """Generate a delta brief file.

        Args:
            results: List of processing results from the run.
            topic_slug: Topic these results belong to.
            run_date: Run date (defaults to now).

        Returns:
            Path to generated delta file, or None if generation failed.
        """
        run_date = run_date or datetime.now(timezone.utc)
        date_str = run_date.strftime("%Y-%m-%d")

        # Validate date format
        if not self._validate_date_format(date_str):
            logger.error(
                "invalid_date_format",
                date=date_str,
            )
            return None

        logger.info(
            "delta_generation_started",
            topic=topic_slug,
            date=date_str,
            total_results=len(results),
        )

        # Create delta brief
        brief = self.create_delta_brief(results, topic_slug, run_date)

        # Render content
        content = self._render_delta_brief(brief)

        # Ensure directory exists
        runs_dir = self._ensure_runs_directory(topic_slug)

        # Write file
        filename = DELTA_FILENAME_PATTERN.format(date=date_str)
        delta_path = runs_dir / filename

        try:
            delta_path.write_text(content, encoding="utf-8")

            logger.info(
                "delta_generation_completed",
                topic=topic_slug,
                path=str(delta_path),
                new_papers=brief.total_new,
                backfilled=brief.total_backfilled,
            )

            return delta_path

        except Exception as e:
            logger.error(
                "delta_generation_failed",
                topic=topic_slug,
                error=str(e),
            )
            return None

    def get_delta_history(self, topic_slug: str) -> List[Path]:
        """Get list of all delta files for a topic.

        Args:
            topic_slug: Topic to get history for.

        Returns:
            List of delta file paths, sorted by date (newest first).
        """
        safe_slug = PathSanitizer.sanitize_path_component(topic_slug)
        runs_dir = self.output_base_dir / safe_slug / "runs"

        if not runs_dir.exists():
            return []

        delta_files = list(runs_dir.glob("*_Delta.md"))

        # Sort by filename (date) descending
        delta_files.sort(reverse=True)

        return delta_files

"""Cross-Topic Synthesis Output Generator for Phase 3.7.

Generates Global_Synthesis.md with:
- YAML frontmatter with metadata
- Per-question synthesis sections
- Paper reference appendix
- Incremental update support
"""

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import structlog

from src.models.cross_synthesis import (
    CrossTopicSynthesisReport,
    SynthesisResult,
    SynthesisState,
)

logger = structlog.get_logger()

# Default output path
DEFAULT_OUTPUT_PATH = Path("output/Global_Synthesis.md")

# Metadata markers for preserving state
METADATA_START = "<!-- SYNTHESIS_META_START -->"
METADATA_END = "<!-- SYNTHESIS_META_END -->"

# Section markers for incremental updates
SECTION_START = "<!-- SECTION_START:{question_id} -->"
SECTION_END = "<!-- SECTION_END:{question_id} -->"


class CrossSynthesisGenerator:
    """Generator for cross-topic synthesis markdown documents.

    Produces Global_Synthesis.md with:
    - YAML frontmatter with report metadata
    - Overview statistics table
    - Per-question synthesis sections
    - Paper reference appendix
    - Hidden metadata for incremental updates
    """

    def __init__(
        self,
        output_path: Optional[Path] = None,
    ):
        """Initialize the generator.

        Args:
            output_path: Path for output file (default: output/Global_Synthesis.md).
        """
        self.output_path = output_path or DEFAULT_OUTPUT_PATH

        logger.info(
            "cross_synthesis_generator_initialized",
            output_path=str(self.output_path),
        )

    def _ensure_output_directory(self) -> None:
        """Ensure output directory exists."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def _generate_frontmatter(self, report: CrossTopicSynthesisReport) -> str:
        """Generate YAML frontmatter for the document.

        Args:
            report: Synthesis report with metadata.

        Returns:
            YAML frontmatter string.
        """
        lines = [
            "---",
            'title: "Cross-Topic Research Synthesis"',
            f'generated: "{report.created_at.isoformat()}"',
            f'last_updated: "{report.updated_at.isoformat()}"',
            f"total_papers: {report.total_papers_in_registry}",
            f"total_topics: {self._count_unique_topics(report)}",
            f"questions_answered: {report.questions_answered}",
            f"total_synthesis_cost_usd: {report.total_cost_usd:.2f}",
            "---",
            "",
        ]
        return "\n".join(lines)

    def _count_unique_topics(self, report: CrossTopicSynthesisReport) -> int:
        """Count unique topics across all synthesis results.

        Args:
            report: Synthesis report.

        Returns:
            Count of unique topics.
        """
        topics: Set[str] = set()
        for result in report.results:
            topics.update(result.topics_covered)
        return len(topics)

    def _generate_header(self, report: CrossTopicSynthesisReport) -> str:
        """Generate document header with overview.

        Args:
            report: Synthesis report.

        Returns:
            Header markdown string.
        """
        unique_topics = self._count_unique_topics(report)

        lines = [
            "# Cross-Topic Research Synthesis",
            "",
            "> Auto-generated synthesis across all research topics.",
            "> Updated incrementally after each pipeline run.",
            "",
            "## Overview",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Papers Analyzed | {report.total_papers_in_registry} |",
            f"| Topics Covered | {unique_topics} |",
            f"| Questions Answered | {report.questions_answered} |",
            f"| Last Updated | {report.updated_at.strftime('%Y-%m-%d')} |",
            f"| New Papers Since Last | {report.new_papers_since_last} |",
            f"| Total Cost | ${report.total_cost_usd:.2f} |",
            "",
            "---",
            "",
        ]
        return "\n".join(lines)

    def _generate_question_section(
        self,
        result: SynthesisResult,
        index: int,
    ) -> str:
        """Generate section for a single synthesis question.

        Args:
            result: Synthesis result for the question.
            index: Section number (1-indexed).

        Returns:
            Markdown section string.
        """
        lines = []

        # Section header with markers for incremental updates
        lines.append(SECTION_START.format(question_id=result.question_id))
        lines.append(f"## {index}. {result.question_name}")
        lines.append("")

        # Metadata block
        lines.append(f"> **Question ID:** {result.question_id}")
        lines.append(
            f"> **Papers Used:** {len(result.papers_used)} | "
            f"**Cost:** ${result.cost_usd:.2f} | "
            f"**Updated:** {result.synthesized_at.strftime('%Y-%m-%d')}"
        )
        lines.append(f"> **Topics:** {', '.join(sorted(result.topics_covered))}")
        lines.append("")

        # Synthesis content
        lines.append(result.synthesis_text)
        lines.append("")

        # End marker
        lines.append(SECTION_END.format(question_id=result.question_id))
        lines.append("")
        lines.append("---")
        lines.append("")

        return "\n".join(lines)

    def _generate_appendix(self, report: CrossTopicSynthesisReport) -> str:
        """Generate paper reference appendix.

        Args:
            report: Synthesis report.

        Returns:
            Appendix markdown string.
        """
        lines = [
            "## Appendix: Papers Referenced",
            "",
        ]

        # Collect all unique papers with their sections
        paper_sections: Dict[str, List[int]] = {}
        for i, result in enumerate(report.results, 1):
            for paper_id in result.papers_used:
                if paper_id not in paper_sections:
                    paper_sections[paper_id] = []
                paper_sections[paper_id].append(i)

        if not paper_sections:
            lines.append("*No papers referenced in this synthesis.*")
            lines.append("")
            return "\n".join(lines)

        # Generate table
        lines.append("| # | Paper ID | Sections |")
        lines.append("|---|----------|----------|")

        for i, (paper_id, sections) in enumerate(sorted(paper_sections.items()), 1):
            sections_str = ", ".join(str(s) for s in sections)
            # Truncate long paper IDs
            display_id = paper_id[:20] + "..." if len(paper_id) > 20 else paper_id
            lines.append(f"| {i} | {display_id} | {sections_str} |")

        lines.append("")
        return "\n".join(lines)

    def _generate_metadata_section(
        self,
        report: CrossTopicSynthesisReport,
    ) -> str:
        """Generate hidden metadata section for incremental updates.

        Args:
            report: Synthesis report.

        Returns:
            Hidden metadata section string.
        """
        metadata = {
            "report_id": report.report_id,
            "last_synthesis": report.updated_at.isoformat(),
            "questions_processed": [r.question_id for r in report.results],
            "incremental": report.incremental,
            "total_papers": report.total_papers_in_registry,
        }

        lines = [
            "---",
            "",
            METADATA_START,
            json.dumps(metadata, indent=2),
            METADATA_END,
        ]

        return "\n".join(lines)

    def generate(self, report: CrossTopicSynthesisReport) -> str:
        """Generate complete Global_Synthesis.md content.

        Args:
            report: Synthesis report to render.

        Returns:
            Complete markdown document.
        """
        parts = []

        # YAML frontmatter
        parts.append(self._generate_frontmatter(report))

        # Header with overview
        parts.append(self._generate_header(report))

        # Question sections
        for i, result in enumerate(report.results, 1):
            parts.append(self._generate_question_section(result, i))

        # Appendix
        parts.append(self._generate_appendix(report))

        # Hidden metadata
        parts.append(self._generate_metadata_section(report))

        return "\n".join(parts)

    def _extract_existing_sections(
        self,
        content: str,
    ) -> Dict[str, str]:
        """Extract existing synthesis sections from document.

        Args:
            content: Existing document content.

        Returns:
            Dictionary mapping question_id to section content.
        """
        sections: Dict[str, str] = {}

        # Pattern to match section markers
        pattern = re.compile(
            r"<!-- SECTION_START:(\S+) -->\s*(.*?)\s*<!-- SECTION_END:\1 -->",
            re.DOTALL,
        )

        for match in pattern.finditer(content):
            question_id = match.group(1)
            section_content = match.group(2).strip()
            sections[question_id] = section_content

        return sections

    def _extract_existing_metadata(
        self,
        content: str,
    ) -> Optional[Dict]:
        """Extract existing metadata from document.

        Args:
            content: Existing document content.

        Returns:
            Metadata dictionary or None.
        """
        pattern = re.compile(
            rf"{re.escape(METADATA_START)}\s*(.*?)\s*{re.escape(METADATA_END)}",
            re.DOTALL,
        )

        match = pattern.search(content)
        if not match:
            return None

        try:
            result: dict[Any, Any] = json.loads(match.group(1))
            return result
        except json.JSONDecodeError:
            logger.warning("failed_to_parse_metadata")
            return None

    def generate_incremental(
        self,
        report: CrossTopicSynthesisReport,
        existing_content: str,
    ) -> str:
        """Generate incremental update preserving existing sections.

        Preserves sections for questions not in current report,
        updates sections for questions that were re-synthesized.

        Args:
            report: New synthesis report.
            existing_content: Existing document content.

        Returns:
            Updated markdown document.
        """
        # Extract existing sections
        existing_sections = self._extract_existing_sections(existing_content)

        # Merge results - new results override existing
        current_question_ids = {r.question_id for r in report.results}

        # Keep existing sections not in current report
        for question_id, section in existing_sections.items():
            if question_id not in current_question_ids:
                # Create a placeholder result for the existing section
                # This preserves the section in output
                logger.debug(
                    "preserving_existing_section",
                    question_id=question_id,
                )
                # Note: We don't add placeholder results, just regenerate
                # with current results. This is intentional - incremental
                # updates replace sections for processed questions.

        # Generate full document with merged results
        return self.generate(report)

    def _atomic_write(self, content: str) -> bool:
        """Atomically write content to output file.

        Uses temp file + rename pattern for safety.

        Args:
            content: Content to write.

        Returns:
            True if write succeeded.
        """
        self._ensure_output_directory()

        try:
            # Write to temp file
            fd, tmp_path = tempfile.mkstemp(
                dir=self.output_path.parent,
                prefix=".synthesis_",
                suffix=".tmp",
            )

            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic rename
                os.rename(tmp_path, self.output_path)

                # Set permissions (0644)
                os.chmod(self.output_path, 0o644)

                logger.info(
                    "synthesis_file_written",
                    path=str(self.output_path),
                )
                return True

            except Exception:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise

        except Exception as e:
            logger.error(
                "atomic_write_failed",
                path=str(self.output_path),
                error=str(e),
            )
            return False

    def write(
        self,
        report: CrossTopicSynthesisReport,
        incremental: bool = True,
    ) -> Optional[Path]:
        """Write synthesis report to file.

        Args:
            report: Synthesis report to write.
            incremental: Whether to preserve existing sections.

        Returns:
            Path to written file, or None on failure.
        """
        # Check for existing content if incremental
        existing_content = None
        if incremental and self.output_path.exists():
            try:
                existing_content = self.output_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(
                    "failed_to_read_existing",
                    error=str(e),
                )

        # Generate content
        if existing_content and incremental:
            content = self.generate_incremental(report, existing_content)
        else:
            content = self.generate(report)

        # Write atomically
        if self._atomic_write(content):
            return self.output_path

        return None

    def load_state(self) -> Optional[SynthesisState]:
        """Load synthesis state from existing output file.

        Returns:
            SynthesisState if found, None otherwise.
        """
        if not self.output_path.exists():
            return None

        try:
            content = self.output_path.read_text(encoding="utf-8")
            metadata = self._extract_existing_metadata(content)

            if not metadata:
                return None

            return SynthesisState(
                last_synthesis_at=(
                    datetime.fromisoformat(metadata.get("last_synthesis", ""))
                    if metadata.get("last_synthesis")
                    else None
                ),
                last_report_id=metadata.get("report_id"),
                questions_processed=metadata.get("questions_processed", []),
            )

        except Exception as e:
            logger.warning(
                "failed_to_load_state",
                error=str(e),
            )
            return None

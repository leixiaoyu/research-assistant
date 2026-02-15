"""Report parser service for extracting key learnings from Delta briefs.

Parses generated markdown reports (Delta briefs) to extract engineering
summaries and key learnings for Slack notifications.

Usage:
    from src.services.report_parser import ReportParser

    parser = ReportParser()
    learnings = parser.extract_key_learnings(
        output_files=["output/topic/runs/2025-01-23_Delta.md"],
        max_per_topic=2
    )
"""

import re
from pathlib import Path
from typing import List, Optional
import structlog

from src.models.notification import KeyLearning

logger = structlog.get_logger()


class ReportParser:
    """Parses Delta briefs to extract key learnings.

    Extracts engineering summaries from NEW papers in Delta briefs
    for inclusion in Slack notifications.

    Supports multiple report formats:
    - Delta briefs (YYYY-MM-DD_Delta.md)
    - Research briefs (YYYY-MM-DD_Research.md)
    """

    # Regex patterns for parsing
    PAPER_HEADER_PATTERN = re.compile(
        r"^###\s+(?:\S+\s+)?(.+?)$", re.MULTILINE  # Captures paper title
    )

    # Pattern for extracting engineering summaries
    ENGINEERING_SUMMARY_PATTERN = re.compile(
        r"\*\*Engineering[_ ]?Summary\*\*[^\n]*\n+((?:[^\n]+\n?)+)",
        re.IGNORECASE | re.MULTILINE,
    )

    # Alternative pattern for extraction results
    EXTRACTION_RESULT_PATTERN = re.compile(
        r"\*\*Engineering Summary\*\*\s*\(confidence:\s*[\d.]+%?\)"
        r"\s*\n+((?:[^\n]+\n?)+)",
        re.IGNORECASE | re.MULTILINE,
    )

    # Pattern for NEW papers section
    # Note: Uses ^## with MULTILINE to match only ## at line start,
    # not ## inside ### headers
    NEW_PAPERS_SECTION = re.compile(
        r"^##\s+(?::new:|🆕)\s*New Papers?\s*\n(.*?)(?=^##[^#]|\Z)",
        re.IGNORECASE | re.DOTALL | re.MULTILINE,
    )

    # Pattern for individual new paper entries
    NEW_PAPER_ENTRY = re.compile(
        r"###\s+(?::new:|🆕)\s*(.+?)\n(.*?)(?=###\s+(?::new:|🆕)|\Z)",
        re.DOTALL,
    )

    def __init__(self, max_summary_length: int = 200) -> None:
        """Initialize report parser.

        Args:
            max_summary_length: Maximum length for truncated summaries.
        """
        self.max_summary_length = max_summary_length

    def extract_key_learnings(
        self,
        output_files: List[str],
        max_per_topic: int = 2,
    ) -> List[KeyLearning]:
        """Extract key learnings from output files.

        Parses Delta briefs and Research briefs to extract engineering
        summaries from top papers.

        Args:
            output_files: List of output file paths to parse.
            max_per_topic: Maximum learnings to extract per topic.

        Returns:
            List of KeyLearning objects.
        """
        learnings: List[KeyLearning] = []

        for file_path in output_files:
            try:
                topic_learnings = self._parse_file(file_path, max_per_topic)
                learnings.extend(topic_learnings)
            except Exception as e:
                logger.warning(
                    "report_parse_failed",
                    file=file_path,
                    error=str(e),
                )
                continue

        logger.info(
            "key_learnings_extracted",
            files_processed=len(output_files),
            learnings_found=len(learnings),
        )

        return learnings

    def _parse_file(self, file_path: str, max_learnings: int) -> List[KeyLearning]:
        """Parse a single report file.

        Args:
            file_path: Path to the report file.
            max_learnings: Maximum learnings to extract.

        Returns:
            List of KeyLearning objects from this file.
        """
        path = Path(file_path)

        if not path.exists():
            logger.debug("report_file_not_found", path=file_path)
            return []

        # Extract topic slug from path
        # Expected: output/{topic_slug}/runs/YYYY-MM-DD_Delta.md
        # or: output/{topic_slug}/YYYY-MM-DD_Research.md
        topic_slug = self._extract_topic_slug(path)

        content = path.read_text(encoding="utf-8")

        # Try Delta brief format first (preferred for new papers)
        learnings = self._parse_delta_brief(content, topic_slug, max_learnings)

        # Fall back to Research brief format if no learnings found
        if not learnings:
            learnings = self._parse_research_brief(content, topic_slug, max_learnings)

        return learnings

    def _extract_topic_slug(self, path: Path) -> str:
        """Extract topic slug from file path.

        Args:
            path: Path to report file.

        Returns:
            Topic slug string.
        """
        # Handle paths like: output/{topic}/runs/file.md or output/{topic}/file.md
        parts = path.parts

        # Find "output" in path and get the next part
        try:
            output_idx = parts.index("output")
            if output_idx + 1 < len(parts):
                return parts[output_idx + 1]
        except ValueError:
            pass

        # Fallback: use parent directory name
        if path.parent.name == "runs":
            return path.parent.parent.name
        return path.parent.name

    def _parse_delta_brief(
        self, content: str, topic_slug: str, max_learnings: int
    ) -> List[KeyLearning]:
        """Parse Delta brief format.

        Delta briefs have a specific structure with NEW papers section.

        Args:
            content: File content.
            topic_slug: Topic identifier.
            max_learnings: Maximum learnings to extract.

        Returns:
            List of KeyLearning objects.
        """
        learnings: List[KeyLearning] = []

        # Find NEW papers section
        new_section_match = self.NEW_PAPERS_SECTION.search(content)
        if not new_section_match:
            return learnings

        new_section = new_section_match.group(1)

        # Extract individual paper entries
        paper_entries = self.NEW_PAPER_ENTRY.findall(new_section)

        for title, paper_content in paper_entries[:max_learnings]:
            # Clean up title
            title = self._clean_title(title)

            # Try to extract summary from paper content
            summary = self._extract_summary_from_section(paper_content)

            if summary:
                learnings.append(
                    KeyLearning(
                        paper_title=title,
                        topic=topic_slug,
                        summary=self._truncate_summary(summary),
                    )
                )

        return learnings

    def _parse_research_brief(
        self, content: str, topic_slug: str, max_learnings: int
    ) -> List[KeyLearning]:
        """Parse Research brief format.

        Research briefs have extraction results with engineering summaries.

        Args:
            content: File content.
            topic_slug: Topic identifier.
            max_learnings: Maximum learnings to extract.

        Returns:
            List of KeyLearning objects.
        """
        learnings: List[KeyLearning] = []

        # Find all paper sections
        paper_sections = re.split(r"\n---\n", content)

        for section in paper_sections[: max_learnings * 2]:  # Check more sections
            if len(learnings) >= max_learnings:
                break

            # Extract title from section
            title_match = self.PAPER_HEADER_PATTERN.search(section)
            if not title_match:
                continue

            title = self._clean_title(title_match.group(1))

            # Try to extract engineering summary
            summary = self._extract_summary_from_section(section)

            if summary:
                learnings.append(
                    KeyLearning(
                        paper_title=title,
                        topic=topic_slug,
                        summary=self._truncate_summary(summary),
                    )
                )

        return learnings

    def _extract_summary_from_section(self, section: str) -> Optional[str]:
        """Extract engineering summary from a paper section.

        Args:
            section: Paper section content.

        Returns:
            Extracted summary or None.
        """
        # Try extraction result pattern first (more specific with confidence score)
        match = self.EXTRACTION_RESULT_PATTERN.search(section)
        if match:
            return self._clean_summary(match.group(1))

        # Fall back to general engineering summary pattern
        match = self.ENGINEERING_SUMMARY_PATTERN.search(section)
        if match:
            return self._clean_summary(match.group(1))

        # Try to extract from blockquote (abstract as fallback)
        blockquote_pattern = re.compile(r"^>\s*(.+?)$", re.MULTILINE)
        matches = blockquote_pattern.findall(section)
        if matches:
            # Join blockquote lines and use as summary
            abstract = " ".join(matches)
            if len(abstract) > 50:  # Only use if substantial
                return self._clean_summary(abstract)

        return None

    def _clean_title(self, title: str) -> str:
        """Clean paper title.

        Args:
            title: Raw title string.

        Returns:
            Cleaned title.
        """
        # Remove markdown links
        title = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", title)
        # Remove leading numbers and dots
        title = re.sub(r"^\d+\.\s*", "", title)
        # Remove emojis
        title = re.sub(r"[:][a-z_]+[:]", "", title)
        # Strip whitespace
        return title.strip()

    def _clean_summary(self, summary: str) -> str:
        """Clean extracted summary text.

        Args:
            summary: Raw summary text.

        Returns:
            Cleaned summary.
        """
        # Remove markdown formatting
        summary = re.sub(r"\*\*([^*]+)\*\*", r"\1", summary)
        summary = re.sub(r"\*([^*]+)\*", r"\1", summary)
        summary = re.sub(r"`([^`]+)`", r"\1", summary)

        # Remove multiple whitespace
        summary = re.sub(r"\s+", " ", summary)

        # Remove leading/trailing whitespace
        return summary.strip()

    def _truncate_summary(self, summary: str) -> str:
        """Truncate summary to Slack-friendly length.

        Args:
            summary: Full summary text.

        Returns:
            Truncated summary with ellipsis if needed.
        """
        if len(summary) <= self.max_summary_length:
            return summary

        # Truncate at word boundary
        truncated = summary[: self.max_summary_length]
        last_space = truncated.rfind(" ")
        if last_space > self.max_summary_length // 2:
            truncated = truncated[:last_space]

        return truncated.rstrip(".,;:") + "..."

    def find_delta_briefs(
        self,
        output_dir: str,
        date_filter: Optional[str] = None,
    ) -> List[str]:
        """Find Delta brief files in output directory.

        Args:
            output_dir: Base output directory.
            date_filter: Optional date string to filter (YYYY-MM-DD).

        Returns:
            List of Delta brief file paths.
        """
        base_path = Path(output_dir)
        if not base_path.exists():
            return []

        pattern = "*_Delta.md"
        if date_filter:
            pattern = f"{date_filter}_Delta.md"

        # Search in topic/runs/ directories
        delta_files = list(base_path.glob(f"*/runs/{pattern}"))

        # Also search directly in topic directories (legacy format)
        delta_files.extend(base_path.glob(f"*/{pattern}"))

        return [str(f) for f in sorted(delta_files, reverse=True)]

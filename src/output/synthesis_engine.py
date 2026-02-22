"""Synthesis Engine for Phase 3.6: Cumulative Knowledge Synthesis.

Provides the core synthesis logic for generating:
- Knowledge_Base.md: Cumulative, quality-ranked master document
- User note preservation via anchor tags
- Atomic file operations with backup support
"""

import os
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional
import structlog

from src.models.synthesis import (
    KnowledgeBaseEntry,
    UserNoteAnchor,
    SynthesisStats,
)
from src.models.registry import RegistryEntry
from src.services.registry_service import RegistryService
from src.utils.author_utils import normalize_authors
from src.utils.security import PathSanitizer

logger = structlog.get_logger()

# File names
KNOWLEDGE_BASE_FILENAME = "Knowledge_Base.md"
BACKUP_SUFFIX = ".bak"

# Anchor pattern for extracting user notes
# Paper IDs can be alphanumeric with hyphens/underscores (UUIDs, arxiv IDs, etc.)
USER_NOTE_PATTERN = re.compile(
    r"<!-- USER_NOTES_START:([\w-]+) -->\s*(.*?)\s*<!-- USER_NOTES_END:\1 -->",
    re.DOTALL | re.IGNORECASE,
)


class SynthesisEngine:
    """Engine for synthesizing cumulative Knowledge Base documents.

    Provides:
    - Quality-ranked paper aggregation from registry
    - Anchor-based user note preservation
    - Atomic file operations with backup
    - Multi-topic synthesis support
    """

    def __init__(
        self,
        registry_service: Optional[RegistryService] = None,
        output_base_dir: Path = Path("output"),
    ):
        """Initialize the synthesis engine.

        Args:
            registry_service: Registry service instance (created if None).
            output_base_dir: Base directory for output files.
        """
        self.registry_service = registry_service or RegistryService()
        self.output_base_dir = output_base_dir

        logger.info(
            "synthesis_engine_initialized",
            output_dir=str(output_base_dir),
        )

    def _ensure_topic_directory(self, topic_slug: str) -> Path:
        """Ensure topic directory exists with proper structure.

        Args:
            topic_slug: Sanitized topic slug.

        Returns:
            Path to topic directory.
        """
        # Sanitize topic slug for filesystem safety
        safe_slug = PathSanitizer.sanitize_path_component(topic_slug)
        topic_dir = self.output_base_dir / safe_slug

        # Create directory structure
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "runs").mkdir(exist_ok=True)
        (topic_dir / "papers").mkdir(exist_ok=True)

        return topic_dir

    def _get_entries_for_topic(self, topic_slug: str) -> List[RegistryEntry]:
        """Get all registry entries for a topic.

        Args:
            topic_slug: Topic slug to filter by.

        Returns:
            List of registry entries affiliated with the topic.
        """
        return self.registry_service.get_entries_for_topic(topic_slug)

    def _entry_to_kb_entry(self, entry: RegistryEntry) -> KnowledgeBaseEntry:
        """Convert a registry entry to a knowledge base entry.

        Args:
            entry: Registry entry to convert.

        Returns:
            KnowledgeBaseEntry for rendering.
        """
        # Extract metadata from snapshot
        metadata = entry.metadata_snapshot or {}

        # Get quality score from metadata
        quality_score = metadata.get("quality_score", 0.0)

        # Get authors (handles List[dict], List[str], str, None)
        authors = normalize_authors(metadata.get("authors"))

        return KnowledgeBaseEntry(
            paper_id=entry.paper_id,
            title=metadata.get("title", entry.title_normalized),
            authors=authors,
            abstract=metadata.get("abstract"),
            url=metadata.get("url"),
            doi=entry.identifiers.get("doi"),
            arxiv_id=entry.identifiers.get("arxiv"),
            publication_date=metadata.get("publication_date"),
            quality_score=quality_score,
            pdf_available=entry.pdf_path is not None,
            pdf_path=entry.pdf_path,
            extraction_results=metadata.get("extraction_results"),
            topic_affiliations=entry.topic_affiliations,
            first_discovered=entry.processed_at,
            last_updated=entry.processed_at,
        )

    def _extract_user_notes(self, kb_path: Path) -> Dict[str, UserNoteAnchor]:
        """Extract user notes from existing Knowledge Base.

        Args:
            kb_path: Path to existing Knowledge Base file.

        Returns:
            Dictionary mapping paper_id to UserNoteAnchor.
        """
        notes: Dict[str, UserNoteAnchor] = {}

        if not kb_path.exists():
            return notes

        try:
            content = kb_path.read_text(encoding="utf-8")

            for match in USER_NOTE_PATTERN.finditer(content):
                paper_id = match.group(1)
                note_content = match.group(2).strip()

                if note_content:
                    notes[paper_id] = UserNoteAnchor(
                        paper_id=paper_id,
                        content=note_content,
                    )

            logger.debug(
                "user_notes_extracted",
                count=len(notes),
                path=str(kb_path),
            )

        except Exception as e:
            logger.warning(
                "user_notes_extraction_failed",
                path=str(kb_path),
                error=str(e),
            )

        return notes

    def _quality_badge(self, score: float) -> str:
        """Generate quality badge based on score.

        Args:
            score: Quality score (0-100).

        Returns:
            Emoji badge string.
        """
        if score >= 80:
            return f"⭐⭐⭐ Excellent ({score:.0f})"
        elif score >= 60:
            return f"⭐⭐ Good ({score:.0f})"
        elif score >= 40:
            return f"⭐ Fair ({score:.0f})"
        else:
            return f"○ Low ({score:.0f})"

    def _pdf_badge(self, available: bool) -> str:
        """Generate PDF availability badge.

        Args:
            available: Whether PDF is available.

        Returns:
            Badge string.
        """
        return "📄 PDF" if available else "📋 Abstract"

    def _render_paper_section(
        self,
        entry: KnowledgeBaseEntry,
        user_note: Optional[UserNoteAnchor] = None,
    ) -> str:
        """Render a single paper section for the Knowledge Base.

        Args:
            entry: Knowledge Base entry to render.
            user_note: Optional preserved user note.

        Returns:
            Markdown string for the paper section.
        """
        lines = []

        # Paper header with badges
        quality_badge = self._quality_badge(entry.quality_score)
        pdf_badge = self._pdf_badge(entry.pdf_available)

        lines.append(f"### {entry.title}")
        lines.append(f"**Quality:** {quality_badge} | **Status:** {pdf_badge}")
        lines.append("")

        # Metadata
        if entry.authors:
            lines.append(f"**Authors:** {', '.join(entry.authors)}")

        if entry.publication_date:
            lines.append(f"**Published:** {entry.publication_date}")

        if entry.doi:
            lines.append(f"**DOI:** [{entry.doi}](https://doi.org/{entry.doi})")

        if entry.arxiv_id:
            lines.append(
                f"**ArXiv:** [{entry.arxiv_id}]"
                f"(https://arxiv.org/abs/{entry.arxiv_id})"
            )

        if entry.url:
            lines.append(f"**URL:** {entry.url}")

        lines.append("")

        # Abstract
        if entry.abstract:
            lines.append("**Abstract:**")
            lines.append(f"> {entry.abstract}")
            lines.append("")

        # Extraction results
        if entry.extraction_results:
            lines.append("**Extracted Insights:**")
            for key, value in entry.extraction_results.items():
                if value:
                    lines.append(f"- **{key.replace('_', ' ').title()}:** {value}")
            lines.append("")

        # User notes section with anchors
        lines.append(UserNoteAnchor.create_start_tag(entry.paper_id))
        if user_note and user_note.content:
            lines.append(user_note.content)
        lines.append(UserNoteAnchor.create_end_tag(entry.paper_id))
        lines.append("")

        # Topic affiliations
        if len(entry.topic_affiliations) > 1:
            other_topics = [t for t in entry.topic_affiliations if t != entry.paper_id]
            if other_topics:
                lines.append(f"*Also appears in: {', '.join(other_topics)}*")
                lines.append("")

        lines.append("---")
        lines.append("")

        return "\n".join(lines)

    def _render_knowledge_base(
        self,
        topic_slug: str,
        entries: List[KnowledgeBaseEntry],
        user_notes: Dict[str, UserNoteAnchor],
    ) -> str:
        """Render the complete Knowledge Base document.

        Args:
            topic_slug: Topic slug for the header.
            entries: Sorted list of KB entries.
            user_notes: Preserved user notes by paper_id.

        Returns:
            Complete markdown document.
        """
        lines = []

        # Header
        lines.append(f"# Knowledge Base: {topic_slug}")
        lines.append("")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"*Last updated: {timestamp}*")
        lines.append("")

        # Statistics
        total = len(entries)
        with_pdf = sum(1 for e in entries if e.pdf_available)
        avg_quality = sum(e.quality_score for e in entries) / total if total else 0

        lines.append("## Overview")
        lines.append("")
        lines.append(f"- **Total Papers:** {total}")
        lines.append(f"- **With PDF:** {with_pdf}")
        lines.append(f"- **Average Quality:** {avg_quality:.1f}")
        lines.append("")

        # Table of Contents (top 10 by quality)
        if entries:
            lines.append("## Top Papers by Quality")
            lines.append("")
            for i, entry in enumerate(entries[:10], 1):
                badge = self._quality_badge(entry.quality_score)
                # Create anchor-safe title
                anchor = re.sub(r"[^\w\s-]", "", entry.title.lower())
                anchor = re.sub(r"\s+", "-", anchor)
                lines.append(f"{i}. [{entry.title}](#{anchor}) - {badge}")
            lines.append("")

        # All papers
        lines.append("## All Papers")
        lines.append("")

        for entry in entries:
            user_note = user_notes.get(entry.paper_id)
            lines.append(self._render_paper_section(entry, user_note))

        return "\n".join(lines)

    def _create_backup(self, file_path: Path) -> Optional[Path]:
        """Create a backup of the file before overwriting.

        Args:
            file_path: Path to file to backup.

        Returns:
            Path to backup file, or None if no backup needed.
        """
        if not file_path.exists():
            return None

        backup_path = file_path.with_suffix(file_path.suffix + BACKUP_SUFFIX)

        try:
            import shutil

            shutil.copy2(file_path, backup_path)
            logger.debug(
                "backup_created",
                original=str(file_path),
                backup=str(backup_path),
            )
            return backup_path

        except Exception as e:
            logger.warning(
                "backup_failed",
                path=str(file_path),
                error=str(e),
            )
            return None

    def _atomic_write(self, file_path: Path, content: str) -> bool:
        """Atomically write content to file.

        Uses temp file + rename pattern for safety.

        Args:
            file_path: Destination file path.
            content: Content to write.

        Returns:
            True if write succeeded.
        """
        import tempfile

        try:
            # Write to temp file
            fd, tmp_path = tempfile.mkstemp(
                dir=file_path.parent,
                prefix=".kb_",
                suffix=".tmp",
            )

            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic rename
                os.rename(tmp_path, file_path)

                # Set permissions (0644 - readable by all)
                os.chmod(file_path, 0o644)

                return True

            except Exception:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise

        except Exception as e:
            logger.error(
                "atomic_write_failed",
                path=str(file_path),
                error=str(e),
            )
            return False

    def synthesize(self, topic_slug: str) -> SynthesisStats:
        """Synthesize the Knowledge Base for a topic.

        Aggregates all papers from the registry, sorts by quality,
        preserves user notes, and generates the Knowledge_Base.md file.

        Args:
            topic_slug: Topic to synthesize.

        Returns:
            SynthesisStats with operation results.
        """
        start_time = time.time()

        logger.info("synthesis_started", topic=topic_slug)

        # Ensure directory exists
        topic_dir = self._ensure_topic_directory(topic_slug)
        kb_path = topic_dir / KNOWLEDGE_BASE_FILENAME

        # Extract existing user notes
        user_notes = self._extract_user_notes(kb_path)

        # Get all entries for topic
        registry_entries = self._get_entries_for_topic(topic_slug)

        if not registry_entries:
            logger.info("synthesis_no_papers", topic=topic_slug)
            return SynthesisStats(
                topic_slug=topic_slug,
                synthesis_duration_ms=int((time.time() - start_time) * 1000),
            )

        # Convert to KB entries
        kb_entries = [self._entry_to_kb_entry(e) for e in registry_entries]

        # Sort by quality score (descending)
        kb_entries.sort(key=lambda e: e.quality_score, reverse=True)

        # Create backup
        self._create_backup(kb_path)

        # Render Knowledge Base
        content = self._render_knowledge_base(topic_slug, kb_entries, user_notes)

        # Atomic write
        success = self._atomic_write(kb_path, content)

        if not success:
            logger.error("synthesis_write_failed", topic=topic_slug)
            return SynthesisStats(
                topic_slug=topic_slug,
                synthesis_duration_ms=int((time.time() - start_time) * 1000),
            )

        # Calculate stats
        duration_ms = int((time.time() - start_time) * 1000)
        total_papers = len(kb_entries)
        papers_with_pdf = sum(1 for e in kb_entries if e.pdf_available)
        papers_with_extraction = sum(1 for e in kb_entries if e.extraction_results)
        avg_quality = (
            sum(e.quality_score for e in kb_entries) / total_papers
            if total_papers
            else 0
        )
        top_quality = kb_entries[0].quality_score if kb_entries else 0

        stats = SynthesisStats(
            topic_slug=topic_slug,
            total_papers=total_papers,
            papers_with_pdf=papers_with_pdf,
            papers_with_extraction=papers_with_extraction,
            average_quality=avg_quality,
            top_quality_score=top_quality,
            user_notes_preserved=len(user_notes),
            synthesis_duration_ms=duration_ms,
        )

        logger.info(
            "synthesis_completed",
            topic=topic_slug,
            total_papers=total_papers,
            duration_ms=duration_ms,
        )

        return stats

    def synthesize_all_topics(self) -> Dict[str, SynthesisStats]:
        """Synthesize Knowledge Bases for all topics in registry.

        Returns:
            Dictionary mapping topic_slug to SynthesisStats.
        """
        # Get all unique topics from registry
        state = self.registry_service.load()
        all_topics: set = set()

        for entry in state.entries.values():
            all_topics.update(entry.topic_affiliations)

        results: Dict[str, SynthesisStats] = {}

        for topic in sorted(all_topics):
            try:
                stats = self.synthesize(topic)
                results[topic] = stats
            except Exception as e:
                logger.error(
                    "synthesis_topic_failed",
                    topic=topic,
                    error=str(e),
                )
                results[topic] = SynthesisStats(
                    topic_slug=topic,
                )

        return results

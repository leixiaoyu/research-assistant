"""Feedback storage service for Phase 7.3.

This module provides persistent storage for feedback entries with atomic writes,
querying capabilities, and archival for large datasets.
"""

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from pydantic import ValidationError

from src.models.feedback import FeedbackEntry, FeedbackFilters, FeedbackRating

logger = logging.getLogger(__name__)


class FeedbackStorage:
    """Persistent storage for feedback entries.

    Provides atomic writes, querying, and archival capabilities.
    Uses JSON file storage with backup on corruption.

    Attributes:
        storage_path: Path to the main feedback JSON file.
        archive_dir: Directory for archived feedback files.
    """

    def __init__(
        self,
        storage_path: Path | str = "data/feedback.json",
        archive_dir: Optional[Path | str] = None,
    ) -> None:
        """Initialize feedback storage.

        Args:
            storage_path: Path to the feedback JSON file.
            archive_dir: Optional directory for archives. Defaults to
                storage_path.parent / "archives".
        """
        self.storage_path = Path(storage_path)
        self.archive_dir = (
            Path(archive_dir) if archive_dir else self.storage_path.parent / "archives"
        )
        self._entries: List[FeedbackEntry] = []
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        """Ensure entries are loaded from disk."""
        if not self._loaded:
            await self.load_all()

    async def load_all(self) -> List[FeedbackEntry]:
        """Load all feedback entries from storage.

        Returns:
            List of all feedback entries.

        Note:
            If the file is corrupted, creates a backup and starts fresh.
        """
        if not self.storage_path.exists():
            self._entries = []
            self._loaded = True
            return self._entries

        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            self._entries = [FeedbackEntry.model_validate(entry) for entry in data]
            self._loaded = True
            logger.debug(f"Loaded {len(self._entries)} feedback entries")
            return self._entries
        except json.JSONDecodeError as e:
            logger.error(f"Feedback file corrupted: {e}")
            await self._create_backup_and_reset()
            return self._entries
        except ValidationError as e:
            logger.error(f"Feedback data validation failed: {e}")
            await self._create_backup_and_reset()
            return self._entries

    async def _create_backup_and_reset(self) -> None:
        """Create a backup of corrupted file and start fresh."""
        if self.storage_path.exists():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_path = self.storage_path.with_suffix(f".backup_{timestamp}.json")
            shutil.copy2(self.storage_path, backup_path)
            logger.warning(f"Created backup at {backup_path}")
        self._entries = []
        self._loaded = True

    async def save(self, entry: FeedbackEntry) -> None:
        """Save a feedback entry with atomic write.

        Args:
            entry: The feedback entry to save.

        Raises:
            IOError: If writing to disk fails.
        """
        await self._ensure_loaded()

        # Check for existing entry for same paper (update case)
        existing_idx = next(
            (i for i, e in enumerate(self._entries) if e.paper_id == entry.paper_id),
            None,
        )

        if existing_idx is not None:
            self._entries[existing_idx] = entry
            logger.debug(f"Updated feedback for paper {entry.paper_id}")
        else:
            self._entries.append(entry)
            logger.debug(f"Added new feedback for paper {entry.paper_id}")

        await self._write_to_disk()

    async def _write_to_disk(self) -> None:
        """Write entries to disk atomically."""
        # Ensure parent directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first (atomic write pattern)
        temp_path = self.storage_path.with_suffix(".tmp")
        data = [entry.model_dump(mode="json") for entry in self._entries]

        try:
            temp_path.write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )
            # Atomic rename
            temp_path.replace(self.storage_path)
        except Exception as e:
            # Clean up temp file on failure
            if temp_path.exists():
                temp_path.unlink()
            raise IOError(f"Failed to write feedback: {e}") from e

    async def query(self, filters: FeedbackFilters) -> List[FeedbackEntry]:
        """Query feedback entries with filters.

        Args:
            filters: Filters to apply.

        Returns:
            List of matching feedback entries.
        """
        await self._ensure_loaded()

        results = self._entries.copy()

        if filters.topic_slug:
            results = [e for e in results if e.topic_slug == filters.topic_slug]

        if filters.rating:
            rating_value = (
                filters.rating.value
                if isinstance(filters.rating, FeedbackRating)
                else filters.rating
            )
            results = [e for e in results if e.rating == rating_value]

        if filters.reasons:
            reason_values = [
                r.value if hasattr(r, "value") else r for r in filters.reasons
            ]
            results = [e for e in results if any(r in e.reasons for r in reason_values)]

        if filters.start_date:
            results = [e for e in results if e.timestamp >= filters.start_date]

        if filters.end_date:
            results = [e for e in results if e.timestamp <= filters.end_date]

        if filters.paper_ids:
            results = [e for e in results if e.paper_id in filters.paper_ids]

        return results

    async def get_by_paper_id(self, paper_id: str) -> Optional[FeedbackEntry]:
        """Get feedback for a specific paper.

        Args:
            paper_id: The paper's registry ID.

        Returns:
            The feedback entry if found, None otherwise.
        """
        await self._ensure_loaded()
        return next((e for e in self._entries if e.paper_id == paper_id), None)

    async def get_by_topic(
        self,
        topic_slug: str,
        rating_filter: Optional[FeedbackRating] = None,
    ) -> List[FeedbackEntry]:
        """Get all feedback for a topic.

        Args:
            topic_slug: The topic identifier.
            rating_filter: Optional filter by rating.

        Returns:
            List of feedback entries for the topic.
        """
        filters = FeedbackFilters(topic_slug=topic_slug, rating=rating_filter)
        return await self.query(filters)

    async def delete(self, entry_id: str) -> bool:
        """Delete a feedback entry.

        Args:
            entry_id: The ID of the entry to delete.

        Returns:
            True if deleted, False if not found.
        """
        await self._ensure_loaded()

        original_len = len(self._entries)
        self._entries = [e for e in self._entries if e.id != entry_id]

        if len(self._entries) < original_len:
            await self._write_to_disk()
            logger.debug(f"Deleted feedback entry {entry_id}")
            return True
        return False

    async def archive_old_entries(self, threshold: int = 10000) -> int:
        """Archive entries beyond threshold.

        Keeps the most recent entries up to threshold, archives the rest.

        Args:
            threshold: Maximum entries to keep in main file.

        Returns:
            Number of entries archived.
        """
        await self._ensure_loaded()

        if len(self._entries) <= threshold:
            return 0

        # Sort by timestamp, most recent first
        sorted_entries = sorted(self._entries, key=lambda e: e.timestamp, reverse=True)

        # Split into keep and archive
        keep = sorted_entries[:threshold]
        archive = sorted_entries[threshold:]

        # Write archive
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_path = self.archive_dir / f"feedback_archive_{timestamp}.json"

        archive_data = [entry.model_dump(mode="json") for entry in archive]
        archive_path.write_text(
            json.dumps(archive_data, indent=2, default=str), encoding="utf-8"
        )

        # Update main file
        self._entries = keep
        await self._write_to_disk()

        logger.info(f"Archived {len(archive)} entries to {archive_path}")
        return len(archive)

    async def export(
        self,
        format: str = "json",
        output_path: Optional[Path] = None,
    ) -> str:
        """Export feedback data.

        Args:
            format: Export format ("json" or "csv").
            output_path: Optional output file path.

        Returns:
            Exported data as string, or path to file if output_path given.

        Raises:
            ValueError: If format is not supported.
        """
        await self._ensure_loaded()

        if format == "json":
            data = json.dumps(
                [e.model_dump(mode="json") for e in self._entries],
                indent=2,
                default=str,
            )
        elif format == "csv":
            import csv
            import io

            output = io.StringIO()
            if self._entries:
                fieldnames = list(self._entries[0].model_dump().keys())
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                for entry in self._entries:
                    row = entry.model_dump(mode="json")
                    # Convert lists to strings for CSV
                    row["reasons"] = ",".join(row.get("reasons", []))
                    writer.writerow(row)
            data = output.getvalue()
        else:
            raise ValueError(f"Unsupported export format: {format}")

        if output_path:
            Path(output_path).write_text(data, encoding="utf-8")
            return str(output_path)
        return data

    @property
    def count(self) -> int:
        """Get the number of entries (requires prior load)."""
        return len(self._entries)

    async def clear(self) -> None:
        """Clear all entries (for testing)."""
        self._entries = []
        self._loaded = True
        if self.storage_path.exists():
            self.storage_path.unlink()

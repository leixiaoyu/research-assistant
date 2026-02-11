"""Registry Service for Phase 3.5: Global Paper Identity.

Provides persistent identity resolution and cross-topic deduplication
with atomic state updates and file locking for concurrent safety.
"""

import os
import json
import tempfile
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone
import structlog

from src.models.registry import (
    RegistryEntry,
    RegistryState,
    IdentityMatch,
    ProcessingAction,
)
from src.models.paper import PaperMetadata
from src.models.extraction import ExtractionTarget
from src.utils.hash import (
    calculate_extraction_hash,
    normalize_title,
    calculate_title_similarity,
)

logger = structlog.get_logger()

# Default registry location
DEFAULT_REGISTRY_PATH = Path("data/registry.json")

# Title similarity threshold for fuzzy matching (95%)
TITLE_SIMILARITY_THRESHOLD = 0.95


class RegistryService:
    """Service for managing the global paper identity registry.

    Provides:
    - Identity resolution (DOI → Provider ID → Fuzzy Title)
    - Atomic state persistence with file locking
    - Backfill detection based on extraction target changes
    - Cross-topic deduplication and affiliation tracking
    """

    def __init__(
        self,
        registry_path: Optional[Path] = None,
        title_similarity_threshold: float = TITLE_SIMILARITY_THRESHOLD,
    ):
        """Initialize the registry service.

        Args:
            registry_path: Path to registry.json file.
            title_similarity_threshold: Minimum similarity for title matching.
        """
        self.registry_path = registry_path or DEFAULT_REGISTRY_PATH
        self.title_similarity_threshold = title_similarity_threshold
        self._state: Optional[RegistryState] = None
        self._lock_fd: Optional[int] = None

        logger.info(
            "registry_service_initialized",
            path=str(self.registry_path),
            threshold=self.title_similarity_threshold,
        )

    def _ensure_directory(self) -> None:
        """Ensure the registry directory exists with proper permissions."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        # Set directory permissions to owner-only (0700)
        try:
            os.chmod(self.registry_path.parent, 0o700)
        except OSError as e:
            logger.warning("registry_dir_chmod_failed", error=str(e))

    def _set_file_permissions(self) -> None:
        """Set registry file permissions to owner-only (0600)."""
        if self.registry_path.exists():
            try:
                os.chmod(self.registry_path, 0o600)
            except OSError as e:
                logger.warning("registry_file_chmod_failed", error=str(e))

    def load(self) -> RegistryState:
        """Load registry state from disk.

        Creates an empty registry if file doesn't exist.

        Returns:
            Current registry state.
        """
        if self._state is not None:
            return self._state

        self._ensure_directory()

        if not self.registry_path.exists():
            logger.info("registry_creating_new", path=str(self.registry_path))
            self._state = RegistryState()
            return self._state

        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._state = RegistryState.model_validate(data)

            logger.info(
                "registry_loaded",
                path=str(self.registry_path),
                entries=self._state.get_entry_count(),
            )
            return self._state

        except json.JSONDecodeError as e:
            logger.error(
                "registry_parse_error",
                path=str(self.registry_path),
                error=str(e),
            )
            # Create backup and start fresh
            backup_path = self.registry_path.with_suffix(".json.backup")
            if self.registry_path.exists():
                self.registry_path.rename(backup_path)
                logger.warning(
                    "registry_backed_up",
                    backup=str(backup_path),
                )

            self._state = RegistryState()
            return self._state

        except Exception as e:
            logger.error(
                "registry_load_error",
                path=str(self.registry_path),
                error=str(e),
            )
            self._state = RegistryState()
            return self._state

    def save(self) -> bool:
        """Save registry state to disk atomically.

        Uses temporary file + rename pattern to prevent corruption.

        Returns:
            True if save succeeded, False otherwise.
        """
        if self._state is None:
            logger.warning("registry_save_no_state")
            return False

        self._ensure_directory()

        # Update timestamp
        self._state.updated_at = datetime.now(timezone.utc)

        try:
            # Write to temporary file first
            fd, tmp_path = tempfile.mkstemp(
                dir=self.registry_path.parent,
                prefix=".registry_",
                suffix=".tmp",
            )

            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(
                        self._state.model_dump(mode="json"),
                        f,
                        indent=2,
                        default=str,
                    )
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic rename
                os.rename(tmp_path, self.registry_path)

                # Set proper permissions
                self._set_file_permissions()

                logger.debug(
                    "registry_saved",
                    path=str(self.registry_path),
                    entries=self._state.get_entry_count(),
                )
                return True

            except Exception:
                # Clean up temp file on error
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise

        except Exception as e:
            logger.error(
                "registry_save_error",
                path=str(self.registry_path),
                error=str(e),
            )
            return False

    def resolve_identity(self, paper: PaperMetadata) -> IdentityMatch:
        """Resolve paper identity against the registry.

        Uses priority-based matching:
        1. DOI (exact match)
        2. Provider ID (arxiv:xxx, semantic_scholar:xxx)
        3. Fuzzy title matching (>95% similarity)

        Args:
            paper: Paper metadata to resolve.

        Returns:
            IdentityMatch with matched entry or None.
        """
        state = self.load()

        # Stage 1: DOI lookup
        if paper.doi:
            if paper.doi in state.doi_index:
                paper_id = state.doi_index[paper.doi]
                entry = state.entries.get(paper_id)
                if entry:
                    logger.debug(
                        "identity_matched_by_doi",
                        doi=paper.doi,
                        paper_id=paper_id,
                    )
                    return IdentityMatch(
                        matched=True,
                        entry=entry,
                        match_method="doi",
                    )

        # Stage 2: Provider ID lookup
        provider_keys = []
        if paper.paper_id:
            # Detect provider from paper_id format
            if paper.paper_id.startswith("arxiv:"):
                provider_keys.append(paper.paper_id)
            elif "." in paper.paper_id and paper.paper_id[0].isdigit():
                # Likely ArXiv format: YYMM.NNNNN
                provider_keys.append(f"arxiv:{paper.paper_id}")
            else:
                # Assume Semantic Scholar
                provider_keys.append(f"semantic_scholar:{paper.paper_id}")

        for key in provider_keys:
            if key in state.provider_id_index:
                paper_id = state.provider_id_index[key]
                entry = state.entries.get(paper_id)
                if entry:
                    # Determine which provider matched
                    provider = key.split(":")[0] if ":" in key else "unknown"
                    logger.debug(
                        "identity_matched_by_provider_id",
                        provider=provider,
                        key=key,
                        paper_id=paper_id,
                    )
                    return IdentityMatch(
                        matched=True,
                        entry=entry,
                        match_method=provider,
                    )

        # Stage 3: Fuzzy title matching
        if paper.title:
            best_match: Optional[RegistryEntry] = None
            best_score = 0.0

            for entry in state.entries.values():
                similarity = calculate_title_similarity(
                    paper.title, entry.title_normalized
                )
                if similarity > best_score:
                    best_score = similarity
                    best_match = entry

            if best_match and best_score >= self.title_similarity_threshold:
                logger.debug(
                    "identity_matched_by_title",
                    title=paper.title[:50],
                    similarity=f"{best_score:.3f}",
                    paper_id=best_match.paper_id,
                )
                return IdentityMatch(
                    matched=True,
                    entry=best_match,
                    match_method="title",
                    similarity_score=best_score,
                )

        # No match found
        logger.debug(
            "identity_no_match",
            title=paper.title[:50] if paper.title else "N/A",
            doi=paper.doi,
        )
        return IdentityMatch(matched=False)

    def determine_action(
        self,
        paper: PaperMetadata,
        topic_slug: str,
        extraction_targets: Optional[List[ExtractionTarget]] = None,
    ) -> tuple[ProcessingAction, Optional[RegistryEntry]]:
        """Determine what action to take for a paper.

        Args:
            paper: Paper metadata to check.
            topic_slug: Sanitized slug of the current topic.
            extraction_targets: Current extraction targets (for hash comparison).

        Returns:
            Tuple of (action, existing_entry or None).
        """
        # Resolve identity
        match = self.resolve_identity(paper)

        # New paper - full processing required
        if not match.matched:
            logger.debug(
                "action_full_process",
                reason="new_paper",
                title=paper.title[:50] if paper.title else "N/A",
            )
            return ProcessingAction.FULL_PROCESS, None

        entry = match.entry
        # Type guard: entry should not be None when match.matched is True
        assert entry is not None, "Entry must exist when match is found"

        current_hash = calculate_extraction_hash(extraction_targets)

        # Check if extraction targets have changed
        if entry.extraction_target_hash != current_hash:
            logger.info(
                "action_backfill",
                paper_id=entry.paper_id,
                old_hash=entry.extraction_target_hash[:20] + "...",
                new_hash=current_hash[:20] + "...",
            )
            return ProcessingAction.BACKFILL, entry

        # Check if already affiliated with this topic
        if topic_slug in entry.topic_affiliations:
            logger.debug(
                "action_skip",
                paper_id=entry.paper_id,
                topic=topic_slug,
            )
            return ProcessingAction.SKIP, entry

        # Same requirements, different topic - just map
        logger.debug(
            "action_map_only",
            paper_id=entry.paper_id,
            topic=topic_slug,
        )
        return ProcessingAction.MAP_ONLY, entry

    def register_paper(
        self,
        paper: PaperMetadata,
        topic_slug: str,
        extraction_targets: Optional[List[ExtractionTarget]] = None,
        pdf_path: Optional[str] = None,
        markdown_path: Optional[str] = None,
        existing_entry: Optional[RegistryEntry] = None,
    ) -> RegistryEntry:
        """Register a paper in the global registry.

        Creates a new entry or updates an existing one.

        Args:
            paper: Paper metadata.
            topic_slug: Topic slug for affiliation.
            extraction_targets: Extraction targets used.
            pdf_path: Path to downloaded PDF.
            markdown_path: Path to converted markdown.
            existing_entry: Existing entry to update (for backfill).

        Returns:
            Created or updated registry entry.
        """
        state = self.load()
        target_hash = calculate_extraction_hash(extraction_targets)

        if existing_entry:
            # Update existing entry
            entry = existing_entry
            entry.extraction_target_hash = target_hash
            entry.processed_at = datetime.now(timezone.utc)
            entry.add_topic_affiliation(topic_slug)

            if pdf_path:
                entry.pdf_path = pdf_path
            if markdown_path:
                entry.markdown_path = markdown_path

            # Update metadata snapshot
            entry.metadata_snapshot = paper.model_dump(mode="json")

            logger.info(
                "registry_entry_updated",
                paper_id=entry.paper_id,
                topic=topic_slug,
            )
        else:
            # Build identifiers
            identifiers = {}
            if paper.doi:
                identifiers["doi"] = paper.doi
            if paper.paper_id:
                if "." in paper.paper_id and paper.paper_id[0].isdigit():
                    identifiers["arxiv"] = paper.paper_id
                else:
                    identifiers["semantic_scholar"] = paper.paper_id

            # Create new entry
            entry = RegistryEntry(
                identifiers=identifiers,
                title_normalized=normalize_title(paper.title),
                extraction_target_hash=target_hash,
                topic_affiliations=[topic_slug],
                pdf_path=pdf_path,
                markdown_path=markdown_path,
                metadata_snapshot=paper.model_dump(mode="json"),
            )

            logger.info(
                "registry_entry_created",
                paper_id=entry.paper_id,
                title=paper.title[:50] if paper.title else "N/A",
                topic=topic_slug,
            )

        # Add to state and save
        state.add_entry(entry)
        self.save()

        return entry

    def add_topic_affiliation(
        self,
        entry: RegistryEntry,
        topic_slug: str,
    ) -> bool:
        """Add a topic affiliation to an existing entry.

        Args:
            entry: Registry entry to update.
            topic_slug: Topic slug to add.

        Returns:
            True if affiliation was added, False if already present.
        """
        state = self.load()

        # Find entry in state
        if entry.paper_id not in state.entries:
            logger.warning(
                "registry_entry_not_found",
                paper_id=entry.paper_id,
            )
            return False

        # Add affiliation
        existing = state.entries[entry.paper_id]
        added = existing.add_topic_affiliation(topic_slug)

        if added:
            self.save()
            logger.debug(
                "topic_affiliation_added",
                paper_id=entry.paper_id,
                topic=topic_slug,
            )

        return added

    def get_entry(self, paper_id: str) -> Optional[RegistryEntry]:
        """Get a registry entry by paper ID.

        Args:
            paper_id: Canonical paper UUID.

        Returns:
            Registry entry or None.
        """
        state = self.load()
        return state.entries.get(paper_id)

    def get_entries_for_topic(self, topic_slug: str) -> List[RegistryEntry]:
        """Get all registry entries affiliated with a topic.

        Args:
            topic_slug: Topic slug to filter by.

        Returns:
            List of registry entries for the topic.
        """
        state = self.load()
        return [
            entry
            for entry in state.entries.values()
            if topic_slug in entry.topic_affiliations
        ]

    def get_stats(self) -> dict:
        """Get registry statistics.

        Returns:
            Dictionary of registry stats.
        """
        state = self.load()
        return {
            "total_entries": state.get_entry_count(),
            "total_dois": len(state.doi_index),
            "total_provider_ids": len(state.provider_id_index),
            "created_at": state.created_at.isoformat(),
            "updated_at": state.updated_at.isoformat(),
        }

    def clear(self) -> None:
        """Clear the registry (for testing).

        Warning: This removes all registry data!
        """
        self._state = RegistryState()
        self.save()
        logger.warning("registry_cleared")

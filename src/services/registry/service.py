"""Registry service orchestration layer.

This module coordinates between persistence, registration, and query layers
to provide the main RegistryService API.
"""

from pathlib import Path
from typing import Optional, List
import structlog

from src.models.registry import (
    RegistryEntry,
    RegistryState,
    IdentityMatch,
    ProcessingAction,
)
from src.models.paper import PaperMetadata
from src.models.extraction import ExtractionTarget

from .persistence import RegistryPersistence
from .paper_registry import PaperRegistry, TITLE_SIMILARITY_THRESHOLD
from .queries import RegistryQueries

logger = structlog.get_logger()

# Default registry location
DEFAULT_REGISTRY_PATH = Path("data/registry.json")


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

        # Initialize subsystems
        self._persistence = RegistryPersistence(self.registry_path)
        self._registry = PaperRegistry(title_similarity_threshold)
        self._queries = RegistryQueries()

        # Cached state
        self._state: Optional[RegistryState] = None

        logger.info(
            "registry_service_initialized",
            path=str(self.registry_path),
            threshold=self.title_similarity_threshold,
        )

    # Private methods exposed for backward compatibility with tests
    @property
    def _lock_fd(self) -> Optional[int]:
        """Expose lock file descriptor for testing."""
        return self._persistence._lock_fd

    @_lock_fd.setter
    def _lock_fd(self, value: Optional[int]) -> None:
        """Set lock file descriptor for testing."""
        self._persistence._lock_fd = value

    def _ensure_directory(self) -> None:
        """Ensure registry directory exists (delegated to persistence)."""
        self._persistence._ensure_directory()

    def _set_file_permissions(self) -> None:
        """Set file permissions (delegated to persistence)."""
        self._persistence._set_file_permissions()

    def _acquire_lock(self) -> bool:
        """Acquire lock (delegated to persistence)."""
        return self._persistence.acquire_lock()

    def _release_lock(self) -> None:
        """Release lock (delegated to persistence)."""
        self._persistence.release_lock()

    def load(self) -> RegistryState:
        """Load registry state from disk.

        Creates an empty registry if file doesn't exist.
        Uses advisory file locking to prevent concurrent access issues.

        Returns:
            Current registry state.
        """
        if self._state is not None:
            return self._state

        self._acquire_lock()

        try:
            loaded_state = self._persistence.load()

            if loaded_state is None:
                logger.info("registry_creating_new", path=str(self.registry_path))
                self._state = RegistryState()
            else:
                self._state = loaded_state

            return self._state

        finally:
            self._release_lock()

    def save(self) -> bool:
        """Save registry state to disk atomically.

        Uses temporary file + rename pattern to prevent corruption.
        Uses advisory file locking to prevent concurrent access issues.

        Returns:
            True if save succeeded, False otherwise.
        """
        if self._state is None:
            logger.warning("registry_save_no_state")
            return False

        self._acquire_lock()

        try:
            return self._persistence.save(self._state)
        finally:
            self._release_lock()

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
        return self._registry.resolve_identity(paper, state)

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
        state = self.load()
        return self._registry.determine_action(
            paper, topic_slug, state, extraction_targets
        )

    def register_paper(
        self,
        paper: PaperMetadata,
        topic_slug: str,
        extraction_targets: Optional[List[ExtractionTarget]] = None,
        pdf_path: Optional[str] = None,
        markdown_path: Optional[str] = None,
        existing_entry: Optional[RegistryEntry] = None,
        discovery_only: bool = False,
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
            discovery_only: If True, register paper at discovery time without
                requiring extraction. This enables deduplication for papers
                that may be filtered out before extraction.

        Returns:
            Created or updated registry entry.
        """
        state = self.load()
        entry = self._registry.register_paper(
            paper=paper,
            topic_slug=topic_slug,
            state=state,
            extraction_targets=extraction_targets,
            pdf_path=pdf_path,
            markdown_path=markdown_path,
            existing_entry=existing_entry,
            discovery_only=discovery_only,
        )
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
        added = self._registry.add_topic_affiliation(entry, topic_slug, state)

        if added:
            self.save()

        return added

    def get_entry(self, paper_id: str) -> Optional[RegistryEntry]:
        """Get a registry entry by paper ID.

        Args:
            paper_id: Canonical paper UUID.

        Returns:
            Registry entry or None.
        """
        state = self.load()
        return self._queries.get_entry(paper_id, state)

    def get_entries_for_topic(self, topic_slug: str) -> List[RegistryEntry]:
        """Get all registry entries affiliated with a topic.

        Args:
            topic_slug: Topic slug to filter by.

        Returns:
            List of registry entries for the topic.
        """
        state = self.load()
        return self._queries.get_entries_for_topic(topic_slug, state)

    def get_stats(self) -> dict:
        """Get registry statistics.

        Returns:
            Dictionary of registry stats.
        """
        state = self.load()
        return self._queries.get_stats(state)

    def clear(self) -> None:
        """Clear the registry (for testing).

        Warning: This removes all registry data!
        """
        self._state = RegistryState()
        self.save()
        logger.warning("registry_cleared")

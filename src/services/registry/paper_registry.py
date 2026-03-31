"""Core paper registration and identity resolution logic.

This module handles:
- Identity resolution (DOI → Provider ID → Fuzzy Title)
- Paper registration with deduplication
- Topic affiliation management
- Backfill detection based on extraction target changes
"""

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

# Title similarity threshold for fuzzy matching (95%)
TITLE_SIMILARITY_THRESHOLD = 0.95


class PaperRegistry:
    """Core registry logic for paper identity resolution and registration.

    Handles:
    - Three-stage identity resolution (DOI, Provider ID, Fuzzy Title)
    - Paper registration with automatic deduplication
    - Topic affiliation tracking
    - Backfill detection based on extraction target changes
    """

    def __init__(self, title_similarity_threshold: float = TITLE_SIMILARITY_THRESHOLD):
        """Initialize paper registry.

        Args:
            title_similarity_threshold: Minimum similarity for title matching.
        """
        self.title_similarity_threshold = title_similarity_threshold

        logger.debug(
            "paper_registry_initialized",
            threshold=self.title_similarity_threshold,
        )

    def resolve_identity(
        self, paper: PaperMetadata, state: RegistryState
    ) -> IdentityMatch:
        """Resolve paper identity against the registry.

        Uses priority-based matching:
        1. DOI (exact match)
        2. Provider ID (arxiv:xxx, semantic_scholar:xxx)
        3. Fuzzy title matching (>95% similarity)

        Args:
            paper: Paper metadata to resolve.
            state: Current registry state.

        Returns:
            IdentityMatch with matched entry or None.
        """
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
        state: RegistryState,
        extraction_targets: Optional[List[ExtractionTarget]] = None,
    ) -> tuple[ProcessingAction, Optional[RegistryEntry]]:
        """Determine what action to take for a paper.

        Args:
            paper: Paper metadata to check.
            topic_slug: Sanitized slug of the current topic.
            state: Current registry state.
            extraction_targets: Current extraction targets (for hash comparison).

        Returns:
            Tuple of (action, existing_entry or None).
        """
        # Resolve identity
        match = self.resolve_identity(paper, state)

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
        state: RegistryState,
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
            state: Current registry state (will be modified).
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
        target_hash = calculate_extraction_hash(extraction_targets)

        # Check if paper already exists in registry (may have been registered
        # at discovery time before quality filtering)
        if not existing_entry:
            match = self.resolve_identity(paper, state)
            if match.matched and match.entry:
                existing_entry = match.entry

        if existing_entry:
            # Update existing entry (either passed in or found via identity)
            entry = existing_entry
            # Only update extraction fields if not discovery_only
            if not discovery_only:
                entry.extraction_target_hash = target_hash
                entry.processed_at = datetime.now(timezone.utc)
                if pdf_path:
                    entry.pdf_path = pdf_path
                if markdown_path:
                    entry.markdown_path = markdown_path
                # Update metadata snapshot with potentially richer data
                entry.metadata_snapshot = paper.model_dump(mode="json")

            entry.add_topic_affiliation(topic_slug)

            logger.info(
                "registry_entry_updated",
                paper_id=entry.paper_id,
                topic=topic_slug,
                discovery_only=discovery_only,
            )
        else:
            # Build identifiers - include both arxiv_id and paper_id
            identifiers = {}
            if paper.doi:
                identifiers["doi"] = paper.doi
            # Check arxiv_id first (explicit ArXiv ID field)
            if hasattr(paper, "arxiv_id") and paper.arxiv_id:
                identifiers["arxiv"] = paper.arxiv_id
            # Also check paper_id format
            if paper.paper_id:
                if "." in paper.paper_id and paper.paper_id[0].isdigit():
                    # ArXiv format: YYMM.NNNNN
                    if "arxiv" not in identifiers:
                        identifiers["arxiv"] = paper.paper_id
                else:
                    identifiers["semantic_scholar"] = paper.paper_id

            # Create new entry
            entry = RegistryEntry(
                identifiers=identifiers,
                title_normalized=normalize_title(paper.title),
                extraction_target_hash=target_hash,
                topic_affiliations=[topic_slug],
                pdf_path=pdf_path if not discovery_only else None,
                markdown_path=markdown_path if not discovery_only else None,
                metadata_snapshot=paper.model_dump(mode="json"),
            )

            logger.info(
                "registry_entry_created",
                paper_id=entry.paper_id,
                title=paper.title[:50] if paper.title else "N/A",
                topic=topic_slug,
                discovery_only=discovery_only,
            )

        # Add to state
        state.add_entry(entry)

        return entry

    def add_topic_affiliation(
        self,
        entry: RegistryEntry,
        topic_slug: str,
        state: RegistryState,
    ) -> bool:
        """Add a topic affiliation to an existing entry.

        Args:
            entry: Registry entry to update.
            topic_slug: Topic slug to add.
            state: Current registry state.

        Returns:
            True if affiliation was added, False if already present.
        """
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
            logger.debug(
                "topic_affiliation_added",
                paper_id=entry.paper_id,
                topic=topic_slug,
            )

        return added

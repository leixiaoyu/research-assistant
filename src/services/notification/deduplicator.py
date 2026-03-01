"""Notification Deduplicator for Phase 3.8.

Categorizes discovered papers into new/duplicate based on registry presence
to enable deduplication-aware Slack notifications.

Usage:
    from src.services.notification import NotificationDeduplicator
    from src.services.registry_service import RegistryService

    registry = RegistryService()
    deduplicator = NotificationDeduplicator(registry)
    result = deduplicator.categorize_papers(papers)

Note:
    The "retry_papers" category is reserved for future use when RegistryEntry
    gains a status field to track processing outcomes (PROCESSED, FAILED, SKIPPED).
    Currently, papers are only categorized as "new" or "duplicate" based on
    registry presence.
"""

from typing import List, Optional, TYPE_CHECKING
import structlog

from src.models.notification import DeduplicationResult
from src.models.paper import PaperMetadata

if TYPE_CHECKING:
    from src.services.registry_service import RegistryService

logger = structlog.get_logger()


class NotificationDeduplicator:
    """Service for categorizing papers for deduplication-aware notifications.

    Uses the RegistryService to determine paper status and categorize them:
    - new_papers: Papers not found in registry (truly new discoveries)
    - duplicate_papers: Papers found in registry (already processed)
    - retry_papers: Reserved for future use (requires status tracking in registry)

    Note:
        The retry_papers category requires RegistryEntry to have a status field
        tracking processing outcomes. This is planned for a future phase.
        Currently, all papers found in registry are categorized as duplicates.

    Attributes:
        registry_service: Registry service for identity resolution.
    """

    def __init__(self, registry_service: Optional["RegistryService"] = None) -> None:
        """Initialize the notification deduplicator.

        Args:
            registry_service: Registry service instance. If None, all papers
                will be treated as new (graceful degradation).
        """
        self._registry_service = registry_service
        logger.info(
            "notification_deduplicator_initialized",
            has_registry=registry_service is not None,
        )

    @property
    def registry_service(self) -> Optional["RegistryService"]:
        """Get the registry service."""
        return self._registry_service

    def categorize_papers(
        self,
        papers: List[PaperMetadata],
    ) -> DeduplicationResult:
        """Categorize papers based on registry status.

        Args:
            papers: List of discovered papers to categorize.

        Returns:
            DeduplicationResult with papers categorized into new/retry/duplicate.
        """
        new_papers: List[dict] = []
        retry_papers: List[dict] = []
        duplicate_papers: List[dict] = []

        # Graceful fallback if registry unavailable
        if self._registry_service is None:
            logger.warning(
                "notification_deduplicator_no_registry",
                papers_count=len(papers),
                action="treating_all_as_new",
            )
            for paper in papers:
                new_papers.append(paper.model_dump(mode="json"))

            return DeduplicationResult(
                new_papers=new_papers,
                retry_papers=retry_papers,
                duplicate_papers=duplicate_papers,
            )

        # Categorize each paper based on registry status
        for paper in papers:
            try:
                category = self._categorize_single_paper(paper)
                paper_dict = paper.model_dump(mode="json")

                if category == "new":
                    new_papers.append(paper_dict)
                elif category == "retry":
                    retry_papers.append(paper_dict)
                else:  # duplicate
                    duplicate_papers.append(paper_dict)

            except Exception as e:
                # On error, treat as new (fail-safe)
                logger.warning(
                    "notification_deduplicator_paper_error",
                    paper_title=paper.title[:50] if paper.title else "N/A",
                    error=str(e),
                    action="treating_as_new",
                )
                new_papers.append(paper.model_dump(mode="json"))

        logger.info(
            "notification_deduplicator_categorized",
            total=len(papers),
            new=len(new_papers),
            retry=len(retry_papers),
            duplicate=len(duplicate_papers),
        )

        return DeduplicationResult(
            new_papers=new_papers,
            retry_papers=retry_papers,
            duplicate_papers=duplicate_papers,
        )

    def _categorize_single_paper(self, paper: PaperMetadata) -> str:
        """Categorize a single paper based on registry presence.

        Categorization logic:
        - "new": Paper not found in registry (truly new discovery)
        - "duplicate": Paper found in registry (already processed)

        Note:
            The "retry" category is reserved for future use when RegistryEntry
            gains a status field to track processing outcomes. Currently, we
            cannot distinguish between successfully processed papers and those
            that failed, so all registered papers are treated as duplicates.

        Args:
            paper: Paper to categorize.

        Returns:
            Category string: "new" or "duplicate".
        """
        # Type guard: registry_service must be set when this method is called
        assert self._registry_service is not None

        # Query registry for identity
        match = self._registry_service.resolve_identity(paper)

        # Not in registry = new paper
        if not match.matched:
            return "new"

        # Found in registry - paper was previously processed
        # Note: We cannot distinguish success/failure without a status field
        # in RegistryEntry. All registered papers are treated as duplicates.
        entry = match.entry
        if entry is None:
            # Edge case: matched but no entry (shouldn't happen, but be safe)
            return "new"

        # Paper exists in registry = duplicate (already seen/processed)
        return "duplicate"

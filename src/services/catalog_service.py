from typing import Optional
from datetime import datetime
import hashlib
import structlog
from src.models.catalog import CatalogRun, TopicCatalogEntry
from src.models.config import ResearchTopic

logger = structlog.get_logger()


class CatalogService:
    """Service for managing the research catalog and deduplication"""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.catalog = None

    def load(self) -> None:
        """Load catalog from storage"""
        self.catalog = self.config_manager.load_catalog()

    def save(self) -> None:
        """Save catalog to storage"""
        if self.catalog:
            self.config_manager.save_catalog(self.catalog)

    def get_or_create_topic(self, query: str) -> TopicCatalogEntry:
        """Find existing topic or create new with slug collision handling"""
        if self.catalog is None:
            self.load()

        assert self.catalog is not None
        base_slug = self.config_manager.generate_topic_slug(query)

        # 1. Check if topic already exists with this EXACT query (normalized)
        # Normalize: strip spaces, lowercase
        norm_query = " ".join(query.lower().split())
        topic: TopicCatalogEntry
        for topic in self.catalog.topics.values():
            existing_norm = " ".join(topic.query.lower().split())
            if existing_norm == norm_query:
                logger.info("existing_topic_found", query=query, slug=topic.topic_slug)
                return topic

        # 2. Check for slug collision
        topic_slug = base_slug
        counter = 1
        while topic_slug in self.catalog.topics:
            topic_slug = f"{base_slug}-{counter}"
            counter += 1

        logger.info("creating_new_topic", query=query, slug=topic_slug)
        new_topic: TopicCatalogEntry = self.catalog.get_or_create_topic(
            topic_slug, query
        )
        return new_topic

    def add_run(self, topic_slug: str, run: CatalogRun) -> None:
        """Add a run to a topic and save"""
        if self.catalog is None:
            self.load()

        assert self.catalog is not None
        if topic_slug not in self.catalog.topics:
            raise ValueError(f"Topic not found: {topic_slug}")

        topic = self.catalog.topics[topic_slug]
        topic.add_run(run)
        self.save()

    def is_paper_processed(
        self, topic_slug: str, paper_id: str, doi: Optional[str] = None
    ) -> bool:
        """Check if a paper has already been processed for this topic"""
        if self.catalog is None:
            self.load()

        assert self.catalog is not None
        if topic_slug not in self.catalog.topics:
            return False

        topic_entry: TopicCatalogEntry = self.catalog.topics[topic_slug]
        return topic_entry.has_paper(paper_id, doi)

    def get_last_discovery_at(self, topic_slug: str) -> Optional[datetime]:
        """Get last successful discovery timestamp for a topic.

        Phase 7.1: Used for incremental discovery scheduling.

        Args:
            topic_slug: The topic slug to query

        Returns:
            Last successful discovery timestamp, or None if not found or not set
        """
        if self.catalog is None:
            self.load()

        assert self.catalog is not None
        if topic_slug not in self.catalog.topics:
            logger.debug("topic_not_found_for_last_discovery", topic_slug=topic_slug)
            return None

        topic_entry: TopicCatalogEntry = self.catalog.topics[topic_slug]
        logger.debug(
            "retrieved_last_discovery_timestamp",
            topic_slug=topic_slug,
            timestamp=topic_entry.last_successful_discovery_at,
        )
        return topic_entry.last_successful_discovery_at

    def set_last_discovery_at(self, topic_slug: str, timestamp: datetime) -> None:
        """Set last successful discovery timestamp for a topic.

        Phase 7.1: Records when discovery successfully completed.
        Creates topic entry if it doesn't exist (with minimal data).

        Args:
            topic_slug: The topic slug to update
            timestamp: The discovery completion timestamp
        """
        if self.catalog is None:
            self.load()

        assert self.catalog is not None

        # Create topic if it doesn't exist
        if topic_slug not in self.catalog.topics:
            logger.info(
                "creating_topic_for_discovery_timestamp",
                topic_slug=topic_slug,
            )
            self.catalog.topics[topic_slug] = TopicCatalogEntry(
                topic_slug=topic_slug,
                query="",  # Will be populated later
                folder=topic_slug,
                created_at=datetime.utcnow(),
                last_successful_discovery_at=timestamp,
            )
        else:
            topic_entry = self.catalog.topics[topic_slug]
            topic_entry.last_successful_discovery_at = timestamp
            topic_entry.last_updated = datetime.utcnow()

        logger.info(
            "set_last_discovery_timestamp",
            topic_slug=topic_slug,
            timestamp=timestamp,
        )
        self.save()

    def detect_query_change(self, topic: ResearchTopic, topic_slug: str) -> bool:
        """Check if topic query has changed since last run.

        Phase 7.1: Detects query modifications that should reset discovery timestamp.
        Uses SHA-256 hash comparison for reliable change detection.

        Args:
            topic: The current ResearchTopic configuration
            topic_slug: The topic slug to check

        Returns:
            True if query has changed (should reset timestamp), False otherwise
        """
        if self.catalog is None:
            self.load()

        assert self.catalog is not None
        if topic_slug not in self.catalog.topics:
            logger.debug(
                "topic_not_found_for_change_detection",
                topic_slug=topic_slug,
            )
            return False  # No previous query to compare

        topic_entry: TopicCatalogEntry = self.catalog.topics[topic_slug]

        # Compute current query hash
        current_hash = hashlib.sha256(topic.query.encode("utf-8")).hexdigest()

        # Compare with stored hash
        if topic_entry.query_hash is None:
            logger.info(
                "no_previous_query_hash",
                topic_slug=topic_slug,
                setting_hash=current_hash,
            )
            # Store hash for future comparisons
            topic_entry.query_hash = current_hash
            self.save()
            return False  # First time tracking, not a "change"

        query_changed = current_hash != topic_entry.query_hash

        if query_changed:
            logger.warning(
                "query_change_detected",
                topic_slug=topic_slug,
                old_hash=topic_entry.query_hash,
                new_hash=current_hash,
                old_query=topic_entry.query,
                new_query=topic.query,
            )
            # Update hash
            topic_entry.query_hash = current_hash
            topic_entry.query = topic.query  # Update query text
            self.save()
        else:
            logger.debug(
                "no_query_change",
                topic_slug=topic_slug,
                hash=current_hash,
            )

        return query_changed

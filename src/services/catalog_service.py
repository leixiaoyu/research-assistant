from typing import Optional
import structlog
from src.models.catalog import CatalogRun, TopicCatalogEntry

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
        return self.catalog.get_or_create_topic(topic_slug, query)

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

        return self.catalog.topics[topic_slug].has_paper(paper_id, doi)

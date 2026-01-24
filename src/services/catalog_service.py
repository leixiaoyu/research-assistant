import structlog
from typing import Optional
from datetime import datetime

from src.models.catalog import Catalog, TopicCatalogEntry, CatalogRun
from src.services.config_manager import ConfigManager

logger = structlog.get_logger()

class CatalogService:
    """Manages research catalog and topic deduplication"""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.catalog: Optional[Catalog] = None

    def load(self):
        """Load catalog from disk"""
        self.catalog = self.config_manager.load_catalog()

    def save(self):
        """Save catalog to disk"""
        if self.catalog:
            self.config_manager.save_catalog(self.catalog)

    def get_or_create_topic(self, query: str) -> TopicCatalogEntry:
        """Get existing topic or create new one with deduplication"""
        if not self.catalog:
            self.load()
            
        assert self.catalog is not None
        
        # 1. Normalize query for deduplication checking
        # Simple normalization: lowercase, remove punctuation, strict whitespace
        normalized_query = self._normalize_query_for_matching(query)
        
        # 2. Check existing topics
        for topic in self.catalog.topics.values():
            if self._normalize_query_for_matching(topic.query) == normalized_query:
                logger.info("duplicate_topic_detected", query=query, existing=topic.topic_slug)
                return topic
                
        # 3. Create new
        slug = self.config_manager.generate_topic_slug(query)
        
        # Handle collision by appending hash if needed? 
        # For MVP, if slug exists but query is different, we might have an issue.
        # But generate_topic_slug is deterministic.
        if slug in self.catalog.topics:
            existing = self.catalog.topics[slug]
            if existing.query != query:
                # Collision! Append short hash
                import hashlib
                hash_suffix = hashlib.md5(query.encode()).hexdigest()[:4]
                slug = f"{slug}-{hash_suffix}"
        
        return self.catalog.get_or_create_topic(slug, query)

    def add_run(self, topic_slug: str, run: CatalogRun):
        """Record a research run"""
        if not self.catalog:
            self.load()
            
        assert self.catalog is not None
            
        if topic_slug not in self.catalog.topics:
            raise ValueError(f"Topic not found: {topic_slug}")
            
        topic = self.catalog.topics[topic_slug]
        topic.add_run(run)
        self.save()

    def _normalize_query_for_matching(self, query: str) -> str:
        """Normalize query for fuzzy matching"""
        import re
        # Lowercase
        q = query.lower()
        # Remove common booleans to match intent (optional, maybe too aggressive for MVP?)
        # Let's just normalize whitespace and punctuation for now
        q = re.sub(r'[^\w\s]', '', q)
        q = re.sub(r'\s+', ' ', q).strip()
        return q

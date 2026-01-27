"""
Data models for caching system.

Defines cache configuration and statistics models.
"""

from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class CacheConfig(BaseModel):
    """Cache configuration"""

    model_config = ConfigDict(protected_namespaces=())

    enabled: bool = True
    cache_dir: str = "./cache"

    # TTL settings (seconds)
    ttl_api_hours: int = 1
    ttl_pdf_days: int = 7
    ttl_extraction_days: int = 30

    # Size limits
    max_cache_size_mb: int = 10000  # 10GB default
    auto_cleanup: bool = True

    @property
    def ttl_api_seconds(self) -> int:
        return self.ttl_api_hours * 3600

    @property
    def ttl_pdf_seconds(self) -> int:
        return self.ttl_pdf_days * 86400

    @property
    def ttl_extraction_seconds(self) -> int:
        return self.ttl_extraction_days * 86400


class CacheStats(BaseModel):
    """Cache statistics"""

    model_config = ConfigDict(protected_namespaces=())

    api_cache_size: int = 0
    api_cache_hits: int = 0
    api_cache_misses: int = 0

    pdf_cache_size: int = 0
    pdf_cache_disk_mb: float = 0.0

    extraction_cache_size: int = 0
    extraction_cache_hits: int = 0
    extraction_cache_misses: int = 0

    last_updated: datetime = Field(default_factory=datetime.now)

    @property
    def api_hit_rate(self) -> float:
        """Calculate API cache hit rate"""
        total = self.api_cache_hits + self.api_cache_misses
        if total == 0:
            return 0.0
        return self.api_cache_hits / total

    @property
    def extraction_hit_rate(self) -> float:
        """Calculate extraction cache hit rate"""
        total = self.extraction_cache_hits + self.extraction_cache_misses
        if total == 0:
            return 0.0
        return self.extraction_cache_hits / total

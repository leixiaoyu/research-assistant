"""Data models for caching system."""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime

class CacheConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    enabled: bool = True
    cache_dir: str = "./cache"
    ttl_api_hours: int = 1
    ttl_pdf_days: int = 7
    ttl_extraction_days: int = 30
    max_cache_size_mb: int = 10000
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
        total = self.api_cache_hits + self.api_cache_misses
        return self.api_cache_hits / total if total > 0 else 0.0

    @property
    def extraction_hit_rate(self) -> float:
        total = self.extraction_cache_hits + self.extraction_cache_misses
        return self.extraction_cache_hits / total if total > 0 else 0.0

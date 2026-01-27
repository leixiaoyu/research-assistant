"""Data models for deduplication system."""

from pydantic import BaseModel, Field, ConfigDict
from typing import Set, Dict


class DedupConfig(BaseModel):
    """Deduplication configuration"""
    model_config = ConfigDict(protected_namespaces=())

    enabled: bool = True
    title_similarity_threshold: float = Field(0.90, ge=0.0, le=1.0)
    use_doi_matching: bool = True
    use_title_matching: bool = True


class DedupStats(BaseModel):
    """Deduplication statistics"""
    model_config = ConfigDict(protected_namespaces=())

    total_papers_checked: int = 0
    duplicates_found: int = 0
    duplicates_by_doi: int = 0
    duplicates_by_title: int = 0
    unique_dois_indexed: int = 0
    unique_titles_indexed: int = 0

    @property
    def dedup_rate(self) -> float:
        """Calculate deduplication rate"""
        if self.total_papers_checked == 0:
            return 0.0
        return self.duplicates_found / self.total_papers_checked

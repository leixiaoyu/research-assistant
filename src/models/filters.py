"""Data models for paper filtering and ranking."""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List


class FilterConfig(BaseModel):
    """Paper filtering configuration"""
    model_config = ConfigDict(protected_namespaces=())

    min_citation_count: int = Field(0, ge=0)
    min_year: Optional[int] = Field(None, ge=1900, le=2100)
    max_year: Optional[int] = Field(None, ge=1900, le=2100)
    min_relevance_score: float = Field(0.0, ge=0.0, le=1.0)

    # Scoring weights (must sum to 1.0)
    citation_weight: float = Field(0.30, ge=0.0, le=1.0)
    recency_weight: float = Field(0.20, ge=0.0, le=1.0)
    relevance_weight: float = Field(0.50, ge=0.0, le=1.0)


class PaperScore(BaseModel):
    """Relevance score breakdown for a paper"""
    model_config = ConfigDict(protected_namespaces=())

    paper_id: str
    citation_score: float = Field(0.0, ge=0.0, le=1.0)
    recency_score: float = Field(0.0, ge=0.0, le=1.0)
    text_similarity_score: float = Field(0.0, ge=0.0, le=1.0)
    total_score: float = Field(0.0, ge=0.0, le=1.0)


class FilterStats(BaseModel):
    """Paper filtering statistics"""
    model_config = ConfigDict(protected_namespaces=())

    total_papers_input: int = 0
    papers_filtered_out: int = 0
    papers_ranked: int = 0
    avg_citation_score: float = 0.0
    avg_recency_score: float = 0.0
    avg_relevance_score: float = 0.0

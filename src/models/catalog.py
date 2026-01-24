from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import datetime


class CatalogRun(BaseModel):
    """A single pipeline run for a topic"""

    run_id: str = Field(..., min_length=1)
    date: datetime
    papers_found: int = Field(0, ge=0)
    papers_processed: int = Field(0, ge=0)
    papers_failed: int = Field(0, ge=0)
    papers_skipped: int = Field(0, ge=0)
    timeframe: str
    output_file: str
    total_cost_usd: float = Field(0.0, ge=0.0)
    total_duration_seconds: float = Field(0.0, ge=0.0)


class ProcessedPaper(BaseModel):
    """Reference to a processed paper to avoid re-processing"""

    paper_id: str
    doi: Optional[str] = None
    title: str
    processed_at: datetime
    run_id: str


class TopicCatalogEntry(BaseModel):
    """Catalog entry for a research topic"""

    topic_slug: str
    query: str
    folder: str
    created_at: datetime
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    runs: List[CatalogRun] = Field(default_factory=list)
    processed_papers: List[ProcessedPaper] = Field(default_factory=list)

    def add_run(self, run: CatalogRun):
        """Add a run and update timestamp"""
        self.runs.append(run)
        self.last_updated = datetime.utcnow()

    def has_paper(self, paper_id: str, doi: Optional[str] = None) -> bool:
        """Check if paper already processed"""
        for p in self.processed_papers:
            if p.paper_id == paper_id:
                return True
            if doi and p.doi and p.doi == doi:
                return True
        return False


class Catalog(BaseModel):
    """Master catalog of all research"""

    version: str = "1.0"
    topics: Dict[str, TopicCatalogEntry] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    def get_or_create_topic(self, topic_slug: str, query: str) -> TopicCatalogEntry:
        """Get existing topic or create new entry"""
        if topic_slug not in self.topics:
            self.topics[topic_slug] = TopicCatalogEntry(
                topic_slug=topic_slug,
                query=query,
                folder=topic_slug,
                created_at=datetime.utcnow(),
            )
        self.last_updated = datetime.utcnow()
        return self.topics[topic_slug]

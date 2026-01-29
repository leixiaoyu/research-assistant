"""Data models for checkpoint system."""

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Set
from datetime import datetime


class CheckpointConfig(BaseModel):
    """Checkpoint configuration"""

    model_config = ConfigDict(protected_namespaces=())

    enabled: bool = True
    checkpoint_dir: str = "./checkpoints"
    checkpoint_interval: int = Field(10, ge=1, le=100)  # Save every N papers


class Checkpoint(BaseModel):
    """Checkpoint data for a run"""

    model_config = ConfigDict(protected_namespaces=())

    run_id: str
    processed_paper_ids: List[str] = Field(default_factory=list)
    total_processed: int = 0
    last_updated: datetime = Field(default_factory=datetime.now)
    completed: bool = False

    @property
    def processed_set(self) -> Set[str]:
        """Get processed IDs as a set for O(1) lookup"""
        return set(self.processed_paper_ids)

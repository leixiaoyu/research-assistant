"""Knowledge-graph models (Milestone 9.3).

Defines:
- ``EntityType``: kinds of extracted entities (method, dataset, etc.)
- ``ExtractedEntity``: extracted entity with provenance
- ``ExtractedRelation``: relation between entities (typed via EdgeType)
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.services.intelligence.models.graph import (
    ENTITY_NAME_PATTERN,
    EdgeType,
)


class EntityType(str, Enum):
    """Types of entities extracted from papers (Milestone 9.3).

    Used for knowledge graph construction.
    """

    METHOD = "method"  # e.g., "LoRA", "Chain-of-Thought"
    DATASET = "dataset"  # e.g., "WMT14", "SQuAD"
    METRIC = "metric"  # e.g., "BLEU", "accuracy"
    MODEL = "model"  # e.g., "GPT-4", "LLaMA-2"
    TASK = "task"  # e.g., "machine translation", "QA"
    RESULT = "result"  # e.g., "42.3 BLEU on WMT14"
    HYPERPARAMETER = "hyperparam"  # e.g., "learning_rate=1e-4"


class ExtractedEntity(BaseModel):
    """An entity extracted from a paper (Milestone 9.3).

    Attributes:
        entity_id: Unique entity identifier
        entity_type: Type of entity (method, dataset, etc.)
        name: Canonical name of the entity
        aliases: Alternative names for the entity
        description: Brief description or context
        paper_id: Source paper ID
        section: Section where entity was found
        confidence: Extraction confidence score (0.0-1.0)
        extracted_at: When the entity was extracted
    """

    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Unique entity identifier",
    )
    entity_type: EntityType = Field(..., description="Type of entity")
    name: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Canonical entity name",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Alternative names for the entity",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Brief description or context",
    )
    paper_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Source paper ID",
    )
    section: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Section where entity was found",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score",
    )
    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Extraction timestamp",
    )

    @field_validator("name")
    @classmethod
    def sanitize_entity_name(cls, v: str) -> str:
        """Validate entity names against allowed character pattern (SR-9.3)."""
        v = v.strip()
        if not ENTITY_NAME_PATTERN.match(v):
            raise ValueError(
                f"Entity name contains disallowed characters: {v!r}. "
                "Allowed: alphanumeric, spaces, hyphens, periods, parentheses."
            )
        return v

    @field_validator("aliases")
    @classmethod
    def sanitize_aliases(cls, v: list[str]) -> list[str]:
        """Validate all aliases against allowed character pattern."""
        sanitized = []
        for alias in v:
            alias = alias.strip()
            if not alias:
                continue
            if not ENTITY_NAME_PATTERN.match(alias):
                raise ValueError(
                    f"Alias contains disallowed characters: {alias!r}. "
                    "Allowed: alphanumeric, spaces, hyphens, periods, parentheses."
                )
            sanitized.append(alias)
        return sanitized


class ExtractedRelation(BaseModel):
    """A relationship between entities (Milestone 9.3).

    Attributes:
        relation_id: Unique relation identifier
        relation_type: Type of relation (achieves, uses, etc.)
        source_entity_id: Source entity ID
        target_entity_id: Target entity ID
        context: Supporting text from paper
        paper_id: Source paper ID
        confidence: Extraction confidence score (0.0-1.0)
        extracted_at: When the relation was extracted
    """

    model_config = ConfigDict(extra="forbid")

    relation_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Unique relation identifier",
    )
    relation_type: EdgeType = Field(..., description="Type of relation")
    source_entity_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Source entity ID",
    )
    target_entity_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Target entity ID",
    )
    context: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Supporting text from paper",
    )
    paper_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Source paper ID",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score",
    )
    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Extraction timestamp",
    )

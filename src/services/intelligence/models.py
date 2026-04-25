"""Shared data models for Phase 9: Research Intelligence Layer.

This module defines:
- NodeType and EdgeType enums for graph storage
- GraphNode and GraphEdge models for unified graph operations
- Shared base models used across all milestones
"""

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Entity name validation pattern (SR-9.3)
# Allows alphanumeric, spaces, hyphens, periods, parentheses only
ENTITY_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 .\-()]+$")


class NodeType(str, Enum):
    """Types of nodes in the unified graph.

    Used across all milestones:
    - PAPER: Paper nodes (Milestones 9.1-9.4)
    - ENTITY: Extracted entities (Milestone 9.3)
    - RESULT: Experimental results (Milestone 9.3)
    - TOPIC: Research topics (Milestone 9.4)
    - AUTHOR: Paper authors (Milestone 9.4)
    - VENUE: Publication venues (Milestone 9.4)
    - SUBSCRIPTION: User subscriptions (Milestone 9.1)
    """

    PAPER = "paper"
    ENTITY = "entity"
    RESULT = "result"
    TOPIC = "topic"
    AUTHOR = "author"
    VENUE = "venue"
    SUBSCRIPTION = "subscription"


class EdgeType(str, Enum):
    """Types of edges in the unified graph.

    Citation edges (Milestone 9.2):
    - CITES: Paper A cites Paper B
    - CITED_BY: Paper A is cited by Paper B (reverse of CITES)

    Knowledge edges (Milestone 9.3):
    - MENTIONS: Paper mentions Entity
    - ACHIEVES: Entity (method) achieves Result
    - USES: Paper/Entity uses another Entity
    - COMPARES: Paper compares two Entities
    - IMPROVES: Entity A improves upon Entity B
    - EXTENDS: Entity A extends Entity B
    - EVALUATES_ON: Entity evaluates on Dataset

    Frontier edges (Milestone 9.4):
    - BELONGS_TO: Paper/Entity belongs to Topic
    - AUTHORED_BY: Paper authored by Author
    - PUBLISHED_IN: Paper published in Venue

    Monitoring edges (Milestone 9.1):
    - MATCHES: Paper matches Subscription
    """

    # Citation edges
    CITES = "cites"
    CITED_BY = "cited_by"

    # Knowledge edges
    MENTIONS = "mentions"
    ACHIEVES = "achieves"
    USES = "uses"
    COMPARES = "compares"
    IMPROVES = "improves"
    EXTENDS = "extends"
    EVALUATES_ON = "evaluates_on"
    REQUIRES = "requires"

    # Frontier edges
    BELONGS_TO = "belongs_to"
    AUTHORED_BY = "authored_by"
    PUBLISHED_IN = "published_in"

    # Monitoring edges
    MATCHES = "matches"


class GraphNode(BaseModel):
    """A node in the unified graph.

    Attributes:
        node_id: Unique node identifier
        node_type: Type of node (paper, entity, etc.)
        properties: Node properties as key-value pairs
        version: Optimistic locking version number
        created_at: When the node was created
        updated_at: When the node was last updated
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "node_id": "paper:arxiv:2301.12345",
                "node_type": "paper",
                "properties": {
                    "title": "Attention Is All You Need",
                    "year": 2017,
                    "citation_count": 50000,
                },
                "version": 1,
            }
        },
    )

    node_id: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Unique node identifier",
    )
    node_type: NodeType = Field(..., description="Type of node")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Node properties as key-value pairs",
    )
    version: int = Field(
        default=1,
        ge=1,
        description="Optimistic locking version number",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update timestamp",
    )

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, v: str) -> str:
        """Validate node ID format."""
        v = v.strip()
        if not v:
            raise ValueError("Node ID cannot be empty")
        # Allow alphanumeric, colons, hyphens, underscores, periods
        if not re.match(r"^[A-Za-z0-9:._-]+$", v):
            raise ValueError(
                f"Invalid node ID format: {v!r}. "
                "Allowed: alphanumeric, colons, periods, hyphens, underscores."
            )
        return v


class GraphEdge(BaseModel):
    """An edge in the unified graph.

    Attributes:
        edge_id: Unique edge identifier
        edge_type: Type of edge (cites, mentions, etc.)
        source_id: Source node ID
        target_id: Target node ID
        properties: Edge properties as key-value pairs
        version: Optimistic locking version number
        created_at: When the edge was created
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "edge_id": "edge:cites:paper1:paper2",
                "edge_type": "cites",
                "source_id": "paper:arxiv:2301.12345",
                "target_id": "paper:arxiv:1706.03762",
                "properties": {
                    "context": "Building on the transformer architecture..."
                },
            }
        },
    )

    edge_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Unique edge identifier",
    )
    edge_type: EdgeType = Field(..., description="Type of edge")
    source_id: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Source node ID",
    )
    target_id: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Target node ID",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Edge properties as key-value pairs",
    )
    version: int = Field(
        default=1,
        ge=1,
        description="Optimistic locking version number",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )

    @field_validator("edge_id", "source_id", "target_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        """Validate edge and node ID format."""
        v = v.strip()
        if not v:
            raise ValueError("ID cannot be empty")
        if not re.match(r"^[A-Za-z0-9:._-]+$", v):
            raise ValueError(
                f"Invalid ID format: {v!r}. "
                "Allowed: alphanumeric, colons, periods, hyphens, underscores."
            )
        return v


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


class RelationType(str, Enum):
    """Types of relations between entities (Milestone 9.3).

    Used for knowledge graph edges.
    """

    ACHIEVES = "achieves"  # Method ACHIEVES Result on Dataset
    USES = "uses"  # Paper USES Method
    EVALUATES_ON = "evaluates_on"  # Model EVALUATES_ON Dataset
    IMPROVES = "improves"  # Method A IMPROVES Method B
    COMPARES = "compares"  # Paper COMPARES Method A to Method B
    EXTENDS = "extends"  # Method A EXTENDS Method B
    REQUIRES = "requires"  # Method REQUIRES Hyperparameter


class TrendStatus(str, Enum):
    """Status of a research trend (Milestone 9.4)."""

    EMERGING = "emerging"  # Low volume, high acceleration
    GROWING = "growing"  # High volume, positive acceleration
    PEAKED = "peaked"  # High volume, zero/negative acceleration
    DECLINING = "declining"  # Decreasing volume
    NICHE = "niche"  # Consistently low volume


class GapType(str, Enum):
    """Types of research gaps (Milestone 9.4)."""

    INTERSECTION = "intersection"  # Topic A + Topic B underexplored
    APPLICATION = "application"  # Method not applied to domain
    SCALE = "scale"  # Not tested at different scales
    MODALITY = "modality"  # Not explored in other modalities
    REPLICATION = "replication"  # Results not independently verified


class PaperSource(str, Enum):
    """Sources for paper monitoring (Milestone 9.1).

    MVP Scope: Only ARXIV has RSS/Atom feeds enabling efficient monitoring.
    Other sources require polling with API rate limits.
    """

    ARXIV = "arxiv"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    HUGGINGFACE = "huggingface"
    OPENALEX = "openalex"


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
    relation_type: RelationType = Field(..., description="Type of relation")
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


class SubscriptionLimitError(ValueError):
    """Raised when subscription limits are exceeded (SR-9.5).

    Limits:
    - Max 50 subscriptions per user
    - Max 100 keywords per subscription
    - Max 1000 papers checked per monitoring cycle
    """

    def __init__(self, limit_type: str, current: int, max_allowed: int):
        message = (
            f"Subscription limit exceeded: {limit_type} "
            f"(current: {current}, max: {max_allowed}). "
            "Remove inactive subscriptions or upgrade plan."
        )
        super().__init__(message)
        self.limit_type = limit_type
        self.current = current
        self.max_allowed = max_allowed


class OptimisticLockError(Exception):
    """Raised when optimistic locking detects a concurrent modification.

    This indicates another process modified the record between read and write.
    The caller should retry the operation with fresh data.
    """

    def __init__(self, node_id: str, expected_version: int, actual_version: int):
        message = (
            f"Concurrent modification detected for {node_id}: "
            f"expected version {expected_version}, found {actual_version}. "
            "Retry with fresh data."
        )
        super().__init__(message)
        self.node_id = node_id
        self.expected_version = expected_version
        self.actual_version = actual_version


class GraphStoreError(Exception):
    """Base exception for graph store operations."""

    pass


class NodeNotFoundError(GraphStoreError):
    """Raised when a node is not found in the graph."""

    def __init__(self, node_id: str):
        super().__init__(f"Node not found: {node_id}")
        self.node_id = node_id


class EdgeNotFoundError(GraphStoreError):
    """Raised when an edge is not found in the graph."""

    def __init__(self, edge_id: str):
        super().__init__(f"Edge not found: {edge_id}")
        self.edge_id = edge_id


class ReferentialIntegrityError(GraphStoreError):
    """Raised when an operation would violate referential integrity."""

    def __init__(self, message: str):
        super().__init__(message)

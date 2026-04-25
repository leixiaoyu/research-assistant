"""Graph kernel models: nodes, edges, and the type enums they reference.

Decision (item 15): ``version``, ``created_at``, ``updated_at`` are
**backend-managed** and intentionally remain non-Optional with
auto-generating defaults. Callers (storage layer) overwrite them on
read. We do not expose a separate DTO/persistence split because:

1. The persistence boundary is single-owner (the SQLite store) and
   already wires these fields explicitly on every read.
2. Pydantic strict mode (``extra="forbid"``) still enforces type
   safety on every construction, so a None slipping in would fail
   validation immediately.
3. Lower churn for downstream milestones (9.1-9.4) which want a single
   GraphNode/GraphEdge type to pass around.

If a future milestone needs to construct GraphNodes pre-persistence
without timestamps it should populate them with sentinel values rather
than relax the schema.
"""

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

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
        version: Optimistic locking version number (backend-managed)
        created_at: When the node was created (backend-managed)
        updated_at: When the node was last updated (backend-managed)
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
        description="Optimistic locking version number (backend-managed)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp (backend-managed)",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update timestamp (backend-managed)",
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
        version: Optimistic locking version number (backend-managed)
        created_at: When the edge was created (backend-managed)
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
        description="Optimistic locking version number (backend-managed)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp (backend-managed)",
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

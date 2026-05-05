"""Domain models for the citation graph (Milestone 9.2).

These models layer over the shared ``GraphNode`` / ``GraphEdge`` kernel
defined in ``src.services.intelligence.models.graph``. They give the
citation subsystem typed accessors and validation appropriate to the
domain (years, citation counts, DOIs, S2 ids) without forcing those
concerns into the kernel — which is reused by knowledge, frontier,
and monitoring milestones too.

Design notes:
- Pydantic V2 with ``extra="forbid"`` per project standards (see
  CLAUDE.md). Conversion helpers (``to_graph_node`` / ``to_graph_edge``)
  produce kernel objects ready for ``GraphStore.add_nodes_batch`` /
  ``add_edges_batch``.
- ``paper_id`` is the canonical identifier used inside the graph. We
  always emit the ``paper:`` prefix so node ids never collide with
  other ``NodeType`` (entity, topic, author, venue) — a constraint
  the storage layer's ``node_id`` regex enforces but does not assert.
- ``CitationDirection`` is the small enum the graph builder uses to
  decide which S2/OpenAlex endpoints to hit. The full Week-2
  ``CrawlConfig`` enum from the spec lives in ``crawler.py`` once it
  ships; we keep this one minimal so we don't pre-commit to choices
  the crawler will revisit.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.services.intelligence.citation._id_validation import (
    CANONICAL_NODE_ID_PATTERN,
)
from src.services.intelligence.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
)

# Identifier scrubber: keep only chars allowed by GraphNode.node_id
# (alphanumeric, colons, periods, hyphens, underscores). Anything else
# is collapsed to ``_`` so external ids with slashes/spaces still
# produce valid node ids.
_ID_SAFE_CHARS = re.compile(r"[^A-Za-z0-9:._-]+")


def _normalize_id_segment(value: str) -> str:
    """Return a node-id-safe segment: scrub disallowed chars, trim.

    Collapses runs of unsafe characters (slash, space, etc.) into a
    single underscore so the resulting node id matches the kernel's
    validation regex without losing readability.
    """
    cleaned = _ID_SAFE_CHARS.sub("_", value.strip()).strip("_")
    if not cleaned:
        raise ValueError("Identifier segment is empty after sanitization")
    return cleaned


def make_paper_node_id(source: str, external_id: str) -> str:
    """Build a canonical ``paper:<source>:<external_id>`` node id.

    Args:
        source: Origin of the id (``s2``, ``openalex``, ``arxiv``,
            ``doi``). Must be a short identifier; sanitized.
        external_id: The provider-specific id. Sanitized for storage.

    Returns:
        A node id of the form ``paper:<source>:<external_id>``.

    Raises:
        ValueError: If either segment is empty after sanitization.
    """
    return f"paper:{_normalize_id_segment(source)}:{_normalize_id_segment(external_id)}"


def make_citation_edge_id(citing_id: str, cited_id: str) -> str:
    """Build a deterministic edge id for a CITES relationship.

    Deterministic edge ids let bulk inserts be idempotent within a
    single transaction (a duplicate raises a constraint error before
    any partial write — see ``add_edges_batch``).

    Implementation note: the citing/cited node ids both contain ``:``
    separators (e.g. ``paper:s2:abc``). Concatenating them with another
    ``:`` would let two distinct pairs collide on the resulting edge
    id (``a:b:c + d:e:f`` and ``a:b + c:d:e:f`` both yield
    ``a:b:c:d:e:f``), which would silently merge unrelated edges in
    ``add_edges_batch``. We hash the pair with SHA-256 to get a
    collision-free, deterministic, length-bounded id. Only the first
    32 hex chars (128 bits) are kept to stay within the storage
    layer's ``edge_id`` length budget; collisions remain
    cryptographically negligible at our scale (~10^9 edges).
    """
    # The two node ids are already validated, but we still scrub here
    # to defend against future callers passing raw external ids.
    citing = _normalize_id_segment(citing_id)
    cited = _normalize_id_segment(cited_id)
    digest = hashlib.sha256(f"{citing}|{cited}".encode("utf-8")).hexdigest()[:32]
    return f"edge:cites:{digest}"


class LegacyCitationDirection(str, Enum):
    """Direction of citation traversal for the graph builder (legacy).

    - ``OUT``: outgoing — the seed paper's *references* (what it cites).
    - ``IN``: incoming — papers that *cite* the seed.
    - ``BOTH``: both directions (one round-trip per side).

    .. deprecated::
        This enum is the legacy graph-builder direction. New code that
        operates the BFS crawler should use :class:`CrawlDirection` which
        uses ``FORWARD`` / ``BACKWARD`` / ``BOTH`` to match the spec
        vocabulary (REQ-9.2.2). ``CitationDirection`` is kept as an alias
        for backward compatibility with ``graph_builder.py`` callers.
    """

    OUT = "out"
    IN = "in"
    BOTH = "both"


# Backward-compatible alias so all existing callers (graph_builder.py,
# tests, public __init__.py) continue to work without changes.
CitationDirection = LegacyCitationDirection


class CrawlDirection(str, Enum):
    """Direction of the BFS expansion (REQ-9.2.2 §574-592) — canonical enum.

    This is the single source of truth for crawler direction across the
    citation package. The legacy :class:`LegacyCitationDirection` (aliased
    as ``CitationDirection``) uses OUT/IN semantics for the depth=1 graph
    builder; this enum uses FORWARD/BACKWARD per the spec vocabulary.

    - ``FORWARD``: follow papers that *cite* the current paper (incoming).
    - ``BACKWARD``: follow papers that the current paper *references*
      (outgoing — what the paper cites).
    - ``BOTH``: union of the two (one provider call per direction).
    """

    FORWARD = "forward"
    BACKWARD = "backward"
    BOTH = "both"


class CitationNode(BaseModel):
    """A paper in the citation graph (REQ-9.2.1).

    This is the domain model layered over ``GraphNode``. It carries the
    fields the spec calls out (paper_id, external_ids, title, year,
    citation_count, reference_count, is_in_corpus, influence_score,
    fetched_at) and validates them more strictly than a generic
    properties dict would.

    Construction expectations:
    - ``paper_id`` is the canonical graph node id. Use
      :func:`make_paper_node_id` to build one from a provider id.
    - ``external_ids`` maps short source codes (``s2``, ``doi``,
      ``arxiv``, ``openalex``) to their provider value. Optional fields
      are simply omitted; we never store ``None`` values in the graph
      properties dict.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "paper_id": "paper:s2:204e3073870fae3d05bcbc2f6a8e263d9b72e776",
                "external_ids": {
                    "s2": "204e3073870fae3d05bcbc2f6a8e263d9b72e776",
                    "doi": "10.5555/3295222.3295349",
                    "arxiv": "1706.03762",
                },
                "title": "Attention Is All You Need",
                "year": 2017,
                "citation_count": 95000,
                "reference_count": 36,
                "is_in_corpus": False,
                "influence_score": None,
            }
        },
    )

    paper_id: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Canonical graph node id (use make_paper_node_id).",
    )
    external_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Source-to-id map (e.g. {'s2': '...', 'doi': '...'}).",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Paper title.",
    )
    year: int | None = Field(
        default=None,
        ge=1800,
        le=2100,
        description="Publication year, if known.",
    )
    citation_count: int = Field(
        default=0,
        ge=0,
        description="How many papers cite this one (per source).",
    )
    reference_count: int = Field(
        default=0,
        ge=0,
        description="How many papers this one references.",
    )
    is_in_corpus: bool = Field(
        default=False,
        description="True iff we have full text for this paper locally.",
    )
    influence_score: float | None = Field(
        default=None,
        description="Optional precomputed influence score (e.g. PageRank).",
    )
    influential_citation_count: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Semantic Scholar 'influentialCitationCount' metric. None when the "
            "source does not provide it (e.g. OpenAlex)."
        ),
    )
    publication_date: date | None = Field(
        default=None,
        description=(
            "Full publication date when known. Optional: many providers only "
            "report year-precision; in those cases use 'year' instead."
        ),
    )
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this record was fetched from the source.",
    )

    @field_validator("paper_id")
    @classmethod
    def _validate_paper_id(cls, v: str) -> str:
        """Mirror the storage-layer node id regex.

        We re-validate here so callers fail at model construction time
        with a meaningful error, rather than at the SQLite boundary.
        Uses the canonical post-normalization pattern from
        :mod:`_id_validation` (single source of truth — H-A1).
        """
        v = v.strip()
        if not v:
            raise ValueError("paper_id cannot be empty")
        if not CANONICAL_NODE_ID_PATTERN.match(v):
            raise ValueError(
                f"Invalid paper_id format: {v!r}. "
                "Allowed: alphanumeric, colons, periods, hyphens, underscores."
            )
        return v

    @field_validator("external_ids")
    @classmethod
    def _validate_external_ids(cls, v: dict[str, str]) -> dict[str, str]:
        """Reject empty source codes or empty id values.

        We don't try to enumerate the allowed source codes — the spec
        explicitly anticipates new sources (Crossref, OpenAlex variants)
        — but every entry must be a non-empty key/value pair so we
        don't pollute the graph with ``{"": ""}`` placeholders.
        """
        for key, value in v.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("external_ids keys must be non-empty source codes")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"external_ids[{key!r}] must be a non-empty string")
        return v

    def to_graph_node(self) -> GraphNode:
        """Project the domain model onto a kernel ``GraphNode``.

        Properties dict is built explicitly — we omit ``None`` values
        rather than store JSON nulls — and ``fetched_at`` is serialized
        to ISO-8601 so the storage layer's JSON dump is stable.
        """
        properties: dict[str, Any] = {
            "title": self.title,
            "external_ids": dict(self.external_ids),
            "citation_count": self.citation_count,
            "reference_count": self.reference_count,
            "is_in_corpus": self.is_in_corpus,
            "fetched_at": self.fetched_at.isoformat(),
        }
        if self.year is not None:
            properties["year"] = self.year
        if self.influence_score is not None:
            properties["influence_score"] = self.influence_score
        if self.influential_citation_count is not None:
            properties["influential_citation_count"] = self.influential_citation_count
        if self.publication_date is not None:
            properties["publication_date"] = self.publication_date.isoformat()

        return GraphNode(
            node_id=self.paper_id,
            node_type=NodeType.PAPER,
            properties=properties,
        )


class CitationEdge(BaseModel):
    """A directed citation relationship (REQ-9.2.1).

    Mirrors the spec's ``CitationEdge``. Edges always point from the
    citing paper to the cited paper (``CITES`` semantics). The
    ``is_influential`` flag carries Semantic Scholar's
    ``isInfluential`` signal verbatim when available; OpenAlex does not
    provide this and will leave it ``None``.
    """

    model_config = ConfigDict(extra="forbid")

    citing_paper_id: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Source (citing) paper node id.",
    )
    cited_paper_id: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Target (cited) paper node id.",
    )
    context: str | None = Field(
        default=None,
        max_length=4096,
        description="Snippet around the citation marker, if available.",
    )
    section: str | None = Field(
        default=None,
        max_length=256,
        description="Section the citation appears in (e.g. 'Introduction').",
    )
    is_influential: bool | None = Field(
        default=None,
        description=(
            "Semantic Scholar 'isInfluential' flag. None when the "
            "source does not provide it (e.g. OpenAlex)."
        ),
    )
    source: str = Field(
        default="semantic_scholar",
        min_length=1,
        max_length=64,
        description="Provider that produced this edge (provenance).",
    )

    @field_validator("citing_paper_id", "cited_paper_id")
    @classmethod
    def _validate_ids(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Citation paper ids cannot be empty")
        if not CANONICAL_NODE_ID_PATTERN.match(v):
            raise ValueError(
                f"Invalid citation paper id: {v!r}. "
                "Allowed: alphanumeric, colons, periods, hyphens, underscores."
            )
        return v

    def to_graph_edge(self) -> GraphEdge:
        """Project the domain edge onto a kernel ``GraphEdge``."""
        properties: dict[str, Any] = {"source": self.source}
        if self.context is not None:
            properties["context"] = self.context
        if self.section is not None:
            properties["section"] = self.section
        if self.is_influential is not None:
            properties["is_influential"] = self.is_influential

        return GraphEdge(
            edge_id=make_citation_edge_id(self.citing_paper_id, self.cited_paper_id),
            edge_type=EdgeType.CITES,
            source_id=self.citing_paper_id,
            target_id=self.cited_paper_id,
            properties=properties,
        )


# ---------------------------------------------------------------------------
# Recommendation models (REQ-9.2.5 / Issue #130)
# ---------------------------------------------------------------------------


class RecommendationStrategy(str, Enum):
    """Strategy used to produce a paper recommendation (REQ-9.2.5)."""

    SIMILAR = "similar"
    INFLUENTIAL_PREDECESSOR = "influential_predecessor"
    ACTIVE_SUCCESSOR = "active_successor"
    BRIDGE = "bridge"


class Recommendation(BaseModel):
    """A single paper recommendation produced by ``CitationRecommender``.

    Pydantic V2 strict model (``extra="forbid"``) per project standards.

    Constraints:
    - ``paper_id`` must match the canonical node-id pattern.
    - ``score`` is in [0.0, 1.0]; strategy-specific normalization ensures
      every strategy emits comparable scores.
    - ``seed_paper_id`` must differ from ``paper_id`` — a paper cannot
      recommend itself.
    - ``reasoning`` is a short human-readable explanation (1–512 chars).
    """

    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Canonical node id of the recommended paper.",
    )
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Strategy-specific score in [0.0, 1.0].",
    )
    strategy: RecommendationStrategy = Field(
        ...,
        description="Which strategy produced this recommendation.",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Human-readable explanation of why this paper was recommended.",
    )
    seed_paper_id: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Canonical node id of the seed paper this was recommended for.",
    )

    @field_validator("paper_id", "seed_paper_id")
    @classmethod
    def _validate_id_format(cls, v: str) -> str:
        """Enforce canonical node-id format on both paper ids."""
        v = v.strip()
        if not v:
            raise ValueError("paper id cannot be empty")
        if not CANONICAL_NODE_ID_PATTERN.match(v):
            raise ValueError(
                f"Invalid paper id format: {v!r}. "
                "Allowed: alphanumeric, colons, periods, hyphens, underscores."
            )
        return v

    @model_validator(mode="after")
    def _reject_self_recommendation(self) -> "Recommendation":
        """Ensure the recommended paper differs from the seed."""
        if self.paper_id == self.seed_paper_id:
            raise ValueError(
                f"paper_id and seed_paper_id must differ; both are {self.paper_id!r}"
            )
        return self

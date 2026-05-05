"""Coupling protocol shim for parallel development with issue #128.

# TO BE REPLACED by #128's models — interface-locked for parallel development.

Issue #128 (CouplingAnalyzer — Bibliographic Coupling) is being developed
concurrently. This module defines a minimal ``CouplingAnalyzerProtocol``
and a stub ``CouplingResult`` model so the recommender (issue #130) can
code against a well-typed interface without waiting for #128 to land.

When #128 lands and this branch rebases onto main, the real
``CouplingAnalyzer`` will already satisfy the Protocol implicitly (duck
typing). No production code change will be needed in the recommender.

Interface-lock contract:
- ``CouplingResult.paper_a_id`` / ``paper_b_id`` — canonical node-id format
- ``CouplingResult.coupling_strength`` — float in [0.0, 1.0]
- ``CouplingResult.shared_reference_count`` — non-negative int
- ``CouplingAnalyzerProtocol.analyze_pair(a_id, b_id) -> CouplingResult``
- ``CouplingAnalyzerProtocol.analyze_for_paper(seed_id, candidates, top_k)
  -> list[CouplingResult]``
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from src.services.intelligence.citation._id_validation import (
    CANONICAL_NODE_ID_PATTERN,
    PAPER_ID_MAX_LENGTH,
)


def _validate_paper_id_str(v: str, field_name: str) -> str:
    """Validate a paper id string against the canonical node-id pattern."""
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(v) > PAPER_ID_MAX_LENGTH:
        raise ValueError(
            f"{field_name} length {len(v)} exceeds max {PAPER_ID_MAX_LENGTH}"
        )
    if not CANONICAL_NODE_ID_PATTERN.match(v):
        raise ValueError(
            f"Invalid {field_name} format: {v!r}. "
            "Allowed: alphanumeric, colons, periods, hyphens, underscores."
        )
    return v


class CouplingResult(BaseModel):
    """Result of a bibliographic coupling computation between two papers.

    # TO BE REPLACED by #128's models — interface-locked for parallel development.

    Mirrors the spec contract from issue #128 so the recommender can
    consume coupling results without importing the (not-yet-landed)
    ``CouplingAnalyzer``.

    Validators:
    - ``paper_a_id`` and ``paper_b_id`` must match the canonical node-id
      pattern (alphanumeric, colons, periods, hyphens, underscores).
    - ``coupling_strength`` is clamped to [0.0, 1.0].
    """

    model_config = ConfigDict(extra="forbid", strict=False)

    paper_a_id: str = Field(
        ...,
        min_length=1,
        max_length=PAPER_ID_MAX_LENGTH,
        description="Canonical node id of the first paper.",
    )
    paper_b_id: str = Field(
        ...,
        min_length=1,
        max_length=PAPER_ID_MAX_LENGTH,
        description="Canonical node id of the second paper.",
    )
    coupling_strength: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Bibliographic coupling strength in [0.0, 1.0].",
    )
    shared_reference_count: int = Field(
        default=0,
        ge=0,
        description="Number of references shared by both papers.",
    )
    jaccard_index: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Jaccard index of reference sets: |A ∩ B| / |A ∪ B|. "
            "Zero when either paper has no references."
        ),
    )

    def model_post_init(self, __context: object) -> None:
        """Validate paper ids after field construction."""
        _validate_paper_id_str(self.paper_a_id, "paper_a_id")
        _validate_paper_id_str(self.paper_b_id, "paper_b_id")


@runtime_checkable
class CouplingAnalyzerProtocol(Protocol):
    """Protocol for bibliographic coupling analysis.

    # TO BE REPLACED by #128's models — interface-locked for parallel development.

    The recommender depends on this protocol, not on the concrete
    ``CouplingAnalyzer`` class from issue #128. When #128 lands, the real
    ``CouplingAnalyzer`` will satisfy this protocol implicitly. Tests inject
    mock objects implementing this protocol.

    Methods:
        analyze_pair: Compute coupling between two papers.
        analyze_for_paper: Find the top-k most coupled papers for a seed.
    """

    async def analyze_pair(self, paper_a_id: str, paper_b_id: str) -> "CouplingResult":
        """Compute bibliographic coupling between two papers.

        Args:
            paper_a_id: Canonical node id of the first paper.
            paper_b_id: Canonical node id of the second paper.

        Returns:
            A ``CouplingResult`` with the coupling metrics.
        """
        raise NotImplementedError  # pragma: abstract

    async def analyze_for_paper(
        self,
        seed_id: str,
        candidates: list[str],
        top_k: int = 10,
    ) -> list["CouplingResult"]:
        """Find the top-k most coupled papers for a seed.

        Args:
            seed_id: Canonical node id of the seed paper.
            candidates: Node ids of candidate papers to rank.
            top_k: Maximum number of results to return.

        Returns:
            Coupling results sorted by ``coupling_strength`` descending,
            at most ``top_k`` entries.
        """
        raise NotImplementedError  # pragma: abstract

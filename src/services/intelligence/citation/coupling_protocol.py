"""Coupling protocol for the citation recommender (Milestone 9.2, Issue #130).

Defines :class:`CouplingAnalyzerProtocol` — the structural protocol that
:class:`CitationRecommender` depends on for bibliographic coupling analysis.
The real :class:`CouplingAnalyzer` (PR #147 / Issue #128) satisfies this
protocol implicitly through duck typing; no explicit registration is needed.

Design rationale for keeping the Protocol:
- Decouples the recommender from the concrete ``CouplingAnalyzer`` import
  path, preventing a potential circular-import if the analyzer ever imports
  recommender utilities.
- Tests can inject ``AsyncMock()`` objects that satisfy the protocol without
  importing or constructing the real analyzer.
- Near-zero LOC cost (~15 lines) for meaningful architectural insurance.

``CouplingResult`` is re-exported from :mod:`src.services.intelligence.citation.models`
for backwards-compatibility with any code that imports it from this module.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.services.intelligence.citation.models import CouplingResult

__all__ = [
    "CouplingAnalyzerProtocol",
    "CouplingResult",
]


@runtime_checkable
class CouplingAnalyzerProtocol(Protocol):
    """Protocol for bibliographic coupling analysis.

    The recommender depends on this protocol, not on the concrete
    ``CouplingAnalyzer`` class. When PR #147 landed, the real
    ``CouplingAnalyzer`` began satisfying this protocol implicitly.
    Tests inject mock objects implementing this protocol.

    Methods:
        analyze_pair: Compute coupling between two papers.
        analyze_for_paper: Find the top-k most coupled papers for a seed.
    """

    async def analyze_pair(self, paper_a_id: str, paper_b_id: str) -> CouplingResult:
        """Compute bibliographic coupling between two papers.

        Args:
            paper_a_id: Canonical node id of the first paper.
            paper_b_id: Canonical node id of the second paper.

        Returns:
            A ``CouplingResult`` with the coupling metrics.
        """
        raise NotImplementedError

    async def analyze_for_paper(
        self,
        seed_id: str,
        candidates: list[str],
        top_k: int = 10,
    ) -> list[CouplingResult]:
        """Find the top-k most coupled papers for a seed.

        Args:
            seed_id: Canonical node id of the seed paper.
            candidates: Node ids of candidate papers to rank.
            top_k: Maximum number of results to return.

        Returns:
            Coupling results sorted by ``coupling_strength`` descending,
            at most ``top_k`` entries.
        """
        raise NotImplementedError

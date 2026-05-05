"""Citation-based paper recommender (Milestone 9.2 — REQ-9.2.5 / Issue #130).

Implements four recommendation strategies built on top of the crawler,
coupling, and influence layers:

1. **Similar** — papers with high bibliographic coupling to the seed
   (uses :class:`CouplingAnalyzerProtocol`).
2. **Influential Predecessors** — high-PageRank papers in the backward
   citation chain (uses :class:`CitationCrawler` BACKWARD +
   :class:`InfluenceScorer`).
3. **Active Successors** — recent papers (last 2 years) that cite the
   seed with high ``citation_velocity`` (uses :class:`CitationCrawler`
   FORWARD + :class:`InfluenceScorer`).
4. **Bridge Papers** — papers connecting different citation clusters via
   a simple heuristic: papers cited by the seed *and* also cited by ≥2
   papers in the seed's BFS frontier beyond radius 2 (no NetworkX /
   community-detection libs required).

Design notes
------------
- All four strategies are injected via DI constructor so callers can
  substitute mocks in tests.
- ``recommend_all`` runs all four in ``asyncio.gather`` for concurrency.
  ``return_exceptions=True`` is used so one strategy failure returns a
  partial result and emits ``recommender_strategy_failed_in_recommend_all``
  rather than aborting all strategies.
- Scores are normalized to [0.0, 1.0] per strategy before being wrapped
  in :class:`Recommendation` objects.

  .. warning::
      Scores are **not** cross-comparable between strategies — each
      strategy normalizes independently. Do NOT rank recommendations from
      different strategies against each other by score.

- Every public method validates ``seed_id`` via the canonical
  :func:`_validate_paper_id` (single source of truth in this package).
  ``k`` is validated to be in [1, 100].
- Structured log events emitted: ``recommender_strategy_complete``,
  ``recommender_seed_isolated_returns_empty``,
  ``recommender_strategy_failed``,
  ``recommender_strategy_failed_in_recommend_all``,
  ``recommender_bridge_frontier_truncated``.

Failure semantics
-----------------
Individual strategies propagate exceptions to the caller (fail-hard by
default). In ``recommend_all``, ``asyncio.gather(return_exceptions=True)``
is used so a single strategy failure returns a partial result for the
other strategies, and emits ``recommender_strategy_failed_in_recommend_all``
for each failed strategy.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import structlog

from src.services.intelligence.citation._id_validation import (
    CANONICAL_NODE_ID_PATTERN,
    PAPER_ID_MAX_LENGTH,
)
from src.services.intelligence.citation.coupling_protocol import (
    CouplingAnalyzerProtocol,
)
from src.services.intelligence.citation.crawler import CitationCrawler
from src.services.intelligence.citation.influence_scorer import InfluenceScorer
from src.services.intelligence.citation.models import (
    EdgeType,
    Recommendation,
    RecommendationStrategy,
)
from src.storage.intelligence_graph.connection import _trunc
from src.storage.intelligence_graph.unified_graph import SQLiteGraphStore

logger = structlog.get_logger(__name__)

# Year cutoff for "active successors": papers published in the last N years.
_ACTIVE_SUCCESSOR_YEARS = 2

# BFS radius used to gather seed candidates for similar strategy.
_BFS_RADIUS_SIMILAR = 2

# BFS radius used to gather backward candidates for influential predecessors.
# Kept separate from _BFS_RADIUS_SIMILAR so each strategy can be tuned
# independently without inadvertently changing the other.
_BFS_RADIUS_PREDECESSOR = 2

# Minimum number of "distant papers" (frontier) that must co-cite a bridge
# candidate for it to count as a bridge.
_BRIDGE_MIN_DISTANT_CO_CITERS = 2

# BFS depth for gathering the distant frontier used in bridge detection.
_BRIDGE_FRONTIER_RADIUS = 3

# Hard cap on the distant-frontier size in bridge detection. Large corpora
# can produce thousands of radius-3 nodes which would trigger one
# _get_bfs_neighbors call per node. Capping at 500 prevents pathological
# runtimes while still covering realistic citation graphs.
_BRIDGE_MAX_DISTANT = 500

# Hard cap on the candidate list passed to analyze_for_paper (M-7).
# Large BFS expansions can produce thousands of candidates; capping here
# prevents unbounded work in the coupling analyzer.
_MAX_CANDIDATES = 500

# Valid range for k (applies to all public methods).
_K_MIN = 1
_K_MAX = 100


def _validate_paper_id(paper_id: str) -> None:
    """Validate a paper id against the project's canonical node-id pattern.

    Raises:
        ValueError: If ``paper_id`` is malformed.
    """
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ValueError("paper_id must be a non-empty string")
    if len(paper_id) > PAPER_ID_MAX_LENGTH:
        raise ValueError(
            f"paper_id length {len(paper_id)} exceeds max {PAPER_ID_MAX_LENGTH}"
        )
    if not CANONICAL_NODE_ID_PATTERN.match(paper_id):
        raise ValueError(
            f"Invalid paper_id format: {paper_id!r}. "
            "Allowed: alphanumeric, colons, periods, hyphens, underscores."
        )


def _validate_k(k: int) -> None:
    """Validate that k is in [_K_MIN, _K_MAX].

    Raises:
        ValueError: If ``k`` is outside [1, 100].
    """
    if not _K_MIN <= k <= _K_MAX:
        raise ValueError(f"k must be in [{_K_MIN}, {_K_MAX}]; got {k}")


def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    """Linearly normalize scores to [0.0, 1.0] by dividing by max.

    When all scores are 0.0 (or the dict is empty), all results remain 0.0.
    """
    if not scores:
        return scores
    max_score = max(scores.values())
    if max_score <= 0.0:
        return {k: 0.0 for k in scores}
    return {k: v / max_score for k, v in scores.items()}


def _current_year() -> int:
    """Return the current UTC year. Extracted for testability."""
    return datetime.now(timezone.utc).year


class CitationRecommender:
    """Recommend papers via four citation-based strategies (REQ-9.2.5).

    Constructor requires all collaborators so tests can inject mocks at the
    module boundary (PR #143 H-5 lesson: patch public dependencies, not
    private methods).

    Args:
        coupling: A :class:`CouplingAnalyzerProtocol` for similarity.
        crawler: A :class:`CitationCrawler` for BFS expansion.
        scorer: An :class:`InfluenceScorer` for PageRank + velocity.
        store: A :class:`SQLiteGraphStore` for raw graph reads.
    """

    def __init__(
        self,
        coupling: CouplingAnalyzerProtocol,
        crawler: CitationCrawler,
        scorer: InfluenceScorer,
        store: SQLiteGraphStore,
    ) -> None:
        self._coupling = coupling
        self._crawler = crawler
        self._scorer = scorer
        self._store = store

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def connect(
        cls,
        *,
        db_path: Path | str,
        coupling: CouplingAnalyzerProtocol | None = None,
    ) -> "CitationRecommender":
        """Create a fully-wired ``CitationRecommender`` from a database path.

        Wires together ``SQLiteGraphStore``, ``CitationCrawler``,
        ``InfluenceScorer``, and (optionally) a ``CouplingAnalyzerProtocol``
        so callers do not need to know about the internal collaborators.

        Args:
            db_path: Path to the SQLite database backing the graph store.
            coupling: Optional coupling analyzer. When ``None``, no
                similarity analysis is available; the ``recommend_similar``
                strategy will return empty results or raise on any call
                that reaches the analyzer. In production, PR #128's
                ``CouplingAnalyzer`` should be passed here once it lands.

        Returns:
            A ready-to-use ``CitationRecommender``.
        """
        from src.services.intelligence.citation.crawler import CitationCrawler
        from src.services.intelligence.citation.openalex_client import (
            OpenAlexCitationClient,
        )
        from src.services.intelligence.citation.semantic_scholar_client import (
            SemanticScholarCitationClient,
        )

        store = SQLiteGraphStore(db_path)
        s2_client = SemanticScholarCitationClient()
        openalex_client = OpenAlexCitationClient()
        crawler = CitationCrawler(
            store=store,
            s2_client=s2_client,
            openalex_client=openalex_client,
        )
        scorer = InfluenceScorer(store=store)

        if coupling is None:
            # Use a no-op coupling adapter that always returns empty results.
            # External code (PR #128 / CouplingAnalyzer) should be injected
            # once it lands.
            coupling = _NullCouplingAdapter()  # type: ignore[assignment]

        return cls(
            coupling=coupling,  # type: ignore[arg-type]
            crawler=crawler,
            scorer=scorer,
            store=store,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def recommend_similar(
        self, seed_id: str, k: int = 10
    ) -> list[Recommendation]:
        """Recommend papers similar to ``seed_id`` by coupling strength.

        Candidate set: all nodes discovered via BFS expansion of the seed
        at radius 1–2 (using the stored graph; no new provider calls).
        Coupling is computed via ``CouplingAnalyzerProtocol.analyze_for_paper``.

        Args:
            seed_id: Canonical node id of the seed paper.
            k: Maximum number of recommendations to return (1–100).

        Returns:
            Up to ``k`` :class:`Recommendation` objects, sorted by score
            descending.

        Raises:
            ValueError: If ``seed_id`` is malformed or ``k`` is out of range.
        """
        _validate_paper_id(seed_id)
        _validate_k(k)
        strategy = RecommendationStrategy.SIMILAR
        try:
            candidates = self._get_bfs_neighbors(seed_id, radius=_BFS_RADIUS_SIMILAR)
            candidates = [c for c in candidates if c != seed_id]

            if not candidates:
                logger.info(
                    "recommender_seed_isolated_returns_empty",
                    seed_id=seed_id,
                    strategy=strategy.value,
                )
                return []

            # Cap candidate list to prevent unbounded coupling work.
            if len(candidates) > _MAX_CANDIDATES:
                candidates = candidates[:_MAX_CANDIDATES]

            coupling_results = await self._coupling.analyze_for_paper(
                seed_id, candidates, top_k=k
            )

            recommendations: list[Recommendation] = []
            for cr in coupling_results:
                other_id = cr.paper_b_id if cr.paper_a_id == seed_id else cr.paper_a_id
                if other_id == seed_id:
                    continue
                reasoning = (
                    f"Top coupling (Jaccard={cr.jaccard_index:.2f}, "
                    f"{cr.shared_reference_count} shared references)"
                )
                recommendations.append(
                    Recommendation(
                        paper_id=other_id,
                        score=cr.coupling_strength,
                        strategy=strategy,
                        reasoning=reasoning,
                        seed_paper_id=seed_id,
                    )
                )

            recommendations.sort(key=lambda r: r.score, reverse=True)
            recommendations = recommendations[:k]

            logger.info(
                "recommender_strategy_complete",
                seed_id=seed_id,
                strategy=strategy.value,
                count=len(recommendations),
            )
            return recommendations

        except Exception as exc:
            logger.error(
                "recommender_strategy_failed",
                seed_id=seed_id,
                strategy=strategy.value,
                error=_trunc(exc),
            )
            raise

    async def recommend_influential_predecessors(
        self, seed_id: str, k: int = 10
    ) -> list[Recommendation]:
        """Recommend high-influence papers in the backward citation chain.

        Performs a BACKWARD BFS crawl (papers that ``seed_id`` cites,
        transitively), then ranks by ``pagerank_score`` from
        :class:`InfluenceScorer`.

        Args:
            seed_id: Canonical node id of the seed paper.
            k: Maximum number of recommendations to return (1–100).

        Returns:
            Up to ``k`` :class:`Recommendation` objects sorted by score
            descending.

        Raises:
            ValueError: If ``seed_id`` is malformed or ``k`` is out of range.
        """
        _validate_paper_id(seed_id)
        _validate_k(k)
        strategy = RecommendationStrategy.INFLUENTIAL_PREDECESSOR
        try:
            backward_nodes = self._get_bfs_neighbors(
                seed_id,
                radius=_BFS_RADIUS_PREDECESSOR,
                direction="outgoing",
            )
            backward_nodes = [n for n in backward_nodes if n != seed_id]

            if not backward_nodes:
                logger.info(
                    "recommender_seed_isolated_returns_empty",
                    seed_id=seed_id,
                    strategy=strategy.value,
                )
                return []

            metrics_list = await self._scorer.compute_for_graph(backward_nodes)
            metrics_by_id = {m.paper_id: m for m in metrics_list}

            # pagerank_score is already in [0.0, 1.0] from InfluenceScorer.
            ranked = sorted(
                backward_nodes,
                key=lambda nid: (
                    metrics_by_id.get(nid).pagerank_score  # type: ignore[union-attr]
                    if metrics_by_id.get(nid)
                    else 0.0
                ),
                reverse=True,
            )
            ranked = ranked[:k]

            recommendations: list[Recommendation] = []
            for nid in ranked:
                m = metrics_by_id.get(nid)
                pr = m.pagerank_score if m else 0.0
                reasoning = (
                    f"PageRank={pr:.4f}, " "cited by seed via backward citation chain"
                )
                recommendations.append(
                    Recommendation(
                        paper_id=nid,
                        score=pr,
                        strategy=strategy,
                        reasoning=reasoning,
                        seed_paper_id=seed_id,
                    )
                )

            logger.info(
                "recommender_strategy_complete",
                seed_id=seed_id,
                strategy=strategy.value,
                count=len(recommendations),
            )
            return recommendations

        except Exception as exc:
            logger.error(
                "recommender_strategy_failed",
                seed_id=seed_id,
                strategy=strategy.value,
                error=_trunc(exc),
            )
            raise

    async def recommend_active_successors(
        self, seed_id: str, k: int = 10
    ) -> list[Recommendation]:
        """Recommend recent papers that cite the seed with high velocity.

        Performs a FORWARD BFS crawl (papers that cite ``seed_id``), then
        filters to papers published within the last
        :data:`_ACTIVE_SUCCESSOR_YEARS` years (from the current UTC year).
        Results are ranked by ``citation_velocity`` (normalized by the
        max velocity in the result set).

        Args:
            seed_id: Canonical node id of the seed paper.
            k: Maximum number of recommendations to return (1–100).

        Returns:
            Up to ``k`` :class:`Recommendation` objects sorted by score
            descending.

        Raises:
            ValueError: If ``seed_id`` is malformed or ``k`` is out of range.
        """
        _validate_paper_id(seed_id)
        _validate_k(k)
        strategy = RecommendationStrategy.ACTIVE_SUCCESSOR
        try:
            forward_nodes = self._get_bfs_neighbors(
                seed_id,
                radius=_BFS_RADIUS_SIMILAR,
                direction="incoming",
            )
            forward_nodes = [n for n in forward_nodes if n != seed_id]

            if not forward_nodes:
                logger.info(
                    "recommender_seed_isolated_returns_empty",
                    seed_id=seed_id,
                    strategy=strategy.value,
                )
                return []

            # Filter by publication year.
            cutoff_year = _current_year() - _ACTIVE_SUCCESSOR_YEARS
            recent_nodes = self._filter_by_year(forward_nodes, cutoff_year)

            if not recent_nodes:
                logger.info(
                    "recommender_seed_isolated_returns_empty",
                    seed_id=seed_id,
                    strategy=strategy.value,
                )
                return []

            metrics_list = await self._scorer.compute_for_graph(recent_nodes)
            metrics_by_id = {m.paper_id: m for m in metrics_list}

            # Normalize velocity by the max in the result set.
            velocity_map = {
                nid: (
                    metrics_by_id[nid].citation_velocity
                    if nid in metrics_by_id
                    else 0.0
                )
                for nid in recent_nodes
            }
            normalized = _normalize_scores(velocity_map)

            ranked = sorted(
                recent_nodes, key=lambda nid: normalized.get(nid, 0.0), reverse=True
            )
            ranked = ranked[:k]

            recommendations: list[Recommendation] = []
            for nid in ranked:
                m = metrics_by_id.get(nid)
                vel = m.citation_velocity if m else 0.0
                norm_score = normalized.get(nid, 0.0)
                reasoning = (
                    f"velocity={vel:.2f} citations/year, " f"published ≥{cutoff_year}"
                )
                recommendations.append(
                    Recommendation(
                        paper_id=nid,
                        score=norm_score,
                        strategy=strategy,
                        reasoning=reasoning,
                        seed_paper_id=seed_id,
                    )
                )

            logger.info(
                "recommender_strategy_complete",
                seed_id=seed_id,
                strategy=strategy.value,
                count=len(recommendations),
            )
            return recommendations

        except Exception as exc:
            logger.error(
                "recommender_strategy_failed",
                seed_id=seed_id,
                strategy=strategy.value,
                error=_trunc(exc),
            )
            raise

    async def recommend_bridge_papers(
        self, seed_id: str, k: int = 10
    ) -> list[Recommendation]:
        """Recommend papers that bridge different citation clusters.

        Heuristic (no NetworkX / community-detection libs required):
        1. Collect all papers cited by the seed (radius-2 backward BFS).
        2. Collect a "distant frontier" at radius-3 backward BFS.
           The distant frontier is capped at :data:`_BRIDGE_MAX_DISTANT`
           nodes to prevent pathological runtimes on large corpora.
        3. A candidate is a "bridge" if it appears in the seed's radius-2
           neighborhood AND is also cited by ≥
           :data:`_BRIDGE_MIN_DISTANT_CO_CITERS` distinct papers in the
           distant frontier (i.e., it connects the seed's cluster to
           distant clusters).
        4. Score = bridge_count (number of distinct distant co-citers),
           normalized by max bridge_count.

        Args:
            seed_id: Canonical node id of the seed paper.
            k: Maximum number of recommendations to return (1–100).

        Returns:
            Up to ``k`` :class:`Recommendation` objects sorted by score
            descending.

        Raises:
            ValueError: If ``seed_id`` is malformed or ``k`` is out of range.
        """
        _validate_paper_id(seed_id)
        _validate_k(k)
        strategy = RecommendationStrategy.BRIDGE
        try:
            # Radius-2 neighbors of seed (candidates).
            r2_nodes = self._get_bfs_neighbors(
                seed_id,
                radius=2,
                direction="outgoing",
            )
            r2_nodes = [n for n in r2_nodes if n != seed_id]

            if not r2_nodes:
                logger.info(
                    "recommender_seed_isolated_returns_empty",
                    seed_id=seed_id,
                    strategy=strategy.value,
                )
                return []

            r2_set = set(r2_nodes)

            # Radius-3 "distant" neighbors.
            r3_nodes = self._get_bfs_neighbors(
                seed_id,
                radius=_BRIDGE_FRONTIER_RADIUS,
                direction="outgoing",
            )
            # Distant = in r3 but NOT in r2 (radius > 2 from seed).
            distant_nodes = [n for n in r3_nodes if n not in r2_set and n != seed_id]

            # Cap the frontier to bound per-node BFS calls (H-3).
            if len(distant_nodes) > _BRIDGE_MAX_DISTANT:
                distant_nodes = distant_nodes[:_BRIDGE_MAX_DISTANT]
                logger.info(
                    "recommender_bridge_frontier_truncated",
                    seed_id=seed_id,
                    cap=_BRIDGE_MAX_DISTANT,
                )

            # Count how many distinct distant nodes cite each r2 candidate.
            # "Cite" in the backward direction means: the distant node
            # references the candidate (outgoing edge from distant → candidate).
            bridge_counts: dict[str, int] = {}
            for distant in distant_nodes:
                # What does this distant node reference?
                cited_by_distant = self._get_bfs_neighbors(
                    distant,
                    radius=1,
                    direction="outgoing",
                )
                for cited in cited_by_distant:
                    if cited in r2_set:
                        bridge_counts[cited] = bridge_counts.get(cited, 0) + 1

            # Keep only candidates with sufficient co-citation bridge count.
            bridge_candidates = {
                nid: count
                for nid, count in bridge_counts.items()
                if count >= _BRIDGE_MIN_DISTANT_CO_CITERS
            }

            if not bridge_candidates:
                logger.info(
                    "recommender_seed_isolated_returns_empty",
                    seed_id=seed_id,
                    strategy=strategy.value,
                )
                return []

            # Normalize bridge counts.
            normalized = _normalize_scores(
                {k: float(v) for k, v in bridge_candidates.items()}
            )

            ranked = sorted(
                bridge_candidates.keys(),
                key=lambda nid: normalized.get(nid, 0.0),
                reverse=True,
            )
            ranked = ranked[:k]

            recommendations: list[Recommendation] = []
            for nid in ranked:
                raw_count = bridge_candidates[nid]
                norm_score = normalized.get(nid, 0.0)
                reasoning = (
                    f"Bridge paper: co-cited by {raw_count} distant papers "
                    f"(radius >{_BFS_RADIUS_SIMILAR}) in the citation frontier"
                )
                recommendations.append(
                    Recommendation(
                        paper_id=nid,
                        score=norm_score,
                        strategy=strategy,
                        reasoning=reasoning,
                        seed_paper_id=seed_id,
                    )
                )

            logger.info(
                "recommender_strategy_complete",
                seed_id=seed_id,
                strategy=strategy.value,
                count=len(recommendations),
            )
            return recommendations

        except Exception as exc:
            logger.error(
                "recommender_strategy_failed",
                seed_id=seed_id,
                strategy=strategy.value,
                error=_trunc(exc),
            )
            raise

    async def recommend_all(
        self, seed_id: str, k_per_strategy: int = 5
    ) -> dict[RecommendationStrategy, list[Recommendation]]:
        """Run all four strategies concurrently and return a combined dict.

        Uses ``asyncio.gather(return_exceptions=True)`` so a single strategy
        failure returns a partial result for the remaining strategies rather
        than aborting all of them. Each failing strategy is logged with
        ``recommender_strategy_failed_in_recommend_all`` and contributes an
        empty list in the returned dict.

        Args:
            seed_id: Canonical node id of the seed paper.
            k_per_strategy: ``k`` passed to each individual strategy (1–100).

        Returns:
            A dict mapping each :class:`RecommendationStrategy` to its
            list of :class:`Recommendation` objects. Strategies that raised
            an exception map to an empty list.

        Raises:
            ValueError: If ``seed_id`` is malformed or ``k_per_strategy``
                is out of range.
        """
        _validate_paper_id(seed_id)
        _validate_k(k_per_strategy)

        strategies = [
            RecommendationStrategy.SIMILAR,
            RecommendationStrategy.INFLUENTIAL_PREDECESSOR,
            RecommendationStrategy.ACTIVE_SUCCESSOR,
            RecommendationStrategy.BRIDGE,
        ]
        coroutines = [
            self.recommend_similar(seed_id, k=k_per_strategy),
            self.recommend_influential_predecessors(seed_id, k=k_per_strategy),
            self.recommend_active_successors(seed_id, k=k_per_strategy),
            self.recommend_bridge_papers(seed_id, k=k_per_strategy),
        ]

        # return_exceptions=True: partial results on strategy failure.
        raw_results = await asyncio.gather(*coroutines, return_exceptions=True)

        output: dict[RecommendationStrategy, list[Recommendation]] = {}
        for strategy, result in zip(strategies, raw_results):
            if isinstance(result, BaseException):
                logger.error(
                    "recommender_strategy_failed_in_recommend_all",
                    seed_id=seed_id,
                    strategy=strategy.value,
                    error=_trunc(result),
                )
                output[strategy] = []
            else:
                output[strategy] = result
        return output

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_bfs_neighbors(
        self,
        node_id: str,
        radius: int,
        direction: str = "both",
    ) -> list[str]:
        """Return all node ids reachable from ``node_id`` within ``radius`` hops.

        Uses :meth:`SQLiteGraphStore.traverse` with the CITES edge type.
        The returned list excludes the start node itself.

        Args:
            node_id: Starting node id.
            radius: Maximum BFS depth.
            direction: ``"outgoing"``, ``"incoming"``, or ``"both"``.

        Returns:
            List of neighbor node ids (order not guaranteed).
        """
        nodes = self._store.traverse(
            node_id,
            edge_types=[EdgeType.CITES],
            max_depth=radius,
            direction=direction,
        )
        return [n.node_id for n in nodes]

    def _filter_by_year(self, node_ids: list[str], cutoff_year: int) -> list[str]:
        """Return only node ids whose stored year is >= ``cutoff_year``.

        Nodes without a year property (or whose property is missing from
        the graph) are excluded.

        Args:
            node_ids: Candidate node ids to check.
            cutoff_year: Minimum publication year (inclusive).

        Returns:
            Filtered list of node ids.
        """
        kept: list[str] = []
        for nid in node_ids:
            node = self._store.get_node(nid)
            if node is None:
                continue
            props = node.properties or {}
            year = props.get("year")
            if year is None:
                # Try publication_date as fallback.
                pub_date_str = props.get("publication_date")
                if pub_date_str:
                    try:
                        year = int(pub_date_str[:4])
                    except (ValueError, TypeError):
                        year = None
            if year is not None:
                try:
                    year_int = int(year)
                except (ValueError, TypeError):
                    continue
                if year_int >= cutoff_year:
                    kept.append(nid)
        return kept


class _NullCouplingAdapter:
    """No-op coupling adapter used when no real CouplingAnalyzer is available.

    This satisfies :class:`CouplingAnalyzerProtocol` and is the default
    wired by :meth:`CitationRecommender.connect` until PR #128 lands and
    provides a real implementation.
    """

    async def analyze_pair(self, paper_a_id: str, paper_b_id: str) -> object:
        """Always returns an empty result (no coupling data available)."""
        return None

    async def analyze_for_paper(
        self,
        seed_id: str,
        candidates: list[str],
        top_k: int = 10,
    ) -> list[object]:
        """Always returns an empty list (no coupling data available)."""
        return []

"""Milestone 9.2: Citation Graph Intelligence (Week 1 + 1.5 surface).

This package builds and persists citation graphs from external APIs
(Semantic Scholar primary, OpenAlex fallback) using the Phase 9
``GraphStore`` for storage. Week 1 + 1.5 deliver depth=1 graph
construction; BFS crawler, coupling analyzer, influence scorer, and
recommender are deferred to follow-up PRs (Weeks 2-3).

Public surface:

- :class:`CitationNode` / :class:`CitationEdge` — domain models that
  layer over the shared ``GraphNode`` / ``GraphEdge`` kernel.
- :class:`CitationDirection` — small enum for traversal direction.
- :class:`SemanticScholarCitationClient` — primary citation source.
- :class:`OpenAlexCitationClient` — fallback citation source with
  polite-pool email convention.
- :class:`CitationGraphBuilder` / :class:`GraphBuildResult` — composes
  the two clients and persists via ``GraphStore.add_nodes_batch`` /
  ``add_edges_batch`` (depth=1 only; BFS crawl is Week 2).

Architecture choice (recorded for downstream milestones):
We deliberately built **dedicated citation clients alongside** the
existing ``SemanticScholarProvider`` / ``OpenAlexProvider`` in
``src/services/providers/`` rather than extending those. The existing
providers implement the ``DiscoveryProvider`` ABC for keyword-based
paper search and have request shapes, response parsers, and retry
semantics that don't transfer cleanly to the
``/paper/{id}/citations|references`` and ``/works/{id}`` endpoints.
Wrapping them would require either widening the ABC or layering an
adapter on top — both add coupling without saving meaningful code.
"""

from src.services.intelligence.citation.graph_builder import (
    CitationGraphBuilder,
    GraphBuildResult,
)
from src.services.intelligence.citation.models import (
    CitationDirection,
    CitationEdge,
    CitationNode,
    make_citation_edge_id,
    make_paper_node_id,
)
from src.services.intelligence.citation.openalex_client import (
    OpenAlexCitationClient,
)
from src.services.intelligence.citation.semantic_scholar_client import (
    SemanticScholarCitationClient,
)

__all__ = [
    # Models
    "CitationDirection",
    "CitationEdge",
    "CitationNode",
    "make_citation_edge_id",
    "make_paper_node_id",
    # Clients
    "SemanticScholarCitationClient",
    "OpenAlexCitationClient",
    # Builder
    "CitationGraphBuilder",
    "GraphBuildResult",
]

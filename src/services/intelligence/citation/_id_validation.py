"""Canonical paper-ID validation constants for the citation package.

Why two patterns?
-----------------
Provider IDs and canonical graph-node IDs have different character sets:

``RAW_PROVIDER_ID_PATTERN``
    Accepts the full character set that provider APIs return in their id
    fields, including ``/`` (needed for DOIs, e.g. ``10.18653/v1/...``).
    Used by:
    - :mod:`semantic_scholar_client` — validates the raw S2 paper id before
      it is used to construct an HTTP URL.
    - :mod:`crawler` — validates the seed paper id supplied by the caller
      (which may be a DOI or arXiv id with slashes).

``CANONICAL_NODE_ID_PATTERN``
    Accepts only characters that pass the storage-layer ``node_id`` regex
    enforced by ``GraphNode``. Excludes ``/`` because slashes are scrubbed
    to ``_`` by :func:`models._normalize_id_segment` before a node id is
    constructed.  Used by:
    - :class:`CitationNode` — validates ``paper_id`` (the graph node id,
      which is always ``paper:{source}:{normalized_external_id}``).
    - :class:`CitationEdge` — validates ``citing_paper_id`` /
      ``cited_paper_id`` (same shape as CitationNode.paper_id).
    - :mod:`influence_scorer` — validates the caller-supplied ``paper_id``
      at the scorer boundary (by that point the id is already normalized).

Single source of truth
-----------------------
Before this module existed the same two regexes were duplicated across
``models.py``, ``crawler.py``, ``influence_scorer.py``, and
``semantic_scholar_client.py``.  A single definition here lets all of them
import the appropriate constant and ensures any future loosening or
tightening is applied consistently.
"""

from __future__ import annotations

import re

# Allow-list for raw provider IDs (before normalization).  Includes ``/``
# so DOIs (``10.18653/v1/...``) and arXiv forms (``arxiv:1706.03762``)
# are accepted.  ``://`` and ``..`` are still blocked by the separate
# forbidden-substring checks in the callers that need SSRF protection.
RAW_PROVIDER_ID_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9:./_\-]+$")

# Allow-list for canonical graph-node IDs (post-normalization).  Excludes
# ``/`` because the storage layer's ``node_id`` column rejects it and
# :func:`models._normalize_id_segment` collapses slashes to ``_`` before
# emitting a node id.
CANONICAL_NODE_ID_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9:._-]+$")

# Shared length cap used everywhere.  512 characters leaves comfortable
# headroom for realistic provider IDs (S2 native hex = 64 chars, DOIs
# rarely exceed ~100) while bounding worst-case URL length and rejecting
# payload-stuffing attempts.
PAPER_ID_MAX_LENGTH: int = 512

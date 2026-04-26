"""Tests for citation domain models (Milestone 9.2 — Week 1)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.services.intelligence.citation.models import (
    CitationDirection,
    CitationEdge,
    CitationNode,
    _normalize_id_segment,
    make_citation_edge_id,
    make_paper_node_id,
)
from src.services.intelligence.models import EdgeType, NodeType

# ---------------------------------------------------------------------------
# _normalize_id_segment
# ---------------------------------------------------------------------------


def test_normalize_id_segment_passes_safe_input():
    assert _normalize_id_segment("abc.123-DEF") == "abc.123-DEF"


def test_normalize_id_segment_collapses_unsafe_runs():
    # slashes and spaces collapse to a single underscore
    assert _normalize_id_segment("10.18653/v1/2020 paper") == "10.18653_v1_2020_paper"


def test_normalize_id_segment_strips_surrounding_whitespace():
    assert _normalize_id_segment("  abc  ") == "abc"


def test_normalize_id_segment_rejects_empty_string():
    with pytest.raises(ValueError, match="empty after sanitization"):
        _normalize_id_segment("")


def test_normalize_id_segment_rejects_only_unsafe_chars():
    # All chars get replaced and stripped → empty result
    with pytest.raises(ValueError, match="empty after sanitization"):
        _normalize_id_segment("///")


# ---------------------------------------------------------------------------
# make_paper_node_id
# ---------------------------------------------------------------------------


def test_make_paper_node_id_builds_canonical_form():
    node_id = make_paper_node_id("s2", "204e3073870fae3d05bcbc2f6a8e263d9b72e776")
    assert node_id == "paper:s2:204e3073870fae3d05bcbc2f6a8e263d9b72e776"


def test_make_paper_node_id_sanitizes_doi_with_slashes():
    node_id = make_paper_node_id("doi", "10.18653/v1/2020.acl-main.1")
    assert node_id == "paper:doi:10.18653_v1_2020.acl-main.1"
    # Must satisfy GraphNode.node_id regex
    import re

    assert re.match(r"^[A-Za-z0-9:._-]+$", node_id)


def test_make_paper_node_id_rejects_empty_external_id():
    with pytest.raises(ValueError):
        make_paper_node_id("s2", "")


def test_make_paper_node_id_rejects_empty_source():
    with pytest.raises(ValueError):
        make_paper_node_id("", "abc123")


# ---------------------------------------------------------------------------
# make_citation_edge_id
# ---------------------------------------------------------------------------


def test_make_citation_edge_id_is_deterministic():
    e1 = make_citation_edge_id("paper:s2:abc", "paper:s2:def")
    e2 = make_citation_edge_id("paper:s2:abc", "paper:s2:def")
    assert e1 == e2 == "edge:cites:paper:s2:abc:paper:s2:def"


def test_make_citation_edge_id_directional_difference():
    forward = make_citation_edge_id("paper:s2:abc", "paper:s2:def")
    reverse = make_citation_edge_id("paper:s2:def", "paper:s2:abc")
    assert forward != reverse


def test_make_citation_edge_id_sanitizes_inputs():
    edge_id = make_citation_edge_id("paper s2 abc", "paper/def")
    # Spaces and slashes get scrubbed
    assert " " not in edge_id
    assert "/" not in edge_id


# ---------------------------------------------------------------------------
# CitationDirection enum
# ---------------------------------------------------------------------------


def test_citation_direction_values():
    assert CitationDirection.OUT.value == "out"
    assert CitationDirection.IN.value == "in"
    assert CitationDirection.BOTH.value == "both"


def test_citation_direction_membership():
    assert CitationDirection("out") is CitationDirection.OUT
    assert CitationDirection("in") is CitationDirection.IN
    assert CitationDirection("both") is CitationDirection.BOTH


def test_citation_direction_rejects_unknown_value():
    with pytest.raises(ValueError):
        CitationDirection("sideways")


# ---------------------------------------------------------------------------
# CitationNode — happy path & defaults
# ---------------------------------------------------------------------------


def test_citation_node_minimal_construction():
    node = CitationNode(paper_id="paper:s2:abc123", title="A Paper")
    assert node.paper_id == "paper:s2:abc123"
    assert node.title == "A Paper"
    assert node.year is None
    assert node.citation_count == 0
    assert node.reference_count == 0
    assert node.is_in_corpus is False
    assert node.influence_score is None
    assert node.external_ids == {}
    assert isinstance(node.fetched_at, datetime)
    assert node.fetched_at.tzinfo == timezone.utc


def test_citation_node_full_construction():
    node = CitationNode(
        paper_id="paper:s2:abc",
        external_ids={"s2": "abc", "doi": "10.1/2"},
        title="Attention Is All You Need",
        year=2017,
        citation_count=95000,
        reference_count=36,
        is_in_corpus=True,
        influence_score=0.91,
    )
    assert node.year == 2017
    assert node.influence_score == 0.91
    assert node.is_in_corpus is True
    assert node.external_ids["doi"] == "10.1/2"


# ---------------------------------------------------------------------------
# CitationNode — validators
# ---------------------------------------------------------------------------


def test_citation_node_paper_id_strips_whitespace():
    node = CitationNode(paper_id="  paper:s2:abc  ", title="t")
    assert node.paper_id == "paper:s2:abc"


def test_citation_node_paper_id_rejects_empty_after_strip():
    with pytest.raises(ValidationError) as exc:
        CitationNode(paper_id="   ", title="t")
    assert "cannot be empty" in str(exc.value) or "at least 1 character" in str(
        exc.value
    )


def test_citation_node_paper_id_rejects_invalid_chars():
    with pytest.raises(ValidationError, match="Invalid paper_id format"):
        CitationNode(paper_id="paper:s2:abc/def", title="t")


def test_citation_node_paper_id_rejects_min_length_violation():
    with pytest.raises(ValidationError):
        CitationNode(paper_id="", title="t")


def test_citation_node_title_required():
    with pytest.raises(ValidationError):
        CitationNode(paper_id="paper:s2:abc", title="")


def test_citation_node_year_lower_bound():
    with pytest.raises(ValidationError):
        CitationNode(paper_id="paper:s2:abc", title="t", year=1799)


def test_citation_node_year_upper_bound():
    with pytest.raises(ValidationError):
        CitationNode(paper_id="paper:s2:abc", title="t", year=2101)


def test_citation_node_year_accepts_valid_range():
    node = CitationNode(paper_id="paper:s2:abc", title="t", year=2017)
    assert node.year == 2017


def test_citation_node_citation_count_negative_rejected():
    with pytest.raises(ValidationError):
        CitationNode(paper_id="paper:s2:abc", title="t", citation_count=-1)


def test_citation_node_reference_count_negative_rejected():
    with pytest.raises(ValidationError):
        CitationNode(paper_id="paper:s2:abc", title="t", reference_count=-1)


def test_citation_node_external_ids_rejects_empty_key():
    with pytest.raises(ValidationError, match="non-empty source codes"):
        CitationNode(paper_id="paper:s2:abc", title="t", external_ids={"": "value"})


def test_citation_node_external_ids_rejects_whitespace_key():
    with pytest.raises(ValidationError, match="non-empty source codes"):
        CitationNode(paper_id="paper:s2:abc", title="t", external_ids={"   ": "value"})


def test_citation_node_external_ids_rejects_empty_value():
    with pytest.raises(ValidationError, match="must be a non-empty string"):
        CitationNode(paper_id="paper:s2:abc", title="t", external_ids={"s2": ""})


def test_citation_node_external_ids_rejects_whitespace_value():
    with pytest.raises(ValidationError, match="must be a non-empty string"):
        CitationNode(paper_id="paper:s2:abc", title="t", external_ids={"s2": "   "})


def test_citation_node_external_ids_rejects_non_string_key():
    # Pydantic itself coerces here when possible; but ints will raise
    with pytest.raises(ValidationError):
        CitationNode.model_validate(
            {
                "paper_id": "paper:s2:abc",
                "title": "t",
                "external_ids": {123: "value"},
            }
        )


def test_citation_node_external_ids_rejects_non_string_value():
    with pytest.raises(ValidationError):
        CitationNode.model_validate(
            {
                "paper_id": "paper:s2:abc",
                "title": "t",
                "external_ids": {"s2": 123},
            }
        )


def test_citation_node_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        CitationNode.model_validate(
            {
                "paper_id": "paper:s2:abc",
                "title": "t",
                "unknown_field": "x",
            }
        )


# ---------------------------------------------------------------------------
# CitationNode.to_graph_node
# ---------------------------------------------------------------------------


def test_citation_node_to_graph_node_minimal():
    node = CitationNode(paper_id="paper:s2:abc", title="My Paper")
    graph_node = node.to_graph_node()
    assert graph_node.node_id == "paper:s2:abc"
    assert graph_node.node_type == NodeType.PAPER
    props = graph_node.properties
    assert props["title"] == "My Paper"
    assert props["citation_count"] == 0
    assert props["reference_count"] == 0
    assert props["is_in_corpus"] is False
    assert props["external_ids"] == {}
    # year and influence_score must be omitted, not present as None
    assert "year" not in props
    assert "influence_score" not in props
    assert "fetched_at" in props
    # ISO-8601 string
    assert isinstance(props["fetched_at"], str)
    assert "T" in props["fetched_at"]


def test_citation_node_to_graph_node_includes_year_and_influence():
    node = CitationNode(
        paper_id="paper:s2:abc",
        title="Paper",
        year=2020,
        influence_score=0.5,
    )
    props = node.to_graph_node().properties
    assert props["year"] == 2020
    assert props["influence_score"] == 0.5


def test_citation_node_to_graph_node_external_ids_copied():
    ext = {"s2": "abc", "doi": "10.1/2"}
    node = CitationNode(paper_id="paper:s2:abc", title="t", external_ids=ext)
    props = node.to_graph_node().properties
    # Defensive: verify it's a copy, mutating the result doesn't leak back
    props["external_ids"]["new"] = "x"
    assert "new" not in node.external_ids


# ---------------------------------------------------------------------------
# CitationEdge — happy path & validators
# ---------------------------------------------------------------------------


def test_citation_edge_minimal_construction():
    edge = CitationEdge(
        citing_paper_id="paper:s2:a",
        cited_paper_id="paper:s2:b",
    )
    assert edge.citing_paper_id == "paper:s2:a"
    assert edge.cited_paper_id == "paper:s2:b"
    assert edge.context is None
    assert edge.section is None
    assert edge.is_influential is None
    assert edge.source == "semantic_scholar"


def test_citation_edge_full_construction():
    edge = CitationEdge(
        citing_paper_id="paper:s2:a",
        cited_paper_id="paper:s2:b",
        context="As shown in [1]...",
        section="Introduction",
        is_influential=True,
        source="openalex",
    )
    assert edge.context == "As shown in [1]..."
    assert edge.section == "Introduction"
    assert edge.is_influential is True
    assert edge.source == "openalex"


def test_citation_edge_strips_id_whitespace():
    edge = CitationEdge(
        citing_paper_id="  paper:s2:a  ",
        cited_paper_id="paper:s2:b",
    )
    assert edge.citing_paper_id == "paper:s2:a"


def test_citation_edge_rejects_blank_citing_id():
    with pytest.raises(ValidationError):
        CitationEdge(citing_paper_id="   ", cited_paper_id="paper:s2:b")


def test_citation_edge_rejects_invalid_citing_id():
    with pytest.raises(ValidationError, match="Invalid citation paper id"):
        CitationEdge(citing_paper_id="paper s2 a", cited_paper_id="paper:s2:b")


def test_citation_edge_rejects_invalid_cited_id():
    with pytest.raises(ValidationError, match="Invalid citation paper id"):
        CitationEdge(citing_paper_id="paper:s2:a", cited_paper_id="paper/b")


def test_citation_edge_rejects_blank_source():
    with pytest.raises(ValidationError):
        CitationEdge(
            citing_paper_id="paper:s2:a", cited_paper_id="paper:s2:b", source=""
        )


def test_citation_edge_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        CitationEdge.model_validate(
            {
                "citing_paper_id": "paper:s2:a",
                "cited_paper_id": "paper:s2:b",
                "unknown_field": "x",
            }
        )


# ---------------------------------------------------------------------------
# CitationEdge.to_graph_edge
# ---------------------------------------------------------------------------


def test_citation_edge_to_graph_edge_minimal():
    edge = CitationEdge(
        citing_paper_id="paper:s2:a",
        cited_paper_id="paper:s2:b",
    )
    g = edge.to_graph_edge()
    assert g.source_id == "paper:s2:a"
    assert g.target_id == "paper:s2:b"
    assert g.edge_type == EdgeType.CITES
    assert g.edge_id == "edge:cites:paper:s2:a:paper:s2:b"
    # Only source property when no extras
    assert g.properties == {"source": "semantic_scholar"}


def test_citation_edge_to_graph_edge_full_properties():
    edge = CitationEdge(
        citing_paper_id="paper:s2:a",
        cited_paper_id="paper:s2:b",
        context="ctx",
        section="Methods",
        is_influential=False,
        source="openalex",
    )
    g = edge.to_graph_edge()
    assert g.properties == {
        "source": "openalex",
        "context": "ctx",
        "section": "Methods",
        "is_influential": False,
    }


def test_citation_edge_to_graph_edge_omits_none_properties():
    # context=None and is_influential=None — should not appear in props
    edge = CitationEdge(
        citing_paper_id="paper:s2:a",
        cited_paper_id="paper:s2:b",
        section="Intro",
    )
    g = edge.to_graph_edge()
    assert "context" not in g.properties
    assert "is_influential" not in g.properties
    assert g.properties["section"] == "Intro"
    assert g.properties["source"] == "semantic_scholar"

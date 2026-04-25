"""Tests for intelligence layer shared models.

Tests cover:
- NodeType and EdgeType enums
- GraphNode and GraphEdge models
- Entity and relation models
- Validation and sanitization
- Exception classes
"""

import pytest
from datetime import datetime

from src.services.intelligence.models import (
    NodeType,
    EdgeType,
    GraphNode,
    GraphEdge,
    EntityType,
    RelationType,
    TrendStatus,
    GapType,
    PaperSource,
    ExtractedEntity,
    ExtractedRelation,
    SubscriptionLimitError,
    OptimisticLockError,
    GraphStoreError,
    NodeNotFoundError,
    EdgeNotFoundError,
    ReferentialIntegrityError,
    ENTITY_NAME_PATTERN,
)


class TestNodeType:
    """Tests for NodeType enum."""

    def test_all_node_types_defined(self) -> None:
        """Verify all expected node types are defined."""
        expected = {
            "paper",
            "entity",
            "result",
            "topic",
            "author",
            "venue",
            "subscription",
        }
        actual = {nt.value for nt in NodeType}
        assert actual == expected

    def test_node_type_is_string_enum(self) -> None:
        """Verify NodeType is a string enum."""
        assert isinstance(NodeType.PAPER.value, str)
        assert NodeType.PAPER == "paper"

    def test_node_type_from_string(self) -> None:
        """Verify NodeType can be created from string."""
        assert NodeType("paper") == NodeType.PAPER
        assert NodeType("entity") == NodeType.ENTITY


class TestEdgeType:
    """Tests for EdgeType enum."""

    def test_citation_edge_types(self) -> None:
        """Verify citation edge types are defined."""
        assert EdgeType.CITES.value == "cites"
        assert EdgeType.CITED_BY.value == "cited_by"

    def test_knowledge_edge_types(self) -> None:
        """Verify knowledge edge types are defined."""
        knowledge_edges = {
            "mentions",
            "achieves",
            "uses",
            "compares",
            "improves",
            "extends",
            "evaluates_on",
            "requires",
        }
        actual = {et.value for et in EdgeType if et.value in knowledge_edges}
        assert knowledge_edges <= actual

    def test_frontier_edge_types(self) -> None:
        """Verify frontier edge types are defined."""
        assert EdgeType.BELONGS_TO.value == "belongs_to"
        assert EdgeType.AUTHORED_BY.value == "authored_by"
        assert EdgeType.PUBLISHED_IN.value == "published_in"

    def test_monitoring_edge_types(self) -> None:
        """Verify monitoring edge types are defined."""
        assert EdgeType.MATCHES.value == "matches"


class TestGraphNode:
    """Tests for GraphNode model."""

    def test_create_minimal_node(self) -> None:
        """Test creating a node with minimal required fields."""
        node = GraphNode(
            node_id="paper:arxiv:2301.12345",
            node_type=NodeType.PAPER,
        )
        assert node.node_id == "paper:arxiv:2301.12345"
        assert node.node_type == NodeType.PAPER
        assert node.properties == {}
        assert node.version == 1

    def test_create_node_with_properties(self) -> None:
        """Test creating a node with properties."""
        props = {"title": "Test Paper", "year": 2024}
        node = GraphNode(
            node_id="paper:arxiv:2401.00001",
            node_type=NodeType.PAPER,
            properties=props,
        )
        assert node.properties == props

    def test_node_id_validation_valid(self) -> None:
        """Test valid node IDs pass validation."""
        valid_ids = [
            "paper:arxiv:2301.12345",
            "entity:method:lora",
            "topic:llm-alignment",
            "node_123",
            "Node.Test-1",
        ]
        for node_id in valid_ids:
            node = GraphNode(node_id=node_id, node_type=NodeType.PAPER)
            assert node.node_id == node_id

    def test_node_id_validation_invalid(self) -> None:
        """Test invalid node IDs are rejected."""
        invalid_ids = [
            "",
            "  ",
            "node with spaces",
            "node/with/slashes",
            "node<script>",
            "node;drop table",
        ]
        for node_id in invalid_ids:
            with pytest.raises(ValueError):
                GraphNode(node_id=node_id, node_type=NodeType.PAPER)

    def test_node_id_whitespace_stripped(self) -> None:
        """Test node ID whitespace is stripped."""
        node = GraphNode(
            node_id="  paper:test  ",
            node_type=NodeType.PAPER,
        )
        assert node.node_id == "paper:test"

    def test_node_version_defaults_to_one(self) -> None:
        """Test version defaults to 1."""
        node = GraphNode(node_id="test:node", node_type=NodeType.PAPER)
        assert node.version == 1

    def test_node_timestamps_auto_generated(self) -> None:
        """Test timestamps are auto-generated."""
        node = GraphNode(node_id="test:node", node_type=NodeType.PAPER)
        assert isinstance(node.created_at, datetime)
        assert isinstance(node.updated_at, datetime)

    def test_node_json_serialization(self) -> None:
        """Test node can be serialized to JSON."""
        node = GraphNode(
            node_id="paper:test",
            node_type=NodeType.PAPER,
            properties={"title": "Test"},
        )
        data = node.model_dump(mode="json")
        assert data["node_id"] == "paper:test"
        assert data["node_type"] == "paper"


class TestGraphEdge:
    """Tests for GraphEdge model."""

    def test_create_minimal_edge(self) -> None:
        """Test creating an edge with minimal required fields."""
        edge = GraphEdge(
            edge_id="edge:cites:a:b",
            edge_type=EdgeType.CITES,
            source_id="paper:a",
            target_id="paper:b",
        )
        assert edge.edge_id == "edge:cites:a:b"
        assert edge.edge_type == EdgeType.CITES
        assert edge.source_id == "paper:a"
        assert edge.target_id == "paper:b"
        assert edge.properties == {}

    def test_create_edge_with_properties(self) -> None:
        """Test creating an edge with properties."""
        props = {"context": "Building on previous work..."}
        edge = GraphEdge(
            edge_id="edge:cites:a:b",
            edge_type=EdgeType.CITES,
            source_id="paper:a",
            target_id="paper:b",
            properties=props,
        )
        assert edge.properties == props

    def test_edge_id_validation(self) -> None:
        """Test edge ID validation."""
        with pytest.raises(ValueError):
            GraphEdge(
                edge_id="edge with spaces",
                edge_type=EdgeType.CITES,
                source_id="paper:a",
                target_id="paper:b",
            )

    def test_edge_source_target_validation(self) -> None:
        """Test source and target ID validation."""
        with pytest.raises(ValueError):
            GraphEdge(
                edge_id="edge:test",
                edge_type=EdgeType.CITES,
                source_id="",
                target_id="paper:b",
            )

    def test_edge_id_empty_validation(self) -> None:
        """Test empty edge_id is rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            GraphEdge(
                edge_id="   ",  # Whitespace only
                edge_type=EdgeType.CITES,
                source_id="paper:a",
                target_id="paper:b",
            )

    def test_edge_target_empty_validation(self) -> None:
        """Test empty target_id is rejected."""
        with pytest.raises(ValueError):
            GraphEdge(
                edge_id="edge:test",
                edge_type=EdgeType.CITES,
                source_id="paper:a",
                target_id="   ",
            )

    def test_edge_version_defaults_to_one(self) -> None:
        """Test version defaults to 1."""
        edge = GraphEdge(
            edge_id="edge:test",
            edge_type=EdgeType.CITES,
            source_id="paper:a",
            target_id="paper:b",
        )
        assert edge.version == 1


class TestEntityType:
    """Tests for EntityType enum."""

    def test_all_entity_types_defined(self) -> None:
        """Verify all expected entity types are defined."""
        expected = {
            "method",
            "dataset",
            "metric",
            "model",
            "task",
            "result",
            "hyperparam",
        }
        actual = {et.value for et in EntityType}
        assert actual == expected


class TestRelationType:
    """Tests for RelationType enum."""

    def test_all_relation_types_defined(self) -> None:
        """Verify all expected relation types are defined."""
        expected = {
            "achieves",
            "uses",
            "evaluates_on",
            "improves",
            "compares",
            "extends",
            "requires",
        }
        actual = {rt.value for rt in RelationType}
        assert actual == expected


class TestTrendStatus:
    """Tests for TrendStatus enum."""

    def test_all_trend_statuses_defined(self) -> None:
        """Verify all expected trend statuses are defined."""
        expected = {"emerging", "growing", "peaked", "declining", "niche"}
        actual = {ts.value for ts in TrendStatus}
        assert actual == expected


class TestGapType:
    """Tests for GapType enum."""

    def test_all_gap_types_defined(self) -> None:
        """Verify all expected gap types are defined."""
        expected = {"intersection", "application", "scale", "modality", "replication"}
        actual = {gt.value for gt in GapType}
        assert actual == expected


class TestPaperSource:
    """Tests for PaperSource enum."""

    def test_all_paper_sources_defined(self) -> None:
        """Verify all expected paper sources are defined."""
        expected = {"arxiv", "semantic_scholar", "huggingface", "openalex"}
        actual = {ps.value for ps in PaperSource}
        assert actual == expected


class TestExtractedEntity:
    """Tests for ExtractedEntity model."""

    def test_create_valid_entity(self) -> None:
        """Test creating a valid entity."""
        entity = ExtractedEntity(
            entity_id="entity:method:lora",
            entity_type=EntityType.METHOD,
            name="LoRA",
            paper_id="paper:arxiv:2301.12345",
            confidence=0.95,
        )
        assert entity.name == "LoRA"
        assert entity.confidence == 0.95

    def test_entity_name_sanitization_valid(self) -> None:
        """Test valid entity names pass sanitization."""
        valid_names = [
            "LoRA",
            "GPT-4",
            "BERT-base",
            "alpha-helix (protein)",
            "F1-score",
            "WMT14 EN-DE",
        ]
        for name in valid_names:
            entity = ExtractedEntity(
                entity_id="entity:test",
                entity_type=EntityType.METHOD,
                name=name,
                paper_id="paper:test",
                confidence=0.9,
            )
            assert entity.name == name

    def test_entity_name_sanitization_invalid(self) -> None:
        """Test invalid entity names are rejected (SR-9.3)."""
        invalid_names = [
            "<script>alert('xss')</script>",
            "name\nwith\nnewlines",
            "name\twith\ttabs",
            "unicode\u0000null",
            "special!@#$%^&*",
        ]
        for name in invalid_names:
            with pytest.raises(ValueError, match="disallowed characters"):
                ExtractedEntity(
                    entity_id="entity:test",
                    entity_type=EntityType.METHOD,
                    name=name,
                    paper_id="paper:test",
                    confidence=0.9,
                )

    def test_entity_name_whitespace_stripped(self) -> None:
        """Test entity name whitespace is stripped."""
        entity = ExtractedEntity(
            entity_id="entity:test",
            entity_type=EntityType.METHOD,
            name="  LoRA  ",
            paper_id="paper:test",
            confidence=0.9,
        )
        assert entity.name == "LoRA"

    def test_entity_aliases_sanitization(self) -> None:
        """Test alias sanitization."""
        entity = ExtractedEntity(
            entity_id="entity:test",
            entity_type=EntityType.METHOD,
            name="LoRA",
            aliases=["Low-Rank Adaptation", "lora-adapter"],
            paper_id="paper:test",
            confidence=0.9,
        )
        assert entity.aliases == ["Low-Rank Adaptation", "lora-adapter"]

    def test_entity_aliases_invalid_rejected(self) -> None:
        """Test invalid aliases are rejected."""
        with pytest.raises(ValueError, match="disallowed characters"):
            ExtractedEntity(
                entity_id="entity:test",
                entity_type=EntityType.METHOD,
                name="LoRA",
                aliases=["<invalid>"],
                paper_id="paper:test",
                confidence=0.9,
            )

    def test_entity_aliases_empty_stripped(self) -> None:
        """Test empty aliases are stripped."""
        entity = ExtractedEntity(
            entity_id="entity:test",
            entity_type=EntityType.METHOD,
            name="LoRA",
            aliases=["", "  ", "valid-alias"],
            paper_id="paper:test",
            confidence=0.9,
        )
        assert entity.aliases == ["valid-alias"]

    def test_entity_confidence_range(self) -> None:
        """Test confidence must be in [0, 1]."""
        with pytest.raises(ValueError):
            ExtractedEntity(
                entity_id="entity:test",
                entity_type=EntityType.METHOD,
                name="Test",
                paper_id="paper:test",
                confidence=1.5,
            )


class TestExtractedRelation:
    """Tests for ExtractedRelation model."""

    def test_create_valid_relation(self) -> None:
        """Test creating a valid relation."""
        relation = ExtractedRelation(
            relation_id="rel:achieves:1:2",
            relation_type=RelationType.ACHIEVES,
            source_entity_id="entity:method:lora",
            target_entity_id="entity:result:42bleu",
            paper_id="paper:arxiv:2301.12345",
            confidence=0.85,
        )
        assert relation.relation_type == RelationType.ACHIEVES
        assert relation.confidence == 0.85

    def test_relation_with_context(self) -> None:
        """Test relation with context text."""
        relation = ExtractedRelation(
            relation_id="rel:test",
            relation_type=RelationType.USES,
            source_entity_id="entity:a",
            target_entity_id="entity:b",
            context="We use method A to achieve...",
            paper_id="paper:test",
            confidence=0.8,
        )
        assert relation.context == "We use method A to achieve..."


class TestSubscriptionLimitError:
    """Tests for SubscriptionLimitError exception."""

    def test_error_message_format(self) -> None:
        """Test error message format."""
        error = SubscriptionLimitError("subscriptions", 50, 50)
        assert "subscriptions" in str(error)
        assert "50" in str(error)
        assert "Remove inactive" in str(error)

    def test_error_attributes(self) -> None:
        """Test error attributes are accessible."""
        error = SubscriptionLimitError("keywords", 150, 100)
        assert error.limit_type == "keywords"
        assert error.current == 150
        assert error.max_allowed == 100

    def test_error_is_value_error(self) -> None:
        """Test error inherits from ValueError."""
        error = SubscriptionLimitError("test", 1, 1)
        assert isinstance(error, ValueError)


class TestOptimisticLockError:
    """Tests for OptimisticLockError exception."""

    def test_error_message_format(self) -> None:
        """Test error message format."""
        error = OptimisticLockError("node:123", 5, 6)
        assert "node:123" in str(error)
        assert "5" in str(error)
        assert "6" in str(error)
        assert "Retry" in str(error)

    def test_error_attributes(self) -> None:
        """Test error attributes are accessible."""
        error = OptimisticLockError("test:node", 10, 11)
        assert error.node_id == "test:node"
        assert error.expected_version == 10
        assert error.actual_version == 11


class TestGraphStoreError:
    """Tests for graph store exceptions."""

    def test_node_not_found_error(self) -> None:
        """Test NodeNotFoundError."""
        error = NodeNotFoundError("missing:node")
        assert "missing:node" in str(error)
        assert error.node_id == "missing:node"
        assert isinstance(error, GraphStoreError)

    def test_edge_not_found_error(self) -> None:
        """Test EdgeNotFoundError."""
        error = EdgeNotFoundError("missing:edge")
        assert "missing:edge" in str(error)
        assert error.edge_id == "missing:edge"
        assert isinstance(error, GraphStoreError)

    def test_referential_integrity_error(self) -> None:
        """Test ReferentialIntegrityError."""
        error = ReferentialIntegrityError("Cannot delete node with edges")
        assert "delete" in str(error)
        assert isinstance(error, GraphStoreError)


class TestEntityNamePattern:
    """Tests for entity name validation pattern."""

    def test_pattern_matches_valid_names(self) -> None:
        """Test pattern matches valid entity names."""
        valid = [
            "LoRA",
            "GPT-4",
            "BERT (large)",
            "F1-score",
            "accuracy",
            "WMT14 EN-DE",
        ]
        for name in valid:
            assert ENTITY_NAME_PATTERN.match(name) is not None

    def test_pattern_rejects_invalid_names(self) -> None:
        """Test pattern rejects invalid entity names."""
        invalid = [
            "<script>",
            "test\nname",
            "special!@#$",
            "",
        ]
        for name in invalid:
            assert ENTITY_NAME_PATTERN.match(name) is None

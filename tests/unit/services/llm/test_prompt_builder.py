"""Tests for PromptBuilder module.

Phase 5.1: Tests for prompt construction and behavioral equivalence.
"""

import pytest
import json

from src.services.llm.prompt_builder import PromptBuilder
from src.models.extraction import ExtractionTarget
from src.models.paper import PaperMetadata, Author


class TestPromptBuilder:
    """Tests for PromptBuilder class."""

    @pytest.fixture
    def builder(self) -> PromptBuilder:
        """Create test prompt builder."""
        return PromptBuilder()

    @pytest.fixture
    def paper_metadata(self) -> PaperMetadata:
        """Create test paper metadata."""
        return PaperMetadata(
            paper_id="test-paper-123",
            title="Test Paper Title",
            authors=[
                Author(name="John Doe", author_id="author1"),
                Author(name="Jane Smith", author_id="author2"),
            ],
            year=2024,
            abstract="Test abstract",
            url="https://example.com/paper",
        )

    @pytest.fixture
    def extraction_targets(self) -> list[ExtractionTarget]:
        """Create test extraction targets."""
        return [
            ExtractionTarget(
                name="summary",
                description="Extract the main summary",
                output_format="text",
                required=True,
                examples=["This paper presents..."],
            ),
            ExtractionTarget(
                name="code",
                description="Extract code snippets",
                output_format="code",
                required=False,
                examples=["def main():"],
            ),
        ]

    def test_build_prompt_contains_metadata(
        self,
        builder: PromptBuilder,
        paper_metadata: PaperMetadata,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test prompt contains paper metadata."""
        prompt = builder.build(
            markdown_content="# Test content",
            targets=extraction_targets,
            paper_metadata=paper_metadata,
        )

        assert paper_metadata.title in prompt
        assert paper_metadata.paper_id in prompt
        assert str(paper_metadata.year) in prompt
        assert "John Doe" in prompt
        assert "Jane Smith" in prompt

    def test_build_prompt_contains_targets(
        self,
        builder: PromptBuilder,
        paper_metadata: PaperMetadata,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test prompt contains extraction targets."""
        prompt = builder.build(
            markdown_content="# Test content",
            targets=extraction_targets,
            paper_metadata=paper_metadata,
        )

        assert "summary" in prompt
        assert "code" in prompt
        assert "Extract the main summary" in prompt

    def test_build_prompt_contains_content(
        self,
        builder: PromptBuilder,
        paper_metadata: PaperMetadata,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test prompt contains markdown content."""
        content = "# Test Paper\n\nThis is the paper content."
        prompt = builder.build(
            markdown_content=content,
            targets=extraction_targets,
            paper_metadata=paper_metadata,
        )

        assert content in prompt

    def test_build_prompt_contains_json_schema(
        self,
        builder: PromptBuilder,
        paper_metadata: PaperMetadata,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test prompt contains JSON schema."""
        prompt = builder.build(
            markdown_content="# Test",
            targets=extraction_targets,
            paper_metadata=paper_metadata,
        )

        assert "extractions" in prompt
        assert "target_name" in prompt
        assert "success" in prompt
        assert "confidence" in prompt

    def test_build_prompt_unknown_authors(
        self,
        builder: PromptBuilder,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test prompt handles missing authors."""
        metadata = PaperMetadata(
            paper_id="test-123",
            title="Test Paper",
            authors=[],
            year=2024,
            abstract="Abstract",
            url="https://example.com",
        )

        prompt = builder.build(
            markdown_content="# Test",
            targets=extraction_targets,
            paper_metadata=metadata,
        )

        assert "Unknown" in prompt

    def test_build_prompt_unknown_year(
        self,
        builder: PromptBuilder,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test prompt handles missing year."""
        metadata = PaperMetadata(
            paper_id="test-123",
            title="Test Paper",
            authors=[],
            year=None,
            abstract="Abstract",
            url="https://example.com",
        )

        prompt = builder.build(
            markdown_content="# Test",
            targets=extraction_targets,
            paper_metadata=metadata,
        )

        assert "Unknown" in prompt


class TestPromptBuilderBehavioralEquivalence:
    """Behavioral equivalence tests for prompt building.

    These tests verify that the PromptBuilder produces prompts
    that match the original LLMService._build_extraction_prompt.
    """

    @pytest.fixture
    def builder(self) -> PromptBuilder:
        """Create test prompt builder."""
        return PromptBuilder()

    def test_prompt_structure_matches_original(
        self,
        builder: PromptBuilder,
    ) -> None:
        """Test prompt structure matches original format."""
        metadata = PaperMetadata(
            paper_id="test-123",
            title="Test Title",
            authors=[Author(name="Test Author", author_id="a1")],
            year=2024,
            abstract="Test abstract",
            url="https://example.com",
        )
        targets = [
            ExtractionTarget(
                name="test_target",
                description="Test description",
                output_format="text",
                required=True,
                examples=["Example 1"],
            )
        ]

        prompt = builder.build(
            markdown_content="Test content",
            targets=targets,
            paper_metadata=metadata,
        )

        # Verify key structural elements from original
        assert "research paper analyst" in prompt.lower()
        assert "**Paper Metadata:**" in prompt
        assert "**Extraction Targets:**" in prompt
        assert "**Instructions:**" in prompt
        assert "**Required JSON Structure:**" in prompt
        assert "**Paper Content:**" in prompt
        assert "**Now extract the information" in prompt

    def test_targets_json_format(
        self,
        builder: PromptBuilder,
    ) -> None:
        """Test targets are formatted as valid JSON."""
        metadata = PaperMetadata(
            paper_id="test-123",
            title="Test",
            authors=[],
            year=2024,
            abstract="Test",
            url="https://example.com",
        )
        targets = [
            ExtractionTarget(
                name="test",
                description="Test desc",
                output_format="text",
                required=True,
                examples=["ex1"],
            )
        ]

        prompt = builder.build(
            markdown_content="Content",
            targets=targets,
            paper_metadata=metadata,
        )

        # Extract targets JSON from prompt
        # Should be parseable JSON array
        targets_section = prompt.split("**Extraction Targets:**")[1]
        targets_section = targets_section.split("**Instructions:**")[0].strip()

        # Should be valid JSON
        parsed = json.loads(targets_section)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "test"

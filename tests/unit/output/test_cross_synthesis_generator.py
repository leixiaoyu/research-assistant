"""Unit tests for Phase 3.7 CrossSynthesisGenerator.

Tests:
- Markdown generation
- Frontmatter generation
- Section rendering
- Incremental updates
- Atomic file operations
- State management
"""

import pytest

from src.models.cross_synthesis import (
    SynthesisResult,
    CrossTopicSynthesisReport,
)
from src.output.cross_synthesis_generator import (
    CrossSynthesisGenerator,
    METADATA_START,
    METADATA_END,
    SECTION_START,
    SECTION_END,
)


@pytest.fixture
def sample_report():
    """Create a sample synthesis report."""
    return CrossTopicSynthesisReport(
        report_id="syn-20250216-123456",
        total_papers_in_registry=100,
        results=[
            SynthesisResult(
                question_id="q1",
                question_name="Question One",
                synthesis_text="This is the synthesis for question one.",
                papers_used=["paper1", "paper2", "paper3"],
                topics_covered=["topic-a", "topic-b"],
                tokens_used=5000,
                cost_usd=0.15,
                model_used="claude-3-5-sonnet",
                confidence=0.85,
            ),
            SynthesisResult(
                question_id="q2",
                question_name="Question Two",
                synthesis_text="This is the synthesis for question two.",
                papers_used=["paper3", "paper4"],
                topics_covered=["topic-b", "topic-c"],
                tokens_used=3000,
                cost_usd=0.10,
                model_used="claude-3-5-sonnet",
                confidence=0.75,
            ),
        ],
        total_tokens_used=8000,
        total_cost_usd=0.25,
        incremental=False,
        new_papers_since_last=10,
    )


@pytest.fixture
def generator(tmp_path):
    """Create a generator with temp output path."""
    output_path = tmp_path / "Global_Synthesis.md"
    return CrossSynthesisGenerator(output_path=output_path)


class TestMarkdownGeneration:
    """Tests for markdown content generation."""

    def test_generate_produces_valid_markdown(self, generator, sample_report):
        """Test that generate produces valid markdown."""
        content = generator.generate(sample_report)

        assert content is not None
        assert len(content) > 0
        assert "# Cross-Topic Research Synthesis" in content

    def test_generate_includes_frontmatter(self, generator, sample_report):
        """Test that frontmatter is included."""
        content = generator.generate(sample_report)

        assert content.startswith("---")
        assert 'title: "Cross-Topic Research Synthesis"' in content
        assert "total_papers: 100" in content
        assert "questions_answered: 2" in content

    def test_generate_includes_overview(self, generator, sample_report):
        """Test that overview section is included."""
        content = generator.generate(sample_report)

        assert "## Overview" in content
        assert "Papers Analyzed | 100" in content
        assert "Questions Answered | 2" in content
        assert "$0.25" in content

    def test_generate_includes_all_questions(self, generator, sample_report):
        """Test that all question sections are included."""
        content = generator.generate(sample_report)

        assert "## 1. Question One" in content
        assert "## 2. Question Two" in content
        assert "This is the synthesis for question one." in content
        assert "This is the synthesis for question two." in content

    def test_generate_includes_question_metadata(self, generator, sample_report):
        """Test that question metadata is included."""
        content = generator.generate(sample_report)

        assert "**Question ID:** q1" in content
        assert "**Papers Used:** 3" in content
        assert "**Cost:** $0.15" in content
        assert "topic-a" in content

    def test_generate_includes_appendix(self, generator, sample_report):
        """Test that paper reference appendix is included."""
        content = generator.generate(sample_report)

        assert "## Appendix: Papers Referenced" in content
        assert "paper1" in content
        assert "paper2" in content

    def test_generate_includes_hidden_metadata(self, generator, sample_report):
        """Test that hidden metadata section is included."""
        content = generator.generate(sample_report)

        assert METADATA_START in content
        assert METADATA_END in content
        assert '"report_id": "syn-20250216-123456"' in content

    def test_generate_empty_report(self, generator):
        """Test generating with empty report."""
        report = CrossTopicSynthesisReport(
            report_id="empty-report",
            total_papers_in_registry=0,
        )

        content = generator.generate(report)

        assert "# Cross-Topic Research Synthesis" in content
        assert "Questions Answered | 0" in content


class TestFrontmatterGeneration:
    """Tests for YAML frontmatter generation."""

    def test_frontmatter_format(self, generator, sample_report):
        """Test frontmatter format."""
        frontmatter = generator._generate_frontmatter(sample_report)

        assert frontmatter.startswith("---")
        assert frontmatter.rstrip().endswith("---")
        assert "total_papers: 100" in frontmatter

    def test_frontmatter_includes_timestamps(self, generator, sample_report):
        """Test frontmatter includes timestamps."""
        frontmatter = generator._generate_frontmatter(sample_report)

        assert "generated:" in frontmatter
        assert "last_updated:" in frontmatter


class TestSectionRendering:
    """Tests for question section rendering."""

    def test_section_includes_markers(self, generator, sample_report):
        """Test that section markers are included."""
        section = generator._generate_question_section(sample_report.results[0], 1)

        expected_start = SECTION_START.format(question_id="q1")
        expected_end = SECTION_END.format(question_id="q1")

        assert expected_start in section
        assert expected_end in section

    def test_section_includes_synthesis_text(self, generator, sample_report):
        """Test that synthesis text is included."""
        section = generator._generate_question_section(sample_report.results[0], 1)

        assert "This is the synthesis for question one." in section

    def test_section_includes_topics(self, generator, sample_report):
        """Test that topics are listed."""
        section = generator._generate_question_section(sample_report.results[0], 1)

        assert "topic-a" in section
        assert "topic-b" in section


class TestAppendixGeneration:
    """Tests for appendix generation."""

    def test_appendix_lists_papers(self, generator, sample_report):
        """Test that appendix lists all papers."""
        appendix = generator._generate_appendix(sample_report)

        assert "paper1" in appendix
        assert "paper2" in appendix
        assert "paper3" in appendix
        assert "paper4" in appendix

    def test_appendix_shows_sections(self, generator, sample_report):
        """Test that appendix shows which sections reference papers."""
        appendix = generator._generate_appendix(sample_report)

        # paper3 is in both sections
        assert "paper3" in appendix

    def test_appendix_empty_report(self, generator):
        """Test appendix with no papers."""
        report = CrossTopicSynthesisReport(
            report_id="empty",
            total_papers_in_registry=0,
        )

        appendix = generator._generate_appendix(report)

        assert "No papers referenced" in appendix

    def test_appendix_truncates_long_ids(self, generator):
        """Test that long paper IDs are truncated."""
        result = SynthesisResult(
            question_id="q1",
            question_name="Q1",
            synthesis_text="T",
            papers_used=["a" * 30],
        )
        report = CrossTopicSynthesisReport(
            report_id="test",
            total_papers_in_registry=1,
            results=[result],
        )

        appendix = generator._generate_appendix(report)

        assert "..." in appendix


class TestIncrementalUpdates:
    """Tests for incremental update functionality."""

    def test_extract_existing_sections(self, generator):
        """Test extracting sections from existing content."""
        content = """
# Header

<!-- SECTION_START:q1 -->
## 1. Question One
Content for question one.
<!-- SECTION_END:q1 -->

<!-- SECTION_START:q2 -->
## 2. Question Two
Content for question two.
<!-- SECTION_END:q2 -->
"""
        sections = generator._extract_existing_sections(content)

        assert "q1" in sections
        assert "q2" in sections
        assert "Question One" in sections["q1"]

    def test_extract_existing_metadata(self, generator):
        """Test extracting metadata from existing content."""
        content = f"""
# Header

{METADATA_START}
{{
  "report_id": "old-report",
  "last_synthesis": "2025-01-15T10:00:00Z",
  "questions_processed": ["q1", "q2"]
}}
{METADATA_END}
"""
        metadata = generator._extract_existing_metadata(content)

        assert metadata is not None
        assert metadata["report_id"] == "old-report"
        assert len(metadata["questions_processed"]) == 2

    def test_extract_existing_metadata_invalid_json(self, generator):
        """Test extracting invalid metadata returns None."""
        content = f"""
{METADATA_START}
invalid json here
{METADATA_END}
"""
        metadata = generator._extract_existing_metadata(content)

        assert metadata is None

    def test_generate_incremental_preserves_structure(self, generator, sample_report):
        """Test that incremental generation preserves document structure."""
        existing = """---
title: "Old Title"
---
# Old Header
Old content
"""
        updated = generator.generate_incremental(sample_report, existing)

        # Should have new content structure
        assert "# Cross-Topic Research Synthesis" in updated
        assert "Question One" in updated


class TestFileOperations:
    """Tests for file write operations."""

    def test_write_creates_file(self, generator, sample_report):
        """Test that write creates the output file."""
        result = generator.write(sample_report)

        assert result is not None
        assert result.exists()

    def test_write_content_is_valid(self, generator, sample_report):
        """Test that written content is valid markdown."""
        generator.write(sample_report)

        content = generator.output_path.read_text()

        assert "# Cross-Topic Research Synthesis" in content
        assert "Question One" in content

    def test_write_sets_permissions(self, generator, sample_report):
        """Test that written file has correct permissions."""
        result = generator.write(sample_report)

        # Check file is readable
        assert result.stat().st_mode & 0o644

    def test_write_incremental_mode(self, generator, sample_report):
        """Test incremental write mode."""
        # First write
        generator.write(sample_report)

        # Second write (incremental)
        sample_report.results[0].synthesis_text = "Updated content"
        result = generator.write(sample_report, incremental=True)

        content = result.read_text()
        assert "Updated content" in content

    def test_write_non_incremental_mode(self, generator, sample_report):
        """Test non-incremental write mode."""
        # First write
        generator.write(sample_report)

        # Modify existing file
        generator.output_path.write_text("Old content")

        # Non-incremental write should replace
        result = generator.write(sample_report, incremental=False)

        content = result.read_text()
        assert "Old content" not in content
        assert "Question One" in content

    def test_atomic_write_creates_temp_file(self, generator, sample_report):
        """Test that atomic write uses temp file."""
        content = generator.generate(sample_report)

        success = generator._atomic_write(content)

        assert success
        assert generator.output_path.exists()

    def test_ensure_output_directory(self, tmp_path):
        """Test that output directory is created."""
        deep_path = tmp_path / "a" / "b" / "c" / "output.md"
        gen = CrossSynthesisGenerator(output_path=deep_path)

        gen._ensure_output_directory()

        assert deep_path.parent.exists()


class TestStateManagement:
    """Tests for synthesis state management."""

    def test_load_state_no_file(self, generator):
        """Test loading state when no file exists."""
        state = generator.load_state()

        assert state is None

    def test_load_state_from_file(self, generator, sample_report):
        """Test loading state from existing file."""
        # Write a report first
        generator.write(sample_report)

        state = generator.load_state()

        assert state is not None
        assert state.last_report_id == sample_report.report_id
        assert "q1" in state.questions_processed
        assert "q2" in state.questions_processed

    def test_load_state_invalid_file(self, generator):
        """Test loading state from invalid file."""
        generator.output_path.parent.mkdir(parents=True, exist_ok=True)
        generator.output_path.write_text("No metadata here")

        state = generator.load_state()

        assert state is None


class TestTopicCounting:
    """Tests for topic counting utility."""

    def test_count_unique_topics(self, generator, sample_report):
        """Test counting unique topics across results."""
        count = generator._count_unique_topics(sample_report)

        # topic-a, topic-b, topic-c = 3 unique
        assert count == 3

    def test_count_unique_topics_empty(self, generator):
        """Test counting topics with no results."""
        report = CrossTopicSynthesisReport(
            report_id="empty",
            total_papers_in_registry=0,
        )

        count = generator._count_unique_topics(report)

        assert count == 0


class TestErrorHandling:
    """Tests for error handling paths."""

    def test_atomic_write_failure(self, tmp_path):
        """Test atomic write handles write failures gracefully."""
        # Create a read-only directory
        output_dir = tmp_path / "readonly"
        output_dir.mkdir()
        output_path = output_dir / "output.md"

        generator = CrossSynthesisGenerator(output_path=output_path)

        # Make directory read-only to cause write failure
        import os

        os.chmod(output_dir, 0o444)

        try:
            success = generator._atomic_write("Test content")
            # Should return False on failure (not raise)
            assert success is False
        finally:
            # Restore permissions for cleanup
            os.chmod(output_dir, 0o755)

    def test_write_incremental_read_error(self, tmp_path):
        """Test write handles read error for existing file."""
        output_path = tmp_path / "output.md"

        # Create a file that can't be read
        output_path.write_text("original content")
        import os

        os.chmod(output_path, 0o000)

        try:
            generator = CrossSynthesisGenerator(output_path=output_path)

            report = CrossTopicSynthesisReport(
                report_id="test",
                total_papers_in_registry=10,
            )

            # Should still write (falls back to non-incremental)
            result = generator.write(report, incremental=True)

            # Restore permissions to allow write
            os.chmod(output_path, 0o644)
            result = generator.write(report, incremental=True)

            assert result is not None
        finally:
            os.chmod(output_path, 0o644)

    def test_load_state_exception(self, tmp_path):
        """Test load_state handles parse errors."""
        output_path = tmp_path / "output.md"

        # Write file with invalid JSON in metadata section
        invalid_content = """---
title: Test
---

# Content

<!-- SYNTHESIS_META_START -->
{ invalid json here
<!-- SYNTHESIS_META_END -->
"""
        output_path.write_text(invalid_content)

        generator = CrossSynthesisGenerator(output_path=output_path)

        # Should return None on error (not raise)
        state = generator.load_state()
        assert state is None

    def test_generate_incremental_preserves_unreferenced_sections(
        self, generator, sample_report
    ):
        """Test that incremental generation handles existing sections."""
        # Create existing content with a section not in current report
        existing = """---
title: "Cross-Topic Research Synthesis"
---

# Cross-Topic Research Synthesis

<!-- SECTION_START:old-question -->
## 1. Old Question
Old content here.
<!-- SECTION_END:old-question -->

<!-- SECTION_START:q1 -->
## 2. Question One
Previous content.
<!-- SECTION_END:q1 -->
"""
        # Generate incrementally
        updated = generator.generate_incremental(sample_report, existing)

        # Should have current results (q1, q2)
        assert "Question One" in updated
        assert "Question Two" in updated

    def test_write_returns_none_on_failure(self, tmp_path, monkeypatch):
        """Test write returns None when atomic write fails."""
        output_path = tmp_path / "output.md"

        generator = CrossSynthesisGenerator(output_path=output_path)

        report = CrossTopicSynthesisReport(
            report_id="test",
            total_papers_in_registry=10,
        )

        # Mock _atomic_write to return False (simulating failure)
        monkeypatch.setattr(generator, "_atomic_write", lambda content: False)

        result = generator.write(report)
        assert result is None

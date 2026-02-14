"""Unit tests for ReportParser service (Phase 3.7).

Tests markdown report parsing and key learnings extraction from:
- Delta briefs
- Research briefs
"""

from pathlib import Path
from unittest.mock import patch
import tempfile

from src.services.report_parser import ReportParser


class TestReportParser:
    """Tests for ReportParser class."""

    def test_init_default_max_length(self) -> None:
        """Test default max_summary_length."""
        parser = ReportParser()
        assert parser.max_summary_length == 200

    def test_init_custom_max_length(self) -> None:
        """Test custom max_summary_length."""
        parser = ReportParser(max_summary_length=150)
        assert parser.max_summary_length == 150


class TestExtractKeyLearnings:
    """Tests for extract_key_learnings method."""

    def test_empty_file_list(self) -> None:
        """Test with empty file list."""
        parser = ReportParser()
        learnings = parser.extract_key_learnings([], max_per_topic=2)

        assert learnings == []

    def test_nonexistent_file(self) -> None:
        """Test with nonexistent file path."""
        parser = ReportParser()
        learnings = parser.extract_key_learnings(
            ["/nonexistent/path/file.md"],
            max_per_topic=2,
        )

        assert learnings == []

    def test_parse_delta_brief(self) -> None:
        """Test parsing Delta brief format."""
        delta_content = """# Delta Brief: test-topic
**Run Date:** 2025-01-23

## Summary

| Metric | Count |
|--------|-------|
| 🆕 New Papers | 2 |

## 🆕 New Papers

Papers processed for the first time in this run.

### 🆕 First Paper Title
**Quality:** ⭐⭐ Good (65) | **Source:** 📄 PDF

**Engineering Summary** (confidence: 95%)

This paper presents a novel approach to neural machine translation
that improves performance on low-resource language pairs.

---

### 🆕 Second Paper Title
**Quality:** ⭐ Fair (45) | **Source:** 📋 Abstract

**Engineering Summary** (confidence: 80%)

The authors propose a new attention mechanism for document-level
translation that maintains coherence across paragraphs.

---
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create proper path structure
            topic_dir = Path(tmpdir) / "output" / "test-topic" / "runs"
            topic_dir.mkdir(parents=True)
            file_path = topic_dir / "2025-01-23_Delta.md"
            file_path.write_text(delta_content)

            parser = ReportParser()
            learnings = parser.extract_key_learnings(
                [str(file_path)],
                max_per_topic=2,
            )

            assert len(learnings) == 2
            assert learnings[0].paper_title == "First Paper Title"
            assert learnings[0].topic == "test-topic"
            assert "neural machine translation" in learnings[0].summary

    def test_parse_research_brief(self) -> None:
        """Test parsing Research brief format."""
        research_content = """---
topic: "test query"
date: 2025-01-23
papers_processed: 2
---

# Research Brief: test query

**Generated:** 2025-01-23 09:00:00 UTC
**Papers Found:** 2

## Papers

### 1. [First Research Paper](https://example.com/paper1)
**Quality:** ⭐⭐ Good (60) | **Status:** 📄 PDF Available
**Authors:** John Doe, Jane Smith

> This is the abstract of the first paper with important findings.

#### Extraction Results

**Engineering Summary** (confidence: 90%)

This paper introduces a breakthrough methodology for improving
translation quality using attention mechanisms.

---

### 2. [Second Research Paper](https://example.com/paper2)
**Quality:** ⭐ Fair (40) | **Status:** 📋 Abstract Only

> Abstract of the second paper describing experimental results.

---
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            topic_dir = Path(tmpdir) / "output" / "research-topic"
            topic_dir.mkdir(parents=True)
            file_path = topic_dir / "2025-01-23_Research.md"
            file_path.write_text(research_content)

            parser = ReportParser()
            learnings = parser.extract_key_learnings(
                [str(file_path)],
                max_per_topic=2,
            )

            assert len(learnings) >= 1
            assert learnings[0].topic == "research-topic"

    def test_max_per_topic_limit(self) -> None:
        """Test max_per_topic limits learnings."""
        delta_content = """# Delta Brief: test-topic

## 🆕 New Papers

### 🆕 Paper 1
**Engineering Summary** (confidence: 95%)
Summary for paper 1.

---

### 🆕 Paper 2
**Engineering Summary** (confidence: 90%)
Summary for paper 2.

---

### 🆕 Paper 3
**Engineering Summary** (confidence: 85%)
Summary for paper 3.

---
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            topic_dir = Path(tmpdir) / "output" / "topic" / "runs"
            topic_dir.mkdir(parents=True)
            file_path = topic_dir / "2025-01-23_Delta.md"
            file_path.write_text(delta_content)

            parser = ReportParser()

            # Limit to 1
            learnings = parser.extract_key_learnings([str(file_path)], max_per_topic=1)
            assert len(learnings) == 1

            # Limit to 2
            learnings = parser.extract_key_learnings([str(file_path)], max_per_topic=2)
            assert len(learnings) == 2

    def test_multiple_files(self) -> None:
        """Test parsing multiple files."""
        content1 = """# Delta Brief: topic-1

## 🆕 New Papers

### 🆕 Paper from Topic 1
**Engineering Summary** (confidence: 90%)
This is the summary for topic 1 paper.

---
"""

        content2 = """# Delta Brief: topic-2

## 🆕 New Papers

### 🆕 Paper from Topic 2
**Engineering Summary** (confidence: 85%)
This is the summary for topic 2 paper.

---
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two topic directories
            topic1_dir = Path(tmpdir) / "output" / "topic-1" / "runs"
            topic1_dir.mkdir(parents=True)
            file1 = topic1_dir / "2025-01-23_Delta.md"
            file1.write_text(content1)

            topic2_dir = Path(tmpdir) / "output" / "topic-2" / "runs"
            topic2_dir.mkdir(parents=True)
            file2 = topic2_dir / "2025-01-23_Delta.md"
            file2.write_text(content2)

            parser = ReportParser()
            learnings = parser.extract_key_learnings(
                [str(file1), str(file2)],
                max_per_topic=2,
            )

            assert len(learnings) == 2
            topics = {learning.topic for learning in learnings}
            assert "topic-1" in topics
            assert "topic-2" in topics

    def test_file_parse_error_handled(self) -> None:
        """Test file parsing errors are handled gracefully."""
        parser = ReportParser()

        # Mock _parse_file to raise exception
        with patch.object(parser, "_parse_file", side_effect=Exception("Parse error")):
            learnings = parser.extract_key_learnings(
                ["/some/path.md"],
                max_per_topic=2,
            )

            # Should return empty list, not raise
            assert learnings == []


class TestExtractTopicSlug:
    """Tests for _extract_topic_slug method."""

    def test_standard_delta_path(self) -> None:
        """Test extraction from standard Delta brief path."""
        parser = ReportParser()
        path = Path("/project/output/my-topic/runs/2025-01-23_Delta.md")

        slug = parser._extract_topic_slug(path)
        assert slug == "my-topic"

    def test_research_brief_path(self) -> None:
        """Test extraction from Research brief path (no runs dir)."""
        parser = ReportParser()
        path = Path("/project/output/another-topic/2025-01-23_Research.md")

        slug = parser._extract_topic_slug(path)
        assert slug == "another-topic"

    def test_fallback_to_parent(self) -> None:
        """Test fallback when 'output' not in path."""
        parser = ReportParser()
        path = Path("/custom/path/topic-name/file.md")

        slug = parser._extract_topic_slug(path)
        assert slug == "topic-name"


class TestCleanTitle:
    """Tests for _clean_title method."""

    def test_remove_markdown_links(self) -> None:
        """Test markdown links are removed from title."""
        parser = ReportParser()
        title = "[Paper Title](https://example.com)"

        cleaned = parser._clean_title(title)
        assert cleaned == "Paper Title"

    def test_remove_leading_numbers(self) -> None:
        """Test leading numbers are removed."""
        parser = ReportParser()
        title = "1. Paper Title"

        cleaned = parser._clean_title(title)
        assert cleaned == "Paper Title"

    def test_remove_emojis(self) -> None:
        """Test emoji codes are removed."""
        parser = ReportParser()
        title = ":new: Paper Title :star:"

        cleaned = parser._clean_title(title)
        assert cleaned == "Paper Title"

    def test_whitespace_stripped(self) -> None:
        """Test whitespace is stripped."""
        parser = ReportParser()
        title = "  Paper Title  "

        cleaned = parser._clean_title(title)
        assert cleaned == "Paper Title"


class TestCleanSummary:
    """Tests for _clean_summary method."""

    def test_remove_bold_formatting(self) -> None:
        """Test bold formatting is removed."""
        parser = ReportParser()
        summary = "This is **bold** text."

        cleaned = parser._clean_summary(summary)
        assert cleaned == "This is bold text."

    def test_remove_italic_formatting(self) -> None:
        """Test italic formatting is removed."""
        parser = ReportParser()
        summary = "This is *italic* text."

        cleaned = parser._clean_summary(summary)
        assert cleaned == "This is italic text."

    def test_remove_code_formatting(self) -> None:
        """Test code formatting is removed."""
        parser = ReportParser()
        summary = "Use `function()` here."

        cleaned = parser._clean_summary(summary)
        assert cleaned == "Use function() here."

    def test_collapse_whitespace(self) -> None:
        """Test multiple whitespace is collapsed."""
        parser = ReportParser()
        summary = "Multiple   spaces\nand\nnewlines."

        cleaned = parser._clean_summary(summary)
        assert cleaned == "Multiple spaces and newlines."


class TestTruncateSummary:
    """Tests for _truncate_summary method."""

    def test_short_summary_unchanged(self) -> None:
        """Test short summary is not truncated."""
        parser = ReportParser(max_summary_length=100)
        summary = "Short summary."

        truncated = parser._truncate_summary(summary)
        assert truncated == summary

    def test_long_summary_truncated(self) -> None:
        """Test long summary is truncated with ellipsis."""
        parser = ReportParser(max_summary_length=50)
        summary = (
            "This is a very long summary that should be truncated at word boundary."
        )

        truncated = parser._truncate_summary(summary)
        assert len(truncated) <= 53  # 50 + "..."
        assert truncated.endswith("...")

    def test_truncate_at_word_boundary(self) -> None:
        """Test truncation happens at word boundary."""
        parser = ReportParser(max_summary_length=20)
        summary = "Word1 Word2 Word3 Word4"

        truncated = parser._truncate_summary(summary)
        # Should not cut in middle of a word
        assert not truncated.rstrip("...").endswith("Wor")


class TestFindDeltaBriefs:
    """Tests for find_delta_briefs method."""

    def test_find_delta_briefs_in_runs(self) -> None:
        """Test finding Delta briefs in runs directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Delta briefs in runs directories
            topic1_runs = Path(tmpdir) / "topic-1" / "runs"
            topic1_runs.mkdir(parents=True)
            (topic1_runs / "2025-01-23_Delta.md").touch()
            (topic1_runs / "2025-01-22_Delta.md").touch()

            topic2_runs = Path(tmpdir) / "topic-2" / "runs"
            topic2_runs.mkdir(parents=True)
            (topic2_runs / "2025-01-23_Delta.md").touch()

            parser = ReportParser()
            delta_files = parser.find_delta_briefs(tmpdir)

            assert len(delta_files) == 3

    def test_find_delta_briefs_with_date_filter(self) -> None:
        """Test finding Delta briefs with date filter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            topic_runs = Path(tmpdir) / "topic" / "runs"
            topic_runs.mkdir(parents=True)
            (topic_runs / "2025-01-23_Delta.md").touch()
            (topic_runs / "2025-01-22_Delta.md").touch()

            parser = ReportParser()
            delta_files = parser.find_delta_briefs(tmpdir, date_filter="2025-01-23")

            assert len(delta_files) == 1
            assert "2025-01-23_Delta.md" in delta_files[0]

    def test_find_delta_briefs_nonexistent_dir(self) -> None:
        """Test with nonexistent output directory."""
        parser = ReportParser()
        delta_files = parser.find_delta_briefs("/nonexistent/path")

        assert delta_files == []

    def test_find_delta_briefs_legacy_format(self) -> None:
        """Test finding Delta briefs in legacy format (no runs dir)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Legacy format: directly in topic directory
            topic_dir = Path(tmpdir) / "topic"
            topic_dir.mkdir(parents=True)
            (topic_dir / "2025-01-23_Delta.md").touch()

            parser = ReportParser()
            delta_files = parser.find_delta_briefs(tmpdir)

            assert len(delta_files) == 1


class TestExtractSummaryFromSection:
    """Tests for _extract_summary_from_section method."""

    def test_extract_engineering_summary(self) -> None:
        """Test extracting engineering summary."""
        parser = ReportParser()
        section = """
### Paper Title

**Engineering Summary**

This is the engineering summary content.
It spans multiple lines.

---
"""
        summary = parser._extract_summary_from_section(section)
        assert summary is not None
        assert "engineering summary content" in summary

    def test_extract_from_extraction_result(self) -> None:
        """Test extracting from extraction result format."""
        parser = ReportParser()
        section = """
### Paper Title

**Engineering Summary** (confidence: 95%)

This is extracted via LLM with high confidence.

---
"""
        summary = parser._extract_summary_from_section(section)
        assert summary is not None
        assert "extracted via LLM" in summary

    def test_fallback_to_abstract(self) -> None:
        """Test fallback to blockquote abstract."""
        parser = ReportParser()
        section = """
### Paper Title

> This is the paper abstract which provides context about the research
> and its key findings in the field of machine translation.

---
"""
        summary = parser._extract_summary_from_section(section)
        assert summary is not None
        assert "paper abstract" in summary

    def test_no_summary_found(self) -> None:
        """Test when no summary can be extracted."""
        parser = ReportParser()
        section = """
### Paper Title

No summary here.

---
"""
        summary = parser._extract_summary_from_section(section)
        # May return None if no blockquote or engineering summary
        # The implementation extracts blockquotes only if > 50 chars
        assert summary is None

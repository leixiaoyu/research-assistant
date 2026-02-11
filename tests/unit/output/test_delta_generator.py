"""Tests for Phase 3.6 DeltaGenerator."""

import pytest
from pathlib import Path
from datetime import datetime, timezone

from src.output.delta_generator import DeltaGenerator
from src.models.synthesis import (
    ProcessingResult,
    ProcessingStatus,
    DeltaBrief,
)


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create temporary output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


@pytest.fixture
def generator(temp_output_dir):
    """Create DeltaGenerator with temp directory."""
    return DeltaGenerator(output_base_dir=temp_output_dir)


@pytest.fixture
def sample_new_result():
    """Create a sample new paper result."""
    return ProcessingResult(
        paper_id="new-paper-id",
        title="New Paper Title",
        status=ProcessingStatus.NEW,
        quality_score=75.0,
        pdf_available=True,
        extraction_success=True,
        topic_slug="test-topic",
    )


@pytest.fixture
def sample_backfilled_result():
    """Create a sample backfilled paper result."""
    return ProcessingResult(
        paper_id="backfill-paper-id",
        title="Backfilled Paper Title",
        status=ProcessingStatus.BACKFILLED,
        quality_score=60.0,
        pdf_available=True,
        extraction_success=True,
        topic_slug="test-topic",
    )


@pytest.fixture
def sample_skipped_result():
    """Create a sample skipped paper result."""
    return ProcessingResult(
        paper_id="skipped-paper-id",
        title="Skipped Paper Title",
        status=ProcessingStatus.SKIPPED,
        quality_score=50.0,
        pdf_available=False,
        extraction_success=False,
        topic_slug="test-topic",
    )


@pytest.fixture
def sample_failed_result():
    """Create a sample failed paper result."""
    return ProcessingResult(
        paper_id="failed-paper-id",
        title="Failed Paper Title",
        status=ProcessingStatus.FAILED,
        quality_score=0.0,
        pdf_available=False,
        extraction_success=False,
        topic_slug="test-topic",
        error_message="Connection timeout",
    )


class TestDeltaGeneratorInit:
    """Tests for DeltaGenerator initialization."""

    def test_init_creates_generator(self, temp_output_dir):
        """Test generator initialization."""
        generator = DeltaGenerator(output_base_dir=temp_output_dir)

        assert generator.output_base_dir == temp_output_dir

    def test_init_with_default_dir(self):
        """Test generator with default output directory."""
        generator = DeltaGenerator()

        assert generator.output_base_dir == Path("output")


class TestEnsureRunsDirectory:
    """Tests for runs directory creation."""

    def test_creates_runs_directory(self, generator, temp_output_dir):
        """Test that runs directory is created."""
        runs_dir = generator._ensure_runs_directory("test-topic")

        assert runs_dir.exists()
        assert runs_dir.name == "runs"
        assert runs_dir.parent.name == "test-topic"

    def test_sanitizes_topic_slug(self, generator, temp_output_dir):
        """Test that topic slug is sanitized."""
        runs_dir = generator._ensure_runs_directory("../malicious")

        # Should not create directory outside output
        assert temp_output_dir in runs_dir.parents


class TestValidateDateFormat:
    """Tests for date format validation."""

    def test_valid_date_format(self, generator):
        """Test valid date format."""
        assert generator._validate_date_format("2025-01-15") is True
        assert generator._validate_date_format("2025-12-31") is True

    def test_invalid_date_formats(self, generator):
        """Test invalid date formats."""
        assert generator._validate_date_format("2025/01/15") is False
        assert generator._validate_date_format("15-01-2025") is False
        assert generator._validate_date_format("2025-1-15") is False
        assert generator._validate_date_format("not-a-date") is False


class TestQualityBadge:
    """Tests for quality badge generation."""

    def test_excellent_badge(self, generator):
        """Test excellent quality badge."""
        badge = generator._quality_badge(85.0)
        assert "⭐⭐⭐" in badge

    def test_good_badge(self, generator):
        """Test good quality badge."""
        badge = generator._quality_badge(65.0)
        assert "⭐⭐" in badge
        assert "⭐⭐⭐" not in badge

    def test_fair_badge(self, generator):
        """Test fair quality badge."""
        badge = generator._quality_badge(45.0)
        assert badge.count("⭐") == 1

    def test_low_badge(self, generator):
        """Test low quality badge."""
        badge = generator._quality_badge(25.0)
        assert "○" in badge


class TestStatusEmoji:
    """Tests for status emoji generation."""

    def test_new_emoji(self, generator):
        """Test new status emoji."""
        assert generator._status_emoji(ProcessingStatus.NEW) == "🆕"

    def test_backfilled_emoji(self, generator):
        """Test backfilled status emoji."""
        assert generator._status_emoji(ProcessingStatus.BACKFILLED) == "🔄"

    def test_skipped_emoji(self, generator):
        """Test skipped status emoji."""
        assert generator._status_emoji(ProcessingStatus.SKIPPED) == "⏭️"

    def test_failed_emoji(self, generator):
        """Test failed status emoji."""
        assert generator._status_emoji(ProcessingStatus.FAILED) == "❌"


class TestRenderPaperEntry:
    """Tests for paper entry rendering."""

    def test_renders_new_paper(self, generator, sample_new_result):
        """Test rendering a new paper entry."""
        entry = generator._render_paper_entry(sample_new_result)

        assert "### 🆕 New Paper Title" in entry
        assert "⭐⭐" in entry  # Good quality (75)
        assert "📄 PDF" in entry
        assert "✅ Extraction successful" in entry

    def test_renders_failed_paper(self, generator, sample_failed_result):
        """Test rendering a failed paper entry."""
        entry = generator._render_paper_entry(sample_failed_result)

        assert "### ❌ Failed Paper Title" in entry
        assert "Connection timeout" in entry


class TestCreateDeltaBrief:
    """Tests for delta brief creation."""

    def test_creates_brief_with_new_papers(self, generator, sample_new_result):
        """Test creating brief with new papers."""
        brief = generator.create_delta_brief(
            results=[sample_new_result],
            topic_slug="test-topic",
        )

        assert brief.topic_slug == "test-topic"
        assert brief.total_new == 1
        assert brief.total_backfilled == 0
        assert brief.has_changes is True

    def test_creates_brief_with_backfilled(self, generator, sample_backfilled_result):
        """Test creating brief with backfilled papers."""
        brief = generator.create_delta_brief(
            results=[sample_backfilled_result],
            topic_slug="test-topic",
        )

        assert brief.total_backfilled == 1
        assert brief.has_changes is True

    def test_creates_brief_with_mixed_results(
        self,
        generator,
        sample_new_result,
        sample_backfilled_result,
        sample_skipped_result,
        sample_failed_result,
    ):
        """Test creating brief with mixed results."""
        results = [
            sample_new_result,
            sample_backfilled_result,
            sample_skipped_result,
            sample_failed_result,
        ]

        brief = generator.create_delta_brief(
            results=results,
            topic_slug="test-topic",
        )

        assert brief.total_new == 1
        assert brief.total_backfilled == 1
        assert brief.skipped_count == 1
        assert brief.failed_count == 1

    def test_creates_brief_with_custom_date(self, generator, sample_new_result):
        """Test creating brief with custom date."""
        custom_date = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        brief = generator.create_delta_brief(
            results=[sample_new_result],
            topic_slug="test-topic",
            run_date=custom_date,
        )

        assert brief.run_date == custom_date


class TestRenderDeltaBrief:
    """Tests for delta brief rendering."""

    def test_renders_header(self, generator):
        """Test rendering brief header."""
        brief = DeltaBrief(topic_slug="test-topic")

        content = generator._render_delta_brief(brief)

        assert "# Delta Brief: test-topic" in content
        assert "**Run Date:**" in content

    def test_renders_summary_table(self, generator):
        """Test rendering summary statistics table."""
        brief = DeltaBrief(
            topic_slug="test-topic",
            new_papers=[],
            skipped_count=5,
            failed_count=2,
        )

        content = generator._render_delta_brief(brief)

        assert "| 🆕 New Papers | 0 |" in content
        assert "| ⏭️ Skipped | 5 |" in content
        assert "| ❌ Failed | 2 |" in content

    def test_renders_new_papers_section(self, generator, sample_new_result):
        """Test rendering new papers section."""
        brief = DeltaBrief(
            topic_slug="test-topic",
            new_papers=[sample_new_result],
        )

        content = generator._render_delta_brief(brief)

        assert "## 🆕 New Papers" in content
        assert "New Paper Title" in content

    def test_renders_backfilled_papers_section(
        self, generator, sample_backfilled_result
    ):
        """Test rendering backfilled papers section."""
        brief = DeltaBrief(
            topic_slug="test-topic",
            backfilled_papers=[sample_backfilled_result],
        )

        content = generator._render_delta_brief(brief)

        assert "## 🔄 Backfilled Papers" in content
        assert "Existing papers updated with new extraction targets" in content
        assert "Backfilled Paper Title" in content

    def test_renders_backfilled_sorted_by_quality(self, generator):
        """Test that backfilled papers are sorted by quality score."""
        high_quality = ProcessingResult(
            paper_id="high-quality",
            title="High Quality Backfill",
            status=ProcessingStatus.BACKFILLED,
            quality_score=90.0,
            topic_slug="test-topic",
        )
        low_quality = ProcessingResult(
            paper_id="low-quality",
            title="Low Quality Backfill",
            status=ProcessingStatus.BACKFILLED,
            quality_score=30.0,
            topic_slug="test-topic",
        )

        brief = DeltaBrief(
            topic_slug="test-topic",
            backfilled_papers=[low_quality, high_quality],  # Wrong order
        )

        content = generator._render_delta_brief(brief)

        # High quality should appear before low quality
        high_pos = content.find("High Quality Backfill")
        low_pos = content.find("Low Quality Backfill")
        assert high_pos < low_pos

    def test_renders_no_changes_message(self, generator):
        """Test rendering no changes message."""
        brief = DeltaBrief(topic_slug="test-topic")

        content = generator._render_delta_brief(brief)

        assert "## No Changes" in content
        assert "No new papers were discovered" in content


class TestGenerate:
    """Tests for delta file generation."""

    def test_generates_delta_file(self, generator, sample_new_result, temp_output_dir):
        """Test generating delta file."""
        run_date = datetime(2025, 1, 15, tzinfo=timezone.utc)

        path = generator.generate(
            results=[sample_new_result],
            topic_slug="test-topic",
            run_date=run_date,
        )

        assert path is not None
        assert path.exists()
        assert path.name == "2025-01-15_Delta.md"

    def test_generates_in_runs_directory(
        self, generator, sample_new_result, temp_output_dir
    ):
        """Test that delta is generated in runs directory."""
        path = generator.generate(
            results=[sample_new_result],
            topic_slug="test-topic",
        )

        assert path.parent.name == "runs"
        assert path.parent.parent.name == "test-topic"

    def test_returns_none_on_failure(self, generator, mocker):
        """Test that None is returned on write failure."""
        mocker.patch.object(Path, "write_text", side_effect=OSError("Write failed"))

        path = generator.generate(
            results=[],
            topic_slug="test-topic",
        )

        assert path is None


class TestGetDeltaHistory:
    """Tests for getting delta history."""

    def test_returns_empty_for_new_topic(self, generator):
        """Test returns empty list for topic with no deltas."""
        history = generator.get_delta_history("new-topic")

        assert history == []

    def test_returns_sorted_history(self, generator, temp_output_dir):
        """Test returns history sorted by date descending."""
        # Create runs directory with delta files
        runs_dir = temp_output_dir / "test-topic" / "runs"
        runs_dir.mkdir(parents=True)

        (runs_dir / "2025-01-10_Delta.md").write_text("delta 1")
        (runs_dir / "2025-01-15_Delta.md").write_text("delta 2")
        (runs_dir / "2025-01-12_Delta.md").write_text("delta 3")

        history = generator.get_delta_history("test-topic")

        assert len(history) == 3
        # Should be sorted descending (newest first)
        assert history[0].name == "2025-01-15_Delta.md"
        assert history[1].name == "2025-01-12_Delta.md"
        assert history[2].name == "2025-01-10_Delta.md"

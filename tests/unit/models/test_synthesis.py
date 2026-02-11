"""Tests for Phase 3.6 Synthesis models."""

import pytest

from src.models.synthesis import (
    ProcessingStatus,
    ProcessingResult,
    KnowledgeBaseEntry,
    DeltaBrief,
    UserNoteAnchor,
    SynthesisStats,
)


class TestProcessingStatus:
    """Tests for ProcessingStatus enum."""

    def test_new_status_value(self):
        """Test NEW status value."""
        assert ProcessingStatus.NEW.value == "new"

    def test_backfilled_status_value(self):
        """Test BACKFILLED status value."""
        assert ProcessingStatus.BACKFILLED.value == "backfilled"

    def test_skipped_status_value(self):
        """Test SKIPPED status value."""
        assert ProcessingStatus.SKIPPED.value == "skipped"

    def test_mapped_status_value(self):
        """Test MAPPED status value."""
        assert ProcessingStatus.MAPPED.value == "mapped"

    def test_failed_status_value(self):
        """Test FAILED status value."""
        assert ProcessingStatus.FAILED.value == "failed"


class TestProcessingResult:
    """Tests for ProcessingResult model."""

    def test_create_minimal_result(self):
        """Test creating result with minimal fields."""
        result = ProcessingResult(
            paper_id="test-id",
            title="Test Paper",
            status=ProcessingStatus.NEW,
            topic_slug="test-topic",
        )

        assert result.paper_id == "test-id"
        assert result.title == "Test Paper"
        assert result.status == ProcessingStatus.NEW
        assert result.quality_score == 0.0
        assert result.pdf_available is False

    def test_create_full_result(self):
        """Test creating result with all fields."""
        result = ProcessingResult(
            paper_id="test-id",
            title="Test Paper",
            status=ProcessingStatus.NEW,
            quality_score=85.5,
            pdf_available=True,
            extraction_success=True,
            topic_slug="test-topic",
            error_message=None,
            metadata={"key": "value"},
        )

        assert result.quality_score == 85.5
        assert result.pdf_available is True
        assert result.extraction_success is True
        assert result.metadata == {"key": "value"}

    def test_quality_score_bounds(self):
        """Test quality score validation bounds."""
        # Valid score
        result = ProcessingResult(
            paper_id="test-id",
            title="Test",
            status=ProcessingStatus.NEW,
            quality_score=50.0,
            topic_slug="test",
        )
        assert result.quality_score == 50.0

        # Max score
        result = ProcessingResult(
            paper_id="test-id",
            title="Test",
            status=ProcessingStatus.NEW,
            quality_score=100.0,
            topic_slug="test",
        )
        assert result.quality_score == 100.0

    def test_failed_result_with_error(self):
        """Test failed result with error message."""
        result = ProcessingResult(
            paper_id="test-id",
            title="Test Paper",
            status=ProcessingStatus.FAILED,
            topic_slug="test-topic",
            error_message="Connection timeout",
        )

        assert result.status == ProcessingStatus.FAILED
        assert result.error_message == "Connection timeout"


class TestKnowledgeBaseEntry:
    """Tests for KnowledgeBaseEntry model."""

    def test_create_minimal_entry(self):
        """Test creating entry with minimal fields."""
        entry = KnowledgeBaseEntry(
            paper_id="test-id",
            title="Test Paper",
        )

        assert entry.paper_id == "test-id"
        assert entry.title == "Test Paper"
        assert entry.authors == []
        assert entry.quality_score == 0.0

    def test_create_full_entry(self):
        """Test creating entry with all fields."""
        entry = KnowledgeBaseEntry(
            paper_id="test-id",
            title="Test Paper",
            authors=["Author A", "Author B"],
            abstract="Test abstract",
            url="https://example.com",
            doi="10.1234/test",
            arxiv_id="2301.12345",
            publication_date="2025-01-01",
            quality_score=90.0,
            pdf_available=True,
            pdf_path="/data/test.pdf",
            extraction_results={"prompts": "test"},
            topic_affiliations=["topic-a", "topic-b"],
        )

        assert entry.authors == ["Author A", "Author B"]
        assert entry.doi == "10.1234/test"
        assert entry.quality_score == 90.0
        assert len(entry.topic_affiliations) == 2


class TestDeltaBrief:
    """Tests for DeltaBrief model."""

    def test_create_empty_brief(self):
        """Test creating empty delta brief."""
        brief = DeltaBrief(topic_slug="test-topic")

        assert brief.topic_slug == "test-topic"
        assert brief.total_new == 0
        assert brief.total_backfilled == 0
        assert brief.has_changes is False

    def test_brief_with_new_papers(self):
        """Test brief with new papers."""
        new_paper = ProcessingResult(
            paper_id="new-1",
            title="New Paper",
            status=ProcessingStatus.NEW,
            topic_slug="test-topic",
        )

        brief = DeltaBrief(
            topic_slug="test-topic",
            new_papers=[new_paper],
        )

        assert brief.total_new == 1
        assert brief.has_changes is True

    def test_brief_with_backfilled_papers(self):
        """Test brief with backfilled papers."""
        backfilled = ProcessingResult(
            paper_id="back-1",
            title="Backfilled Paper",
            status=ProcessingStatus.BACKFILLED,
            topic_slug="test-topic",
        )

        brief = DeltaBrief(
            topic_slug="test-topic",
            backfilled_papers=[backfilled],
        )

        assert brief.total_backfilled == 1
        assert brief.has_changes is True

    def test_brief_with_skipped_and_failed(self):
        """Test brief with skipped and failed counts."""
        brief = DeltaBrief(
            topic_slug="test-topic",
            skipped_count=10,
            failed_count=2,
        )

        assert brief.skipped_count == 10
        assert brief.failed_count == 2
        assert brief.has_changes is False


class TestUserNoteAnchor:
    """Tests for UserNoteAnchor model."""

    def test_create_anchor(self):
        """Test creating user note anchor."""
        anchor = UserNoteAnchor(
            paper_id="test-id",
            content="My notes about this paper.",
        )

        assert anchor.paper_id == "test-id"
        assert anchor.content == "My notes about this paper."

    def test_create_start_tag(self):
        """Test creating start anchor tag."""
        tag = UserNoteAnchor.create_start_tag("abc-123")
        assert tag == "<!-- USER_NOTES_START:abc-123 -->"

    def test_create_end_tag(self):
        """Test creating end anchor tag."""
        tag = UserNoteAnchor.create_end_tag("abc-123")
        assert tag == "<!-- USER_NOTES_END:abc-123 -->"

    def test_script_injection_blocked(self):
        """Test that script tags are blocked in content."""
        with pytest.raises(ValueError, match="Script tags"):
            UserNoteAnchor(
                paper_id="test-id",
                content="<script>alert('xss')</script>",
            )

    def test_case_insensitive_script_block(self):
        """Test script blocking is case insensitive."""
        with pytest.raises(ValueError, match="Script tags"):
            UserNoteAnchor(
                paper_id="test-id",
                content="<SCRIPT>alert('xss')</SCRIPT>",
            )

    def test_valid_html_allowed(self):
        """Test that non-script HTML is allowed."""
        anchor = UserNoteAnchor(
            paper_id="test-id",
            content="<b>Bold text</b> and <i>italic</i>",
        )
        assert "<b>Bold text</b>" in anchor.content


class TestSynthesisStats:
    """Tests for SynthesisStats model."""

    def test_create_empty_stats(self):
        """Test creating empty stats."""
        stats = SynthesisStats(topic_slug="test-topic")

        assert stats.topic_slug == "test-topic"
        assert stats.total_papers == 0
        assert stats.average_quality == 0.0

    def test_create_full_stats(self):
        """Test creating stats with all fields."""
        stats = SynthesisStats(
            topic_slug="test-topic",
            total_papers=100,
            papers_with_pdf=80,
            papers_with_extraction=75,
            average_quality=72.5,
            top_quality_score=95.0,
            user_notes_preserved=5,
            synthesis_duration_ms=1500,
        )

        assert stats.total_papers == 100
        assert stats.papers_with_pdf == 80
        assert stats.average_quality == 72.5
        assert stats.synthesis_duration_ms == 1500

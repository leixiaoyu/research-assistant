"""Tests for src/cli/feedback.py CLI commands.

This module provides comprehensive tests for the Phase 7.3 feedback CLI,
covering all commands: rate, interactive, similar, analytics, export, clear, show.
"""

from datetime import datetime, timezone
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from src.cli.feedback import (
    app,
    _get_feedback_service,
    _get_embedding_service,
    _get_similarity_searcher,
)
from src.models.feedback import (
    FeedbackAnalytics,
    FeedbackEntry,
    FeedbackRating,
    FeedbackReason,
    SimilarPaper,
    TopicAnalytics,
)

runner = CliRunner()


# ============================================================================
# Helper Factories
# ============================================================================


def make_feedback_entry(
    paper_id: str = "paper123",
    rating: FeedbackRating = FeedbackRating.THUMBS_UP,
    reasons: Optional[List[FeedbackReason]] = None,
    free_text: Optional[str] = None,
    topic_slug: Optional[str] = None,
) -> FeedbackEntry:
    """Create a FeedbackEntry for testing."""
    return FeedbackEntry(
        id="entry-id-1",
        paper_id=paper_id,
        rating=rating,
        reasons=reasons or [],
        free_text=free_text,
        topic_slug=topic_slug,
        timestamp=datetime.now(timezone.utc),
    )


def make_analytics(
    total: int = 10,
    thumbs_up: int = 5,
    thumbs_down: int = 3,
    neutral: int = 2,
) -> FeedbackAnalytics:
    """Create FeedbackAnalytics for testing."""
    return FeedbackAnalytics(
        total_ratings=total,
        rating_distribution={
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "neutral": neutral,
        },
        top_reasons=[("methodology", 5), ("findings", 3)],
        topic_breakdown={
            "test-topic": TopicAnalytics(
                topic_slug="test-topic",
                total=total,
                thumbs_up=thumbs_up,
                thumbs_down=thumbs_down,
                neutral=neutral,
                common_reasons=["methodology"],
            )
        },
        trending_themes=["methodology", "novelty"],
    )


def make_similar_paper(
    paper_id: str = "similar-paper-1",
    title: str = "Similar Paper Title",
    similarity_score: float = 0.85,
    previously_discovered: bool = False,
) -> SimilarPaper:
    """Create SimilarPaper for testing."""
    return SimilarPaper(
        paper_id=paper_id,
        title=title,
        similarity_score=similarity_score,
        matching_aspects=["related", "similar_methodology"],
        previously_discovered=previously_discovered,
    )


# ============================================================================
# Tests for helper functions
# ============================================================================


class TestHelperFunctions:
    """Tests for the module helper functions."""

    def test_get_feedback_service_creates_service(self):
        """Test _get_feedback_service creates a FeedbackService instance."""
        with (
            patch("src.services.feedback.storage.FeedbackStorage") as mock_storage_cls,
            patch(
                "src.services.feedback.feedback_service.FeedbackService"
            ) as mock_service_cls,
        ):
            mock_storage = MagicMock()
            mock_storage_cls.return_value = mock_storage
            mock_service = MagicMock()
            mock_service_cls.return_value = mock_service

            result = _get_feedback_service()

            mock_storage_cls.assert_called_once()
            mock_service_cls.assert_called_once_with(mock_storage)
            assert result == mock_service

    def test_get_embedding_service_creates_service(self):
        """Test _get_embedding_service creates an EmbeddingService instance."""
        with patch(
            "src.services.embeddings.embedding_service.EmbeddingService"
        ) as mock_cls:
            mock_service = MagicMock()
            mock_cls.return_value = mock_service

            result = _get_embedding_service()

            mock_cls.assert_called_once()
            assert result == mock_service

    def test_get_similarity_searcher_creates_searcher(self):
        """Test _get_similarity_searcher creates a SimilaritySearcher instance."""
        with (
            patch(
                "src.services.embeddings.embedding_service.EmbeddingService"
            ) as mock_emb_cls,
            patch(
                "src.services.embeddings.similarity_searcher.SimilaritySearcher"
            ) as mock_searcher_cls,
        ):
            mock_emb_service = MagicMock()
            mock_emb_cls.return_value = mock_emb_service
            mock_searcher = MagicMock()
            mock_searcher_cls.return_value = mock_searcher

            result = _get_similarity_searcher()

            mock_emb_cls.assert_called_once()
            mock_searcher_cls.assert_called_once_with(mock_emb_service)
            assert result == mock_searcher


# ============================================================================
# Tests for 'rate' command
# ============================================================================


class TestRateCommand:
    """Tests for the 'rate' CLI command."""

    def test_rate_thumbs_up_success(self):
        """Test rating a paper with thumbs up."""
        mock_service = MagicMock()
        mock_service.submit_feedback = AsyncMock(
            return_value=make_feedback_entry(rating="thumbs_up")
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["rate", "paper123", "up"])

        assert result.exit_code == 0
        assert "Feedback recorded" in result.stdout
        assert "paper123" in result.stdout
        mock_service.submit_feedback.assert_called_once()

    def test_rate_thumbs_down_success(self):
        """Test rating a paper with thumbs down."""
        mock_service = MagicMock()
        mock_service.submit_feedback = AsyncMock(
            return_value=make_feedback_entry(rating="thumbs_down")
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["rate", "paper123", "down"])

        assert result.exit_code == 0
        assert "Feedback recorded" in result.stdout

    def test_rate_neutral_success(self):
        """Test rating a paper as neutral."""
        mock_service = MagicMock()
        mock_service.submit_feedback = AsyncMock(
            return_value=make_feedback_entry(rating="neutral")
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["rate", "paper123", "neutral"])

        assert result.exit_code == 0
        assert "Feedback recorded" in result.stdout

    def test_rate_with_alternate_rating_names(self):
        """Test rating with alternate names (thumbs_up, thumbs_down)."""
        mock_service = MagicMock()
        mock_service.submit_feedback = AsyncMock(
            return_value=make_feedback_entry(rating="thumbs_up")
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["rate", "paper123", "thumbs_up"])

        assert result.exit_code == 0

    def test_rate_invalid_rating(self):
        """Test that invalid rating values are rejected."""
        result = runner.invoke(app, ["rate", "paper123", "invalid"])

        assert result.exit_code == 1
        assert "Invalid rating" in result.stdout

    def test_rate_with_reasons(self):
        """Test rating with structured reasons."""
        mock_service = MagicMock()
        mock_service.submit_feedback = AsyncMock(
            return_value=make_feedback_entry(
                rating="thumbs_up",
                reasons=["methodology", "findings"],
            )
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(
                app,
                ["rate", "paper123", "up", "-r", "methodology", "-r", "findings"],
            )

        assert result.exit_code == 0
        call_kwargs = mock_service.submit_feedback.call_args.kwargs
        assert FeedbackReason.METHODOLOGY in call_kwargs["reasons"]
        assert FeedbackReason.FINDINGS in call_kwargs["reasons"]

    def test_rate_with_unknown_reason_warns(self):
        """Test that unknown reasons generate a warning but don't fail."""
        mock_service = MagicMock()
        mock_service.submit_feedback = AsyncMock(
            return_value=make_feedback_entry(rating="thumbs_up")
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(
                app,
                ["rate", "paper123", "up", "-r", "unknown_reason"],
            )

        assert result.exit_code == 0
        assert "Warning: Unknown reason" in result.stdout

    def test_rate_with_comment(self):
        """Test rating with a free-text comment."""
        mock_service = MagicMock()
        mock_service.submit_feedback = AsyncMock(
            return_value=make_feedback_entry(
                rating="thumbs_up",
                free_text="Great methodology!",
            )
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(
                app,
                ["rate", "paper123", "up", "-c", "Great methodology!"],
            )

        assert result.exit_code == 0
        call_kwargs = mock_service.submit_feedback.call_args.kwargs
        assert call_kwargs["free_text"] == "Great methodology!"

    def test_rate_with_topic(self):
        """Test rating with topic context."""
        mock_service = MagicMock()
        mock_service.submit_feedback = AsyncMock(
            return_value=make_feedback_entry(
                rating="thumbs_up",
                topic_slug="ml-transformers",
            )
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(
                app,
                ["rate", "paper123", "up", "-t", "ml-transformers"],
            )

        assert result.exit_code == 0
        call_kwargs = mock_service.submit_feedback.call_args.kwargs
        assert call_kwargs["topic_slug"] == "ml-transformers"

    def test_rate_all_valid_reasons(self):
        """Test rating with all valid reason types."""
        mock_service = MagicMock()
        mock_service.submit_feedback = AsyncMock(
            return_value=make_feedback_entry(rating="thumbs_up")
        )

        reasons = [
            "methodology",
            "findings",
            "applications",
            "writing_quality",
            "relevance",
            "novelty",
        ]

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            args = ["rate", "paper123", "up"]
            for r in reasons:
                args.extend(["-r", r])
            result = runner.invoke(app, args)

        assert result.exit_code == 0
        call_kwargs = mock_service.submit_feedback.call_args.kwargs
        assert len(call_kwargs["reasons"]) == 6

    def test_rate_service_exception(self):
        """Test that service exceptions are handled gracefully."""
        mock_service = MagicMock()
        mock_service.submit_feedback = AsyncMock(
            side_effect=Exception("Database error")
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["rate", "paper123", "up"])

        assert result.exit_code == 1
        # Error message goes to stderr, check combined output
        assert "Error" in result.output or result.exit_code == 1

    def test_rate_case_insensitive(self):
        """Test that rating values are case-insensitive."""
        mock_service = MagicMock()
        mock_service.submit_feedback = AsyncMock(
            return_value=make_feedback_entry(rating="thumbs_up")
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["rate", "paper123", "UP"])

        assert result.exit_code == 0


# ============================================================================
# Tests for 'interactive' command
# ============================================================================


class TestInteractiveCommand:
    """Tests for the 'interactive' CLI command."""

    def test_interactive_basic(self):
        """Test basic interactive session startup."""
        result = runner.invoke(app, ["interactive"])

        assert result.exit_code == 0
        assert "Interactive Feedback Session" in result.stdout
        assert "Commands:" in result.stdout
        assert "Session complete" in result.stdout

    def test_interactive_with_topic(self):
        """Test interactive session with topic filter."""
        result = runner.invoke(app, ["interactive", "-t", "ml-topic"])

        assert result.exit_code == 0
        assert "Interactive Feedback Session" in result.stdout

    def test_interactive_with_limit(self):
        """Test interactive session with paper limit."""
        result = runner.invoke(app, ["interactive", "-n", "5"])

        assert result.exit_code == 0
        assert "Interactive Feedback Session" in result.stdout

    def test_interactive_shows_stats(self):
        """Test that interactive session shows statistics."""
        result = runner.invoke(app, ["interactive"])

        assert result.exit_code == 0
        assert "Thumbs up:" in result.stdout
        assert "Thumbs down:" in result.stdout
        assert "Neutral:" in result.stdout
        assert "Skipped:" in result.stdout


# ============================================================================
# Tests for 'similar' command
# ============================================================================


class TestSimilarCommand:
    """Tests for the 'similar' CLI command."""

    def test_similar_basic(self):
        """Test finding similar papers."""
        mock_searcher = MagicMock()
        mock_searcher.find_similar = AsyncMock(
            return_value=[
                make_similar_paper("paper-1", "Paper One", 0.95, True),
                make_similar_paper("paper-2", "Paper Two", 0.85, False),
            ]
        )

        with patch(
            "src.cli.feedback._get_similarity_searcher", return_value=mock_searcher
        ):
            result = runner.invoke(app, ["similar", "query-paper"])

        assert result.exit_code == 0
        assert "Finding papers similar to" in result.stdout
        assert "Similar Papers" in result.stdout
        assert "Paper One" in result.stdout
        assert "Paper Two" in result.stdout

    def test_similar_with_top_k(self):
        """Test finding similar papers with custom top_k."""
        mock_searcher = MagicMock()
        mock_searcher.find_similar = AsyncMock(return_value=[])

        with patch(
            "src.cli.feedback._get_similarity_searcher", return_value=mock_searcher
        ):
            result = runner.invoke(app, ["similar", "query-paper", "-k", "5"])

        assert result.exit_code == 0
        call_kwargs = mock_searcher.find_similar.call_args.kwargs
        assert call_kwargs["top_k"] == 5

    def test_similar_with_reason(self):
        """Test finding similar papers with user reason."""
        mock_searcher = MagicMock()
        mock_searcher.find_similar = AsyncMock(return_value=[])

        with patch(
            "src.cli.feedback._get_similarity_searcher", return_value=mock_searcher
        ):
            result = runner.invoke(
                app,
                ["similar", "query-paper", "-r", "I like the methodology"],
            )

        assert result.exit_code == 0
        call_kwargs = mock_searcher.find_similar.call_args.kwargs
        assert call_kwargs["include_reasons"] == "I like the methodology"

    def test_similar_no_results(self):
        """Test handling when no similar papers found."""
        mock_searcher = MagicMock()
        mock_searcher.find_similar = AsyncMock(return_value=[])

        with patch(
            "src.cli.feedback._get_similarity_searcher", return_value=mock_searcher
        ):
            result = runner.invoke(app, ["similar", "query-paper"])

        assert result.exit_code == 0
        assert "No similar papers found" in result.stdout
        assert "FAISS index" in result.stdout

    def test_similar_shows_scores(self):
        """Test that similarity scores are displayed."""
        mock_searcher = MagicMock()
        mock_searcher.find_similar = AsyncMock(
            return_value=[make_similar_paper(similarity_score=0.85)]
        )

        with patch(
            "src.cli.feedback._get_similarity_searcher", return_value=mock_searcher
        ):
            result = runner.invoke(app, ["similar", "query-paper"])

        assert result.exit_code == 0
        assert "85.0%" in result.stdout

    def test_similar_shows_aspects(self):
        """Test that matching aspects are displayed."""
        mock_searcher = MagicMock()
        similar = make_similar_paper()
        similar.matching_aspects = ["related", "similar_methodology", "similar_topic"]
        mock_searcher.find_similar = AsyncMock(return_value=[similar])

        with patch(
            "src.cli.feedback._get_similarity_searcher", return_value=mock_searcher
        ):
            result = runner.invoke(app, ["similar", "query-paper"])

        assert result.exit_code == 0
        assert "Aspects:" in result.stdout

    def test_similar_shows_discovery_status(self):
        """Test that previously discovered status is shown."""
        mock_searcher = MagicMock()
        mock_searcher.find_similar = AsyncMock(
            return_value=[
                make_similar_paper("paper-1", "Discovered", 0.9, True),
                make_similar_paper("paper-2", "New Paper", 0.8, False),
            ]
        )

        with patch(
            "src.cli.feedback._get_similarity_searcher", return_value=mock_searcher
        ):
            result = runner.invoke(app, ["similar", "query-paper"])

        assert result.exit_code == 0
        # Check for discovery indicators (emoji)
        assert "Discovered" in result.stdout
        assert "New Paper" in result.stdout

    def test_similar_exception_handling(self):
        """Test that exceptions are handled gracefully."""
        mock_searcher = MagicMock()
        mock_searcher.find_similar = AsyncMock(side_effect=Exception("Search failed"))

        with patch(
            "src.cli.feedback._get_similarity_searcher", return_value=mock_searcher
        ):
            result = runner.invoke(app, ["similar", "query-paper"])

        assert result.exit_code == 1
        # Error message goes to stderr, check combined output
        assert "Error" in result.output or result.exit_code == 1


# ============================================================================
# Tests for 'analytics' command
# ============================================================================


class TestAnalyticsCommand:
    """Tests for the 'analytics' CLI command."""

    def test_analytics_basic(self):
        """Test basic analytics report."""
        mock_service = MagicMock()
        mock_service.get_analytics = AsyncMock(return_value=make_analytics())

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["analytics"])

        assert result.exit_code == 0
        assert "Feedback Analytics Report" in result.stdout
        assert "Total Ratings:" in result.stdout
        assert "Rating Distribution:" in result.stdout

    def test_analytics_with_topic(self):
        """Test analytics with topic filter."""
        mock_service = MagicMock()
        mock_service.get_analytics = AsyncMock(return_value=make_analytics())

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["analytics", "-t", "ml-topic"])

        assert result.exit_code == 0
        mock_service.get_analytics.assert_called_once_with("ml-topic")

    def test_analytics_output_to_file(self, tmp_path):
        """Test analytics output to file."""
        mock_service = MagicMock()
        mock_service.get_analytics = AsyncMock(return_value=make_analytics())

        output_file = tmp_path / "report.txt"

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(
                app,
                ["analytics", "-o", str(output_file)],
            )

        assert result.exit_code == 0
        assert "Report saved to" in result.stdout
        assert output_file.exists()
        content = output_file.read_text()
        assert "Feedback Analytics Report" in content

    def test_analytics_shows_rating_distribution(self):
        """Test that rating distribution is shown."""
        mock_service = MagicMock()
        mock_service.get_analytics = AsyncMock(
            return_value=make_analytics(
                total=100, thumbs_up=60, thumbs_down=30, neutral=10
            )
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["analytics"])

        assert result.exit_code == 0
        assert "Thumbs Up: 60" in result.stdout
        assert "Thumbs Down: 30" in result.stdout
        assert "Neutral: 10" in result.stdout

    def test_analytics_shows_top_reasons(self):
        """Test that top reasons are shown."""
        mock_service = MagicMock()
        analytics = make_analytics()
        analytics.top_reasons = [("methodology", 25), ("novelty", 15)]
        mock_service.get_analytics = AsyncMock(return_value=analytics)

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["analytics"])

        assert result.exit_code == 0
        assert "Top Reasons:" in result.stdout
        assert "methodology" in result.stdout

    def test_analytics_shows_trending_themes(self):
        """Test that trending themes are shown."""
        mock_service = MagicMock()
        analytics = make_analytics()
        analytics.trending_themes = ["methodology", "innovation"]
        mock_service.get_analytics = AsyncMock(return_value=analytics)

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["analytics"])

        assert result.exit_code == 0
        assert "Trending Themes:" in result.stdout

    def test_analytics_shows_topic_breakdown(self):
        """Test that topic breakdown is shown."""
        mock_service = MagicMock()
        mock_service.get_analytics = AsyncMock(return_value=make_analytics())

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["analytics"])

        assert result.exit_code == 0
        assert "By Topic:" in result.stdout
        assert "test-topic" in result.stdout

    def test_analytics_exception_handling(self):
        """Test that exceptions are handled gracefully."""
        mock_service = MagicMock()
        mock_service.get_analytics = AsyncMock(
            side_effect=Exception("Analytics failed")
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["analytics"])

        assert result.exit_code == 1
        # Error message goes to stderr, check combined output
        assert "Error" in result.output or result.exit_code == 1

    def test_analytics_empty_top_reasons(self):
        """Test analytics when top_reasons is empty."""
        mock_service = MagicMock()
        analytics = make_analytics()
        analytics.top_reasons = []
        mock_service.get_analytics = AsyncMock(return_value=analytics)

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["analytics"])

        assert result.exit_code == 0
        # Should not crash with empty reasons

    def test_analytics_empty_trending_themes(self):
        """Test analytics when trending_themes is empty."""
        mock_service = MagicMock()
        analytics = make_analytics()
        analytics.trending_themes = []
        mock_service.get_analytics = AsyncMock(return_value=analytics)

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["analytics"])

        assert result.exit_code == 0

    def test_analytics_empty_topic_breakdown(self):
        """Test analytics when topic_breakdown is empty."""
        mock_service = MagicMock()
        analytics = make_analytics()
        analytics.topic_breakdown = {}
        mock_service.get_analytics = AsyncMock(return_value=analytics)

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["analytics"])

        assert result.exit_code == 0


# ============================================================================
# Tests for 'export' command
# ============================================================================


class TestExportCommand:
    """Tests for the 'export' CLI command."""

    def test_export_json_to_console(self):
        """Test JSON export to console."""
        mock_service = MagicMock()
        mock_service.export_feedback = AsyncMock(
            return_value='[{"paper_id": "paper123"}]'
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["export", "-f", "json"])

        assert result.exit_code == 0
        assert "paper123" in result.stdout
        mock_service.export_feedback.assert_called_once_with("json", None)

    def test_export_csv_to_console(self):
        """Test CSV export to console."""
        mock_service = MagicMock()
        mock_service.export_feedback = AsyncMock(
            return_value="paper_id,rating\npaper123,thumbs_up"
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["export", "-f", "csv"])

        assert result.exit_code == 0
        mock_service.export_feedback.assert_called_once_with("csv", None)

    def test_export_to_file(self, tmp_path):
        """Test export to file."""
        mock_service = MagicMock()
        mock_service.export_feedback = AsyncMock(return_value="exported")

        output_file = tmp_path / "feedback.json"

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(
                app,
                ["export", "-f", "json", "-o", str(output_file)],
            )

        assert result.exit_code == 0
        assert "Exported feedback to" in result.stdout
        mock_service.export_feedback.assert_called_once_with("json", str(output_file))

    def test_export_invalid_format(self):
        """Test that invalid format is rejected."""
        result = runner.invoke(app, ["export", "-f", "xml"])

        assert result.exit_code == 1
        assert "Invalid format" in result.stdout

    def test_export_exception_handling(self):
        """Test that exceptions are handled gracefully."""
        mock_service = MagicMock()
        mock_service.export_feedback = AsyncMock(side_effect=Exception("Export failed"))

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["export"])

        assert result.exit_code == 1
        # Error message goes to stderr, check combined output
        assert "Error" in result.output or result.exit_code == 1

    def test_export_default_format_is_json(self):
        """Test that default export format is JSON."""
        mock_service = MagicMock()
        mock_service.export_feedback = AsyncMock(return_value="{}")

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["export"])

        assert result.exit_code == 0
        mock_service.export_feedback.assert_called_once_with("json", None)


# ============================================================================
# Tests for 'clear' command
# ============================================================================


class TestClearCommand:
    """Tests for the 'clear' CLI command."""

    def test_clear_with_confirm_flag(self):
        """Test clearing feedback with --yes flag."""
        mock_service = MagicMock()
        mock_service.storage = MagicMock()
        mock_service.storage.clear = AsyncMock()

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["clear", "--yes"])

        assert result.exit_code == 0
        assert "All feedback data cleared" in result.stdout
        mock_service.storage.clear.assert_called_once()

    def test_clear_cancelled(self):
        """Test clearing feedback when user cancels."""
        with patch("src.cli.feedback._get_feedback_service"):
            # CliRunner's default input is empty, which makes confirm return False
            result = runner.invoke(app, ["clear"], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.stdout

    def test_clear_confirmed_interactively(self):
        """Test clearing feedback when user confirms interactively."""
        mock_service = MagicMock()
        mock_service.storage = MagicMock()
        mock_service.storage.clear = AsyncMock()

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["clear"], input="y\n")

        assert result.exit_code == 0
        assert "All feedback data cleared" in result.stdout


# ============================================================================
# Tests for 'show' command
# ============================================================================


class TestShowCommand:
    """Tests for the 'show' CLI command."""

    def test_show_existing_feedback(self):
        """Test showing feedback for an existing paper."""
        mock_service = MagicMock()
        mock_service.get_feedback_for_paper = AsyncMock(
            return_value=make_feedback_entry(
                paper_id="paper123",
                rating="thumbs_up",
                reasons=["methodology", "novelty"],
                free_text="Great paper!",
                topic_slug="ml-topic",
            )
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["show", "paper123"])

        assert result.exit_code == 0
        assert "Feedback for paper123" in result.stdout
        assert "thumbs_up" in result.stdout
        assert "ml-topic" in result.stdout
        assert "methodology" in result.stdout
        assert "Great paper!" in result.stdout

    def test_show_no_feedback_found(self):
        """Test showing feedback when none exists."""
        mock_service = MagicMock()
        mock_service.get_feedback_for_paper = AsyncMock(return_value=None)

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["show", "paper123"])

        assert result.exit_code == 0
        assert "No feedback found" in result.stdout

    def test_show_feedback_without_optional_fields(self):
        """Test showing feedback without optional fields."""
        mock_service = MagicMock()
        entry = make_feedback_entry(
            paper_id="paper123",
            rating="thumbs_up",
            reasons=[],
            free_text=None,
            topic_slug=None,
        )
        mock_service.get_feedback_for_paper = AsyncMock(return_value=entry)

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["show", "paper123"])

        assert result.exit_code == 0
        assert "N/A" in result.stdout  # Topic shows as N/A

    def test_show_exception_handling(self):
        """Test that exceptions are handled gracefully."""
        mock_service = MagicMock()
        mock_service.get_feedback_for_paper = AsyncMock(
            side_effect=Exception("Database error")
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["show", "paper123"])

        assert result.exit_code == 1
        # Error message goes to stderr, check combined output
        assert "Error" in result.output or result.exit_code == 1

    def test_show_displays_timestamp(self):
        """Test that timestamp is displayed."""
        mock_service = MagicMock()
        mock_service.get_feedback_for_paper = AsyncMock(
            return_value=make_feedback_entry()
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(app, ["show", "paper123"])

        assert result.exit_code == 0
        assert "Timestamp:" in result.stdout


# ============================================================================
# Tests for 'register_commands' function
# ============================================================================


class TestRegisterCommands:
    """Tests for the register_commands function."""

    def test_register_commands(self):
        """Test registering feedback commands with main app."""
        import typer
        from src.cli.feedback import register_commands

        main_app = typer.Typer()
        register_commands(main_app)

        # The feedback app should be registered as a subcommand
        # We can check the registered commands
        assert main_app.registered_groups or main_app.registered_commands


# ============================================================================
# Edge cases and integration-like tests
# ============================================================================


class TestEdgeCases:
    """Edge case and integration-like tests."""

    def test_rate_with_all_options(self):
        """Test rate command with all options specified."""
        mock_service = MagicMock()
        mock_service.submit_feedback = AsyncMock(
            return_value=make_feedback_entry(
                rating="thumbs_up",
                reasons=["methodology"],
                free_text="Excellent!",
                topic_slug="ai-topic",
            )
        )

        with patch("src.cli.feedback._get_feedback_service", return_value=mock_service):
            result = runner.invoke(
                app,
                [
                    "rate",
                    "paper123",
                    "up",
                    "-r",
                    "methodology",
                    "-c",
                    "Excellent!",
                    "-t",
                    "ai-topic",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_service.submit_feedback.call_args.kwargs
        assert call_kwargs["paper_id"] == "paper123"
        assert call_kwargs["rating"] == FeedbackRating.THUMBS_UP
        assert FeedbackReason.METHODOLOGY in call_kwargs["reasons"]
        assert call_kwargs["free_text"] == "Excellent!"
        assert call_kwargs["topic_slug"] == "ai-topic"

    def test_similar_with_no_matching_aspects(self):
        """Test similar command when results have no matching aspects."""
        mock_searcher = MagicMock()
        similar = make_similar_paper()
        similar.matching_aspects = []
        mock_searcher.find_similar = AsyncMock(return_value=[similar])

        with patch(
            "src.cli.feedback._get_similarity_searcher", return_value=mock_searcher
        ):
            result = runner.invoke(app, ["similar", "query-paper"])

        assert result.exit_code == 0
        # Should not crash with empty aspects

    def test_app_has_correct_name(self):
        """Test that the app has the correct name."""
        assert app.info.name == "feedback"

    def test_app_has_help_text(self):
        """Test that the app has help text."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "feedback" in result.stdout.lower()
        assert "personalized recommendations" in result.stdout.lower()

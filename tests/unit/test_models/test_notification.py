"""Unit tests for notification models (Phase 3.7).

Tests Pydantic validation, serialization, and business logic for:
- SlackConfig
- KeyLearning
- NotificationSettings
- NotificationResult
- PipelineSummary
"""

import pytest
from pydantic import ValidationError

from src.models.notification import (
    SlackConfig,
    KeyLearning,
    NotificationSettings,
    NotificationResult,
    PipelineSummary,
)


class TestSlackConfig:
    """Tests for SlackConfig model."""

    def test_default_values(self) -> None:
        """Test SlackConfig has sensible defaults."""
        config = SlackConfig()

        assert config.enabled is False
        assert config.webhook_url is None
        assert config.channel_override is None
        assert config.notify_on_success is True
        assert config.notify_on_failure is True
        assert config.notify_on_partial is True
        assert config.include_cost_summary is True
        assert config.include_key_learnings is True
        assert config.max_learnings_per_topic == 2
        assert config.mention_on_failure is None
        assert config.timeout_seconds == 10.0

    def test_enabled_with_webhook(self) -> None:
        """Test SlackConfig with valid webhook URL."""
        config = SlackConfig(
            enabled=True,
            webhook_url="https://hooks.slack.com/services/T00/B00/XXX",
        )

        assert config.enabled is True
        assert str(config.webhook_url) == "https://hooks.slack.com/services/T00/B00/XXX"

    def test_webhook_url_validation_none(self) -> None:
        """Test webhook URL can be None."""
        config = SlackConfig(webhook_url=None)
        assert config.webhook_url is None

    def test_webhook_url_validation_empty_string(self) -> None:
        """Test empty string becomes None."""
        config = SlackConfig(webhook_url="")
        assert config.webhook_url is None

    def test_webhook_url_validation_env_var_placeholder(self) -> None:
        """Test env var placeholder becomes None."""
        config = SlackConfig(webhook_url="${SLACK_WEBHOOK_URL}")
        assert config.webhook_url is None

    def test_channel_override_with_hash(self) -> None:
        """Test channel override with # prefix."""
        config = SlackConfig(channel_override="#alerts")
        assert config.channel_override == "#alerts"

    def test_channel_override_with_at(self) -> None:
        """Test channel override with @ prefix (DM)."""
        config = SlackConfig(channel_override="@user")
        assert config.channel_override == "@user"

    def test_channel_override_invalid(self) -> None:
        """Test channel override without valid prefix raises error."""
        with pytest.raises(ValidationError) as exc_info:
            SlackConfig(channel_override="invalid-channel")

        assert "Channel must start with '#' or '@'" in str(exc_info.value)

    def test_channel_override_empty_string(self) -> None:
        """Test empty string becomes None."""
        config = SlackConfig(channel_override="")
        assert config.channel_override is None

    def test_mention_on_failure_channel(self) -> None:
        """Test <!channel> mention format."""
        config = SlackConfig(mention_on_failure="<!channel>")
        assert config.mention_on_failure == "<!channel>"

    def test_mention_on_failure_here(self) -> None:
        """Test <!here> mention format."""
        config = SlackConfig(mention_on_failure="<!here>")
        assert config.mention_on_failure == "<!here>"

    def test_mention_on_failure_user(self) -> None:
        """Test <@USER_ID> mention format."""
        config = SlackConfig(mention_on_failure="<@U12345678>")
        assert config.mention_on_failure == "<@U12345678>"

    def test_mention_on_failure_subteam(self) -> None:
        """Test <!subteam^...> mention format."""
        config = SlackConfig(mention_on_failure="<!subteam^S12345>")
        assert config.mention_on_failure == "<!subteam^S12345>"

    def test_mention_on_failure_invalid(self) -> None:
        """Test invalid mention format raises error."""
        with pytest.raises(ValidationError) as exc_info:
            SlackConfig(mention_on_failure="@invalid")

        assert "valid Slack mention" in str(exc_info.value)

    def test_mention_on_failure_empty_string(self) -> None:
        """Test empty string becomes None."""
        config = SlackConfig(mention_on_failure="")
        assert config.mention_on_failure is None

    def test_max_learnings_per_topic_bounds(self) -> None:
        """Test max_learnings_per_topic validation."""
        # Valid values
        assert SlackConfig(max_learnings_per_topic=1).max_learnings_per_topic == 1
        assert SlackConfig(max_learnings_per_topic=10).max_learnings_per_topic == 10

        # Invalid values
        with pytest.raises(ValidationError):
            SlackConfig(max_learnings_per_topic=0)

        with pytest.raises(ValidationError):
            SlackConfig(max_learnings_per_topic=11)

    def test_timeout_seconds_bounds(self) -> None:
        """Test timeout_seconds validation."""
        # Valid values
        assert SlackConfig(timeout_seconds=1.0).timeout_seconds == 1.0
        assert SlackConfig(timeout_seconds=60.0).timeout_seconds == 60.0

        # Invalid values
        with pytest.raises(ValidationError):
            SlackConfig(timeout_seconds=0.5)

        with pytest.raises(ValidationError):
            SlackConfig(timeout_seconds=61.0)


class TestKeyLearning:
    """Tests for KeyLearning model."""

    def test_basic_creation(self) -> None:
        """Test basic KeyLearning creation."""
        learning = KeyLearning(
            paper_title="Test Paper Title",
            topic="test-topic",
            summary="This is a test summary.",
        )

        assert learning.paper_title == "Test Paper Title"
        assert learning.topic == "test-topic"
        assert learning.summary == "This is a test summary."

    def test_summary_truncation(self) -> None:
        """Test summary is truncated to max length."""
        long_summary = "x" * 600  # Exceeds 500 char limit
        learning = KeyLearning(
            paper_title="Test",
            topic="test",
            summary=long_summary,
        )

        assert len(learning.summary) == 500
        assert learning.summary.endswith("...")

    def test_summary_not_truncated_when_short(self) -> None:
        """Test short summary is not truncated."""
        short_summary = "Short summary."
        learning = KeyLearning(
            paper_title="Test",
            topic="test",
            summary=short_summary,
        )

        assert learning.summary == short_summary
        assert not learning.summary.endswith("...")

    def test_empty_fields_rejected(self) -> None:
        """Test empty required fields are rejected."""
        with pytest.raises(ValidationError):
            KeyLearning(paper_title="", topic="test", summary="test")

        with pytest.raises(ValidationError):
            KeyLearning(paper_title="test", topic="", summary="test")

        with pytest.raises(ValidationError):
            KeyLearning(paper_title="test", topic="test", summary="")


class TestNotificationSettings:
    """Tests for NotificationSettings model."""

    def test_default_slack_config(self) -> None:
        """Test default NotificationSettings has Slack config."""
        settings = NotificationSettings()

        assert settings.slack is not None
        assert isinstance(settings.slack, SlackConfig)
        assert settings.slack.enabled is False

    def test_custom_slack_config(self) -> None:
        """Test custom SlackConfig in NotificationSettings."""
        settings = NotificationSettings(
            slack=SlackConfig(
                enabled=True,
                webhook_url="https://hooks.slack.com/services/T00/B00/XXX",
            )
        )

        assert settings.slack.enabled is True


class TestNotificationResult:
    """Tests for NotificationResult model."""

    def test_success_result(self) -> None:
        """Test successful notification result."""
        result = NotificationResult(
            success=True,
            provider="slack",
            response_status=200,
        )

        assert result.success is True
        assert result.provider == "slack"
        assert result.error is None
        assert result.response_status == 200

    def test_failure_result(self) -> None:
        """Test failed notification result."""
        result = NotificationResult(
            success=False,
            provider="slack",
            error="HTTP 500: Internal Server Error",
            response_status=500,
        )

        assert result.success is False
        assert result.error == "HTTP 500: Internal Server Error"
        assert result.response_status == 500


class TestPipelineSummary:
    """Tests for PipelineSummary model."""

    def test_default_values(self) -> None:
        """Test PipelineSummary has sensible defaults."""
        summary = PipelineSummary(date="2025-01-23 09:00 UTC")

        assert summary.topics_processed == 0
        assert summary.topics_failed == 0
        assert summary.papers_discovered == 0
        assert summary.papers_processed == 0
        assert summary.papers_with_extraction == 0
        assert summary.total_tokens_used == 0
        assert summary.total_cost_usd == 0.0
        assert summary.output_files == []
        assert summary.errors == []
        assert summary.key_learnings == []

    def test_full_summary(self) -> None:
        """Test PipelineSummary with all fields."""
        learnings = [
            KeyLearning(
                paper_title="Paper 1",
                topic="topic-1",
                summary="Summary 1",
            )
        ]

        summary = PipelineSummary(
            date="2025-01-23 09:00 UTC",
            topics_processed=3,
            topics_failed=0,
            papers_discovered=45,
            papers_processed=38,
            papers_with_extraction=32,
            total_tokens_used=12500,
            total_cost_usd=0.0234,
            output_files=["file1.md", "file2.md"],
            errors=[],
            key_learnings=learnings,
        )

        assert summary.topics_processed == 3
        assert summary.total_cost_usd == 0.0234
        assert len(summary.key_learnings) == 1

    def test_status_success(self) -> None:
        """Test status is 'success' when no failures."""
        summary = PipelineSummary(
            date="2025-01-23",
            topics_processed=3,
            topics_failed=0,
        )

        assert summary.status == "success"
        assert summary.status_emoji == ":white_check_mark:"
        assert summary.status_text == "Completed Successfully"

    def test_status_failure(self) -> None:
        """Test status is 'failure' when no successes."""
        summary = PipelineSummary(
            date="2025-01-23",
            topics_processed=0,
            topics_failed=3,
        )

        assert summary.status == "failure"
        assert summary.status_emoji == ":x:"
        assert summary.status_text == "Failed"

    def test_status_partial(self) -> None:
        """Test status is 'partial' with mixed results."""
        summary = PipelineSummary(
            date="2025-01-23",
            topics_processed=2,
            topics_failed=1,
        )

        assert summary.status == "partial"
        assert summary.status_emoji == ":warning:"
        assert summary.status_text == "Completed with Errors"

    def test_status_no_topics(self) -> None:
        """Test status when both processed and failed are 0."""
        summary = PipelineSummary(
            date="2025-01-23",
            topics_processed=0,
            topics_failed=0,
        )

        # No topics processed counts as failure
        assert summary.status == "failure"

    def test_negative_values_rejected(self) -> None:
        """Test negative values are rejected."""
        with pytest.raises(ValidationError):
            PipelineSummary(
                date="2025-01-23",
                topics_processed=-1,
            )

        with pytest.raises(ValidationError):
            PipelineSummary(
                date="2025-01-23",
                total_cost_usd=-0.5,
            )

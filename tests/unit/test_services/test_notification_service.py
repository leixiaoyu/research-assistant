"""Unit tests for NotificationService (Phase 3.7).

Tests Slack message building and notification delivery with:
- Message formatting
- Error handling
- Fail-safe behavior
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.services.notification_service import (
    NotificationService,
    SlackMessageBuilder,
)
from src.models.notification import (
    NotificationSettings,
    SlackConfig,
    PipelineSummary,
    KeyLearning,
)


class TestSlackMessageBuilder:
    """Tests for SlackMessageBuilder class."""

    @pytest.fixture
    def builder(self) -> SlackMessageBuilder:
        """Create a message builder with default settings."""
        settings = NotificationSettings()
        return SlackMessageBuilder(settings)

    @pytest.fixture
    def success_summary(self) -> PipelineSummary:
        """Create a successful pipeline summary."""
        return PipelineSummary(
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
        )

    def test_build_header_success(self, builder: SlackMessageBuilder) -> None:
        """Test header block for success status."""
        summary = PipelineSummary(
            date="2025-01-23",
            topics_processed=1,
            topics_failed=0,
        )

        header = builder._build_header(summary)

        assert header["type"] == "header"
        assert ":white_check_mark:" in header["text"]["text"]
        assert "Completed Successfully" in header["text"]["text"]

    def test_build_header_failure(self, builder: SlackMessageBuilder) -> None:
        """Test header block for failure status."""
        summary = PipelineSummary(
            date="2025-01-23",
            topics_processed=0,
            topics_failed=3,
        )

        header = builder._build_header(summary)

        assert ":x:" in header["text"]["text"]
        assert "Failed" in header["text"]["text"]

    def test_build_header_partial(self, builder: SlackMessageBuilder) -> None:
        """Test header block for partial success."""
        summary = PipelineSummary(
            date="2025-01-23",
            topics_processed=2,
            topics_failed=1,
        )

        header = builder._build_header(summary)

        assert ":warning:" in header["text"]["text"]
        assert "Completed with Errors" in header["text"]["text"]

    def test_build_stats_section(
        self, builder: SlackMessageBuilder, success_summary: PipelineSummary
    ) -> None:
        """Test statistics section formatting."""
        stats = builder._build_stats_section(success_summary)

        assert stats["type"] == "section"
        text = stats["text"]["text"]
        assert "*Date:* 2025-01-23 09:00 UTC" in text
        assert "*Topics:* 3 processed, 0 failed" in text
        assert "*Papers:* 45 discovered, 38 processed" in text
        assert "*Extractions:* 32 with LLM extraction" in text

    def test_build_cost_section(
        self, builder: SlackMessageBuilder, success_summary: PipelineSummary
    ) -> None:
        """Test cost summary section formatting."""
        cost = builder._build_cost_section(success_summary)

        assert cost["type"] == "section"
        text = cost["text"]["text"]
        assert ":moneybag:" in text
        assert "$0.0234" in text
        assert "12,500 tokens" in text

    def test_build_learnings_section(self, builder: SlackMessageBuilder) -> None:
        """Test key learnings section formatting."""
        learnings = [
            KeyLearning(
                paper_title="Paper 1",
                topic="topic-1",
                summary="This is the first learning summary.",
            ),
            KeyLearning(
                paper_title="Paper 2",
                topic="topic-1",
                summary="This is the second learning summary.",
            ),
            KeyLearning(
                paper_title="Paper 3",
                topic="topic-2",
                summary="This is a learning from another topic.",
            ),
        ]

        blocks = builder._build_learnings_section(learnings)

        # Should have header + topic sections
        assert len(blocks) >= 2
        assert ":books:" in blocks[0]["text"]["text"]
        assert "Key Learnings" in blocks[0]["text"]["text"]

    def test_build_errors_section(self, builder: SlackMessageBuilder) -> None:
        """Test errors section formatting."""
        summary = PipelineSummary(
            date="2025-01-23",
            topics_processed=1,
            topics_failed=2,
            errors=[
                {"topic": "topic-1", "error": "Connection timeout"},
                {"topic": "topic-2", "error": "Rate limit exceeded"},
            ],
        )

        errors = builder._build_errors_section(summary)

        assert errors["type"] == "section"
        text = errors["text"]["text"]
        assert ":rotating_light:" in text
        assert "topic-1" in text
        assert "Connection timeout" in text

    def test_build_errors_section_truncates_long_errors(
        self, builder: SlackMessageBuilder
    ) -> None:
        """Test long error messages are truncated."""
        summary = PipelineSummary(
            date="2025-01-23",
            errors=[
                {"topic": "topic", "error": "x" * 200},  # Long error
            ],
        )

        errors = builder._build_errors_section(summary)
        text = errors["text"]["text"]

        # Should be truncated with ...
        assert "..." in text

    def test_build_errors_section_limits_count(
        self, builder: SlackMessageBuilder
    ) -> None:
        """Test errors are limited to 5."""
        summary = PipelineSummary(
            date="2025-01-23",
            errors=[{"topic": f"topic-{i}", "error": f"Error {i}"} for i in range(10)],
        )

        errors = builder._build_errors_section(summary)
        text = errors["text"]["text"]

        # Should mention remaining errors
        assert "5 more errors" in text

    def test_build_footer(
        self, builder: SlackMessageBuilder, success_summary: PipelineSummary
    ) -> None:
        """Test footer block formatting."""
        footer = builder._build_footer(success_summary)

        assert footer["type"] == "context"
        assert "ARISP Pipeline" in footer["elements"][0]["text"]

    def test_build_pipeline_summary_full(self, builder: SlackMessageBuilder) -> None:
        """Test full pipeline summary message."""
        learnings = [
            KeyLearning(
                paper_title="Paper 1",
                topic="topic",
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
            key_learnings=learnings,
        )

        payload = builder.build_pipeline_summary(summary)

        assert "blocks" in payload
        blocks = payload["blocks"]

        # Should have header, divider, stats, cost, divider, learnings, divider, footer
        assert len(blocks) >= 5

    def test_build_pipeline_summary_with_channel_override(self) -> None:
        """Test channel override is included in payload."""
        settings = NotificationSettings(
            slack=SlackConfig(channel_override="#custom-channel")
        )
        builder = SlackMessageBuilder(settings)

        summary = PipelineSummary(date="2025-01-23", topics_processed=1)
        payload = builder.build_pipeline_summary(summary)

        assert payload.get("channel") == "#custom-channel"

    def test_build_pipeline_summary_with_mention_on_failure(self) -> None:
        """Test mention is added for failures."""
        settings = NotificationSettings(
            slack=SlackConfig(mention_on_failure="<!channel>")
        )
        builder = SlackMessageBuilder(settings)

        summary = PipelineSummary(
            date="2025-01-23",
            topics_processed=0,
            topics_failed=1,
        )
        payload = builder.build_pipeline_summary(summary)

        # Mention should be prepended
        blocks = payload["blocks"]
        mention_block = blocks[0]
        assert "<!channel>" in mention_block["text"]["text"]

    def test_build_pipeline_summary_with_errors(
        self, builder: SlackMessageBuilder
    ) -> None:
        """Test pipeline summary with errors includes error section (Lines 81-82)."""
        summary = PipelineSummary(
            date="2025-01-23 09:00 UTC",
            topics_processed=2,
            topics_failed=1,
            papers_discovered=30,
            papers_processed=25,
            errors=[
                {"topic": "failed-topic", "error": "API rate limit exceeded"},
            ],
        )

        payload = builder.build_pipeline_summary(summary)

        assert "blocks" in payload
        blocks = payload["blocks"]

        # Find the errors section block
        error_section_found = False
        for block in blocks:
            if block.get("type") == "section":
                text = block.get("text", {}).get("text", "")
                if ":rotating_light:" in text and "Errors" in text:
                    error_section_found = True
                    assert "failed-topic" in text
                    assert "API rate limit exceeded" in text
                    break

        assert error_section_found, "Errors section not found in payload"


class TestNotificationService:
    """Tests for NotificationService class."""

    @pytest.fixture
    def service(self) -> NotificationService:
        """Create a notification service with default settings."""
        settings = NotificationSettings()
        return NotificationService(settings)

    @pytest.fixture
    def enabled_service(self) -> NotificationService:
        """Create a notification service with Slack enabled."""
        settings = NotificationSettings(
            slack=SlackConfig(
                enabled=True,
                webhook_url="https://hooks.slack.com/services/T00/B00/XXX",
            )
        )
        return NotificationService(settings)

    def test_should_notify_success(self) -> None:
        """Test _should_notify for success status."""
        settings = NotificationSettings(
            slack=SlackConfig(
                notify_on_success=True,
                notify_on_failure=False,
                notify_on_partial=False,
            )
        )
        service = NotificationService(settings)

        assert service._should_notify("success") is True
        assert service._should_notify("failure") is False
        assert service._should_notify("partial") is False

    def test_should_notify_failure(self) -> None:
        """Test _should_notify for failure status."""
        settings = NotificationSettings(
            slack=SlackConfig(
                notify_on_success=False,
                notify_on_failure=True,
                notify_on_partial=False,
            )
        )
        service = NotificationService(settings)

        assert service._should_notify("success") is False
        assert service._should_notify("failure") is True
        assert service._should_notify("partial") is False

    def test_should_notify_partial(self) -> None:
        """Test _should_notify for partial status."""
        settings = NotificationSettings(
            slack=SlackConfig(
                notify_on_success=False,
                notify_on_failure=False,
                notify_on_partial=True,
            )
        )
        service = NotificationService(settings)

        assert service._should_notify("success") is False
        assert service._should_notify("failure") is False
        assert service._should_notify("partial") is True

    @pytest.mark.asyncio
    async def test_send_when_disabled(self, service: NotificationService) -> None:
        """Test notification is skipped when disabled."""
        summary = PipelineSummary(date="2025-01-23", topics_processed=1)

        result = await service.send_pipeline_summary(summary)

        assert result.success is True
        assert result.error == "Notifications disabled"

    @pytest.mark.asyncio
    async def test_send_without_webhook_url(self) -> None:
        """Test notification fails without webhook URL."""
        settings = NotificationSettings(
            slack=SlackConfig(enabled=True, webhook_url=None)
        )
        service = NotificationService(settings)
        summary = PipelineSummary(date="2025-01-23", topics_processed=1)

        result = await service.send_pipeline_summary(summary)

        assert result.success is False
        assert "not configured" in result.error

    @pytest.mark.asyncio
    async def test_send_condition_not_met(self) -> None:
        """Test notification skipped when condition not met."""
        settings = NotificationSettings(
            slack=SlackConfig(
                enabled=True,
                webhook_url="https://hooks.slack.com/test",
                notify_on_success=False,  # Disabled for success
            )
        )
        service = NotificationService(settings)
        summary = PipelineSummary(
            date="2025-01-23",
            topics_processed=1,
            topics_failed=0,  # Success status
        )

        result = await service.send_pipeline_summary(summary)

        assert result.success is True
        assert "condition not met" in result.error

    @pytest.mark.asyncio
    async def test_send_successful(self, enabled_service: NotificationService) -> None:
        """Test successful notification send."""
        summary = PipelineSummary(date="2025-01-23", topics_processed=1)

        # Mock aiohttp
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="ok")

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=None),
            )
        )
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await enabled_service.send_pipeline_summary(summary)

        assert result.success is True
        assert result.response_status == 200

    @pytest.mark.asyncio
    async def test_send_http_error(self, enabled_service: NotificationService) -> None:
        """Test handling of HTTP error response."""
        summary = PipelineSummary(date="2025-01-23", topics_processed=1)

        # Mock aiohttp with error response
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=None),
            )
        )
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await enabled_service.send_pipeline_summary(summary)

        assert result.success is False
        assert result.response_status == 500
        assert "500" in result.error

    @pytest.mark.asyncio
    async def test_send_client_error(
        self, enabled_service: NotificationService
    ) -> None:
        """Test handling of client connection error."""
        import aiohttp

        summary = PipelineSummary(date="2025-01-23", topics_processed=1)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = MagicMock(
                side_effect=aiohttp.ClientError("Connection failed")
            )
            mock_session_class.return_value = mock_session

            result = await enabled_service.send_pipeline_summary(summary)

        assert result.success is False
        assert "HTTP error" in result.error

    @pytest.mark.asyncio
    async def test_send_unexpected_error(
        self, enabled_service: NotificationService
    ) -> None:
        """Test handling of unexpected error (fail-safe)."""
        summary = PipelineSummary(date="2025-01-23", topics_processed=1)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session_class.side_effect = RuntimeError("Unexpected")

            result = await enabled_service.send_pipeline_summary(summary)

        # Should not raise, should return failure result
        assert result.success is False
        assert "Unexpected error" in result.error


class TestCreateSummaryFromResult:
    """Tests for create_summary_from_result static method."""

    def test_basic_conversion(self) -> None:
        """Test basic result dict conversion."""
        result = {
            "topics_processed": 3,
            "topics_failed": 0,
            "papers_discovered": 45,
            "papers_processed": 38,
            "papers_with_extraction": 32,
            "total_tokens_used": 12500,
            "total_cost_usd": 0.0234,
            "output_files": ["file1.md", "file2.md"],
            "errors": [],
        }

        summary = NotificationService.create_summary_from_result(result)

        assert summary.topics_processed == 3
        assert summary.papers_discovered == 45
        assert summary.total_cost_usd == 0.0234
        assert len(summary.output_files) == 2

    def test_with_key_learnings(self) -> None:
        """Test conversion with key learnings."""
        result = {"topics_processed": 1}
        learnings = [
            KeyLearning(
                paper_title="Paper",
                topic="topic",
                summary="Summary",
            )
        ]

        summary = NotificationService.create_summary_from_result(result, learnings)

        assert len(summary.key_learnings) == 1
        assert summary.key_learnings[0].paper_title == "Paper"

    def test_missing_fields_use_defaults(self) -> None:
        """Test missing fields use default values."""
        result = {}

        summary = NotificationService.create_summary_from_result(result)

        assert summary.topics_processed == 0
        assert summary.papers_discovered == 0
        assert summary.total_cost_usd == 0.0
        assert summary.output_files == []
        assert summary.errors == []

    def test_date_is_set(self) -> None:
        """Test date is set to current time."""
        result = {}

        summary = NotificationService.create_summary_from_result(result)

        assert summary.date is not None
        assert "UTC" in summary.date

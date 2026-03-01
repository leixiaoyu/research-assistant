"""Notification service for sending pipeline notifications.

Provides async notification delivery via Slack webhooks with:
- Slack Block Kit message formatting
- Fail-safe error handling (never breaks pipeline)
- Key learnings integration
- Cost summary reporting

Usage:
    from src.services.notification_service import NotificationService
    from src.models.notification import NotificationSettings, PipelineSummary

    service = NotificationService(NotificationSettings())
    result = await service.send_pipeline_summary(summary)
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
import structlog

from src.models.notification import (
    NotificationSettings,
    NotificationResult,
    PipelineSummary,
    KeyLearning,
    DeduplicationResult,
)

logger = structlog.get_logger()


class SlackMessageBuilder:
    """Builds Slack Block Kit messages for pipeline notifications.

    Creates formatted Slack messages with:
    - Status header with emoji
    - Pipeline statistics
    - Cost summary
    - Key learnings by topic
    - Error details (on failure)
    """

    def __init__(self, config: "NotificationSettings") -> None:
        """Initialize message builder.

        Args:
            config: Notification settings.
        """
        self.config = config

    def build_pipeline_summary(self, summary: PipelineSummary) -> Dict[str, Any]:
        """Build Slack message payload for pipeline summary.

        Args:
            summary: Pipeline execution summary.

        Returns:
            Slack message payload with blocks.
        """
        blocks: List[Dict[str, Any]] = []

        # Header block
        blocks.append(self._build_header(summary))

        # Divider
        blocks.append({"type": "divider"})

        # Statistics section
        blocks.append(self._build_stats_section(summary))

        # Cost summary (if enabled)
        if self.config.slack.include_cost_summary and summary.total_cost_usd > 0:
            blocks.append(self._build_cost_section(summary))

        # New papers section (if there are new papers)
        if summary.new_papers_count > 0 and summary.new_paper_titles:
            blocks.append({"type": "divider"})
            blocks.extend(self._build_new_papers_section(summary))

        # Retry papers section (if enabled and there are retry papers)
        if self.config.slack.show_retry_papers and summary.retry_papers_count > 0:
            blocks.append(self._build_retry_papers_section(summary))

        # Key learnings (if enabled and available)
        if self.config.slack.include_key_learnings and summary.key_learnings:
            blocks.append({"type": "divider"})
            blocks.extend(self._build_learnings_section(summary.key_learnings))

        # Errors section (if any)
        if summary.errors:
            blocks.append({"type": "divider"})
            blocks.append(self._build_errors_section(summary))

        # Footer
        blocks.append({"type": "divider"})
        blocks.append(self._build_footer(summary))

        # Build final payload
        payload: Dict[str, Any] = {"blocks": blocks}

        # Add channel override if configured
        if self.config.slack.channel_override:
            payload["channel"] = self.config.slack.channel_override

        # Add mention for failures
        if summary.status == "failure" and self.config.slack.mention_on_failure:
            # Prepend mention to first text block
            mention_block = {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": self.config.slack.mention_on_failure,
                },
            }
            blocks.insert(0, mention_block)

        return payload

    def _build_header(self, summary: PipelineSummary) -> Dict[str, Any]:
        """Build header block with status."""
        emoji_map = {
            "success": ":white_check_mark:",
            "failure": ":x:",
            "partial": ":warning:",
        }
        emoji = emoji_map.get(summary.status, ":question:")

        return {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Daily Research Pipeline {summary.status_text}",
                "emoji": True,
            },
        }

    def _build_stats_section(self, summary: PipelineSummary) -> Dict[str, Any]:
        """Build statistics section."""
        stats_text = (
            f"*Date:* {summary.date}\n"
            f"*Topics:* {summary.topics_processed} processed, "
            f"{summary.topics_failed} failed\n"
            f"*Papers:* {summary.papers_discovered} discovered, "
            f"{summary.papers_processed} processed\n"
            f"*Extractions:* {summary.papers_with_extraction} with LLM extraction"
        )

        # Add deduplication stats if available
        if summary.total_papers_checked > 0:
            dedup_parts = []

            # Always show new papers count
            dedup_parts.append(f"{summary.new_papers_count} new")

            # Show retry count if enabled and > 0
            if self.config.slack.show_retry_papers and summary.retry_papers_count > 0:
                dedup_parts.append(f"{summary.retry_papers_count} retry")

            # Show duplicate count if enabled
            if self.config.slack.show_duplicates_count:
                dedup_parts.append(f"{summary.duplicate_papers_count} duplicate")

            dedup_text = ", ".join(dedup_parts)

            # Add total checked if enabled
            if self.config.slack.include_total_checked:
                total = summary.total_papers_checked
                stats_text += f"\n*Dedup:* {dedup_text} (of {total} checked)"
            else:
                stats_text += f"\n*Dedup:* {dedup_text}"

        return {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": stats_text,
            },
        }

    def _build_cost_section(self, summary: PipelineSummary) -> Dict[str, Any]:
        """Build cost summary section."""
        cost_text = (
            f":moneybag: *LLM Cost:* ${summary.total_cost_usd:.4f} "
            f"({summary.total_tokens_used:,} tokens)"
        )

        return {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": cost_text,
            },
        }

    def _build_new_papers_section(
        self, summary: PipelineSummary
    ) -> List[Dict[str, Any]]:
        """Build new papers section listing paper titles.

        Args:
            summary: Pipeline summary with new paper titles.

        Returns:
            List of Slack blocks for the new papers section.
        """
        blocks: List[Dict[str, Any]] = []

        if not summary.new_paper_titles:
            return blocks

        # Section header
        header_text = f":sparkles: *New Papers* ({summary.new_papers_count})"
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": header_text,
                },
            }
        )

        # List paper titles (respect max limit from config)
        max_titles = self.config.slack.max_new_papers_listed
        titles_to_show = summary.new_paper_titles[:max_titles]

        papers_text = ""
        for i, title in enumerate(titles_to_show, 1):
            papers_text += f"{i}. _{title}_\n"

        # Show remaining count if truncated
        remaining = summary.new_papers_count - len(titles_to_show)
        if remaining > 0:
            papers_text += f"_...and {remaining} more new papers_"

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": papers_text.strip(),
                },
            }
        )

        return blocks

    def _build_retry_papers_section(self, summary: PipelineSummary) -> Dict[str, Any]:
        """Build retry papers section.

        Args:
            summary: Pipeline summary with retry count.

        Returns:
            Slack block for the retry papers section.
        """
        retry_text = (
            f":arrows_counterclockwise: *Retry Papers:* "
            f"{summary.retry_papers_count} papers being retried from previous failures"
        )

        return {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": retry_text,
            },
        }

    def _build_learnings_section(
        self, learnings: List[KeyLearning]
    ) -> List[Dict[str, Any]]:
        """Build key learnings section."""
        blocks: List[Dict[str, Any]] = []

        # Section header
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":books: *Key Learnings*",
                },
            }
        )

        # Group learnings by topic
        by_topic: Dict[str, List[KeyLearning]] = {}
        for learning in learnings:
            if learning.topic not in by_topic:
                by_topic[learning.topic] = []
            by_topic[learning.topic].append(learning)

        # Build blocks for each topic
        for topic, topic_learnings in by_topic.items():
            topic_text = f"*{topic}*\n"
            for learning in topic_learnings:
                # Format: › "Summary text..."
                topic_text += f"> _{learning.summary}_\n"

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": topic_text.strip(),
                    },
                }
            )

        return blocks

    def _build_errors_section(self, summary: PipelineSummary) -> Dict[str, Any]:
        """Build errors section."""
        error_text = ":rotating_light: *Errors*\n"

        for error in summary.errors[:5]:  # Limit to 5 errors
            topic = error.get("topic", "unknown")
            msg = error.get("error", "Unknown error")
            # Truncate long error messages
            if len(msg) > 100:
                msg = msg[:97] + "..."
            error_text += f"• *{topic}:* {msg}\n"

        if len(summary.errors) > 5:
            error_text += f"_...and {len(summary.errors) - 5} more errors_"

        return {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": error_text.strip(),
            },
        }

    def _build_footer(self, summary: PipelineSummary) -> Dict[str, Any]:
        """Build footer block."""
        return {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"ARISP Pipeline | {summary.date.split()[0]}",
                },
            ],
        }


class NotificationService:
    """Service for sending pipeline notifications.

    Sends notifications via configured providers (currently Slack).
    All errors are caught and logged - notifications never break the pipeline.

    Attributes:
        settings: Notification configuration.
    """

    def __init__(self, settings: NotificationSettings) -> None:
        """Initialize notification service.

        Args:
            settings: Notification settings.
        """
        self.settings = settings
        self._message_builder = SlackMessageBuilder(settings)

    async def send_pipeline_summary(
        self,
        summary: PipelineSummary,
    ) -> NotificationResult:
        """Send pipeline summary notification.

        Sends notification via all enabled providers. Errors are caught
        and logged but never raised - notifications are fail-safe.

        Args:
            summary: Pipeline execution summary.

        Returns:
            NotificationResult with success status.
        """
        # Check if Slack is enabled
        if not self.settings.slack.enabled:
            logger.debug("slack_notifications_disabled")
            return NotificationResult(
                success=True,
                provider="slack",
                error="Notifications disabled",
            )

        # Check webhook URL
        if not self.settings.slack.webhook_url:
            logger.warning("slack_webhook_url_not_configured")
            return NotificationResult(
                success=False,
                provider="slack",
                error="Webhook URL not configured",
            )

        # Check notification conditions
        should_notify = self._should_notify(summary.status)
        if not should_notify:
            logger.debug(
                "notification_skipped",
                status=summary.status,
                reason="notification_condition_not_met",
            )
            return NotificationResult(
                success=True,
                provider="slack",
                error="Notification condition not met",
            )

        # Send notification
        return await self._send_slack_notification(summary)

    def _should_notify(self, status: str) -> bool:
        """Check if notification should be sent based on status.

        Args:
            status: Pipeline status (success, failure, partial).

        Returns:
            True if notification should be sent.
        """
        config = self.settings.slack

        if status == "success" and config.notify_on_success:
            return True
        if status == "failure" and config.notify_on_failure:
            return True
        if status == "partial" and config.notify_on_partial:
            return True

        return False

    async def _send_slack_notification(
        self,
        summary: PipelineSummary,
    ) -> NotificationResult:
        """Send Slack webhook notification.

        Args:
            summary: Pipeline summary.

        Returns:
            NotificationResult with response details.
        """
        import aiohttp

        try:
            # Build message payload
            payload = self._message_builder.build_pipeline_summary(summary)

            # Get webhook URL as string
            webhook_url = str(self.settings.slack.webhook_url)

            logger.info(
                "sending_slack_notification",
                status=summary.status,
                topics=summary.topics_processed,
            )

            # Send HTTP request
            timeout = aiohttp.ClientTimeout(total=self.settings.slack.timeout_seconds)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    response_status = response.status

                    if response_status == 200:
                        logger.info(
                            "slack_notification_sent",
                            status=summary.status,
                        )
                        return NotificationResult(
                            success=True,
                            provider="slack",
                            response_status=response_status,
                        )
                    else:
                        response_text = await response.text()
                        logger.warning(
                            "slack_notification_failed",
                            status_code=response_status,
                            response=response_text[:200],
                        )
                        return NotificationResult(
                            success=False,
                            provider="slack",
                            error=f"HTTP {response_status}: {response_text[:100]}",
                            response_status=response_status,
                        )

        except aiohttp.ClientError as e:
            logger.error(
                "slack_notification_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            return NotificationResult(
                success=False,
                provider="slack",
                error=f"HTTP error: {str(e)}",
            )
        except Exception as e:
            # Catch-all: notifications should never break the pipeline
            logger.exception(
                "slack_notification_unexpected_error",
                error=str(e),
            )
            return NotificationResult(
                success=False,
                provider="slack",
                error=f"Unexpected error: {str(e)}",
            )

    @staticmethod
    def create_summary_from_result(
        result: Dict[str, Any],
        key_learnings: Optional[List[KeyLearning]] = None,
        dedup_result: Optional[DeduplicationResult] = None,
    ) -> PipelineSummary:
        """Create PipelineSummary from pipeline result dict.

        Convenience method to convert pipeline result dictionary
        to a PipelineSummary object.

        Args:
            result: Pipeline result dictionary (from PipelineResult.to_dict()).
            key_learnings: Optional list of extracted key learnings.
            dedup_result: Optional deduplication result for paper categorization.

        Returns:
            PipelineSummary object.
        """
        # Build base summary
        summary_data = {
            "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "topics_processed": result.get("topics_processed", 0),
            "topics_failed": result.get("topics_failed", 0),
            "papers_discovered": result.get("papers_discovered", 0),
            "papers_processed": result.get("papers_processed", 0),
            "papers_with_extraction": result.get("papers_with_extraction", 0),
            "total_tokens_used": result.get("total_tokens_used", 0),
            "total_cost_usd": result.get("total_cost_usd", 0.0),
            "output_files": result.get("output_files", []),
            "errors": result.get("errors", []),
            "key_learnings": key_learnings or [],
        }

        # Add deduplication data if provided
        if dedup_result is not None:
            summary_data["new_papers_count"] = dedup_result.new_count
            summary_data["retry_papers_count"] = dedup_result.retry_count
            summary_data["duplicate_papers_count"] = dedup_result.duplicate_count
            summary_data["total_papers_checked"] = dedup_result.total_checked
            summary_data["new_paper_titles"] = dedup_result.get_new_paper_titles()

        return PipelineSummary(**summary_data)

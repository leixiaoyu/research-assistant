"""Notification configuration models for Phase 3.7.

Provides Pydantic models for:
- SlackConfig: Slack webhook and notification settings
- KeyLearning: Extracted learning from a paper
- NotificationSettings: Container for all notification providers
- DeduplicationResult: Paper categorization for dedup-aware notifications

Usage:
    from src.models.notification import NotificationSettings, SlackConfig

    settings = NotificationSettings(
        slack=SlackConfig(
            enabled=True,
            webhook_url="https://hooks.slack.com/services/...",
        )
    )
"""

from typing import Optional, List
from pydantic import BaseModel, Field, HttpUrl, field_validator


class SlackConfig(BaseModel):
    """Configuration for Slack notifications.

    Attributes:
        enabled: Whether Slack notifications are enabled.
        webhook_url: Slack webhook URL (from environment variable).
        channel_override: Optional channel to post to (overrides webhook default).
        notify_on_success: Send notification on successful pipeline run.
        notify_on_failure: Send notification on failed pipeline run.
        notify_on_partial: Send notification on partial success (some topics failed).
        include_cost_summary: Include LLM cost information in notification.
        include_key_learnings: Include key learnings from papers.
        max_learnings_per_topic: Maximum number of learnings to include per topic.
        mention_on_failure: Slack mention string for failures (e.g., "<!channel>").
        timeout_seconds: HTTP request timeout for webhook calls.
    """

    enabled: bool = Field(default=False, description="Enable Slack notifications")
    webhook_url: Optional[HttpUrl] = Field(
        default=None, description="Slack webhook URL from ${SLACK_WEBHOOK_URL}"
    )
    channel_override: Optional[str] = Field(
        default=None,
        max_length=80,
        description="Override default webhook channel",
    )
    notify_on_success: bool = Field(
        default=True, description="Notify on successful runs"
    )
    notify_on_failure: bool = Field(default=True, description="Notify on failed runs")
    notify_on_partial: bool = Field(
        default=True, description="Notify on partial success"
    )
    include_cost_summary: bool = Field(
        default=True, description="Include LLM cost in notification"
    )
    include_key_learnings: bool = Field(
        default=True, description="Include key learnings from papers"
    )
    max_learnings_per_topic: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Max learnings per topic",
    )
    mention_on_failure: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Slack mention on failure (e.g., <!channel>)",
    )
    timeout_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="HTTP timeout for webhook requests",
    )

    # Deduplication display options (Phase 3.8)
    show_duplicates_count: bool = Field(
        default=True,
        description="Show count of duplicate papers in notification",
    )
    show_retry_papers: bool = Field(
        default=True,
        description="Show papers being retried (previously failed)",
    )
    max_new_papers_listed: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum new paper titles to list in notification",
    )
    include_total_checked: bool = Field(
        default=True,
        description="Include total papers checked count in notification",
    )

    @field_validator("webhook_url", mode="before")
    @classmethod
    def validate_webhook_url(cls, v: Optional[str]) -> Optional[str]:
        """Validate webhook URL format.

        Allows None or empty string (disabled state).
        """
        if v is None or v == "" or v == "${SLACK_WEBHOOK_URL}":
            return None
        return v

    @field_validator("channel_override")
    @classmethod
    def validate_channel(cls, v: Optional[str]) -> Optional[str]:
        """Validate channel format (must start with # or be None)."""
        if v is None or v == "":
            return None
        if not v.startswith("#") and not v.startswith("@"):
            raise ValueError("Channel must start with '#' or '@'")
        return v

    @field_validator("mention_on_failure")
    @classmethod
    def validate_mention(cls, v: Optional[str]) -> Optional[str]:
        """Validate Slack mention format."""
        if v is None or v == "":
            return None
        # Allow common Slack mention formats
        valid_prefixes = ("<!channel>", "<!here>", "<@", "<!subteam")
        if not any(v.startswith(prefix) for prefix in valid_prefixes):
            raise ValueError(
                "Mention must be a valid Slack mention "
                "(e.g., <!channel>, <!here>, <@USER_ID>)"
            )
        return v


class KeyLearning(BaseModel):
    """Extracted learning from a research paper.

    Represents a key insight or summary extracted from a paper's
    engineering summary for inclusion in Slack notifications.

    Attributes:
        paper_title: Title of the source paper.
        topic: Topic slug the paper belongs to.
        summary: Truncated engineering summary (Slack-friendly length).
    """

    paper_title: str = Field(..., min_length=1, max_length=500)
    topic: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=500)

    @field_validator("summary", mode="before")
    @classmethod
    def truncate_summary(cls, v: str) -> str:
        """Ensure summary is truncated to Slack-friendly length."""
        if not isinstance(v, str):
            return v
        max_len = 500
        if len(v) > max_len:
            return v[: max_len - 3] + "..."
        return v


class NotificationSettings(BaseModel):
    """Container for all notification provider settings.

    Currently supports Slack notifications. Additional providers
    (email, Discord, etc.) can be added in future phases.

    Attributes:
        slack: Slack notification configuration.
    """

    slack: SlackConfig = Field(
        default_factory=SlackConfig,
        description="Slack notification settings",
    )


class NotificationResult(BaseModel):
    """Result of a notification attempt.

    Attributes:
        success: Whether the notification was sent successfully.
        provider: Provider name (e.g., "slack").
        error: Error message if failed.
        response_status: HTTP response status code.
    """

    success: bool = Field(..., description="Whether notification succeeded")
    provider: str = Field(..., description="Notification provider name")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    response_status: Optional[int] = Field(
        default=None, description="HTTP response status"
    )


class DeduplicationResult(BaseModel):
    """Result of categorizing papers for notification deduplication.

    Categorizes discovered papers into three groups based on registry status:
    - new_papers: Papers not found in registry (truly new discoveries)
    - retry_papers: Papers with FAILED/SKIPPED status (retry candidates)
    - duplicate_papers: Papers with PROCESSED/MAPPED status (already notified)

    Attributes:
        new_papers: List of paper metadata dicts for new papers.
        retry_papers: List of paper metadata dicts for retry candidates.
        duplicate_papers: List of paper metadata dicts for duplicates.
    """

    new_papers: List[dict] = Field(
        default_factory=list,
        description="Papers not in registry (truly new)",
    )
    retry_papers: List[dict] = Field(
        default_factory=list,
        description="Papers with FAILED/SKIPPED status (retry candidates)",
    )
    duplicate_papers: List[dict] = Field(
        default_factory=list,
        description="Papers with PROCESSED/MAPPED status (already notified)",
    )

    @property
    def new_count(self) -> int:
        """Count of new papers."""
        return len(self.new_papers)

    @property
    def retry_count(self) -> int:
        """Count of retry papers."""
        return len(self.retry_papers)

    @property
    def duplicate_count(self) -> int:
        """Count of duplicate papers."""
        return len(self.duplicate_papers)

    @property
    def total_checked(self) -> int:
        """Total papers checked for deduplication."""
        return (
            len(self.new_papers) + len(self.retry_papers) + len(self.duplicate_papers)
        )

    def get_new_paper_titles(self, max_titles: int = 5) -> List[str]:
        """Get titles of new papers for display.

        Args:
            max_titles: Maximum number of titles to return.

        Returns:
            List of paper titles (truncated to max_titles).
        """
        titles = []
        for paper in self.new_papers[:max_titles]:
            title = paper.get("title", "Untitled")
            if len(title) > 80:
                title = title[:77] + "..."
            titles.append(title)
        return titles


class PipelineSummary(BaseModel):
    """Summary of pipeline execution for notifications.

    Provides a structured view of pipeline results suitable
    for building notification messages.

    Attributes:
        date: Execution date string.
        topics_processed: Number of successfully processed topics.
        topics_failed: Number of failed topics.
        papers_discovered: Total papers discovered.
        papers_processed: Papers successfully processed.
        papers_with_extraction: Papers with LLM extraction.
        total_tokens_used: Total LLM tokens used.
        total_cost_usd: Total LLM cost in USD.
        output_files: List of generated output file paths.
        errors: List of error dictionaries.
        key_learnings: Extracted key learnings for notification.
    """

    date: str = Field(..., description="Execution date (YYYY-MM-DD HH:MM UTC)")
    topics_processed: int = Field(default=0, ge=0)
    topics_failed: int = Field(default=0, ge=0)
    papers_discovered: int = Field(default=0, ge=0)
    papers_processed: int = Field(default=0, ge=0)
    papers_with_extraction: int = Field(default=0, ge=0)
    total_tokens_used: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    output_files: List[str] = Field(default_factory=list)
    errors: List[dict] = Field(default_factory=list)
    key_learnings: List[KeyLearning] = Field(default_factory=list)

    # Deduplication-aware fields (Phase 3.8)
    new_papers_count: int = Field(
        default=0,
        ge=0,
        description="Count of truly new papers (not in registry)",
    )
    retry_papers_count: int = Field(
        default=0,
        ge=0,
        description="Count of papers being retried (previously failed)",
    )
    duplicate_papers_count: int = Field(
        default=0,
        ge=0,
        description="Count of duplicate papers (already processed)",
    )
    new_paper_titles: List[str] = Field(
        default_factory=list,
        description="Titles of new papers for display (limited)",
    )
    total_papers_checked: int = Field(
        default=0,
        ge=0,
        description="Total papers checked for deduplication",
    )

    @property
    def status(self) -> str:
        """Determine pipeline status.

        Returns:
            "success", "failure", or "partial"
        """
        if self.topics_failed == 0 and self.topics_processed > 0:
            return "success"
        elif self.topics_processed == 0:
            return "failure"
        else:
            return "partial"

    @property
    def status_emoji(self) -> str:
        """Get emoji for status."""
        status_map = {
            "success": ":white_check_mark:",
            "failure": ":x:",
            "partial": ":warning:",
        }
        return status_map.get(self.status, ":question:")

    @property
    def status_text(self) -> str:
        """Get human-readable status text."""
        status_map = {
            "success": "Completed Successfully",
            "failure": "Failed",
            "partial": "Completed with Errors",
        }
        return status_map.get(self.status, "Unknown")

"""Cross-Topic Synthesis data models for Phase 3.7.

This module defines the data structures for:
- Synthesis questions with configurable prompts
- Synthesis results with cost tracking
- Cross-topic synthesis reports
- Configuration for synthesis operations
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SynthesisQuestion(BaseModel):
    """A user-defined cross-topic synthesis question.

    Represents a research question that spans multiple topics,
    with configurable filtering and prompt templates.
    """

    model_config = ConfigDict(strict=True)

    id: str = Field(
        ...,
        description="Unique identifier (slug) for the question",
        min_length=1,
        max_length=100,
    )
    name: str = Field(
        ...,
        description="Human-readable display name",
        min_length=1,
        max_length=200,
    )
    prompt: str = Field(
        ...,
        description="Complete LLM prompt template with template variables",
        min_length=10,
    )
    topic_filters: List[str] = Field(
        default_factory=list,
        description="Topics to include (empty = all topics)",
    )
    topic_exclude: List[str] = Field(
        default_factory=list,
        description="Topics to exclude from synthesis",
    )
    max_papers: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum papers to include in synthesis",
    )
    min_quality_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Minimum quality score threshold",
    )
    priority: int = Field(
        default=1,
        ge=1,
        description="Processing order (lower = higher priority)",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this question is active",
    )

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate ID is a valid slug format."""
        import re

        if not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$", v):
            raise ValueError(
                "ID must be lowercase alphanumeric with hyphens, "
                "not starting/ending with hyphen"
            )
        return v

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        """Validate prompt doesn't contain dangerous patterns."""
        # Block script injection attempts
        import re

        if re.search(r"<script", v, re.IGNORECASE):
            raise ValueError("Script tags are not allowed in prompts")
        return v


class SynthesisResult(BaseModel):
    """Result of synthesizing one question.

    Contains the LLM-generated synthesis along with metadata
    about papers used, cost, and confidence.
    """

    model_config = ConfigDict(strict=True)

    question_id: str = Field(..., description="ID of the question answered")
    question_name: str = Field(..., description="Display name of the question")
    synthesis_text: str = Field(..., description="LLM-generated synthesis content")
    papers_used: List[str] = Field(
        default_factory=list,
        description="Paper IDs included in synthesis",
    )
    topics_covered: List[str] = Field(
        default_factory=list,
        description="Topics represented in synthesis",
    )
    tokens_used: int = Field(
        default=0,
        ge=0,
        description="Total tokens consumed",
    )
    cost_usd: float = Field(
        default=0.0,
        ge=0.0,
        description="Cost in USD for this synthesis",
    )
    synthesized_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When synthesis was completed",
    )
    model_used: str = Field(
        default="",
        description="LLM model used for synthesis",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score for synthesis quality",
    )


class CrossTopicSynthesisReport(BaseModel):
    """Complete synthesis report for all questions.

    Aggregates results from multiple synthesis questions
    with overall statistics and metadata.
    """

    model_config = ConfigDict(strict=True)

    report_id: str = Field(
        ...,
        description="Unique identifier for this report",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When report was created",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When report was last updated",
    )
    total_papers_in_registry: int = Field(
        default=0,
        ge=0,
        description="Total papers available in registry",
    )
    results: List[SynthesisResult] = Field(
        default_factory=list,
        description="Synthesis results for each question",
    )
    total_tokens_used: int = Field(
        default=0,
        ge=0,
        description="Total tokens across all syntheses",
    )
    total_cost_usd: float = Field(
        default=0.0,
        ge=0.0,
        description="Total cost in USD",
    )
    incremental: bool = Field(
        default=False,
        description="Whether this was an incremental update",
    )
    new_papers_since_last: int = Field(
        default=0,
        ge=0,
        description="New papers added since last synthesis",
    )

    @property
    def questions_answered(self) -> int:
        """Number of questions successfully synthesized."""
        return len(self.results)


class SynthesisConfig(BaseModel):
    """Configuration for cross-topic synthesis.

    Defines budget limits, output paths, and synthesis questions.
    """

    model_config = ConfigDict(strict=True)

    questions: List[SynthesisQuestion] = Field(
        default_factory=list,
        description="List of synthesis questions to answer",
    )
    budget_per_synthesis_usd: float = Field(
        default=15.0,
        ge=0.0,
        le=100.0,
        description="Maximum USD to spend per synthesis run",
    )
    max_tokens_per_question: int = Field(
        default=100000,
        ge=1000,
        le=1000000,
        description="Maximum tokens per question",
    )
    output_path: str = Field(
        default="output/Global_Synthesis.md",
        description="Path to output file",
    )
    cache_synthesis_results: bool = Field(
        default=True,
        description="Whether to cache synthesis results",
    )
    incremental_mode: bool = Field(
        default=True,
        description="Skip synthesis if no new papers since last run",
    )

    @field_validator("output_path")
    @classmethod
    def validate_output_path(cls, v: str) -> str:
        """Validate output path is safe."""
        # Block path traversal
        if ".." in v:
            raise ValueError("Path traversal (..) not allowed in output_path")
        return v


class PaperSummary(BaseModel):
    """Summary of a paper for inclusion in synthesis prompts.

    Provides a condensed view of paper content for LLM context.
    """

    model_config = ConfigDict(strict=True)

    paper_id: str = Field(..., description="Canonical paper ID")
    title: str = Field(..., description="Paper title")
    authors: List[str] = Field(default_factory=list, description="Author names")
    abstract: Optional[str] = Field(default=None, description="Paper abstract")
    publication_date: Optional[str] = Field(
        default=None, description="Publication date"
    )
    quality_score: float = Field(default=0.0, ge=0.0, le=100.0)
    topics: List[str] = Field(default_factory=list, description="Topic affiliations")
    extraction_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Key extraction results",
    )

    def to_prompt_format(self) -> str:
        """Format paper summary for inclusion in LLM prompt.

        Returns:
            Formatted string suitable for prompt context.
        """
        lines = []
        lines.append(f"### {self.title}")
        lines.append(f"**Paper ID:** {self.paper_id}")

        if self.authors:
            lines.append(f"**Authors:** {', '.join(self.authors[:5])}")
            if len(self.authors) > 5:
                lines.append(f"  ...and {len(self.authors) - 5} more")

        if self.publication_date:
            lines.append(f"**Published:** {self.publication_date}")

        lines.append(f"**Quality Score:** {self.quality_score:.0f}/100")
        lines.append(f"**Topics:** {', '.join(self.topics)}")

        if self.abstract:
            # Truncate long abstracts
            abstract = self.abstract
            if len(abstract) > 500:
                abstract = abstract[:497] + "..."
            lines.append(f"\n**Abstract:** {abstract}")

        if self.extraction_summary:
            lines.append("\n**Key Findings:**")
            for key, value in self.extraction_summary.items():
                if value and isinstance(value, str):
                    # Truncate long values
                    display_value = value[:200] + "..." if len(value) > 200 else value
                    lines.append(f"- **{key}:** {display_value}")

        lines.append("")
        return "\n".join(lines)


class SynthesisState(BaseModel):
    """Persistent state for incremental synthesis.

    Tracks when synthesis was last run and registry state
    for determining if new synthesis is needed.
    """

    model_config = ConfigDict(strict=True)

    last_synthesis_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of last synthesis run",
    )
    last_registry_hash: Optional[str] = Field(
        default=None,
        description="Hash of registry state at last synthesis",
    )
    last_report_id: Optional[str] = Field(
        default=None,
        description="ID of last generated report",
    )
    questions_processed: List[str] = Field(
        default_factory=list,
        description="Question IDs processed in last run",
    )

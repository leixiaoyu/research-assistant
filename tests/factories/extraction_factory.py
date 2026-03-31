"""Factory for creating extraction-related model instances.

Provides sensible defaults for ExtractionTarget and ExtractionResult.
"""

from typing import Any, Literal

from src.models.extraction import ExtractionTarget, ExtractionResult


class ExtractionTargetFactory:
    """Factory for creating ExtractionTarget instances."""

    @classmethod
    def create(
        cls,
        name: str = "system_prompts",
        description: str | None = None,
        required: bool = True,
        output_format: Literal["text", "code", "json", "list"] = "list",
        **kwargs: Any,
    ) -> ExtractionTarget:
        """Create an ExtractionTarget with defaults.

        Args:
            name: Target name.
            description: Target description.
            required: Whether extraction is required.
            output_format: Expected output format.
            **kwargs: Additional fields.

        Returns:
            ExtractionTarget instance.
        """
        return ExtractionTarget(
            name=name,
            description=description or f"Extract {name} from the paper",
            required=required,
            output_format=output_format,
            **kwargs,
        )

    @classmethod
    def system_prompts(cls, **kwargs: Any) -> ExtractionTarget:
        """Create a system prompts extraction target."""
        return cls.create(
            name="system_prompts",
            description="Extract system prompts or instructions",
            output_format="list",
            **kwargs,
        )

    @classmethod
    def code_snippets(cls, **kwargs: Any) -> ExtractionTarget:
        """Create a code snippets extraction target."""
        return cls.create(
            name="code_snippets",
            description="Extract code examples and implementations",
            output_format="list",
            **kwargs,
        )

    @classmethod
    def methodology(cls, **kwargs: Any) -> ExtractionTarget:
        """Create a methodology extraction target."""
        return cls.create(
            name="methodology",
            description="Extract research methodology and approach",
            output_format="text",
            **kwargs,
        )

    @classmethod
    def optional(cls, name: str = "supplementary", **kwargs: Any) -> ExtractionTarget:
        """Create an optional extraction target."""
        return cls.create(
            name=name,
            required=False,
            **kwargs,
        )


class ExtractionResultFactory:
    """Factory for creating ExtractionResult instances."""

    @classmethod
    def create(
        cls,
        target_name: str = "system_prompts",
        success: bool = True,
        content: list[str] | str | None = None,
        confidence: float = 0.9,
        error: str | None = None,
        **kwargs: Any,
    ) -> ExtractionResult:
        """Create an ExtractionResult with defaults.

        Args:
            target_name: Name of the extraction target.
            success: Whether extraction succeeded.
            content: Extracted content.
            confidence: Confidence score (0-1).
            error: Error message if failed.
            **kwargs: Additional fields.

        Returns:
            ExtractionResult instance.
        """
        if success and content is None:
            content = ["Extracted content 1", "Extracted content 2"]

        return ExtractionResult(
            target_name=target_name,
            success=success,
            content=content,
            confidence=confidence if success else 0.0,
            error=error,
            **kwargs,
        )

    @classmethod
    def success(
        cls,
        target_name: str = "system_prompts",
        content: list[str] | str | None = None,
        confidence: float = 0.95,
        **kwargs: Any,
    ) -> ExtractionResult:
        """Create a successful extraction result.

        Args:
            target_name: Name of the extraction target.
            content: Extracted content.
            confidence: Confidence score.
            **kwargs: Additional fields.

        Returns:
            Successful ExtractionResult.
        """
        return cls.create(
            target_name=target_name,
            success=True,
            content=content,
            confidence=confidence,
            **kwargs,
        )

    @classmethod
    def failure(
        cls,
        target_name: str = "system_prompts",
        error: str = "Extraction failed",
        **kwargs: Any,
    ) -> ExtractionResult:
        """Create a failed extraction result.

        Args:
            target_name: Name of the extraction target.
            error: Error message.
            **kwargs: Additional fields.

        Returns:
            Failed ExtractionResult.
        """
        return cls.create(
            target_name=target_name,
            success=False,
            content=None,
            confidence=0.0,
            error=error,
            **kwargs,
        )

    @classmethod
    def high_confidence(cls, **kwargs: Any) -> ExtractionResult:
        """Create a high-confidence result (>0.95)."""
        return cls.success(confidence=0.98, **kwargs)

    @classmethod
    def low_confidence(cls, **kwargs: Any) -> ExtractionResult:
        """Create a low-confidence result (<0.5)."""
        return cls.success(confidence=0.35, **kwargs)

    @classmethod
    def with_code(cls, **kwargs: Any) -> ExtractionResult:
        """Create a result with code content."""
        return cls.success(
            target_name="code_snippets",
            content=[
                "def example_function():\n    return 'Hello, World!'",
                "class ExampleClass:\n    pass",
            ],
            **kwargs,
        )

    @classmethod
    def with_prompts(cls, **kwargs: Any) -> ExtractionResult:
        """Create a result with prompt content."""
        return cls.success(
            target_name="system_prompts",
            content=[
                "You are a helpful AI assistant.",
                "Think step by step.",
            ],
            **kwargs,
        )

"""Cross-synthesis phase - cross-topic synthesis and global insights.

Phase 5.2: Extracted from research_pipeline.py.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.models.cross_synthesis import CrossTopicSynthesisReport
from src.orchestration.phases.base import PipelinePhase


@dataclass
class CrossSynthesisResult:
    """Result of the cross-synthesis phase."""

    report: Optional[CrossTopicSynthesisReport] = None
    output_path: Optional[Path] = None
    questions_answered: int = 0
    total_cost_usd: float = 0.0
    total_tokens_used: int = 0
    success: bool = False
    error: Optional[str] = None


class CrossSynthesisPhase(PipelinePhase[CrossSynthesisResult]):
    """Cross-synthesis phase - generates global insights across topics.

    Responsibilities:
    - Execute cross-topic synthesis questions
    - Generate Global_Synthesis.md
    - Aggregate insights across all research topics
    """

    @property
    def name(self) -> str:
        """Phase name."""
        return "cross_synthesis"

    def is_enabled(self) -> bool:
        """Check if cross-synthesis phase should run."""
        return self.context.enable_cross_synthesis

    async def execute(self) -> CrossSynthesisResult:
        """Execute cross-topic synthesis.

        Returns:
            CrossSynthesisResult with synthesis report
        """
        result = CrossSynthesisResult()

        if (
            not self.context.cross_synthesis_service
            or not self.context.cross_synthesis_generator
        ):
            self.logger.warning(
                "cross_synthesis_skipped",
                reason="services not initialized",
            )
            return result

        # Check if there are enabled questions
        enabled_questions = self.context.cross_synthesis_service.get_enabled_questions()
        if not enabled_questions:
            self.logger.info("cross_synthesis_skipped", reason="no enabled questions")
            return result

        self.logger.info(
            "cross_synthesis_starting",
            enabled_questions=len(enabled_questions),
        )

        try:
            # Run synthesis for all enabled questions
            report = await self.context.cross_synthesis_service.synthesize_all()
            result.report = report
            result.questions_answered = report.questions_answered
            result.total_cost_usd = report.total_cost_usd
            result.total_tokens_used = report.total_tokens_used

            # Write output file
            if report.results:
                output_path = self.context.cross_synthesis_generator.write(
                    report=report,
                    incremental=True,
                )

                if output_path:
                    result.output_path = output_path
                    result.success = True
                    self.logger.info(
                        "cross_synthesis_completed",
                        questions_answered=report.questions_answered,
                        total_cost_usd=report.total_cost_usd,
                        output_path=str(output_path),
                    )
                else:
                    result.error = "Failed to write output file"
                    self.logger.warning("cross_synthesis_write_failed")
            else:
                # No results but not an error
                result.success = True
                self.logger.info(
                    "cross_synthesis_no_results",
                    questions_answered=0,
                )

        except Exception as e:
            result.error = str(e)
            self.logger.error(
                "cross_synthesis_failed",
                error=str(e),
                exc_info=True,
            )

        return result

    def _get_default_result(self) -> CrossSynthesisResult:
        """Get default result when phase is skipped."""
        return CrossSynthesisResult()

"""Answer synthesis via LLM for cross-topic synthesis.

Handles LLM interaction for generating synthesis answers from
selected papers.
"""

import uuid
from typing import Any, List, Optional
import structlog

from src.models.cross_synthesis import (
    SynthesisQuestion,
    SynthesisResult,
    PaperSummary,
)
from src.utils.exceptions import CostLimitExceeded

logger = structlog.get_logger()


class AnswerSynthesizer:
    """Synthesizes answers using LLM.

    Handles:
    - LLM service interaction
    - Cost estimation and budget checking
    - Result construction
    """

    def __init__(self, llm_service: Optional[Any] = None):
        """Initialize answer synthesizer.

        Args:
            llm_service: LLM service for synthesis (optional for testing).
        """
        self.llm_service = llm_service

    def estimate_cost(self, prompt: str) -> float:
        """Estimate cost for a synthesis prompt.

        Args:
            prompt: Complete synthesis prompt.

        Returns:
            Estimated cost in USD.
        """
        # Estimate tokens (rough: 4 chars per token)
        estimated_tokens = len(prompt) // 4
        # Assume 1/3 output tokens, use Gemini pricing as baseline
        estimated_cost = (estimated_tokens * 1.5) / 1_000_000 * 3.0  # $3/M tokens avg
        return estimated_cost

    async def synthesize(
        self,
        question: SynthesisQuestion,
        papers: List[PaperSummary],
        prompt: str,
        budget_remaining: float,
    ) -> SynthesisResult:
        """Synthesize an answer for a question.

        Args:
            question: Question to synthesize.
            papers: Papers used for context.
            prompt: Complete prompt for LLM.
            budget_remaining: Remaining budget in USD.

        Returns:
            SynthesisResult with synthesis content.

        Raises:
            CostLimitExceeded: If budget would be exceeded.
        """
        logger.info(
            "synthesizing_question",
            question_id=question.id,
            budget_remaining=budget_remaining,
        )

        # Handle no papers case
        if not papers:
            return SynthesisResult(
                question_id=question.id,
                question_name=question.name,
                synthesis_text="No papers matched the criteria for this question.",
                papers_used=[],
                topics_covered=[],
                tokens_used=0,
                cost_usd=0.0,
                model_used="none",
                confidence=0.0,
            )

        # Check if LLM service available
        if self.llm_service is None:
            logger.warning("llm_service_not_configured")
            return SynthesisResult(
                question_id=question.id,
                question_name=question.name,
                synthesis_text="LLM service not configured for synthesis.",
                papers_used=[p.paper_id for p in papers],
                topics_covered=list({t for p in papers for t in p.topics}),
                tokens_used=0,
                cost_usd=0.0,
                model_used="none",
                confidence=0.0,
            )

        # Call LLM for synthesis
        try:
            synthesis_text, tokens_used, cost_usd, model_used = await self._call_llm(
                prompt, budget_remaining
            )

            # Calculate confidence based on paper coverage and quality
            avg_quality = sum(p.quality_score for p in papers) / len(papers)
            confidence = min(1.0, avg_quality / 100 * 0.8 + 0.2)

            result = SynthesisResult(
                question_id=question.id,
                question_name=question.name,
                synthesis_text=synthesis_text,
                papers_used=[p.paper_id for p in papers],
                topics_covered=list({t for p in papers for t in p.topics}),
                tokens_used=tokens_used,
                cost_usd=cost_usd,
                model_used=model_used,
                confidence=confidence,
            )

            logger.info(
                "question_synthesized",
                question_id=question.id,
                papers_used=len(papers),
                tokens_used=tokens_used,
                cost_usd=cost_usd,
            )

            return result

        except CostLimitExceeded:
            raise
        except Exception as e:
            logger.error(
                "synthesis_failed",
                question_id=question.id,
                error=str(e),
            )
            return SynthesisResult(
                question_id=question.id,
                question_name=question.name,
                synthesis_text=f"Synthesis failed: {e}",
                papers_used=[p.paper_id for p in papers],
                topics_covered=list({t for p in papers for t in p.topics}),
                tokens_used=0,
                cost_usd=0.0,
                model_used="error",
                confidence=0.0,
            )

    async def _call_llm(
        self,
        prompt: str,
        budget_remaining: float,
    ) -> tuple[str, int, float, str]:
        """Call LLM service for synthesis.

        Args:
            prompt: Complete synthesis prompt.
            budget_remaining: Remaining budget in USD.

        Returns:
            Tuple of (synthesis_text, tokens_used, cost_usd, model_used).

        Raises:
            CostLimitExceeded: If cost would exceed budget.
        """
        from src.models.paper import PaperMetadata
        from src.models.extraction import ExtractionTarget

        # Check estimated cost
        estimated_cost = self.estimate_cost(prompt)

        if estimated_cost > budget_remaining:
            msg = f"Estimated cost ${estimated_cost:.2f} exceeds "
            msg += f"budget ${budget_remaining:.2f}"
            raise CostLimitExceeded(msg)

        # Create a synthetic extraction target for synthesis
        synthesis_target = ExtractionTarget(
            name="cross_topic_synthesis",
            description="Synthesize insights across multiple research papers",
            output_format="text",
            required=True,
        )

        # Create minimal paper metadata with required fields
        paper_meta = PaperMetadata(
            paper_id="synthesis-" + str(uuid.uuid4())[:8],
            title="Cross-Topic Synthesis",
            url="https://synthesis.internal/cross-topic",  # type: ignore[arg-type]
            abstract="Cross-topic synthesis request",
            year=2025,
            citation_count=0,
            influential_citation_count=None,  # Synthetic paper, no real data
            relevance_score=1.0,
            quality_score=100.0,
            pdf_available=False,
            pdf_source=None,
        )

        # Call LLM service
        assert self.llm_service is not None, "LLM service not initialized"
        extraction = await self.llm_service.extract(
            markdown_content=prompt,
            targets=[synthesis_target],
            paper_metadata=paper_meta,
        )

        # Extract synthesis text from result
        synthesis_text = ""
        for result in extraction.extraction_results:
            if result.success and result.content:
                synthesis_text = str(result.content)
                break

        if not synthesis_text:
            synthesis_text = "Synthesis did not produce valid output."

        return (
            synthesis_text,
            extraction.tokens_used,
            extraction.cost_usd,
            self.llm_service.config.model if self.llm_service else "unknown",
        )

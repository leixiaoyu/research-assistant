"""Cross-Topic Synthesis Service - Main Orchestrator.

Coordinates paper selection, prompt building, and LLM synthesis
for cross-topic knowledge synthesis.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Any
import structlog

from src.models.cross_synthesis import (
    SynthesisQuestion,
    SynthesisResult,
    CrossTopicSynthesisReport,
    SynthesisConfig,
    SynthesisState,
    PaperSummary,
)
from src.models.registry import RegistryEntry
from src.services.registry_service import RegistryService
from src.services.synthesis.paper_selector import PaperSelector
from src.services.synthesis.prompt_builder import SynthesisPromptBuilder
from src.services.synthesis.answer_synthesizer import AnswerSynthesizer
from src.services.synthesis.state_manager import SynthesisStateManager
from src.utils.exceptions import CostLimitExceeded

logger = structlog.get_logger()


class CrossTopicSynthesisService:
    """Orchestrates cross-topic knowledge synthesis.

    Coordinates:
    - Paper selection (via PaperSelector)
    - Prompt building (via SynthesisPromptBuilder)
    - LLM synthesis (via AnswerSynthesizer)
    - State management (via SynthesisStateManager)
    """

    def __init__(
        self,
        registry_service: RegistryService,
        llm_service: Optional[Any] = None,
        config: Optional[SynthesisConfig] = None,
        config_path: Optional[Path] = None,
    ):
        """Initialize the cross-topic synthesis service.

        Args:
            registry_service: Registry service for paper access.
            llm_service: LLM service for synthesis (optional for testing).
            config: Synthesis configuration (optional, loaded from file if None).
            config_path: Path to synthesis config YAML.
        """
        self.registry = registry_service
        self.llm_service = llm_service

        # Initialize component services
        self._state_manager = SynthesisStateManager(
            registry_service=registry_service,
            config=config,
            config_path=config_path,
        )
        self._paper_selector = PaperSelector(registry_service)
        self._prompt_builder = SynthesisPromptBuilder()
        self._answer_synthesizer = AnswerSynthesizer(llm_service)

        logger.info(
            "cross_synthesis_service_initialized",
            config_path=str(config_path) if config_path else "default",
            has_llm=llm_service is not None,
        )

    @property
    def config(self) -> SynthesisConfig:
        """Get synthesis configuration."""
        return self._state_manager.config

    @property
    def _config(self) -> SynthesisConfig:
        """Backward compatibility: Get synthesis configuration."""
        return self._state_manager.config

    @property
    def _state(self) -> Optional[SynthesisState]:
        """Backward compatibility: Get synthesis state."""
        return self._state_manager.state

    @_state.setter
    def _state(self, value: SynthesisState) -> None:
        """Backward compatibility: Set synthesis state."""
        self._state_manager.state = value

    def load_config(self, config_path: Optional[Path] = None) -> SynthesisConfig:
        """Load synthesis configuration from YAML file.

        Args:
            config_path: Path to config file (uses default if None).

        Returns:
            Validated SynthesisConfig.
        """
        return self._state_manager.load_config(config_path)

    def get_all_entries(self) -> List[RegistryEntry]:
        """Get all entries from the registry.

        Returns:
            List of all registry entries.
        """
        return self._paper_selector.get_all_entries()

    def _entry_to_summary(self, entry: RegistryEntry) -> PaperSummary:
        """Convert a registry entry to a paper summary.

        Args:
            entry: Registry entry to convert.

        Returns:
            PaperSummary for prompt building.
        """
        return self._paper_selector.entry_to_summary(entry)

    def select_papers(
        self,
        question: SynthesisQuestion,
    ) -> List[PaperSummary]:
        """Select papers for synthesis using quality-weighted sampling.

        Args:
            question: Synthesis question with filtering criteria.

        Returns:
            List of PaperSummary objects for synthesis.
        """
        return self._paper_selector.select_papers(question)

    def build_synthesis_prompt(
        self,
        question: SynthesisQuestion,
        papers: List[PaperSummary],
    ) -> str:
        """Build LLM prompt with paper context.

        Args:
            question: Synthesis question with prompt template.
            papers: Selected papers for context.

        Returns:
            Complete prompt for LLM.
        """
        return self._prompt_builder.build_prompt(question, papers)

    def _estimate_tokens(self, prompt: str) -> int:
        """Estimate token count for a prompt.

        Args:
            prompt: Text to estimate.

        Returns:
            Estimated token count.
        """
        return self._prompt_builder.estimate_tokens(prompt)

    def _calculate_registry_hash(self) -> str:
        """Calculate hash of registry state for change detection.

        Returns:
            SHA-256 hash of registry entry IDs and timestamps.
        """
        entries = self._paper_selector.get_all_entries()
        return self._state_manager.calculate_registry_hash(entries)

    def _should_skip_incremental(self) -> tuple[bool, int]:
        """Check if synthesis should be skipped in incremental mode.

        Returns:
            Tuple of (should_skip, new_papers_count).
        """
        entries = self._paper_selector.get_all_entries()
        return self._state_manager.should_skip_incremental(entries)

    async def synthesize_question(
        self,
        question: SynthesisQuestion,
        budget_remaining: float = 15.0,
    ) -> SynthesisResult:
        """Synthesize a single question.

        Args:
            question: Question to synthesize.
            budget_remaining: Remaining budget in USD.

        Returns:
            SynthesisResult with synthesis content.

        Raises:
            CostLimitExceeded: If budget would be exceeded.
            ValueError: If LLM service not configured.
        """
        # Select papers
        papers = self.select_papers(question)

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

        # Build prompt with truncation if needed
        prompt, papers = self._prompt_builder.truncate_for_token_limit(
            question, papers, self.config.max_tokens_per_question
        )

        # Synthesize answer
        return await self._answer_synthesizer.synthesize(
            question=question,
            papers=papers,
            prompt=prompt,
            budget_remaining=budget_remaining,
        )

    async def synthesize_all(
        self,
        force: bool = False,
    ) -> CrossTopicSynthesisReport:
        """Run synthesis for all enabled questions.

        Args:
            force: Force full synthesis even if incremental would skip.

        Returns:
            CrossTopicSynthesisReport with all results.
        """
        logger.info(
            "synthesis_all_starting",
            questions=len(self.config.questions),
            force=force,
        )

        # Check incremental mode
        should_skip, new_papers = self._should_skip_incremental()
        if should_skip and not force:
            return CrossTopicSynthesisReport(
                report_id=f"syn-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
                total_papers_in_registry=len(self.get_all_entries()),
                results=[],
                total_tokens_used=0,
                total_cost_usd=0.0,
                incremental=True,
                new_papers_since_last=0,
            )

        # Get enabled questions sorted by priority
        questions = [q for q in self.config.questions if q.enabled]
        questions.sort(key=lambda q: q.priority)

        if not questions:
            logger.warning("no_enabled_questions")
            return CrossTopicSynthesisReport(
                report_id=f"syn-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
                total_papers_in_registry=len(self.get_all_entries()),
                results=[],
                total_tokens_used=0,
                total_cost_usd=0.0,
                incremental=False,
                new_papers_since_last=new_papers,
            )

        # Track budget and results
        budget_remaining = self.config.budget_per_synthesis_usd
        results: List[SynthesisResult] = []
        total_tokens = 0
        total_cost = 0.0

        # Process each question
        for question in questions:
            if budget_remaining <= 0:
                logger.warning(
                    "budget_exhausted",
                    remaining_questions=len(questions) - len(results),
                )
                break

            try:
                result = await self.synthesize_question(
                    question=question,
                    budget_remaining=budget_remaining,
                )

                results.append(result)
                total_tokens += result.tokens_used
                total_cost += result.cost_usd
                budget_remaining -= result.cost_usd

            except CostLimitExceeded as e:
                logger.warning(
                    "question_skipped_budget",
                    question_id=question.id,
                    error=str(e),
                )
                break
            except Exception as e:
                logger.error(
                    "question_failed",
                    question_id=question.id,
                    error=str(e),
                )
                # Continue with next question

        # Generate report
        report = CrossTopicSynthesisReport(
            report_id=f"syn-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            total_papers_in_registry=len(self.get_all_entries()),
            results=results,
            total_tokens_used=total_tokens,
            total_cost_usd=total_cost,
            incremental=self.config.incremental_mode and not force,
            new_papers_since_last=new_papers,
        )

        # Update state for incremental mode
        self._state_manager.state = SynthesisState(
            last_synthesis_at=datetime.now(timezone.utc),
            last_registry_hash=self._calculate_registry_hash(),
            last_report_id=report.report_id,
            questions_processed=[r.question_id for r in results],
        )

        logger.info(
            "synthesis_all_completed",
            questions_processed=len(results),
            total_tokens=total_tokens,
            total_cost=total_cost,
        )

        return report

    def get_enabled_questions(self) -> List[SynthesisQuestion]:
        """Get list of enabled synthesis questions.

        Returns:
            List of enabled SynthesisQuestion objects.
        """
        return [q for q in self.config.questions if q.enabled]

    def get_question_by_id(self, question_id: str) -> Optional[SynthesisQuestion]:
        """Get a specific question by ID.

        Args:
            question_id: Question ID to find.

        Returns:
            SynthesisQuestion or None if not found.
        """
        for q in self.config.questions:
            if q.id == question_id:
                return q
        return None

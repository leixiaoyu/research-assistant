"""Cross-Topic Synthesis Service for Phase 3.7.

Orchestrates cross-topic knowledge synthesis by:
- Selecting papers using quality-weighted sampling with diversity
- Building prompts with template variable substitution
- Calling LLM for synthesis with budget management
- Tracking costs and generating reports
"""

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Any
import structlog
import yaml

from src.models.cross_synthesis import (
    SynthesisQuestion,
    SynthesisResult,
    CrossTopicSynthesisReport,
    SynthesisConfig,
    PaperSummary,
    SynthesisState,
)
from src.models.registry import RegistryEntry
from src.services.registry_service import RegistryService
from src.utils.exceptions import CostLimitExceeded

logger = structlog.get_logger()

# Default config path
DEFAULT_CONFIG_PATH = Path("config/synthesis_config.yaml")

# Diversity sampling ratio (20% of budget for diversity)
DIVERSITY_RATIO = 0.20


class CrossTopicSynthesisService:
    """Orchestrates cross-topic knowledge synthesis.

    Provides methods for:
    - Loading and validating synthesis configuration
    - Selecting papers with quality weighting and diversity
    - Building synthesis prompts from templates
    - Executing synthesis via LLM with cost tracking
    - Generating synthesis reports
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
        self._config = config
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._state: Optional[SynthesisState] = None

        logger.info(
            "cross_synthesis_service_initialized",
            config_path=str(self._config_path),
            has_llm=llm_service is not None,
        )

    @property
    def config(self) -> SynthesisConfig:
        """Get synthesis configuration, loading if needed."""
        if self._config is None:
            self._config = self.load_config()
        return self._config

    def load_config(self, config_path: Optional[Path] = None) -> SynthesisConfig:
        """Load synthesis configuration from YAML file.

        Args:
            config_path: Path to config file (uses default if None).

        Returns:
            Validated SynthesisConfig.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            ValueError: If config is invalid.
        """
        path = config_path or self._config_path

        if not path.exists():
            logger.warning(
                "synthesis_config_not_found",
                path=str(path),
            )
            # Return default config with no questions
            return SynthesisConfig()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            config = SynthesisConfig.model_validate(data)

            logger.info(
                "synthesis_config_loaded",
                path=str(path),
                questions=len(config.questions),
                budget=config.budget_per_synthesis_usd,
            )

            return config

        except yaml.YAMLError as e:
            logger.error("synthesis_config_yaml_error", error=str(e))
            raise ValueError(f"Invalid YAML in synthesis config: {e}")
        except Exception as e:
            logger.error("synthesis_config_load_error", error=str(e))
            raise ValueError(f"Failed to load synthesis config: {e}")

    def get_all_entries(self) -> List[RegistryEntry]:
        """Get all entries from the registry.

        Returns:
            List of all registry entries.
        """
        state = self.registry.load()
        return list(state.entries.values())

    def _entry_to_summary(self, entry: RegistryEntry) -> PaperSummary:
        """Convert a registry entry to a paper summary.

        Args:
            entry: Registry entry to convert.

        Returns:
            PaperSummary for prompt building.
        """
        metadata = entry.metadata_snapshot or {}

        # Extract authors
        authors = metadata.get("authors", [])
        if isinstance(authors, list):
            # Handle list of author dicts or strings
            author_names = []
            for a in authors:
                if isinstance(a, dict):
                    author_names.append(a.get("name", str(a)))
                else:
                    author_names.append(str(a))
            authors = author_names

        # Extract quality score
        quality_score = metadata.get("quality_score", 0.0)
        if not isinstance(quality_score, (int, float)):
            quality_score = 0.0

        # Extract extraction results for summary
        extraction_summary = None
        if "extraction_results" in metadata:
            extraction_summary = metadata["extraction_results"]

        return PaperSummary(
            paper_id=entry.paper_id,
            title=metadata.get("title", entry.title_normalized),
            authors=authors,
            abstract=metadata.get("abstract"),
            publication_date=metadata.get("publication_date"),
            quality_score=float(quality_score),
            topics=entry.topic_affiliations,
            extraction_summary=extraction_summary,
        )

    def select_papers(
        self,
        question: SynthesisQuestion,
    ) -> List[PaperSummary]:
        """Select papers for synthesis using quality-weighted sampling.

        Algorithm:
        1. Get all registry entries
        2. Filter by topic_filters and topic_exclude
        3. Filter by min_quality_score
        4. Sort by quality_score (descending)
        5. Diversity sampling:
           - 80% budget: top quality papers
           - 20% budget: ensure topic diversity
        6. Limit to max_papers

        Args:
            question: Synthesis question with filtering criteria.

        Returns:
            List of PaperSummary objects for synthesis.
        """
        # 1. Get all entries from registry
        all_entries = self.get_all_entries()

        if not all_entries:
            logger.info("select_papers_no_entries")
            return []

        # 2. Apply topic filters
        filtered = []
        for entry in all_entries:
            # Check topic inclusion
            if question.topic_filters:
                if not any(
                    t in entry.topic_affiliations for t in question.topic_filters
                ):
                    continue

            # Check topic exclusion
            if any(t in entry.topic_affiliations for t in question.topic_exclude):
                continue

            # Get quality score from metadata
            metadata = entry.metadata_snapshot or {}
            quality_score = metadata.get("quality_score", 0.0)
            if not isinstance(quality_score, (int, float)):
                quality_score = 0.0

            # Check quality threshold
            if quality_score < question.min_quality_score:
                continue

            filtered.append((entry, float(quality_score)))

        if not filtered:
            logger.info(
                "select_papers_none_after_filter",
                topic_filters=question.topic_filters,
                topic_exclude=question.topic_exclude,
                min_quality=question.min_quality_score,
            )
            return []

        # 3. Sort by quality (descending)
        filtered.sort(key=lambda x: x[1], reverse=True)

        # 4. Diversity sampling
        max_papers = question.max_papers
        quality_budget = int(max_papers * (1 - DIVERSITY_RATIO))  # 80% for quality

        # Take top quality papers
        selected_entries = [e for e, _ in filtered[:quality_budget]]
        remaining = filtered[quality_budget:]

        # Ensure topic diversity in remaining budget
        topics_covered = set()
        for entry in selected_entries:
            topics_covered.update(entry.topic_affiliations)

        for entry, _ in remaining:
            if len(selected_entries) >= max_papers:
                break
            # Prefer papers from underrepresented topics
            new_topics = set(entry.topic_affiliations) - topics_covered
            if new_topics:
                selected_entries.append(entry)
                topics_covered.update(entry.topic_affiliations)

        # Fill remaining slots if diversity didn't use all budget
        for entry, _ in remaining:
            if len(selected_entries) >= max_papers:
                break
            if entry not in selected_entries:
                selected_entries.append(entry)

        # Convert to summaries
        summaries = [self._entry_to_summary(e) for e in selected_entries]

        logger.info(
            "papers_selected",
            question_id=question.id,
            total_entries=len(all_entries),
            after_filter=len(filtered),
            selected=len(summaries),
            topics_covered=len(topics_covered),
        )

        return summaries

    def build_synthesis_prompt(
        self,
        question: SynthesisQuestion,
        papers: List[PaperSummary],
    ) -> str:
        """Build LLM prompt with paper context.

        Substitutes template variables:
        - {paper_count}: Number of papers included
        - {topics}: Comma-separated list of topics
        - {paper_summaries}: Formatted paper summaries

        Args:
            question: Synthesis question with prompt template.
            papers: Selected papers for context.

        Returns:
            Complete prompt for LLM.
        """
        # Collect all unique topics
        all_topics: set = set()
        for paper in papers:
            all_topics.update(paper.topics)

        # Format paper summaries
        paper_summaries = "\n---\n".join(p.to_prompt_format() for p in papers)

        # Substitute template variables
        prompt = question.prompt
        prompt = prompt.replace("{paper_count}", str(len(papers)))
        prompt = prompt.replace("{topics}", ", ".join(sorted(all_topics)))
        prompt = prompt.replace("{paper_summaries}", paper_summaries)

        return prompt

    def _estimate_tokens(self, prompt: str) -> int:
        """Estimate token count for a prompt.

        Uses rough approximation of 4 characters per token.

        Args:
            prompt: Text to estimate.

        Returns:
            Estimated token count.
        """
        return len(prompt) // 4

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
        logger.info(
            "synthesizing_question",
            question_id=question.id,
            budget_remaining=budget_remaining,
        )

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

        # Build prompt
        prompt = self.build_synthesis_prompt(question, papers)

        # Estimate tokens and check budget
        estimated_tokens = self._estimate_tokens(prompt)
        if estimated_tokens > self.config.max_tokens_per_question:
            # Reduce paper count to fit
            reduction_ratio = (
                self.config.max_tokens_per_question / estimated_tokens * 0.8
            )
            new_count = max(1, int(len(papers) * reduction_ratio))
            papers = papers[:new_count]
            prompt = self.build_synthesis_prompt(question, papers)

            logger.warning(
                "prompt_truncated",
                question_id=question.id,
                original_papers=len(papers),
                reduced_to=new_count,
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
            synthesis_text, tokens_used, cost_usd, model_used = (
                await self._call_llm_synthesis(prompt, budget_remaining)
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

    async def _call_llm_synthesis(
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
            influential_citation_count=0,
            relevance_score=1.0,
            quality_score=100.0,
            pdf_available=False,
            pdf_source=None,
        )

        # Check estimated cost (rough estimate)
        estimated_tokens = self._estimate_tokens(prompt)
        # Assume 1/3 output tokens, use Gemini pricing as baseline
        estimated_cost = (estimated_tokens * 1.5) / 1_000_000 * 3.0  # $3/M tokens avg

        if estimated_cost > budget_remaining:
            msg = f"Estimated cost ${estimated_cost:.2f} exceeds "
            msg += f"budget ${budget_remaining:.2f}"
            raise CostLimitExceeded(msg)

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

    def _calculate_registry_hash(self) -> str:
        """Calculate hash of registry state for change detection.

        Returns:
            SHA-256 hash of registry entry IDs and timestamps.
        """
        state = self.registry.load()
        entries_data = sorted(
            [
                f"{e.paper_id}:{e.processed_at.isoformat()}"
                for e in state.entries.values()
            ]
        )
        combined = "|".join(entries_data)
        return hashlib.sha256(combined.encode()).hexdigest()

    def _should_skip_incremental(self) -> tuple[bool, int]:
        """Check if synthesis should be skipped in incremental mode.

        Returns:
            Tuple of (should_skip, new_papers_count).
        """
        if not self.config.incremental_mode:
            return False, 0

        if self._state is None:
            return False, 0

        if self._state.last_registry_hash is None:
            return False, 0

        current_hash = self._calculate_registry_hash()

        if current_hash == self._state.last_registry_hash:
            logger.info("incremental_skip_no_changes")
            return True, 0

        # Count new papers (simplified - just count difference)
        state = self.registry.load()
        current_count = len(state.entries)

        # Estimate new papers (not perfectly accurate but useful)
        new_count = max(0, current_count - len(self._state.questions_processed) * 10)

        return False, new_count

    async def synthesize_all(
        self,
        force: bool = False,
    ) -> CrossTopicSynthesisReport:
        """Run synthesis for all enabled questions.

        Algorithm:
        1. Load registry state
        2. Check incremental mode (skip if no new papers)
        3. Sort questions by priority
        4. For each enabled question:
           a. Select papers (quality-weighted + diversity)
           b. Build prompt with paper summaries
           c. Call LLM for synthesis
           d. Track tokens and cost
        5. Generate report

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
        self._state = SynthesisState(
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

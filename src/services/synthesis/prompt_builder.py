"""Prompt building for cross-topic synthesis.

Handles template variable substitution and prompt construction
for LLM synthesis requests.
"""

from typing import List
import structlog

from src.models.cross_synthesis import (
    SynthesisQuestion,
    PaperSummary,
)

logger = structlog.get_logger()


class SynthesisPromptBuilder:
    """Builds prompts for cross-topic synthesis.

    Handles template variable substitution:
    - {paper_count}: Number of papers included
    - {topics}: Comma-separated list of topics
    - {paper_summaries}: Formatted paper summaries
    """

    def build_prompt(
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

    def estimate_tokens(self, prompt: str) -> int:
        """Estimate token count for a prompt.

        Uses rough approximation of 4 characters per token.

        Args:
            prompt: Text to estimate.

        Returns:
            Estimated token count.
        """
        return len(prompt) // 4

    def truncate_for_token_limit(
        self,
        question: SynthesisQuestion,
        papers: List[PaperSummary],
        max_tokens: int,
    ) -> tuple[str, List[PaperSummary]]:
        """Build prompt, truncating papers if needed to fit token limit.

        Args:
            question: Synthesis question with prompt template.
            papers: Selected papers for context.
            max_tokens: Maximum tokens allowed.

        Returns:
            Tuple of (prompt, papers_used) after any truncation.
        """
        prompt = self.build_prompt(question, papers)
        estimated_tokens = self.estimate_tokens(prompt)

        if estimated_tokens <= max_tokens:
            return prompt, papers

        # Reduce paper count to fit
        reduction_ratio = max_tokens / estimated_tokens * 0.8
        new_count = max(1, int(len(papers) * reduction_ratio))
        truncated_papers = papers[:new_count]
        prompt = self.build_prompt(question, truncated_papers)

        logger.warning(
            "prompt_truncated",
            question_id=question.id,
            original_papers=len(papers),
            reduced_to=new_count,
        )

        return prompt, truncated_papers

"""LLM Service for Phase 2: PDF Processing & LLM Extraction

This service handles:
1. LLM provider abstraction (Anthropic Claude / Google Gemini)
2. Building structured extraction prompts
3. Parsing LLM JSON responses
4. Cost tracking and budget enforcement
5. Usage statistics

Cost Control Features:
- Per-paper token limits
- Daily spending limits
- Total spending limits
- Automatic daily reset

Security Features:
- API key from environment only
- No hardcoded credentials
- Input validation via Pydantic
"""

import json
from typing import List, Any, Optional
from datetime import datetime
import structlog

from src.models.llm import LLMConfig, CostLimits, UsageStats
from src.models.extraction import ExtractionTarget, ExtractionResult, PaperExtraction
from src.models.paper import PaperMetadata
from src.utils.exceptions import (
    ExtractionError,
    CostLimitExceeded,
    LLMAPIError,
    JSONParseError,
)

logger = structlog.get_logger()


class LLMService:
    """Service for extracting information from papers using LLMs

    Supports both Anthropic (Claude) and Google (Gemini) providers.
    Implements cost tracking and budget enforcement.
    """

    # Claude 3.5 Sonnet pricing (as of Jan 2025)
    CLAUDE_INPUT_COST_PER_MTOK = 3.00  # $3 per million tokens
    CLAUDE_OUTPUT_COST_PER_MTOK = 15.00  # $15 per million tokens

    # Gemini 1.5 Pro pricing (as of Jan 2025)
    GEMINI_INPUT_COST_PER_MTOK = 1.25  # $1.25 per million tokens
    GEMINI_OUTPUT_COST_PER_MTOK = 5.00  # $5 per million tokens

    def __init__(
        self,
        config: LLMConfig,
        cost_limits: CostLimits,
        usage_stats: Optional[UsageStats] = None,
    ):
        """Initialize LLM service

        Args:
            config: LLM configuration (provider, model, API key)
            cost_limits: Budget limits
            usage_stats: Usage statistics (optional, creates new if None)

        Raises:
            ValueError: If API key is invalid
        """
        self.config = config
        self.cost_limits = cost_limits
        self.usage_stats = usage_stats or UsageStats()

        # Initialize provider-specific client
        self.client: Any = None
        if config.provider == "anthropic":
            try:
                from anthropic import AsyncAnthropic

                self.client = AsyncAnthropic(api_key=config.api_key)
            except ImportError:
                raise ExtractionError(
                    "anthropic package not installed. Run: pip install anthropic"
                )
        elif config.provider == "google":
            try:
                import google.generativeai as genai

                genai.configure(api_key=config.api_key)
                self.client = genai.GenerativeModel(config.model)
            except ImportError:
                raise ExtractionError(
                    "google-generativeai package not installed. "
                    "Run: pip install google-generativeai"
                )

        logger.info(
            "llm_service_initialized",
            provider=config.provider,
            model=config.model,
            max_tokens=config.max_tokens,
        )

    async def extract(
        self,
        markdown_content: str,
        targets: List[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> PaperExtraction:
        """Extract information from markdown using LLM

        Args:
            markdown_content: Full paper in markdown format
            targets: List of extraction targets
            paper_metadata: Paper metadata for context

        Returns:
            PaperExtraction with results

        Raises:
            CostLimitExceeded: If cost limits would be exceeded
            ExtractionError: If extraction fails
            LLMAPIError: If LLM API call fails
            JSONParseError: If response parsing fails
        """
        # Check if daily stats should be reset
        if self.usage_stats.should_reset_daily():
            logger.info("daily_stats_reset")
            self.usage_stats.reset_daily_stats()

        # Check cost limits BEFORE calling LLM
        self._check_cost_limits()

        # Build extraction prompt
        prompt = self._build_extraction_prompt(
            markdown_content, targets, paper_metadata
        )

        logger.info(
            "extraction_started",
            paper_id=paper_metadata.paper_id,
            targets=len(targets),
            provider=self.config.provider,
        )

        # Call LLM
        try:
            if self.config.provider == "anthropic":
                response = await self._call_anthropic(prompt)
                tokens_used = response.usage.input_tokens + response.usage.output_tokens
                cost = self._calculate_cost_anthropic(response.usage)
            else:  # google
                response = await self._call_google(prompt)
                tokens_used = getattr(response.usage_metadata, "total_token_count", 0)
                cost = self._calculate_cost_google(tokens_used)

        except Exception as e:
            logger.error(
                "llm_api_call_failed",
                paper_id=paper_metadata.paper_id,
                provider=self.config.provider,
                error=str(e),
            )
            raise LLMAPIError(f"LLM API call failed: {e}")

        # Parse response
        try:
            results = self._parse_response(response, targets)
        except JSONParseError as e:
            logger.error(
                "extraction_parse_failed",
                paper_id=paper_metadata.paper_id,
                error=str(e),
            )
            raise

        # Update usage stats
        self._update_usage(tokens_used, cost)

        logger.info(
            "extraction_completed",
            paper_id=paper_metadata.paper_id,
            tokens_used=tokens_used,
            cost_usd=cost,
            successful_extractions=sum(1 for r in results if r.success),
        )

        return PaperExtraction(
            paper_id=paper_metadata.paper_id,
            extraction_results=results,
            tokens_used=tokens_used,
            cost_usd=cost,
            extraction_timestamp=datetime.utcnow(),
        )

    def _build_extraction_prompt(
        self, markdown: str, targets: List[ExtractionTarget], metadata: PaperMetadata
    ) -> str:
        """Build structured extraction prompt for LLM

        Args:
            markdown: Paper content in markdown
            targets: Extraction targets
            metadata: Paper metadata

        Returns:
            Formatted prompt string
        """
        # Format targets as JSON for structured extraction
        targets_json = [
            {
                "name": t.name,
                "description": t.description,
                "output_format": t.output_format,
                "required": t.required,
                "examples": t.examples,
            }
            for t in targets
        ]

        # Format author names
        author_names = ", ".join(a.name for a in (metadata.authors or []))

        prompt = f"""You are a research paper analyst specialized in extracting structured information from academic papers.

**Paper Metadata:**
- Title: {metadata.title}
- Authors: {author_names or 'Unknown'}
- Year: {metadata.year or 'Unknown'}
- Paper ID: {metadata.paper_id}

**Extraction Targets:**
{json.dumps(targets_json, indent=2)}

**Instructions:**
1. Read the paper content carefully
2. For each extraction target, extract the requested information
3. Follow the specified output_format for each target (text, code, json, list)
4. If a target cannot be found and is NOT required, return null for content
5. If a target is required and not found, set success=false with an error message
6. Provide a confidence score (0.0-1.0) for each extraction
7. Return ONLY valid JSON with NO additional text before or after

**Required JSON Structure:**
{{
  "extractions": [
    {{
      "target_name": "string",
      "success": boolean,
      "content": any,  // format depends on output_format
      "confidence": float,  // 0.0 to 1.0
      "error": "string or null"
    }}
  ]
}}

**Paper Content:**

{markdown}

**Now extract the information and return ONLY the JSON response:**"""

        return prompt

    async def _call_anthropic(self, prompt: str) -> Any:
        """Call Anthropic Claude API

        Args:
            prompt: Extraction prompt

        Returns:
            API response object

        Raises:
            LLMAPIError: If API call fails
        """
        try:
            response = await self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return response
        except Exception as e:
            raise LLMAPIError(f"Anthropic API error: {e}")

    async def _call_google(self, prompt: str) -> Any:
        """Call Google Gemini API

        Args:
            prompt: Extraction prompt

        Returns:
            API response object

        Raises:
            LLMAPIError: If API call fails
        """
        try:
            # Gemini uses async generate_content_async
            response = await self.client.generate_content_async(
                prompt,
                generation_config={
                    "temperature": self.config.temperature,
                    "max_output_tokens": self.config.max_tokens,
                },
            )
            return response
        except Exception as e:
            raise LLMAPIError(f"Google API error: {e}")

    def _parse_response(
        self, response: Any, targets: List[ExtractionTarget]
    ) -> List[ExtractionResult]:
        """Parse LLM response into structured results

        Args:
            response: LLM API response
            targets: Extraction targets for validation

        Returns:
            List of ExtractionResult objects

        Raises:
            JSONParseError: If parsing fails
        """
        # Extract text from response
        if self.config.provider == "anthropic":
            content = response.content[0].text
        else:  # google
            content = response.text

        # Try to extract JSON from response
        # LLM might include markdown code blocks
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        # Parse JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise JSONParseError(
                f"Invalid JSON in LLM response: {e}\nContent: {content[:500]}"
            )

        # Validate structure
        if "extractions" not in data:
            raise JSONParseError("Missing 'extractions' key in response")

        extractions = data["extractions"]
        if not isinstance(extractions, list):
            raise JSONParseError("'extractions' must be a list")

        # Convert to ExtractionResult objects
        results = []
        target_names = {t.name for t in targets}

        for ext in extractions:
            # Validate extraction has required fields
            if "target_name" not in ext:
                logger.warning("extraction_missing_target_name", extraction=ext)
                continue

            target_name = ext["target_name"]
            if target_name not in target_names:
                logger.warning("extraction_unknown_target", target_name=target_name)
                continue

            results.append(
                ExtractionResult(
                    target_name=target_name,
                    success=ext.get("success", True),
                    content=ext.get("content"),
                    confidence=ext.get("confidence", 0.0),
                    error=ext.get("error"),
                )
            )

        # Check if all required targets were extracted
        extracted_names = {r.target_name for r in results}
        for target in targets:
            if target.required and target.name not in extracted_names:
                logger.error("required_target_missing", target_name=target.name)
                results.append(
                    ExtractionResult(
                        target_name=target.name,
                        success=False,
                        content=None,
                        confidence=0.0,
                        error="Required target not found in LLM response",
                    )
                )

        return results

    def _calculate_cost_anthropic(self, usage: Any) -> float:
        """Calculate cost for Anthropic Claude

        Args:
            usage: Usage object from API response

        Returns:
            Cost in USD
        """
        input_cost = (usage.input_tokens / 1_000_000) * self.CLAUDE_INPUT_COST_PER_MTOK
        output_cost = (
            usage.output_tokens / 1_000_000
        ) * self.CLAUDE_OUTPUT_COST_PER_MTOK
        return input_cost + output_cost

    def _calculate_cost_google(self, total_tokens: int) -> float:
        """Calculate cost for Google Gemini

        Args:
            total_tokens: Total token count

        Returns:
            Cost in USD

        Note:
            Gemini API doesn't separate input/output tokens in usage_metadata,
            so we estimate using average cost
        """
        # Use average of input and output pricing
        avg_cost_per_mtok = (
            self.GEMINI_INPUT_COST_PER_MTOK + self.GEMINI_OUTPUT_COST_PER_MTOK
        ) / 2
        return (total_tokens / 1_000_000) * avg_cost_per_mtok

    def _check_cost_limits(self) -> None:
        """Check if cost limits would be exceeded

        Raises:
            CostLimitExceeded: If any limit would be exceeded
        """
        # Check total spending limit
        if self.usage_stats.total_cost_usd >= self.cost_limits.max_total_spend_usd:
            raise CostLimitExceeded(
                f"Total spending limit reached: "
                f"${self.usage_stats.total_cost_usd:.2f} >= "
                f"${self.cost_limits.max_total_spend_usd:.2f}"
            )

        # Check daily spending limit
        if self.usage_stats.total_cost_usd >= self.cost_limits.max_daily_spend_usd:
            raise CostLimitExceeded(
                f"Daily spending limit reached: "
                f"${self.usage_stats.total_cost_usd:.2f} >= "
                f"${self.cost_limits.max_daily_spend_usd:.2f}"
            )

    def _update_usage(self, tokens: int, cost: float) -> None:
        """Update usage statistics

        Args:
            tokens: Tokens used
            cost: Cost incurred
        """
        self.usage_stats.total_tokens += tokens
        self.usage_stats.total_cost_usd += cost
        self.usage_stats.papers_processed += 1

        logger.debug(
            "usage_updated",
            total_tokens=self.usage_stats.total_tokens,
            total_cost_usd=self.usage_stats.total_cost_usd,
            papers_processed=self.usage_stats.papers_processed,
        )

    def get_usage_summary(self) -> dict:
        """Get current usage statistics

        Returns:
            Dictionary with usage stats
        """
        return {
            "total_tokens": self.usage_stats.total_tokens,
            "total_cost_usd": round(self.usage_stats.total_cost_usd, 2),
            "papers_processed": self.usage_stats.papers_processed,
            "last_reset": self.usage_stats.last_reset.isoformat(),
            "daily_budget_remaining": round(
                self.cost_limits.max_daily_spend_usd - self.usage_stats.total_cost_usd,
                2,
            ),
            "total_budget_remaining": round(
                self.cost_limits.max_total_spend_usd - self.usage_stats.total_cost_usd,
                2,
            ),
        }

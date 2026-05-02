"""LLM-based relevance scoring for monitored papers (REQ-9.1.3).

Why this module
---------------
The Week-1 monitor (``ArxivMonitor``) returns papers that match a
subscription's keyword query. That keyword match is necessary but not
sufficient -- many returned papers are tangential. The Week-2
``RelevanceScorer`` uses a small/cheap LLM (Gemini Flash per the
resolved decision in ``.omc/plans/open-questions.md``) to score each
paper's title + abstract against the subscription's intent (keywords +
free-form query). The auto-ingest threshold (relevance >= 0.7) is
applied by callers (the CLI ``arisp monitor check`` command and the
scheduled job) -- this module just produces the score.

Design constraints
------------------
- **Bounded prompt:** title capped at 1000 chars, abstract at 2000.
  Keeps token usage predictable and avoids context-window blowout on
  papers with very long abstracts.
- **Structured output (not free text):** prompt asks for a JSON object
  ``{"score": float, "reasoning": str}`` -- a flexible JSON parse with
  an explicit Pydantic validator on the output enforces shape.
- **Score range enforcement:** [0.0, 1.0] -- malformed scores raise
  ``LLMResponseError`` rather than coerce silently.
- **Cost tracking:** the result carries the cost in USD so callers can
  aggregate across a cycle for the digest's "Stats" section.
- **No live API calls in tests:** the LLM service is dependency-injected
  so unit tests mock ``llm_service.complete``.

Public surface:

- :class:`RelevanceScoreResult` -- Pydantic V2 strict output model.
- :class:`LLMResponseError` -- raised on malformed LLM output.
- :class:`RelevanceScorer` -- the scorer (instantiate once, call
  ``await score(subscription, paper)`` per paper).
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.models.paper import PaperMetadata
from src.services.intelligence.monitoring.models import ResearchSubscription
from src.services.llm.service import LLMService

logger = structlog.get_logger()

# Prompt-side caps. Documented in module docstring.
TITLE_CAP_CHARS = 1000
ABSTRACT_CAP_CHARS = 2000

# Bounded LLM output budget. Reasoning is capped at 4096 chars on the
# Pydantic side; we ask the model for ~600 tokens to stay well under.
_MAX_OUTPUT_TOKENS = 600
_TEMPERATURE = 0.0  # deterministic-ish: scoring should be repeatable

# Truncation indicator embedded when content is capped. Keeps the LLM
# explicitly aware that the input was shortened (so it doesn't penalize
# the paper for the truncation itself).
_TRUNC_SUFFIX = " [...truncated]"


class LLMResponseError(Exception):
    """Raised when the LLM returns malformed JSON or out-of-range values."""


class RelevanceScoreResult(BaseModel):
    """Output of one call to :meth:`RelevanceScorer.score`.

    All fields have defensive validators so a misbehaving caller (or a
    creative LLM response) cannot smuggle invalid state through.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "example": {
                "score": 0.82,
                "reasoning": "Strong overlap with PEFT + adapters.",
                "model_used": "gemini-1.5-flash",
                "cost_usd": 0.00012,
            }
        },
    )

    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Relevance in [0.0, 1.0]. 1.0 means strongly relevant.",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Human-readable rationale for the score.",
    )
    model_used: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Identifier of the LLM model that produced the score.",
    )
    cost_usd: float = Field(
        ...,
        ge=0.0,
        description="Cost of the single LLM call in USD.",
    )


# Pricing for Gemini Flash (2024). Hard-coded here -- the LLM service's
# CostTracker prices Gemini Pro by default. Flash is significantly
# cheaper, and we don't want to plumb a second provider config through
# the existing manager just to score a paper. Source:
# https://ai.google.dev/pricing (Jan 2025: input $0.075/MTok, output
# $0.30/MTok). If the provider price changes we update one constant.
_FLASH_INPUT_USD_PER_MTOK = 0.075
_FLASH_OUTPUT_USD_PER_MTOK = 0.30


def _estimate_flash_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a Gemini Flash call.

    Centralized so tests can monkey-patch and so we keep the math in
    one place. Uses simple linear pricing (no batching discount).
    """
    return (input_tokens / 1_000_000.0) * _FLASH_INPUT_USD_PER_MTOK + (
        output_tokens / 1_000_000.0
    ) * _FLASH_OUTPUT_USD_PER_MTOK


def _truncate(value: Optional[str], cap: int) -> str:
    """Cap ``value`` to ``cap`` chars, appending a truncation marker."""
    if not value:
        return ""
    text = value.strip()
    if len(text) <= cap:
        return text
    # Reserve room for the suffix so the final string fits the cap.
    keep = max(1, cap - len(_TRUNC_SUFFIX))
    return text[:keep] + _TRUNC_SUFFIX


# Match a JSON object anywhere in the response, including ones wrapped
# in ``` fences. We try direct json.loads first; this regex is the
# fallback for chatty models that prefix the JSON with prose.
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _extract_json(content: str) -> dict[str, Any]:
    """Pull the JSON object out of an LLM response.

    Raises :class:`LLMResponseError` if no JSON object is found OR if
    the parse fails. Callers handle the error -- the scorer surfaces it
    as a normal failure (not as a generic LLM exception) so the caller
    can attribute the failure to the LLM, not to the network.
    """
    cleaned = content.strip()
    if not cleaned:
        raise LLMResponseError("LLM returned empty content")
    # Direct parse first -- cheapest and matches the prompted contract.
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: extract the outermost JSON object if the model
        # added prose around it (e.g. "Sure! Here is the JSON: {...}").
        match = _JSON_OBJECT_RE.search(cleaned)
        if not match:
            raise LLMResponseError("LLM response did not contain a JSON object")
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                f"Failed to parse JSON object from LLM response: {exc}"
            )
    if not isinstance(parsed, dict):
        raise LLMResponseError(
            f"LLM JSON was not an object (got {type(parsed).__name__})"
        )
    return parsed


class RelevanceScorer:
    """Score a paper's relevance to a subscription via Gemini Flash.

    The LLM service is injected so tests can mock the ``complete``
    method. Production callers wire in the project-wide ``LLMService``
    configured with a Flash model.
    """

    def __init__(self, llm_service: LLMService) -> None:
        """Initialize the scorer.

        Args:
            llm_service: Existing project LLM service. Its
                :meth:`LLMService.complete` is invoked once per
                ``score()`` call. The model identifier on the service's
                config is reported back via
                :attr:`RelevanceScoreResult.model_used`.
        """
        self._llm = llm_service

    async def score(
        self,
        subscription: ResearchSubscription,
        paper: PaperMetadata,
    ) -> RelevanceScoreResult:
        """Score ``paper`` against ``subscription``.

        Returns:
            A :class:`RelevanceScoreResult` with score, reasoning,
            model identifier, and estimated USD cost.

        Raises:
            LLMResponseError: If the LLM returns malformed JSON or a
                value outside the documented contract (score outside
                [0.0, 1.0], missing reasoning, etc.). Callers decide
                whether to retry or skip the paper -- the scorer does
                NOT swallow the error.
        """
        prompt = self._build_prompt(subscription, paper)
        response = await self._llm.complete(
            prompt=prompt,
            temperature=_TEMPERATURE,
            max_tokens=_MAX_OUTPUT_TOKENS,
        )

        parsed = _extract_json(response.content)

        # Validate via Pydantic so score-range / reasoning-length
        # constraints are enforced once, in the model.
        try:
            score_val = float(parsed["score"])
            reasoning_val = str(parsed["reasoning"])
        except KeyError as exc:
            raise LLMResponseError(f"LLM response missing required field: {exc}")
        except (TypeError, ValueError) as exc:
            raise LLMResponseError(f"LLM response had wrong type: {exc}")

        cost = _estimate_flash_cost(
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        try:
            result = RelevanceScoreResult(
                score=score_val,
                reasoning=reasoning_val,
                model_used=response.model,
                cost_usd=cost,
            )
        except ValidationError as exc:
            # Most common case: score outside [0, 1] or empty reasoning.
            raise LLMResponseError(f"LLM produced an invalid scoring payload: {exc}")

        logger.info(
            "relevance_scored",
            subscription_id=subscription.subscription_id,
            paper_id=paper.paper_id,
            score=result.score,
            model=result.model_used,
            cost_usd=result.cost_usd,
        )
        return result

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------
    @staticmethod
    def _build_prompt(subscription: ResearchSubscription, paper: PaperMetadata) -> str:
        """Construct the bounded, structured-output relevance prompt.

        We deliberately ask for a *strict* JSON shape to make parsing
        deterministic. The instruction set also asks the model to
        consider both the explicit keywords AND the free-form query --
        otherwise ``query`` becomes dead context for keyword-only subs.
        """
        title = _truncate(paper.title, TITLE_CAP_CHARS)
        abstract = _truncate(paper.abstract, ABSTRACT_CAP_CHARS)
        keywords_str = (
            ", ".join(subscription.keywords) if subscription.keywords else "(none)"
        )
        excludes_str = (
            ", ".join(subscription.exclude_keywords)
            if subscription.exclude_keywords
            else "(none)"
        )
        return (
            "You score how relevant a research paper is to a user's "
            "subscription. Score on a scale from 0.0 (not relevant) to "
            "1.0 (highly relevant).\n\n"
            "Subscription:\n"
            f"- Name: {subscription.name}\n"
            f"- Query: {subscription.query}\n"
            f"- Keywords: {keywords_str}\n"
            f"- Exclude keywords: {excludes_str}\n\n"
            "Paper:\n"
            f"- Title: {title}\n"
            f"- Abstract: {abstract or '(no abstract provided)'}\n\n"
            "Output requirements:\n"
            "- Respond with ONLY a single JSON object on one line, no "
            "prose, no code fences.\n"
            '- Schema: {"score": <float in [0.0, 1.0]>, "reasoning": '
            "<short string, <= 280 chars>}.\n"
            "- The score must be 0.0 to 1.0 inclusive.\n"
            "- Penalize papers that match exclude keywords.\n"
        )

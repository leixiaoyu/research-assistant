"""Tests for ``RelevanceScorer`` (Milestone 9.1, Week 2).

All LLM traffic is mocked at the ``LLMService.complete`` boundary --
no live network calls are made. Coverage targets:

- Happy path: well-formed JSON in -> RelevanceScoreResult out.
- Bounded prompt: title cap, abstract cap, truncation marker.
- Empty / missing abstract: prompt still well-formed.
- Excludes / keywords passthrough into the prompt.
- LLM responds with malformed JSON -> LLMResponseError.
- LLM omits the score field -> LLMResponseError.
- Score outside [0, 1] -> LLMResponseError.
- Score not numeric -> LLMResponseError.
- Empty response content -> LLMResponseError.
- JSON wrapped in prose -> recovered via regex fallback.
- Non-dict JSON top-level -> LLMResponseError.
- Cost calculation matches the documented per-MTok rates.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.paper import Author, PaperMetadata
from src.services.intelligence.monitoring.models import ResearchSubscription
from src.services.intelligence.monitoring.relevance_scorer import (
    ABSTRACT_CAP_CHARS,
    LLMResponseError,
    RelevanceScorer,
    RelevanceScoreResult,
    TITLE_CAP_CHARS,
    _estimate_flash_cost,
    _extract_json,
    _truncate,
)
from src.services.llm.providers.base import LLMResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_subscription(
    *,
    name: str = "PEFT Research",
    query: str = "parameter efficient fine tuning",
    keywords: list[str] | None = None,
    excludes: list[str] | None = None,
) -> ResearchSubscription:
    # ``or`` fallback would swallow an explicit empty-list, which we
    # need for the "(none)" prompt-rendering test. Use sentinels instead.
    if keywords is None:
        keywords = ["LoRA", "QLoRA"]
    if excludes is None:
        excludes = []
    return ResearchSubscription(
        subscription_id="sub-test12345",
        user_id="alice",
        name=name,
        query=query,
        keywords=keywords,
        exclude_keywords=excludes,
    )


def _make_paper(
    *,
    paper_id: str = "2401.00001",
    title: str = "Adapter Tuning for Efficient LLM Fine-Tuning",
    abstract: str | None = "We introduce a novel adapter approach.",
) -> PaperMetadata:
    return PaperMetadata(
        paper_id=paper_id,
        title=title,
        abstract=abstract,
        authors=[Author(name="Jane Doe")],
        url="https://arxiv.org/abs/2401.00001",  # type: ignore[arg-type]
    )


def _make_llm(
    content: str,
    *,
    input_tokens: int = 200,
    output_tokens: int = 50,
    model: str = "gemini-1.5-flash",
) -> MagicMock:
    """Return a mock LLMService whose ``complete`` returns ``content``."""
    response = LLMResponse(
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        provider="google",
        latency_ms=12.0,
    )
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=response)
    return llm


# ---------------------------------------------------------------------------
# Helper-level tests (pure functions)
# ---------------------------------------------------------------------------


class TestTruncate:
    """``_truncate`` enforces the cap and adds the marker."""

    def test_short_value_unchanged(self) -> None:
        assert _truncate("hello", 100) == "hello"

    def test_strips_whitespace(self) -> None:
        assert _truncate("  hello  ", 100) == "hello"

    def test_none_returns_empty(self) -> None:
        assert _truncate(None, 100) == ""

    def test_empty_returns_empty(self) -> None:
        assert _truncate("", 100) == ""

    def test_long_value_truncated_with_suffix(self) -> None:
        text = "a" * 50
        result = _truncate(text, 20)
        assert result.endswith("[...truncated]")
        assert len(result) == 20

    def test_truncation_keeps_at_least_one_char(self) -> None:
        # Cap smaller than the suffix length -- must still keep 1 char.
        result = _truncate("abcdef", 5)
        assert result.startswith("a")


class TestExtractJson:
    """``_extract_json`` handles direct + wrapped JSON, rejects garbage."""

    def test_direct_json(self) -> None:
        assert _extract_json('{"score": 0.5}') == {"score": 0.5}

    def test_json_wrapped_in_prose(self) -> None:
        # Some chatty models prefix the JSON with text.
        wrapped = 'Sure! Here is your JSON: {"score": 0.7, "reasoning": "ok"}'
        assert _extract_json(wrapped) == {"score": 0.7, "reasoning": "ok"}

    def test_json_in_code_fence(self) -> None:
        wrapped = '```json\n{"score": 0.3, "reasoning": "meh"}\n```'
        assert _extract_json(wrapped) == {"score": 0.3, "reasoning": "meh"}

    def test_empty_raises(self) -> None:
        with pytest.raises(LLMResponseError, match="empty content"):
            _extract_json("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(LLMResponseError, match="empty content"):
            _extract_json("   \n  ")

    def test_no_json_raises(self) -> None:
        with pytest.raises(LLMResponseError, match="did not contain a JSON"):
            _extract_json("just some prose, no JSON here")

    def test_malformed_json_after_extraction_raises(self) -> None:
        # Regex extracts "{not valid}" but it doesn't parse.
        with pytest.raises(LLMResponseError, match="Failed to parse JSON"):
            _extract_json("Here: {not valid}")

    def test_array_json_rejected(self) -> None:
        # Top-level must be an object, not an array.
        with pytest.raises(LLMResponseError, match="not an object"):
            _extract_json("[1, 2, 3]")


class TestEstimateFlashCost:
    """``_estimate_flash_cost`` matches the documented Gemini Flash pricing."""

    def test_zero_tokens_zero_cost(self) -> None:
        assert _estimate_flash_cost(0, 0) == 0.0

    def test_input_only(self) -> None:
        # 1M input tokens at $0.075/MTok = $0.075
        assert _estimate_flash_cost(1_000_000, 0) == pytest.approx(0.075)

    def test_output_only(self) -> None:
        # 1M output tokens at $0.30/MTok = $0.30
        assert _estimate_flash_cost(0, 1_000_000) == pytest.approx(0.30)

    def test_mixed(self) -> None:
        # 200 in + 50 out -> very small cost
        cost = _estimate_flash_cost(200, 50)
        expected = (200 / 1_000_000) * 0.075 + (50 / 1_000_000) * 0.30
        assert cost == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Output model tests
# ---------------------------------------------------------------------------


class TestRelevanceScoreResult:
    """The Pydantic V2 model enforces score range + reasoning length."""

    def test_construct_happy(self) -> None:
        result = RelevanceScoreResult(
            score=0.5,
            reasoning="ok",
            model_used="gemini-1.5-flash",
            cost_usd=0.0001,
        )
        assert result.score == 0.5

    def test_score_out_of_range_high_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RelevanceScoreResult(
                score=1.1,
                reasoning="ok",
                model_used="m",
                cost_usd=0.0,
            )

    def test_score_out_of_range_low_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RelevanceScoreResult(
                score=-0.1,
                reasoning="ok",
                model_used="m",
                cost_usd=0.0,
            )

    def test_extra_field_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RelevanceScoreResult(  # type: ignore[call-arg]
                score=0.5,
                reasoning="ok",
                model_used="m",
                cost_usd=0.0,
                extra_field="nope",
            )


# ---------------------------------------------------------------------------
# RelevanceScorer.score() integration tests (LLM mocked)
# ---------------------------------------------------------------------------


class TestRelevanceScorerScore:
    """End-to-end ``score()`` behavior with a mocked LLM."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        llm = _make_llm('{"score": 0.85, "reasoning": "Very relevant"}')
        scorer = RelevanceScorer(llm)

        result = await scorer.score(_make_subscription(), _make_paper())

        assert isinstance(result, RelevanceScoreResult)
        assert result.score == 0.85
        assert result.reasoning == "Very relevant"
        assert result.model_used == "gemini-1.5-flash"
        assert result.cost_usd > 0.0
        # Verify the LLM was called with bounded prompt + low temp.
        llm.complete.assert_awaited_once()
        kwargs = llm.complete.await_args.kwargs
        assert kwargs["temperature"] == 0.0
        assert kwargs["max_tokens"] == 600

    @pytest.mark.asyncio
    async def test_prompt_includes_subscription_keywords_and_excludes(self) -> None:
        llm = _make_llm('{"score": 0.5, "reasoning": "ok"}')
        scorer = RelevanceScorer(llm)
        sub = _make_subscription(
            keywords=["adapters", "PEFT"],
            excludes=["survey"],
        )
        await scorer.score(sub, _make_paper())

        prompt = llm.complete.await_args.kwargs["prompt"]
        assert "adapters" in prompt
        assert "PEFT" in prompt
        assert "survey" in prompt
        assert sub.query in prompt

    @pytest.mark.asyncio
    async def test_prompt_handles_no_keywords(self) -> None:
        llm = _make_llm('{"score": 0.5, "reasoning": "ok"}')
        scorer = RelevanceScorer(llm)
        sub = _make_subscription(keywords=[], excludes=[])
        await scorer.score(sub, _make_paper())

        prompt = llm.complete.await_args.kwargs["prompt"]
        # When no keywords, prompt shows "(none)".
        assert "Keywords: (none)" in prompt
        assert "Exclude keywords: (none)" in prompt

    @pytest.mark.asyncio
    async def test_prompt_handles_missing_abstract(self) -> None:
        llm = _make_llm('{"score": 0.5, "reasoning": "ok"}')
        scorer = RelevanceScorer(llm)
        await scorer.score(_make_subscription(), _make_paper(abstract=None))

        prompt = llm.complete.await_args.kwargs["prompt"]
        assert "(no abstract provided)" in prompt

    @pytest.mark.asyncio
    async def test_prompt_truncates_long_title_and_abstract(self) -> None:
        llm = _make_llm('{"score": 0.5, "reasoning": "ok"}')
        scorer = RelevanceScorer(llm)
        # Build long inputs > caps. Use lengths that hit the caps but
        # remain within PaperMetadata's own validation (title <= 1000,
        # abstract <= 10000) -- our caps are 1000 / 2000.
        long_title = "X" * TITLE_CAP_CHARS  # exactly at cap (no truncation)
        long_abstract = "Y" * (ABSTRACT_CAP_CHARS + 500)
        await scorer.score(
            _make_subscription(),
            _make_paper(title=long_title, abstract=long_abstract),
        )

        prompt = llm.complete.await_args.kwargs["prompt"]
        # The truncation marker must appear for the abstract.
        assert "[...truncated]" in prompt

    @pytest.mark.asyncio
    async def test_malformed_json_raises(self) -> None:
        llm = _make_llm("definitely not json at all")
        scorer = RelevanceScorer(llm)
        with pytest.raises(LLMResponseError):
            await scorer.score(_make_subscription(), _make_paper())

    @pytest.mark.asyncio
    async def test_missing_score_field_raises(self) -> None:
        llm = _make_llm('{"reasoning": "ok"}')
        scorer = RelevanceScorer(llm)
        with pytest.raises(LLMResponseError, match="missing required field"):
            await scorer.score(_make_subscription(), _make_paper())

    @pytest.mark.asyncio
    async def test_missing_reasoning_field_raises(self) -> None:
        llm = _make_llm('{"score": 0.5}')
        scorer = RelevanceScorer(llm)
        with pytest.raises(LLMResponseError, match="missing required field"):
            await scorer.score(_make_subscription(), _make_paper())

    @pytest.mark.asyncio
    async def test_score_out_of_range_high_raises(self) -> None:
        llm = _make_llm('{"score": 2.0, "reasoning": "way over"}')
        scorer = RelevanceScorer(llm)
        with pytest.raises(LLMResponseError, match="invalid scoring payload"):
            await scorer.score(_make_subscription(), _make_paper())

    @pytest.mark.asyncio
    async def test_score_out_of_range_negative_raises(self) -> None:
        llm = _make_llm('{"score": -0.5, "reasoning": "negative"}')
        scorer = RelevanceScorer(llm)
        with pytest.raises(LLMResponseError, match="invalid scoring payload"):
            await scorer.score(_make_subscription(), _make_paper())

    @pytest.mark.asyncio
    async def test_score_not_numeric_raises(self) -> None:
        llm = _make_llm('{"score": "high", "reasoning": "ok"}')
        scorer = RelevanceScorer(llm)
        with pytest.raises(LLMResponseError, match="wrong type"):
            await scorer.score(_make_subscription(), _make_paper())

    @pytest.mark.asyncio
    async def test_score_none_raises(self) -> None:
        llm = _make_llm('{"score": null, "reasoning": "ok"}')
        scorer = RelevanceScorer(llm)
        with pytest.raises(LLMResponseError, match="wrong type"):
            await scorer.score(_make_subscription(), _make_paper())

    @pytest.mark.asyncio
    async def test_empty_content_raises(self) -> None:
        llm = _make_llm("")
        scorer = RelevanceScorer(llm)
        with pytest.raises(LLMResponseError, match="empty content"):
            await scorer.score(_make_subscription(), _make_paper())

    @pytest.mark.asyncio
    async def test_empty_reasoning_after_validation_raises(self) -> None:
        # Pydantic min_length=1 on reasoning catches this.
        llm = _make_llm('{"score": 0.5, "reasoning": ""}')
        scorer = RelevanceScorer(llm)
        with pytest.raises(LLMResponseError, match="invalid scoring payload"):
            await scorer.score(_make_subscription(), _make_paper())

    @pytest.mark.asyncio
    async def test_reasoning_too_long_raises(self) -> None:
        # Pydantic max_length=4096; force the LLM to respond with > 4096 chars.
        long_reasoning = "x" * 5000
        llm = _make_llm('{"score": 0.5, "reasoning": "' + long_reasoning + '"}')
        scorer = RelevanceScorer(llm)
        with pytest.raises(LLMResponseError, match="invalid scoring payload"):
            await scorer.score(_make_subscription(), _make_paper())

    @pytest.mark.asyncio
    async def test_score_recovered_from_prose_wrapped_json(self) -> None:
        llm = _make_llm('Sure! {"score": 0.42, "reasoning": "moderate"} as requested.')
        scorer = RelevanceScorer(llm)
        result = await scorer.score(_make_subscription(), _make_paper())
        assert result.score == 0.42
        assert result.reasoning == "moderate"

    @pytest.mark.asyncio
    async def test_cost_uses_response_token_counts(self) -> None:
        # 100 input + 20 output -> deterministic small cost.
        llm = _make_llm(
            '{"score": 0.5, "reasoning": "ok"}',
            input_tokens=100,
            output_tokens=20,
        )
        scorer = RelevanceScorer(llm)
        result = await scorer.score(_make_subscription(), _make_paper())

        expected = _estimate_flash_cost(100, 20)
        assert result.cost_usd == pytest.approx(expected)

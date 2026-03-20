"""Tests for synthesis service component modules.

Tests for the decomposed synthesis service components:
- PaperSelector
- SynthesisPromptBuilder
- AnswerSynthesizer
- SynthesisStateManager
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from src.services.synthesis.paper_selector import PaperSelector, DIVERSITY_RATIO
from src.services.synthesis.prompt_builder import SynthesisPromptBuilder
from src.services.synthesis.answer_synthesizer import AnswerSynthesizer
from src.services.synthesis.state_manager import (
    SynthesisStateManager,
    DEFAULT_CONFIG_PATH,
)
from src.services.synthesis.cross_synthesis import CrossTopicSynthesisService
from src.models.cross_synthesis import (
    SynthesisQuestion,
    SynthesisConfig,
    SynthesisState,
    PaperSummary,
)
from src.models.registry import RegistryEntry, RegistryState


class TestPaperSelector:
    """Tests for PaperSelector component."""

    def test_diversity_ratio_constant(self):
        """Test DIVERSITY_RATIO constant value."""
        assert DIVERSITY_RATIO == 0.20

    def test_entry_to_summary_basic(self):
        """Test converting registry entry to paper summary."""
        mock_registry = MagicMock()
        selector = PaperSelector(mock_registry)

        entry = RegistryEntry(
            paper_id="paper-1",
            title_normalized="test paper",
            doi=None,
            topic_affiliations=["topic-a"],
            first_seen_at=datetime.now(timezone.utc),
            processed_at=datetime.now(timezone.utc),
            extraction_target_hash="abc123",
            metadata_snapshot={
                "title": "Test Paper",
                "authors": ["Author A"],
                "quality_score": 85.0,
            },
        )

        summary = selector.entry_to_summary(entry)

        assert summary.paper_id == "paper-1"
        assert summary.title == "Test Paper"
        assert summary.quality_score == 85.0

    def test_filter_entries_empty(self):
        """Test filtering with no entries."""
        mock_registry = MagicMock()
        selector = PaperSelector(mock_registry)

        question = SynthesisQuestion(
            id="q1",
            name="Test",
            prompt="Test prompt",
        )

        result = selector._filter_entries([], question)
        assert result == []


class TestSynthesisPromptBuilder:
    """Tests for SynthesisPromptBuilder component."""

    def test_build_prompt_basic(self):
        """Test basic prompt building."""
        builder = SynthesisPromptBuilder()

        question = SynthesisQuestion(
            id="q1",
            name="Test",
            prompt="Analyze {paper_count} papers on {topics}. {paper_summaries}",
        )

        papers = [
            PaperSummary(
                paper_id="p1",
                title="Paper 1",
                authors=["Author"],
                quality_score=80.0,
                topics=["ml"],
            ),
        ]

        prompt = builder.build_prompt(question, papers)

        assert "1 papers" in prompt
        assert "ml" in prompt

    def test_estimate_tokens(self):
        """Test token estimation."""
        builder = SynthesisPromptBuilder()

        # 100 chars should be ~25 tokens
        text = "a" * 100
        tokens = builder.estimate_tokens(text)
        assert tokens == 25

    def test_truncate_within_limit(self):
        """Test truncation when within limit."""
        builder = SynthesisPromptBuilder()

        question = SynthesisQuestion(
            id="q1",
            name="Test",
            prompt="Short prompt",
        )

        papers = [
            PaperSummary(
                paper_id="p1",
                title="Paper 1",
                authors=["Author"],
                quality_score=80.0,
                topics=["ml"],
            ),
        ]

        prompt, result_papers = builder.truncate_for_token_limit(
            question, papers, max_tokens=10000
        )

        assert len(result_papers) == 1


class TestAnswerSynthesizer:
    """Tests for AnswerSynthesizer component."""

    def test_estimate_cost(self):
        """Test cost estimation."""
        synthesizer = AnswerSynthesizer()

        # 4000 chars = ~1000 tokens
        # Cost = (1000 * 1.5) / 1M * 3 = 0.0045
        prompt = "x" * 4000
        cost = synthesizer.estimate_cost(prompt)
        assert cost == pytest.approx(0.0045, rel=0.01)

    @pytest.mark.asyncio
    async def test_synthesize_no_papers(self):
        """Test synthesize with empty papers list."""
        synthesizer = AnswerSynthesizer()

        question = SynthesisQuestion(
            id="q1",
            name="Test",
            prompt="Test prompt",
        )

        result = await synthesizer.synthesize(
            question=question,
            papers=[],  # Empty papers
            prompt="Test prompt",
            budget_remaining=10.0,
        )

        assert (
            result.synthesis_text == "No papers matched the criteria for this question."
        )
        assert result.model_used == "none"

    @pytest.mark.asyncio
    async def test_synthesize_no_llm_service(self):
        """Test synthesize without LLM service configured."""
        synthesizer = AnswerSynthesizer(llm_service=None)

        question = SynthesisQuestion(
            id="q1",
            name="Test",
            prompt="Test prompt",
        )

        papers = [
            PaperSummary(
                paper_id="p1",
                title="Paper 1",
                authors=["Author"],
                quality_score=80.0,
                topics=["ml"],
            ),
        ]

        result = await synthesizer.synthesize(
            question=question,
            papers=papers,
            prompt="Test prompt",
            budget_remaining=10.0,
        )

        assert "not configured" in result.synthesis_text
        assert result.model_used == "none"


class TestSynthesisStateManager:
    """Tests for SynthesisStateManager component."""

    def test_default_config_path(self):
        """Test DEFAULT_CONFIG_PATH constant."""
        assert DEFAULT_CONFIG_PATH == Path("config/synthesis_config.yaml")

    def test_config_property_loads(self):
        """Test config property loads config when needed."""
        mock_registry = MagicMock()
        manager = SynthesisStateManager(
            registry_service=mock_registry,
            config=None,
        )

        # Should load default config when accessed
        config = manager.config
        assert isinstance(config, SynthesisConfig)

    def test_state_property_getter(self):
        """Test state property getter."""
        mock_registry = MagicMock()
        manager = SynthesisStateManager(registry_service=mock_registry)

        # Initially None
        assert manager.state is None

    def test_state_property_setter(self):
        """Test state property setter."""
        mock_registry = MagicMock()
        manager = SynthesisStateManager(registry_service=mock_registry)

        state = SynthesisState(
            last_synthesis_at=datetime.now(timezone.utc),
            last_registry_hash="abc123",
            last_report_id="report-1",
            questions_processed=["q1"],
        )

        manager.state = state
        assert manager.state == state

    def test_calculate_registry_hash(self):
        """Test registry hash calculation."""
        mock_registry = MagicMock()
        manager = SynthesisStateManager(registry_service=mock_registry)

        entries = [
            RegistryEntry(
                paper_id="p1",
                title_normalized="paper 1",
                doi=None,
                topic_affiliations=[],
                first_seen_at=datetime.now(timezone.utc),
                processed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                extraction_target_hash="abc123",
                metadata_snapshot={},
            ),
        ]

        hash1 = manager.calculate_registry_hash(entries)
        hash2 = manager.calculate_registry_hash(entries)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex


class TestCrossTopicSynthesisServiceBackwardCompat:
    """Tests for backward compatibility properties in CrossTopicSynthesisService."""

    def test_config_property(self):
        """Test config property."""
        mock_registry = MagicMock()
        mock_registry.load.return_value = RegistryState(entries={})

        service = CrossTopicSynthesisService(
            registry_service=mock_registry,
            config=SynthesisConfig(questions=[]),
        )

        assert isinstance(service.config, SynthesisConfig)

    def test_underscore_config_property(self):
        """Test _config backward compat property."""
        mock_registry = MagicMock()
        mock_registry.load.return_value = RegistryState(entries={})

        service = CrossTopicSynthesisService(
            registry_service=mock_registry,
            config=SynthesisConfig(questions=[]),
        )

        # Access _config (backward compat)
        assert isinstance(service._config, SynthesisConfig)

    def test_underscore_state_property_getter(self):
        """Test _state backward compat property getter."""
        mock_registry = MagicMock()
        mock_registry.load.return_value = RegistryState(entries={})

        service = CrossTopicSynthesisService(
            registry_service=mock_registry,
            config=SynthesisConfig(questions=[]),
        )

        # Initially None
        assert service._state is None

    def test_underscore_state_property_setter(self):
        """Test _state backward compat property setter."""
        mock_registry = MagicMock()
        mock_registry.load.return_value = RegistryState(entries={})

        service = CrossTopicSynthesisService(
            registry_service=mock_registry,
            config=SynthesisConfig(questions=[]),
        )

        state = SynthesisState(
            last_synthesis_at=datetime.now(timezone.utc),
            last_registry_hash="abc123",
            last_report_id="report-1",
            questions_processed=["q1"],
        )

        service._state = state
        assert service._state == state

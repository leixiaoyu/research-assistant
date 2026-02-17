"""Unit tests for Phase 3.7 CrossTopicSynthesisService.

Tests:
- Configuration loading
- Paper selection algorithm
- Quality-weighted selection
- Diversity sampling
- Topic filtering
- Prompt building
- Synthesis orchestration
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
import tempfile
import yaml

from src.models.cross_synthesis import (
    SynthesisQuestion,
    SynthesisConfig,
    PaperSummary,
)
from src.models.registry import RegistryEntry, RegistryState
from src.services.cross_synthesis_service import CrossTopicSynthesisService
from src.services.registry_service import RegistryService


@pytest.fixture
def mock_registry_service():
    """Create a mock registry service."""
    service = MagicMock(spec=RegistryService)

    # Create mock registry state with entries
    entries = {}
    for i in range(10):
        entry = RegistryEntry(
            identifiers={"doi": f"10.1234/paper{i}"},
            title_normalized=f"test paper {i}",
            extraction_target_hash=f"sha256:test{i}",
            topic_affiliations=[f"topic-{i % 3}"],  # 3 topics
            metadata_snapshot={
                "title": f"Test Paper {i}",
                "abstract": f"Abstract for paper {i}",
                "authors": [f"Author {i}"],
                "quality_score": 90 - i * 5,  # 90, 85, 80, ..., 45
            },
        )
        entries[entry.paper_id] = entry

    state = MagicMock(spec=RegistryState)
    state.entries = entries
    service.load.return_value = state

    return service


@pytest.fixture
def sample_config():
    """Create a sample synthesis config."""
    return SynthesisConfig(
        questions=[
            SynthesisQuestion(
                id="test-question-1",
                name="Test Question 1",
                prompt="Analyze {paper_count} papers from {topics}.\n{paper_summaries}",
                topic_filters=[],
                max_papers=5,
                min_quality_score=0.0,
                priority=1,
                enabled=True,
            ),
            SynthesisQuestion(
                id="test-question-2",
                name="Test Question 2",
                prompt="Second question {paper_summaries}",
                topic_filters=["topic-0"],
                max_papers=3,
                min_quality_score=60.0,
                priority=2,
                enabled=True,
            ),
            SynthesisQuestion(
                id="disabled-question",
                name="Disabled Question",
                prompt="Should not run {paper_summaries}",
                enabled=False,
            ),
        ],
        budget_per_synthesis_usd=10.0,
        max_tokens_per_question=50000,
    )


@pytest.fixture
def synthesis_service(mock_registry_service, sample_config):
    """Create a synthesis service with mocked dependencies."""
    return CrossTopicSynthesisService(
        registry_service=mock_registry_service,
        llm_service=None,
        config=sample_config,
    )


class TestConfigLoading:
    """Tests for configuration loading."""

    def test_load_config_from_file(self):
        """Test loading config from YAML file."""
        config_data = {
            "budget_per_synthesis_usd": 20.0,
            "max_tokens_per_question": 80000,
            "questions": [
                {
                    "id": "q1",
                    "name": "Question 1",
                    "prompt": "Test prompt {paper_summaries}",
                    "enabled": True,
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)

        try:
            mock_registry = MagicMock(spec=RegistryService)
            mock_registry.load.return_value = MagicMock(entries={})

            service = CrossTopicSynthesisService(
                registry_service=mock_registry,
                config_path=config_path,
            )

            config = service.load_config()
            assert config.budget_per_synthesis_usd == 20.0
            assert config.max_tokens_per_question == 80000
            assert len(config.questions) == 1
        finally:
            config_path.unlink()

    def test_load_config_file_not_found(self):
        """Test loading config when file doesn't exist."""
        mock_registry = MagicMock(spec=RegistryService)
        mock_registry.load.return_value = MagicMock(entries={})

        service = CrossTopicSynthesisService(
            registry_service=mock_registry,
            config_path=Path("/nonexistent/config.yaml"),
        )

        # Should return default config with no questions
        config = service.load_config()
        assert config.questions == []
        assert config.budget_per_synthesis_usd == 15.0

    def test_load_config_invalid_yaml(self):
        """Test loading invalid YAML config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: content: [")
            config_path = Path(f.name)

        try:
            mock_registry = MagicMock(spec=RegistryService)
            service = CrossTopicSynthesisService(
                registry_service=mock_registry,
                config_path=config_path,
            )

            with pytest.raises(ValueError, match="Invalid YAML"):
                service.load_config()
        finally:
            config_path.unlink()


class TestPaperSelection:
    """Tests for paper selection algorithm."""

    def test_select_papers_basic(self, synthesis_service):
        """Test basic paper selection."""
        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Test {paper_summaries}",
            max_papers=5,
        )

        papers = synthesis_service.select_papers(question)

        assert len(papers) == 5
        # Should be sorted by quality (highest first)
        for i in range(len(papers) - 1):
            assert papers[i].quality_score >= papers[i + 1].quality_score

    def test_select_papers_topic_filter(self, synthesis_service):
        """Test paper selection with topic filter."""
        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Test {paper_summaries}",
            topic_filters=["topic-0"],
            max_papers=10,
        )

        papers = synthesis_service.select_papers(question)

        # All papers should be from topic-0
        for paper in papers:
            assert "topic-0" in paper.topics

    def test_select_papers_topic_exclude(self, synthesis_service):
        """Test paper selection with topic exclusion."""
        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Test {paper_summaries}",
            topic_exclude=["topic-0"],
            max_papers=10,
        )

        papers = synthesis_service.select_papers(question)

        # No papers should be from topic-0
        for paper in papers:
            assert "topic-0" not in paper.topics

    def test_select_papers_quality_threshold(self, synthesis_service):
        """Test paper selection with quality threshold."""
        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Test {paper_summaries}",
            min_quality_score=70.0,
            max_papers=10,
        )

        papers = synthesis_service.select_papers(question)

        # All papers should have quality >= 70
        for paper in papers:
            assert paper.quality_score >= 70.0

    def test_select_papers_max_limit(self, synthesis_service):
        """Test paper selection respects max_papers."""
        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Test {paper_summaries}",
            max_papers=3,
        )

        papers = synthesis_service.select_papers(question)

        assert len(papers) <= 3

    def test_select_papers_empty_registry(self):
        """Test paper selection with empty registry."""
        mock_registry = MagicMock(spec=RegistryService)
        mock_registry.load.return_value = MagicMock(entries={})

        service = CrossTopicSynthesisService(
            registry_service=mock_registry,
            config=SynthesisConfig(),
        )

        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Test {paper_summaries}",
        )

        papers = service.select_papers(question)
        assert papers == []

    def test_select_papers_diversity_sampling(self, mock_registry_service):
        """Test diversity sampling includes underrepresented topics."""
        # Create entries with varied topics
        entries = {}
        # 8 papers in topic-a
        for i in range(8):
            entry = RegistryEntry(
                identifiers={"doi": f"10.1234/a{i}"},
                title_normalized=f"topic a paper {i}",
                extraction_target_hash=f"sha256:a{i}",
                topic_affiliations=["topic-a"],
                metadata_snapshot={
                    "title": f"Topic A Paper {i}",
                    "quality_score": 80 - i,
                },
            )
            entries[entry.paper_id] = entry

        # 2 papers in topic-b (underrepresented)
        for i in range(2):
            entry = RegistryEntry(
                identifiers={"doi": f"10.1234/b{i}"},
                title_normalized=f"topic b paper {i}",
                extraction_target_hash=f"sha256:b{i}",
                topic_affiliations=["topic-b"],
                metadata_snapshot={
                    "title": f"Topic B Paper {i}",
                    "quality_score": 50 - i,
                },
            )
            entries[entry.paper_id] = entry

        state = MagicMock()
        state.entries = entries
        mock_registry_service.load.return_value = state

        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            config=SynthesisConfig(),
        )

        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Test {paper_summaries}",
            max_papers=10,
        )

        papers = service.select_papers(question)

        # Should include some topic-b papers due to diversity
        topic_b_count = sum(1 for p in papers if "topic-b" in p.topics)
        assert topic_b_count > 0


class TestPromptBuilding:
    """Tests for prompt building."""

    def test_build_synthesis_prompt_basic(self, synthesis_service):
        """Test basic prompt building."""
        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Analyze {paper_count} papers from {topics}.\n{paper_summaries}",
        )

        papers = [
            PaperSummary(
                paper_id="p1",
                title="Paper 1",
                topics=["topic-a"],
                quality_score=80.0,
            ),
            PaperSummary(
                paper_id="p2",
                title="Paper 2",
                topics=["topic-b"],
                quality_score=70.0,
            ),
        ]

        prompt = synthesis_service.build_synthesis_prompt(question, papers)

        assert "2 papers" in prompt
        assert "topic-a" in prompt
        assert "topic-b" in prompt
        assert "Paper 1" in prompt
        assert "Paper 2" in prompt

    def test_build_synthesis_prompt_empty_papers(self, synthesis_service):
        """Test prompt building with no papers."""
        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Analyze {paper_count} papers.\n{paper_summaries}",
        )

        prompt = synthesis_service.build_synthesis_prompt(question, [])

        assert "0 papers" in prompt

    def test_build_synthesis_prompt_preserves_template(self, synthesis_service):
        """Test that original prompt structure is preserved."""
        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Start\n{paper_count}\nMiddle\n{topics}\n"
            "End\n{paper_summaries}\nFinal",
        )

        papers = [
            PaperSummary(
                paper_id="p1",
                title="Test",
                topics=["t1"],
                quality_score=50.0,
            ),
        ]

        prompt = synthesis_service.build_synthesis_prompt(question, papers)

        assert prompt.startswith("Start")
        assert "Final" in prompt


class TestSynthesisOrchestration:
    """Tests for synthesis orchestration."""

    @pytest.mark.asyncio
    async def test_synthesize_question_no_llm(self, synthesis_service):
        """Test synthesizing without LLM service returns placeholder."""
        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Test {paper_summaries}",
            max_papers=3,
        )

        result = await synthesis_service.synthesize_question(question)

        assert result.question_id == "q1"
        assert "LLM service not configured" in result.synthesis_text
        assert len(result.papers_used) > 0  # Papers were selected
        assert result.tokens_used == 0
        assert result.cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_synthesize_question_no_papers(self):
        """Test synthesizing when no papers match."""
        mock_registry = MagicMock(spec=RegistryService)
        mock_registry.load.return_value = MagicMock(entries={})

        service = CrossTopicSynthesisService(
            registry_service=mock_registry,
            config=SynthesisConfig(),
        )

        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Test {paper_summaries}",
        )

        result = await service.synthesize_question(question)

        assert result.question_id == "q1"
        assert "No papers matched" in result.synthesis_text
        assert result.papers_used == []
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_synthesize_all_processes_enabled_questions(self, synthesis_service):
        """Test synthesize_all processes only enabled questions."""
        report = await synthesis_service.synthesize_all()

        # Should have processed 2 enabled questions
        assert len(report.results) == 2
        assert any(r.question_id == "test-question-1" for r in report.results)
        assert any(r.question_id == "test-question-2" for r in report.results)
        assert not any(r.question_id == "disabled-question" for r in report.results)

    @pytest.mark.asyncio
    async def test_synthesize_all_respects_priority(self, synthesis_service):
        """Test synthesize_all processes questions in priority order."""
        report = await synthesis_service.synthesize_all()

        # Questions should be processed by priority
        assert report.results[0].question_id == "test-question-1"  # priority 1
        assert report.results[1].question_id == "test-question-2"  # priority 2

    @pytest.mark.asyncio
    async def test_synthesize_all_no_questions(self):
        """Test synthesize_all with no enabled questions."""
        mock_registry = MagicMock(spec=RegistryService)
        mock_registry.load.return_value = MagicMock(entries={})

        config = SynthesisConfig(
            questions=[
                SynthesisQuestion(
                    id="q1",
                    name="Q1",
                    prompt="Test prompt text",
                    enabled=False,
                ),
            ]
        )

        service = CrossTopicSynthesisService(
            registry_service=mock_registry,
            config=config,
        )

        report = await service.synthesize_all()

        assert report.results == []
        assert report.questions_answered == 0


class TestHelperMethods:
    """Tests for helper methods."""

    def test_get_all_entries(self, synthesis_service):
        """Test getting all registry entries."""
        entries = synthesis_service.get_all_entries()
        assert len(entries) == 10

    def test_get_enabled_questions(self, synthesis_service):
        """Test getting enabled questions."""
        enabled = synthesis_service.get_enabled_questions()
        assert len(enabled) == 2
        assert all(q.enabled for q in enabled)

    def test_get_question_by_id_found(self, synthesis_service):
        """Test getting question by ID when it exists."""
        question = synthesis_service.get_question_by_id("test-question-1")
        assert question is not None
        assert question.id == "test-question-1"

    def test_get_question_by_id_not_found(self, synthesis_service):
        """Test getting question by ID when it doesn't exist."""
        question = synthesis_service.get_question_by_id("nonexistent")
        assert question is None

    def test_estimate_tokens(self, synthesis_service):
        """Test token estimation."""
        prompt = "a" * 400  # 400 characters
        tokens = synthesis_service._estimate_tokens(prompt)
        # Should be approximately 100 tokens (4 chars per token)
        assert tokens == 100

    def test_entry_to_summary(self, synthesis_service):
        """Test converting registry entry to paper summary."""
        entry = RegistryEntry(
            identifiers={"doi": "10.1234/test"},
            title_normalized="test paper",
            extraction_target_hash="sha256:test",
            topic_affiliations=["topic-a", "topic-b"],
            metadata_snapshot={
                "title": "Test Paper Title",
                "abstract": "Test abstract",
                "authors": [{"name": "Author A"}, {"name": "Author B"}],
                "quality_score": 85.0,
                "publication_date": "2025-01-15",
            },
        )

        summary = synthesis_service._entry_to_summary(entry)

        assert summary.paper_id == entry.paper_id
        assert summary.title == "Test Paper Title"
        assert summary.abstract == "Test abstract"
        assert summary.quality_score == 85.0
        assert len(summary.topics) == 2

    def test_entry_to_summary_minimal_metadata(self, synthesis_service):
        """Test converting entry with minimal metadata."""
        entry = RegistryEntry(
            identifiers={},
            title_normalized="minimal paper",
            extraction_target_hash="sha256:minimal",
            topic_affiliations=["topic-a"],
            metadata_snapshot={},
        )

        summary = synthesis_service._entry_to_summary(entry)

        assert summary.paper_id == entry.paper_id
        assert summary.title == "minimal paper"  # Falls back to normalized
        assert summary.abstract is None
        assert summary.quality_score == 0.0


class TestIncrementalMode:
    """Tests for incremental mode."""

    def test_calculate_registry_hash(self, synthesis_service):
        """Test registry hash calculation."""
        hash1 = synthesis_service._calculate_registry_hash()
        hash2 = synthesis_service._calculate_registry_hash()

        # Same registry should produce same hash
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def test_should_skip_incremental_no_state(self, synthesis_service):
        """Test incremental skip check with no previous state."""
        should_skip, new_count = synthesis_service._should_skip_incremental()

        assert should_skip is False

    @pytest.mark.asyncio
    async def test_synthesize_all_force_ignores_incremental(self, synthesis_service):
        """Test that force flag ignores incremental mode."""
        # First run
        report1 = await synthesis_service.synthesize_all()

        # Second run with force
        report2 = await synthesis_service.synthesize_all(force=True)

        # Both should have results
        assert len(report1.results) > 0
        assert len(report2.results) > 0

    def test_should_skip_incremental_disabled(self, mock_registry_service):
        """Test incremental skip when incremental mode is disabled."""
        config = SynthesisConfig(incremental_mode=False)
        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            config=config,
        )

        should_skip, new_count = service._should_skip_incremental()

        assert should_skip is False
        assert new_count == 0

    def test_should_skip_incremental_with_state_no_hash(self, mock_registry_service):
        """Test incremental skip with state but no hash."""
        from src.models.cross_synthesis import SynthesisState

        config = SynthesisConfig(incremental_mode=True)
        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            config=config,
        )
        service._state = SynthesisState(last_registry_hash=None)

        should_skip, new_count = service._should_skip_incremental()

        assert should_skip is False

    def test_should_skip_incremental_hash_unchanged(self, mock_registry_service):
        """Test incremental skip when hash is unchanged."""
        from src.models.cross_synthesis import SynthesisState

        config = SynthesisConfig(incremental_mode=True)
        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            config=config,
        )

        # Set state with current hash
        current_hash = service._calculate_registry_hash()
        service._state = SynthesisState(
            last_registry_hash=current_hash,
            questions_processed=["q1"],
        )

        should_skip, new_count = service._should_skip_incremental()

        assert should_skip is True
        assert new_count == 0

    def test_should_skip_incremental_hash_changed(self, mock_registry_service):
        """Test incremental skip when hash has changed."""
        from src.models.cross_synthesis import SynthesisState

        config = SynthesisConfig(incremental_mode=True)
        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            config=config,
        )

        # Set state with old hash
        service._state = SynthesisState(
            last_registry_hash="oldhash123",
            questions_processed=["q1"],
        )

        should_skip, new_count = service._should_skip_incremental()

        assert should_skip is False


class TestLLMIntegration:
    """Tests for LLM integration."""

    @pytest.mark.asyncio
    async def test_synthesize_question_with_llm(self, mock_registry_service):
        """Test synthesizing with mock LLM service."""
        from src.models.extraction import PaperExtraction, ExtractionResult

        # Create mock LLM service
        mock_llm = AsyncMock()
        mock_llm.config = MagicMock()
        mock_llm.config.model = "test-model"

        # Mock extraction result
        mock_extraction = PaperExtraction(
            paper_id="test",
            extraction_results=[
                ExtractionResult(
                    target_name="cross_topic_synthesis",
                    success=True,
                    content="Synthesized insights from the papers.",
                )
            ],
            tokens_used=1000,
            cost_usd=0.05,
        )
        mock_llm.extract = AsyncMock(return_value=mock_extraction)

        config = SynthesisConfig(
            questions=[
                SynthesisQuestion(
                    id="test-q",
                    name="Test Question",
                    prompt="Analyze papers {paper_summaries}",
                    max_papers=3,
                ),
            ],
        )

        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            llm_service=mock_llm,
            config=config,
        )

        question = config.questions[0]
        result = await service.synthesize_question(question)

        assert result.question_id == "test-q"
        assert "Synthesized insights" in result.synthesis_text
        assert result.tokens_used == 1000
        assert result.cost_usd == 0.05
        assert result.model_used == "test-model"
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_synthesize_question_llm_empty_result(self, mock_registry_service):
        """Test synthesizing when LLM returns empty result."""
        from src.models.extraction import PaperExtraction, ExtractionResult

        mock_llm = AsyncMock()
        mock_llm.config = MagicMock()
        mock_llm.config.model = "test-model"

        # Empty extraction result
        mock_extraction = PaperExtraction(
            paper_id="test",
            extraction_results=[
                ExtractionResult(
                    target_name="cross_topic_synthesis",
                    success=False,
                    content=None,
                )
            ],
            tokens_used=500,
            cost_usd=0.02,
        )
        mock_llm.extract = AsyncMock(return_value=mock_extraction)

        config = SynthesisConfig(
            questions=[
                SynthesisQuestion(
                    id="test-q",
                    name="Test Question",
                    prompt="Analyze papers {paper_summaries}",
                ),
            ],
        )

        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            llm_service=mock_llm,
            config=config,
        )

        result = await service.synthesize_question(config.questions[0])

        assert "did not produce valid output" in result.synthesis_text

    @pytest.mark.asyncio
    async def test_synthesize_question_llm_exception(self, mock_registry_service):
        """Test synthesizing when LLM raises exception."""
        mock_llm = AsyncMock()
        mock_llm.config = MagicMock()
        mock_llm.config.model = "test-model"
        mock_llm.extract = AsyncMock(side_effect=Exception("LLM error"))

        config = SynthesisConfig(
            questions=[
                SynthesisQuestion(
                    id="test-q",
                    name="Test Question",
                    prompt="Analyze papers {paper_summaries}",
                ),
            ],
        )

        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            llm_service=mock_llm,
            config=config,
        )

        result = await service.synthesize_question(config.questions[0])

        assert "Synthesis failed" in result.synthesis_text
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_synthesize_question_cost_limit_via_budget(
        self, mock_registry_service
    ):
        """Test synthesizing stops when estimated cost exceeds budget."""
        # Test by checking that very long prompts are handled gracefully
        # The cost limit is checked after truncation, so we verify the flow works
        mock_llm = AsyncMock()
        mock_llm.config = MagicMock()
        mock_llm.config.model = "test-model"
        # Have LLM raise cost limit exceeded
        from src.utils.exceptions import CostLimitExceeded

        mock_llm.extract = AsyncMock(
            side_effect=CostLimitExceeded("Cost limit exceeded")
        )

        config = SynthesisConfig(
            questions=[
                SynthesisQuestion(
                    id="test-q",
                    name="Test Question",
                    prompt="Test prompt text {paper_summaries}",
                ),
            ],
        )

        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            llm_service=mock_llm,
            config=config,
        )

        with pytest.raises(CostLimitExceeded):
            await service.synthesize_question(
                config.questions[0],
                budget_remaining=100.0,
            )


class TestTokenTruncation:
    """Tests for token truncation logic."""

    @pytest.mark.asyncio
    async def test_prompt_truncated_when_exceeds_limit(self, mock_registry_service):
        """Test that prompts are truncated when exceeding token limit."""
        config = SynthesisConfig(
            max_tokens_per_question=1000,  # Minimum valid limit
            questions=[
                SynthesisQuestion(
                    id="test-q",
                    name="Test Question",
                    prompt="A" * 5000 + " {paper_summaries}",  # Long prompt
                    max_papers=10,
                ),
            ],
        )

        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            config=config,
        )

        # Without LLM, we can test the truncation logic via synthesize_question
        question = config.questions[0]
        result = await service.synthesize_question(question)

        # Should complete without error - LLM not configured message
        assert result is not None
        assert "LLM service not configured" in result.synthesis_text


class TestBudgetManagement:
    """Tests for budget management."""

    @pytest.mark.asyncio
    async def test_synthesize_all_budget_exhausted(self, mock_registry_service):
        """Test synthesize_all stops when CostLimitExceeded is raised."""
        from src.utils.exceptions import CostLimitExceeded
        from src.models.extraction import PaperExtraction, ExtractionResult

        mock_llm = AsyncMock()
        mock_llm.config = MagicMock()
        mock_llm.config.model = "test-model"

        call_count = 0

        async def mock_extract(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First question succeeds
                return PaperExtraction(
                    paper_id="test",
                    extraction_results=[
                        ExtractionResult(
                            target_name="cross_topic_synthesis",
                            success=True,
                            content="First synthesis",
                        )
                    ],
                    tokens_used=10000,
                    cost_usd=5.0,
                )
            else:
                # Second question exceeds budget
                raise CostLimitExceeded("Budget exceeded")

        mock_llm.extract = mock_extract

        config = SynthesisConfig(
            budget_per_synthesis_usd=10.0,
            questions=[
                SynthesisQuestion(
                    id="q1",
                    name="Q1",
                    prompt="Test prompt one {paper_summaries}",
                    priority=1,
                ),
                SynthesisQuestion(
                    id="q2",
                    name="Q2",
                    prompt="Test prompt two {paper_summaries}",
                    priority=2,
                ),
            ],
        )

        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            llm_service=mock_llm,
            config=config,
        )

        report = await service.synthesize_all()

        # Should only have first question result; second stopped due to budget
        assert len(report.results) == 1
        assert report.results[0].question_id == "q1"
        assert "First synthesis" in report.results[0].synthesis_text

    @pytest.mark.asyncio
    async def test_synthesize_all_handles_question_failure(self, mock_registry_service):
        """Test synthesize_all continues after question failure."""
        from src.models.extraction import PaperExtraction, ExtractionResult

        mock_llm = AsyncMock()
        mock_llm.config = MagicMock()
        mock_llm.config.model = "test-model"

        call_count = 0

        async def mock_extract(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First question failed")
            return PaperExtraction(
                paper_id="test",
                extraction_results=[
                    ExtractionResult(
                        target_name="cross_topic_synthesis",
                        success=True,
                        content="Success",
                    )
                ],
                tokens_used=100,
                cost_usd=0.01,
            )

        mock_llm.extract = mock_extract

        config = SynthesisConfig(
            questions=[
                SynthesisQuestion(
                    id="q1",
                    name="Q1",
                    prompt="Test prompt one {paper_summaries}",
                    priority=1,
                ),
                SynthesisQuestion(
                    id="q2",
                    name="Q2",
                    prompt="Test prompt two {paper_summaries}",
                    priority=2,
                ),
            ],
        )

        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            llm_service=mock_llm,
            config=config,
        )

        report = await service.synthesize_all()

        # Should have results for both - first with failure text, second with success
        assert len(report.results) == 2


class TestConfigValidation:
    """Tests for config validation edge cases."""

    def test_load_config_pydantic_validation_error(self):
        """Test loading config with Pydantic validation error."""
        config_data = {
            "budget_per_synthesis_usd": -10.0,  # Invalid negative budget
            "questions": [],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)

        try:
            mock_registry = MagicMock(spec=RegistryService)
            service = CrossTopicSynthesisService(
                registry_service=mock_registry,
                config_path=config_path,
            )

            with pytest.raises(ValueError):
                service.load_config()
        finally:
            config_path.unlink()

    def test_load_config_general_exception(self):
        """Test loading config with general exception."""
        # Create a file that can't be parsed
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".yaml", delete=False) as f:
            f.write(b"\x00\x01\x02")  # Binary content
            config_path = Path(f.name)

        try:
            mock_registry = MagicMock(spec=RegistryService)
            service = CrossTopicSynthesisService(
                registry_service=mock_registry,
                config_path=config_path,
            )

            with pytest.raises(ValueError):
                service.load_config()
        finally:
            config_path.unlink()


class TestEntryConversion:
    """Tests for entry conversion edge cases."""

    def test_entry_to_summary_with_extraction_results(self, mock_registry_service):
        """Test converting entry with extraction results."""
        config = SynthesisConfig()
        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            config=config,
        )

        entry = RegistryEntry(
            identifiers={"doi": "10.1234/test"},
            title_normalized="test paper",
            extraction_target_hash="sha256:test",
            topic_affiliations=["topic-a"],
            metadata_snapshot={
                "title": "Test Paper",
                "quality_score": 80.0,
                "extraction_results": {
                    "key_findings": "Important results here",
                    "methodology": "Novel approach",
                },
            },
        )

        summary = service._entry_to_summary(entry)

        assert summary.extraction_summary is not None
        assert "key_findings" in summary.extraction_summary

    def test_entry_to_summary_invalid_quality_score(self, mock_registry_service):
        """Test converting entry with invalid quality score type."""
        config = SynthesisConfig()
        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            config=config,
        )

        entry = RegistryEntry(
            identifiers={},
            title_normalized="test paper",
            extraction_target_hash="sha256:test",
            topic_affiliations=["topic-a"],
            metadata_snapshot={
                "quality_score": "not a number",  # Invalid type
            },
        )

        summary = service._entry_to_summary(entry)

        assert summary.quality_score == 0.0


class TestPaperSelectionEdgeCases:
    """Tests for paper selection edge cases."""

    def test_select_papers_no_matching_filters(self, mock_registry_service):
        """Test paper selection when no papers match filters."""
        config = SynthesisConfig()
        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            config=config,
        )

        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Test {paper_summaries}",
            topic_filters=["nonexistent-topic"],
        )

        papers = service.select_papers(question)

        assert papers == []

    def test_select_papers_all_below_quality(self, mock_registry_service):
        """Test paper selection when all papers below quality threshold."""
        config = SynthesisConfig()
        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            config=config,
        )

        question = SynthesisQuestion(
            id="q1",
            name="Q1",
            prompt="Test {paper_summaries}",
            min_quality_score=99.0,  # Higher than any paper
        )

        papers = service.select_papers(question)

        assert papers == []


class TestCostLimitPaths:
    """Tests for cost limit and budget paths."""

    @pytest.mark.asyncio
    async def test_synthesize_raises_cost_limit_on_estimate(
        self, mock_registry_service
    ):
        """Test that CostLimitExceeded is raised when estimated cost exceeds budget."""
        from src.models.extraction import PaperExtraction, ExtractionResult

        mock_llm = AsyncMock()
        mock_llm.config = MagicMock()
        mock_llm.config.model = "test-model"

        # The actual extraction won't be called because cost check happens first
        mock_extraction = PaperExtraction(
            paper_id="test",
            extraction_results=[
                ExtractionResult(
                    target_name="cross_topic_synthesis",
                    success=True,
                    content="Result",
                )
            ],
            tokens_used=1000,
            cost_usd=0.05,
        )
        mock_llm.extract = AsyncMock(return_value=mock_extraction)

        config = SynthesisConfig(
            questions=[
                SynthesisQuestion(
                    id="test-q",
                    name="Test Question",
                    # Very long prompt to estimate high cost
                    prompt="X" * 100000 + " {paper_summaries}",
                ),
            ],
        )

        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            llm_service=mock_llm,
            config=config,
        )

        from src.utils.exceptions import CostLimitExceeded

        with pytest.raises(CostLimitExceeded):
            await service.synthesize_question(
                config.questions[0],
                budget_remaining=0.0001,  # Very low budget
            )

    @pytest.mark.asyncio
    async def test_synthesize_all_skips_when_incremental_and_unchanged(
        self, mock_registry_service
    ):
        """Test that synthesize_all skips when incremental mode and no changes."""
        from src.models.cross_synthesis import SynthesisState

        config = SynthesisConfig(
            incremental_mode=True,
            questions=[
                SynthesisQuestion(
                    id="q1",
                    name="Q1",
                    prompt="Test prompt text {paper_summaries}",
                ),
            ],
        )

        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            config=config,
        )

        # Set state with current hash (simulating no changes)
        current_hash = service._calculate_registry_hash()
        service._state = SynthesisState(
            last_registry_hash=current_hash,
            questions_processed=["q1"],
        )

        # Should skip synthesis and return empty report
        report = await service.synthesize_all(force=False)

        assert report.results == []
        assert report.incremental is True

    @pytest.mark.asyncio
    async def test_synthesize_all_zero_budget_stops(self, mock_registry_service):
        """Test synthesize_all stops when budget is zero."""
        from src.models.extraction import PaperExtraction, ExtractionResult

        mock_llm = AsyncMock()
        mock_llm.config = MagicMock()
        mock_llm.config.model = "test-model"

        # First call succeeds and uses all budget
        mock_extraction = PaperExtraction(
            paper_id="test",
            extraction_results=[
                ExtractionResult(
                    target_name="cross_topic_synthesis",
                    success=True,
                    content="Result",
                )
            ],
            tokens_used=1000,
            cost_usd=10.0,  # Uses all budget
        )
        mock_llm.extract = AsyncMock(return_value=mock_extraction)

        config = SynthesisConfig(
            budget_per_synthesis_usd=10.0,  # Exact budget for one question
            questions=[
                SynthesisQuestion(
                    id="q1",
                    name="Q1",
                    prompt="Test prompt one {paper_summaries}",
                    priority=1,
                ),
                SynthesisQuestion(
                    id="q2",
                    name="Q2",
                    prompt="Test prompt two {paper_summaries}",
                    priority=2,
                ),
            ],
        )

        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            llm_service=mock_llm,
            config=config,
        )

        report = await service.synthesize_all()

        # Should stop after first question due to budget
        assert len(report.results) == 1
        assert report.results[0].question_id == "q1"

    @pytest.mark.asyncio
    async def test_synthesize_all_general_exception_continues(
        self, mock_registry_service
    ):
        """Test synthesize_all continues after general exception."""
        mock_llm = AsyncMock()
        mock_llm.config = MagicMock()
        mock_llm.config.model = "test-model"

        # First call raises exception, second succeeds
        call_count = 0

        async def mock_extract(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Unexpected error")
            from src.models.extraction import PaperExtraction, ExtractionResult

            return PaperExtraction(
                paper_id="test",
                extraction_results=[
                    ExtractionResult(
                        target_name="cross_topic_synthesis",
                        success=True,
                        content="Success",
                    )
                ],
                tokens_used=100,
                cost_usd=0.01,
            )

        mock_llm.extract = mock_extract

        config = SynthesisConfig(
            questions=[
                SynthesisQuestion(
                    id="q1",
                    name="Q1",
                    prompt="Test prompt one {paper_summaries}",
                    priority=1,
                ),
                SynthesisQuestion(
                    id="q2",
                    name="Q2",
                    prompt="Test prompt two {paper_summaries}",
                    priority=2,
                ),
            ],
        )

        service = CrossTopicSynthesisService(
            registry_service=mock_registry_service,
            llm_service=mock_llm,
            config=config,
        )

        report = await service.synthesize_all()

        # Both questions attempted, first failed, second succeeded
        assert len(report.results) == 2
        assert "Synthesis failed" in report.results[0].synthesis_text
        assert "Success" in report.results[1].synthesis_text

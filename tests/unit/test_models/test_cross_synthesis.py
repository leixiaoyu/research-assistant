"""Unit tests for Phase 3.7 cross-synthesis data models.

Tests:
- SynthesisQuestion validation
- SynthesisResult creation
- CrossTopicSynthesisReport properties
- SynthesisConfig validation
- PaperSummary formatting
- SynthesisState tracking
"""

import pytest
from datetime import datetime, timezone

from src.models.cross_synthesis import (
    SynthesisQuestion,
    SynthesisResult,
    CrossTopicSynthesisReport,
    SynthesisConfig,
    PaperSummary,
    SynthesisState,
)


class TestSynthesisQuestion:
    """Tests for SynthesisQuestion model."""

    def test_valid_question_creation(self):
        """Test creating a valid synthesis question."""
        question = SynthesisQuestion(
            id="test-question",
            name="Test Question",
            prompt="Analyze {paper_count} papers from {topics}.\n{paper_summaries}",
        )

        assert question.id == "test-question"
        assert question.name == "Test Question"
        assert "{paper_count}" in question.prompt
        assert question.topic_filters == []
        assert question.topic_exclude == []
        assert question.max_papers == 50
        assert question.min_quality_score == 0.0
        assert question.priority == 1
        assert question.enabled is True

    def test_question_with_all_fields(self):
        """Test creating a question with all optional fields."""
        question = SynthesisQuestion(
            id="full-question",
            name="Full Question",
            prompt="Test prompt {paper_summaries}",
            topic_filters=["topic-a", "topic-b"],
            topic_exclude=["topic-c"],
            max_papers=100,
            min_quality_score=50.0,
            priority=2,
            enabled=False,
        )

        assert question.topic_filters == ["topic-a", "topic-b"]
        assert question.topic_exclude == ["topic-c"]
        assert question.max_papers == 100
        assert question.min_quality_score == 50.0
        assert question.priority == 2
        assert question.enabled is False

    def test_question_id_validation_valid(self):
        """Test valid question IDs."""
        valid_ids = ["a", "ab", "test-question", "a1", "test123", "a-b-c"]
        for valid_id in valid_ids:
            question = SynthesisQuestion(
                id=valid_id,
                name="Test",
                prompt="Test prompt text",
            )
            assert question.id == valid_id

    def test_question_id_validation_invalid(self):
        """Test invalid question IDs are rejected."""
        invalid_ids = ["-test", "test-", "Test", "test_question", "test question"]
        for invalid_id in invalid_ids:
            with pytest.raises(ValueError):
                SynthesisQuestion(
                    id=invalid_id,
                    name="Test",
                    prompt="Test prompt text",
                )

    def test_question_prompt_script_injection_blocked(self):
        """Test that script tags are blocked in prompts."""
        with pytest.raises(ValueError, match="Script tags"):
            SynthesisQuestion(
                id="test",
                name="Test",
                prompt="<script>alert('xss')</script> {paper_summaries}",
            )

    def test_question_max_papers_bounds(self):
        """Test max_papers validation bounds."""
        # Valid bounds
        q1 = SynthesisQuestion(
            id="q1", name="Q1", prompt="Test prompt text", max_papers=1
        )
        assert q1.max_papers == 1

        q2 = SynthesisQuestion(
            id="q2", name="Q2", prompt="Test prompt text", max_papers=200
        )
        assert q2.max_papers == 200

        # Invalid bounds
        with pytest.raises(ValueError):
            SynthesisQuestion(id="q", name="Q", prompt="Test prompt text", max_papers=0)

        with pytest.raises(ValueError):
            SynthesisQuestion(
                id="q", name="Q", prompt="Test prompt text", max_papers=201
            )

    def test_question_quality_score_bounds(self):
        """Test min_quality_score validation bounds."""
        q1 = SynthesisQuestion(
            id="q1", name="Q1", prompt="Test prompt text", min_quality_score=0.0
        )
        assert q1.min_quality_score == 0.0

        q2 = SynthesisQuestion(
            id="q2", name="Q2", prompt="Test prompt text", min_quality_score=100.0
        )
        assert q2.min_quality_score == 100.0

        with pytest.raises(ValueError):
            SynthesisQuestion(
                id="q", name="Q", prompt="Test prompt text", min_quality_score=-1.0
            )

        with pytest.raises(ValueError):
            SynthesisQuestion(
                id="q", name="Q", prompt="Test prompt text", min_quality_score=101.0
            )


class TestSynthesisResult:
    """Tests for SynthesisResult model."""

    def test_result_creation(self):
        """Test creating a synthesis result."""
        result = SynthesisResult(
            question_id="test-q",
            question_name="Test Question",
            synthesis_text="This is the synthesis output.",
        )

        assert result.question_id == "test-q"
        assert result.question_name == "Test Question"
        assert result.synthesis_text == "This is the synthesis output."
        assert result.papers_used == []
        assert result.topics_covered == []
        assert result.tokens_used == 0
        assert result.cost_usd == 0.0
        assert result.model_used == ""
        assert result.confidence == 0.5

    def test_result_with_all_fields(self):
        """Test creating a result with all fields."""
        now = datetime.now(timezone.utc)
        result = SynthesisResult(
            question_id="full-q",
            question_name="Full Question",
            synthesis_text="Full synthesis output.",
            papers_used=["paper1", "paper2", "paper3"],
            topics_covered=["topic-a", "topic-b"],
            tokens_used=5000,
            cost_usd=0.15,
            synthesized_at=now,
            model_used="claude-3-5-sonnet",
            confidence=0.85,
        )

        assert len(result.papers_used) == 3
        assert len(result.topics_covered) == 2
        assert result.tokens_used == 5000
        assert result.cost_usd == 0.15
        assert result.synthesized_at == now
        assert result.model_used == "claude-3-5-sonnet"
        assert result.confidence == 0.85

    def test_result_confidence_bounds(self):
        """Test confidence score bounds."""
        # Valid bounds
        r1 = SynthesisResult(
            question_id="q", question_name="Q", synthesis_text="T", confidence=0.0
        )
        assert r1.confidence == 0.0

        r2 = SynthesisResult(
            question_id="q", question_name="Q", synthesis_text="T", confidence=1.0
        )
        assert r2.confidence == 1.0

        # Invalid bounds
        with pytest.raises(ValueError):
            SynthesisResult(
                question_id="q", question_name="Q", synthesis_text="T", confidence=-0.1
            )

        with pytest.raises(ValueError):
            SynthesisResult(
                question_id="q", question_name="Q", synthesis_text="T", confidence=1.1
            )


class TestCrossTopicSynthesisReport:
    """Tests for CrossTopicSynthesisReport model."""

    def test_report_creation(self):
        """Test creating a synthesis report."""
        report = CrossTopicSynthesisReport(
            report_id="syn-20250216-123456",
            total_papers_in_registry=100,
        )

        assert report.report_id == "syn-20250216-123456"
        assert report.total_papers_in_registry == 100
        assert report.results == []
        assert report.total_tokens_used == 0
        assert report.total_cost_usd == 0.0
        assert report.incremental is False
        assert report.new_papers_since_last == 0
        assert report.questions_answered == 0

    def test_report_questions_answered_property(self):
        """Test questions_answered property."""
        result1 = SynthesisResult(
            question_id="q1", question_name="Q1", synthesis_text="T1"
        )
        result2 = SynthesisResult(
            question_id="q2", question_name="Q2", synthesis_text="T2"
        )

        report = CrossTopicSynthesisReport(
            report_id="test",
            total_papers_in_registry=50,
            results=[result1, result2],
        )

        assert report.questions_answered == 2

    def test_report_with_full_data(self):
        """Test report with complete data."""
        now = datetime.now(timezone.utc)
        results = [
            SynthesisResult(
                question_id="q1",
                question_name="Q1",
                synthesis_text="S1",
                tokens_used=1000,
                cost_usd=0.05,
            ),
            SynthesisResult(
                question_id="q2",
                question_name="Q2",
                synthesis_text="S2",
                tokens_used=2000,
                cost_usd=0.10,
            ),
        ]

        report = CrossTopicSynthesisReport(
            report_id="full-report",
            created_at=now,
            updated_at=now,
            total_papers_in_registry=200,
            results=results,
            total_tokens_used=3000,
            total_cost_usd=0.15,
            incremental=True,
            new_papers_since_last=25,
        )

        assert report.questions_answered == 2
        assert report.total_tokens_used == 3000
        assert report.total_cost_usd == 0.15
        assert report.incremental is True
        assert report.new_papers_since_last == 25


class TestSynthesisConfig:
    """Tests for SynthesisConfig model."""

    def test_config_defaults(self):
        """Test config with default values."""
        config = SynthesisConfig()

        assert config.questions == []
        assert config.budget_per_synthesis_usd == 15.0
        assert config.max_tokens_per_question == 100000
        assert config.output_path == "output/Global_Synthesis.md"
        assert config.cache_synthesis_results is True
        assert config.incremental_mode is True

    def test_config_with_questions(self):
        """Test config with questions."""
        questions = [
            SynthesisQuestion(
                id="q1",
                name="Q1",
                prompt="Prompt 1 {paper_summaries}",
            ),
            SynthesisQuestion(
                id="q2",
                name="Q2",
                prompt="Prompt 2 {paper_summaries}",
            ),
        ]

        config = SynthesisConfig(
            questions=questions,
            budget_per_synthesis_usd=10.0,
            max_tokens_per_question=50000,
        )

        assert len(config.questions) == 2
        assert config.budget_per_synthesis_usd == 10.0
        assert config.max_tokens_per_question == 50000

    def test_config_output_path_traversal_blocked(self):
        """Test that path traversal is blocked."""
        with pytest.raises(ValueError, match="Path traversal"):
            SynthesisConfig(output_path="../../../etc/passwd")

        with pytest.raises(ValueError, match="Path traversal"):
            SynthesisConfig(output_path="output/../sensitive.md")

    def test_config_budget_bounds(self):
        """Test budget validation bounds."""
        # Valid bounds
        c1 = SynthesisConfig(budget_per_synthesis_usd=0.0)
        assert c1.budget_per_synthesis_usd == 0.0

        c2 = SynthesisConfig(budget_per_synthesis_usd=100.0)
        assert c2.budget_per_synthesis_usd == 100.0

        # Invalid bounds
        with pytest.raises(ValueError):
            SynthesisConfig(budget_per_synthesis_usd=-1.0)

        with pytest.raises(ValueError):
            SynthesisConfig(budget_per_synthesis_usd=101.0)

    def test_config_tokens_bounds(self):
        """Test max_tokens_per_question bounds."""
        c1 = SynthesisConfig(max_tokens_per_question=1000)
        assert c1.max_tokens_per_question == 1000

        c2 = SynthesisConfig(max_tokens_per_question=1000000)
        assert c2.max_tokens_per_question == 1000000

        with pytest.raises(ValueError):
            SynthesisConfig(max_tokens_per_question=999)

        with pytest.raises(ValueError):
            SynthesisConfig(max_tokens_per_question=1000001)


class TestPaperSummary:
    """Tests for PaperSummary model."""

    def test_summary_creation(self):
        """Test creating a paper summary."""
        summary = PaperSummary(
            paper_id="paper-123",
            title="Test Paper Title",
        )

        assert summary.paper_id == "paper-123"
        assert summary.title == "Test Paper Title"
        assert summary.authors == []
        assert summary.abstract is None
        assert summary.publication_date is None
        assert summary.quality_score == 0.0
        assert summary.topics == []
        assert summary.extraction_summary is None

    def test_summary_with_all_fields(self):
        """Test summary with all fields."""
        summary = PaperSummary(
            paper_id="full-paper",
            title="Full Paper Title",
            authors=["Author A", "Author B"],
            abstract="This is the abstract.",
            publication_date="2025-01-15",
            quality_score=85.0,
            topics=["topic-a", "topic-b"],
            extraction_summary={"key_finding": "Important result"},
        )

        assert len(summary.authors) == 2
        assert summary.abstract == "This is the abstract."
        assert summary.publication_date == "2025-01-15"
        assert summary.quality_score == 85.0
        assert len(summary.topics) == 2
        assert "key_finding" in summary.extraction_summary

    def test_summary_to_prompt_format(self):
        """Test formatting summary for prompt."""
        summary = PaperSummary(
            paper_id="paper-123",
            title="Attention Is All You Need",
            authors=["Vaswani", "Shazeer", "Parmar"],
            abstract="We propose a new architecture.",
            publication_date="2017-06-12",
            quality_score=95.0,
            topics=["transformers", "nlp"],
        )

        formatted = summary.to_prompt_format()

        assert "### Attention Is All You Need" in formatted
        assert "paper-123" in formatted
        assert "Vaswani" in formatted
        assert "2017-06-12" in formatted
        assert "95/100" in formatted
        assert "transformers" in formatted

    def test_summary_prompt_format_truncates_long_abstract(self):
        """Test that long abstracts are truncated."""
        long_abstract = "A" * 600
        summary = PaperSummary(
            paper_id="p1",
            title="Test",
            abstract=long_abstract,
        )

        formatted = summary.to_prompt_format()
        assert "..." in formatted
        assert len(formatted) < len(long_abstract) + 200

    def test_summary_prompt_format_truncates_authors(self):
        """Test that many authors are truncated."""
        many_authors = [f"Author {i}" for i in range(10)]
        summary = PaperSummary(
            paper_id="p1",
            title="Test",
            authors=many_authors,
        )

        formatted = summary.to_prompt_format()
        assert "...and 5 more" in formatted

    def test_summary_quality_score_bounds(self):
        """Test quality score bounds."""
        s1 = PaperSummary(paper_id="p1", title="T", quality_score=0.0)
        assert s1.quality_score == 0.0

        s2 = PaperSummary(paper_id="p2", title="T", quality_score=100.0)
        assert s2.quality_score == 100.0

        with pytest.raises(ValueError):
            PaperSummary(paper_id="p", title="T", quality_score=-1.0)

        with pytest.raises(ValueError):
            PaperSummary(paper_id="p", title="T", quality_score=101.0)


class TestSynthesisState:
    """Tests for SynthesisState model."""

    def test_state_defaults(self):
        """Test state with default values."""
        state = SynthesisState()

        assert state.last_synthesis_at is None
        assert state.last_registry_hash is None
        assert state.last_report_id is None
        assert state.questions_processed == []

    def test_state_with_data(self):
        """Test state with all fields."""
        now = datetime.now(timezone.utc)
        state = SynthesisState(
            last_synthesis_at=now,
            last_registry_hash="sha256:abc123",
            last_report_id="syn-123",
            questions_processed=["q1", "q2"],
        )

        assert state.last_synthesis_at == now
        assert state.last_registry_hash == "sha256:abc123"
        assert state.last_report_id == "syn-123"
        assert len(state.questions_processed) == 2

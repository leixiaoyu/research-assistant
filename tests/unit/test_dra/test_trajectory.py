"""Unit tests for Phase 8 DRA trajectory learning."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models.dra import (
    ResearchResult,
    ToolCallType,
    TrajectoryInsights,
    TrajectoryRecord,
    Turn,
    ToolCall,
)
from src.services.dra.trajectory import (
    ExpertSeedTrajectory,
    TrajectoryCollector,
    DEFAULT_EXPERT_SEEDS,
)


class TestExpertSeedTrajectory:
    """Tests for ExpertSeedTrajectory model."""

    def test_basic_creation(self):
        """Test basic expert seed trajectory creation."""
        from datetime import datetime, UTC

        turns = [
            Turn(
                turn_number=1,
                reasoning="Test reasoning",
                action=ToolCall(
                    tool=ToolCallType.SEARCH,
                    arguments={"query": "test"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Test obs",
                observation_tokens=10,
            )
        ]

        seed = ExpertSeedTrajectory(
            seed_id="test_seed",
            name="Test Seed",
            description="A test expert trajectory",
            question="Test question",
            turns=turns,
            key_patterns=["pattern1", "pattern2"],
            created_by="test_user",
        )

        assert seed.seed_id == "test_seed"
        assert seed.name == "Test Seed"
        assert seed.quality_score == 1.0  # Always 1.0 for experts
        assert len(seed.turns) == 1
        assert len(seed.key_patterns) == 2
        assert seed.created_by == "test_user"
        assert isinstance(seed.created_at, datetime)

    def test_to_trajectory_record(self):
        """Test converting expert seed to trajectory record."""
        turns = [
            Turn(
                turn_number=1,
                reasoning="Search for papers",
                action=ToolCall(
                    tool=ToolCallType.SEARCH,
                    arguments={"query": "transformers"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Found papers",
                observation_tokens=50,
            ),
            Turn(
                turn_number=2,
                reasoning="Open a paper",
                action=ToolCall(
                    tool=ToolCallType.OPEN,
                    arguments={"paper_id": "paper1"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Opened paper",
                observation_tokens=100,
            ),
            Turn(
                turn_number=3,
                reasoning="Find specific info",
                action=ToolCall(
                    tool=ToolCallType.FIND,
                    arguments={"pattern": "accuracy"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Found matches",
                observation_tokens=30,
            ),
        ]

        seed = ExpertSeedTrajectory(
            seed_id="test_seed",
            name="Test",
            description="Test desc",
            question="Test question",
            turns=turns,
            created_by="expert",
        )

        record = seed.to_trajectory_record()

        assert record.trajectory_id == "expert_seed_test_seed"
        assert record.question == "Test question"
        assert record.quality_score == 1.0
        assert len(record.turns) == 3
        assert record.papers_opened == 1  # One OPEN action
        assert record.unique_searches == 1  # One unique search
        assert record.find_operations == 1  # One FIND action
        assert record.context_length_tokens == 180  # 50+100+30

    def test_to_trajectory_record_no_answer(self):
        """Test expert seeds have no answer (focus on process)."""
        turns = [
            Turn(
                turn_number=1,
                reasoning="Test",
                action=ToolCall(
                    tool=ToolCallType.SEARCH,
                    arguments={"query": "test"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Test",
                observation_tokens=10,
            )
        ]

        seed = ExpertSeedTrajectory(
            seed_id="test",
            name="Test",
            description="Test",
            question="Test",
            turns=turns,
            created_by="expert",
        )

        record = seed.to_trajectory_record()

        assert record.answer is None


class TestTrajectoryCollector:
    """Tests for TrajectoryCollector class."""

    @pytest.fixture
    def temp_storage(self):
        """Create temporary storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def collector(self, temp_storage):
        """Create trajectory collector with temp storage."""
        return TrajectoryCollector(storage_dir=temp_storage)

    @pytest.fixture
    def collector_with_seeds(self, temp_storage):
        """Create collector with expert seeds."""
        turns = [
            Turn(
                turn_number=1,
                reasoning="Search",
                action=ToolCall(
                    tool=ToolCallType.SEARCH,
                    arguments={"query": "test"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Found",
                observation_tokens=10,
            ),
            Turn(
                turn_number=2,
                reasoning="Open",
                action=ToolCall(
                    tool=ToolCallType.OPEN,
                    arguments={"paper_id": "p1"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Opened",
                observation_tokens=20,
            ),
        ]

        seed = ExpertSeedTrajectory(
            seed_id="expert1",
            name="Expert Pattern",
            description="Good pattern",
            question="Test",
            turns=turns,
            created_by="expert",
        )

        return TrajectoryCollector(storage_dir=temp_storage, expert_seeds=[seed])

    def test_initialization(self, collector, temp_storage):
        """Test collector initialization."""
        assert collector.storage_dir == temp_storage
        assert temp_storage.exists()
        assert len(collector.expert_seeds) == 0

    def test_initialization_with_expert_seeds(self, collector_with_seeds):
        """Test collector initialization with expert seeds."""
        assert len(collector_with_seeds.expert_seeds) == 1

    def test_record_trajectory(self, collector):
        """Test recording a trajectory."""
        turns = [
            Turn(
                turn_number=1,
                reasoning="Search for papers",
                action=ToolCall(
                    tool=ToolCallType.SEARCH,
                    arguments={"query": "transformers"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Found 3 papers",
                observation_tokens=50,
            ),
            Turn(
                turn_number=2,
                reasoning="Open paper",
                action=ToolCall(
                    tool=ToolCallType.OPEN,
                    arguments={"paper_id": "paper1"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Paper content",
                observation_tokens=200,
            ),
            Turn(
                turn_number=3,
                reasoning="Provide answer",
                action=ToolCall(
                    tool=ToolCallType.ANSWER,
                    arguments={"answer": "Final answer"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Answer provided",
                observation_tokens=20,
            ),
        ]

        result = ResearchResult(
            question="Test question",
            answer="Final answer",
            trajectory=turns,
            papers_consulted=["paper1"],
            total_turns=3,
            exhausted=False,
            total_tokens=270,
            duration_seconds=10.5,
        )

        record = collector.record_trajectory(result)

        assert record.question == "Test question"
        assert record.answer == "Final answer"
        assert len(record.turns) == 3
        assert record.papers_opened == 1
        assert record.unique_searches == 1
        assert record.quality_score > 0

        # Check file was saved
        files = list(collector.storage_dir.glob("*.json"))
        assert len(files) == 1

    def test_record_trajectory_with_custom_quality_score(self, collector):
        """Test recording trajectory with pre-computed quality score."""
        turns = [
            Turn(
                turn_number=1,
                reasoning="Test",
                action=ToolCall(
                    tool=ToolCallType.SEARCH,
                    arguments={"query": "test"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Test",
                observation_tokens=10,
            )
        ]

        result = ResearchResult(
            question="Test",
            answer="Answer",
            trajectory=turns,
            papers_consulted=[],
            total_turns=1,
            exhausted=False,
            total_tokens=10,
            duration_seconds=1.0,
        )

        record = collector.record_trajectory(result, quality_score=0.95)

        assert record.quality_score == 0.95

    def test_compute_quality_score_successful_answer(self, collector):
        """Test quality score for successful trajectory."""
        turns = [
            Turn(
                turn_number=i + 1,
                reasoning="Test",
                action=ToolCall(
                    tool=ToolCallType.SEARCH,
                    arguments={"query": f"query{i}"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Test",
                observation_tokens=10,
            )
            for i in range(5)
        ]

        result = ResearchResult(
            question="Test",
            answer="Good answer",
            trajectory=turns,
            papers_consulted=["paper1", "paper2"],
            total_turns=5,
            exhausted=False,
            total_tokens=100,
            duration_seconds=5.0,
        )

        score = collector._compute_quality_score(result)

        # Should get points for: answer (0.4), reasonable turns (0.2), papers (0.2)
        assert score >= 0.8

    def test_compute_quality_score_no_answer(self, collector):
        """Test quality score without answer."""
        result = ResearchResult(
            question="Test",
            answer=None,
            trajectory=[],
            papers_consulted=[],
            total_turns=5,
            exhausted=True,
            total_tokens=100,
            duration_seconds=5.0,
        )

        score = collector._compute_quality_score(result)

        # No answer = lower score
        assert score < 0.5

    def test_compute_quality_score_too_long(self, collector):
        """Test quality score penalizes very long sessions."""
        result = ResearchResult(
            question="Test",
            answer="Answer",
            trajectory=[],
            papers_consulted=["p1", "p2"],
            total_turns=50,  # Very long
            exhausted=False,
            total_tokens=1000,
            duration_seconds=100.0,
        )

        score = collector._compute_quality_score(result)

        # Long session gets partial credit for turns
        assert 0.5 <= score < 0.9

    def test_compute_expert_alignment(self, collector_with_seeds):
        """Test expert alignment scoring."""
        # Create result with similar action sequence to expert seed
        turns = [
            Turn(
                turn_number=1,
                reasoning="Search",
                action=ToolCall(
                    tool=ToolCallType.SEARCH,
                    arguments={"query": "test"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Found",
                observation_tokens=10,
            ),
            Turn(
                turn_number=2,
                reasoning="Open",
                action=ToolCall(
                    tool=ToolCallType.OPEN,
                    arguments={"paper_id": "p1"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Opened",
                observation_tokens=20,
            ),
        ]

        result = ResearchResult(
            question="Test",
            answer="Answer",
            trajectory=turns,
            papers_consulted=["p1"],
            total_turns=2,
            exhausted=False,
            total_tokens=30,
            duration_seconds=1.0,
        )

        alignment = collector_with_seeds._compute_expert_alignment(result)

        # Should have high alignment (same sequence: search -> open)
        assert alignment > 0.5

    def test_compute_expert_alignment_no_seeds(self, collector):
        """Test alignment with no expert seeds returns neutral score."""
        result = ResearchResult(
            question="Test",
            answer="Answer",
            trajectory=[],
            papers_consulted=[],
            total_turns=1,
            exhausted=False,
            total_tokens=10,
            duration_seconds=1.0,
        )

        alignment = collector._compute_expert_alignment(result)

        assert alignment == 0.5  # Neutral

    def test_longest_common_subsequence(self, collector):
        """Test LCS calculation."""
        seq1 = ["a", "b", "c", "d"]
        seq2 = ["a", "x", "c", "d"]

        lcs = collector._longest_common_subsequence(seq1, seq2)

        assert lcs == 3  # "a", "c", "d"

    def test_longest_common_subsequence_no_common(self, collector):
        """Test LCS with no common elements."""
        seq1 = ["a", "b", "c"]
        seq2 = ["x", "y", "z"]

        lcs = collector._longest_common_subsequence(seq1, seq2)

        assert lcs == 0

    def test_filter_quality_basic(self, collector):
        """Test quality filtering."""
        # Record some trajectories
        for i in range(3):
            turns = [
                Turn(
                    turn_number=j + 1,
                    reasoning="Test",
                    action=ToolCall(
                        tool=ToolCallType.SEARCH,
                        arguments={"query": f"q{j}"},
                        timestamp=datetime.now(UTC),
                    ),
                    observation="Test",
                    observation_tokens=10,
                )
                for j in range(5)
            ]

            result = ResearchResult(
                question=f"Question {i}",
                answer=f"Answer {i}",
                trajectory=turns,
                papers_consulted=["p1", "p2"],
                total_turns=5,
                exhausted=False,
                total_tokens=50,
                duration_seconds=5.0,
            )

            collector.record_trajectory(result)

        filtered = collector.filter_quality(
            min_turns=3,
            require_answer=True,
            min_quality_score=0.5,
        )

        assert len(filtered) == 3

    def test_filter_quality_removes_low_quality(self, collector):
        """Test filtering removes low quality trajectories."""
        # High quality
        good_result = ResearchResult(
            question="Good",
            answer="Answer",
            trajectory=[
                Turn(
                    turn_number=i + 1,
                    reasoning="Test",
                    action=ToolCall(
                        tool=ToolCallType.SEARCH,
                        arguments={"query": f"q{i}"},
                        timestamp=datetime.now(UTC),
                    ),
                    observation="Test",
                    observation_tokens=10,
                )
                for i in range(5)
            ],
            papers_consulted=["p1", "p2"],
            total_turns=5,
            exhausted=False,
            total_tokens=50,
            duration_seconds=5.0,
        )

        # Low quality (no answer, exhausted)
        bad_result = ResearchResult(
            question="Bad",
            answer=None,
            trajectory=[
                Turn(
                    turn_number=1,
                    reasoning="Test",
                    action=ToolCall(
                        tool=ToolCallType.SEARCH,
                        arguments={"query": "q"},
                        timestamp=datetime.now(UTC),
                    ),
                    observation="Test",
                    observation_tokens=10,
                )
            ],
            papers_consulted=[],
            total_turns=1,
            exhausted=True,
            total_tokens=10,
            duration_seconds=1.0,
        )

        collector.record_trajectory(good_result)
        collector.record_trajectory(bad_result)

        filtered = collector.filter_quality(min_quality_score=0.5)

        assert len(filtered) == 1
        assert filtered[0].question == "Good"

    def test_filter_quality_includes_expert_seeds(self, collector_with_seeds):
        """Test filtering includes expert seeds."""
        # Expert seeds have no answer by default, so need to adjust filter
        filtered = collector_with_seeds.filter_quality(
            min_turns=2,
            require_answer=False,  # Expert seeds focus on process, not answer
            min_quality_score=0.5,
        )

        # Should include the expert seed
        assert len(filtered) >= 1
        expert_records = [
            t for t in filtered if t.trajectory_id.startswith("expert_seed_")
        ]
        assert len(expert_records) == 1

    def test_filter_quality_require_answer_true(self, collector):
        """Test require_answer=True filters out trajectories without answers."""
        # Trajectory with answer
        with_answer = ResearchResult(
            question="With answer",
            answer="The answer",
            trajectory=[
                Turn(
                    turn_number=i + 1,
                    reasoning="Test",
                    action=ToolCall(
                        tool=ToolCallType.SEARCH,
                        arguments={"query": f"q{i}"},
                        timestamp=datetime.now(UTC),
                    ),
                    observation="Test",
                    observation_tokens=10,
                )
                for i in range(3)
            ],
            papers_consulted=["p1"],
            total_turns=3,
            exhausted=False,
            total_tokens=30,
            duration_seconds=3.0,
        )

        # Trajectory without answer
        without_answer = ResearchResult(
            question="Without answer",
            answer=None,
            trajectory=[
                Turn(
                    turn_number=i + 1,
                    reasoning="Test",
                    action=ToolCall(
                        tool=ToolCallType.SEARCH,
                        arguments={"query": f"q{i}"},
                        timestamp=datetime.now(UTC),
                    ),
                    observation="Test",
                    observation_tokens=10,
                )
                for i in range(3)
            ],
            papers_consulted=["p1"],
            total_turns=3,
            exhausted=False,
            total_tokens=30,
            duration_seconds=3.0,
        )

        collector.record_trajectory(with_answer)
        collector.record_trajectory(without_answer)

        # With require_answer=True, only trajectory with answer should be included
        filtered = collector.filter_quality(
            min_turns=1,
            require_answer=True,
            min_quality_score=0.0,
        )

        assert len(filtered) == 1
        assert filtered[0].question == "With answer"
        assert filtered[0].answer == "The answer"

    def test_filter_quality_min_quality_score_boundary(self, collector):
        """Test min_quality_score filtering at boundary values."""
        # Create trajectory with specific quality
        result = ResearchResult(
            question="Boundary test",
            answer="Answer",
            trajectory=[
                Turn(
                    turn_number=i + 1,
                    reasoning="Test",
                    action=ToolCall(
                        tool=ToolCallType.SEARCH,
                        arguments={"query": f"q{i}"},
                        timestamp=datetime.now(UTC),
                    ),
                    observation="Test",
                    observation_tokens=10,
                )
                for i in range(3)
            ],
            papers_consulted=["p1"],
            total_turns=3,
            exhausted=False,
            total_tokens=30,
            duration_seconds=3.0,
        )

        # Record with explicit quality score
        collector.record_trajectory(result, quality_score=0.6)

        # Score exactly at boundary - should be included
        filtered_at = collector.filter_quality(min_quality_score=0.6)
        assert len(filtered_at) == 1

        # Score above trajectory quality - should be excluded
        filtered_above = collector.filter_quality(min_quality_score=0.7)
        assert len(filtered_above) == 0

    def test_analyze_patterns_basic(self, collector):
        """Test pattern analysis."""
        # Record trajectories with patterns
        for i in range(3):
            turns = [
                Turn(
                    turn_number=1,
                    reasoning="Search",
                    action=ToolCall(
                        tool=ToolCallType.SEARCH,
                        arguments={"query": "transformer attention mechanism"},
                        timestamp=datetime.now(UTC),
                    ),
                    observation="Found",
                    observation_tokens=10,
                ),
                Turn(
                    turn_number=2,
                    reasoning="Open",
                    action=ToolCall(
                        tool=ToolCallType.OPEN,
                        arguments={"paper_id": f"p{i}", "section": "methods"},
                        timestamp=datetime.now(UTC),
                    ),
                    observation="Opened",
                    observation_tokens=20,
                ),
                Turn(
                    turn_number=3,
                    reasoning="Find",
                    action=ToolCall(
                        tool=ToolCallType.FIND,
                        arguments={"pattern": "accuracy"},
                        timestamp=datetime.now(UTC),
                    ),
                    observation="Found",
                    observation_tokens=10,
                ),
            ]

            result = ResearchResult(
                question=f"Question {i}",
                answer=f"Answer {i}",
                trajectory=turns,
                papers_consulted=[f"p{i}"],
                total_turns=3,
                exhausted=False,
                total_tokens=40,
                duration_seconds=3.0,
            )

            collector.record_trajectory(result)

        insights = collector.analyze_patterns()

        assert len(insights.effective_query_patterns) > 0
        assert "transformer" in insights.effective_query_patterns
        assert len(insights.successful_sequences) > 0
        assert insights.average_turns_to_success == 3.0
        assert "methods" in insights.paper_consultation_patterns

    def test_analyze_patterns_empty_trajectories(self, collector):
        """Test pattern analysis with no trajectories."""
        insights = collector.analyze_patterns()

        assert isinstance(insights, TrajectoryInsights)
        assert len(insights.effective_query_patterns) == 0
        assert insights.average_turns_to_success == 0.0

    def test_analyze_patterns_with_provided_trajectories(self, collector):
        """Test analyzing specific trajectories."""
        turns = [
            Turn(
                turn_number=1,
                reasoning="Search",
                action=ToolCall(
                    tool=ToolCallType.SEARCH,
                    arguments={"query": "test query"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Found",
                observation_tokens=10,
            )
        ]

        traj = TrajectoryRecord(
            trajectory_id="test",
            question="Test",
            answer="Answer",
            turns=turns,
            quality_score=0.9,
            papers_opened=1,
            unique_searches=1,
            find_operations=0,
            context_length_tokens=10,
        )

        insights = collector.analyze_patterns(trajectories=[traj])

        assert "test" in insights.effective_query_patterns

    def test_generate_contextual_tips(self, collector):
        """Test generating contextual tips from insights."""
        insights = TrajectoryInsights(
            effective_query_patterns=["transformer", "attention", "neural"],
            successful_sequences=["search -> open -> find"],
            failure_modes={},
            average_turns_to_success=8.5,
            paper_consultation_patterns={"methods": 10, "results": 8},
        )

        tips = collector.generate_contextual_tips(insights, min_confidence=0.7)

        assert len(tips) > 0
        # Should have tips about query patterns, sequences, and turn efficiency
        assert any("transformer" in tip.strategy.lower() for tip in tips)

    def test_generate_contextual_tips_confidence_filtering(self, collector):
        """Test tips are filtered by confidence."""
        insights = TrajectoryInsights(
            effective_query_patterns=["test"],
            successful_sequences=["search -> open"],
            average_turns_to_success=5.0,
        )

        # High threshold
        tips_high = collector.generate_contextual_tips(insights, min_confidence=0.9)
        # Low threshold
        tips_low = collector.generate_contextual_tips(insights, min_confidence=0.6)

        # Low threshold should have more tips
        assert len(tips_low) >= len(tips_high)

    def test_save_trajectory(self, collector):
        """Test trajectory is saved to disk."""
        turns = [
            Turn(
                turn_number=1,
                reasoning="Test",
                action=ToolCall(
                    tool=ToolCallType.SEARCH,
                    arguments={"query": "test"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Test",
                observation_tokens=10,
            )
        ]

        record = TrajectoryRecord(
            trajectory_id="test123",
            question="Test question",
            answer="Test answer",
            turns=turns,
            quality_score=0.8,
            papers_opened=0,
            unique_searches=1,
            find_operations=0,
            context_length_tokens=10,
        )

        collector._save_trajectory(record)

        # Check file exists
        saved_file = collector.storage_dir / "test123.json"
        assert saved_file.exists()

        # Check content
        with open(saved_file) as f:
            data = json.load(f)

        assert data["trajectory_id"] == "test123"
        assert data["question"] == "Test question"
        assert len(data["turns"]) == 1

    def test_load_all_trajectories(self, collector):
        """Test loading all saved trajectories."""
        # Save multiple trajectories
        for i in range(3):
            turns = [
                Turn(
                    turn_number=1,
                    reasoning="Test",
                    action=ToolCall(
                        tool=ToolCallType.SEARCH,
                        arguments={"query": f"q{i}"},
                        timestamp=datetime.now(UTC),
                    ),
                    observation="Test",
                    observation_tokens=10,
                )
            ]

            record = TrajectoryRecord(
                trajectory_id=f"test{i}",
                question=f"Question {i}",
                answer=f"Answer {i}",
                turns=turns,
                quality_score=0.8,
                papers_opened=0,
                unique_searches=1,
                find_operations=0,
                context_length_tokens=10,
            )

            collector._save_trajectory(record)

        # Load all
        trajectories = collector._load_all_trajectories()

        assert len(trajectories) == 3

    def test_load_all_trajectories_handles_corrupt_files(self, collector):
        """Test loading handles corrupt files gracefully."""
        # Create a corrupt file
        corrupt_file = collector.storage_dir / "corrupt.json"
        corrupt_file.write_text("not valid json {")

        # Create a valid file
        turns = [
            Turn(
                turn_number=1,
                reasoning="Test",
                action=ToolCall(
                    tool=ToolCallType.SEARCH,
                    arguments={"query": "test"},
                    timestamp=datetime.now(UTC),
                ),
                observation="Test",
                observation_tokens=10,
            )
        ]

        record = TrajectoryRecord(
            trajectory_id="valid",
            question="Test",
            answer="Answer",
            turns=turns,
            quality_score=0.8,
            papers_opened=0,
            unique_searches=1,
            find_operations=0,
            context_length_tokens=10,
        )

        collector._save_trajectory(record)

        # Should load only valid file
        with patch("src.services.dra.trajectory.logger") as mock_logger:
            trajectories = collector._load_all_trajectories()

            assert len(trajectories) == 1
            assert trajectories[0].trajectory_id == "valid"
            # Should log warning about corrupt file
            assert mock_logger.warning.called


class TestDefaultExpertSeeds:
    """Tests for default expert seed templates."""

    def test_default_seeds_exist(self):
        """Test default expert seeds are defined."""
        assert len(DEFAULT_EXPERT_SEEDS) > 0

    def test_default_seeds_structure(self):
        """Test default seeds have required fields."""
        for seed_data in DEFAULT_EXPERT_SEEDS:
            assert "seed_id" in seed_data
            assert "name" in seed_data
            assert "description" in seed_data
            assert "question" in seed_data
            assert "key_patterns" in seed_data
            assert "created_by" in seed_data

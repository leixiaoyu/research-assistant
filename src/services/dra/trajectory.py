"""Trajectory learning and quality analysis for DRA.

This module provides:
- Trajectory quality filtering
- Pattern analysis and insight extraction
- Expert seed trajectory management (SR-8.3)
- Contextual learning tips generation
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import structlog
from pydantic import BaseModel, Field

from src.models.dra import (
    ContextualTip,
    ResearchResult,
    ToolCallType,
    TrajectoryInsights,
    TrajectoryRecord,
    Turn,
)

logger = structlog.get_logger()


class ExpertSeedTrajectory(BaseModel):
    """A manually curated "golden path" trajectory.

    SR-8.3: Expert seeds are used as benchmarks to prevent
    self-reinforcement of bad habits during trajectory learning.

    Attributes:
        seed_id: Unique identifier for this expert trajectory
        name: Human-readable name (e.g., "comparative_analysis_best_practice")
        description: What makes this trajectory exemplary
        question: Example research question
        turns: Sequence of expert turns
        quality_score: Always 1.0 (perfect benchmark)
        key_patterns: Important patterns demonstrated
        created_by: Who curated this trajectory (human expert)
        created_at: When it was added
    """

    seed_id: str = Field(..., max_length=256, description="Seed ID")
    name: str = Field(..., max_length=256, description="Trajectory name")
    description: str = Field(..., max_length=2000, description="Why this is exemplary")
    question: str = Field(..., max_length=2000, description="Example question")
    turns: list[Turn] = Field(..., description="Expert turn sequence")
    quality_score: float = Field(1.0, description="Always 1.0 for expert seeds")
    key_patterns: list[str] = Field(
        default_factory=list, description="Key patterns demonstrated"
    )
    created_by: str = Field(..., max_length=256, description="Curator name")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Creation time"
    )

    def to_trajectory_record(self) -> TrajectoryRecord:
        """Convert to TrajectoryRecord for unified processing.

        Returns:
            TrajectoryRecord representation
        """
        # Extract metadata from turns
        papers_opened = len(
            {t.action.arguments.get("paper_id") for t in self.turns if t.action.tool == ToolCallType.OPEN}
        )
        unique_searches = len(
            {t.action.arguments.get("query") for t in self.turns if t.action.tool == ToolCallType.SEARCH}
        )
        find_ops = sum(1 for t in self.turns if t.action.tool == ToolCallType.FIND)
        context_tokens = sum(t.observation_tokens for t in self.turns)

        return TrajectoryRecord(
            trajectory_id=f"expert_seed_{self.seed_id}",
            question=self.question,
            answer=None,  # Expert seeds focus on process, not answer
            turns=self.turns,
            quality_score=1.0,  # Perfect quality
            papers_opened=papers_opened,
            unique_searches=unique_searches,
            find_operations=find_ops,
            context_length_tokens=context_tokens,
            created_at=self.created_at,
        )


class TrajectoryCollector:
    """Manages trajectory collection, quality filtering, and learning.

    SR-8.3: Implements expert seed trajectory weighting to prevent
    self-reinforcement of bad habits.
    """

    def __init__(
        self,
        storage_dir: Path,
        expert_seeds: Optional[list[ExpertSeedTrajectory]] = None,
    ):
        """Initialize trajectory collector.

        Args:
            storage_dir: Directory to store trajectories
            expert_seeds: List of expert seed trajectories (SR-8.3)
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Load expert seeds (SR-8.3)
        self.expert_seeds = expert_seeds or []
        logger.info(
            "trajectory_collector_initialized",
            storage_dir=str(storage_dir),
            expert_seeds=len(self.expert_seeds),
        )

    def record_trajectory(
        self,
        result: ResearchResult,
        quality_score: Optional[float] = None,
    ) -> TrajectoryRecord:
        """Record a completed research trajectory.

        Args:
            result: Research result from agent session
            quality_score: Optional pre-computed quality score

        Returns:
            Recorded trajectory
        """
        # Generate trajectory ID
        trajectory_id = f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        # Compute metadata
        papers_opened = len(set(result.papers_consulted))
        unique_searches = len(
            {
                t.action.arguments.get("query")
                for t in result.trajectory
                if t.action.tool == ToolCallType.SEARCH
            }
        )
        find_operations = sum(
            1 for t in result.trajectory if t.action.tool == ToolCallType.FIND
        )

        # Compute quality score if not provided
        if quality_score is None:
            quality_score = self._compute_quality_score(result)

        record = TrajectoryRecord(
            trajectory_id=trajectory_id,
            question=result.question,
            answer=result.answer,
            turns=result.trajectory,
            quality_score=quality_score,
            papers_opened=papers_opened,
            unique_searches=unique_searches,
            find_operations=find_operations,
            context_length_tokens=result.total_tokens,
            created_at=datetime.now(UTC),
        )

        # Save to disk
        self._save_trajectory(record)

        logger.info(
            "trajectory_recorded",
            trajectory_id=trajectory_id,
            turns=len(result.trajectory),
            quality=quality_score,
        )

        return record

    def _compute_quality_score(self, result: ResearchResult) -> float:
        """Compute quality score for a trajectory.

        SR-8.3: Weights expert seed alignment higher to prevent bad habit reinforcement.

        Scoring factors:
        - Answered successfully: +0.4
        - Reasonable turn count (not degenerate, not exhausted): +0.2
        - Papers consulted (good breadth): +0.2
        - Expert seed alignment (SR-8.3): +0.2

        Args:
            result: Research result

        Returns:
            Quality score (0.0-1.0)
        """
        score = 0.0

        # Factor 1: Answered successfully
        if result.answer and not result.exhausted:
            score += 0.4

        # Factor 2: Reasonable turn count (3-30 turns)
        if 3 <= result.total_turns <= 30:
            score += 0.2
        elif result.total_turns > 30:
            # Penalize very long sessions (possibly inefficient)
            score += 0.1

        # Factor 3: Papers consulted (at least 2)
        if len(result.papers_consulted) >= 2:
            score += 0.2
        elif len(result.papers_consulted) >= 1:
            score += 0.1

        # Factor 4: Expert seed alignment (SR-8.3)
        alignment_score = self._compute_expert_alignment(result)
        score += alignment_score * 0.2

        return round(score, 4)

    def _compute_expert_alignment(self, result: ResearchResult) -> float:
        """Compute alignment with expert seed trajectories.

        SR-8.3: Measures how well trajectory follows expert patterns.

        Args:
            result: Research result

        Returns:
            Alignment score (0.0-1.0)
        """
        if not self.expert_seeds:
            return 0.5  # Neutral if no expert seeds

        # Extract action sequence from result
        action_sequence = [t.action.tool.value for t in result.trajectory]

        # Compare with each expert seed
        alignment_scores: list[float] = []
        for seed in self.expert_seeds:
            seed_sequence = [t.action.tool.value for t in seed.turns]

            # Simple sequence similarity (longest common subsequence ratio)
            lcs_length = self._longest_common_subsequence(action_sequence, seed_sequence)
            similarity = lcs_length / max(len(action_sequence), len(seed_sequence))

            alignment_scores.append(similarity)

        # Return best alignment score
        return round(max(alignment_scores), 4) if alignment_scores else 0.5

    def _longest_common_subsequence(self, seq1: list[str], seq2: list[str]) -> int:
        """Compute LCS length between two sequences.

        Args:
            seq1: First sequence
            seq2: Second sequence

        Returns:
            LCS length
        """
        m, n = len(seq1), len(seq2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if seq1[i - 1] == seq2[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

        return dp[m][n]

    def filter_quality(
        self,
        min_turns: int = 3,
        require_answer: bool = True,
        min_quality_score: float = 0.5,
    ) -> list[TrajectoryRecord]:
        """Filter trajectories by quality criteria.

        SR-8.3: Automatically includes expert seeds (perfect quality).

        Args:
            min_turns: Minimum turn count
            require_answer: Whether answer is required
            min_quality_score: Minimum quality score

        Returns:
            List of quality trajectories
        """
        # Load all saved trajectories
        trajectories = self._load_all_trajectories()

        # Add expert seeds (SR-8.3)
        expert_records = [seed.to_trajectory_record() for seed in self.expert_seeds]
        all_trajectories = trajectories + expert_records

        # Apply filters
        filtered = []
        for traj in all_trajectories:
            # Check minimum turns
            if len(traj.turns) < min_turns:
                continue

            # Check answer requirement
            if require_answer and not traj.answer:
                continue

            # Check quality score
            if traj.quality_score < min_quality_score:
                continue

            filtered.append(traj)

        logger.info(
            "quality_filter_applied",
            total=len(all_trajectories),
            filtered=len(filtered),
            criteria={"min_turns": min_turns, "require_answer": require_answer, "min_quality": min_quality_score},
        )

        return filtered

    def analyze_patterns(
        self,
        trajectories: Optional[list[TrajectoryRecord]] = None,
    ) -> TrajectoryInsights:
        """Analyze trajectory patterns to extract insights.

        Args:
            trajectories: Trajectories to analyze (loads all if None)

        Returns:
            Extracted insights
        """
        if trajectories is None:
            trajectories = self.filter_quality()

        if not trajectories:
            logger.warning("no_trajectories_for_analysis")
            return TrajectoryInsights()

        logger.info("analyzing_trajectory_patterns", count=len(trajectories))

        # Extract query patterns
        query_patterns: dict[str, int] = {}
        for traj in trajectories:
            for turn in traj.turns:
                if turn.action.tool == ToolCallType.SEARCH:
                    query = turn.action.arguments.get("query", "")
                    # Extract key terms
                    terms = query.lower().split()
                    for term in terms:
                        if len(term) > 3:  # Ignore short words
                            query_patterns[term] = query_patterns.get(term, 0) + 1

        # Get top query patterns
        effective_patterns = sorted(query_patterns.items(), key=lambda x: x[1], reverse=True)[:10]
        effective_query_patterns = [term for term, _ in effective_patterns]

        # Extract successful sequences (most common 3-action sequences)
        sequence_counts: dict[str, int] = {}
        for traj in trajectories:
            actions = [t.action.tool.value for t in traj.turns]
            for i in range(len(actions) - 2):
                seq = " -> ".join(actions[i:i+3])
                sequence_counts[seq] = sequence_counts.get(seq, 0) + 1

        successful_sequences = sorted(sequence_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        successful_seqs = [seq for seq, _ in successful_sequences]

        # Compute average turns to success
        successful_trajs = [t for t in trajectories if t.answer]
        avg_turns = (
            sum(len(t.turns) for t in successful_trajs) / len(successful_trajs)
            if successful_trajs else 0.0
        )

        # Extract paper consultation patterns
        section_counts: dict[str, int] = {}
        for traj in trajectories:
            for turn in traj.turns:
                if turn.action.tool == ToolCallType.OPEN:
                    section = turn.action.arguments.get("section", "full_paper")
                    section_counts[section] = section_counts.get(section, 0) + 1

        insights = TrajectoryInsights(
            effective_query_patterns=effective_query_patterns,
            successful_sequences=successful_seqs,
            failure_modes={},  # TODO: Implement failure mode detection
            average_turns_to_success=round(avg_turns, 2),
            paper_consultation_patterns=section_counts,
        )

        logger.info(
            "pattern_analysis_complete",
            query_patterns=len(effective_query_patterns),
            sequences=len(successful_seqs),
        )

        return insights

    def generate_contextual_tips(
        self,
        insights: TrajectoryInsights,
        min_confidence: float = 0.7,
    ) -> list[ContextualTip]:
        """Generate contextual strategy tips from insights.

        Args:
            insights: Trajectory insights
            min_confidence: Minimum confidence threshold

        Returns:
            List of contextual tips
        """
        tips: list[ContextualTip] = []

        # Tip 1: Query patterns
        if insights.effective_query_patterns:
            tip = ContextualTip(
                context="When searching for papers",
                strategy=f"Use terms like: {', '.join(insights.effective_query_patterns[:5])}. "
                "These terms frequently lead to relevant results.",
                confidence=0.8,
                examples=["expert_seed_comparative_analysis"],  # Reference expert seeds
            )
            tips.append(tip)

        # Tip 2: Action sequences
        if insights.successful_sequences:
            tip = ContextualTip(
                context="When gathering evidence",
                strategy=f"Follow successful patterns: {insights.successful_sequences[0]}. "
                "This sequence often leads to comprehensive findings.",
                confidence=0.75,
                examples=["expert_seed_evidence_gathering"],
            )
            tips.append(tip)

        # Tip 3: Turn efficiency
        if insights.average_turns_to_success > 0:
            tip = ContextualTip(
                context="When planning research strategy",
                strategy=f"Aim for {int(insights.average_turns_to_success)} turns. "
                "This is the typical depth for thorough research.",
                confidence=0.7,
                examples=[],
            )
            tips.append(tip)

        # Filter by confidence
        tips = [t for t in tips if t.confidence >= min_confidence]

        logger.info("contextual_tips_generated", count=len(tips))

        return tips

    def _save_trajectory(self, record: TrajectoryRecord) -> None:
        """Save trajectory to disk.

        Args:
            record: Trajectory record to save
        """
        file_path = self.storage_dir / f"{record.trajectory_id}.json"

        data = record.model_dump()
        # Convert datetime to ISO format
        data["created_at"] = record.created_at.isoformat()
        # Convert Turn objects to dicts
        data["turns"] = [
            {
                "turn_number": t.turn_number,
                "reasoning": t.reasoning,
                "action": {
                    "tool": t.action.tool.value,
                    "arguments": t.action.arguments,
                    "timestamp": t.action.timestamp.isoformat(),
                },
                "observation": t.observation,
                "observation_tokens": t.observation_tokens,
            }
            for t in record.turns
        ]

        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)

        logger.debug("trajectory_saved", file=str(file_path))

    def _load_all_trajectories(self) -> list[TrajectoryRecord]:
        """Load all saved trajectories from disk.

        Returns:
            List of trajectory records
        """
        trajectories: list[TrajectoryRecord] = []

        for file_path in self.storage_dir.glob("*.json"):
            try:
                with open(file_path) as f:
                    data = json.load(f)

                # Reconstruct TrajectoryRecord
                # (Simplified - in production, use proper deserialization)
                record = TrajectoryRecord.model_validate(data)
                trajectories.append(record)

            except Exception as e:
                logger.warning(
                    "trajectory_load_failed",
                    file=str(file_path),
                    error=str(e),
                )

        logger.debug("trajectories_loaded", count=len(trajectories))

        return trajectories


# SR-8.3: Predefined expert seed trajectories
DEFAULT_EXPERT_SEEDS = [
    {
        "seed_id": "comparative_analysis",
        "name": "Comparative Analysis Best Practice",
        "description": "Demonstrates effective strategy for comparing two approaches",
        "question": "How does Transformer architecture compare to RNN for machine translation?",
        "key_patterns": [
            "Use 'vs' or 'compared to' in search queries",
            "Open methods sections first to understand implementations",
            "Use find() to locate specific metrics (BLEU, accuracy)",
        ],
        "created_by": "human_expert",
    },
    {
        "seed_id": "evidence_gathering",
        "name": "Evidence Gathering Best Practice",
        "description": "Shows systematic evidence collection across multiple papers",
        "question": "What empirical evidence supports the effectiveness of attention mechanisms?",
        "key_patterns": [
            "Search for multiple related terms (attention, self-attention, multi-head)",
            "Open results sections to find empirical data",
            "Use find() to extract specific numbers and tables",
        ],
        "created_by": "human_expert",
    },
]

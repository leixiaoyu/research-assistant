"""Preference model for Phase 7.3 Human Feedback Loop.

This module implements preference learning using contextual bandits
with Thompson Sampling for exploration-exploitation balance.
"""

import logging
import math
import random
from typing import Dict, List, Optional, Protocol, runtime_checkable

import numpy as np

from src.models.feedback import FeedbackEntry, FeedbackRating

logger = logging.getLogger(__name__)


@runtime_checkable
class PaperLike(Protocol):
    """Protocol for paper-like objects."""

    paper_id: str
    title: str


class PreferenceModel:
    """Model for learning user preferences from feedback.

    Implements contextual bandits with Thompson Sampling for
    balancing exploration and exploitation in paper ranking.

    Attributes:
        algorithm: Learning algorithm ("contextual_bandit" or "simple_average").
        exploration_rate: Epsilon for exploration (0-1).
        min_feedback_for_training: Minimum feedback before training.
        blend_weight: Weight of preference score vs base score.
    """

    def __init__(
        self,
        algorithm: str = "contextual_bandit",
        exploration_rate: float = 0.1,
        min_feedback_for_training: int = 20,
        blend_weight: float = 0.3,
    ) -> None:
        """Initialize preference model.

        Args:
            algorithm: Learning algorithm to use.
            exploration_rate: Exploration rate for Thompson Sampling.
            min_feedback_for_training: Minimum feedback entries to train.
            blend_weight: Weight of preference vs base score (0-1).
        """
        self.algorithm = algorithm
        self.exploration_rate = exploration_rate
        self.min_feedback_for_training = min_feedback_for_training
        self.blend_weight = blend_weight

        # Model parameters
        self._feature_weights: Optional[np.ndarray] = None
        self._feature_dim: int = 0
        self._trained: bool = False

        # Thompson Sampling parameters (Beta distribution)
        self._alpha: Dict[str, float] = {}  # Success counts
        self._beta: Dict[str, float] = {}  # Failure counts

        # Feature statistics for normalization
        self._feature_mean: Optional[np.ndarray] = None
        self._feature_std: Optional[np.ndarray] = None

    async def train(
        self,
        feedback_entries: List[FeedbackEntry],
        paper_features: Dict[str, np.ndarray],
    ) -> None:
        """Train the preference model on feedback data.

        Args:
            feedback_entries: List of feedback entries.
            paper_features: Dictionary mapping paper_id to feature vector.
        """
        if len(feedback_entries) < self.min_feedback_for_training:
            logger.info(
                f"Not enough feedback ({len(feedback_entries)}) "
                f"for training (min: {self.min_feedback_for_training})"
            )
            return

        logger.info(f"Training preference model on {len(feedback_entries)} entries")

        if self.algorithm == "simple_average":
            await self._train_simple_average(feedback_entries)
        else:
            await self._train_contextual_bandit(feedback_entries, paper_features)

        self._trained = True

    async def _train_simple_average(
        self,
        feedback_entries: List[FeedbackEntry],
    ) -> None:
        """Train using simple average of ratings per paper.

        Updates Thompson Sampling parameters based on feedback.
        """
        for entry in feedback_entries:
            paper_id = entry.paper_id

            if paper_id not in self._alpha:
                self._alpha[paper_id] = 1.0  # Prior
                self._beta[paper_id] = 1.0

            if entry.rating == FeedbackRating.THUMBS_UP.value:
                self._alpha[paper_id] += 1.0
            elif entry.rating == FeedbackRating.THUMBS_DOWN.value:
                self._beta[paper_id] += 1.0
            # Neutral doesn't update

    async def _train_contextual_bandit(
        self,
        feedback_entries: List[FeedbackEntry],
        paper_features: Dict[str, np.ndarray],
    ) -> None:
        """Train contextual bandit model.

        Uses linear regression on features to predict preference.
        """
        # Filter to entries with features
        valid_entries = [e for e in feedback_entries if e.paper_id in paper_features]

        if len(valid_entries) < self.min_feedback_for_training:
            logger.warning(
                f"Only {len(valid_entries)} entries have features, "
                "falling back to simple average"
            )
            await self._train_simple_average(feedback_entries)
            return

        # Build training data
        X_list: List[np.ndarray] = []
        y_list: List[float] = []

        for entry in valid_entries:
            features = paper_features[entry.paper_id]
            X_list.append(features)

            # Convert rating to reward
            if entry.rating == FeedbackRating.THUMBS_UP.value:
                reward = 1.0
            elif entry.rating == FeedbackRating.THUMBS_DOWN.value:
                reward = 0.0
            else:
                reward = 0.5  # Neutral
            y_list.append(reward)

        X = np.array(X_list)
        y = np.array(y_list)

        self._feature_dim = int(X.shape[1])

        # Normalize features
        self._feature_mean = X.mean(axis=0)
        self._feature_std = X.std(axis=0) + 1e-8  # Avoid division by zero
        X_normalized = (X - self._feature_mean) / self._feature_std

        # Simple linear regression with L2 regularization
        lambda_reg = 0.1
        try:
            # Ridge regression: w = (X^T X + λI)^-1 X^T y
            XtX = X_normalized.T @ X_normalized
            reg_matrix = lambda_reg * np.eye(self._feature_dim)
            self._feature_weights = np.linalg.solve(
                XtX + reg_matrix, X_normalized.T @ y
            )
            logger.info(f"Trained contextual bandit with {self._feature_dim} features")
        except np.linalg.LinAlgError:
            logger.warning("Linear regression failed, using uniform weights")
            self._feature_weights = np.ones(self._feature_dim) / self._feature_dim

        # Also update Thompson Sampling params for exploration
        await self._train_simple_average(feedback_entries)

    async def predict_preference(
        self,
        paper: PaperLike,
        features: Optional[np.ndarray] = None,
    ) -> float:
        """Predict preference score for a paper.

        Args:
            paper: Paper object.
            features: Optional feature vector for the paper.

        Returns:
            Preference score between 0 and 1.
        """
        paper_id = paper.paper_id

        # If we have contextual model and features
        if (
            self._feature_weights is not None
            and features is not None
            and self._feature_mean is not None
            and self._feature_std is not None
        ):
            # Normalize features
            features_norm = (features - self._feature_mean) / self._feature_std
            # Linear prediction
            score = float(np.dot(self._feature_weights, features_norm))
            # Sigmoid to bound to [0, 1]
            return 1.0 / (1.0 + math.exp(-score))

        # Fall back to Thompson Sampling estimate
        if paper_id in self._alpha:
            alpha = self._alpha[paper_id]
            beta = self._beta[paper_id]
            # Mean of Beta distribution
            return alpha / (alpha + beta)

        # Unknown paper - return neutral
        return 0.5

    async def rank_papers(
        self,
        papers: List[PaperLike],
        base_scores: Dict[str, float],
        paper_features: Optional[Dict[str, np.ndarray]] = None,
    ) -> List[PaperLike]:
        """Rank papers using preference + base scores.

        Args:
            papers: List of papers to rank.
            base_scores: Base scores (citations, recency, etc.).
            paper_features: Optional feature vectors.

        Returns:
            Papers sorted by blended score (highest first).
        """
        if not self._trained:
            # Return sorted by base score if not trained
            return sorted(
                papers,
                key=lambda p: base_scores.get(p.paper_id, 0.0),
                reverse=True,
            )

        scored_papers: List[tuple] = []

        for paper in papers:
            base_score = base_scores.get(paper.paper_id, 0.0)

            features = None
            if paper_features and paper.paper_id in paper_features:
                features = paper_features[paper.paper_id]

            pref_score = await self.predict_preference(paper, features)

            # Blend scores
            blended = (
                self.blend_weight * pref_score + (1 - self.blend_weight) * base_score
            )
            scored_papers.append((paper, blended))

        # Sort by blended score
        scored_papers.sort(key=lambda x: x[1], reverse=True)

        return [p for p, _ in scored_papers]

    def get_exploration_candidates(
        self,
        papers: List[PaperLike],
        n: int = 5,
    ) -> List[PaperLike]:
        """Select papers for exploration using Thompson Sampling.

        Args:
            papers: Pool of candidate papers.
            n: Number of papers to select.

        Returns:
            Selected papers for exploration.
        """
        if not papers:
            return []

        n = min(n, len(papers))

        # Thompson Sampling: sample from Beta distributions
        sampled_scores: List[tuple] = []

        for paper in papers:
            paper_id = paper.paper_id

            if paper_id in self._alpha:
                alpha = self._alpha[paper_id]
                beta = self._beta[paper_id]
            else:
                # Uninformative prior for unknown papers
                # Thompson Sampling naturally explores unknown papers
                # through wider Beta distributions
                alpha = 1.0
                beta = 1.0

            # Thompson Sampling: sample from Beta distribution
            # Unknown papers have wider distributions (alpha=beta=1),
            # providing natural exploration without explicit bonus
            sampled_score = random.betavariate(alpha, beta)

            sampled_scores.append((paper, sampled_score))

        # Sort by sampled score and take top n
        sampled_scores.sort(key=lambda x: x[1], reverse=True)

        return [p for p, _ in sampled_scores[:n]]

    def get_model_stats(self) -> Dict:
        """Get model statistics.

        Returns:
            Dictionary with model statistics.
        """
        return {
            "trained": self._trained,
            "algorithm": self.algorithm,
            "papers_with_feedback": len(self._alpha),
            "feature_dim": self._feature_dim,
            "exploration_rate": self.exploration_rate,
            "blend_weight": self.blend_weight,
        }

    @property
    def is_trained(self) -> bool:
        """Check if model has been trained."""
        return self._trained

    def reset(self) -> None:
        """Reset the model to initial state."""
        self._feature_weights = None
        self._feature_dim = 0
        self._trained = False
        self._alpha.clear()
        self._beta.clear()
        self._feature_mean = None
        self._feature_std = None
        logger.info("Preference model reset")

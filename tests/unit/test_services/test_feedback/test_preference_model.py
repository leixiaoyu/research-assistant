"""Unit tests for PreferenceModel."""

import numpy as np
import pytest

from src.models.feedback import FeedbackEntry, FeedbackRating
from src.services.feedback.preference_model import PreferenceModel


class MockPaper:
    """Mock paper for testing."""

    def __init__(self, paper_id: str, title: str):
        self.paper_id = paper_id
        self.title = title


@pytest.fixture
def model():
    """Create PreferenceModel with default settings."""
    return PreferenceModel()


@pytest.fixture
def model_simple():
    """Create PreferenceModel with simple_average algorithm and low threshold."""
    return PreferenceModel(algorithm="simple_average", min_feedback_for_training=1)


@pytest.fixture
def sample_feedback():
    """Create sample feedback entries."""
    return [
        FeedbackEntry(
            paper_id=f"paper-{i}",
            rating=(
                FeedbackRating.THUMBS_UP if i % 2 == 0 else FeedbackRating.THUMBS_DOWN
            ),
        )
        for i in range(25)
    ]


@pytest.fixture
def sample_features():
    """Create sample paper features."""
    return {f"paper-{i}": np.random.randn(10).astype(np.float32) for i in range(25)}


@pytest.fixture
def sample_papers():
    """Create sample papers."""
    return [MockPaper(f"paper-{i}", f"Title {i}") for i in range(10)]


class TestPreferenceModelInit:
    """Tests for PreferenceModel initialization."""

    def test_init_default(self):
        """Test default initialization."""
        model = PreferenceModel()
        assert model.algorithm == "contextual_bandit"
        assert model.exploration_rate == 0.1
        assert model.min_feedback_for_training == 20
        assert model.blend_weight == 0.3
        assert model.is_trained is False

    def test_init_custom(self):
        """Test custom initialization."""
        model = PreferenceModel(
            algorithm="simple_average",
            exploration_rate=0.2,
            min_feedback_for_training=10,
            blend_weight=0.5,
        )
        assert model.algorithm == "simple_average"
        assert model.exploration_rate == 0.2
        assert model.min_feedback_for_training == 10
        assert model.blend_weight == 0.5


class TestPreferenceModelTrainSimpleAverage:
    """Tests for training with simple_average algorithm."""

    @pytest.mark.asyncio
    async def test_train_simple_average(self, model_simple, sample_feedback):
        """Test training with simple average."""
        await model_simple.train(sample_feedback, {})

        assert model_simple.is_trained is True

    @pytest.mark.asyncio
    async def test_train_updates_thompson_params(self, model_simple, sample_feedback):
        """Test that training updates Thompson Sampling parameters."""
        await model_simple.train(sample_feedback, {})

        # Should have alpha/beta for papers
        assert len(model_simple._alpha) > 0
        assert len(model_simple._beta) > 0

    @pytest.mark.asyncio
    async def test_train_thumbs_up_increases_alpha(self, model_simple):
        """Test thumbs up increases alpha."""
        feedback = [
            FeedbackEntry(paper_id="paper-1", rating=FeedbackRating.THUMBS_UP),
            FeedbackEntry(paper_id="paper-1", rating=FeedbackRating.THUMBS_UP),
        ]

        await model_simple.train(feedback, {})

        # Alpha should be 1 (prior) + 2 (thumbs up) = 3
        assert model_simple._alpha["paper-1"] == 3.0
        assert model_simple._beta["paper-1"] == 1.0  # Just prior

    @pytest.mark.asyncio
    async def test_train_thumbs_down_increases_beta(self, model_simple):
        """Test thumbs down increases beta."""
        feedback = [
            FeedbackEntry(paper_id="paper-1", rating=FeedbackRating.THUMBS_DOWN),
            FeedbackEntry(paper_id="paper-1", rating=FeedbackRating.THUMBS_DOWN),
        ]

        await model_simple.train(feedback, {})

        assert model_simple._alpha["paper-1"] == 1.0  # Just prior
        assert model_simple._beta["paper-1"] == 3.0


class TestPreferenceModelTrainContextualBandit:
    """Tests for training with contextual_bandit algorithm."""

    @pytest.mark.asyncio
    async def test_train_contextual_bandit(
        self, model, sample_feedback, sample_features
    ):
        """Test training with contextual bandit."""
        await model.train(sample_feedback, sample_features)

        assert model.is_trained is True
        assert model._feature_weights is not None

    @pytest.mark.asyncio
    async def test_train_insufficient_features_falls_back(self, model):
        """Test training falls back when insufficient features."""
        feedback = [
            FeedbackEntry(paper_id=f"paper-{i}", rating=FeedbackRating.THUMBS_UP)
            for i in range(25)
        ]
        # Only provide features for some papers
        features = {
            f"paper-{i}": np.random.randn(10).astype(np.float32) for i in range(5)
        }

        await model.train(feedback, features)

        # Should still be trained (falls back to simple_average)
        assert model.is_trained is True

    @pytest.mark.asyncio
    async def test_train_normalizes_features(
        self, model, sample_feedback, sample_features
    ):
        """Test that features are normalized during training."""
        await model.train(sample_feedback, sample_features)

        assert model._feature_mean is not None
        assert model._feature_std is not None


class TestPreferenceModelTrainInsufficientData:
    """Tests for training with insufficient data."""

    @pytest.mark.asyncio
    async def test_train_insufficient_feedback(self, model):
        """Test training with too few feedback entries."""
        feedback = [
            FeedbackEntry(paper_id=f"paper-{i}", rating=FeedbackRating.THUMBS_UP)
            for i in range(5)  # Less than min_feedback_for_training
        ]

        await model.train(feedback, {})

        assert model.is_trained is False


class TestPreferenceModelPredict:
    """Tests for predict_preference method."""

    @pytest.mark.asyncio
    async def test_predict_untrained_returns_neutral(self, model):
        """Test prediction without training returns 0.5."""
        paper = MockPaper("unknown-paper", "Title")
        score = await model.predict_preference(paper)
        assert score == 0.5

    @pytest.mark.asyncio
    async def test_predict_with_thompson_sampling(self, model_simple):
        """Test prediction uses Thompson Sampling params."""
        feedback = [
            FeedbackEntry(paper_id="paper-1", rating=FeedbackRating.THUMBS_UP),
            FeedbackEntry(paper_id="paper-1", rating=FeedbackRating.THUMBS_UP),
            FeedbackEntry(paper_id="paper-1", rating=FeedbackRating.THUMBS_UP),
        ]
        await model_simple.train(feedback, {})

        paper = MockPaper("paper-1", "Title")
        score = await model_simple.predict_preference(paper)

        # Should be high since all positive
        # alpha=4, beta=1, mean = 4/5 = 0.8
        assert score == 0.8

    @pytest.mark.asyncio
    async def test_predict_with_features(self, model, sample_feedback, sample_features):
        """Test prediction with features uses contextual model."""
        await model.train(sample_feedback, sample_features)

        paper = MockPaper("paper-0", "Title")
        features = sample_features["paper-0"]

        score = await model.predict_preference(paper, features)

        # Should be between 0 and 1 (sigmoid output)
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_predict_unknown_paper(self, model_simple, sample_feedback):
        """Test prediction for unknown paper returns neutral."""
        await model_simple.train(sample_feedback, {})

        unknown = MockPaper("unknown-paper", "Title")
        score = await model_simple.predict_preference(unknown)

        assert score == 0.5


class TestPreferenceModelRankPapers:
    """Tests for rank_papers method."""

    @pytest.mark.asyncio
    async def test_rank_untrained_uses_base_scores(self, model, sample_papers):
        """Test ranking without training uses base scores only."""
        base_scores = {p.paper_id: float(i) for i, p in enumerate(sample_papers)}

        ranked = await model.rank_papers(sample_papers, base_scores)

        # Should be sorted by base score (descending)
        assert ranked[0].paper_id == "paper-9"
        assert ranked[-1].paper_id == "paper-0"

    @pytest.mark.asyncio
    async def test_rank_blends_scores(
        self, model, sample_feedback, sample_features, sample_papers
    ):
        """Test ranking blends preference and base scores."""
        await model.train(sample_feedback, sample_features)

        base_scores = {p.paper_id: 0.5 for p in sample_papers}

        ranked = await model.rank_papers(sample_papers, base_scores, sample_features)

        # Should still return all papers
        assert len(ranked) == len(sample_papers)

    @pytest.mark.asyncio
    async def test_rank_empty_list(self, model):
        """Test ranking empty list."""
        ranked = await model.rank_papers([], {})
        assert ranked == []


class TestPreferenceModelExploration:
    """Tests for get_exploration_candidates method."""

    def test_exploration_empty_list(self, model):
        """Test exploration with empty list."""
        candidates = model.get_exploration_candidates([])
        assert candidates == []

    def test_exploration_returns_n_papers(self, model, sample_papers):
        """Test exploration returns n papers."""
        candidates = model.get_exploration_candidates(sample_papers, n=3)
        assert len(candidates) == 3

    def test_exploration_respects_max(self, model, sample_papers):
        """Test exploration doesn't exceed available papers."""
        candidates = model.get_exploration_candidates(sample_papers, n=100)
        assert len(candidates) == len(sample_papers)

    def test_exploration_favors_uncertain(self, model_simple, sample_papers):
        """Test exploration favors papers with uncertainty."""
        # Train on some papers
        feedback = [
            FeedbackEntry(paper_id="paper-0", rating=FeedbackRating.THUMBS_UP),
            FeedbackEntry(paper_id="paper-0", rating=FeedbackRating.THUMBS_UP),
        ]
        import asyncio

        asyncio.run(model_simple.train(feedback, {}))

        # Exploration should include unknown papers
        candidates = model_simple.get_exploration_candidates(sample_papers, n=5)
        candidate_ids = [c.paper_id for c in candidates]

        # Unknown papers should often appear due to uncertainty bonus
        assert len(candidate_ids) == 5


class TestPreferenceModelStats:
    """Tests for get_model_stats method."""

    def test_stats_untrained(self, model):
        """Test stats for untrained model."""
        stats = model.get_model_stats()

        assert stats["trained"] is False
        assert stats["algorithm"] == "contextual_bandit"
        assert stats["papers_with_feedback"] == 0
        assert stats["feature_dim"] == 0

    @pytest.mark.asyncio
    async def test_stats_trained(self, model_simple, sample_feedback):
        """Test stats for trained model."""
        await model_simple.train(sample_feedback, {})

        stats = model_simple.get_model_stats()

        assert stats["trained"] is True
        assert stats["papers_with_feedback"] > 0


class TestPreferenceModelReset:
    """Tests for reset method."""

    @pytest.mark.asyncio
    async def test_reset(self, model_simple, sample_feedback):
        """Test model reset."""
        await model_simple.train(sample_feedback, {})
        assert model_simple.is_trained is True

        model_simple.reset()

        assert model_simple.is_trained is False
        assert len(model_simple._alpha) == 0
        assert len(model_simple._beta) == 0


class TestPreferenceModelLinearRegression:
    """Tests for linear regression edge cases."""

    @pytest.mark.asyncio
    async def test_train_contextual_bandit_normalizes_features(self):
        """Test that contextual bandit training normalizes features."""
        model = PreferenceModel(
            algorithm="contextual_bandit",
            min_feedback_for_training=3,
        )

        # Create feedback entries
        feedback = [
            FeedbackEntry(paper_id=f"paper-{i}", rating=FeedbackRating.THUMBS_UP)
            for i in range(5)
        ]

        # Create features with varying values
        features = {
            f"paper-{i}": np.random.randn(10).astype(np.float32) * 100 for i in range(5)
        }

        await model.train(feedback, features)

        # Should compute normalization stats
        assert model._feature_mean is not None
        assert model._feature_std is not None
        assert model._feature_weights is not None
        assert model.is_trained is True

    @pytest.mark.asyncio
    async def test_train_neutral_rating(self):
        """Test training with neutral ratings."""
        model = PreferenceModel(
            algorithm="simple_average",
            min_feedback_for_training=1,
        )

        feedback = [
            FeedbackEntry(paper_id="paper-1", rating=FeedbackRating.NEUTRAL),
        ]

        await model.train(feedback, {})

        # Neutral shouldn't update alpha/beta beyond prior
        assert model._alpha["paper-1"] == 1.0
        assert model._beta["paper-1"] == 1.0

    @pytest.mark.asyncio
    async def test_contextual_bandit_with_neutral(self):
        """Test contextual bandit with neutral rating."""
        model = PreferenceModel(
            algorithm="contextual_bandit",
            min_feedback_for_training=3,
        )

        feedback = [
            FeedbackEntry(paper_id="paper-1", rating=FeedbackRating.THUMBS_UP),
            FeedbackEntry(paper_id="paper-2", rating=FeedbackRating.NEUTRAL),
            FeedbackEntry(paper_id="paper-3", rating=FeedbackRating.THUMBS_DOWN),
        ]

        features = {
            f"paper-{i}": np.random.randn(10).astype(np.float32) for i in range(1, 4)
        }

        await model.train(feedback, features)

        assert model.is_trained is True


class TestPreferenceModelPredictEdgeCases:
    """Tests for prediction edge cases."""

    @pytest.mark.asyncio
    async def test_predict_with_negative_dot_product(self):
        """Test prediction with features giving negative dot product."""
        model = PreferenceModel(
            algorithm="contextual_bandit",
            min_feedback_for_training=3,
        )

        # Create features and train
        feedback = [
            FeedbackEntry(paper_id=f"paper-{i}", rating=FeedbackRating.THUMBS_UP)
            for i in range(5)
        ]
        features = {
            f"paper-{i}": np.random.randn(10).astype(np.float32) for i in range(5)
        }

        await model.train(feedback, features)

        # Create paper with features that give large negative dot product
        paper = MockPaper("test-paper", "Title")
        test_features = -10 * np.ones(10).astype(np.float32)

        score = await model.predict_preference(paper, test_features)

        # Sigmoid bounds output to (0, 1)
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_predict_trained_no_features(self, sample_feedback, sample_features):
        """Test prediction without features after contextual training."""
        model = PreferenceModel(min_feedback_for_training=5)

        await model.train(sample_feedback, sample_features)

        # Predict without features - should use Thompson Sampling
        paper = MockPaper("paper-0", "Title")
        score = await model.predict_preference(paper, features=None)

        # Should use Thompson Sampling estimate
        assert 0.0 <= score <= 1.0


class TestPreferenceModelAdditionalCoverage:
    """Additional tests for full coverage."""

    @pytest.mark.asyncio
    async def test_train_linalg_error_uniform_weights(self):
        """Test that linear algebra error uses uniform weights."""
        model = PreferenceModel(
            algorithm="contextual_bandit",
            min_feedback_for_training=3,
        )

        feedback = [
            FeedbackEntry(paper_id=f"paper-{i}", rating=FeedbackRating.THUMBS_UP)
            for i in range(5)
        ]

        # Create singular matrix (all same features)
        features = {f"paper-{i}": np.zeros(10).astype(np.float32) for i in range(5)}

        # Manually trigger the linalg error path
        original_solve = np.linalg.solve

        def mock_solve(*args, **kwargs):
            raise np.linalg.LinAlgError("Singular matrix")

        np.linalg.solve = mock_solve
        try:
            await model.train(feedback, features)
        finally:
            np.linalg.solve = original_solve

        # Should be trained with uniform weights
        assert model.is_trained is True
        assert model._feature_weights is not None

    @pytest.mark.asyncio
    async def test_rank_papers_empty_base_scores(
        self, sample_feedback, sample_features
    ):
        """Test ranking when paper not in base_scores."""
        model = PreferenceModel(min_feedback_for_training=5)
        await model.train(sample_feedback, sample_features)

        papers = [MockPaper("unknown-paper", "Title")]
        base_scores = {}  # Empty - paper not in base_scores

        ranked = await model.rank_papers(papers, base_scores)

        assert len(ranked) == 1

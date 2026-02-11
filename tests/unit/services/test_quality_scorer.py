"""Tests for QualityScorer service (Phase 3.4)."""

import pytest
from datetime import datetime, timezone, timedelta
import yaml

from src.services.quality_scorer import (
    QualityScorer,
    load_venue_scores,
)
from src.models.paper import PaperMetadata, Author


class TestLoadVenueScores:
    """Tests for load_venue_scores function."""

    def test_load_venue_scores_default_path(self):
        """Test loading venue scores from default path."""
        venues, default = load_venue_scores()
        # Should load successfully (file exists)
        assert isinstance(venues, dict)
        assert isinstance(default, int)
        assert default == 15  # Default score from our YAML

    def test_load_venue_scores_custom_path(self, tmp_path):
        """Test loading venue scores from custom path."""
        custom_yaml = tmp_path / "custom_venues.yaml"
        custom_yaml.write_text(
            yaml.dump(
                {
                    "default_score": 20,
                    "venues": {"nature": 30, "arxiv": 10},
                }
            )
        )

        venues, default = load_venue_scores(custom_yaml)
        assert default == 20
        assert venues["nature"] == 30
        assert venues["arxiv"] == 10

    def test_load_venue_scores_file_not_found(self, tmp_path):
        """Test fallback when file not found."""
        venues, default = load_venue_scores(tmp_path / "nonexistent.yaml")
        assert venues == {}
        assert default == 15  # Fallback default

    def test_load_venue_scores_empty_file(self, tmp_path):
        """Test handling empty YAML file."""
        empty_yaml = tmp_path / "empty.yaml"
        empty_yaml.write_text("")

        venues, default = load_venue_scores(empty_yaml)
        assert venues == {}
        assert default == 15

    def test_load_venue_scores_invalid_yaml(self, tmp_path):
        """Test handling invalid YAML."""
        invalid_yaml = tmp_path / "invalid.yaml"
        invalid_yaml.write_text("not: valid: yaml: {{{{")

        venues, default = load_venue_scores(invalid_yaml)
        assert venues == {}
        assert default == 15

    def test_load_venue_scores_case_insensitive(self, tmp_path):
        """Test that venue names are lowercased."""
        custom_yaml = tmp_path / "venues.yaml"
        custom_yaml.write_text(
            yaml.dump(
                {
                    "default_score": 15,
                    "venues": {"NeurIPS": 30, "EMNLP": 28},
                }
            )
        )

        venues, _ = load_venue_scores(custom_yaml)
        assert "neurips" in venues
        assert "emnlp" in venues
        assert venues["neurips"] == 30


class TestQualityScorerInit:
    """Tests for QualityScorer initialization."""

    def test_default_initialization(self):
        """Test default weight initialization."""
        scorer = QualityScorer()
        assert scorer.citation_weight == 0.40
        assert scorer.venue_weight == 0.30
        assert scorer.recency_weight == 0.20
        assert scorer.completeness_weight == 0.10

    def test_custom_weights(self):
        """Test custom weight initialization."""
        scorer = QualityScorer(
            citation_weight=0.50,
            venue_weight=0.20,
            recency_weight=0.20,
            completeness_weight=0.10,
        )
        assert scorer.citation_weight == 0.50
        assert scorer.venue_weight == 0.20

    def test_invalid_weights_sum(self):
        """Test that weights must sum to 1.0."""
        with pytest.raises(ValueError, match="Weights must sum to 1.0"):
            QualityScorer(
                citation_weight=0.50,
                venue_weight=0.50,
                recency_weight=0.50,
                completeness_weight=0.50,
            )

    def test_weights_tolerance(self):
        """Test weight sum tolerance for floating point."""
        # Should not raise - within tolerance
        scorer = QualityScorer(
            citation_weight=0.401,
            venue_weight=0.299,
            recency_weight=0.20,
            completeness_weight=0.10,
        )
        assert scorer is not None


class TestQualityScorerCitationScore:
    """Tests for citation scoring."""

    @pytest.fixture
    def scorer(self):
        return QualityScorer()

    def test_zero_citations(self, scorer):
        """Test score for zero citations."""
        paper = self._make_paper(citation_count=0)
        score = scorer._citation_score(paper)
        assert score == 0.0

    def test_one_citation(self, scorer):
        """Test score for one citation."""
        paper = self._make_paper(citation_count=1)
        score = scorer._citation_score(paper)
        assert 0.1 < score < 0.2  # log10(2)/3 ≈ 0.1

    def test_ten_citations(self, scorer):
        """Test score for 10 citations."""
        paper = self._make_paper(citation_count=10)
        score = scorer._citation_score(paper)
        assert 0.3 < score < 0.4  # log10(11)/3 ≈ 0.35

    def test_hundred_citations(self, scorer):
        """Test score for 100 citations."""
        paper = self._make_paper(citation_count=100)
        score = scorer._citation_score(paper)
        assert 0.6 < score < 0.7  # log10(101)/3 ≈ 0.67

    def test_thousand_citations(self, scorer):
        """Test score for 1000 citations."""
        paper = self._make_paper(citation_count=1000)
        score = scorer._citation_score(paper)
        assert score == 1.0  # Capped at 1.0

    def test_influential_citations_bonus(self, scorer):
        """Test influential citation bonus."""
        paper_without = self._make_paper(
            citation_count=100, influential_citation_count=0
        )
        paper_with = self._make_paper(citation_count=100, influential_citation_count=10)

        score_without = scorer._citation_score(paper_without)
        score_with = scorer._citation_score(paper_with)

        # Score with influential should be higher
        assert score_with > score_without
        # Bonus capped at 0.1
        assert score_with - score_without <= 0.1

    @staticmethod
    def _make_paper(**kwargs) -> PaperMetadata:
        """Helper to create paper with defaults."""
        defaults = {
            "paper_id": "test123",
            "title": "Test Paper",
            "url": "https://example.com/paper",
            "citation_count": 0,
            "influential_citation_count": 0,
        }
        defaults.update(kwargs)
        return PaperMetadata(**defaults)


class TestQualityScorerVenueScore:
    """Tests for venue scoring."""

    @pytest.fixture
    def scorer(self):
        return QualityScorer()

    def test_top_venue_neurips(self, scorer):
        """Test score for NeurIPS (top venue)."""
        paper = self._make_paper(venue="NeurIPS 2024")
        score = scorer._venue_score(paper)
        assert score == 1.0  # 30/30

    def test_top_venue_acl(self, scorer):
        """Test score for ACL (top venue)."""
        paper = self._make_paper(venue="Proceedings of ACL 2024")
        score = scorer._venue_score(paper)
        assert score == 1.0  # 30/30

    def test_preprint_arxiv(self, scorer):
        """Test score for ArXiv (preprint)."""
        paper = self._make_paper(venue="ArXiv")
        score = scorer._venue_score(paper)
        assert score == 10 / 30  # Lower score for preprint

    def test_unknown_venue(self, scorer):
        """Test score for unknown venue."""
        paper = self._make_paper(venue="Unknown Regional Symposium Proceedings")
        score = scorer._venue_score(paper)
        assert score == 15 / 30  # Default score

    def test_empty_venue(self, scorer):
        """Test score for empty venue."""
        paper = self._make_paper(venue="")
        score = scorer._venue_score(paper)
        assert score == 15 / 30  # Default score

    def test_none_venue(self, scorer):
        """Test score for None venue."""
        paper = self._make_paper(venue=None)
        score = scorer._venue_score(paper)
        assert score == 15 / 30  # Default score

    def test_case_insensitive_matching(self, scorer):
        """Test case insensitive venue matching."""
        paper_upper = self._make_paper(venue="NEURIPS")
        paper_lower = self._make_paper(venue="neurips")
        paper_mixed = self._make_paper(venue="NeurIPS")

        assert scorer._venue_score(paper_upper) == scorer._venue_score(paper_lower)
        assert scorer._venue_score(paper_upper) == scorer._venue_score(paper_mixed)

    def test_partial_matching(self, scorer):
        """Test partial venue matching."""
        paper = self._make_paper(venue="Proceedings of the 2024 Conference EMNLP")
        score = scorer._venue_score(paper)
        assert score == 1.0  # Should match "emnlp"

    @staticmethod
    def _make_paper(**kwargs) -> PaperMetadata:
        """Helper to create paper with defaults."""
        defaults = {
            "paper_id": "test123",
            "title": "Test Paper",
            "url": "https://example.com/paper",
        }
        defaults.update(kwargs)
        return PaperMetadata(**defaults)


class TestQualityScorerRecencyScore:
    """Tests for recency scoring."""

    @pytest.fixture
    def scorer(self):
        return QualityScorer()

    def test_recent_paper_within_year(self, scorer):
        """Test score for paper published within 1 year."""
        pub_date = datetime.now(timezone.utc) - timedelta(days=100)
        paper = self._make_paper(publication_date=pub_date)
        score = scorer._recency_score(paper)
        assert score == 1.0

    def test_paper_one_to_two_years(self, scorer):
        """Test score for paper 1-2 years old."""
        pub_date = datetime.now(timezone.utc) - timedelta(days=500)
        paper = self._make_paper(publication_date=pub_date)
        score = scorer._recency_score(paper)
        assert score == 0.75

    def test_paper_two_to_five_years(self, scorer):
        """Test score for paper 2-5 years old."""
        pub_date = datetime.now(timezone.utc) - timedelta(days=1000)
        paper = self._make_paper(publication_date=pub_date)
        score = scorer._recency_score(paper)
        assert score == 0.50

    def test_paper_older_than_five_years(self, scorer):
        """Test score for paper older than 5 years."""
        pub_date = datetime.now(timezone.utc) - timedelta(days=2000)
        paper = self._make_paper(publication_date=pub_date)
        score = scorer._recency_score(paper)
        assert score == 0.25

    def test_no_publication_date(self, scorer):
        """Test score when publication date is None."""
        paper = self._make_paper(publication_date=None)
        score = scorer._recency_score(paper)
        assert score == 0.5  # Neutral score

    def test_future_date(self, scorer):
        """Test score for future publication date (data error)."""
        pub_date = datetime.now(timezone.utc) + timedelta(days=100)
        paper = self._make_paper(publication_date=pub_date)
        score = scorer._recency_score(paper)
        assert score == 0.5  # Neutral score

    def test_timezone_naive_date(self, scorer):
        """Test handling of timezone-naive dates."""
        pub_date = datetime.utcnow() - timedelta(days=100)  # Naive
        paper = self._make_paper(publication_date=pub_date)
        score = scorer._recency_score(paper)
        assert score == 1.0  # Should handle gracefully

    @staticmethod
    def _make_paper(**kwargs) -> PaperMetadata:
        """Helper to create paper with defaults."""
        defaults = {
            "paper_id": "test123",
            "title": "Test Paper",
            "url": "https://example.com/paper",
        }
        defaults.update(kwargs)
        return PaperMetadata(**defaults)


class TestQualityScorerCompletenessScore:
    """Tests for completeness scoring."""

    @pytest.fixture
    def scorer(self):
        return QualityScorer()

    def test_fully_complete(self, scorer):
        """Test score for paper with all metadata."""
        paper = self._make_paper(
            abstract="This is an abstract.",
            authors=[Author(name="John Doe")],
            doi="10.1234/test",
        )
        score = scorer._completeness_score(paper)
        assert score == 1.0

    def test_abstract_only(self, scorer):
        """Test score for paper with only abstract."""
        paper = self._make_paper(
            abstract="This is an abstract.",
            authors=[],
            doi=None,
        )
        score = scorer._completeness_score(paper)
        assert score == 0.5

    def test_authors_only(self, scorer):
        """Test score for paper with only authors."""
        paper = self._make_paper(
            abstract=None,
            authors=[Author(name="John Doe")],
            doi=None,
        )
        score = scorer._completeness_score(paper)
        assert score == 0.3

    def test_doi_only(self, scorer):
        """Test score for paper with only DOI."""
        paper = self._make_paper(
            abstract=None,
            authors=[],
            doi="10.1234/test",
        )
        score = scorer._completeness_score(paper)
        assert score == 0.2

    def test_empty_paper(self, scorer):
        """Test score for paper with no optional metadata."""
        paper = self._make_paper(
            abstract=None,
            authors=[],
            doi=None,
        )
        score = scorer._completeness_score(paper)
        assert score == 0.0

    def test_empty_string_abstract(self, scorer):
        """Test that empty string abstract scores 0."""
        paper = self._make_paper(
            abstract="",
            authors=[],
            doi=None,
        )
        score = scorer._completeness_score(paper)
        assert score == 0.0

    def test_whitespace_doi(self, scorer):
        """Test that whitespace-only DOI scores 0."""
        paper = self._make_paper(
            abstract=None,
            authors=[],
            doi="   ",
        )
        score = scorer._completeness_score(paper)
        assert score == 0.0

    @staticmethod
    def _make_paper(**kwargs) -> PaperMetadata:
        """Helper to create paper with defaults."""
        defaults = {
            "paper_id": "test123",
            "title": "Test Paper",
            "url": "https://example.com/paper",
            "abstract": None,
            "authors": [],
            "doi": None,
        }
        defaults.update(kwargs)
        return PaperMetadata(**defaults)


class TestQualityScorerCompositeScore:
    """Tests for composite quality score."""

    @pytest.fixture
    def scorer(self):
        return QualityScorer()

    def test_score_range(self, scorer):
        """Test that score is always 0-100."""
        papers = [
            self._make_paper(
                citation_count=0,
                venue=None,
                publication_date=None,
                abstract=None,
            ),
            self._make_paper(
                citation_count=10000,
                venue="NeurIPS",
                publication_date=datetime.now(timezone.utc),
                abstract="Abstract",
                authors=[Author(name="Test")],
                doi="10.1234/test",
            ),
        ]

        for paper in papers:
            score = scorer.score(paper)
            assert 0 <= score <= 100

    def test_high_quality_paper(self, scorer):
        """Test score for high-quality paper."""
        paper = self._make_paper(
            citation_count=500,
            venue="NeurIPS 2023",
            publication_date=datetime.now(timezone.utc) - timedelta(days=180),
            abstract="This is a detailed abstract.",
            authors=[Author(name="Alice"), Author(name="Bob")],
            doi="10.1234/neurips.2023.001",
        )
        score = scorer.score(paper)
        assert score >= 70  # High quality paper

    def test_low_quality_paper(self, scorer):
        """Test score for low-quality paper."""
        paper = self._make_paper(
            citation_count=0,
            venue="Unknown",
            publication_date=datetime.now(timezone.utc) - timedelta(days=3000),
            abstract=None,
            authors=[],
            doi=None,
        )
        score = scorer.score(paper)
        assert score < 40  # Low quality paper

    def test_score_affects_quality_score_field(self, scorer):
        """Test that score populates quality_score field."""
        paper = self._make_paper(citation_count=100)
        assert paper.quality_score == 0.0  # Default

        scorer.score(paper)  # Score doesn't modify the paper

        # rank_papers should modify it
        papers = scorer.rank_papers([paper])
        assert papers[0].quality_score > 0

    @staticmethod
    def _make_paper(**kwargs) -> PaperMetadata:
        """Helper to create paper with defaults."""
        defaults = {
            "paper_id": "test123",
            "title": "Test Paper",
            "url": "https://example.com/paper",
        }
        defaults.update(kwargs)
        return PaperMetadata(**defaults)


class TestQualityScorerRankPapers:
    """Tests for rank_papers method."""

    @pytest.fixture
    def scorer(self):
        return QualityScorer()

    def test_rank_papers_ordering(self, scorer):
        """Test that papers are sorted by quality score descending."""
        papers = [
            self._make_paper(paper_id="low", citation_count=1),
            self._make_paper(paper_id="high", citation_count=1000),
            self._make_paper(paper_id="mid", citation_count=100),
        ]

        ranked = scorer.rank_papers(papers)

        assert ranked[0].paper_id == "high"
        assert ranked[1].paper_id == "mid"
        assert ranked[2].paper_id == "low"

    def test_rank_papers_sets_quality_score(self, scorer):
        """Test that ranking populates quality_score field."""
        papers = [
            self._make_paper(citation_count=100),
        ]

        ranked = scorer.rank_papers(papers)

        assert ranked[0].quality_score > 0

    def test_rank_papers_min_score_filter(self, scorer):
        """Test minimum score filtering."""
        papers = [
            self._make_paper(paper_id="low", citation_count=0),  # Very low score
            self._make_paper(
                paper_id="high",
                citation_count=1000,
                venue="NeurIPS",
                publication_date=datetime.now(timezone.utc),
                abstract="Test",
                authors=[Author(name="Test")],
                doi="10.1234/test",
            ),  # High score
        ]

        # Filter with high min_score
        ranked = scorer.rank_papers(papers, min_score=60)

        assert len(ranked) == 1
        assert ranked[0].paper_id == "high"

    def test_rank_papers_empty_list(self, scorer):
        """Test ranking empty list."""
        ranked = scorer.rank_papers([])
        assert ranked == []

    def test_rank_papers_preserves_original(self, scorer):
        """Test that original list is not modified."""
        papers = [
            self._make_paper(paper_id="a", citation_count=1),
            self._make_paper(paper_id="b", citation_count=100),
        ]
        original_order = [p.paper_id for p in papers]

        scorer.rank_papers(papers)

        # Original list order should be unchanged
        assert [p.paper_id for p in papers] == original_order

    @staticmethod
    def _make_paper(**kwargs) -> PaperMetadata:
        """Helper to create paper with defaults."""
        defaults = {
            "paper_id": "test123",
            "title": "Test Paper",
            "url": "https://example.com/paper",
        }
        defaults.update(kwargs)
        return PaperMetadata(**defaults)


class TestQualityScorerGetQualityTier:
    """Tests for get_quality_tier method."""

    @pytest.fixture
    def scorer(self):
        return QualityScorer()

    def test_excellent_tier(self, scorer):
        """Test excellent tier (80+)."""
        assert scorer.get_quality_tier(80) == "excellent"
        assert scorer.get_quality_tier(100) == "excellent"
        assert scorer.get_quality_tier(90) == "excellent"

    def test_good_tier(self, scorer):
        """Test good tier (60-79)."""
        assert scorer.get_quality_tier(60) == "good"
        assert scorer.get_quality_tier(79) == "good"
        assert scorer.get_quality_tier(70) == "good"

    def test_fair_tier(self, scorer):
        """Test fair tier (40-59)."""
        assert scorer.get_quality_tier(40) == "fair"
        assert scorer.get_quality_tier(59) == "fair"
        assert scorer.get_quality_tier(50) == "fair"

    def test_low_tier(self, scorer):
        """Test low tier (<40)."""
        assert scorer.get_quality_tier(0) == "low"
        assert scorer.get_quality_tier(39) == "low"
        assert scorer.get_quality_tier(20) == "low"

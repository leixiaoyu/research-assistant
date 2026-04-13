"""Unit tests for QualityIntelligenceService.

Tests the unified quality scoring service with 6 configurable signals:
- Citation impact (with influential bonus)
- Venue reputation
- Publication recency
- Community engagement
- Metadata completeness
- Author reputation

Coverage target: ≥99%
"""

import math
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.models.discovery import QualityWeights, ScoredPaper
from src.models.paper import PaperMetadata, Author
from src.services.quality_intelligence_service import QualityIntelligenceService
from src.services.venue_repository import VenueRepository
from tests.conftest_types import make_url

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_venue_repository() -> MagicMock:
    """Mock venue repository for testing."""
    repo = MagicMock(spec=VenueRepository)
    repo.get_default_score.return_value = 0.5
    repo.get_score.return_value = 0.8  # Default mock return
    return repo  # type: ignore[return-value]


@pytest.fixture
def default_service(
    mock_venue_repository: MagicMock,
) -> QualityIntelligenceService:
    """Service with default weights and mocked venue repository."""
    return QualityIntelligenceService(venue_repository=mock_venue_repository)


@pytest.fixture
def sample_paper() -> PaperMetadata:
    """Create a sample paper with complete metadata."""
    return PaperMetadata(
        paper_id="2301.12345",
        title="Sample Paper on Machine Learning",
        abstract=(
            "This is a sufficiently long abstract that exceeds the minimum "
            "length requirement for completeness scoring. It contains "
            "multiple sentences and provides detailed information."
        ),
        doi="10.1234/sample.2023",
        url=make_url("https://arxiv.org/abs/2301.12345"),
        open_access_pdf=make_url("https://arxiv.org/pdf/2301.12345.pdf"),
        authors=[Author(name="Alice Researcher"), Author(name="Bob Scientist")],
        publication_date=datetime(2023, 1, 15, tzinfo=timezone.utc),
        venue="NeurIPS 2023",
        citation_count=100,
    )


# ============================================================================
# Initialization Tests
# ============================================================================


def test_init_with_defaults(mock_venue_repository: MagicMock) -> None:
    """Test initialization with default weights."""
    service = QualityIntelligenceService(venue_repository=mock_venue_repository)

    assert service.weights.citation == 0.25
    assert service.weights.venue == 0.20
    assert service.weights.recency == 0.20
    assert service.weights.engagement == 0.15
    assert service.weights.completeness == 0.10
    assert service.weights.author == 0.10
    assert service.min_citations == 0
    assert service.venue_repository == mock_venue_repository


def test_init_with_custom_weights(mock_venue_repository: MagicMock) -> None:
    """Test initialization with custom weights."""
    weights = QualityWeights(
        citation=0.3,
        venue=0.2,
        recency=0.2,
        engagement=0.15,
        completeness=0.1,
        author=0.05,
    )

    service = QualityIntelligenceService(
        weights=weights,
        venue_repository=mock_venue_repository,
        min_citations=5,
    )

    assert service.weights == weights
    assert service.min_citations == 5


def test_init_with_invalid_weights(mock_venue_repository: MagicMock) -> None:
    """Test initialization fails with weights that don't sum to 1.0."""
    invalid_weights = QualityWeights(
        citation=0.5,
        venue=0.3,
        recency=0.1,
        engagement=0.05,
        completeness=0.02,
        author=0.01,  # Sum = 0.98 (outside tolerance)
    )

    with pytest.raises(ValueError, match="Weights must sum to 1.0"):
        QualityIntelligenceService(
            weights=invalid_weights,
            venue_repository=mock_venue_repository,
        )


# ============================================================================
# Citation Score Tests
# ============================================================================


def test_citation_score_zero_citations(
    default_service: QualityIntelligenceService,
) -> None:
    """Test citation score with zero citations."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        citation_count=0,
    )

    score = default_service._calculate_citation_score(paper)
    assert score == 0.0


def test_citation_score_no_citation_count(
    default_service: QualityIntelligenceService,
) -> None:
    """Test citation score defaults to 0 when citation_count is 0."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        citation_count=0,  # citation_count has default of 0, not None
    )

    score = default_service._calculate_citation_score(paper)
    assert score == 0.0


def test_citation_score_log_normalization(
    default_service: QualityIntelligenceService,
) -> None:
    """Test citation score uses log1p normalization (SS source, known 0 influential)."""
    test_cases = [
        (10, math.log1p(10) / 10.0),
        (100, math.log1p(100) / 10.0),
        (1000, math.log1p(1000) / 10.0),
    ]

    for citations, expected in test_cases:
        paper = PaperMetadata(
            paper_id="test",
            title="Test",
            url=make_url("https://example.com"),
            citation_count=citations,
            influential_citation_count=0,  # SS source with known 0 influential
        )
        score = default_service._calculate_citation_score(paper)
        assert abs(score - expected) < 0.01


def test_citation_score_with_influential_bonus(
    default_service: QualityIntelligenceService,
) -> None:
    """Test citation score includes influential citation bonus."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        citation_count=100,
        influential_citation_count=5,  # Semantic Scholar provides this field
    )

    score = default_service._calculate_citation_score(paper)

    # Base score + bonus
    base = math.log1p(100) / 10.0
    bonus = min(0.1, 5 * 0.01)
    expected = base + bonus

    assert abs(score - expected) < 0.01


def test_citation_score_influential_bonus_cap(
    default_service: QualityIntelligenceService,
) -> None:
    """Test influential bonus capped at 0.1."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        citation_count=100,
        influential_citation_count=50,  # High influential count
    )

    score = default_service._calculate_citation_score(paper)

    # Bonus should be capped at 0.1
    base = math.log1p(100) / 10.0
    expected = base + 0.1

    assert abs(score - expected) < 0.01


def test_citation_score_no_influential_data(
    default_service: QualityIntelligenceService,
) -> None:
    """Test citation score when influential data unavailable (non-SS provider)."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        citation_count=100,
        influential_citation_count=None,  # Explicitly None (ArXiv, OpenAlex, etc.)
    )

    score = default_service._calculate_citation_score(paper)

    # Should use base score + neutral bonus (0.05) to prevent provider bias
    expected = math.log1p(100) / 10.0 + 0.05
    assert abs(score - expected) < 0.01


def test_citation_score_capped_at_one(
    default_service: QualityIntelligenceService,
) -> None:
    """Test citation score capped at 1.0."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        citation_count=100000,  # Very high citation count
    )

    score = default_service._calculate_citation_score(paper)
    assert score <= 1.0


# ============================================================================
# Venue Score Tests
# ============================================================================


def test_venue_score_delegates_to_repository(
    mock_venue_repository: MagicMock,
) -> None:
    """Test venue score delegates to injected repository."""
    mock_venue_repository.get_score.return_value = 0.95

    service = QualityIntelligenceService(venue_repository=mock_venue_repository)
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        venue="NeurIPS 2023",
    )

    score = service._calculate_venue_score(paper)

    mock_venue_repository.get_score.assert_called_once_with("NeurIPS 2023")
    assert score == 0.95


def test_venue_score_missing_venue(mock_venue_repository: MagicMock) -> None:
    """Test venue score with missing venue."""
    mock_venue_repository.get_default_score.return_value = 0.5

    service = QualityIntelligenceService(venue_repository=mock_venue_repository)
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        venue=None,
    )

    score = service._calculate_venue_score(paper)

    mock_venue_repository.get_default_score.assert_called_once()
    assert score == 0.5


def test_venue_score_empty_venue(mock_venue_repository: MagicMock) -> None:
    """Test venue score with empty venue string."""
    mock_venue_repository.get_default_score.return_value = 0.5

    service = QualityIntelligenceService(venue_repository=mock_venue_repository)
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        venue="",
    )

    score = service._calculate_venue_score(paper)

    mock_venue_repository.get_default_score.assert_called_once()
    assert score == 0.5


# ============================================================================
# Recency Score Tests
# ============================================================================


def test_recency_score_current_year(
    default_service: QualityIntelligenceService,
) -> None:
    """Test recency score for current year publication."""
    current_year = datetime.now(timezone.utc).year
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        publication_date=datetime(current_year, 1, 1, tzinfo=timezone.utc),
    )

    score = default_service._calculate_recency_score(paper)
    assert score == 1.0  # Current year = full score


def test_recency_score_one_year_old(
    default_service: QualityIntelligenceService,
) -> None:
    """Test recency score for 1-year-old paper."""
    current_year = datetime.now(timezone.utc).year
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        publication_date=datetime(current_year - 1, 1, 1, tzinfo=timezone.utc),
    )

    score = default_service._calculate_recency_score(paper)
    expected = 1.0 / (1 + 0.2 * 1)  # ~0.83
    assert abs(score - expected) < 0.01


def test_recency_score_five_years_old(
    default_service: QualityIntelligenceService,
) -> None:
    """Test recency score for 5-year-old paper."""
    current_year = datetime.now(timezone.utc).year
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        publication_date=datetime(current_year - 5, 1, 1, tzinfo=timezone.utc),
    )

    score = default_service._calculate_recency_score(paper)
    expected = 1.0 / (1 + 0.2 * 5)  # 0.5
    assert abs(score - expected) < 0.01


def test_recency_score_floor(default_service: QualityIntelligenceService) -> None:
    """Test recency score has floor of 0.1."""
    current_year = datetime.now(timezone.utc).year
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        publication_date=datetime(current_year - 50, 1, 1, tzinfo=timezone.utc),
    )

    score = default_service._calculate_recency_score(paper)
    assert score >= 0.1  # Floor value


def test_recency_score_full_date_string(
    default_service: QualityIntelligenceService,
) -> None:
    """Test recency score with datetime object."""
    current_year = datetime.now(timezone.utc).year
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        publication_date=datetime(current_year - 2, 6, 15, tzinfo=timezone.utc),
    )

    score = default_service._calculate_recency_score(paper)
    expected = 1.0 / (1 + 0.2 * 2)  # ~0.71
    assert abs(score - expected) < 0.01


def test_recency_score_datetime_object(
    default_service: QualityIntelligenceService,
) -> None:
    """Test recency score with datetime object."""
    current_year = datetime.now(timezone.utc).year
    pub_date = datetime(current_year - 3, 1, 1, tzinfo=timezone.utc)

    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        publication_date=pub_date,
    )

    score = default_service._calculate_recency_score(paper)
    expected = 1.0 / (1 + 0.2 * 3)  # ~0.625
    assert abs(score - expected) < 0.01


def test_recency_score_missing_date(
    default_service: QualityIntelligenceService,
) -> None:
    """Test recency score with missing publication date."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        publication_date=None,
    )

    score = default_service._calculate_recency_score(paper)
    assert score == 0.5  # Default neutral score


def test_recency_score_invalid_date_format(
    default_service: QualityIntelligenceService,
) -> None:
    """Test recency score with None date (Pydantic validates datetime type)."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        publication_date=None,
    )

    score = default_service._calculate_recency_score(paper)
    assert score == 0.5  # Default for missing date


def test_recency_score_string_year_only(
    default_service: QualityIntelligenceService,
) -> None:
    """Test recency score with string year (YYYY format)."""
    current_year = datetime.now(timezone.utc).year
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
    )
    # Bypass Pydantic validation to test string handling
    object.__setattr__(paper, "publication_date", str(current_year - 2))

    score = default_service._calculate_recency_score(paper)
    expected = 1.0 / (1 + 0.2 * 2)  # ~0.71
    assert abs(score - expected) < 0.01


def test_recency_score_string_year_month(
    default_service: QualityIntelligenceService,
) -> None:
    """Test recency score with string YYYY-MM format."""
    current_year = datetime.now(timezone.utc).year
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
    )
    # Bypass Pydantic validation to test string handling
    object.__setattr__(paper, "publication_date", f"{current_year - 1}-06")

    score = default_service._calculate_recency_score(paper)
    expected = 1.0 / (1 + 0.2 * 1)  # ~0.83
    assert abs(score - expected) < 0.01


def test_recency_score_string_too_short(
    default_service: QualityIntelligenceService,
) -> None:
    """Test recency score with invalid short string."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
    )
    # Bypass Pydantic validation to test error handling
    object.__setattr__(paper, "publication_date", "202")  # Too short

    score = default_service._calculate_recency_score(paper)
    assert score == 0.5  # Default for invalid format


def test_recency_score_string_invalid_year(
    default_service: QualityIntelligenceService,
) -> None:
    """Test recency score with non-numeric year string."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
    )
    # Bypass Pydantic validation to test error handling
    object.__setattr__(paper, "publication_date", "abcd")

    score = default_service._calculate_recency_score(paper)
    assert score == 0.5  # Default for ValueError


# ============================================================================
# Engagement Score Tests
# ============================================================================


def test_engagement_score_zero_upvotes(
    default_service: QualityIntelligenceService,
) -> None:
    """Test engagement score with zero upvotes returns neutral 0.5."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
    )
    # Dynamically add upvotes attribute (simulating HuggingFace paper)
    # Use object.__setattr__ to bypass Pydantic validation
    object.__setattr__(paper, "upvotes", 0)

    score = default_service._calculate_engagement_score(paper)
    assert score == 0.5  # Neutral, not 0.0


def test_engagement_score_missing_upvotes(
    default_service: QualityIntelligenceService,
) -> None:
    """Test engagement score with missing upvotes attribute."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
    )
    # No upvotes attribute (non-HuggingFace paper)

    score = default_service._calculate_engagement_score(paper)
    assert score == 0.5  # Neutral for missing data


def test_engagement_score_log_normalization(
    default_service: QualityIntelligenceService,
) -> None:
    """Test engagement score uses log1p normalization."""
    test_cases = [
        (10, math.log1p(10) / 7.0),
        (100, math.log1p(100) / 7.0),
        (500, math.log1p(500) / 7.0),
    ]

    for upvotes, expected in test_cases:
        paper = PaperMetadata(
            paper_id="test",
            title="Test",
            url=make_url("https://example.com"),
        )
        object.__setattr__(paper, "upvotes", upvotes)

        score = default_service._calculate_engagement_score(paper)
        assert abs(score - expected) < 0.01


def test_engagement_score_capped_at_one(
    default_service: QualityIntelligenceService,
) -> None:
    """Test engagement score capped at 1.0."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
    )
    object.__setattr__(paper, "upvotes", 100000)

    score = default_service._calculate_engagement_score(paper)
    assert score <= 1.0


# ============================================================================
# Completeness Score Tests
# ============================================================================


def test_completeness_score_all_fields_present(
    default_service: QualityIntelligenceService,
) -> None:
    """Test completeness score with all fields present."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        abstract=(
            "A sufficiently long abstract with more than fifty " "characters in total."
        ),
        authors=[Author(name="Author One"), Author(name="Author Two")],
        venue="NeurIPS 2023",
        open_access_pdf=make_url("https://example.com/paper.pdf"),
        doi="10.1234/test",
    )

    score = default_service._calculate_completeness_score(paper)
    assert score == 1.0  # All fields present


def test_completeness_score_missing_abstract(
    default_service: QualityIntelligenceService,
) -> None:
    """Test completeness score with missing abstract."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        abstract=None,
        authors=[Author(name="Author")],
        venue="NeurIPS",
        open_access_pdf=make_url("https://example.com/paper.pdf"),
        doi="10.1234/test",
    )

    score = default_service._calculate_completeness_score(paper)
    expected = (0.2 + 0.2 + 0.2 + 0.1) / 1.0  # Missing 0.3 for abstract
    assert abs(score - expected) < 0.01


def test_completeness_score_short_abstract(
    default_service: QualityIntelligenceService,
) -> None:
    """Test completeness score with abstract shorter than 50 chars."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        abstract="Short",  # Less than MIN_ABSTRACT_LENGTH
        authors=[Author(name="Author")],
        venue="NeurIPS",
        open_access_pdf=make_url("https://example.com/paper.pdf"),
        doi="10.1234/test",
    )

    score = default_service._calculate_completeness_score(paper)
    expected = (0.2 + 0.2 + 0.2 + 0.1) / 1.0  # Abstract too short
    assert abs(score - expected) < 0.01


def test_completeness_score_missing_authors(
    default_service: QualityIntelligenceService,
) -> None:
    """Test completeness score with missing authors."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        abstract=(
            "A sufficiently long abstract with more than fifty " "characters in total."
        ),
        authors=[],
        venue="NeurIPS",
        open_access_pdf=make_url("https://example.com/paper.pdf"),
        doi="10.1234/test",
    )

    score = default_service._calculate_completeness_score(paper)
    expected = (0.3 + 0.2 + 0.2 + 0.1) / 1.0  # Missing 0.2 for authors
    assert abs(score - expected) < 0.01


def test_completeness_score_missing_venue(
    default_service: QualityIntelligenceService,
) -> None:
    """Test completeness score with missing venue."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        abstract=(
            "A sufficiently long abstract with more than fifty " "characters in total."
        ),
        authors=[Author(name="Author")],
        venue=None,
        open_access_pdf=make_url("https://example.com/paper.pdf"),
        doi="10.1234/test",
    )

    score = default_service._calculate_completeness_score(paper)
    expected = (0.3 + 0.2 + 0.2 + 0.1) / 1.0  # Missing 0.2 for venue
    assert abs(score - expected) < 0.01


def test_completeness_score_missing_pdf(
    default_service: QualityIntelligenceService,
) -> None:
    """Test completeness score with missing PDF."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        abstract=(
            "A sufficiently long abstract with more than fifty " "characters in total."
        ),
        authors=[Author(name="Author")],
        venue="NeurIPS",
        open_access_pdf=None,
        doi="10.1234/test",
    )

    score = default_service._calculate_completeness_score(paper)
    expected = (0.3 + 0.2 + 0.2 + 0.1) / 1.0  # Missing 0.2 for PDF
    assert abs(score - expected) < 0.01


def test_completeness_score_missing_doi(
    default_service: QualityIntelligenceService,
) -> None:
    """Test completeness score with missing DOI."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        abstract=(
            "A sufficiently long abstract with more than fifty " "characters in total."
        ),
        authors=[Author(name="Author")],
        venue="NeurIPS",
        open_access_pdf=make_url("https://example.com/paper.pdf"),
        doi=None,
    )

    score = default_service._calculate_completeness_score(paper)
    expected = (0.3 + 0.2 + 0.2 + 0.2) / 1.0  # Missing 0.1 for DOI
    assert abs(score - expected) < 0.01


def test_completeness_score_all_fields_missing(
    default_service: QualityIntelligenceService,
) -> None:
    """Test completeness score with all fields missing."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        abstract=None,
        authors=[],
        venue=None,
        open_access_pdf=None,
        doi=None,
    )

    score = default_service._calculate_completeness_score(paper)
    assert score == 0.0  # No fields present


# ============================================================================
# Author Score Tests
# ============================================================================


def test_author_score_returns_default(
    default_service: QualityIntelligenceService,
) -> None:
    """Test author score returns neutral 0.5 (placeholder)."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
    )

    score = default_service._calculate_author_score(paper)
    assert score == 0.5  # Placeholder implementation


# ============================================================================
# Composite Scoring Tests
# ============================================================================


def test_score_paper_returns_scored_paper(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
) -> None:
    """Test score_paper returns ScoredPaper object."""
    scored = default_service.score_paper(sample_paper)

    assert isinstance(scored, ScoredPaper)
    assert scored.paper_id == sample_paper.paper_id
    assert scored.title == sample_paper.title
    assert 0.0 <= scored.quality_score <= 1.0


def test_score_paper_uses_weights(
    mock_venue_repository: MagicMock,
    sample_paper: PaperMetadata,
) -> None:
    """Test score_paper applies configured weights."""
    # Custom weights with heavy citation emphasis
    weights = QualityWeights(
        citation=0.5,
        venue=0.2,
        recency=0.1,
        engagement=0.1,
        completeness=0.05,
        author=0.05,
    )

    service = QualityIntelligenceService(
        weights=weights,
        venue_repository=mock_venue_repository,
    )

    scored = service.score_paper(sample_paper)
    assert 0.0 <= scored.quality_score <= 1.0


def test_score_paper_deterministic(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
) -> None:
    """Test score_paper is deterministic (same input = same output)."""
    scored1 = default_service.score_paper(sample_paper)
    scored2 = default_service.score_paper(sample_paper)

    assert scored1.quality_score == scored2.quality_score


def test_score_papers_batch(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
) -> None:
    """Test score_papers processes multiple papers."""
    papers = [sample_paper, sample_paper, sample_paper]

    scored = default_service.score_papers(papers)

    assert len(scored) == 3
    assert all(isinstance(p, ScoredPaper) for p in scored)


def test_score_papers_empty_list(
    default_service: QualityIntelligenceService,
) -> None:
    """Test score_papers with empty list."""
    scored = default_service.score_papers([])
    assert scored == []


# ============================================================================
# Filtering Tests
# ============================================================================


def test_filter_by_quality_applies_threshold(
    default_service: QualityIntelligenceService,
    mock_venue_repository: MagicMock,
) -> None:
    """Test filter_by_quality filters papers below threshold."""
    # Create papers with varying quality
    high_quality = PaperMetadata(
        paper_id="high",
        title="High Quality Paper",
        url=make_url("https://example.com"),
        abstract="A sufficiently long abstract with more than fifty characters.",
        authors=[Author(name="Author")],
        venue="NeurIPS",
        citation_count=500,
        publication_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        doi="10.1234/high",
        open_access_pdf=make_url("https://example.com/high.pdf"),
    )

    low_quality = PaperMetadata(
        paper_id="low",
        title="Low Quality Paper",
        url=make_url("https://example.com"),
        citation_count=0,
        publication_date=datetime(1990, 1, 1, tzinfo=timezone.utc),
        abstract=None,
        authors=[],
        venue=None,
    )

    mock_venue_repository.get_score.return_value = 0.8

    filtered = default_service.filter_by_quality(
        [high_quality, low_quality], min_score=0.5
    )

    # Only high quality paper should pass
    assert len(filtered) == 1
    assert filtered[0].paper_id == "high"


def test_filter_by_quality_applies_min_citations(
    mock_venue_repository: MagicMock,
    sample_paper: PaperMetadata,
) -> None:
    """Test filter_by_quality pre-filters by citation count."""
    service = QualityIntelligenceService(
        venue_repository=mock_venue_repository,
        min_citations=50,
    )

    low_citation_paper = PaperMetadata(
        paper_id="low",
        title="Low Citation Paper",
        url=make_url("https://example.com"),
        citation_count=10,
    )

    high_citation_paper = PaperMetadata(
        paper_id="high",
        title="High Citation Paper",
        url=make_url("https://example.com"),
        citation_count=100,
    )

    filtered = service.filter_by_quality(
        [low_citation_paper, high_citation_paper],
        min_score=0.0,
    )

    # Only paper with ≥50 citations should remain
    assert len(filtered) == 1
    assert filtered[0].paper_id == "high"


def test_filter_by_quality_empty_input(
    default_service: QualityIntelligenceService,
) -> None:
    """Test filter_by_quality with empty input."""
    filtered = default_service.filter_by_quality([], min_score=0.5)
    assert filtered == []


# ============================================================================
# Quality Tier Tests
# ============================================================================


def test_get_tier_excellent(default_service: QualityIntelligenceService) -> None:
    """Test get_tier returns 'excellent' for scores ≥0.80."""
    assert default_service.get_tier(0.80) == "excellent"
    assert default_service.get_tier(0.95) == "excellent"
    assert default_service.get_tier(1.0) == "excellent"


def test_get_tier_good(default_service: QualityIntelligenceService) -> None:
    """Test get_tier returns 'good' for scores ≥0.60 and <0.80."""
    assert default_service.get_tier(0.60) == "good"
    assert default_service.get_tier(0.70) == "good"
    assert default_service.get_tier(0.79) == "good"


def test_get_tier_fair(default_service: QualityIntelligenceService) -> None:
    """Test get_tier returns 'fair' for scores ≥0.40 and <0.60."""
    assert default_service.get_tier(0.40) == "fair"
    assert default_service.get_tier(0.50) == "fair"
    assert default_service.get_tier(0.59) == "fair"


def test_get_tier_low(default_service: QualityIntelligenceService) -> None:
    """Test get_tier returns 'low' for scores <0.40."""
    assert default_service.get_tier(0.0) == "low"
    assert default_service.get_tier(0.20) == "low"
    assert default_service.get_tier(0.39) == "low"


# ============================================================================
# Edge Case Tests
# ============================================================================


def test_score_paper_with_minimal_metadata(
    default_service: QualityIntelligenceService,
) -> None:
    """Test scoring paper with minimal metadata doesn't crash."""
    minimal_paper = PaperMetadata(
        paper_id="minimal",
        title="Minimal Paper",
        url=make_url("https://example.com"),
    )

    scored = default_service.score_paper(minimal_paper)

    assert isinstance(scored, ScoredPaper)
    assert 0.0 <= scored.quality_score <= 1.0


def test_score_paper_with_zero_citation_count(
    default_service: QualityIntelligenceService,
) -> None:
    """Test scoring paper with zero citation_count (default)."""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url=make_url("https://example.com"),
        citation_count=0,  # Default value, not None
    )

    scored = default_service.score_paper(paper)
    assert isinstance(scored, ScoredPaper)


def test_score_clamped_to_valid_range(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
) -> None:
    """Test final score is always in [0.0, 1.0] range."""
    scored = default_service.score_paper(sample_paper)

    assert 0.0 <= scored.quality_score <= 1.0


# ============================================================================
# Legacy Compatibility Tests
# ============================================================================


def test_score_legacy_returns_0_100_scale(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
) -> None:
    """Test score_legacy returns score on 0-100 scale."""
    score = default_service.score_legacy(sample_paper)

    assert 0.0 <= score <= 100.0
    assert isinstance(score, float)


def test_score_legacy_matches_normalized_score(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
) -> None:
    """Test score_legacy is score_paper * 100."""
    legacy_score = default_service.score_legacy(sample_paper)
    normalized_score = default_service.score_paper(sample_paper).quality_score

    assert abs(legacy_score - (normalized_score * 100.0)) < 0.01


def test_score_legacy_emits_deprecation_warning(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
    capsys: pytest.CaptureFixture,
) -> None:
    """Test score_legacy emits deprecation warning."""
    # Reset class-level flag for this test
    QualityIntelligenceService._warned_score_legacy = False

    default_service.score_legacy(sample_paper)

    # Check warning was logged to stdout (structlog output)
    captured = capsys.readouterr()
    assert "score_legacy is deprecated" in captured.out
    assert "deprecation_warning" in captured.out


def test_score_legacy_warning_only_once(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
    capsys: pytest.CaptureFixture,
) -> None:
    """Test score_legacy warning only emitted once."""
    # Reset flag
    QualityIntelligenceService._warned_score_legacy = False

    default_service.score_legacy(sample_paper)
    default_service.score_legacy(sample_paper)
    default_service.score_legacy(sample_paper)

    # Check output - should only have one warning
    captured = capsys.readouterr()
    warning_count = captured.out.count("score_legacy is deprecated")
    assert warning_count == 1


def test_rank_papers_legacy_returns_sorted_papers(
    default_service: QualityIntelligenceService,
    mock_venue_repository: MagicMock,
) -> None:
    """Test rank_papers_legacy returns papers sorted by quality_score."""
    # Create papers with different quality
    high_quality = PaperMetadata(
        paper_id="high",
        title="High",
        url=make_url("https://example.com"),
        citation_count=500,
        abstract="A sufficiently long abstract with more than fifty characters.",
        authors=[Author(name="Author")],
        venue="NeurIPS",
        doi="10.1234/high",
        open_access_pdf=make_url("https://example.com/high.pdf"),
    )

    medium_quality = PaperMetadata(
        paper_id="medium",
        title="Medium",
        url=make_url("https://example.com"),
        citation_count=100,
    )

    low_quality = PaperMetadata(
        paper_id="low",
        title="Low",
        url=make_url("https://example.com"),
        citation_count=10,
    )

    mock_venue_repository.get_score.return_value = 0.8

    papers = [low_quality, high_quality, medium_quality]
    ranked = default_service.rank_papers_legacy(papers, min_score=0.0)

    # Should be sorted descending
    assert ranked[0].paper_id == "high"
    assert ranked[1].paper_id == "medium"
    assert ranked[2].paper_id == "low"


def test_rank_papers_legacy_mutates_quality_score(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
) -> None:
    """Test rank_papers_legacy sets quality_score attribute on papers."""
    papers = [sample_paper]
    ranked = default_service.rank_papers_legacy(papers, min_score=0.0)

    # Original paper should have quality_score set
    assert sample_paper.quality_score is not None
    assert 0.0 <= sample_paper.quality_score <= 100.0
    assert sample_paper.quality_score == ranked[0].quality_score


def test_rank_papers_legacy_filters_by_min_score(
    default_service: QualityIntelligenceService,
    mock_venue_repository: MagicMock,
) -> None:
    """Test rank_papers_legacy filters papers below min_score."""
    high_quality = PaperMetadata(
        paper_id="high",
        title="High",
        url=make_url("https://example.com"),
        citation_count=500,
        abstract="A sufficiently long abstract with more than fifty characters.",
        authors=[Author(name="Author")],
        venue="NeurIPS",
        doi="10.1234/high",
        open_access_pdf=make_url("https://example.com/high.pdf"),
        publication_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    low_quality = PaperMetadata(
        paper_id="low",
        title="Low",
        url=make_url("https://example.com"),
        citation_count=0,
    )

    mock_venue_repository.get_score.return_value = 0.8

    papers = [high_quality, low_quality]
    ranked = default_service.rank_papers_legacy(papers, min_score=50.0)

    # Only high quality paper should pass
    assert len(ranked) == 1
    assert ranked[0].paper_id == "high"
    assert ranked[0].quality_score >= 50.0


def test_rank_papers_legacy_empty_list(
    default_service: QualityIntelligenceService,
) -> None:
    """Test rank_papers_legacy with empty list."""
    ranked = default_service.rank_papers_legacy([], min_score=0.0)
    assert ranked == []


def test_rank_papers_legacy_emits_deprecation_warning(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
    capsys: pytest.CaptureFixture,
) -> None:
    """Test rank_papers_legacy emits deprecation warning."""
    # Reset flag
    QualityIntelligenceService._warned_rank_papers_legacy = False

    default_service.rank_papers_legacy([sample_paper], min_score=0.0)

    # Check warning was logged to stdout (structlog output)
    captured = capsys.readouterr()
    assert "rank_papers_legacy is deprecated" in captured.out
    assert "deprecation_warning" in captured.out


def test_rank_papers_legacy_0_100_scale(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
) -> None:
    """Test rank_papers_legacy uses 0-100 scale for min_score and quality_score."""
    papers = [sample_paper]
    ranked = default_service.rank_papers_legacy(papers, min_score=0.0)

    # Quality score should be on 0-100 scale
    assert 0.0 <= ranked[0].quality_score <= 100.0


def test_filter_and_score_returns_scored_papers(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
) -> None:
    """Test filter_and_score returns ScoredPaper objects."""
    papers = [sample_paper]
    scored = default_service.filter_and_score(papers)

    assert len(scored) == 1
    assert isinstance(scored[0], ScoredPaper)
    assert 0.0 <= scored[0].quality_score <= 1.0


def test_filter_and_score_uses_custom_weights(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
) -> None:
    """Test filter_and_score accepts custom weights."""
    custom_weights = {
        "citation": 0.5,
        "venue": 0.2,
        "recency": 0.1,
        "engagement": 0.1,
        "completeness": 0.05,
        "author": 0.05,
    }

    papers = [sample_paper]
    scored = default_service.filter_and_score(papers, weights=custom_weights)

    assert len(scored) == 1
    assert isinstance(scored[0], ScoredPaper)


def test_filter_and_score_uses_service_weights_if_none(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
) -> None:
    """Test filter_and_score uses service weights when weights=None."""
    papers = [sample_paper]
    scored_with_none = default_service.filter_and_score(papers, weights=None)
    scored_default = default_service.score_papers(papers)

    # Should produce same results
    assert len(scored_with_none) == len(scored_default)
    assert (
        abs(scored_with_none[0].quality_score - scored_default[0].quality_score) < 0.01
    )


def test_filter_and_score_validates_custom_weights(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
) -> None:
    """Test filter_and_score validates custom weights sum to 1.0."""
    invalid_weights = {
        "citation": 0.5,
        "venue": 0.3,
        "recency": 0.1,
        "engagement": 0.05,
        "completeness": 0.02,
        "author": 0.01,  # Sum = 0.98
    }

    papers = [sample_paper]

    with pytest.raises(ValueError, match="Weights must sum to 1.0"):
        default_service.filter_and_score(papers, weights=invalid_weights)


def test_filter_and_score_emits_deprecation_warning(
    default_service: QualityIntelligenceService,
    sample_paper: PaperMetadata,
    capsys: pytest.CaptureFixture,
) -> None:
    """Test filter_and_score emits deprecation warning."""
    # Reset flag
    QualityIntelligenceService._warned_filter_and_score = False

    default_service.filter_and_score([sample_paper])

    # Check warning was logged to stdout (structlog output)
    captured = capsys.readouterr()
    assert "filter_and_score is deprecated" in captured.out
    assert "deprecation_warning" in captured.out


def test_filter_and_score_empty_list(
    default_service: QualityIntelligenceService,
) -> None:
    """Test filter_and_score with empty list."""
    scored = default_service.filter_and_score([])
    assert scored == []


def test_legacy_methods_integration(
    default_service: QualityIntelligenceService,
    mock_venue_repository: MagicMock,
) -> None:
    """Integration test: All legacy methods work together."""
    # Create test papers
    papers = [
        PaperMetadata(
            paper_id=f"paper_{i}",
            title=f"Paper {i}",
            url=make_url("https://example.com"),
            citation_count=i * 100,
            abstract="A sufficiently long abstract with more than fifty characters.",
            authors=[Author(name="Author")],
            venue="NeurIPS",
        )
        for i in range(3)
    ]

    mock_venue_repository.get_score.return_value = 0.8

    # Test score_legacy
    for paper in papers:
        score = default_service.score_legacy(paper)
        assert 0.0 <= score <= 100.0

    # Test rank_papers_legacy
    ranked = default_service.rank_papers_legacy(papers, min_score=0.0)
    assert len(ranked) == 3
    assert all(hasattr(p, "quality_score") for p in ranked)
    assert all(p.quality_score is not None for p in ranked)

    # Test filter_and_score
    scored = default_service.filter_and_score(papers)
    assert len(scored) == 3
    assert all(isinstance(p, ScoredPaper) for p in scored)

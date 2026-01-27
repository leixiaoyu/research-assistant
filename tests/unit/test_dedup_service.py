"""Unit tests for deduplication service"""

import pytest
from src.services.dedup_service import DeduplicationService
from src.models.dedup import DedupConfig
from src.models.paper import PaperMetadata


@pytest.fixture
def dedup_service():
    """Create deduplication service with default config"""
    config = DedupConfig(
        enabled=True,
        title_similarity_threshold=0.90,
        use_doi_matching=True,
        use_title_matching=True,
    )
    return DeduplicationService(config)


@pytest.fixture
def sample_papers():
    """Create sample papers for testing"""
    return [
        PaperMetadata(
            paper_id="paper1",
            title="Attention Is All You Need",
            doi="10.48550/arXiv.1706.03762",
            url="https://arxiv.org/abs/1706.03762",
            abstract="Transformer architecture paper",
            citation_count=50000,
            year=2017,
        ),
        PaperMetadata(
            paper_id="paper2",
            title="BERT: Pre-training of Deep Bidirectional Transformers",
            doi="10.48550/arXiv.1810.04805",
            url="https://arxiv.org/abs/1810.04805",
            abstract="BERT paper",
            citation_count=30000,
            year=2018,
        ),
        PaperMetadata(
            paper_id="paper3",
            title="GPT-3: Language Models are Few-Shot Learners",
            url="https://arxiv.org/abs/2005.14165",
            abstract="GPT-3 paper",
            citation_count=20000,
            year=2020,
        ),
    ]


def test_dedup_service_initialization(dedup_service):
    """Test deduplication service initializes correctly"""
    assert dedup_service.config.enabled
    assert dedup_service.config.title_similarity_threshold == 0.90
    assert len(dedup_service.doi_index) == 0
    assert len(dedup_service.title_index) == 0


def test_find_duplicates_empty_indices(dedup_service, sample_papers):
    """Test finding duplicates with empty indices (all papers are new)"""
    new_papers, duplicates = dedup_service.find_duplicates(sample_papers)

    assert len(new_papers) == 3
    assert len(duplicates) == 0
    assert dedup_service.stats.total_papers_checked == 3
    assert dedup_service.stats.duplicates_found == 0


def test_exact_doi_matching(dedup_service, sample_papers):
    """Test exact DOI matching detects duplicates"""
    # First pass: all papers are new
    new_papers, duplicates = dedup_service.find_duplicates(sample_papers)
    assert len(new_papers) == 3
    assert len(duplicates) == 0

    # Update indices with processed papers
    dedup_service.update_indices(new_papers)
    assert len(dedup_service.doi_index) == 2  # Only paper1 and paper2 have DOIs
    assert dedup_service.stats.unique_dois_indexed == 2

    # Second pass: try to add same papers again
    new_papers2, duplicates2 = dedup_service.find_duplicates(sample_papers)
    assert len(duplicates2) == 3  # All 3 detected as duplicates (2 by DOI, 1 by title)
    assert len(new_papers2) == 0
    assert dedup_service.stats.duplicates_by_doi == 2
    assert dedup_service.stats.duplicates_by_title == 1  # paper3 detected by title


def test_title_similarity_matching(dedup_service):
    """Test title fuzzy matching detects similar titles"""
    papers = [
        PaperMetadata(
            paper_id="paper1",
            title="Attention Is All You Need",
            url="https://arxiv.org/abs/1706.03762",
            year=2017,
        ),
        PaperMetadata(
            paper_id="paper2",
            title="Attention is all you need!",  # Very similar (punctuation difference)
            url="https://arxiv.org/abs/1706.03762",
            year=2017,
        ),
    ]

    # First paper
    new_papers, duplicates = dedup_service.find_duplicates([papers[0]])
    assert len(new_papers) == 1
    assert len(duplicates) == 0

    # Update indices
    dedup_service.update_indices(new_papers)

    # Second paper with similar title
    new_papers2, duplicates2 = dedup_service.find_duplicates([papers[1]])
    assert len(duplicates2) == 1  # Detected as duplicate by title
    assert len(new_papers2) == 0
    assert dedup_service.stats.duplicates_by_title == 1


def test_title_normalization(dedup_service):
    """Test title normalization removes punctuation and case"""
    title1 = "Attention Is All You Need!"
    title2 = "attention is all you need"
    title3 = "Attention, Is: All; You - Need?"

    norm1 = dedup_service._normalize_title(title1)
    norm2 = dedup_service._normalize_title(title2)
    norm3 = dedup_service._normalize_title(title3)

    assert norm1 == norm2 == norm3
    assert norm1 == "attention is all you need"


def test_title_similarity_threshold(dedup_service):
    """Test title similarity respects threshold"""
    papers = [
        PaperMetadata(
            paper_id="paper1",
            title="Attention Is All You Need",
            url="https://arxiv.org/abs/1",
            year=2017,
        ),
        PaperMetadata(
            paper_id="paper2",
            title="Attention Mechanism Survey",  # Different title (<90% similar)
            url="https://arxiv.org/abs/2",
            year=2018,
        ),
    ]

    # Process first paper
    new_papers, _ = dedup_service.find_duplicates([papers[0]])
    dedup_service.update_indices(new_papers)

    # Second paper should NOT be detected as duplicate (different title)
    new_papers2, duplicates2 = dedup_service.find_duplicates([papers[1]])
    assert len(new_papers2) == 1  # Not a duplicate
    assert len(duplicates2) == 0


def test_update_indices(dedup_service, sample_papers):
    """Test updating indices with new papers"""
    # Process papers
    new_papers, _ = dedup_service.find_duplicates(sample_papers)

    # Update indices
    dedup_service.update_indices(new_papers)

    # Check indices were updated
    assert len(dedup_service.doi_index) == 2  # paper1 and paper2 have DOIs
    assert len(dedup_service.title_index) == 3  # All 3 papers have titles
    assert dedup_service.stats.unique_dois_indexed == 2
    assert dedup_service.stats.unique_titles_indexed == 3


def test_get_stats(dedup_service, sample_papers):
    """Test getting deduplication statistics"""
    # First pass
    new_papers, duplicates = dedup_service.find_duplicates(sample_papers)
    stats = dedup_service.get_stats()

    assert stats.total_papers_checked == 3
    assert stats.duplicates_found == 0
    assert stats.dedup_rate == 0.0

    # Update indices and try again
    dedup_service.update_indices(new_papers)
    new_papers2, duplicates2 = dedup_service.find_duplicates(sample_papers)
    stats2 = dedup_service.get_stats()

    assert stats2.total_papers_checked == 6  # 3 + 3
    assert stats2.duplicates_found == 3  # All 3 papers (2 by DOI, 1 by title)
    assert 0.0 < stats2.dedup_rate < 1.0


def test_clear_indices(dedup_service, sample_papers):
    """Test clearing deduplication indices"""
    # Process and update
    new_papers, _ = dedup_service.find_duplicates(sample_papers)
    dedup_service.update_indices(new_papers)

    assert len(dedup_service.doi_index) > 0
    assert len(dedup_service.title_index) > 0

    # Clear
    dedup_service.clear_indices()

    assert len(dedup_service.doi_index) == 0
    assert len(dedup_service.title_index) == 0
    assert dedup_service.stats.total_papers_checked == 0


def test_disabled_dedup_service():
    """Test deduplication service when disabled"""
    config = DedupConfig(enabled=False)
    service = DeduplicationService(config)

    papers = [
        PaperMetadata(
            paper_id="paper1",
            title="Test Paper",
            url="https://arxiv.org/abs/1",
            year=2020,
        )
    ]

    # All operations should be no-ops
    new_papers, duplicates = service.find_duplicates(papers)
    assert len(new_papers) == 1  # All papers returned as new
    assert len(duplicates) == 0

    service.update_indices(papers)
    assert len(service.doi_index) == 0
    assert len(service.title_index) == 0


def test_doi_matching_can_be_disabled():
    """Test disabling DOI matching"""
    config = DedupConfig(
        enabled=True,
        use_doi_matching=False,  # Disable DOI matching
        use_title_matching=True,
    )
    service = DeduplicationService(config)

    papers = [
        PaperMetadata(
            paper_id="paper1",
            title="Test Paper",
            doi="10.1234/test",
            url="https://arxiv.org/abs/1",
            year=2020,
        )
    ]

    # Process and update
    new_papers, _ = service.find_duplicates(papers)
    service.update_indices(new_papers)

    # DOI should not be in index
    assert len(service.doi_index) == 0
    assert service.stats.unique_dois_indexed == 0

    # But title should be
    assert len(service.title_index) == 1


def test_title_matching_can_be_disabled():
    """Test disabling title matching"""
    config = DedupConfig(
        enabled=True,
        use_doi_matching=True,
        use_title_matching=False,  # Disable title matching
    )
    service = DeduplicationService(config)

    papers = [
        PaperMetadata(
            paper_id="paper1",
            title="Test Paper",
            url="https://arxiv.org/abs/1",
            year=2020,
        )
    ]

    # Process and update
    new_papers, _ = service.find_duplicates(papers)
    service.update_indices(new_papers)

    # Title should not be in index
    assert len(service.title_index) == 0
    assert service.stats.unique_titles_indexed == 0

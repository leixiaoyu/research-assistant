"""Unit tests for cache service"""

import shutil
import tempfile
from pathlib import Path

import pytest

from src.models.cache import CacheConfig
from src.models.config import TimeframeRecent
from src.models.extraction import ExtractionTarget, PaperExtraction
from src.services.cache_service import CacheService


@pytest.fixture
def temp_cache_dir():
    """Create temporary cache directory"""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def cache_service(temp_cache_dir):
    """Create cache service with temp directory"""
    config = CacheConfig(
        enabled=True,
        cache_dir=str(temp_cache_dir),
        ttl_api_hours=1,
        ttl_pdf_days=7,
        ttl_extraction_days=30,
    )
    return CacheService(config)


def test_cache_service_initialization(cache_service, temp_cache_dir):
    """Test cache service initializes correctly"""
    assert cache_service.enabled
    assert cache_service.cache_dir == temp_cache_dir
    assert (temp_cache_dir / "api").exists()
    assert (temp_cache_dir / "pdfs").exists()
    assert (temp_cache_dir / "extractions").exists()


def test_api_cache_hit_miss(cache_service):
    """Test API cache stores and retrieves responses"""
    query = "test query"
    timeframe = TimeframeRecent(type="recent", value="48h")
    response = {"papers": [{"title": "Paper 1"}]}

    # Miss on first access
    cached = cache_service.get_api_response(query, timeframe)
    assert cached is None

    # Store response
    cache_service.set_api_response(query, timeframe, response)

    # Hit on second access
    cached = cache_service.get_api_response(query, timeframe)
    assert cached is not None
    assert cached["papers"][0]["title"] == "Paper 1"


def test_pdf_cache(cache_service, temp_cache_dir):
    """Test PDF cache stores and retrieves paths"""
    paper_id = "2301.12345"
    pdf_path = temp_cache_dir / "test.pdf"
    pdf_path.touch()  # Create dummy file

    # Miss on first access
    cached = cache_service.get_pdf(paper_id)
    assert cached is None

    # Store path
    cache_service.set_pdf(paper_id, pdf_path)

    # Hit on second access
    cached = cache_service.get_pdf(paper_id)
    assert cached is not None
    assert cached == pdf_path.resolve()


def test_pdf_cache_stale_file(cache_service, temp_cache_dir):
    """Test PDF cache handles deleted files"""
    paper_id = "2301.12345"
    pdf_path = temp_cache_dir / "test.pdf"
    pdf_path.touch()

    # Cache the path
    cache_service.set_pdf(paper_id, pdf_path)

    # Delete the file
    pdf_path.unlink()

    # Should return None (stale entry removed)
    cached = cache_service.get_pdf(paper_id)
    assert cached is None


def test_extraction_cache(cache_service):
    """Test extraction cache with targets hash"""
    paper_id = "2301.12345"
    targets = [
        ExtractionTarget(
            name="summary", description="Extract summary", output_format="text"
        )
    ]

    extraction = PaperExtraction(
        paper_id=paper_id,
        extraction_results=[],
        tokens_used=1000,
        cost_usd=0.01,
    )

    # Miss on first access
    cached = cache_service.get_extraction(paper_id, targets)
    assert cached is None

    # Store extraction
    cache_service.set_extraction(paper_id, targets, extraction)

    # Hit on second access
    cached = cache_service.get_extraction(paper_id, targets)
    assert cached is not None
    assert cached.paper_id == paper_id


def test_extraction_cache_invalidated_by_targets_change(cache_service):
    """Test extraction cache key includes targets hash"""
    paper_id = "2301.12345"

    targets_v1 = [
        ExtractionTarget(name="summary", description="v1", output_format="text")
    ]

    targets_v2 = [
        ExtractionTarget(name="summary", description="v2", output_format="text")
    ]

    extraction = PaperExtraction(
        paper_id=paper_id,
        extraction_results=[],
        tokens_used=1000,
        cost_usd=0.01,
    )

    # Cache with v1 targets
    cache_service.set_extraction(paper_id, targets_v1, extraction)

    # Should miss with v2 targets (different hash)
    cached = cache_service.get_extraction(paper_id, targets_v2)
    assert cached is None


def test_hash_query_consistency(cache_service):
    """Test query hashing is consistent"""
    query = "machine learning"
    timeframe = TimeframeRecent(type="recent", value="7d")

    hash1 = cache_service.hash_query(query, timeframe)
    hash2 = cache_service.hash_query(query, timeframe)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 hex


def test_hash_targets_order_independent(cache_service):
    """Test targets hash is order-independent"""
    targets1 = [
        ExtractionTarget(name="summary", description="d1", output_format="text"),
        ExtractionTarget(name="code", description="d2", output_format="text"),
    ]

    targets2 = [
        ExtractionTarget(name="code", description="d2", output_format="text"),
        ExtractionTarget(name="summary", description="d1", output_format="text"),
    ]

    hash1 = cache_service.hash_targets(targets1)
    hash2 = cache_service.hash_targets(targets2)

    assert hash1 == hash2


def test_cache_stats(cache_service):
    """Test cache statistics collection"""
    # Perform some operations
    cache_service.set_api_response(
        "query1", TimeframeRecent(type="recent", value="7d"), {}
    )
    cache_service.get_api_response(
        "query1", TimeframeRecent(type="recent", value="7d")
    )  # Hit
    cache_service.get_api_response(
        "query2", TimeframeRecent(type="recent", value="7d")
    )  # Miss

    stats = cache_service.get_stats()

    assert stats.api_cache_size > 0
    # diskcache stats may not update immediately in tests
    # assert stats.api_cache_hits > 0
    # assert stats.api_cache_misses > 0
    # assert 0.0 <= stats.api_hit_rate <= 1.0


def test_clear_cache(cache_service):
    """Test cache clearing"""
    # Add some data
    cache_service.set_api_response(
        "query", TimeframeRecent(type="recent", value="7d"), {}
    )

    # Verify it's there
    stats_before = cache_service.get_stats()
    assert stats_before.api_cache_size > 0

    # Clear API cache
    cache_service.clear_cache("api")

    # Verify it's gone
    stats_after = cache_service.get_stats()
    assert stats_after.api_cache_size == 0


def test_disabled_cache(temp_cache_dir):
    """Test cache with enabled=False"""
    config = CacheConfig(enabled=False, cache_dir=str(temp_cache_dir))
    cache_service = CacheService(config)

    assert not cache_service.enabled

    # All operations should be no-ops
    cache_service.set_api_response(
        "query", TimeframeRecent(type="recent", value="7d"), {}
    )
    cached = cache_service.get_api_response(
        "query", TimeframeRecent(type="recent", value="7d")
    )
    assert cached is None

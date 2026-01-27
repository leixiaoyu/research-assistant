"""Additional tests for cache service to reach 95%+ coverage"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.models.cache import CacheConfig
from src.models.config import TimeframeRecent, TimeframeDateRange, TimeframeSinceYear
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
    """Create enabled cache service"""
    config = CacheConfig(
        enabled=True,
        cache_dir=str(temp_cache_dir),
        ttl_api_hours=1,
        ttl_pdf_days=7,
        ttl_extraction_days=30,
    )
    return CacheService(config)


# ==================== Exception Handling Tests ====================


def test_get_api_response_exception_handling(cache_service):
    """Test get_api_response handles cache errors gracefully"""
    query = "test query"
    timeframe = TimeframeRecent(type="recent", value="48h")

    with patch.object(
        cache_service.api_cache, "get", side_effect=Exception("Cache error")
    ):
        result = cache_service.get_api_response(query, timeframe)
        assert result is None


def test_set_api_response_exception_handling(cache_service):
    """Test set_api_response handles cache errors gracefully"""
    query = "test query"
    timeframe = TimeframeRecent(type="recent", value="48h")
    response = {"papers": []}

    with patch.object(
        cache_service.api_cache, "set", side_effect=Exception("Cache error")
    ):
        # Should not raise, just log
        cache_service.set_api_response(query, timeframe, response)


def test_get_pdf_exception_handling(cache_service):
    """Test get_pdf handles cache errors gracefully"""
    paper_id = "2301.12345"

    with patch.object(
        cache_service.pdf_cache, "get", side_effect=Exception("Cache error")
    ):
        result = cache_service.get_pdf(paper_id)
        assert result is None


def test_set_pdf_exception_handling(cache_service, temp_cache_dir):
    """Test set_pdf handles cache errors gracefully"""
    paper_id = "2301.12345"
    pdf_path = temp_cache_dir / "test.pdf"

    with patch.object(
        cache_service.pdf_cache, "set", side_effect=Exception("Cache error")
    ):
        # Should not raise, just log
        cache_service.set_pdf(paper_id, pdf_path)


def test_get_extraction_exception_handling(cache_service):
    """Test get_extraction handles cache errors gracefully"""
    paper_id = "2301.12345"
    targets = [
        ExtractionTarget(name="summary", description="test", output_format="text")
    ]

    with patch.object(
        cache_service.extraction_cache, "get", side_effect=Exception("Cache error")
    ):
        result = cache_service.get_extraction(paper_id, targets)
        assert result is None


def test_set_extraction_exception_handling(cache_service):
    """Test set_extraction handles cache errors gracefully"""
    paper_id = "2301.12345"
    targets = [
        ExtractionTarget(name="summary", description="test", output_format="text")
    ]
    extraction = PaperExtraction(
        paper_id=paper_id,
        extraction_results=[],
        tokens_used=100,
        cost_usd=0.01,
    )

    with patch.object(
        cache_service.extraction_cache, "set", side_effect=Exception("Cache error")
    ):
        # Should not raise, just log
        cache_service.set_extraction(paper_id, targets, extraction)


def test_get_stats_exception_handling(cache_service):
    """Test get_stats handles errors gracefully"""
    with patch.object(
        cache_service.api_cache, "stats", side_effect=Exception("Stats error")
    ):
        stats = cache_service.get_stats()
        # Should return default CacheStats
        assert stats.api_cache_size == 0


def test_get_cache_size_mb_exception_handling(cache_service):
    """Test _get_cache_size_mb handles errors gracefully"""
    mock_cache = Mock()
    mock_cache.directory = "/nonexistent/path"

    size = cache_service._get_cache_size_mb(mock_cache)
    assert size == 0.0


# ==================== Disabled Cache Tests ====================


def test_disabled_get_pdf(temp_cache_dir):
    """Test get_pdf returns None when cache disabled"""
    config = CacheConfig(enabled=False, cache_dir=str(temp_cache_dir))
    service = CacheService(config)

    result = service.get_pdf("2301.12345")
    assert result is None


def test_disabled_set_pdf(temp_cache_dir):
    """Test set_pdf is no-op when cache disabled"""
    config = CacheConfig(enabled=False, cache_dir=str(temp_cache_dir))
    service = CacheService(config)

    # Should not raise
    service.set_pdf("2301.12345", Path("/tmp/test.pdf"))


def test_disabled_get_extraction(temp_cache_dir):
    """Test get_extraction returns None when cache disabled"""
    config = CacheConfig(enabled=False, cache_dir=str(temp_cache_dir))
    service = CacheService(config)

    targets = [
        ExtractionTarget(name="summary", description="test", output_format="text")
    ]
    result = service.get_extraction("2301.12345", targets)
    assert result is None


def test_disabled_set_extraction(temp_cache_dir):
    """Test set_extraction is no-op when cache disabled"""
    config = CacheConfig(enabled=False, cache_dir=str(temp_cache_dir))
    service = CacheService(config)

    targets = [
        ExtractionTarget(name="summary", description="test", output_format="text")
    ]
    extraction = PaperExtraction(
        paper_id="2301.12345",
        extraction_results=[],
        tokens_used=100,
        cost_usd=0.01,
    )

    # Should not raise
    service.set_extraction("2301.12345", targets, extraction)


def test_disabled_get_stats(temp_cache_dir):
    """Test get_stats returns default stats when cache disabled"""
    config = CacheConfig(enabled=False, cache_dir=str(temp_cache_dir))
    service = CacheService(config)

    stats = service.get_stats()
    assert stats.api_cache_size == 0


def test_disabled_clear_cache(temp_cache_dir):
    """Test clear_cache is no-op when cache disabled"""
    config = CacheConfig(enabled=False, cache_dir=str(temp_cache_dir))
    service = CacheService(config)

    # Should not raise
    service.clear_cache()


# ==================== TimeframeDateRange Tests ====================


def test_hash_query_with_date_range():
    """Test hash_query handles TimeframeDateRange correctly"""
    query = "machine learning"
    timeframe = TimeframeDateRange(
        type="date_range", start_date="2024-01-01", end_date="2024-12-31"
    )

    hash1 = CacheService.hash_query(query, timeframe)
    hash2 = CacheService.hash_query(query, timeframe)

    # Should be consistent
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 hex


def test_hash_query_with_since_year():
    """Test hash_query handles TimeframeSinceYear correctly"""
    query = "deep learning"
    timeframe = TimeframeSinceYear(type="since_year", value=2020)

    hash1 = CacheService.hash_query(query, timeframe)
    hash2 = CacheService.hash_query(query, timeframe)

    assert hash1 == hash2


# ==================== Clear Cache Specific Types ====================


def test_clear_cache_api_only(cache_service):
    """Test clearing only API cache"""
    # Add data to all caches
    cache_service.set_api_response(
        "query", TimeframeRecent(type="recent", value="7d"), {}
    )
    pdf_path = cache_service.cache_dir / "test.pdf"
    pdf_path.touch()
    cache_service.set_pdf("paper1", pdf_path)

    # Clear only API cache
    cache_service.clear_cache("api")

    # API cache should be empty
    stats = cache_service.get_stats()
    assert stats.api_cache_size == 0
    # PDF cache should still have data
    assert stats.pdf_cache_size > 0


def test_clear_cache_pdf_only(cache_service):
    """Test clearing only PDF cache"""
    # Add data to all caches
    cache_service.set_api_response(
        "query", TimeframeRecent(type="recent", value="7d"), {}
    )
    pdf_path = cache_service.cache_dir / "test.pdf"
    pdf_path.touch()
    cache_service.set_pdf("paper1", pdf_path)

    # Clear only PDF cache
    cache_service.clear_cache("pdf")

    stats = cache_service.get_stats()
    # API cache should still have data
    assert stats.api_cache_size > 0
    # PDF cache should be empty
    assert stats.pdf_cache_size == 0


def test_clear_cache_extraction_only(cache_service):
    """Test clearing only extraction cache"""
    # Add data to all caches
    cache_service.set_api_response(
        "query", TimeframeRecent(type="recent", value="7d"), {}
    )
    targets = [
        ExtractionTarget(name="summary", description="test", output_format="text")
    ]
    extraction = PaperExtraction(
        paper_id="paper1",
        extraction_results=[],
        tokens_used=100,
        cost_usd=0.01,
    )
    cache_service.set_extraction("paper1", targets, extraction)

    # Clear only extraction cache
    cache_service.clear_cache("extraction")

    stats = cache_service.get_stats()
    # API cache should still have data
    assert stats.api_cache_size > 0
    # Extraction cache should be empty
    assert stats.extraction_cache_size == 0


def test_clear_cache_all(cache_service):
    """Test clearing all caches"""
    # Add data to all caches
    cache_service.set_api_response(
        "query", TimeframeRecent(type="recent", value="7d"), {}
    )
    pdf_path = cache_service.cache_dir / "test.pdf"
    pdf_path.touch()
    cache_service.set_pdf("paper1", pdf_path)
    targets = [
        ExtractionTarget(name="summary", description="test", output_format="text")
    ]
    extraction = PaperExtraction(
        paper_id="paper1",
        extraction_results=[],
        tokens_used=100,
        cost_usd=0.01,
    )
    cache_service.set_extraction("paper1", targets, extraction)

    # Clear all
    cache_service.clear_cache(None)

    stats = cache_service.get_stats()
    assert stats.api_cache_size == 0
    assert stats.pdf_cache_size == 0
    assert stats.extraction_cache_size == 0

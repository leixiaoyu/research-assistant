from datetime import datetime

from src.models.cache import CacheConfig, CacheStats


class TestCacheConfig:
    """Test CacheConfig model"""

    def test_cache_config_defaults(self):
        """Test default configuration values"""
        config = CacheConfig()

        assert config.enabled is True
        assert config.cache_dir == "./cache"
        assert config.ttl_api_hours == 1
        assert config.ttl_pdf_days == 7
        assert config.ttl_extraction_days == 30
        assert config.max_cache_size_mb == 10000
        assert config.auto_cleanup is True

    def test_cache_config_custom(self):
        """Test custom configuration values"""
        config = CacheConfig(
            enabled=False,
            cache_dir="/custom/cache",
            ttl_api_hours=2,
            ttl_pdf_days=14,
            ttl_extraction_days=60,
            max_cache_size_mb=5000,
            auto_cleanup=False,
        )

        assert config.enabled is False
        assert config.cache_dir == "/custom/cache"
        assert config.ttl_api_hours == 2
        assert config.ttl_pdf_days == 14
        assert config.ttl_extraction_days == 60
        assert config.max_cache_size_mb == 5000
        assert config.auto_cleanup is False

    def test_cache_config_ttl_properties(self):
        """Test TTL conversion properties"""
        config = CacheConfig(ttl_api_hours=2, ttl_pdf_days=7, ttl_extraction_days=30)

        assert config.ttl_api_seconds == 2 * 3600  # 7200
        assert config.ttl_pdf_seconds == 7 * 86400  # 604800
        assert config.ttl_extraction_seconds == 30 * 86400  # 2592000


class TestCacheStats:
    """Test CacheStats model and computed properties"""

    def test_cache_stats_defaults(self):
        """Test default statistics values"""
        stats = CacheStats()

        assert stats.api_cache_size == 0
        assert stats.api_cache_hits == 0
        assert stats.api_cache_misses == 0
        assert stats.pdf_cache_size == 0
        assert stats.pdf_cache_disk_mb == 0.0
        assert stats.extraction_cache_size == 0
        assert stats.extraction_cache_hits == 0
        assert stats.extraction_cache_misses == 0
        assert isinstance(stats.last_updated, datetime)

    def test_api_hit_rate_with_data(self):
        """Test API hit rate calculation with hits and misses"""
        stats = CacheStats(api_cache_hits=7, api_cache_misses=3)

        # 7 hits / (7+3) total = 0.7
        assert stats.api_hit_rate == 0.7

    def test_api_hit_rate_zero_total(self):
        """Test API hit rate when no cache operations occurred (lines 62-65)"""
        stats = CacheStats(api_cache_hits=0, api_cache_misses=0)

        # Division by zero protection - should return 0.0
        assert stats.api_hit_rate == 0.0

    def test_extraction_hit_rate_with_data(self):
        """Test extraction hit rate calculation with hits and misses"""
        stats = CacheStats(extraction_cache_hits=15, extraction_cache_misses=5)

        # 15 hits / (15+5) total = 0.75
        assert stats.extraction_hit_rate == 0.75

    def test_extraction_hit_rate_zero_total(self):
        """Test extraction hit rate when no cache operations occurred (lines 70-73)"""
        stats = CacheStats(extraction_cache_hits=0, extraction_cache_misses=0)

        # Division by zero protection - should return 0.0
        assert stats.extraction_hit_rate == 0.0

    def test_perfect_hit_rate(self):
        """Test 100% hit rate (all hits, no misses)"""
        stats = CacheStats(
            api_cache_hits=10,
            api_cache_misses=0,
            extraction_cache_hits=20,
            extraction_cache_misses=0,
        )

        assert stats.api_hit_rate == 1.0
        assert stats.extraction_hit_rate == 1.0

    def test_zero_hit_rate(self):
        """Test 0% hit rate (all misses, no hits)"""
        stats = CacheStats(
            api_cache_hits=0,
            api_cache_misses=10,
            extraction_cache_hits=0,
            extraction_cache_misses=20,
        )

        assert stats.api_hit_rate == 0.0
        assert stats.extraction_hit_rate == 0.0

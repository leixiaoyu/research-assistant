"""
Multi-level disk cache service.

Implements 3-tier caching:
1. API responses (short TTL, frequently changing)
2. PDFs (medium TTL, rarely change)
3. Extractions (long TTL, expensive to regenerate)
"""

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

import diskcache
import structlog

from src.models.cache import CacheConfig, CacheStats
from src.models.config import Timeframe
from src.models.extraction import ExtractionTarget, PaperExtraction

logger = structlog.get_logger()


class CacheService:
    """
    Multi-level disk cache service.

    Provides automatic expiration, statistics tracking, and size management.
    Thread-safe and async-compatible.
    """

    def __init__(self, config: CacheConfig):
        """
        Initialize cache service.

        Args:
            config: Cache configuration
        """
        self.config = config
        self.cache_dir = Path(config.cache_dir)

        if not config.enabled:
            logger.info("cache_disabled")
            self.enabled = False
            return

        self.enabled = True

        # Create cache directories
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize cache instances
        self.api_cache = diskcache.Cache(
            self.cache_dir / "api", timeout=config.ttl_api_seconds
        )

        self.pdf_cache = diskcache.Cache(
            self.cache_dir / "pdfs", timeout=config.ttl_pdf_seconds
        )

        self.extraction_cache = diskcache.Cache(
            self.cache_dir / "extractions", timeout=config.ttl_extraction_seconds
        )

        logger.info(
            "cache_service_initialized",
            cache_dir=str(self.cache_dir),
            api_ttl_hours=config.ttl_api_hours,
            pdf_ttl_days=config.ttl_pdf_days,
            extraction_ttl_days=config.ttl_extraction_days,
        )

    # ==================== API Response Cache ====================

    def get_api_response(self, query: str, timeframe: Timeframe) -> Optional[Dict]:
        """
        Get cached API response for query.

        Args:
            query: Search query string
            timeframe: Query timeframe

        Returns:
            Cached response dict or None if not cached
        """
        if not self.enabled:
            return None

        cache_key = self.hash_query(query, timeframe)

        try:
            response = cast(Optional[Dict[Any, Any]], self.api_cache.get(cache_key))

            if response is not None:
                logger.info("api_cache_hit", query=query[:50], cache_key=cache_key[:8])
                return response
            else:
                logger.debug(
                    "api_cache_miss", query=query[:50], cache_key=cache_key[:8]
                )
                return None

        except Exception as e:
            logger.error("api_cache_error", error=str(e))
            return None

    def set_api_response(
        self, query: str, timeframe: Timeframe, response: Dict
    ) -> None:
        """
        Cache API response.

        Args:
            query: Search query string
            timeframe: Query timeframe
            response: API response to cache
        """
        if not self.enabled:
            return

        cache_key = self.hash_query(query, timeframe)

        try:
            self.api_cache.set(cache_key, response)
            logger.debug(
                "api_cached",
                query=query[:50],
                cache_key=cache_key[:8],
                papers_count=len(response.get("papers", [])),
            )
        except Exception as e:
            logger.error("api_cache_set_error", error=str(e))

    # ==================== PDF Cache ====================

    def get_pdf(self, paper_id: str) -> Optional[Path]:
        """
        Get cached PDF path.

        Args:
            paper_id: Paper identifier

        Returns:
            Path to cached PDF or None if not cached
        """
        if not self.enabled:
            return None

        try:
            cached_path = self.pdf_cache.get(paper_id)

            if cached_path:
                path = Path(cached_path)
                if path.exists():
                    logger.info("pdf_cache_hit", paper_id=paper_id)
                    return path
                else:
                    # File was deleted, remove from cache
                    self.pdf_cache.delete(paper_id)
                    logger.warning("pdf_cache_stale", paper_id=paper_id)

            logger.debug("pdf_cache_miss", paper_id=paper_id)
            return None

        except Exception as e:
            logger.error("pdf_cache_error", error=str(e))
            return None

    def set_pdf(self, paper_id: str, pdf_path: Path) -> None:
        """
        Cache PDF file path.

        Args:
            paper_id: Paper identifier
            pdf_path: Path to PDF file
        """
        if not self.enabled:
            return

        try:
            self.pdf_cache.set(paper_id, str(pdf_path.resolve()))
            logger.debug("pdf_cached", paper_id=paper_id, path=str(pdf_path))
        except Exception as e:
            logger.error("pdf_cache_set_error", error=str(e))

    # ==================== Extraction Cache ====================

    def get_extraction(
        self, paper_id: str, targets: List[ExtractionTarget]
    ) -> Optional[PaperExtraction]:
        """
        Get cached extraction result.

        Cache key includes paper_id AND targets hash, so changes
        to extraction targets invalidate the cache.

        Args:
            paper_id: Paper identifier
            targets: Extraction targets (for cache key)

        Returns:
            Cached extraction or None if not cached
        """
        if not self.enabled:
            return None

        targets_hash = self.hash_targets(targets)
        cache_key = f"{paper_id}:{targets_hash}"

        try:
            cached_data = self.extraction_cache.get(cache_key)

            if cached_data:
                logger.info(
                    "extraction_cache_hit",
                    paper_id=paper_id,
                    targets_hash=targets_hash[:8],
                )
                return PaperExtraction.model_validate(cached_data)
            else:
                logger.debug(
                    "extraction_cache_miss",
                    paper_id=paper_id,
                    targets_hash=targets_hash[:8],
                )
                return None

        except Exception as e:
            logger.error("extraction_cache_error", error=str(e))
            return None

    def set_extraction(
        self,
        paper_id: str,
        targets: List[ExtractionTarget],
        extraction: PaperExtraction,
    ) -> None:
        """
        Cache extraction result.

        Args:
            paper_id: Paper identifier
            targets: Extraction targets (for cache key)
            extraction: Extraction result to cache
        """
        if not self.enabled:
            return

        targets_hash = self.hash_targets(targets)
        cache_key = f"{paper_id}:{targets_hash}"

        try:
            self.extraction_cache.set(cache_key, extraction.model_dump())
            logger.debug(
                "extraction_cached", paper_id=paper_id, targets_hash=targets_hash[:8]
            )
        except Exception as e:
            logger.error("extraction_cache_set_error", error=str(e))

    # ==================== Utility Methods ====================

    @staticmethod
    def hash_query(query: str, timeframe: Timeframe) -> str:
        """
        Generate cache key for query + timeframe.

        Args:
            query: Search query
            timeframe: Query timeframe

        Returns:
            SHA256 hash as hex string
        """
        if hasattr(timeframe, "value"):
            content = f"{query}:{timeframe.type}:{timeframe.value}"
        else:
            # TimeframeDateRange
            content = (
                f"{query}:{timeframe.type}:{timeframe.start_date}:{timeframe.end_date}"
            )
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def hash_targets(targets: List[ExtractionTarget]) -> str:
        """
        Generate hash for extraction targets.

        Sorted by name to ensure consistent hashing regardless of order.

        Args:
            targets: List of extraction targets

        Returns:
            SHA256 hash as hex string
        """
        content = "|".join(
            f"{t.name}:{t.description}:{t.output_format}"
            for t in sorted(targets, key=lambda x: x.name)
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def get_stats(self) -> CacheStats:
        """
        Get cache statistics.

        Returns:
            CacheStats with current statistics
        """
        if not self.enabled:
            return CacheStats()

        try:
            # Get disk cache stats (returns tuple of (hits, misses))
            api_hits, api_misses = self.api_cache.stats()
            ext_hits, ext_misses = self.extraction_cache.stats()

            # Calculate PDF cache size on disk
            pdf_cache_mb = self._get_cache_size_mb(self.pdf_cache)

            return CacheStats(
                api_cache_size=len(self.api_cache),
                api_cache_hits=api_hits,
                api_cache_misses=api_misses,
                pdf_cache_size=len(self.pdf_cache),
                pdf_cache_disk_mb=pdf_cache_mb,
                extraction_cache_size=len(self.extraction_cache),
                extraction_cache_hits=ext_hits,
                extraction_cache_misses=ext_misses,
            )

        except Exception as e:
            logger.error("cache_stats_error", error=str(e))
            return CacheStats()

    def _get_cache_size_mb(self, cache: diskcache.Cache) -> float:
        """Calculate cache size on disk in MB"""
        try:
            cache_path = Path(cache.directory)
            total_size = sum(
                f.stat().st_size for f in cache_path.rglob("*") if f.is_file()
            )
            return total_size / (1024 * 1024)  # Convert to MB
        except Exception:
            return 0.0

    def clear_cache(self, cache_type: Optional[str] = None) -> None:
        """
        Clear cache(s).

        Args:
            cache_type: "api", "pdf", "extraction", or None for all
        """
        if not self.enabled:
            return

        if cache_type is None or cache_type == "api":
            self.api_cache.clear()
            logger.info("api_cache_cleared")

        if cache_type is None or cache_type == "pdf":
            self.pdf_cache.clear()
            logger.info("pdf_cache_cleared")

        if cache_type is None or cache_type == "extraction":
            self.extraction_cache.clear()
            logger.info("extraction_cache_cleared")

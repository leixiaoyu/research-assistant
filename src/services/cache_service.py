"""Cache service implementation."""
import hashlib
from pathlib import Path
from typing import Optional, Dict, List
import diskcache
import structlog
from src.models.cache import CacheConfig, CacheStats
from src.models.config import Timeframe
from src.models.extraction import ExtractionTarget, PaperExtraction

logger = structlog.get_logger()

class CacheService:
    def __init__(self, config: CacheConfig):
        self.config = config
        self.cache_dir = Path(config.cache_dir)
        if not config.enabled:
            self.enabled = False
            return
        self.enabled = True
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.api_cache = diskcache.Cache(self.cache_dir / "api", timeout=config.ttl_api_seconds, statistics=True)
        self.pdf_cache = diskcache.Cache(self.cache_dir / "pdfs", timeout=config.ttl_pdf_seconds, statistics=True)
        self.extraction_cache = diskcache.Cache(self.cache_dir / "extractions", timeout=config.ttl_extraction_seconds, statistics=True)
    def get_api_response(self, query: str, timeframe: Timeframe) -> Optional[Dict]:
        if not self.enabled: return None
        return self.api_cache.get(self.hash_query(query, timeframe))
    def set_api_response(self, query: str, timeframe: Timeframe, response: Dict) -> None:
        if self.enabled: self.api_cache.set(self.hash_query(query, timeframe), response)
    def get_pdf(self, paper_id: str) -> Optional[Path]:
        if not self.enabled: return None
        path_str = self.pdf_cache.get(paper_id)
        if path_str:
            path = Path(path_str)
            if path.exists(): return path
            self.pdf_cache.delete(paper_id)
        return None
    def set_pdf(self, paper_id: str, pdf_path: Path) -> None:
        if self.enabled: self.pdf_cache.set(paper_id, str(pdf_path.resolve()))
    def get_extraction(self, paper_id: str, targets: List[ExtractionTarget]) -> Optional[PaperExtraction]:
        if not self.enabled: return None
        data = self.extraction_cache.get(f"{paper_id}:{self.hash_targets(targets)}")
        return PaperExtraction.model_validate(data) if data else None
    def set_extraction(self, paper_id: str, targets: List[ExtractionTarget], extraction: PaperExtraction) -> None:
        if self.enabled: self.extraction_cache.set(f"{paper_id}:{self.hash_targets(targets)}", extraction.model_dump())
    @staticmethod
    def hash_query(query: str, timeframe: Timeframe) -> str:
        return hashlib.sha256(f"{query}:{timeframe.type}:{timeframe.value}".encode()).hexdigest()
    @staticmethod
    def hash_targets(targets: List[ExtractionTarget]) -> str:
        content = "|".join(f"{t.name}:{t.description}" for t in sorted(targets, key=lambda x: x.name))
        return hashlib.sha256(content.encode()).hexdigest()
    def get_stats(self) -> CacheStats:
        if not self.enabled: return CacheStats()
        ah, am = self.api_cache.stats()
        eh, em = self.extraction_cache.stats()
        return CacheStats(api_cache_size=len(self.api_cache), api_cache_hits=ah, api_cache_misses=am, pdf_cache_size=len(self.pdf_cache), extraction_cache_size=len(self.extraction_cache), extraction_cache_hits=eh, extraction_cache_misses=em)
    def clear_cache(self, cache_type: Optional[str] = None) -> None:
        if not self.enabled: return
        if cache_type in [None, "api"]: self.api_cache.clear()
        if cache_type in [None, "pdf"]: self.pdf_cache.clear()
        if cache_type in [None, "extraction"]: self.extraction_cache.clear()

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
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.fixture
def cache_service(temp_cache_dir):
    config = CacheConfig(enabled=True, cache_dir=str(temp_cache_dir))
    return CacheService(config)

def test_api_cache(cache_service):
    q, t = 'test', TimeframeRecent(value='1d')
    assert cache_service.get_api_response(q, t) is None
    cache_service.set_api_response(q, t, {'ok': True})
    assert cache_service.get_api_response(q, t) == {'ok': True}

def test_pdf_cache(cache_service, temp_cache_dir):
    p_id = 'id1'
    pdf = temp_cache_dir / 'test.pdf'
    pdf.touch()
    cache_service.set_pdf(p_id, pdf)
    assert cache_service.get_pdf(p_id) == pdf.resolve()
    pdf.unlink()
    assert cache_service.get_pdf(p_id) is None

def test_extraction_cache(cache_service):
    p_id = 'id1'
    targets = [ExtractionTarget(name='s', description='d')]
    ext = PaperExtraction(paper_id=p_id, extraction_results=[], tokens_used=10, cost_usd=0.1)
    cache_service.set_extraction(p_id, targets, ext)
    cached = cache_service.get_extraction(p_id, targets)
    assert cached.paper_id == p_id

def test_stats_and_clear(cache_service):
    cache_service.set_api_response('q', TimeframeRecent(value='1d'), {})
    assert cache_service.get_stats().api_cache_size == 1
    cache_service.clear_cache('api')
    assert cache_service.get_stats().api_cache_size == 0

def test_disabled(temp_cache_dir):
    svc = CacheService(CacheConfig(enabled=False, cache_dir=str(temp_cache_dir)))
    assert not svc.enabled
    assert svc.get_api_response('q', TimeframeRecent(value='1d')) is None
    assert svc.get_stats().api_cache_size == 0
def test_hit_rates(cache_service):
    stats = cache_service.get_stats()
    assert stats.api_hit_rate == 0.0
    cache_service.set_api_response("q", TimeframeRecent(value="1d"), {})
    cache_service.get_api_response("q", TimeframeRecent(value="1d"))
    stats = cache_service.get_stats()
    assert stats.api_hit_rate == 1.0
    assert stats.extraction_hit_rate == 0.0

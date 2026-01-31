"""Integration tests for concurrent pipeline end-to-end (Phase 3.1)"""

import pytest

from src.orchestration.concurrent_pipeline import ConcurrentPipeline
from src.models.concurrency import ConcurrencyConfig
from src.models.paper import PaperMetadata, Author
from src.models.extraction import ExtractionTarget
from src.models.cache import CacheConfig
from src.models.checkpoint import CheckpointConfig
from src.models.dedup import DedupConfig
from src.models.filters import FilterConfig

from src.services.pdf_extractors.fallback_service import FallbackPDFService
from src.services.llm_service import LLMService
from src.services.cache_service import CacheService
from src.services.dedup_service import DeduplicationService
from src.services.filter_service import FilterService
from src.services.checkpoint_service import CheckpointService


@pytest.fixture
def concurrency_config():
    """Small concurrency config for testing"""
    return ConcurrencyConfig(
        max_concurrent_downloads=2,
        max_concurrent_conversions=1,
        max_concurrent_llm=1,
        queue_size=10,  # Minimum allowed is 10
        checkpoint_interval=2,
    )


@pytest.fixture
def sample_papers():
    """Sample papers for E2E testing"""
    return [
        PaperMetadata(
            paper_id=f"e2e-{i}",
            title=f"E2E Test Paper {i}",
            abstract=f"This is a test abstract for paper {i}",
            authors=[Author(name=f"Test Author {i}")],
            url=f"https://example.com/e2e-{i}",
            open_access_pdf=None,  # No PDF - will use abstract
            year=2024,
        )
        for i in range(3)
    ]


@pytest.fixture
def extraction_targets():
    """Sample extraction targets"""
    return [
        ExtractionTarget(
            name="summary",
            description="Extract a brief summary",
            output_format="text",
            required=True,
        )
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_pipeline_e2e_mock_llm(
    concurrency_config, sample_papers, extraction_targets, tmp_path
):
    """Test full concurrent pipeline with mocked LLM (no API calls)"""
    # Initialize all Phase 3 services with test configs
    cache_config = CacheConfig(
        enabled=True,
        cache_dir=str(tmp_path / "cache"),
        ttl_api_hours=1,
        ttl_pdf_days=1,
        ttl_extraction_days=1,
    )
    cache_service = CacheService(cache_config)

    dedup_config = DedupConfig(enabled=True)
    dedup_service = DeduplicationService(dedup_config)

    filter_config = FilterConfig(
        min_citation_count=0,
        min_year=2000,
        max_papers=10,
    )
    filter_service = FilterService(filter_config)

    checkpoint_config = CheckpointConfig(
        enabled=True,
        checkpoint_dir=str(tmp_path / "checkpoints"),
    )
    checkpoint_service = CheckpointService(checkpoint_config)

    # Mock LLM service (no real API calls)
    from unittest.mock import AsyncMock
    from src.models.extraction import PaperExtraction, ExtractionResult

    llm_service = AsyncMock(spec=LLMService)
    llm_service.extract = AsyncMock(
        return_value=PaperExtraction(
            paper_id="test",
            extraction_results=[
                ExtractionResult(
                    target_name="summary",
                    success=True,
                    content="Mocked summary",
                    confidence=0.9,
                )
            ],
            tokens_used=100,
            cost_usd=0.001,
        )
    )

    # Mock PDF service (papers have no PDFs in this test)
    from unittest.mock import Mock

    fallback_pdf_service = Mock(spec=FallbackPDFService)

    # Create pipeline
    pipeline = ConcurrentPipeline(
        config=concurrency_config,
        fallback_pdf_service=fallback_pdf_service,
        llm_service=llm_service,
        cache_service=cache_service,
        dedup_service=dedup_service,
        filter_service=filter_service,
        checkpoint_service=checkpoint_service,
    )

    # Process papers concurrently
    results = []
    async for extracted_paper in pipeline.process_papers_concurrent(
        papers=sample_papers,
        targets=extraction_targets,
        run_id="e2e-test-1",
        query="test query",
    ):
        results.append(extracted_paper)

    # Verify results
    assert len(results) == len(sample_papers)
    assert all(r.extraction is not None for r in results)

    # Verify pipeline stats
    stats = pipeline.get_stats()
    assert stats.papers_completed == len(sample_papers)
    assert stats.papers_failed == 0
    assert stats.total_papers == len(sample_papers)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_checkpoint_resume_e2e(
    concurrency_config, sample_papers, extraction_targets, tmp_path
):
    """Test checkpoint resume functionality in E2E scenario"""
    # Initialize services
    cache_service = CacheService(
        CacheConfig(enabled=True, cache_dir=str(tmp_path / "cache"))
    )
    dedup_service = DeduplicationService(DedupConfig(enabled=True))
    filter_service = FilterService(FilterConfig())
    checkpoint_service = CheckpointService(
        CheckpointConfig(enabled=True, checkpoint_dir=str(tmp_path / "checkpoints"))
    )

    # Mock LLM
    from unittest.mock import AsyncMock, Mock
    from src.models.extraction import PaperExtraction

    llm_service = AsyncMock(spec=LLMService)
    llm_service.extract = AsyncMock(
        return_value=PaperExtraction(
            paper_id="test", extraction_results=[], tokens_used=50, cost_usd=0.0005
        )
    )
    fallback_pdf_service = Mock()

    # Create pipeline
    pipeline = ConcurrentPipeline(
        config=concurrency_config,
        fallback_pdf_service=fallback_pdf_service,
        llm_service=llm_service,
        cache_service=cache_service,
        dedup_service=dedup_service,
        filter_service=filter_service,
        checkpoint_service=checkpoint_service,
    )

    run_id = "e2e-checkpoint-test"

    # First run: process first 2 papers
    first_results = []
    counter = 0
    async for extracted_paper in pipeline.process_papers_concurrent(
        papers=sample_papers,
        targets=extraction_targets,
        run_id=run_id,
        query="test",
    ):
        first_results.append(extracted_paper)
        counter += 1
        if counter == 2:
            break  # Simulate interruption

    assert len(first_results) == 2

    # Manually save checkpoint for the processed papers
    processed_ids = [paper.metadata.paper_id for paper in first_results]
    checkpoint_service.save_checkpoint(
        run_id=run_id, processed_paper_ids=processed_ids, completed=False
    )

    # Second run: resume from checkpoint
    # Create new pipeline instance to simulate restart
    pipeline2 = ConcurrentPipeline(
        config=concurrency_config,
        fallback_pdf_service=fallback_pdf_service,
        llm_service=llm_service,
        cache_service=cache_service,
        dedup_service=dedup_service,
        filter_service=filter_service,
        checkpoint_service=checkpoint_service,
    )

    second_results = []
    async for extracted_paper in pipeline2.process_papers_concurrent(
        papers=sample_papers,
        targets=extraction_targets,
        run_id=run_id,
        query="test",
    ):
        second_results.append(extracted_paper)

    # Should only process remaining paper (3rd one)
    assert len(second_results) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cache_integration_e2e(
    concurrency_config, sample_papers, extraction_targets, tmp_path
):
    """Test cache service integration in E2E scenario"""
    cache_service = CacheService(
        CacheConfig(enabled=True, cache_dir=str(tmp_path / "cache"))
    )
    dedup_service = DeduplicationService(DedupConfig(enabled=True))
    filter_service = FilterService(FilterConfig())
    checkpoint_service = CheckpointService(
        CheckpointConfig(enabled=True, checkpoint_dir=str(tmp_path / "checkpoints"))
    )

    # Mock LLM
    from unittest.mock import AsyncMock, Mock
    from src.models.extraction import PaperExtraction

    llm_service = AsyncMock(spec=LLMService)
    llm_call_count = 0

    def count_llm_calls(*args, **kwargs):
        nonlocal llm_call_count
        llm_call_count += 1
        return PaperExtraction(
            paper_id="test", extraction_results=[], tokens_used=50, cost_usd=0.0005
        )

    llm_service.extract = AsyncMock(side_effect=count_llm_calls)
    fallback_pdf_service = Mock()

    pipeline = ConcurrentPipeline(
        config=concurrency_config,
        fallback_pdf_service=fallback_pdf_service,
        llm_service=llm_service,
        cache_service=cache_service,
        dedup_service=dedup_service,
        filter_service=filter_service,
        checkpoint_service=checkpoint_service,
    )

    # First run
    first_results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=sample_papers,
        targets=extraction_targets,
        run_id="cache-test-1",
        query="test",
    ):
        first_results.append(paper)

    first_llm_calls = llm_call_count

    # Clear dedup indices so papers aren't marked as duplicates in second run
    dedup_service.clear_indices()

    # Second run - should use cache
    llm_call_count = 0
    pipeline2 = ConcurrentPipeline(
        config=concurrency_config,
        fallback_pdf_service=fallback_pdf_service,
        llm_service=llm_service,
        cache_service=cache_service,
        dedup_service=dedup_service,
        filter_service=filter_service,
        checkpoint_service=checkpoint_service,
    )

    second_results = []
    async for paper in pipeline2.process_papers_concurrent(
        papers=sample_papers,
        targets=extraction_targets,
        run_id="cache-test-2",
        query="test",
    ):
        second_results.append(paper)

    second_llm_calls = llm_call_count

    # Second run should use cache, so fewer LLM calls
    assert second_llm_calls < first_llm_calls
    assert len(second_results) == len(first_results)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deduplication_e2e(concurrency_config, extraction_targets, tmp_path):
    """Test deduplication prevents reprocessing same papers"""
    cache_service = CacheService(
        CacheConfig(enabled=True, cache_dir=str(tmp_path / "cache"))
    )
    dedup_service = DeduplicationService(DedupConfig(enabled=True))
    filter_service = FilterService(FilterConfig())
    checkpoint_service = CheckpointService(
        CheckpointConfig(enabled=True, checkpoint_dir=str(tmp_path / "checkpoints"))
    )

    # Mock services
    from unittest.mock import AsyncMock, Mock
    from src.models.extraction import PaperExtraction

    llm_service = AsyncMock(spec=LLMService)
    llm_service.extract = AsyncMock(
        return_value=PaperExtraction(
            paper_id="test", extraction_results=[], tokens_used=50, cost_usd=0.0005
        )
    )
    fallback_pdf_service = Mock()

    # Create identical papers
    papers_batch1 = [
        PaperMetadata(
            paper_id="dup-1",
            title="Duplicate Paper",
            abstract="Same paper",
            authors=[],
            url="https://example.com/dup",
        )
    ]

    papers_batch2 = [
        PaperMetadata(
            paper_id="dup-1",  # Same ID
            title="Duplicate Paper",
            abstract="Same paper",
            authors=[],
            url="https://example.com/dup",
        )
    ]

    pipeline = ConcurrentPipeline(
        config=concurrency_config,
        fallback_pdf_service=fallback_pdf_service,
        llm_service=llm_service,
        cache_service=cache_service,
        dedup_service=dedup_service,
        filter_service=filter_service,
        checkpoint_service=checkpoint_service,
    )

    # First batch
    results1 = []
    async for paper in pipeline.process_papers_concurrent(
        papers=papers_batch1,
        targets=extraction_targets,
        run_id="dedup-test-1",
        query="test",
    ):
        results1.append(paper)

    # Second batch with duplicate - should be deduplicated
    results2 = []
    async for paper in pipeline.process_papers_concurrent(
        papers=papers_batch2,
        targets=extraction_targets,
        run_id="dedup-test-2",
        query="test",
    ):
        results2.append(paper)

    # First batch should process the paper
    assert len(results1) == 1

    # Second batch should skip duplicate
    assert len(results2) == 0

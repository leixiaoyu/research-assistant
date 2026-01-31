"""Unit tests for ConcurrentPipeline (Phase 3.1)"""

import pytest
from unittest.mock import Mock, AsyncMock

from src.orchestration.concurrent_pipeline import ConcurrentPipeline
from src.models.concurrency import ConcurrencyConfig, PipelineStats
from src.models.paper import PaperMetadata, Author
from src.models.extraction import ExtractionTarget, PaperExtraction, ExtractionResult
from src.models.pdf_extraction import PDFExtractionResult, PDFBackend


@pytest.fixture
def concurrency_config():
    """Default concurrency configuration for testing"""
    return ConcurrencyConfig(
        max_concurrent_downloads=3,
        max_concurrent_conversions=2,
        max_concurrent_llm=2,
        queue_size=10,
        checkpoint_interval=5,
        worker_timeout_seconds=60,
        enable_backpressure=True,
        backpressure_threshold=0.8,
    )


@pytest.fixture
def mock_services():
    """Mock all Phase 2.5 and Phase 3 services"""
    services = {
        "fallback_pdf": Mock(),
        "llm": Mock(),
        "cache": Mock(),
        "dedup": Mock(),
        "filter": Mock(),
        "checkpoint": Mock(),
    }

    # Configure mocks
    services["fallback_pdf"].extract_with_fallback = AsyncMock()
    services["llm"].extract = AsyncMock()
    services["cache"].get_extraction = Mock(return_value=None)
    services["cache"].set_extraction = Mock()
    services["dedup"].find_duplicates = Mock()
    services["dedup"].update_indices = Mock()
    services["filter"].filter_and_rank = Mock()
    services["checkpoint"].get_processed_ids = Mock(return_value=set())
    services["checkpoint"].save_checkpoint = Mock()
    services["checkpoint"].clear_checkpoint = Mock()

    return services


@pytest.fixture
def pipeline(concurrency_config, mock_services):
    """Create ConcurrentPipeline with mocked dependencies"""
    return ConcurrentPipeline(
        config=concurrency_config,
        fallback_pdf_service=mock_services["fallback_pdf"],
        llm_service=mock_services["llm"],
        cache_service=mock_services["cache"],
        dedup_service=mock_services["dedup"],
        filter_service=mock_services["filter"],
        checkpoint_service=mock_services["checkpoint"],
    )


@pytest.fixture
def sample_papers():
    """Create sample papers for testing"""
    return [
        PaperMetadata(
            paper_id=f"paper-{i}",
            title=f"Test Paper {i}",
            abstract=f"Abstract {i}",
            authors=[Author(name=f"Author {i}")],
            url=f"https://example.com/paper-{i}",
            open_access_pdf=f"https://example.com/pdf-{i}.pdf",
            year=2024,
        )
        for i in range(5)
    ]


@pytest.fixture
def sample_targets():
    """Sample extraction targets"""
    return [
        ExtractionTarget(
            name="summary",
            description="Extract summary",
            output_format="text",
            required=True,
        )
    ]


@pytest.mark.asyncio
async def test_pipeline_initialization(concurrency_config, mock_services):
    """Test pipeline initializes correctly"""
    pipeline = ConcurrentPipeline(
        config=concurrency_config,
        fallback_pdf_service=mock_services["fallback_pdf"],
        llm_service=mock_services["llm"],
        cache_service=mock_services["cache"],
        dedup_service=mock_services["dedup"],
        filter_service=mock_services["filter"],
        checkpoint_service=mock_services["checkpoint"],
    )

    assert pipeline.config == concurrency_config
    assert pipeline.stats.total_papers == 0
    assert len(pipeline.worker_stats) == 0


@pytest.mark.asyncio
async def test_concurrent_processing_success(
    pipeline, mock_services, sample_papers, sample_targets
):
    """Test successful concurrent processing of papers"""
    # Configure dedup to pass all papers through
    mock_services["dedup"].find_duplicates.return_value = (sample_papers, [])
    mock_services["filter"].filter_and_rank.return_value = sample_papers

    # Configure PDF extraction success
    pdf_result = PDFExtractionResult(
        success=True,
        markdown="# Test Content",
        metadata={"backend": PDFBackend.PYMUPDF},
        quality_score=0.9,
    )
    mock_services["fallback_pdf"].extract_with_fallback.return_value = pdf_result

    # Configure LLM extraction success
    llm_result = PaperExtraction(
        paper_id="test",
        extraction_results=[
            ExtractionResult(
                target_name="summary",
                success=True,
                content="Test summary",
                confidence=0.9,
            )
        ],
        tokens_used=100,
        cost_usd=0.001,
    )
    mock_services["llm"].extract.return_value = llm_result

    # Process papers
    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=sample_papers,
        targets=sample_targets,
        run_id="test-run-1",
        query="test query",
    ):
        results.append(paper)

    # Verify results
    assert len(results) == len(sample_papers)
    assert all(r.extraction is not None for r in results)

    # Verify stats
    assert pipeline.stats.papers_completed == len(sample_papers)
    assert pipeline.stats.papers_failed == 0


@pytest.mark.asyncio
async def test_deduplication_integration(
    pipeline, mock_services, sample_papers, sample_targets
):
    """Test deduplication removes duplicate papers"""
    # Configure dedup to filter out 2 papers
    new_papers = sample_papers[:3]
    duplicates = sample_papers[3:]
    mock_services["dedup"].find_duplicates.return_value = (new_papers, duplicates)
    mock_services["filter"].filter_and_rank.return_value = new_papers

    # Configure successful processing
    pdf_result = PDFExtractionResult(
        success=True, markdown="content", metadata={"backend": PDFBackend.PYMUPDF}
    )
    mock_services["fallback_pdf"].extract_with_fallback.return_value = pdf_result
    mock_services["llm"].extract.return_value = PaperExtraction(
        paper_id="test", extraction_results=[], tokens_used=100, cost_usd=0.001
    )

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=sample_papers,
        targets=sample_targets,
        run_id="test-run-2",
        query="test",
    ):
        results.append(paper)

    # Should only process non-duplicate papers
    assert len(results) == len(new_papers)
    assert pipeline.stats.papers_deduplicated == len(duplicates)


@pytest.mark.asyncio
async def test_cache_hit(pipeline, mock_services, sample_papers, sample_targets):
    """Test cache hit skips PDF and LLM processing"""
    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = (sample_papers[:1], [])
    mock_services["filter"].filter_and_rank.return_value = sample_papers[:1]

    # Configure cache hit
    cached_extraction = PaperExtraction(
        paper_id="cached", extraction_results=[], tokens_used=50, cost_usd=0.0005
    )
    mock_services["cache"].get_extraction.return_value = cached_extraction

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=sample_papers[:1],
        targets=sample_targets,
        run_id="test-run-3",
        query="test",
    ):
        results.append(paper)

    # Verify cache was used
    assert len(results) == 1
    assert pipeline.stats.papers_cached == 1

    # Verify PDF and LLM services NOT called
    mock_services["fallback_pdf"].extract_with_fallback.assert_not_awaited()
    mock_services["llm"].extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_checkpoint_resume(
    pipeline, mock_services, sample_papers, sample_targets
):
    """Test checkpoint resume skips already processed papers"""
    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = (sample_papers, [])
    mock_services["filter"].filter_and_rank.return_value = sample_papers

    # Configure checkpoint with 2 already processed papers
    processed_ids = {sample_papers[0].paper_id, sample_papers[1].paper_id}
    mock_services["checkpoint"].get_processed_ids.return_value = processed_ids

    # Configure successful processing
    pdf_result = PDFExtractionResult(
        success=True, markdown="content", metadata={"backend": PDFBackend.PYMUPDF}
    )
    mock_services["fallback_pdf"].extract_with_fallback.return_value = pdf_result
    mock_services["llm"].extract.return_value = PaperExtraction(
        paper_id="test", extraction_results=[], tokens_used=100, cost_usd=0.001
    )

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=sample_papers,
        targets=sample_targets,
        run_id="test-run-4",
        query="test",
    ):
        results.append(paper)

    # Should only process pending papers
    assert len(results) == len(sample_papers) - len(processed_ids)


@pytest.mark.asyncio
async def test_worker_failure_handling(
    pipeline, mock_services, sample_papers, sample_targets
):
    """Test pipeline continues when individual papers fail"""
    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = (sample_papers[:3], [])
    mock_services["filter"].filter_and_rank.return_value = sample_papers[:3]

    # Configure first paper to fail, others succeed
    pdf_results = [
        PDFExtractionResult(
            success=False, error="Failed", metadata={"backend": PDFBackend.PYMUPDF}
        ),  # Fail
        PDFExtractionResult(
            success=True, markdown="ok", metadata={"backend": PDFBackend.PYMUPDF}
        ),  # Success
        PDFExtractionResult(
            success=True, markdown="ok", metadata={"backend": PDFBackend.PYMUPDF}
        ),
    ]
    mock_services["fallback_pdf"].extract_with_fallback.side_effect = pdf_results

    # Configure LLM success for papers with content
    mock_services["llm"].extract.return_value = PaperExtraction(
        paper_id="test", extraction_results=[], tokens_used=100, cost_usd=0.001
    )

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=sample_papers[:3],
        targets=sample_targets,
        run_id="test-run-5",
        query="test",
    ):
        results.append(paper)

    # Should process all papers despite one failure
    # Failed paper falls back to abstract, so still returns result
    assert len(results) >= 2  # At least successful papers


@pytest.mark.asyncio
async def test_abstract_fallback(pipeline, mock_services, sample_targets):
    """Test fallback to abstract when PDF unavailable"""
    # Paper without PDF
    paper_no_pdf = PaperMetadata(
        paper_id="no-pdf",
        title="Test Paper",
        abstract="Test abstract content",
        authors=[],
        url="https://example.com",
        open_access_pdf=None,  # No PDF
    )

    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = ([paper_no_pdf], [])
    mock_services["filter"].filter_and_rank.return_value = [paper_no_pdf]

    # Configure LLM to accept abstract
    mock_services["llm"].extract.return_value = PaperExtraction(
        paper_id="no-pdf", extraction_results=[], tokens_used=50, cost_usd=0.0005
    )

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=[paper_no_pdf],
        targets=sample_targets,
        run_id="test-run-6",
        query="test",
    ):
        results.append(paper)

    # Verify abstract was used
    assert len(results) == 1
    assert results[0].pdf_available is False

    # Verify LLM was called with abstract content
    mock_services["llm"].extract.assert_awaited_once()
    call_args = mock_services["llm"].extract.call_args[0]
    assert "Test abstract content" in call_args[0]


@pytest.mark.asyncio
async def test_periodic_checkpoint_saves(
    pipeline, mock_services, sample_papers, sample_targets
):
    """Test checkpoint saves periodically during processing"""
    # Set checkpoint interval to 2
    pipeline.config.checkpoint_interval = 2

    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = (sample_papers, [])
    mock_services["filter"].filter_and_rank.return_value = sample_papers

    # Configure successful processing
    pdf_result = PDFExtractionResult(
        success=True, markdown="content", metadata={"backend": PDFBackend.PYMUPDF}
    )
    mock_services["fallback_pdf"].extract_with_fallback.return_value = pdf_result
    mock_services["llm"].extract.return_value = PaperExtraction(
        paper_id="test", extraction_results=[], tokens_used=100, cost_usd=0.001
    )

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=sample_papers,
        targets=sample_targets,
        run_id="test-run-7",
        query="test",
    ):
        results.append(paper)

    # Verify checkpoint was called multiple times
    assert mock_services["checkpoint"].save_checkpoint.call_count >= 2


@pytest.mark.asyncio
async def test_empty_papers_list(pipeline, mock_services, sample_targets):
    """Test handling of empty papers list"""
    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = ([], [])
    mock_services["filter"].filter_and_rank.return_value = []

    # Configure checkpoint to return no pending papers
    mock_services["checkpoint"].get_processed_ids.return_value = set()

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=[], targets=sample_targets, run_id="test-run-8", query="test"
    ):
        results.append(paper)

    assert len(results) == 0


@pytest.mark.asyncio
async def test_llm_extraction_failure(
    pipeline, mock_services, sample_papers, sample_targets
):
    """Test handling of LLM extraction failures"""
    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = (sample_papers[:1], [])
    mock_services["filter"].filter_and_rank.return_value = sample_papers[:1]

    # Configure PDF success
    pdf_result = PDFExtractionResult(
        success=True, markdown="content", metadata={"backend": PDFBackend.PYMUPDF}
    )
    mock_services["fallback_pdf"].extract_with_fallback.return_value = pdf_result

    # Configure LLM failure
    mock_services["llm"].extract.side_effect = Exception("LLM API error")

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=sample_papers[:1],
        targets=sample_targets,
        run_id="test-run-9",
        query="test",
    ):
        results.append(paper)

    # Worker should handle error gracefully and not crash
    # Result should be None since extraction failed
    # No result yielded for failed extraction
    assert len(results) == 0
    assert pipeline.stats.papers_failed == 1


@pytest.mark.asyncio
async def test_get_stats(pipeline):
    """Test pipeline statistics retrieval"""
    stats = pipeline.get_stats()

    assert isinstance(stats, PipelineStats)
    assert stats.total_papers == 0
    assert stats.papers_completed == 0
    assert stats.papers_failed == 0


@pytest.mark.asyncio
async def test_worker_stats_tracking(
    pipeline, mock_services, sample_papers, sample_targets
):
    """Test worker statistics are tracked correctly"""
    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = (sample_papers[:2], [])
    mock_services["filter"].filter_and_rank.return_value = sample_papers[:2]

    # Configure successful processing
    pdf_result = PDFExtractionResult(
        success=True, markdown="content", metadata={"backend": PDFBackend.PYMUPDF}
    )
    mock_services["fallback_pdf"].extract_with_fallback.return_value = pdf_result
    mock_services["llm"].extract.return_value = PaperExtraction(
        paper_id="test", extraction_results=[], tokens_used=100, cost_usd=0.001
    )

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=sample_papers[:2],
        targets=sample_targets,
        run_id="test-run-10",
        query="test",
    ):
        results.append(paper)

    # Verify worker stats were created
    assert len(pipeline.worker_stats) > 0
    assert all(not w.is_active for w in pipeline.worker_stats)  # Workers finished


@pytest.mark.asyncio
async def test_filtering_integration(
    pipeline, mock_services, sample_papers, sample_targets
):
    """Test filtering service integration"""
    # Configure dedup to pass all papers
    mock_services["dedup"].find_duplicates.return_value = (sample_papers, [])

    # Configure filter to return only first 2 papers
    mock_services["filter"].filter_and_rank.return_value = sample_papers[:2]

    # Configure successful processing
    pdf_result = PDFExtractionResult(
        success=True, markdown="content", metadata={"backend": PDFBackend.PYMUPDF}
    )
    mock_services["fallback_pdf"].extract_with_fallback.return_value = pdf_result
    mock_services["llm"].extract.return_value = PaperExtraction(
        paper_id="test", extraction_results=[], tokens_used=100, cost_usd=0.001
    )

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=sample_papers,
        targets=sample_targets,
        run_id="test-run-11",
        query="test query",
    ):
        results.append(paper)

    # Should only process filtered papers
    assert len(results) == 2

    # Verify filter was called with query
    mock_services["filter"].filter_and_rank.assert_called_once()

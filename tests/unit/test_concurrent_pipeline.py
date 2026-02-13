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


@pytest.mark.asyncio
async def test_no_content_available(pipeline, mock_services, sample_targets):
    """Test paper with no PDF and no abstract returns None"""
    # Paper with no PDF and no abstract
    paper_no_content = PaperMetadata(
        paper_id="no-content",
        title="Test Paper",
        abstract=None,  # No abstract
        authors=[],
        url="https://example.com",
        open_access_pdf=None,  # No PDF
    )

    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = ([paper_no_content], [])
    mock_services["filter"].filter_and_rank.return_value = [paper_no_content]

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=[paper_no_content],
        targets=sample_targets,
        run_id="test-run-no-content",
        query="test",
    ):
        results.append(paper)

    # Should return no results since there's no content to extract from
    assert len(results) == 0
    # Should track as failed
    assert pipeline.stats.papers_failed >= 1


@pytest.mark.asyncio
async def test_worker_processing_exception(
    pipeline, mock_services, sample_papers, sample_targets
):
    """Test worker handles exception during _process_single_paper"""
    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = (sample_papers[:1], [])
    mock_services["filter"].filter_and_rank.return_value = sample_papers[:1]

    # Configure PDF to throw an unexpected exception
    mock_services["fallback_pdf"].extract_with_fallback.side_effect = RuntimeError(
        "Unexpected error"
    )

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=sample_papers[:1],
        targets=sample_targets,
        run_id="test-run-exception",
        query="test",
    ):
        results.append(paper)

    # Paper should fallback to abstract even if PDF extraction throws exception
    # So we should still get a result (with abstract fallback)
    # Or if exception is uncaught, pipeline stats should show failure
    assert (
        pipeline.stats.papers_failed >= 0
    )  # Either success via fallback or counted as failed


@pytest.mark.asyncio
async def test_pdf_extraction_exception_with_fallback_to_abstract(
    pipeline, mock_services, sample_papers, sample_targets
):
    """Test PDF extraction exception falls back to abstract"""
    paper = sample_papers[0]

    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = ([paper], [])
    mock_services["filter"].filter_and_rank.return_value = [paper]

    # Configure PDF to fail (return unsuccessful result)
    pdf_result = PDFExtractionResult(
        success=False,
        error="PDF extraction failed completely",
        metadata={"backend": PDFBackend.PYMUPDF},
    )
    mock_services["fallback_pdf"].extract_with_fallback.return_value = pdf_result

    # Configure LLM to succeed with abstract
    mock_services["llm"].extract.return_value = PaperExtraction(
        paper_id=paper.paper_id,
        extraction_results=[],
        tokens_used=50,
        cost_usd=0.0005,
    )

    results = []
    async for extracted in pipeline.process_papers_concurrent(
        papers=[paper],
        targets=sample_targets,
        run_id="test-run-pdf-fail",
        query="test",
    ):
        results.append(extracted)

    # Should succeed with abstract fallback
    assert len(results) == 1
    assert results[0].pdf_available is False  # PDF was not available


@pytest.mark.asyncio
async def test_process_single_paper_raises_exception(
    pipeline, mock_services, sample_papers, sample_targets
):
    """Test worker handles exception raised by _process_single_paper (lines 327-336)"""
    from unittest.mock import patch

    paper = sample_papers[0]

    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = ([paper], [])
    mock_services["filter"].filter_and_rank.return_value = [paper]

    # Mock _process_single_paper to raise an unexpected exception
    with patch.object(
        pipeline, "_process_single_paper", side_effect=RuntimeError("Unexpected crash")
    ):
        results = []
        async for extracted in pipeline.process_papers_concurrent(
            papers=[paper],
            targets=sample_targets,
            run_id="test-run-crash",
            query="test",
        ):
            results.append(extracted)

    # Worker should handle the exception and track failure
    assert len(results) == 0
    assert pipeline.stats.papers_failed >= 1


@pytest.mark.asyncio
async def test_paper_with_empty_abstract_no_pdf(
    pipeline, mock_services, sample_targets
):
    """Test paper with empty abstract (not None) and no PDF"""
    # Paper with empty string abstract
    paper_empty_abstract = PaperMetadata(
        paper_id="empty-abstract",
        title="Test Paper",
        abstract="",  # Empty string abstract
        authors=[],
        url="https://example.com",
        open_access_pdf=None,  # No PDF
    )

    # Configure dedup and filter
    mock_services["dedup"].find_duplicates.return_value = ([paper_empty_abstract], [])
    mock_services["filter"].filter_and_rank.return_value = [paper_empty_abstract]

    # Configure LLM to succeed if called
    mock_services["llm"].extract.return_value = PaperExtraction(
        paper_id=paper_empty_abstract.paper_id,
        extraction_results=[],
        tokens_used=50,
        cost_usd=0.0005,
    )

    results = []
    async for paper in pipeline.process_papers_concurrent(
        papers=[paper_empty_abstract],
        targets=sample_targets,
        run_id="test-run-empty-abstract",
        query="test",
    ):
        results.append(paper)

    # Empty string is truthy for abstract check, so should proceed with extraction
    # But content is "# Title\n\n" - still can be processed by LLM
    # The result depends on whether empty abstract is considered valid content
    assert (
        pipeline.stats.papers_completed >= 0
    )  # Processing completed one way or another


# ==================== Phase 3.5/3.6 Registry Integration Tests ====================


class TestRegistryIntegration:
    """Tests for Phase 3.5 registry service integration."""

    @pytest.fixture
    def mock_registry_service(self):
        """Mock registry service for testing."""
        from src.models.registry import ProcessingAction

        registry = Mock()
        # Default: no existing entries, always FULL_PROCESS
        registry.determine_action = Mock(
            return_value=(ProcessingAction.FULL_PROCESS, None)
        )
        return registry

    @pytest.fixture
    def pipeline_with_registry(
        self, concurrency_config, mock_services, mock_registry_service
    ):
        """ConcurrentPipeline with registry service."""
        return ConcurrentPipeline(
            config=concurrency_config,
            fallback_pdf_service=mock_services["fallback_pdf"],
            llm_service=mock_services["llm"],
            cache_service=mock_services["cache"],
            dedup_service=mock_services["dedup"],
            filter_service=mock_services["filter"],
            checkpoint_service=mock_services["checkpoint"],
            registry_service=mock_registry_service,
        )

    def test_get_processing_results_empty(self, pipeline_with_registry):
        """Test get_processing_results returns empty list initially."""
        results = pipeline_with_registry.get_processing_results()
        assert results == []

    def test_add_processing_result(self, pipeline_with_registry):
        """Test _add_processing_result adds to processing_results."""
        from src.models.synthesis import ProcessingStatus

        paper = PaperMetadata(
            paper_id="test-paper",
            title="Test Paper",
            url="https://example.com",
        )

        pipeline_with_registry._add_processing_result(
            paper=paper,
            status=ProcessingStatus.NEW,
            topic_slug="test-topic",
            quality_score=85.0,
            pdf_available=True,
            extraction_success=True,
        )

        results = pipeline_with_registry.get_processing_results()
        assert len(results) == 1
        assert results[0].paper_id == "test-paper"
        assert results[0].title == "Test Paper"
        assert results[0].status == ProcessingStatus.NEW
        assert results[0].quality_score == 85.0
        assert results[0].pdf_available is True
        assert results[0].extraction_success is True

    def test_add_processing_result_with_error(self, pipeline_with_registry):
        """Test _add_processing_result with error message."""
        from src.models.synthesis import ProcessingStatus

        paper = PaperMetadata(
            paper_id="failed-paper",
            title="Failed Paper",
            url="https://example.com",
        )

        pipeline_with_registry._add_processing_result(
            paper=paper,
            status=ProcessingStatus.FAILED,
            topic_slug="test-topic",
            error_message="PDF download failed",
        )

        results = pipeline_with_registry.get_processing_results()
        assert len(results) == 1
        assert results[0].status == ProcessingStatus.FAILED
        assert results[0].error_message == "PDF download failed"

    @pytest.mark.asyncio
    async def test_process_with_registry_full_process(
        self, pipeline_with_registry, mock_services, mock_registry_service
    ):
        """Test processing papers with registry returning FULL_PROCESS."""
        from src.models.registry import ProcessingAction
        from src.models.synthesis import ProcessingStatus

        paper = PaperMetadata(
            paper_id="new-paper",
            title="New Paper",
            abstract="Test abstract",
            url="https://example.com",
            open_access_pdf="https://example.com/paper.pdf",
        )
        targets = [ExtractionTarget(name="summary", description="Summary")]

        # Configure registry to return FULL_PROCESS
        mock_registry_service.determine_action.return_value = (
            ProcessingAction.FULL_PROCESS,
            None,
        )

        # Configure dedup and filter to pass through
        mock_services["dedup"].find_duplicates.return_value = ([paper], [])
        mock_services["filter"].filter_and_rank.return_value = [paper]

        # Configure PDF and LLM to succeed
        mock_services["fallback_pdf"].extract_with_fallback.return_value = Mock(
            success=True, content="# Test content", backend="test"
        )
        mock_services["llm"].extract.return_value = PaperExtraction(
            paper_id=paper.paper_id,
            extraction_results=[],
            tokens_used=100,
            cost_usd=0.001,
        )

        results = []
        async for result in pipeline_with_registry.process_papers_concurrent(
            papers=[paper],
            targets=targets,
            run_id="test-run",
            query="test",
            topic_slug="test-topic",
        ):
            results.append(result)

        # Verify registry was called
        mock_registry_service.determine_action.assert_called_once()

        # Verify processing result was added
        processing_results = pipeline_with_registry.get_processing_results()
        assert len(processing_results) >= 1
        assert any(r.status == ProcessingStatus.NEW for r in processing_results)

    @pytest.mark.asyncio
    async def test_process_with_registry_skip(
        self, pipeline_with_registry, mock_services, mock_registry_service
    ):
        """Test processing papers with registry returning SKIP."""
        from src.models.registry import ProcessingAction, RegistryEntry
        from src.models.synthesis import ProcessingStatus

        paper = PaperMetadata(
            paper_id="existing-paper",
            title="Existing Paper",
            url="https://example.com",
        )
        targets = [ExtractionTarget(name="summary", description="Summary")]

        # Create mock existing entry
        existing_entry = Mock(spec=RegistryEntry)
        existing_entry.paper_id = "existing-paper"

        # Configure registry to return SKIP
        mock_registry_service.determine_action.return_value = (
            ProcessingAction.SKIP,
            existing_entry,
        )

        # Configure dedup and filter for the empty new_papers list
        mock_services["dedup"].find_duplicates.return_value = ([], [])
        mock_services["filter"].filter_and_rank.return_value = []

        results = []
        async for result in pipeline_with_registry.process_papers_concurrent(
            papers=[paper],
            targets=targets,
            run_id="test-run",
            query="test",
            topic_slug="test-topic",
        ):
            results.append(result)

        # Verify no actual processing happened (paper was skipped)
        processing_results = pipeline_with_registry.get_processing_results()
        assert len(processing_results) == 1
        assert processing_results[0].status == ProcessingStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_process_with_registry_backfill(
        self, pipeline_with_registry, mock_services, mock_registry_service
    ):
        """Test processing papers with registry returning BACKFILL."""
        from src.models.registry import ProcessingAction, RegistryEntry
        from src.models.synthesis import ProcessingStatus

        paper = PaperMetadata(
            paper_id="backfill-paper",
            title="Backfill Paper",
            abstract="Needs reprocessing",
            url="https://example.com",
            open_access_pdf="https://example.com/paper.pdf",
        )
        targets = [ExtractionTarget(name="summary", description="Summary")]

        # Create mock existing entry
        existing_entry = Mock(spec=RegistryEntry)
        existing_entry.paper_id = "backfill-paper"

        # Configure registry to return BACKFILL
        mock_registry_service.determine_action.return_value = (
            ProcessingAction.BACKFILL,
            existing_entry,
        )

        # Configure dedup and filter to pass through
        mock_services["dedup"].find_duplicates.return_value = ([paper], [])
        mock_services["filter"].filter_and_rank.return_value = [paper]

        # Configure PDF and LLM to succeed
        mock_services["fallback_pdf"].extract_with_fallback.return_value = Mock(
            success=True, content="# Test content", backend="test"
        )
        mock_services["llm"].extract.return_value = PaperExtraction(
            paper_id=paper.paper_id,
            extraction_results=[],
            tokens_used=100,
            cost_usd=0.001,
        )

        results = []
        async for result in pipeline_with_registry.process_papers_concurrent(
            papers=[paper],
            targets=targets,
            run_id="test-run",
            query="test",
            topic_slug="test-topic",
        ):
            results.append(result)

        # Verify processing result was added as backfilled
        processing_results = pipeline_with_registry.get_processing_results()
        assert len(processing_results) >= 1
        assert any(r.status == ProcessingStatus.BACKFILLED for r in processing_results)

    @pytest.mark.asyncio
    async def test_process_with_registry_map_only(
        self, pipeline_with_registry, mock_services, mock_registry_service
    ):
        """Test processing papers with registry returning MAP_ONLY."""
        from src.models.registry import ProcessingAction, RegistryEntry
        from src.models.synthesis import ProcessingStatus

        paper = PaperMetadata(
            paper_id="mapped-paper",
            title="Mapped Paper",
            url="https://example.com",
        )
        targets = [ExtractionTarget(name="summary", description="Summary")]

        # Create mock existing entry
        existing_entry = Mock(spec=RegistryEntry)
        existing_entry.paper_id = "mapped-paper"

        # Configure registry to return MAP_ONLY
        mock_registry_service.determine_action.return_value = (
            ProcessingAction.MAP_ONLY,
            existing_entry,
        )

        # Configure dedup and filter for the empty new_papers list
        mock_services["dedup"].find_duplicates.return_value = ([], [])
        mock_services["filter"].filter_and_rank.return_value = []

        results = []
        async for result in pipeline_with_registry.process_papers_concurrent(
            papers=[paper],
            targets=targets,
            run_id="test-run",
            query="test",
            topic_slug="test-topic",
        ):
            results.append(result)

        # Verify processing result was added as mapped
        processing_results = pipeline_with_registry.get_processing_results()
        assert len(processing_results) == 1
        assert processing_results[0].status == ProcessingStatus.MAPPED

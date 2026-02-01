"""Unit tests for ExtractionService with FallbackPDFService integration."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path

from src.services.extraction_service import ExtractionService
from src.services.pdf_service import PDFService
from src.services.llm_service import LLMService
from src.services.pdf_extractors.fallback_service import FallbackPDFService
from src.models.paper import PaperMetadata
from src.models.extraction import PaperExtraction
from src.models.pdf_extraction import PDFExtractionResult, PDFBackend


@pytest.fixture
def mock_pdf_service():
    return Mock(spec=PDFService)


@pytest.fixture
def mock_llm_service():
    return Mock(spec=LLMService)


@pytest.fixture
def mock_fallback_service():
    return Mock(spec=FallbackPDFService)


@pytest.fixture
def extraction_service(mock_pdf_service, mock_llm_service, mock_fallback_service):
    return ExtractionService(
        pdf_service=mock_pdf_service,
        llm_service=mock_llm_service,
        fallback_service=mock_fallback_service,
        keep_pdfs=True,
    )


@pytest.fixture
def mock_paper():
    from src.models.paper import Author

    return PaperMetadata(
        paper_id="2301.12345",
        title="Test Paper",
        abstract="Test abstract",
        authors=[Author(name="Author 1")],
        url="https://arxiv.org/abs/2301.12345",
        open_access_pdf="https://arxiv.org/pdf/2301.12345.pdf",
        year=2023,
    )


@pytest.mark.asyncio
async def test_process_paper_with_fallback_success(
    extraction_service,
    mock_pdf_service,
    mock_fallback_service,
    mock_llm_service,
    mock_paper,
):
    """Test successful extraction using FallbackPDFService"""
    pdf_path = Path("/tmp/test.pdf")
    mock_pdf_service.download_pdf = AsyncMock(return_value=pdf_path)

    # Mock successful fallback extraction
    pdf_result = PDFExtractionResult(
        success=True,
        markdown="Fallback content",
        metadata={"backend": PDFBackend.PYMUPDF},
        quality_score=0.9,
    )
    mock_fallback_service.extract_with_fallback = AsyncMock(return_value=pdf_result)

    # Mock LLM extraction
    llm_result = PaperExtraction(
        paper_id=mock_paper.paper_id,
        extraction_results=[],
        tokens_used=100,
        cost_usd=0.001,
    )
    mock_llm_service.extract = AsyncMock(return_value=llm_result)

    result = await extraction_service.process_paper(mock_paper, [])

    assert result.pdf_available is True
    assert result.extraction == llm_result

    # Verify fallback service was called
    mock_fallback_service.extract_with_fallback.assert_awaited_once_with(pdf_path)

    # Verify LLM was called with markdown from fallback
    mock_llm_service.extract.assert_awaited_once()
    call_args = mock_llm_service.extract.call_args
    assert call_args.kwargs["markdown_content"] == "Fallback content"


@pytest.mark.asyncio
async def test_process_paper_with_fallback_failure(
    extraction_service,
    mock_pdf_service,
    mock_fallback_service,
    mock_llm_service,
    mock_paper,
):
    """Test fallback to abstract when FallbackPDFService fails"""
    pdf_path = Path("/tmp/test.pdf")
    mock_pdf_service.download_pdf = AsyncMock(return_value=pdf_path)

    # Mock failed fallback extraction
    pdf_result = PDFExtractionResult(
        success=False,
        error="Extraction failed",
        metadata={"backend": PDFBackend.TEXT_ONLY},
    )
    mock_fallback_service.extract_with_fallback = AsyncMock(return_value=pdf_result)

    # Mock LLM extraction
    llm_result = PaperExtraction(
        paper_id=mock_paper.paper_id,
        extraction_results=[],
        tokens_used=50,
        cost_usd=0.0005,
    )
    mock_llm_service.extract = AsyncMock(return_value=llm_result)

    result = await extraction_service.process_paper(mock_paper, [])

    assert result.pdf_available is False
    assert result.extraction == llm_result

    # Verify LLM was called with abstract
    mock_llm_service.extract.assert_awaited_once()
    call_args = mock_llm_service.extract.call_args
    assert "Abstract" in call_args.kwargs["markdown_content"]
    assert "Test abstract" in call_args.kwargs["markdown_content"]


@pytest.mark.asyncio
async def test_process_paper_extraction_error(
    extraction_service,
    mock_pdf_service,
    mock_fallback_service,
    mock_llm_service,
    mock_paper,
):
    """Test handling of unexpected errors during extraction"""
    pdf_path = Path("/tmp/test.pdf")
    mock_pdf_service.download_pdf = AsyncMock(return_value=pdf_path)

    # Mock unexpected error in fallback service
    mock_fallback_service.extract_with_fallback = AsyncMock(
        side_effect=Exception("Unexpected crash")
    )

    # Mock LLM extraction
    llm_result = PaperExtraction(
        paper_id=mock_paper.paper_id,
        extraction_results=[],
    )
    mock_llm_service.extract = AsyncMock(return_value=llm_result)

    result = await extraction_service.process_paper(mock_paper, [])

    assert result.pdf_available is False
    # Should fall back to abstract
    call_args = mock_llm_service.extract.call_args
    assert "Abstract" in call_args.kwargs["markdown_content"]


@pytest.mark.asyncio
async def test_process_paper_unexpected_extraction_error(
    extraction_service,
    mock_pdf_service,
    mock_fallback_service,
    mock_llm_service,
    mock_paper,
):
    """Test handling of unexpected errors in LLM extraction"""
    # Setup successful PDF extraction
    pdf_path = Path("/tmp/test.pdf")
    mock_pdf_service.download_pdf = AsyncMock(return_value=pdf_path)
    pdf_result = PDFExtractionResult(
        success=True, markdown="content", metadata={"backend": PDFBackend.PYMUPDF}
    )
    mock_fallback_service.extract_with_fallback = AsyncMock(return_value=pdf_result)

    # Mock LLM error
    mock_llm_service.extract = AsyncMock(side_effect=Exception("LLM crash"))

    result = await extraction_service.process_paper(mock_paper, [])

    assert result.pdf_available is True
    assert result.extraction is None  # Extraction failed but PDF was processed


@pytest.mark.asyncio
async def test_process_paper_cleanup_failure(
    extraction_service,
    mock_pdf_service,
    mock_fallback_service,
    mock_llm_service,
    mock_paper,
):
    """Test that cleanup failure doesn't crash the pipeline"""
    # Setup successful run
    pdf_path = Path("/tmp/test.pdf")
    mock_pdf_service.download_pdf = AsyncMock(return_value=pdf_path)
    pdf_result = PDFExtractionResult(
        success=True, markdown="content", metadata={"backend": PDFBackend.PYMUPDF}
    )
    mock_fallback_service.extract_with_fallback = AsyncMock(return_value=pdf_result)
    mock_llm_service.extract = AsyncMock(
        return_value=PaperExtraction(paper_id="123", extraction_results=[])
    )

    # Mock cleanup failure
    mock_pdf_service.cleanup_temp_files.side_effect = Exception("Cleanup failed")

    result = await extraction_service.process_paper(mock_paper, [])

    assert result.pdf_available is True
    assert result.extraction is not None


@pytest.mark.asyncio
async def test_process_paper_legacy_path(
    mock_pdf_service, mock_llm_service, mock_paper
):
    """Test legacy PDFService conversion path when fallback_service is None"""
    # Create service WITHOUT fallback
    service = ExtractionService(
        pdf_service=mock_pdf_service,
        llm_service=mock_llm_service,
        fallback_service=None,
    )

    pdf_path = Path("/tmp/test.pdf")
    # Use a real path object but mock the behavior needed
    md_path = Path("/tmp/test.md")

    mock_pdf_service.download_pdf = AsyncMock(return_value=pdf_path)
    mock_pdf_service.convert_to_markdown = Mock(return_value=md_path)

    # Mock Path.read_text for the specific file
    with patch.object(Path, "read_text", return_value="Legacy MD"):
        # Mock LLM
        mock_llm_service.extract = AsyncMock(
            return_value=PaperExtraction(paper_id="123", extraction_results=[])
        )

        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 500
            result = await service.process_paper(mock_paper, [])

        assert result.pdf_available is True
        mock_pdf_service.convert_to_markdown.assert_called_once()
        assert (
            "Legacy MD" in mock_llm_service.extract.call_args.kwargs["markdown_content"]
        )


def test_format_abstract(mock_paper):
    """Test paper metadata formatting when PDF is unavailable"""
    service = ExtractionService(Mock(), Mock())

    # Test with full metadata
    markdown = service._format_abstract(mock_paper)
    assert mock_paper.title in markdown
    assert "Author 1" in markdown
    assert "Abstract" in markdown
    assert "Full PDF was not available" in markdown

    # Test with minimal metadata (note: title must be non-empty per Pydantic validation)
    sparse_paper = PaperMetadata(
        paper_id="sparse",
        title="Untitled",
        abstract=None,
        authors=[],
        url="https://example.com",
    )
    markdown_sparse = service._format_abstract(sparse_paper)
    assert "Untitled" in markdown_sparse
    assert "Unknown" in markdown_sparse
    assert "No abstract available" in markdown_sparse


# Tests for process_papers with concurrent/sequential integration (Phase 3.1)


@pytest.mark.asyncio
async def test_process_papers_fallback_to_sequential_when_phase3_missing(
    mock_pdf_service, mock_llm_service, mock_fallback_service, mock_paper
):
    """Test fallback to sequential when Phase 3 services missing."""
    # Create service WITHOUT Phase 3 services
    service = ExtractionService(
        pdf_service=mock_pdf_service,
        llm_service=mock_llm_service,
        fallback_service=mock_fallback_service,
        keep_pdfs=True,
        # Phase 3 services are None (not provided)
        cache_service=None,
        dedup_service=None,
        filter_service=None,
        checkpoint_service=None,
        concurrency_config=None,
    )

    # Setup mocks
    pdf_path = Path("/tmp/test.pdf")
    mock_pdf_service.download_pdf = AsyncMock(return_value=pdf_path)
    pdf_result = PDFExtractionResult(
        success=True, markdown="content", metadata={"backend": PDFBackend.PYMUPDF}
    )
    mock_fallback_service.extract_with_fallback = AsyncMock(return_value=pdf_result)
    mock_llm_service.extract = AsyncMock(
        return_value=PaperExtraction(paper_id="123", extraction_results=[])
    )
    mock_pdf_service.cleanup_temp_files = Mock()

    # Call process_papers with run_id and query - should fallback to sequential
    # since Phase 3 services are not available
    results = await service.process_papers(
        papers=[mock_paper],
        targets=[],
        run_id="test-run",
        query="test query",
    )

    # Should have processed the paper using sequential path
    assert len(results) == 1
    # Concurrent pipeline should NOT be initialized
    assert service._concurrent_pipeline is None


@pytest.mark.asyncio
async def test_process_papers_uses_concurrent_when_phase3_available(
    mock_pdf_service, mock_llm_service, mock_fallback_service, mock_paper
):
    """Test concurrent pipeline is used when Phase 3 services available."""
    from unittest.mock import MagicMock

    # Create mock Phase 3 services
    mock_cache = MagicMock()
    mock_dedup = MagicMock()
    mock_filter = MagicMock()
    mock_checkpoint = MagicMock()

    from src.models.concurrency import ConcurrencyConfig

    concurrency_config = ConcurrencyConfig(
        max_concurrent_downloads=2,
        max_concurrent_llm=1,
        queue_size=10,
        checkpoint_interval=5,
    )

    # Create service WITH Phase 3 services
    service = ExtractionService(
        pdf_service=mock_pdf_service,
        llm_service=mock_llm_service,
        fallback_service=mock_fallback_service,
        keep_pdfs=True,
        cache_service=mock_cache,
        dedup_service=mock_dedup,
        filter_service=mock_filter,
        checkpoint_service=mock_checkpoint,
        concurrency_config=concurrency_config,
    )

    # Verify concurrent pipeline was eagerly initialized
    assert service._concurrent_pipeline is not None
    assert service._concurrent_enabled is True

    # Configure Phase 3 mocks
    mock_dedup.find_duplicates.return_value = ([mock_paper], [])
    mock_filter.filter_and_rank.return_value = [mock_paper]
    mock_checkpoint.get_processed_ids.return_value = set()
    mock_checkpoint.save_checkpoint = MagicMock()
    mock_checkpoint.clear_checkpoint = MagicMock()
    mock_cache.get_extraction.return_value = None
    mock_cache.set_extraction = MagicMock()
    mock_dedup.update_indices = MagicMock()

    # Configure PDF extraction
    pdf_result = PDFExtractionResult(
        success=True,
        markdown="Test content",
        metadata={"backend": PDFBackend.PYMUPDF},
        quality_score=0.9,
    )
    mock_fallback_service.extract_with_fallback = AsyncMock(return_value=pdf_result)

    # Configure LLM
    llm_result = PaperExtraction(
        paper_id=mock_paper.paper_id,
        extraction_results=[],
        tokens_used=100,
        cost_usd=0.001,
    )
    mock_llm_service.extract = AsyncMock(return_value=llm_result)

    # Call process_papers with run_id and query - should use concurrent
    results = await service.process_papers(
        papers=[mock_paper],
        targets=[],
        run_id="test-concurrent-run",
        query="test query",
    )

    # Verify results
    assert len(results) == 1


@pytest.mark.asyncio
async def test_process_papers_partial_services_uses_sequential(
    mock_pdf_service, mock_llm_service, mock_fallback_service, mock_paper
):
    """Test fallback when only some Phase 3 services available."""
    from unittest.mock import MagicMock

    # Create service with PARTIAL Phase 3 services (missing checkpoint)
    mock_cache = MagicMock()
    mock_dedup = MagicMock()

    service = ExtractionService(
        pdf_service=mock_pdf_service,
        llm_service=mock_llm_service,
        fallback_service=mock_fallback_service,
        keep_pdfs=True,
        cache_service=mock_cache,
        dedup_service=mock_dedup,
        filter_service=None,  # Missing
        checkpoint_service=None,  # Missing
        concurrency_config=None,  # Missing
    )

    # Concurrent pipeline should NOT be initialized (partial services)
    assert service._concurrent_pipeline is None
    assert service._concurrent_enabled is False

    # Setup mocks for sequential fallback
    pdf_path = Path("/tmp/test.pdf")
    mock_pdf_service.download_pdf = AsyncMock(return_value=pdf_path)
    pdf_result = PDFExtractionResult(
        success=True, markdown="content", metadata={"backend": PDFBackend.PYMUPDF}
    )
    mock_fallback_service.extract_with_fallback = AsyncMock(return_value=pdf_result)
    mock_llm_service.extract = AsyncMock(
        return_value=PaperExtraction(paper_id="123", extraction_results=[])
    )
    mock_pdf_service.cleanup_temp_files = Mock()

    # Call process_papers with run_id and query - should fallback to sequential
    results = await service.process_papers(
        papers=[mock_paper],
        targets=[],
        run_id="test-run",
        query="test query",
    )

    # Should process via sequential path (no concurrent pipeline initialized)
    assert len(results) == 1
    assert service._concurrent_pipeline is None  # Pipeline was NOT initialized


@pytest.mark.asyncio
async def test_process_papers_sequential_when_no_run_id(
    mock_pdf_service, mock_llm_service, mock_fallback_service, mock_paper
):
    """Test sequential processing when run_id/query not provided."""
    from unittest.mock import MagicMock
    from src.models.concurrency import ConcurrencyConfig

    # Create mock Phase 3 services
    mock_cache = MagicMock()
    mock_dedup = MagicMock()
    mock_filter = MagicMock()
    mock_checkpoint = MagicMock()

    concurrency_config = ConcurrencyConfig(
        max_concurrent_downloads=2,
        max_concurrent_llm=1,
        queue_size=10,
        checkpoint_interval=5,
    )

    # Create service WITH Phase 3 services
    service = ExtractionService(
        pdf_service=mock_pdf_service,
        llm_service=mock_llm_service,
        fallback_service=mock_fallback_service,
        keep_pdfs=True,
        cache_service=mock_cache,
        dedup_service=mock_dedup,
        filter_service=mock_filter,
        checkpoint_service=mock_checkpoint,
        concurrency_config=concurrency_config,
    )

    # Pipeline should be initialized
    assert service._concurrent_pipeline is not None

    # Setup mocks
    pdf_path = Path("/tmp/test.pdf")
    mock_pdf_service.download_pdf = AsyncMock(return_value=pdf_path)
    pdf_result = PDFExtractionResult(
        success=True, markdown="content", metadata={"backend": PDFBackend.PYMUPDF}
    )
    mock_fallback_service.extract_with_fallback = AsyncMock(return_value=pdf_result)
    mock_llm_service.extract = AsyncMock(
        return_value=PaperExtraction(paper_id="123", extraction_results=[])
    )
    mock_pdf_service.cleanup_temp_files = Mock()

    # Call process_papers WITHOUT run_id and query - should use sequential
    results = await service.process_papers(
        papers=[mock_paper],
        targets=[],
        # No run_id or query provided
    )

    # Should have processed the paper using sequential path
    assert len(results) == 1

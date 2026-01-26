"""Unit tests for ExtractionService with FallbackPDFService integration."""

import pytest
from unittest.mock import Mock, AsyncMock
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
    return PaperMetadata(
        paper_id="2301.12345",
        title="Test Paper",
        abstract="Test abstract",
        authors=[],
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

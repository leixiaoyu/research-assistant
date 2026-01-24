"""Unit tests for Extraction Service (Phase 2)

Tests for:
- Service initialization
- Single paper processing (success/failure scenarios)
- Batch paper processing
- Fallback strategies (PDF → abstract)
- Error isolation
- Summary statistics
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from src.services.extraction_service import ExtractionService
from src.services.pdf_service import PDFService
from src.services.llm_service import LLMService
from src.models.paper import PaperMetadata, Author
from src.models.extraction import (
    ExtractionTarget,
    ExtractionResult,
    PaperExtraction,
    ExtractedPaper
)
from src.utils.exceptions import (
    PDFDownloadError,
    ConversionError,
    ExtractionError,
    FileSizeError
)


@pytest.fixture
def mock_pdf_service():
    """Create mock PDF service"""
    service = Mock(spec=PDFService)
    service.download_pdf = AsyncMock()
    service.convert_to_markdown = Mock()
    service.cleanup_temp_files = Mock()
    return service


@pytest.fixture
def mock_llm_service():
    """Create mock LLM service"""
    service = Mock(spec=LLMService)
    service.extract = AsyncMock()
    return service


@pytest.fixture
def extraction_service(mock_pdf_service, mock_llm_service):
    """Create ExtractionService instance"""
    return ExtractionService(
        pdf_service=mock_pdf_service,
        llm_service=mock_llm_service,
        keep_pdfs=True
    )


@pytest.fixture
def paper_with_pdf():
    """Create paper metadata with PDF"""
    return PaperMetadata(
        paper_id="2301.12345",
        title="Test Paper with PDF",
        abstract="This is a test abstract.",
        url="https://example.com/paper",
        open_access_pdf="https://example.com/paper.pdf",
        authors=[Author(name="John Doe")],
        year=2023,
        citation_count=10,
        venue="ArXiv"
    )


@pytest.fixture
def paper_without_pdf():
    """Create paper metadata without PDF"""
    return PaperMetadata(
        paper_id="2301.67890",
        title="Test Paper without PDF",
        abstract="This paper has no PDF.",
        url="https://example.com/paper2",
        open_access_pdf=None,
        authors=[Author(name="Jane Smith")],
        year=2023,
        citation_count=5,
        venue="Conference"
    )


@pytest.fixture
def extraction_targets():
    """Create test extraction targets"""
    return [
        ExtractionTarget(
            name="system_prompts",
            description="Extract system prompts",
            output_format="list",
            required=False
        )
    ]


def test_extraction_service_initialization(mock_pdf_service, mock_llm_service):
    """Test ExtractionService initializes correctly"""
    service = ExtractionService(
        pdf_service=mock_pdf_service,
        llm_service=mock_llm_service,
        keep_pdfs=False
    )

    assert service.pdf_service == mock_pdf_service
    assert service.llm_service == mock_llm_service
    assert service.keep_pdfs is False


@pytest.mark.asyncio
async def test_process_paper_full_pipeline_success(
    extraction_service,
    mock_pdf_service,
    mock_llm_service,
    paper_with_pdf,
    extraction_targets
):
    """Test successful processing with full PDF pipeline"""
    # Mock PDF download
    pdf_path = Path("/temp/pdfs/2301.12345.pdf")
    mock_pdf_service.download_pdf.return_value = pdf_path

    # Mock PDF conversion
    md_path = MagicMock(spec=Path)
    md_path.read_text.return_value = "# Test Paper\n\nThis is the content."
    mock_pdf_service.convert_to_markdown.return_value = md_path

    # Mock LLM extraction
    extraction = PaperExtraction(
        paper_id="2301.12345",
        extraction_results=[
            ExtractionResult(
                target_name="system_prompts",
                success=True,
                content=["Prompt 1"],
                confidence=0.9
            )
        ],
        tokens_used=50000,
        cost_usd=0.20,
        extraction_timestamp=datetime.utcnow()
    )
    mock_llm_service.extract.return_value = extraction

    # Process paper
    result = await extraction_service.process_paper(paper_with_pdf, extraction_targets)

    # Verify PDF pipeline was called
    mock_pdf_service.download_pdf.assert_called_once_with(
        url="https://example.com/paper.pdf",
        paper_id="2301.12345"
    )
    mock_pdf_service.convert_to_markdown.assert_called_once_with(
        pdf_path=pdf_path,
        paper_id="2301.12345"
    )

    # Verify LLM extraction was called with markdown content
    mock_llm_service.extract.assert_called_once()
    call_args = mock_llm_service.extract.call_args
    assert call_args[1]["markdown_content"] == "# Test Paper\n\nThis is the content."
    assert call_args[1]["targets"] == extraction_targets
    assert call_args[1]["paper_metadata"] == paper_with_pdf

    # Verify result
    assert result.pdf_available is True
    assert result.pdf_path == str(pdf_path)
    assert result.markdown_path is not None
    assert result.extraction == extraction
    assert result.metadata == paper_with_pdf

    # Verify cleanup was called
    mock_pdf_service.cleanup_temp_files.assert_called_once_with(
        paper_id="2301.12345",
        keep_pdfs=True
    )


@pytest.mark.asyncio
async def test_process_paper_pdf_download_failure_fallback(
    extraction_service,
    mock_pdf_service,
    mock_llm_service,
    paper_with_pdf,
    extraction_targets
):
    """Test fallback to abstract when PDF download fails"""
    # Mock PDF download failure
    mock_pdf_service.download_pdf.side_effect = PDFDownloadError("Download failed")

    # Mock successful LLM extraction on abstract
    extraction = PaperExtraction(
        paper_id="2301.12345",
        extraction_results=[],
        tokens_used=5000,
        cost_usd=0.02,
        extraction_timestamp=datetime.utcnow()
    )
    mock_llm_service.extract.return_value = extraction

    # Process paper
    result = await extraction_service.process_paper(paper_with_pdf, extraction_targets)

    # Verify PDF download was attempted
    mock_pdf_service.download_pdf.assert_called_once()

    # Verify LLM extraction was called with formatted abstract
    mock_llm_service.extract.assert_called_once()
    call_args = mock_llm_service.extract.call_args
    markdown_content = call_args[1]["markdown_content"]
    assert "Test Paper with PDF" in markdown_content
    assert "This is a test abstract." in markdown_content
    assert "John Doe" in markdown_content

    # Verify result
    assert result.pdf_available is False
    assert result.pdf_path is None
    assert result.markdown_path is None
    assert result.extraction == extraction


@pytest.mark.asyncio
async def test_process_paper_pdf_conversion_failure_fallback(
    extraction_service,
    mock_pdf_service,
    mock_llm_service,
    paper_with_pdf,
    extraction_targets
):
    """Test fallback to abstract when PDF conversion fails"""
    # Mock successful PDF download
    pdf_path = Path("/temp/pdfs/2301.12345.pdf")
    mock_pdf_service.download_pdf.return_value = pdf_path

    # Mock PDF conversion failure
    mock_pdf_service.convert_to_markdown.side_effect = ConversionError("Conversion timeout")

    # Mock LLM extraction
    extraction = PaperExtraction(
        paper_id="2301.12345",
        extraction_results=[],
        tokens_used=5000,
        cost_usd=0.02,
        extraction_timestamp=datetime.utcnow()
    )
    mock_llm_service.extract.return_value = extraction

    # Process paper
    result = await extraction_service.process_paper(paper_with_pdf, extraction_targets)

    # Verify both PDF operations were attempted
    mock_pdf_service.download_pdf.assert_called_once()
    mock_pdf_service.convert_to_markdown.assert_called_once()

    # Verify fallback to abstract
    mock_llm_service.extract.assert_called_once()
    call_args = mock_llm_service.extract.call_args
    markdown_content = call_args[1]["markdown_content"]
    assert "Test Paper with PDF" in markdown_content
    assert "Full PDF was not available" in markdown_content

    # Verify result
    assert result.pdf_available is False


@pytest.mark.asyncio
async def test_process_paper_no_pdf_available(
    extraction_service,
    mock_pdf_service,
    mock_llm_service,
    paper_without_pdf,
    extraction_targets
):
    """Test processing when no PDF is available"""
    # Mock LLM extraction
    extraction = PaperExtraction(
        paper_id="2301.67890",
        extraction_results=[],
        tokens_used=3000,
        cost_usd=0.01,
        extraction_timestamp=datetime.utcnow()
    )
    mock_llm_service.extract.return_value = extraction

    # Process paper
    result = await extraction_service.process_paper(paper_without_pdf, extraction_targets)

    # Verify PDF pipeline was NOT attempted
    mock_pdf_service.download_pdf.assert_not_called()
    mock_pdf_service.convert_to_markdown.assert_not_called()

    # Verify LLM extraction was called with formatted abstract
    mock_llm_service.extract.assert_called_once()
    call_args = mock_llm_service.extract.call_args
    markdown_content = call_args[1]["markdown_content"]
    assert "Test Paper without PDF" in markdown_content
    assert "This paper has no PDF." in markdown_content

    # Verify result
    assert result.pdf_available is False
    assert result.extraction == extraction


@pytest.mark.asyncio
async def test_process_paper_llm_extraction_failure(
    extraction_service,
    mock_pdf_service,
    mock_llm_service,
    paper_without_pdf,
    extraction_targets
):
    """Test processing continues when LLM extraction fails"""
    # Mock LLM extraction failure
    mock_llm_service.extract.side_effect = ExtractionError("LLM API error")

    # Process paper - should not raise
    result = await extraction_service.process_paper(paper_without_pdf, extraction_targets)

    # Verify extraction was attempted
    mock_llm_service.extract.assert_called_once()

    # Verify result has no extraction
    assert result.extraction is None
    assert result.metadata == paper_without_pdf


@pytest.mark.asyncio
async def test_process_paper_unexpected_error_during_pdf_pipeline(
    extraction_service,
    mock_pdf_service,
    mock_llm_service,
    paper_with_pdf,
    extraction_targets
):
    """Test fallback to abstract on unexpected errors"""
    # Mock unexpected error during PDF download
    mock_pdf_service.download_pdf.side_effect = RuntimeError("Unexpected error")

    # Mock LLM extraction
    extraction = PaperExtraction(
        paper_id="2301.12345",
        extraction_results=[],
        tokens_used=5000,
        cost_usd=0.02,
        extraction_timestamp=datetime.utcnow()
    )
    mock_llm_service.extract.return_value = extraction

    # Process paper - should not raise
    result = await extraction_service.process_paper(paper_with_pdf, extraction_targets)

    # Verify fallback to abstract
    assert result.pdf_available is False
    assert result.extraction == extraction


@pytest.mark.asyncio
async def test_process_paper_cleanup_always_called(
    extraction_service,
    mock_pdf_service,
    mock_llm_service,
    paper_with_pdf,
    extraction_targets
):
    """Test cleanup is always called even if processing fails"""
    # Mock PDF download failure
    mock_pdf_service.download_pdf.side_effect = PDFDownloadError("Failed")
    mock_llm_service.extract.side_effect = ExtractionError("Failed")

    # Process paper
    await extraction_service.process_paper(paper_with_pdf, extraction_targets)

    # Verify cleanup was called
    mock_pdf_service.cleanup_temp_files.assert_called_once_with(
        paper_id="2301.12345",
        keep_pdfs=True
    )


@pytest.mark.asyncio
async def test_process_paper_cleanup_failure_does_not_crash(
    extraction_service,
    mock_pdf_service,
    mock_llm_service,
    paper_without_pdf,
    extraction_targets
):
    """Test processing continues even if cleanup fails"""
    # Mock cleanup failure
    mock_pdf_service.cleanup_temp_files.side_effect = Exception("Cleanup failed")

    # Mock LLM extraction
    extraction = PaperExtraction(
        paper_id="2301.67890",
        extraction_results=[],
        tokens_used=3000,
        cost_usd=0.01,
        extraction_timestamp=datetime.utcnow()
    )
    mock_llm_service.extract.return_value = extraction

    # Process paper - should not raise
    result = await extraction_service.process_paper(paper_without_pdf, extraction_targets)

    # Verify result is valid
    assert result.extraction == extraction


@pytest.mark.asyncio
async def test_process_papers_batch_processing(
    extraction_service,
    mock_pdf_service,
    mock_llm_service,
    paper_with_pdf,
    paper_without_pdf,
    extraction_targets
):
    """Test batch processing of multiple papers"""
    papers = [paper_with_pdf, paper_without_pdf]

    # Mock PDF pipeline for first paper
    pdf_path = Path("/temp/pdfs/2301.12345.pdf")
    md_path = MagicMock(spec=Path)
    md_path.read_text.return_value = "# Paper 1"
    mock_pdf_service.download_pdf.return_value = pdf_path
    mock_pdf_service.convert_to_markdown.return_value = md_path

    # Mock LLM extractions
    extraction1 = PaperExtraction(
        paper_id="2301.12345",
        extraction_results=[],
        tokens_used=50000,
        cost_usd=0.20,
        extraction_timestamp=datetime.utcnow()
    )
    extraction2 = PaperExtraction(
        paper_id="2301.67890",
        extraction_results=[],
        tokens_used=5000,
        cost_usd=0.02,
        extraction_timestamp=datetime.utcnow()
    )
    mock_llm_service.extract.side_effect = [extraction1, extraction2]

    # Process batch
    results = await extraction_service.process_papers(papers, extraction_targets)

    # Verify all papers were processed
    assert len(results) == 2
    assert results[0].metadata == paper_with_pdf
    assert results[1].metadata == paper_without_pdf
    assert results[0].pdf_available is True
    assert results[1].pdf_available is False

    # Verify LLM was called twice
    assert mock_llm_service.extract.call_count == 2


@pytest.mark.asyncio
async def test_process_papers_continues_on_individual_failures(
    extraction_service,
    mock_pdf_service,
    mock_llm_service,
    paper_with_pdf,
    paper_without_pdf,
    extraction_targets
):
    """Test batch processing continues even if individual papers fail"""
    papers = [paper_with_pdf, paper_without_pdf]

    # Mock first paper fails completely
    mock_pdf_service.download_pdf.side_effect = PDFDownloadError("Failed")
    mock_llm_service.extract.side_effect = [
        ExtractionError("Failed"),  # First paper fails
        PaperExtraction(  # Second paper succeeds
            paper_id="2301.67890",
            extraction_results=[],
            tokens_used=5000,
            cost_usd=0.02,
            extraction_timestamp=datetime.utcnow()
        )
    ]

    # Process batch
    results = await extraction_service.process_papers(papers, extraction_targets)

    # Verify all papers were processed
    assert len(results) == 2
    assert results[0].extraction is None  # First failed
    assert results[1].extraction is not None  # Second succeeded


def test_format_abstract_complete_metadata(extraction_service, paper_with_pdf):
    """Test _format_abstract with complete metadata"""
    markdown = extraction_service._format_abstract(paper_with_pdf)

    # Check all metadata is present
    assert "Test Paper with PDF" in markdown
    assert "John Doe" in markdown
    assert "2023" in markdown
    assert "ArXiv" in markdown
    assert "10" in markdown  # Citation count
    assert "This is a test abstract." in markdown
    assert "Full PDF was not available" in markdown


def test_format_abstract_minimal_metadata(extraction_service):
    """Test _format_abstract with minimal metadata"""
    paper = PaperMetadata(
        paper_id="test",
        title=None,
        abstract=None,
        url="https://example.com",
        authors=[],
        citation_count=0,
        year=None,
        venue=None
    )

    markdown = extraction_service._format_abstract(paper)

    # Check defaults are used
    assert "Untitled Paper" in markdown
    assert "Unknown" in markdown
    assert "No abstract available" in markdown


def test_format_abstract_multiple_authors(extraction_service):
    """Test _format_abstract formats multiple authors correctly"""
    paper = PaperMetadata(
        paper_id="test",
        title="Test",
        url="https://example.com",
        authors=[
            Author(name="John Doe"),
            Author(name="Jane Smith"),
            Author(name="Bob Johnson")
        ],
        citation_count=0
    )

    markdown = extraction_service._format_abstract(paper)

    assert "John Doe, Jane Smith, Bob Johnson" in markdown


def test_get_extraction_summary_complete(extraction_service):
    """Test get_extraction_summary with complete results"""
    results = [
        ExtractedPaper(
            metadata=PaperMetadata(
                paper_id="1",
                title="Paper 1",
                url="https://example.com/1",
                authors=[],
                citation_count=0
            ),
            pdf_available=True,
            extraction=PaperExtraction(
                paper_id="1",
                extraction_results=[],
                tokens_used=50000,
                cost_usd=0.20,
                extraction_timestamp=datetime.utcnow()
            )
        ),
        ExtractedPaper(
            metadata=PaperMetadata(
                paper_id="2",
                title="Paper 2",
                url="https://example.com/2",
                authors=[],
                citation_count=0
            ),
            pdf_available=False,
            extraction=PaperExtraction(
                paper_id="2",
                extraction_results=[],
                tokens_used=30000,
                cost_usd=0.12,
                extraction_timestamp=datetime.utcnow()
            )
        ),
        ExtractedPaper(
            metadata=PaperMetadata(
                paper_id="3",
                title="Paper 3",
                url="https://example.com/3",
                authors=[],
                citation_count=0
            ),
            pdf_available=True,
            extraction=None  # Extraction failed
        )
    ]

    summary = extraction_service.get_extraction_summary(results)

    assert summary["total_papers"] == 3
    assert summary["papers_with_pdf"] == 2
    assert summary["papers_with_extraction"] == 2
    assert summary["pdf_success_rate"] == 66.7
    assert summary["extraction_success_rate"] == 66.7
    assert summary["total_tokens_used"] == 80000
    assert summary["total_cost_usd"] == 0.32
    assert summary["avg_tokens_per_paper"] == 40000  # 80000 / 2
    assert summary["avg_cost_per_paper"] == 0.160  # 0.32 / 2


def test_get_extraction_summary_empty_results(extraction_service):
    """Test get_extraction_summary with empty results"""
    summary = extraction_service.get_extraction_summary([])

    assert summary["total_papers"] == 0
    assert summary["pdf_success_rate"] == 0.0
    assert summary["extraction_success_rate"] == 0.0
    assert summary["total_tokens_used"] == 0
    assert summary["total_cost_usd"] == 0.0
    assert summary["avg_tokens_per_paper"] == 0
    assert summary["avg_cost_per_paper"] == 0.0


def test_get_extraction_summary_no_successful_extractions(extraction_service):
    """Test get_extraction_summary when all extractions failed"""
    results = [
        ExtractedPaper(
            metadata=PaperMetadata(
                paper_id="1",
                title="Paper 1",
                url="https://example.com/1",
                authors=[],
                citation_count=0
            ),
            pdf_available=False,
            extraction=None
        )
    ]

    summary = extraction_service.get_extraction_summary(results)

    assert summary["total_papers"] == 1
    assert summary["papers_with_extraction"] == 0
    assert summary["avg_tokens_per_paper"] == 0
    assert summary["avg_cost_per_paper"] == 0.0

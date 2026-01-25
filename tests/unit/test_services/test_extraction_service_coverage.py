"""Coverage tests for ExtractionService to achieve ≥95% coverage

This file contains additional tests targeting specific uncovered lines
in extraction_service.py, particularly error handling paths and edge cases.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock

from src.services.extraction_service import ExtractionService
from src.services.pdf_service import PDFService
from src.services.llm_service import LLMService
from src.models.paper import PaperMetadata, Author
from src.models.extraction import PaperExtraction, ExtractedPaper
from src.utils.exceptions import (
    ConversionError,
    ExtractionError,
    FileSizeError,
    PDFValidationError,
)


@pytest.fixture
def mock_paper():
    return PaperMetadata(
        paper_id="test-123",
        title="Test Paper",
        abstract="This is a test abstract with content.",
        authors=[Author(name="Test Author")],
        url="https://arxiv.org/abs/test",
        open_access_pdf="https://arxiv.org/pdf/test.pdf",
        year=2023,
        venue="Test Conference",
    )


@pytest.fixture
def mock_paper_no_pdf():
    """Paper without open access PDF"""
    return PaperMetadata(
        paper_id="test-no-pdf",
        title="Test Paper No PDF",
        abstract="Abstract for paper without PDF.",
        authors=[Author(name="Test Author")],
        url="https://arxiv.org/abs/test-no-pdf",
        open_access_pdf=None,  # No PDF available
        year=2023,
    )


class TestExtractionServiceCoverage:
    """Coverage tests for ExtractionService"""

    @pytest.mark.asyncio
    async def test_process_paper_conversion_error_fallback(self, mock_paper):
        """Test fallback when PDF conversion fails (ConversionError)"""
        pdf_service = Mock(spec=PDFService)
        llm_service = Mock(spec=LLMService)
        service = ExtractionService(pdf_service, llm_service)

        # Setup: download succeeds, conversion fails
        mock_pdf_path = MagicMock(spec=Path)
        mock_pdf_path.__str__ = Mock(return_value="/tmp/test.pdf")
        pdf_service.download_pdf = AsyncMock(return_value=mock_pdf_path)
        pdf_service.convert_to_markdown = Mock(side_effect=ConversionError("Failed"))

        extraction = PaperExtraction(
            paper_id=mock_paper.paper_id,
            extraction_results=[],
            tokens_used=100,
            cost_usd=0.001,
        )
        llm_service.extract = AsyncMock(return_value=extraction)

        result = await service.process_paper(mock_paper, [])

        assert result.pdf_available is False  # PDF failed, reset to False
        assert result.pdf_path is None
        assert result.markdown_path is None
        # Should have used abstract fallback
        args, kwargs = llm_service.extract.call_args
        assert "Abstract" in kwargs["markdown_content"]

    @pytest.mark.asyncio
    async def test_process_paper_file_size_error_fallback(self, mock_paper):
        """Test fallback when PDF is too large (FileSizeError)"""
        pdf_service = Mock(spec=PDFService)
        llm_service = Mock(spec=LLMService)
        service = ExtractionService(pdf_service, llm_service)

        pdf_service.download_pdf = AsyncMock(side_effect=FileSizeError("Too large"))

        extraction = PaperExtraction(
            paper_id=mock_paper.paper_id,
            extraction_results=[],
            tokens_used=100,
            cost_usd=0.001,
        )
        llm_service.extract = AsyncMock(return_value=extraction)

        result = await service.process_paper(mock_paper, [])

        assert result.pdf_available is False
        assert "Abstract" in llm_service.extract.call_args.kwargs["markdown_content"]

    @pytest.mark.asyncio
    async def test_process_paper_validation_error_fallback(self, mock_paper):
        """Test fallback when PDF fails validation (PDFValidationError)"""
        pdf_service = Mock(spec=PDFService)
        llm_service = Mock(spec=LLMService)
        service = ExtractionService(pdf_service, llm_service)

        pdf_service.download_pdf = AsyncMock(
            side_effect=PDFValidationError("Invalid PDF")
        )

        extraction = PaperExtraction(
            paper_id=mock_paper.paper_id,
            extraction_results=[],
            tokens_used=100,
            cost_usd=0.001,
        )
        llm_service.extract = AsyncMock(return_value=extraction)

        result = await service.process_paper(mock_paper, [])

        assert result.pdf_available is False
        assert "Abstract" in llm_service.extract.call_args.kwargs["markdown_content"]

    @pytest.mark.asyncio
    async def test_process_paper_unexpected_pdf_error(self, mock_paper):
        """Test handling of unexpected errors during PDF processing"""
        pdf_service = Mock(spec=PDFService)
        llm_service = Mock(spec=LLMService)
        service = ExtractionService(pdf_service, llm_service)

        # Simulate unexpected error (not one of the expected exception types)
        pdf_service.download_pdf = AsyncMock(
            side_effect=RuntimeError("Unexpected error")
        )

        extraction = PaperExtraction(
            paper_id=mock_paper.paper_id,
            extraction_results=[],
            tokens_used=100,
            cost_usd=0.001,
        )
        llm_service.extract = AsyncMock(return_value=extraction)

        result = await service.process_paper(mock_paper, [])

        # Should still fall back gracefully
        assert result.pdf_available is False
        assert result.pdf_path is None
        assert result.markdown_path is None
        assert "Abstract" in llm_service.extract.call_args.kwargs["markdown_content"]

    @pytest.mark.asyncio
    async def test_process_paper_extraction_error(self, mock_paper):
        """Test handling of LLM extraction errors"""
        pdf_service = Mock(spec=PDFService)
        llm_service = Mock(spec=LLMService)
        service = ExtractionService(pdf_service, llm_service)

        llm_service.extract = AsyncMock(side_effect=ExtractionError("LLM failed"))

        result = await service.process_paper(mock_paper, [])

        # Should complete but without extraction
        assert result.extraction is None
        # Should still try cleanup
        pdf_service.cleanup_temp_files.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_paper_unexpected_extraction_error(self, mock_paper):
        """Test handling of unexpected LLM extraction errors"""
        pdf_service = Mock(spec=PDFService)
        llm_service = Mock(spec=LLMService)
        service = ExtractionService(pdf_service, llm_service)

        llm_service.extract = AsyncMock(side_effect=ValueError("Unexpected LLM error"))

        result = await service.process_paper(mock_paper, [])

        # Should complete but without extraction
        assert result.extraction is None
        pdf_service.cleanup_temp_files.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_paper_cleanup_failure(self, mock_paper):
        """Test that cleanup failures don't crash the pipeline"""
        pdf_service = Mock(spec=PDFService)
        llm_service = Mock(spec=LLMService)
        service = ExtractionService(pdf_service, llm_service)

        # Make cleanup fail
        pdf_service.cleanup_temp_files = Mock(side_effect=OSError("Cleanup failed"))

        extraction = PaperExtraction(
            paper_id=mock_paper.paper_id,
            extraction_results=[],
            tokens_used=100,
            cost_usd=0.001,
        )
        llm_service.extract = AsyncMock(return_value=extraction)

        # Should not raise exception
        result = await service.process_paper(mock_paper, [])

        assert result.extraction == extraction  # Pipeline should complete

    @pytest.mark.asyncio
    async def test_process_paper_no_pdf_available(self, mock_paper_no_pdf):
        """Test processing when paper has no open access PDF"""
        pdf_service = Mock(spec=PDFService)
        llm_service = Mock(spec=LLMService)
        service = ExtractionService(pdf_service, llm_service)

        extraction = PaperExtraction(
            paper_id=mock_paper_no_pdf.paper_id,
            extraction_results=[],
            tokens_used=100,
            cost_usd=0.001,
        )
        llm_service.extract = AsyncMock(return_value=extraction)

        result = await service.process_paper(mock_paper_no_pdf, [])

        # Should use abstract directly, not attempt PDF download
        pdf_service.download_pdf.assert_not_called()
        assert result.pdf_available is False
        assert "Abstract" in llm_service.extract.call_args.kwargs["markdown_content"]

    @pytest.mark.asyncio
    async def test_process_papers_batch(self):
        """Test batch processing of multiple papers"""
        pdf_service = Mock(spec=PDFService)
        llm_service = Mock(spec=LLMService)
        service = ExtractionService(pdf_service, llm_service)

        papers = [
            PaperMetadata(
                paper_id=f"paper-{i}",
                title=f"Paper {i}",
                abstract=f"Abstract {i}",
                authors=[],
                url=f"https://test.com/{i}",
                open_access_pdf=None,
                year=2023,
            )
            for i in range(3)
        ]

        # Mock LLM to return different extractions for each paper
        extraction1 = PaperExtraction(
            paper_id="paper-0", extraction_results=[], tokens_used=100, cost_usd=0.001
        )
        extraction2 = PaperExtraction(
            paper_id="paper-1", extraction_results=[], tokens_used=200, cost_usd=0.002
        )
        extraction3 = PaperExtraction(
            paper_id="paper-2", extraction_results=[], tokens_used=300, cost_usd=0.003
        )

        llm_service.extract = AsyncMock(
            side_effect=[extraction1, extraction2, extraction3]
        )

        results = await service.process_papers(papers, [])

        assert len(results) == 3
        assert all(isinstance(r, ExtractedPaper) for r in results)
        assert llm_service.extract.call_count == 3

    @pytest.mark.asyncio
    async def test_process_papers_partial_failures(self):
        """Test batch processing with some papers failing"""
        pdf_service = Mock(spec=PDFService)
        llm_service = Mock(spec=LLMService)
        service = ExtractionService(pdf_service, llm_service)

        papers = [
            PaperMetadata(
                paper_id=f"paper-{i}",
                title=f"Paper {i}",
                abstract=f"Abstract {i}",
                authors=[],
                url=f"https://test.com/{i}",
                open_access_pdf=None,
                year=2023,
            )
            for i in range(3)
        ]

        # First succeeds, second fails, third succeeds
        extraction1 = PaperExtraction(
            paper_id="paper-0", extraction_results=[], tokens_used=100, cost_usd=0.001
        )
        extraction3 = PaperExtraction(
            paper_id="paper-2", extraction_results=[], tokens_used=300, cost_usd=0.003
        )

        llm_service.extract = AsyncMock(
            side_effect=[extraction1, ExtractionError("Failed"), extraction3]
        )

        results = await service.process_papers(papers, [])

        # All papers should be returned, even if extraction failed
        assert len(results) == 3
        assert results[0].extraction == extraction1
        assert results[1].extraction is None  # Failed
        assert results[2].extraction == extraction3

    def test_format_abstract_minimal_metadata(self):
        """Test _format_abstract with minimal paper metadata"""
        pdf_service = Mock(spec=PDFService)
        llm_service = Mock(spec=LLMService)
        service = ExtractionService(pdf_service, llm_service)

        # Paper with minimal metadata (title required, but others optional)
        paper = PaperMetadata(
            paper_id="minimal",
            title="Minimal Paper",  # Title is required
            abstract=None,  # No abstract
            authors=[],  # No authors
            url="https://test.com",
            open_access_pdf=None,
            year=None,  # No year
            venue=None,  # No venue
        )

        markdown = service._format_abstract(paper)

        # Should handle None/empty values gracefully
        assert "Minimal Paper" in markdown
        assert (
            "Unknown" in markdown
        )  # For authors (empty list → "Unknown"), year, venue
        assert "No abstract available" in markdown

    def test_get_extraction_summary_empty_results(self):
        """Test summary with empty results list"""
        pdf_service = Mock(spec=PDFService)
        llm_service = Mock(spec=LLMService)
        service = ExtractionService(pdf_service, llm_service)

        summary = service.get_extraction_summary([])

        assert summary["total_papers"] == 0
        assert summary["papers_with_pdf"] == 0
        assert summary["papers_with_extraction"] == 0
        assert summary["total_tokens_used"] == 0
        assert summary["total_cost_usd"] == 0
        assert summary["pdf_success_rate"] == 0.0
        assert summary["extraction_success_rate"] == 0.0

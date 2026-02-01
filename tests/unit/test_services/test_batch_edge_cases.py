"""Batch Processing Edge Case Tests

Additional tests for extraction service batch handling.
"""

import pytest
from unittest.mock import Mock, AsyncMock

from src.services.extraction_service import ExtractionService
from src.services.pdf_service import PDFService
from src.services.llm_service import LLMService
from src.models.paper import PaperMetadata, Author
from src.models.extraction import PaperExtraction, ExtractedPaper
from src.utils.exceptions import PDFDownloadError


@pytest.fixture
def mock_pdf_service():
    """Create mock PDF service"""
    return Mock(spec=PDFService)


@pytest.fixture
def mock_llm_service():
    """Create mock LLM service"""
    return Mock(spec=LLMService)


@pytest.fixture
def extraction_service(mock_pdf_service, mock_llm_service):
    """Create extraction service with mocked dependencies"""
    return ExtractionService(
        pdf_service=mock_pdf_service,
        llm_service=mock_llm_service,
        keep_pdfs=True,
    )


@pytest.fixture
def sample_papers():
    """Create list of sample paper metadata"""
    papers = []
    for i in range(3):
        papers.append(
            PaperMetadata(
                paper_id=f"paper_{i}",
                title=f"Test Paper {i}",
                abstract=f"Abstract for paper {i}",
                url=f"https://example.com/paper_{i}",
                authors=[Author(name=f"Author {i}")],
                year=2023,
                open_access_pdf=f"https://example.com/paper_{i}.pdf",
            )
        )
    return papers


class TestEmptyBatch:
    """Tests for empty batch handling"""

    @pytest.mark.asyncio
    async def test_empty_batch_returns_empty_list(self, extraction_service):
        """Test processing of empty paper list"""
        results = await extraction_service.process_papers(papers=[], targets=[])
        assert results == []


class TestPapersWithoutPDF:
    """Tests for papers without open access PDF"""

    @pytest.mark.asyncio
    async def test_paper_without_pdf_url_uses_abstract(
        self, extraction_service, mock_llm_service
    ):
        """Test processing paper without PDF URL"""
        paper = PaperMetadata(
            paper_id="no_pdf_paper",
            title="No PDF Paper",
            abstract="This paper has no PDF",
            url="https://example.com/no_pdf",
            authors=[Author(name="Test Author")],
            year=2023,
            open_access_pdf=None,
        )

        extraction = PaperExtraction(
            paper_id=paper.paper_id,
            extraction_results=[],
            tokens_used=500,
            cost_usd=0.005,
        )
        mock_llm_service.extract = AsyncMock(return_value=extraction)

        result = await extraction_service.process_paper(paper, [])

        assert result is not None
        assert result.pdf_available is False


class TestExtractionSummary:
    """Tests for extraction summary functionality"""

    def test_summary_with_mixed_results(self, extraction_service):
        """Test summary calculation with mixed results"""
        paper1 = PaperMetadata(
            paper_id="p1",
            title="Paper 1",
            abstract="Abstract 1",
            url="https://example.com/1",
            authors=[Author(name="Author")],
            year=2023,
        )
        paper2 = PaperMetadata(
            paper_id="p2",
            title="Paper 2",
            abstract="Abstract 2",
            url="https://example.com/2",
            authors=[Author(name="Author")],
            year=2023,
        )

        extraction = PaperExtraction(
            paper_id="p1",
            extraction_results=[],
            tokens_used=1000,
            cost_usd=0.01,
        )

        results = [
            ExtractedPaper(metadata=paper1, pdf_available=True, extraction=extraction),
            ExtractedPaper(metadata=paper2, pdf_available=False, extraction=extraction),
        ]

        summary = extraction_service.get_extraction_summary(results)

        assert summary["total_papers"] == 2
        assert summary["papers_with_pdf"] == 1
        assert summary["pdf_success_rate"] == 50.0


class TestPDFDownloadFailure:
    """Tests for PDF download failure fallback"""

    @pytest.mark.asyncio
    async def test_pdf_failure_falls_back_to_abstract(
        self, extraction_service, mock_pdf_service, mock_llm_service
    ):
        """Test fallback to abstract when PDF download fails"""
        paper = PaperMetadata(
            paper_id="fail_paper",
            title="Failing Paper",
            abstract="Test abstract content",
            url="https://example.com/fail",
            authors=[Author(name="Test Author")],
            year=2023,
            open_access_pdf="https://example.com/fail.pdf",
        )

        mock_pdf_service.download_pdf = AsyncMock(
            side_effect=PDFDownloadError("Network error")
        )

        extraction = PaperExtraction(
            paper_id=paper.paper_id,
            extraction_results=[],
            tokens_used=500,
            cost_usd=0.005,
        )
        mock_llm_service.extract = AsyncMock(return_value=extraction)

        result = await extraction_service.process_paper(paper, [])

        assert result is not None
        assert result.pdf_available is False
        assert result.extraction == extraction

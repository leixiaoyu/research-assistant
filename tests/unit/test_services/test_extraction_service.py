import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, mock_open

from src.services.extraction_service import ExtractionService
from src.services.pdf_service import PDFService
from src.services.llm_service import LLMService
from src.models.paper import PaperMetadata, Author
from src.models.extraction import PaperExtraction, ExtractedPaper
from src.utils.exceptions import PDFDownloadError


@pytest.fixture
def mock_pdf_service():
    return Mock(spec=PDFService)


@pytest.fixture
def mock_llm_service():
    return Mock(spec=LLMService)


@pytest.fixture
def extraction_service(mock_pdf_service, mock_llm_service):
    return ExtractionService(
        pdf_service=mock_pdf_service, llm_service=mock_llm_service, keep_pdfs=True
    )


@pytest.fixture
def mock_paper():
    return PaperMetadata(
        paper_id="2301.12345",
        title="Test Paper",
        abstract="Test abstract",
        authors=[Author(name="Author 1")],
        url="https://arxiv.org/abs/2301.12345",
        open_access_pdf="https://arxiv.org/pdf/2301.12345.pdf",
        year=2023,
    )


class TestExtractionService:
    @pytest.mark.asyncio
    async def test_process_paper_success(
        self, extraction_service, mock_pdf_service, mock_llm_service, mock_paper
    ):
        """Test successful end-to-end processing of a single paper"""
        pdf_path = Path("/tmp/test.pdf")
        md_path = Path("/tmp/test.md")

        mock_pdf_service.download_pdf = AsyncMock(return_value=pdf_path)
        mock_pdf_service.convert_to_markdown = Mock(return_value=md_path)

        with patch("builtins.open", mock_open(read_data="Markdown content")):
            extraction = PaperExtraction(
                paper_id=mock_paper.paper_id,
                extraction_results=[],
                tokens_used=1000,
                cost_usd=0.01,
            )
            mock_llm_service.extract = AsyncMock(return_value=extraction)

            result = await extraction_service.process_paper(mock_paper, [])

            assert result.pdf_available is True
            assert result.extraction == extraction
            mock_pdf_service.cleanup_temp_files.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_paper_pdf_failure_fallback(
        self, extraction_service, mock_pdf_service, mock_llm_service, mock_paper
    ):
        """Test fallback to abstract when PDF download fails"""
        mock_pdf_service.download_pdf = AsyncMock(
            side_effect=PDFDownloadError("Failed")
        )

        extraction = PaperExtraction(
            paper_id=mock_paper.paper_id,
            extraction_results=[],
            tokens_used=500,
            cost_usd=0.005,
        )
        mock_llm_service.extract = AsyncMock(return_value=extraction)

        result = await extraction_service.process_paper(mock_paper, [])

        assert result.pdf_available is False
        assert result.extraction == extraction
        # Should have called extract with abstract-based markdown
        args, kwargs = mock_llm_service.extract.call_args
        assert "Abstract" in args[0]

    def test_get_extraction_summary(self, extraction_service, mock_paper):
        """Test summary statistics calculation"""
        extraction = PaperExtraction(
            paper_id=mock_paper.paper_id,
            extraction_results=[],
            tokens_used=1000,
            cost_usd=0.01,
        )
        results = [
            ExtractedPaper(
                metadata=mock_paper, pdf_available=True, extraction=extraction
            ),
            ExtractedPaper(
                metadata=mock_paper, pdf_available=False, extraction=extraction
            ),
        ]

        summary = extraction_service.get_extraction_summary(results)
        assert summary["total_papers"] == 2
        assert summary["papers_with_pdf"] == 1
        assert summary["total_tokens_used"] == 2000
        assert summary["total_cost_usd"] == 0.02
        assert summary["pdf_success_rate"] == 50.0

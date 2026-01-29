import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock

from src.services.extraction_service import ExtractionService
from src.services.pdf_service import PDFService
from src.services.llm_service import LLMService
from src.models.paper import PaperMetadata, Author
from src.models.extraction import PaperExtraction, ExtractedPaper
from src.utils.exceptions import PDFDownloadError, ExtractionError


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
        # Create mock Path objects with necessary methods
        mock_pdf_path = MagicMock(spec=Path)
        mock_pdf_path.__str__ = Mock(return_value="/tmp/test.pdf")
        mock_pdf_path.stat.return_value.st_size = 1024  # Mock file size

        mock_md_path = MagicMock(spec=Path)
        mock_md_path.__str__ = Mock(return_value="/tmp/test.md")
        mock_md_path.read_text.return_value = "# Test Paper\n\nMarkdown content"

        mock_pdf_service.download_pdf = AsyncMock(return_value=mock_pdf_path)
        mock_pdf_service.convert_to_markdown = Mock(return_value=mock_md_path)

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
        assert "Abstract" in kwargs["markdown_content"]

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

    @pytest.mark.asyncio
    async def test_process_paper_no_pdf_url(self, extraction_service, mock_llm_service):
        """Test processing paper with no open_access_pdf URL (lines 176-177)"""
        # Create paper without PDF URL
        paper_no_pdf = PaperMetadata(
            paper_id="2301.99999",
            title="No PDF Paper",
            abstract="This paper has no open access PDF",
            authors=[Author(name="Author 1")],
            url="https://arxiv.org/abs/2301.99999",
            open_access_pdf=None,  # No PDF URL
            year=2023,
        )

        extraction = PaperExtraction(
            paper_id=paper_no_pdf.paper_id,
            extraction_results=[],
            tokens_used=500,
            cost_usd=0.005,
        )
        mock_llm_service.extract = AsyncMock(return_value=extraction)

        result = await extraction_service.process_paper(paper_no_pdf, [])

        # Should use abstract-only path (lines 176-177)
        assert result.pdf_available is False
        assert result.pdf_path is None
        assert result.markdown_path is None
        assert result.extraction == extraction

        # Verify LLM was called with abstract-based markdown
        args, kwargs = mock_llm_service.extract.call_args
        assert "Abstract" in kwargs["markdown_content"]
        assert "No PDF Paper" in kwargs["markdown_content"]

    @pytest.mark.asyncio
    async def test_process_paper_extraction_error(
        self, extraction_service, mock_pdf_service, mock_llm_service, mock_paper
    ):
        """Test graceful handling of LLM extraction errors (line 194)"""
        # Setup PDF service to succeed
        mock_pdf_path = MagicMock(spec=Path)
        mock_pdf_path.__str__ = Mock(return_value="/tmp/test.pdf")
        mock_pdf_path.stat.return_value.st_size = 1024

        mock_md_path = MagicMock(spec=Path)
        mock_md_path.__str__ = Mock(return_value="/tmp/test.md")
        mock_md_path.read_text.return_value = "# Test Paper\n\nMarkdown content"

        mock_pdf_service.download_pdf = AsyncMock(return_value=mock_pdf_path)
        mock_pdf_service.convert_to_markdown = Mock(return_value=mock_md_path)

        # LLM extraction raises ExtractionError
        mock_llm_service.extract = AsyncMock(
            side_effect=ExtractionError("LLM API failed")
        )

        # Should not raise - gracefully handle error (line 194)
        result = await extraction_service.process_paper(mock_paper, [])

        assert result.pdf_available is True
        assert result.extraction is None  # Extraction failed but paper still returned
        mock_pdf_service.cleanup_temp_files.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_papers_batch(
        self, extraction_service, mock_pdf_service, mock_llm_service
    ):
        """Test batch processing of multiple papers (lines 228-254)"""
        # Create test papers
        papers = [
            PaperMetadata(
                paper_id=f"2301.{i:05d}",
                title=f"Paper {i}",
                abstract=f"Abstract {i}",
                authors=[Author(name=f"Author {i}")],
                url=f"https://arxiv.org/abs/2301.{i:05d}",
                open_access_pdf=f"https://arxiv.org/pdf/2301.{i:05d}.pdf",
                year=2023,
            )
            for i in range(3)
        ]

        # Setup mocks for successful processing
        mock_pdf_path = MagicMock(spec=Path)
        mock_pdf_path.__str__ = Mock(return_value="/tmp/test.pdf")
        mock_pdf_path.stat.return_value.st_size = 1024

        mock_md_path = MagicMock(spec=Path)
        mock_md_path.__str__ = Mock(return_value="/tmp/test.md")
        mock_md_path.read_text.return_value = "# Test Paper\n\nMarkdown content"

        mock_pdf_service.download_pdf = AsyncMock(return_value=mock_pdf_path)
        mock_pdf_service.convert_to_markdown = Mock(return_value=mock_md_path)

        # Mock LLM extraction
        def create_extraction(paper_id):
            return PaperExtraction(
                paper_id=paper_id,
                extraction_results=[],
                tokens_used=1000,
                cost_usd=0.01,
            )

        mock_llm_service.extract = AsyncMock(
            side_effect=[create_extraction(p.paper_id) for p in papers]
        )

        # Test batch processing (lines 228-254)
        results = await extraction_service.process_papers(papers, [])

        # Verify results
        assert len(results) == 3
        assert all(r.pdf_available is True for r in results)
        assert all(r.extraction is not None for r in results)

        # Verify all papers were processed
        assert mock_llm_service.extract.call_count == 3
        assert mock_pdf_service.cleanup_temp_files.call_count == 3

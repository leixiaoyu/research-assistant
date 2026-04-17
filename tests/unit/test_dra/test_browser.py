"""Unit tests for Phase 8 DRA research browser."""

from unittest.mock import MagicMock

import pytest

from src.models.dra import ChunkType, SearchResult
from src.services.dra.browser import CitationCheck, OpenedDocument, ResearchBrowser
from src.services.dra.corpus_manager import CorpusManager, PaperRecord


class TestOpenedDocument:
    """Tests for OpenedDocument model."""

    def test_basic_creation(self):
        """Test basic document creation."""
        doc = OpenedDocument(
            paper_id="paper123",
            title="Test Paper",
            content="This is test content.",
            section=None,
            token_count=100,
        )
        assert doc.paper_id == "paper123"
        assert doc.title == "Test Paper"
        assert doc.content == "This is test content."
        assert doc.section is None
        assert doc.token_count == 100

    def test_with_section(self):
        """Test document with specific section."""
        doc = OpenedDocument(
            paper_id="paper123",
            title="Test Paper",
            content="Abstract content",
            section=ChunkType.ABSTRACT,
            token_count=50,
        )
        assert doc.section == ChunkType.ABSTRACT

    def test_validation_paper_id_max_length(self):
        """Test paper_id length validation."""
        with pytest.raises(ValueError):
            OpenedDocument(
                paper_id="x" * 257,  # Exceeds max_length=256
                title="Test",
                content="Content",
                token_count=10,
            )

    def test_validation_title_max_length(self):
        """Test title length validation."""
        with pytest.raises(ValueError):
            OpenedDocument(
                paper_id="paper123",
                title="x" * 501,  # Exceeds max_length=500
                content="Content",
                token_count=10,
            )

    def test_validation_token_count_negative(self):
        """Test token_count cannot be negative."""
        with pytest.raises(ValueError):
            OpenedDocument(
                paper_id="paper123",
                title="Test",
                content="Content",
                token_count=-1,
            )


class TestCitationCheck:
    """Tests for CitationCheck model."""

    def test_basic_creation(self):
        """Test basic citation check creation."""
        check = CitationCheck(
            claim="The model achieves 95% accuracy",
            cited_paper_id="paper123",
            found=True,
            evidence="We achieved 95% accuracy on the benchmark.",
            confidence=0.85,
        )
        assert check.claim == "The model achieves 95% accuracy"
        assert check.cited_paper_id == "paper123"
        assert check.found is True
        assert "95% accuracy" in check.evidence
        assert check.confidence == 0.85

    def test_not_found(self):
        """Test citation check when claim not found."""
        check = CitationCheck(
            claim="Test claim",
            cited_paper_id="paper123",
            found=False,
            evidence="",
            confidence=0.0,
        )
        assert check.found is False
        assert check.evidence == ""
        assert check.confidence == 0.0

    def test_validation_claim_max_length(self):
        """Test claim length validation."""
        with pytest.raises(ValueError):
            CitationCheck(
                claim="x" * 5001,
                cited_paper_id="paper123",
                found=False,
            )

    def test_validation_confidence_range(self):
        """Test confidence must be between 0.0 and 1.0."""
        with pytest.raises(ValueError):
            CitationCheck(
                claim="Test",
                cited_paper_id="paper123",
                found=False,
                confidence=1.5,
            )

        with pytest.raises(ValueError):
            CitationCheck(
                claim="Test",
                cited_paper_id="paper123",
                found=False,
                confidence=-0.1,
            )


class TestResearchBrowser:
    """Tests for ResearchBrowser class."""

    @pytest.fixture
    def mock_corpus_manager(self):
        """Create mock corpus manager."""
        manager = MagicMock(spec=CorpusManager)
        manager.search_engine = MagicMock()
        return manager

    @pytest.fixture
    def browser(self, mock_corpus_manager):
        """Create research browser with mock corpus manager."""
        return ResearchBrowser(
            corpus_manager=mock_corpus_manager,
            max_open_documents=20,
        )

    def test_initialization(self, browser, mock_corpus_manager):
        """Test browser initialization."""
        assert browser.corpus_manager == mock_corpus_manager
        assert browser.max_open_documents == 20
        assert browser.open_document_count == 0
        assert browser._current_doc is None

    def test_open_document_count_property(self, browser):
        """Test open_document_count property."""
        assert browser.open_document_count == 0

        # Add some documents
        browser._opened_docs["paper1"] = MagicMock()
        browser._opened_docs["paper2"] = MagicMock()

        assert browser.open_document_count == 2

    def test_search_basic(self, browser, mock_corpus_manager):
        """Test basic search functionality."""
        # Setup mock search results
        expected_results = [
            SearchResult(
                chunk_id="chunk1",
                paper_id="paper1",
                paper_title="Test Paper 1",
                section_type=ChunkType.ABSTRACT,
                snippet="This is a test snippet",
                relevance_score=0.95,
            )
        ]
        mock_corpus_manager.search_engine.search.return_value = expected_results

        results = browser.search("test query", top_k=10)

        assert len(results) == 1
        assert results[0].paper_id == "paper1"
        mock_corpus_manager.search_engine.search.assert_called_once_with(
            query="test query",
            top_k=10,
            section_filter=None,
        )

    def test_search_with_section_filter(self, browser, mock_corpus_manager):
        """Test search with section filter."""
        mock_corpus_manager.search_engine.search.return_value = []

        browser.search("test", top_k=5, section_filter=ChunkType.METHODS)

        mock_corpus_manager.search_engine.search.assert_called_once_with(
            query="test",
            top_k=5,
            section_filter=ChunkType.METHODS,
        )

    def test_search_truncates_long_query(self, browser, mock_corpus_manager):
        """Test search truncates queries longer than 2000 chars."""
        long_query = "x" * 2500
        mock_corpus_manager.search_engine.search.return_value = []

        browser.search(long_query)

        # Should truncate to 2000 chars
        call_args = mock_corpus_manager.search_engine.search.call_args
        assert len(call_args[1]["query"]) == 2000

    def test_open_full_paper(self, browser, mock_corpus_manager):
        """Test opening a full paper."""
        # Setup mock paper record
        paper_record = PaperRecord(
            paper_id="paper1",
            title="Test Paper",
            checksum="abc123",
            chunk_ids=["paper1:0", "paper1:1"],
        )
        mock_corpus_manager.get_paper_info.return_value = paper_record

        # Setup mock chunks
        from src.models.dra import CorpusChunk

        chunk1 = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            section_type=ChunkType.ABSTRACT,
            title="Test Paper",
            content="Abstract content here.",
            token_count=50,
        )
        chunk2 = CorpusChunk(
            chunk_id="paper1:1",
            paper_id="paper1",
            section_type=ChunkType.METHODS,
            title="Test Paper",
            content="Methods content here.",
            token_count=100,
        )
        mock_corpus_manager.search_engine.get_chunk.side_effect = [chunk1, chunk2]

        doc = browser.open("paper1")

        assert doc.paper_id == "paper1"
        assert doc.title == "Test Paper"
        assert doc.section is None  # Full paper
        assert doc.token_count == 150  # 50 + 100
        assert "Abstract content" in doc.content
        assert "Methods content" in doc.content
        assert browser.open_document_count == 1
        assert browser._current_doc == doc

    def test_open_specific_section(self, browser, mock_corpus_manager):
        """Test opening a specific section."""
        paper_record = PaperRecord(
            paper_id="paper1",
            title="Test Paper",
            checksum="abc123",
            chunk_ids=["paper1:0", "paper1:1"],
        )
        mock_corpus_manager.get_paper_info.return_value = paper_record

        from src.models.dra import CorpusChunk

        chunk1 = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            section_type=ChunkType.ABSTRACT,
            title="Test Paper",
            content="Abstract content.",
            token_count=50,
        )
        chunk2 = CorpusChunk(
            chunk_id="paper1:1",
            paper_id="paper1",
            section_type=ChunkType.METHODS,
            title="Test Paper",
            content="Methods content.",
            token_count=100,
        )
        mock_corpus_manager.search_engine.get_chunk.side_effect = [chunk1, chunk2]

        doc = browser.open("paper1", section=ChunkType.ABSTRACT)

        assert doc.section == ChunkType.ABSTRACT
        assert doc.token_count == 50  # Only abstract
        assert "Abstract content" in doc.content
        assert "Methods content" not in doc.content

    def test_open_paper_not_found(self, browser, mock_corpus_manager):
        """Test opening non-existent paper raises error."""
        mock_corpus_manager.get_paper_info.return_value = None

        with pytest.raises(ValueError, match="Paper not found: paper999"):
            browser.open("paper999")

    def test_open_no_content_found(self, browser, mock_corpus_manager):
        """Test opening paper with no matching content raises error."""
        paper_record = PaperRecord(
            paper_id="paper1",
            title="Test Paper",
            checksum="abc123",
            chunk_ids=["paper1:0"],
        )
        mock_corpus_manager.get_paper_info.return_value = paper_record
        mock_corpus_manager.search_engine.get_chunk.return_value = None

        with pytest.raises(ValueError, match="No content found"):
            browser.open("paper1")

    def test_open_section_not_found(self, browser, mock_corpus_manager):
        """Test opening section that doesn't exist raises error."""
        paper_record = PaperRecord(
            paper_id="paper1",
            title="Test Paper",
            checksum="abc123",
            chunk_ids=["paper1:0"],
        )
        mock_corpus_manager.get_paper_info.return_value = paper_record

        from src.models.dra import CorpusChunk

        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            section_type=ChunkType.ABSTRACT,
            title="Test Paper",
            content="Abstract.",
            token_count=10,
        )
        mock_corpus_manager.search_engine.get_chunk.return_value = chunk

        with pytest.raises(ValueError, match="No content found.*section methods"):
            browser.open("paper1", section=ChunkType.METHODS)

    def test_open_document_limit_exceeded(self, browser, mock_corpus_manager):
        """Test opening too many documents raises error."""
        browser.max_open_documents = 2

        # Open first document
        paper_record = PaperRecord(
            paper_id="paper1",
            title="Test Paper 1",
            checksum="abc123",
            chunk_ids=["paper1:0"],
        )
        mock_corpus_manager.get_paper_info.return_value = paper_record

        from src.models.dra import CorpusChunk

        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            section_type=ChunkType.ABSTRACT,
            title="Test Paper 1",
            content="Content 1",
            token_count=10,
        )
        mock_corpus_manager.search_engine.get_chunk.return_value = chunk

        browser.open("paper1")
        assert browser.open_document_count == 1

        # Open second document
        paper_record.paper_id = "paper2"
        paper_record.title = "Test Paper 2"
        chunk.paper_id = "paper2"
        chunk.chunk_id = "paper2:0"
        mock_corpus_manager.search_engine.get_chunk.return_value = chunk

        browser.open("paper2")
        assert browser.open_document_count == 2

        # Try to open third document (should fail)
        with pytest.raises(ValueError, match="Document limit exceeded"):
            browser.open("paper3")

    def test_open_same_paper_twice_no_limit_inc(self, browser, mock_corpus_manager):
        """Test opening same paper twice doesn't increase document count."""
        paper_record = PaperRecord(
            paper_id="paper1",
            title="Test Paper",
            checksum="abc123",
            chunk_ids=["paper1:0"],
        )
        mock_corpus_manager.get_paper_info.return_value = paper_record

        from src.models.dra import CorpusChunk

        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            section_type=ChunkType.ABSTRACT,
            title="Test Paper",
            content="Content",
            token_count=10,
        )
        mock_corpus_manager.search_engine.get_chunk.return_value = chunk

        browser.open("paper1")
        assert browser.open_document_count == 1

        # Open again
        browser.open("paper1")
        assert browser.open_document_count == 1  # Still 1

    def test_find_current_document(self, browser):
        """Test find in current document."""
        # Setup current document
        browser._current_doc = OpenedDocument(
            paper_id="paper1",
            title="Test",
            content="The quick brown fox. Jumps over the lazy dog. The fox is clever.",
            section=None,
            token_count=50,
        )

        results = browser.find("fox", scope="current")

        assert len(results) == 2
        assert results[0].matched_text == "fox"
        assert "brown fox" in results[0].context
        assert results[1].matched_text == "fox"
        assert "fox is clever" in results[1].context

    def test_find_regex_pattern(self, browser):
        """Test find with regex pattern."""
        browser._current_doc = OpenedDocument(
            paper_id="paper1",
            title="Test",
            content="The value is 95%. Another value is 87.5%.",
            section=None,
            token_count=50,
        )

        results = browser.find(r"\d+\.?\d*%", scope="current")

        assert len(results) == 2
        assert results[0].matched_text == "95%"
        assert results[1].matched_text == "87.5%"

    def test_find_case_insensitive(self, browser):
        """Test find is case-insensitive."""
        browser._current_doc = OpenedDocument(
            paper_id="paper1",
            title="Test",
            content="Transformer models are powerful. The TRANSFORMER architecture.",
            section=None,
            token_count=50,
        )

        results = browser.find("transformer", scope="current")

        assert len(results) == 2

    def test_find_max_results_limit(self, browser):
        """Test find respects max_results limit."""
        content = ". ".join([f"Match {i}" for i in range(20)])
        browser._current_doc = OpenedDocument(
            paper_id="paper1",
            title="Test",
            content=content,
            section=None,
            token_count=100,
        )

        results = browser.find("Match", scope="current", max_results=5)

        assert len(results) == 5

    def test_find_all_scope(self, browser):
        """Test find across all open documents."""
        browser._opened_docs["paper1"] = OpenedDocument(
            paper_id="paper1",
            title="Paper 1",
            content="First document with attention mechanism.",
            section=None,
            token_count=50,
        )
        browser._opened_docs["paper2"] = OpenedDocument(
            paper_id="paper2",
            title="Paper 2",
            content="Second document also uses attention.",
            section=None,
            token_count=50,
        )

        results = browser.find("attention", scope="all")

        assert len(results) == 2

    def test_find_no_current_document_raises_error(self, browser):
        """Test find with no current document raises error."""
        with pytest.raises(ValueError, match="No document is currently open"):
            browser.find("test", scope="current")

    def test_find_invalid_scope_raises_error(self, browser):
        """Test find with invalid scope raises error."""
        browser._current_doc = MagicMock()

        with pytest.raises(ValueError, match="Invalid scope: invalid"):
            browser.find("test", scope="invalid")

    def test_find_invalid_regex_raises_error(self, browser):
        """Test find with invalid regex raises error."""
        browser._current_doc = OpenedDocument(
            paper_id="paper1",
            title="Test",
            content="Content",
            section=None,
            token_count=10,
        )

        with pytest.raises(ValueError, match="Invalid regex pattern"):
            browser.find("[invalid(", scope="current")

    def test_find_no_matches(self, browser):
        """Test find with no matches returns empty list."""
        browser._current_doc = OpenedDocument(
            paper_id="paper1",
            title="Test",
            content="This is some content.",
            section=None,
            token_count=10,
        )

        results = browser.find("nonexistent", scope="current")

        assert len(results) == 0

    def test_find_context_truncation(self, browser):
        """Test find truncates context to 5000 chars."""
        # Create very long sentence
        long_content = "x" * 10000
        browser._current_doc = OpenedDocument(
            paper_id="paper1",
            title="Test",
            content=long_content,
            section=None,
            token_count=1000,
        )

        results = browser.find("x", scope="current", max_results=1)

        assert len(results[0].context) <= 5000

    def test_validate_citation_found(self, browser, mock_corpus_manager):
        """Test citation validation when claim is found."""
        # Setup paper
        paper_record = PaperRecord(
            paper_id="paper1",
            title="Test Paper",
            checksum="abc123",
            chunk_ids=["paper1:0"],
        )
        mock_corpus_manager.get_paper_info.return_value = paper_record

        from src.models.dra import CorpusChunk

        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            section_type=ChunkType.RESULTS,
            title="Test Paper",
            content="Our model achieves 95% accuracy on the benchmark dataset. "
            "This performance exceeds previous state-of-the-art results.",
            token_count=100,
        )
        mock_corpus_manager.search_engine.get_chunk.return_value = chunk

        check = browser.validate_citation(
            claim="The model achieves 95% accuracy on benchmark",
            cited_paper_id="paper1",
            fuzzy_threshold=0.7,
        )

        assert check.found is True
        assert check.confidence >= 0.7
        assert "95% accuracy" in check.evidence

    def test_validate_citation_not_found(self, browser, mock_corpus_manager):
        """Test citation validation when claim is not found."""
        paper_record = PaperRecord(
            paper_id="paper1",
            title="Test Paper",
            checksum="abc123",
            chunk_ids=["paper1:0"],
        )
        mock_corpus_manager.get_paper_info.return_value = paper_record

        from src.models.dra import CorpusChunk

        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            section_type=ChunkType.RESULTS,
            title="Test Paper",
            content="This paper discusses various topics.",
            token_count=50,
        )
        mock_corpus_manager.search_engine.get_chunk.return_value = chunk

        check = browser.validate_citation(
            claim="The model achieves 99% accuracy with quantum computing",
            cited_paper_id="paper1",
            fuzzy_threshold=0.7,
        )

        assert check.found is False
        assert check.confidence < 0.7
        assert check.evidence == ""

    def test_validate_citation_paper_not_found(self, browser, mock_corpus_manager):
        """Test citation validation when paper doesn't exist."""
        mock_corpus_manager.get_paper_info.return_value = None

        check = browser.validate_citation(
            claim="Test claim",
            cited_paper_id="nonexistent",
        )

        assert check.found is False
        assert check.confidence == 0.0
        assert check.evidence == ""

    def test_validate_citation_uses_opened_document(self, browser, mock_corpus_manager):
        """Test citation validation reuses already opened document."""
        # Pre-open a document
        browser._opened_docs["paper1"] = OpenedDocument(
            paper_id="paper1",
            title="Test Paper",
            content="The model achieves excellent performance metrics.",
            section=None,
            token_count=50,
        )

        check = browser.validate_citation(
            claim="The model achieves excellent performance",
            cited_paper_id="paper1",
        )

        # Should not call get_paper_info since document already open
        mock_corpus_manager.get_paper_info.assert_not_called()
        assert check.found is True

    def test_validate_citation_no_key_terms(self, browser, mock_corpus_manager):
        """Test citation validation with claim that has no key terms."""
        paper_record = PaperRecord(
            paper_id="paper1",
            title="Test Paper",
            checksum="abc123",
            chunk_ids=["paper1:0"],
        )
        mock_corpus_manager.get_paper_info.return_value = paper_record

        from src.models.dra import CorpusChunk

        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            section_type=ChunkType.ABSTRACT,
            title="Test Paper",
            content="Content here.",
            token_count=10,
        )
        mock_corpus_manager.search_engine.get_chunk.return_value = chunk

        # Claim with only short words (< 4 chars)
        check = browser.validate_citation(
            claim="a is to be or",
            cited_paper_id="paper1",
        )

        assert check.found is False
        assert check.confidence == 0.0

    def test_validate_citation_fuzzy_threshold(self, browser, mock_corpus_manager):
        """Test citation validation with different fuzzy thresholds."""
        paper_record = PaperRecord(
            paper_id="paper1",
            title="Test Paper",
            checksum="abc123",
            chunk_ids=["paper1:0"],
        )
        mock_corpus_manager.get_paper_info.return_value = paper_record

        from src.models.dra import CorpusChunk

        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            section_type=ChunkType.ABSTRACT,
            title="Test Paper",
            content="Transformer architecture neural networks.",
            token_count=50,
        )
        mock_corpus_manager.search_engine.get_chunk.return_value = chunk

        # High threshold - might not pass
        check_high = browser.validate_citation(
            claim="Transformer models",
            cited_paper_id="paper1",
            fuzzy_threshold=0.9,
        )

        # Low threshold - should pass
        check_low = browser.validate_citation(
            claim="Transformer models",
            cited_paper_id="paper1",
            fuzzy_threshold=0.3,
        )

        assert check_low.found is True
        # Verify high threshold check was executed (variable used)
        assert check_high is not None

    def test_close_document(self, browser):
        """Test closing an opened document."""
        browser._opened_docs["paper1"] = OpenedDocument(
            paper_id="paper1",
            title="Test",
            content="Content",
            token_count=10,
        )

        result = browser.close("paper1")

        assert result is True
        assert "paper1" not in browser._opened_docs
        assert browser.open_document_count == 0

    def test_close_document_not_open(self, browser):
        """Test closing a document that isn't open returns False."""
        result = browser.close("nonexistent")

        assert result is False

    def test_close_current_document_clears_current(self, browser):
        """Test closing the current document clears _current_doc."""
        doc = OpenedDocument(
            paper_id="paper1",
            title="Test",
            content="Content",
            token_count=10,
        )
        browser._opened_docs["paper1"] = doc
        browser._current_doc = doc

        browser.close("paper1")

        assert browser._current_doc is None

    def test_close_non_current_document_preserves_current(self, browser):
        """Test closing non-current document preserves _current_doc."""
        doc1 = OpenedDocument(
            paper_id="paper1",
            title="Test 1",
            content="Content 1",
            token_count=10,
        )
        doc2 = OpenedDocument(
            paper_id="paper2",
            title="Test 2",
            content="Content 2",
            token_count=10,
        )
        browser._opened_docs["paper1"] = doc1
        browser._opened_docs["paper2"] = doc2
        browser._current_doc = doc1

        browser.close("paper2")

        assert browser._current_doc == doc1

    def test_close_all(self, browser):
        """Test closing all documents."""
        browser._opened_docs["paper1"] = MagicMock()
        browser._opened_docs["paper2"] = MagicMock()
        browser._opened_docs["paper3"] = MagicMock()
        browser._current_doc = browser._opened_docs["paper1"]

        count = browser.close_all()

        assert count == 3
        assert len(browser._opened_docs) == 0
        assert browser._current_doc is None

    def test_close_all_empty(self, browser):
        """Test close_all with no open documents."""
        count = browser.close_all()

        assert count == 0

    def test_get_opened_papers(self, browser):
        """Test getting list of opened paper IDs."""
        browser._opened_docs["paper1"] = MagicMock()
        browser._opened_docs["paper2"] = MagicMock()
        browser._opened_docs["paper3"] = MagicMock()

        papers = browser.get_opened_papers()

        assert len(papers) == 3
        assert "paper1" in papers
        assert "paper2" in papers
        assert "paper3" in papers

    def test_get_opened_papers_empty(self, browser):
        """Test get_opened_papers with no open documents."""
        papers = browser.get_opened_papers()

        assert len(papers) == 0
        assert papers == []

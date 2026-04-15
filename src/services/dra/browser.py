"""Research browser primitives for DRA agent.

This module provides:
- search() primitive for corpus queries
- open() primitive for document retrieval
- find() primitive for in-document search
- Citation validation for synthesis phase
"""

import re
import structlog
from typing import Optional

from pydantic import BaseModel, Field

from src.models.dra import (
    ChunkType,
    FindResult,
    SearchResult,
)
from src.services.dra.corpus_manager import CorpusManager

logger = structlog.get_logger()


class OpenedDocument(BaseModel):
    """An opened document in the browser session.

    Attributes:
        paper_id: Registry paper ID
        title: Paper title
        content: Full or section-scoped content
        section: Section type if scoped, None if full paper
        token_count: Content token count
    """

    paper_id: str = Field(..., max_length=256, description="Paper ID")
    title: str = Field(..., max_length=500, description="Paper title")
    content: str = Field(..., description="Document content")
    section: Optional[ChunkType] = Field(default=None, description="Section scope")
    token_count: int = Field(..., ge=0, description="Token count")


class CitationCheck(BaseModel):
    """Result of citation validation.

    Attributes:
        claim: The claim being validated
        cited_paper_id: Paper cited as source
        found: Whether claim was found in cited paper
        evidence: Text snippet if found, empty if not
        confidence: Confidence score (0.0-1.0)
    """

    claim: str = Field(..., max_length=5000, description="Claim to validate")
    cited_paper_id: str = Field(..., max_length=256, description="Cited paper")
    found: bool = Field(..., description="Whether claim was found")
    evidence: str = Field(default="", max_length=5000, description="Evidence snippet")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence score")


class ResearchBrowser:
    """Browser primitives for DRA agent.

    Provides search, open, find operations over the offline corpus.
    Tracks all operations in trajectory for learning.
    """

    def __init__(
        self,
        corpus_manager: CorpusManager,
        max_open_documents: int = 20,
    ):
        """Initialize research browser.

        Args:
            corpus_manager: Corpus manager instance
            max_open_documents: Maximum simultaneously open documents
        """
        self.corpus_manager = corpus_manager
        self.search_engine = corpus_manager.search_engine
        self.max_open_documents = max_open_documents

        # Track opened documents
        self._opened_docs: dict[str, OpenedDocument] = {}

        # Current document for find() operations
        self._current_doc: Optional[OpenedDocument] = None

    @property
    def open_document_count(self) -> int:
        """Get number of currently open documents."""
        return len(self._opened_docs)

    def search(
        self,
        query: str,
        top_k: int = 10,
        section_filter: Optional[ChunkType] = None,
    ) -> list[SearchResult]:
        """Search the corpus using hybrid retrieval.

        SR-8.4: Data-driven prompt injection protection.
        Results are safe for LLM consumption as snippets are truncated.

        Args:
            query: Search query
            top_k: Number of results to return
            section_filter: Optional section type filter

        Returns:
            List of search results sorted by relevance
        """
        # Validate query length (prevent abuse)
        if len(query) > 2000:
            logger.warning("search_query_too_long", length=len(query))
            query = query[:2000]

        logger.info("browser_search", query=query[:100], top_k=top_k)

        return self.search_engine.search(
            query=query,
            top_k=top_k,
            section_filter=section_filter,
        )

    def open(
        self,
        paper_id: str,
        section: Optional[ChunkType] = None,
    ) -> OpenedDocument:
        """Open a document (full paper or specific section).

        SR-8.4: Content is wrapped with XML tags for prompt injection protection
        when passed to LLM (done by agent loop, not here).

        Args:
            paper_id: Registry paper ID
            section: Optional section to open (None = full paper)

        Returns:
            Opened document with content

        Raises:
            ValueError: If paper not found or document limit exceeded
        """
        # Check document limit
        if paper_id not in self._opened_docs:
            if self.open_document_count >= self.max_open_documents:
                raise ValueError(
                    f"Document limit exceeded ({self.max_open_documents}). "
                    "Close documents before opening more."
                )

        logger.info("browser_open", paper_id=paper_id, section=section)

        # Get paper record
        paper_record = self.corpus_manager.get_paper_info(paper_id)
        if not paper_record:
            raise ValueError(f"Paper not found: {paper_id}")

        # Collect content from chunks
        content_parts: list[str] = []
        total_tokens = 0

        for chunk_id in paper_record.chunk_ids:
            chunk = self.search_engine.get_chunk(chunk_id)
            if not chunk:
                continue

            # Filter by section if specified
            if section and chunk.section_type != section:
                continue

            content_parts.append(
                f"## {chunk.section_type.value.title()}\n\n{chunk.content}"
            )
            total_tokens += chunk.token_count

        if not content_parts:
            raise ValueError(
                f"No content found for paper {paper_id}"
                + (f" section {section.value}" if section else "")
            )

        # Create opened document
        doc = OpenedDocument(
            paper_id=paper_id,
            title=paper_record.title,
            content="\n\n".join(content_parts),
            section=section,
            token_count=total_tokens,
        )

        # Track opened document
        self._opened_docs[paper_id] = doc
        self._current_doc = doc

        logger.info(
            "document_opened",
            paper_id=paper_id,
            section=section.value if section else "full",
            tokens=total_tokens,
        )

        return doc

    def find(
        self,
        pattern: str,
        scope: str = "current",
        max_results: int = 10,
    ) -> list[FindResult]:
        """Find pattern within opened document(s).

        Args:
            pattern: Search pattern (supports regex)
            scope: Search scope ("current" or "all")
            max_results: Maximum results to return

        Returns:
            List of find results with context

        Raises:
            ValueError: If no document is open or pattern invalid
        """
        if scope == "current":
            if not self._current_doc:
                raise ValueError("No document is currently open")
            docs_to_search = [self._current_doc]
        elif scope == "all":
            docs_to_search = list(self._opened_docs.values())
        else:
            raise ValueError(f"Invalid scope: {scope}")

        logger.info("browser_find", pattern=pattern[:100], scope=scope)

        results: list[FindResult] = []

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}") from e

        for doc in docs_to_search:
            # Split into sentences for context extraction
            sentences = re.split(r"(?<=[.!?])\s+", doc.content)

            for i, sentence in enumerate(sentences):
                matches = list(regex.finditer(sentence))
                if not matches:
                    continue

                # Extract context (current + 2 surrounding sentences)
                context_start = max(0, i - 1)
                context_end = min(len(sentences), i + 2)
                context = " ".join(sentences[context_start:context_end])

                for match in matches:
                    results.append(
                        FindResult(
                            matched_text=match.group(0),
                            context=context[:5000],  # Limit context size
                            position=match.start(),
                            section=doc.section,
                        )
                    )

                    if len(results) >= max_results:
                        break

                if len(results) >= max_results:
                    break

            if len(results) >= max_results:
                break

        logger.info("find_results", pattern=pattern[:50], count=len(results))

        return results

    def validate_citation(
        self,
        claim: str,
        cited_paper_id: str,
        fuzzy_threshold: float = 0.7,
    ) -> CitationCheck:
        """Validate that a claim exists in the cited paper.

        SR-8.6: Citation validation to prevent hallucination.
        Uses fuzzy matching to allow for paraphrasing.

        Args:
            claim: The claim to validate (should be short, factual)
            cited_paper_id: Paper ID that should contain this claim
            fuzzy_threshold: Minimum similarity threshold (0.0-1.0)

        Returns:
            CitationCheck with validation result
        """
        logger.info(
            "validating_citation",
            claim=claim[:100],
            paper_id=cited_paper_id,
        )

        # Try to open the paper if not already open
        try:
            if cited_paper_id not in self._opened_docs:
                doc = self.open(cited_paper_id)
            else:
                doc = self._opened_docs[cited_paper_id]
        except ValueError as e:
            logger.warning(
                "citation_check_paper_not_found", paper_id=cited_paper_id, error=str(e)
            )
            return CitationCheck(
                claim=claim,
                cited_paper_id=cited_paper_id,
                found=False,
                evidence="",
                confidence=0.0,
            )

        # Search for the claim in the paper content
        # Simple approach: check if claim keywords appear in paper
        claim_lower = claim.lower()
        content_lower = doc.content.lower()

        # Extract key terms from claim (remove stopwords, punctuation)
        key_terms = re.findall(r"\b\w{4,}\b", claim_lower)  # Words 4+ chars
        if not key_terms:
            return CitationCheck(
                claim=claim,
                cited_paper_id=cited_paper_id,
                found=False,
                evidence="",
                confidence=0.0,
            )

        # Check how many key terms appear in the paper
        terms_found = sum(1 for term in key_terms if term in content_lower)
        match_ratio = terms_found / len(key_terms)

        # Find best matching sentence as evidence
        best_sentence = ""
        best_score = 0.0

        sentences = re.split(r"(?<=[.!?])\s+", doc.content)
        for sentence in sentences:
            sentence_lower = sentence.lower()
            sentence_terms_found = sum(
                1 for term in key_terms if term in sentence_lower
            )
            sentence_score = sentence_terms_found / len(key_terms)

            if sentence_score > best_score:
                best_score = sentence_score
                best_sentence = sentence

        # Determine if citation is valid
        found = match_ratio >= fuzzy_threshold
        confidence = round(match_ratio, 4)

        logger.info(
            "citation_validated",
            paper_id=cited_paper_id,
            found=found,
            confidence=confidence,
        )

        return CitationCheck(
            claim=claim,
            cited_paper_id=cited_paper_id,
            found=found,
            evidence=best_sentence[:5000] if found else "",
            confidence=confidence,
        )

    def close(self, paper_id: str) -> bool:
        """Close an opened document.

        Args:
            paper_id: Paper ID to close

        Returns:
            True if document was open and closed, False otherwise
        """
        if paper_id not in self._opened_docs:
            return False

        del self._opened_docs[paper_id]

        # Clear current doc if it was the one closed
        if self._current_doc and self._current_doc.paper_id == paper_id:
            self._current_doc = None

        logger.debug("document_closed", paper_id=paper_id)

        return True

    def close_all(self) -> int:
        """Close all opened documents.

        Returns:
            Number of documents closed
        """
        count = len(self._opened_docs)
        self._opened_docs.clear()
        self._current_doc = None

        logger.debug("all_documents_closed", count=count)

        return count

    def get_opened_papers(self) -> list[str]:
        """Get list of currently opened paper IDs.

        Returns:
            List of paper IDs
        """
        return list(self._opened_docs.keys())

"""DRA utility functions for chunking, tokenization, and normalization.

This module provides:
- Section parsing from markdown
- Chunk building with overlap
- Token counting
- Text normalization for BM25
"""

import hashlib
import re
from typing import Optional

import structlog

from src.models.dra import ChunkType, CorpusChunk

logger = structlog.get_logger()

# Section header patterns for markdown parsing
SECTION_PATTERNS = {
    ChunkType.ABSTRACT: re.compile(
        r"^#+\s*(abstract|summary)\s*$", re.IGNORECASE | re.MULTILINE
    ),
    ChunkType.INTRODUCTION: re.compile(
        r"^#+\s*(introduction|background|overview)\s*$", re.IGNORECASE | re.MULTILINE
    ),
    ChunkType.METHODS: re.compile(
        r"^#+\s*(methods?|methodology|approach|experimental setup)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    ChunkType.RESULTS: re.compile(
        r"^#+\s*(results?|findings|experiments?)\s*$", re.IGNORECASE | re.MULTILINE
    ),
    ChunkType.DISCUSSION: re.compile(
        r"^#+\s*(discussion|analysis)\s*$", re.IGNORECASE | re.MULTILINE
    ),
    ChunkType.CONCLUSION: re.compile(
        r"^#+\s*(conclusions?|summary|future work)\s*$", re.IGNORECASE | re.MULTILINE
    ),
    ChunkType.REFERENCES: re.compile(
        r"^#+\s*(references?|bibliography|citations?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
}

# English stopwords for BM25 normalization
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "he",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "that",
        "the",
        "to",
        "was",
        "were",
        "will",
        "with",
    ]
)


class TokenCounter:
    """Count tokens using a simple whitespace-based approach.

    For production, consider using tiktoken or transformers tokenizer.
    This implementation provides a fast approximation.
    """

    def __init__(self, chars_per_token: float = 4.0):
        """Initialize token counter.

        Args:
            chars_per_token: Average characters per token (default 4.0)
        """
        self.chars_per_token = chars_per_token

    def count(self, text: str) -> int:
        """Count tokens in text.

        Args:
            text: Input text

        Returns:
            Estimated token count
        """
        if not text:
            return 0
        # Simple approximation: chars / 4 or word count, whichever is larger
        char_estimate = len(text) / self.chars_per_token
        word_count = len(text.split())
        return max(int(char_estimate), word_count)


class TextNormalizer:
    """Normalize text for BM25 indexing."""

    def __init__(self, remove_stopwords: bool = True, lowercase: bool = True):
        """Initialize normalizer.

        Args:
            remove_stopwords: Whether to remove stopwords
            lowercase: Whether to lowercase text
        """
        self.remove_stopwords = remove_stopwords
        self.lowercase = lowercase

    def normalize(self, text: str) -> str:
        """Normalize text for BM25.

        Args:
            text: Input text

        Returns:
            Normalized text
        """
        if not text:
            return ""

        # Lowercase
        if self.lowercase:
            text = text.lower()

        # Remove punctuation and extra whitespace
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        # Remove stopwords
        if self.remove_stopwords:
            words = text.split()
            words = [w for w in words if w not in STOPWORDS]
            text = " ".join(words)

        return text

    def tokenize(self, text: str) -> list[str]:
        """Tokenize normalized text.

        Args:
            text: Input text

        Returns:
            List of tokens
        """
        normalized = self.normalize(text)
        return normalized.split() if normalized else []


class SectionParser:
    """Parse markdown into sections."""

    def __init__(self):
        """Initialize section parser."""
        self._header_pattern = re.compile(r"^(#+)\s+(.+)$", re.MULTILINE)

    def parse(self, markdown: str) -> list[tuple[ChunkType, str, str]]:
        """Parse markdown into sections.

        Args:
            markdown: Markdown content

        Returns:
            List of (section_type, header_text, content) tuples
        """
        if not markdown:
            return []

        sections: list[tuple[ChunkType, str, str]] = []
        lines = markdown.split("\n")

        current_type = ChunkType.OTHER
        current_header = ""
        current_content: list[str] = []

        for line in lines:
            header_match = self._header_pattern.match(line)

            if header_match:
                # Save previous section if it has content
                if current_content:
                    content = "\n".join(current_content).strip()
                    if content:
                        sections.append((current_type, current_header, content))

                # Determine section type from header
                header_text = header_match.group(2).strip()
                current_header = header_text
                current_type = self._classify_header(header_text)
                current_content = []
            else:
                current_content.append(line)

        # Don't forget the last section
        if current_content:
            content = "\n".join(current_content).strip()
            if content:
                sections.append((current_type, current_header, content))

        return sections

    def _classify_header(self, header: str) -> ChunkType:
        """Classify a header into a section type.

        Args:
            header: Header text

        Returns:
            ChunkType for the section
        """
        for section_type, pattern in SECTION_PATTERNS.items():
            # Check if pattern matches the header text
            test_string = f"# {header}"
            if pattern.search(test_string):
                return section_type

        return ChunkType.OTHER


class ChunkBuilder:
    """Build chunks from sections with overlap."""

    def __init__(
        self,
        max_tokens: int = 512,
        overlap_tokens: int = 64,
        token_counter: Optional[TokenCounter] = None,
    ):
        """Initialize chunk builder.

        Args:
            max_tokens: Maximum tokens per chunk
            overlap_tokens: Overlap between consecutive chunks
            token_counter: Token counter instance
        """
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.token_counter = token_counter or TokenCounter()

    def build_chunks(
        self,
        paper_id: str,
        title: str,
        sections: list[tuple[ChunkType, str, str]],
        metadata: Optional[dict] = None,
    ) -> list[CorpusChunk]:
        """Build chunks from parsed sections.

        Args:
            paper_id: Registry paper ID
            title: Paper title
            sections: List of (section_type, header, content) tuples
            metadata: Additional metadata for chunks

        Returns:
            List of CorpusChunk objects
        """
        chunks: list[CorpusChunk] = []
        chunk_index = 0

        for section_type, header, content in sections:
            section_chunks = self._chunk_section(
                paper_id=paper_id,
                title=title,
                section_type=section_type,
                content=content,
                start_index=chunk_index,
                metadata=metadata or {},
            )
            chunks.extend(section_chunks)
            chunk_index += len(section_chunks)

        logger.debug(
            "chunks_built",
            paper_id=paper_id,
            section_count=len(sections),
            chunk_count=len(chunks),
        )

        return chunks

    def _chunk_section(
        self,
        paper_id: str,
        title: str,
        section_type: ChunkType,
        content: str,
        start_index: int,
        metadata: dict,
    ) -> list[CorpusChunk]:
        """Chunk a single section, splitting if needed.

        Args:
            paper_id: Paper ID
            title: Paper title
            section_type: Section type
            content: Section content
            start_index: Starting chunk index
            metadata: Metadata dict

        Returns:
            List of chunks for this section
        """
        token_count = self.token_counter.count(content)

        # If section fits in one chunk, return it directly
        if token_count <= self.max_tokens:
            chunk = self._create_chunk(
                paper_id=paper_id,
                title=title,
                section_type=section_type,
                content=content,
                token_count=token_count,
                index=start_index,
                metadata=metadata,
            )
            return [chunk]

        # Split at paragraph boundaries
        return self._split_at_paragraphs(
            paper_id=paper_id,
            title=title,
            section_type=section_type,
            content=content,
            start_index=start_index,
            metadata=metadata,
        )

    def _split_at_paragraphs(
        self,
        paper_id: str,
        title: str,
        section_type: ChunkType,
        content: str,
        start_index: int,
        metadata: dict,
    ) -> list[CorpusChunk]:
        """Split content at paragraph boundaries with overlap.

        Args:
            paper_id: Paper ID
            title: Paper title
            section_type: Section type
            content: Content to split
            start_index: Starting index
            metadata: Metadata dict

        Returns:
            List of chunks
        """
        # Split by double newlines (paragraphs)
        paragraphs = re.split(r"\n\n+", content)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        if not paragraphs:
            return []

        chunks: list[CorpusChunk] = []
        current_paragraphs: list[str] = []
        current_tokens = 0
        overlap_buffer: list[str] = []
        chunk_index = start_index

        for para in paragraphs:
            para_tokens = self.token_counter.count(para)

            # Check if adding this paragraph exceeds limit
            if current_tokens + para_tokens > self.max_tokens and current_paragraphs:
                # Create chunk from current paragraphs
                chunk_content = "\n\n".join(current_paragraphs)
                chunk = self._create_chunk(
                    paper_id=paper_id,
                    title=title,
                    section_type=section_type,
                    content=chunk_content,
                    token_count=current_tokens,
                    index=chunk_index,
                    metadata=metadata,
                )
                chunks.append(chunk)
                chunk_index += 1

                # Build overlap buffer from end of current chunk
                overlap_buffer = self._build_overlap_buffer(
                    current_paragraphs, self.overlap_tokens
                )
                current_paragraphs = overlap_buffer.copy()
                current_tokens = sum(
                    self.token_counter.count(p) for p in current_paragraphs
                )

            current_paragraphs.append(para)
            current_tokens += para_tokens

        # Don't forget the last chunk
        if current_paragraphs:
            chunk_content = "\n\n".join(current_paragraphs)
            chunk = self._create_chunk(
                paper_id=paper_id,
                title=title,
                section_type=section_type,
                content=chunk_content,
                token_count=self.token_counter.count(chunk_content),
                index=chunk_index,
                metadata=metadata,
            )
            chunks.append(chunk)

        return chunks

    def _build_overlap_buffer(
        self, paragraphs: list[str], target_tokens: int
    ) -> list[str]:
        """Build overlap buffer from end of paragraph list.

        Args:
            paragraphs: List of paragraphs
            target_tokens: Target token count for overlap

        Returns:
            List of paragraphs for overlap
        """
        buffer: list[str] = []
        token_count = 0

        for para in reversed(paragraphs):
            para_tokens = self.token_counter.count(para)
            if token_count + para_tokens > target_tokens and buffer:
                break
            buffer.insert(0, para)
            token_count += para_tokens

        return buffer

    def _create_chunk(
        self,
        paper_id: str,
        title: str,
        section_type: ChunkType,
        content: str,
        token_count: int,
        index: int,
        metadata: dict,
    ) -> CorpusChunk:
        """Create a CorpusChunk with checksum.

        Args:
            paper_id: Paper ID
            title: Paper title
            section_type: Section type
            content: Chunk content
            token_count: Token count
            index: Chunk index
            metadata: Metadata dict

        Returns:
            CorpusChunk instance
        """
        chunk_id = f"{paper_id}:{index}"
        checksum = compute_checksum(content)

        return CorpusChunk(
            chunk_id=chunk_id,
            paper_id=paper_id,
            section_type=section_type,
            title=title,
            content=content,
            token_count=token_count,
            checksum=checksum,
            metadata=metadata,
        )


def compute_checksum(content: str) -> str:
    """Compute SHA-256 checksum for content.

    Args:
        content: Content to hash

    Returns:
        Hex-encoded SHA-256 hash
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def validate_chunk_integrity(chunk: CorpusChunk) -> bool:
    """Validate chunk integrity by checking checksum.

    Args:
        chunk: Chunk to validate

    Returns:
        True if checksum matches, False otherwise
    """
    if not chunk.checksum:
        return True  # No checksum to validate

    computed = compute_checksum(chunk.content)
    return computed == chunk.checksum

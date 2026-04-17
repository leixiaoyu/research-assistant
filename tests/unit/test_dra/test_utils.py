"""Unit tests for Phase 8 DRA utility functions."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models.dra import ChunkType, CorpusChunk
from src.services.dra.utils import (
    ChunkBuilder,
    SectionParser,
    TextNormalizer,
    TokenCounter,
    atomic_write_json,
    compute_checksum,
    set_secure_permissions,
    validate_chunk_integrity,
)


class TestTokenCounter:
    """Tests for TokenCounter class."""

    def test_default_chars_per_token(self):
        """Test default characters per token."""
        counter = TokenCounter()
        assert counter.chars_per_token == 4.0

    def test_custom_chars_per_token(self):
        """Test custom characters per token."""
        counter = TokenCounter(chars_per_token=5.0)
        assert counter.chars_per_token == 5.0

    def test_count_empty_text(self):
        """Test counting empty text."""
        counter = TokenCounter()
        assert counter.count("") == 0
        assert counter.count(None) == 0  # type: ignore[arg-type]

    def test_count_simple_text(self):
        """Test counting simple text."""
        counter = TokenCounter()
        # "hello world" = 11 chars / 4 = 2.75 -> 2, or 2 words -> max(2, 2) = 2
        result = counter.count("hello world")
        assert result >= 2

    def test_count_longer_text(self):
        """Test counting longer text."""
        counter = TokenCounter()
        text = "This is a longer piece of text with more words and characters."
        result = counter.count(text)
        # Should be reasonable estimate
        assert result > 5
        assert result < len(text)

    def test_count_returns_max_of_estimates(self):
        """Test that count returns max of char and word estimates."""
        counter = TokenCounter(chars_per_token=10.0)
        # Many short words: word count should dominate
        text = "a b c d e f g h i j"  # 10 words, 19 chars -> 19/10 = 1.9 vs 10 words
        result = counter.count(text)
        assert result == 10  # Word count wins


class TestTextNormalizer:
    """Tests for TextNormalizer class."""

    def test_default_settings(self):
        """Test default normalizer settings."""
        normalizer = TextNormalizer()
        assert normalizer.remove_stopwords is True
        assert normalizer.lowercase is True

    def test_normalize_empty_text(self):
        """Test normalizing empty text."""
        normalizer = TextNormalizer()
        assert normalizer.normalize("") == ""
        assert normalizer.normalize(None) == ""  # type: ignore[arg-type]

    def test_normalize_lowercase(self):
        """Test lowercase normalization."""
        normalizer = TextNormalizer(remove_stopwords=False)
        result = normalizer.normalize("Hello WORLD")
        assert "hello" in result
        assert "world" in result

    def test_normalize_no_lowercase(self):
        """Test without lowercase."""
        normalizer = TextNormalizer(lowercase=False, remove_stopwords=False)
        result = normalizer.normalize("Hello WORLD")
        assert "Hello" in result
        assert "WORLD" in result

    def test_normalize_removes_punctuation(self):
        """Test punctuation removal."""
        normalizer = TextNormalizer(remove_stopwords=False)
        result = normalizer.normalize("Hello, world! How are you?")
        assert "," not in result
        assert "!" not in result
        assert "?" not in result

    def test_normalize_removes_stopwords(self):
        """Test stopword removal."""
        normalizer = TextNormalizer()
        result = normalizer.normalize("The quick brown fox is a great animal")
        assert "the" not in result.split()
        assert "is" not in result.split()
        assert "a" not in result.split()
        assert "quick" in result
        assert "brown" in result

    def test_normalize_no_stopword_removal(self):
        """Test without stopword removal."""
        normalizer = TextNormalizer(remove_stopwords=False)
        result = normalizer.normalize("the quick brown fox")
        assert "the" in result

    def test_normalize_collapses_whitespace(self):
        """Test whitespace collapsing."""
        normalizer = TextNormalizer(remove_stopwords=False)
        result = normalizer.normalize("hello    world\n\ntest")
        assert "  " not in result
        assert "\n" not in result

    def test_tokenize_empty(self):
        """Test tokenizing empty text."""
        normalizer = TextNormalizer()
        assert normalizer.tokenize("") == []

    def test_tokenize_returns_words(self):
        """Test tokenize returns word list."""
        normalizer = TextNormalizer()
        tokens = normalizer.tokenize("The neural network learns patterns")
        assert isinstance(tokens, list)
        assert "neural" in tokens
        assert "network" in tokens
        # Stopwords removed
        assert "the" not in tokens


class TestSectionParser:
    """Tests for SectionParser class."""

    def test_parse_empty_content(self):
        """Test parsing empty content."""
        parser = SectionParser()
        assert parser.parse("") == []
        assert parser.parse(None) == []  # type: ignore[arg-type]

    def test_parse_no_headers(self):
        """Test parsing content without headers."""
        parser = SectionParser()
        content = "This is just plain text without any headers."
        sections = parser.parse(content)
        # Content without headers is captured as OTHER section with empty header
        assert len(sections) == 1
        assert sections[0][0] == ChunkType.OTHER
        assert sections[0][1] == ""  # No header text
        assert "plain text" in sections[0][2]

    def test_parse_abstract_section(self):
        """Test parsing abstract section."""
        parser = SectionParser()
        content = """# Abstract

This paper presents a novel approach to machine learning.

# Introduction

We introduce our method here.
"""
        sections = parser.parse(content)
        assert len(sections) == 2
        assert sections[0][0] == ChunkType.ABSTRACT
        assert "novel approach" in sections[0][2]
        assert sections[1][0] == ChunkType.INTRODUCTION

    def test_parse_methods_section(self):
        """Test parsing methods section."""
        parser = SectionParser()
        content = """# Methods

We used the following methodology.

## Experimental Setup

Details of our setup.
"""
        sections = parser.parse(content)
        assert len(sections) >= 1
        assert sections[0][0] == ChunkType.METHODS

    def test_parse_results_section(self):
        """Test parsing results section."""
        parser = SectionParser()
        content = """# Results

Our experiments show significant improvements.
"""
        sections = parser.parse(content)
        assert len(sections) == 1
        assert sections[0][0] == ChunkType.RESULTS

    def test_parse_discussion_section(self):
        """Test parsing discussion section."""
        parser = SectionParser()
        content = """# Discussion

We discuss the implications of our findings.
"""
        sections = parser.parse(content)
        assert len(sections) == 1
        assert sections[0][0] == ChunkType.DISCUSSION

    def test_parse_conclusion_section(self):
        """Test parsing conclusion section."""
        parser = SectionParser()
        content = """# Conclusion

In conclusion, we have demonstrated...
"""
        sections = parser.parse(content)
        assert len(sections) == 1
        assert sections[0][0] == ChunkType.CONCLUSION

    def test_parse_references_section(self):
        """Test parsing references section."""
        parser = SectionParser()
        content = """# References

[1] Author et al. (2023). Title.
"""
        sections = parser.parse(content)
        assert len(sections) == 1
        assert sections[0][0] == ChunkType.REFERENCES

    def test_parse_unknown_section(self):
        """Test parsing unknown section type."""
        parser = SectionParser()
        content = """# Acknowledgments

We thank our sponsors.
"""
        sections = parser.parse(content)
        assert len(sections) == 1
        assert sections[0][0] == ChunkType.OTHER

    def test_parse_case_insensitive(self):
        """Test parsing is case insensitive."""
        parser = SectionParser()
        content = """# ABSTRACT

Content here.

# METHODS

More content.
"""
        sections = parser.parse(content)
        assert sections[0][0] == ChunkType.ABSTRACT
        assert sections[1][0] == ChunkType.METHODS

    def test_parse_alternative_names(self):
        """Test parsing alternative section names."""
        parser = SectionParser()
        content = """# Summary

Executive summary here.

# Methodology

Our approach.

# Findings

What we found.
"""
        sections = parser.parse(content)
        # Summary -> ABSTRACT or CONCLUSION
        # Methodology -> METHODS
        # Findings -> RESULTS
        assert any(s[0] == ChunkType.METHODS for s in sections)

    def test_parse_multiple_heading_levels(self):
        """Test parsing different heading levels."""
        parser = SectionParser()
        content = """## Introduction

Intro content.

### Background

Background info.
"""
        sections = parser.parse(content)
        assert len(sections) >= 1

    def test_parse_empty_section_content(self):
        """Test parsing when section has only whitespace content (line 198 false)."""
        parser = SectionParser()
        content = """# Abstract

# Methods

Actual methods content here.
"""
        sections = parser.parse(content)
        # Abstract section has no content, only Methods should be returned
        assert len(sections) == 1
        assert sections[0][0] == ChunkType.METHODS

    def test_parse_trailing_whitespace_only(self):
        """Test parsing with trailing whitespace after last header (line 212 false)."""
        parser = SectionParser()
        content = """# Abstract

Abstract content here.

# Conclusion


"""
        sections = parser.parse(content)
        # Conclusion section has only whitespace, should not be included
        assert len(sections) == 1
        assert sections[0][0] == ChunkType.ABSTRACT


class TestChunkBuilder:
    """Tests for ChunkBuilder class."""

    def test_default_settings(self):
        """Test default chunk builder settings."""
        builder = ChunkBuilder()
        assert builder.max_tokens == 512
        assert builder.overlap_tokens == 64

    def test_custom_settings(self):
        """Test custom chunk builder settings."""
        builder = ChunkBuilder(max_tokens=256, overlap_tokens=32)
        assert builder.max_tokens == 256
        assert builder.overlap_tokens == 32

    def test_build_chunks_empty_sections(self):
        """Test building chunks from empty sections."""
        builder = ChunkBuilder()
        chunks = builder.build_chunks(
            paper_id="paper1",
            title="Test Paper",
            sections=[],
        )
        assert chunks == []

    def test_build_chunks_single_section(self):
        """Test building chunks from single section."""
        builder = ChunkBuilder(max_tokens=1000)
        sections = [(ChunkType.ABSTRACT, "Abstract", "This is a short abstract.")]
        chunks = builder.build_chunks(
            paper_id="paper1",
            title="Test Paper",
            sections=sections,
        )
        assert len(chunks) == 1
        assert chunks[0].chunk_id == "paper1:0"
        assert chunks[0].paper_id == "paper1"
        assert chunks[0].section_type == ChunkType.ABSTRACT
        assert chunks[0].title == "Test Paper"
        assert "short abstract" in chunks[0].content

    def test_build_chunks_multiple_sections(self):
        """Test building chunks from multiple sections."""
        builder = ChunkBuilder(max_tokens=1000)
        sections = [
            (ChunkType.ABSTRACT, "Abstract", "Abstract content."),
            (ChunkType.INTRODUCTION, "Introduction", "Introduction content."),
            (ChunkType.METHODS, "Methods", "Methods content."),
        ]
        chunks = builder.build_chunks(
            paper_id="paper1",
            title="Test",
            sections=sections,
        )
        assert len(chunks) == 3
        assert chunks[0].chunk_id == "paper1:0"
        assert chunks[1].chunk_id == "paper1:1"
        assert chunks[2].chunk_id == "paper1:2"

    def test_build_chunks_with_splitting(self):
        """Test building chunks that need splitting."""
        builder = ChunkBuilder(max_tokens=50, overlap_tokens=10)
        # Create long content with paragraphs
        long_content = "\n\n".join([f"Paragraph {i}. " * 20 for i in range(5)])
        sections = [(ChunkType.METHODS, "Methods", long_content)]
        chunks = builder.build_chunks(
            paper_id="paper1",
            title="Test",
            sections=sections,
        )
        # Should create multiple chunks
        assert len(chunks) > 1

    def test_build_chunks_with_metadata(self):
        """Test building chunks with metadata."""
        builder = ChunkBuilder()
        sections = [(ChunkType.ABSTRACT, "Abstract", "Content here.")]
        metadata = {"doi": "10.1234/test"}
        chunks = builder.build_chunks(
            paper_id="paper1",
            title="Test",
            sections=sections,
            metadata=metadata,
        )
        assert chunks[0].metadata == metadata

    def test_build_chunks_has_checksum(self):
        """Test that built chunks have checksums."""
        builder = ChunkBuilder()
        sections = [(ChunkType.ABSTRACT, "Abstract", "Content here.")]
        chunks = builder.build_chunks(
            paper_id="paper1",
            title="Test",
            sections=sections,
        )
        assert chunks[0].checksum is not None
        assert len(chunks[0].checksum) == 64  # SHA-256 hex

    def test_build_chunks_sequential_indices(self):
        """Test that chunk indices are sequential."""
        builder = ChunkBuilder(max_tokens=30, overlap_tokens=5)
        long_content = "\n\n".join([f"Para {i}. " * 10 for i in range(10)])
        sections = [(ChunkType.METHODS, "Methods", long_content)]
        chunks = builder.build_chunks(
            paper_id="paper1",
            title="Test",
            sections=sections,
        )
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_id == f"paper1:{i}"


class TestComputeChecksum:
    """Tests for compute_checksum function."""

    def test_empty_content(self):
        """Test checksum of empty content."""
        checksum = compute_checksum("")
        assert len(checksum) == 64
        # SHA-256 of empty string
        assert (
            checksum
            == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_consistent_checksum(self):
        """Test checksum is consistent."""
        content = "Hello, world!"
        checksum1 = compute_checksum(content)
        checksum2 = compute_checksum(content)
        assert checksum1 == checksum2

    def test_different_content_different_checksum(self):
        """Test different content has different checksum."""
        checksum1 = compute_checksum("Hello")
        checksum2 = compute_checksum("World")
        assert checksum1 != checksum2

    def test_checksum_format(self):
        """Test checksum is valid hex."""
        checksum = compute_checksum("test")
        assert all(c in "0123456789abcdef" for c in checksum)


class TestValidateChunkIntegrity:
    """Tests for validate_chunk_integrity function."""

    def test_valid_chunk(self):
        """Test validating a chunk with correct checksum."""
        content = "Test content"
        checksum = compute_checksum(content)
        chunk = CorpusChunk(
            chunk_id="test:0",
            paper_id="test",
            title="Test",
            content=content,
            token_count=2,
            checksum=checksum,
        )
        assert validate_chunk_integrity(chunk) is True

    def test_invalid_chunk(self):
        """Test validating a chunk with incorrect checksum."""
        chunk = CorpusChunk(
            chunk_id="test:0",
            paper_id="test",
            title="Test",
            content="Test content",
            token_count=2,
            checksum="invalid_checksum",
        )
        assert validate_chunk_integrity(chunk) is False

    def test_chunk_without_checksum(self):
        """Test validating a chunk without checksum."""
        chunk = CorpusChunk(
            chunk_id="test:0",
            paper_id="test",
            title="Test",
            content="Test content",
            token_count=2,
        )
        # No checksum means valid (nothing to validate)
        assert validate_chunk_integrity(chunk) is True

    def test_modified_content_fails_validation(self):
        """Test that modified content fails validation."""
        original = "Original content"
        checksum = compute_checksum(original)
        chunk = CorpusChunk(
            chunk_id="test:0",
            paper_id="test",
            title="Test",
            content="Modified content",  # Different from checksum
            token_count=2,
            checksum=checksum,
        )
        assert validate_chunk_integrity(chunk) is False


class TestAtomicWriteJson:
    """Tests for atomic_write_json function (SR-8.1)."""

    def test_writes_valid_json(self):
        """Test that atomic_write_json writes valid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "test.json"
            data = {"key": "value", "number": 42}

            atomic_write_json(target_path, data)

            assert target_path.exists()
            with open(target_path) as f:
                loaded = json.load(f)
            assert loaded == data

    def test_writes_with_indentation(self):
        """Test that atomic_write_json uses proper indentation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "test.json"
            data = {"key": "value"}

            atomic_write_json(target_path, data, indent=2)

            content = target_path.read_text()
            assert "\n" in content  # Indented JSON has newlines

    def test_overwrites_existing_file(self):
        """Test that atomic_write_json overwrites existing files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "test.json"
            target_path.write_text('{"old": "data"}')

            atomic_write_json(target_path, {"new": "data"})

            with open(target_path) as f:
                loaded = json.load(f)
            assert loaded == {"new": "data"}

    def test_no_temp_files_left_on_success(self):
        """Test that no temp files are left after successful write."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "test.json"

            atomic_write_json(target_path, {"key": "value"})

            files = list(Path(tmpdir).iterdir())
            assert len(files) == 1
            assert files[0].name == "test.json"

    def test_cleans_up_temp_file_on_json_error(self):
        """Test that temp files are cleaned up on JSON serialization error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "test.json"

            # Create a non-serializable object
            class NotSerializable:
                pass

            with pytest.raises(TypeError):
                atomic_write_json(target_path, {"bad": NotSerializable()})

            # No temp files should remain
            files = list(Path(tmpdir).iterdir())
            assert len(files) == 0

    def test_cleans_up_temp_file_on_rename_error(self):
        """Test that temp files are cleaned up if rename fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "test.json"

            with patch("pathlib.Path.rename", side_effect=OSError("Rename failed")):
                with pytest.raises(OSError):
                    atomic_write_json(target_path, {"key": "value"})

            # Temp file should be cleaned up
            files = list(Path(tmpdir).iterdir())
            assert len(files) == 0

    def test_complex_data_structures(self):
        """Test atomic_write_json with complex nested data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "test.json"
            data = {
                "papers": [
                    {"id": "paper1", "chunks": ["c1", "c2"]},
                    {"id": "paper2", "chunks": ["c3"]},
                ],
                "stats": {"total": 2, "updated": "2026-01-01"},
            }

            atomic_write_json(target_path, data)

            with open(target_path) as f:
                loaded = json.load(f)
            assert loaded == data

    def test_sets_file_permissions_with_file_mode(self):
        """Test atomic_write_json sets file permissions when file_mode given."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "secure.json"

            # Write with SR-8.1 secure file permissions (0600)
            atomic_write_json(target_path, {"sensitive": "data"}, file_mode=0o600)

            # Verify file permissions
            mode = target_path.stat().st_mode & 0o777
            assert mode == 0o600

    def test_no_file_mode_uses_default_permissions(self):
        """Test that omitting file_mode doesn't change permissions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "default.json"

            # Write without file_mode
            atomic_write_json(target_path, {"key": "value"})

            # File should exist (permissions depend on umask)
            assert target_path.exists()


class TestSetSecurePermissions:
    """Tests for set_secure_permissions function (SR-8.1)."""

    def test_sets_directory_permissions(self):
        """Test that set_secure_permissions sets correct mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "secure_dir"
            test_dir.mkdir()

            set_secure_permissions(test_dir, 0o700)

            # Check permissions (on Unix systems)
            mode = test_dir.stat().st_mode & 0o777
            assert mode == 0o700

    def test_sets_file_permissions(self):
        """Test that set_secure_permissions works on files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "secure_file.txt"
            test_file.write_text("test")

            set_secure_permissions(test_file, 0o600)

            mode = test_file.stat().st_mode & 0o777
            assert mode == 0o600

    def test_handles_chmod_error_gracefully(self):
        """Test that chmod errors are logged but don't raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = Path(tmpdir) / "test"
            test_path.mkdir()

            with patch("os.chmod", side_effect=OSError("Permission denied")):
                # Should not raise, just log warning
                set_secure_permissions(test_path, 0o700)

    def test_default_mode_is_0700(self):
        """Test that default mode is 0o700."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "default_mode"
            test_dir.mkdir()

            set_secure_permissions(test_dir)  # Use default

            mode = test_dir.stat().st_mode & 0o777
            assert mode == 0o700

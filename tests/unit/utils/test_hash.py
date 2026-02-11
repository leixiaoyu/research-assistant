"""Tests for Phase 3.5 hash utilities."""

from src.utils.hash import (
    calculate_extraction_hash,
    normalize_title,
    calculate_title_similarity,
    generate_topic_slug,
)
from src.models.extraction import ExtractionTarget


class TestCalculateExtractionHash:
    """Tests for extraction target hashing."""

    def test_empty_targets_returns_special_hash(self):
        """Test empty targets returns 'sha256:empty'."""
        result = calculate_extraction_hash(None)
        assert result == "sha256:empty"

        result = calculate_extraction_hash([])
        assert result == "sha256:empty"

    def test_single_target_returns_hash(self):
        """Test single target returns SHA-256 hash."""
        targets = [
            ExtractionTarget(
                name="prompts",
                description="Extract system prompts",
                output_format="list",
            )
        ]

        result = calculate_extraction_hash(targets)

        assert result.startswith("sha256:")
        assert len(result) > 10

    def test_same_targets_same_hash(self):
        """Test identical targets produce identical hash."""
        targets1 = [
            ExtractionTarget(
                name="prompts",
                description="Extract system prompts",
                output_format="list",
            )
        ]
        targets2 = [
            ExtractionTarget(
                name="prompts",
                description="Extract system prompts",
                output_format="list",
            )
        ]

        assert calculate_extraction_hash(targets1) == calculate_extraction_hash(
            targets2
        )

    def test_different_targets_different_hash(self):
        """Test different targets produce different hash."""
        targets1 = [
            ExtractionTarget(
                name="prompts",
                description="Extract system prompts",
                output_format="list",
            )
        ]
        targets2 = [
            ExtractionTarget(
                name="code",
                description="Extract code snippets",
                output_format="code",
            )
        ]

        assert calculate_extraction_hash(targets1) != calculate_extraction_hash(
            targets2
        )

    def test_order_independent_hashing(self):
        """Test that target order doesn't affect hash."""
        target_a = ExtractionTarget(
            name="aaa",
            description="First target",
            output_format="text",
        )
        target_b = ExtractionTarget(
            name="bbb",
            description="Second target",
            output_format="text",
        )

        hash1 = calculate_extraction_hash([target_a, target_b])
        hash2 = calculate_extraction_hash([target_b, target_a])

        assert hash1 == hash2

    def test_case_insensitive_normalization(self):
        """Test that name/description are normalized to lowercase."""
        targets1 = [
            ExtractionTarget(
                name="PROMPTS",
                description="EXTRACT SYSTEM PROMPTS",
                output_format="list",
            )
        ]
        targets2 = [
            ExtractionTarget(
                name="prompts",
                description="extract system prompts",
                output_format="list",
            )
        ]

        assert calculate_extraction_hash(targets1) == calculate_extraction_hash(
            targets2
        )

    def test_whitespace_trimmed(self):
        """Test that whitespace is trimmed from name/description."""
        targets1 = [
            ExtractionTarget(
                name="  prompts  ",
                description="  extract prompts  ",
                output_format="list",
            )
        ]
        targets2 = [
            ExtractionTarget(
                name="prompts",
                description="extract prompts",
                output_format="list",
            )
        ]

        assert calculate_extraction_hash(targets1) == calculate_extraction_hash(
            targets2
        )


class TestNormalizeTitle:
    """Tests for title normalization."""

    def test_empty_title(self):
        """Test empty title returns empty string."""
        assert normalize_title("") == ""
        assert normalize_title(None) == ""

    def test_lowercase_conversion(self):
        """Test uppercase is converted to lowercase."""
        result = normalize_title("ATTENTION IS ALL YOU NEED")
        assert result == "attention is all you need"

    def test_punctuation_removal(self):
        """Test punctuation is removed."""
        result = normalize_title("Attention: Is All You Need!")
        assert result == "attention is all you need"

    def test_special_characters_removed(self):
        """Test special characters are removed."""
        result = normalize_title("GPT-4: A Large-Scale Model")
        assert result == "gpt4 a largescale model"

    def test_whitespace_collapse(self):
        """Test multiple spaces collapsed to single space."""
        result = normalize_title("Title   With   Spaces")
        assert result == "title with spaces"

    def test_whitespace_trimmed(self):
        """Test leading/trailing whitespace is trimmed."""
        result = normalize_title("  Title  ")
        assert result == "title"


class TestCalculateTitleSimilarity:
    """Tests for title similarity calculation."""

    def test_identical_titles_return_1(self):
        """Test identical titles have similarity 1.0."""
        result = calculate_title_similarity(
            "Attention Is All You Need",
            "Attention Is All You Need",
        )
        assert result == 1.0

    def test_normalized_identical_return_1(self):
        """Test titles that normalize to same string have similarity 1.0."""
        result = calculate_title_similarity(
            "ATTENTION IS ALL YOU NEED",
            "attention is all you need",
        )
        assert result == 1.0

    def test_completely_different_low_similarity(self):
        """Test completely different titles have low similarity."""
        result = calculate_title_similarity(
            "Machine Learning Fundamentals",
            "Quantum Computing Applications",
        )
        assert result < 0.5

    def test_similar_titles_high_similarity(self):
        """Test similar titles have high similarity."""
        # Minor typo: "Attentions" instead of "Attention"
        result = calculate_title_similarity(
            "Attention Is All You Need",
            "Attentions Is All You Need",
        )
        assert result > 0.8

    def test_empty_title_returns_0(self):
        """Test empty titles return similarity 0."""
        assert calculate_title_similarity("", "Some Title") == 0.0
        assert calculate_title_similarity("Some Title", "") == 0.0
        assert calculate_title_similarity("", "") == 0.0

    def test_threshold_95_percent(self):
        """Test typical matching scenario at 95% threshold."""
        # These should match at 95% threshold
        result = calculate_title_similarity(
            "Attention Is All You Need",
            "Attention Is All You Need Version 2",
        )
        # Should be below 95% due to version suffix
        assert result < 0.95

    def test_short_titles_trigram_handling(self):
        """Test short titles (less than 3 chars) are handled correctly."""
        # Short strings use the whole string as a single trigram
        result = calculate_title_similarity("AI", "AI")
        assert result == 1.0

        # Different short strings
        result = calculate_title_similarity("AI", "ML")
        assert result == 0.0

    def test_very_short_title_vs_long(self):
        """Test short title compared to long title."""
        result = calculate_title_similarity("AI", "Artificial Intelligence")
        assert result < 0.5


class TestGenerateTopicSlug:
    """Tests for topic slug generation."""

    def test_simple_query(self):
        """Test simple query generates slug."""
        result = generate_topic_slug("machine learning")
        assert result == "machine-learning"

    def test_uppercase_converted(self):
        """Test uppercase is converted to lowercase."""
        result = generate_topic_slug("Machine Learning")
        assert result == "machine-learning"

    def test_and_operator_replaced(self):
        """Test AND operator is replaced with hyphen."""
        result = generate_topic_slug("NLP AND transformers")
        assert result == "nlp-transformers"

    def test_or_operator_replaced(self):
        """Test OR operator is replaced with hyphen."""
        result = generate_topic_slug("GPT OR BERT")
        assert result == "gpt-bert"

    def test_special_characters_removed(self):
        """Test special characters are removed."""
        result = generate_topic_slug("GPT-4: Advanced AI!")
        assert result == "gpt-4-advanced-ai"

    def test_multiple_hyphens_collapsed(self):
        """Test multiple hyphens are collapsed."""
        result = generate_topic_slug("AI --- ML")
        assert result == "ai-ml"

    def test_leading_trailing_hyphens_stripped(self):
        """Test leading/trailing hyphens are stripped."""
        result = generate_topic_slug("---test---")
        assert result == "test"

    def test_empty_query_returns_default(self):
        """Test empty query returns default slug."""
        assert generate_topic_slug("") == "unknown-topic"
        assert generate_topic_slug(None) == "unknown-topic"

    def test_long_query_truncated(self):
        """Test long query is truncated to 64 characters."""
        long_query = "a" * 100
        result = generate_topic_slug(long_query)
        assert len(result) <= 64

    def test_truncation_preserves_hyphens(self):
        """Test truncation doesn't leave trailing hyphen."""
        long_query = "a" * 60 + " test query"
        result = generate_topic_slug(long_query)
        assert not result.endswith("-")

    def test_only_special_chars_returns_default(self):
        """Test query with only special chars returns default."""
        result = generate_topic_slug("!@#$%^&*()")
        assert result == "unknown-topic"

"""Tests for author_utils module."""

from src.utils.author_utils import normalize_authors


class TestNormalizeAuthors:
    """Tests for normalize_authors function."""

    def test_normalize_authors_list_of_dicts(self):
        """Convert List[dict] to List[str]."""
        authors = [
            {"name": "John Doe", "authorId": "123"},
            {"name": "Jane Smith", "affiliation": "MIT"},
        ]
        result = normalize_authors(authors)
        assert result == ["John Doe", "Jane Smith"]

    def test_normalize_authors_list_of_strings(self):
        """Pass through List[str] unchanged."""
        authors = ["John Doe", "Jane Smith"]
        result = normalize_authors(authors)
        assert result == ["John Doe", "Jane Smith"]

    def test_normalize_authors_single_string(self):
        """Convert single string to list."""
        result = normalize_authors("John Doe")
        assert result == ["John Doe"]

    def test_normalize_authors_none(self):
        """Handle None input."""
        result = normalize_authors(None)
        assert result == []

    def test_normalize_authors_empty_list(self):
        """Handle empty list input."""
        result = normalize_authors([])
        assert result == []

    def test_normalize_authors_empty_string(self):
        """Handle empty string input (falsy)."""
        result = normalize_authors("")
        assert result == []

    def test_normalize_authors_mixed_list(self):
        """Handle mixed list of dicts and strings."""
        authors = [{"name": "John Doe"}, "Jane Smith", {"name": "Bob Wilson"}]
        result = normalize_authors(authors)
        assert result == ["John Doe", "Jane Smith", "Bob Wilson"]

    def test_normalize_authors_dict_missing_name(self):
        """Fallback to str() if 'name' key missing."""
        authors = [{"authorId": "123", "affiliation": "Stanford"}]
        result = normalize_authors(authors)
        assert len(result) == 1
        # str(dict) representation should contain the keys
        assert "authorId" in result[0]
        assert "123" in result[0]

    def test_normalize_authors_dict_with_none_name(self):
        """Handle dict with name=None (falls back to str(dict))."""
        authors = [{"name": None, "authorId": "123"}]
        result = normalize_authors(authors)
        # get() returns None, so we fallback to str(dict)
        assert len(result) == 1
        assert "authorId" in result[0]
        assert "123" in result[0]

    def test_normalize_authors_nested_data(self):
        """Handle dict with complex nested data gracefully."""
        authors = [
            {
                "name": "Dr. Alice Chen",
                "authorId": "456",
                "affiliations": [{"name": "Stanford", "country": "USA"}],
            }
        ]
        result = normalize_authors(authors)
        assert result == ["Dr. Alice Chen"]

    def test_normalize_authors_numeric_values_in_list(self):
        """Handle numeric values in list (converted via str())."""
        # Edge case: if someone passes numbers, they get stringified
        authors = [123, 456]
        result = normalize_authors(authors)
        assert result == ["123", "456"]

    def test_normalize_authors_preserves_order(self):
        """Verify author order is preserved."""
        authors = [
            {"name": "First Author"},
            {"name": "Second Author"},
            {"name": "Third Author"},
        ]
        result = normalize_authors(authors)
        assert result == ["First Author", "Second Author", "Third Author"]

    def test_normalize_authors_unicode_names(self):
        """Handle Unicode characters in author names."""
        authors = [
            {"name": "Marie Curie"},
            {"name": "Yann LeCun"},
        ]
        result = normalize_authors(authors)
        assert result == ["Marie Curie", "Yann LeCun"]

    def test_normalize_authors_whitespace_handling(self):
        """Names with whitespace are preserved as-is."""
        authors = [{"name": "  John Doe  "}]
        result = normalize_authors(authors)
        # Whitespace is preserved (caller can strip if needed)
        assert result == ["  John Doe  "]

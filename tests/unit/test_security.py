import pytest
from pathlib import Path
from src.utils.security import PathSanitizer, InputValidation, SecurityError


def test_path_sanitizer_valid(tmp_path):
    sanitizer = PathSanitizer(allowed_bases=[tmp_path])

    # Valid child
    child = tmp_path / "child.txt"
    safe = sanitizer.safe_path(tmp_path, "child.txt")
    assert safe == child.resolve()

    # Valid subdirectory
    subdir = tmp_path / "subdir" / "file.txt"
    safe = sanitizer.safe_path(tmp_path, "subdir/file.txt")
    assert safe == subdir.resolve()


def test_path_sanitizer_traversal(tmp_path):
    sanitizer = PathSanitizer(allowed_bases=[tmp_path])

    # Simple traversal
    with pytest.raises(SecurityError):
        sanitizer.safe_path(tmp_path, "../outside.txt")

    # Root traversal
    with pytest.raises(SecurityError):
        sanitizer.safe_path(tmp_path, "/etc/passwd")


def test_path_sanitizer_base_check(tmp_path):
    # Base not in allowed list
    other_path = Path("/tmp/other")
    sanitizer = PathSanitizer(allowed_bases=[tmp_path])

    with pytest.raises(SecurityError):
        sanitizer.safe_path(other_path, "file.txt")


def test_input_validation_query():
    # Valid
    assert InputValidation.validate_query("machine learning") == "machine learning"
    assert InputValidation.validate_query("AI AND Robotics") == "AI AND Robotics"

    # Invalid character &
    with pytest.raises(ValueError):
        InputValidation.validate_query("AI & Robotics")

    # Command injection
    with pytest.raises(ValueError):
        InputValidation.validate_query("test; rm -rf /")

    with pytest.raises(ValueError):
        InputValidation.validate_query("$(whoami)")


def test_input_validation_invalid_char_logging():
    from unittest.mock import patch

    with patch("src.utils.security.logger") as mock_logger:
        # String with invalid char that is NOT a dangerous pattern
        # whitelist: [a-zA-Z0-9\s\-_+.,"():]
        # char '#' is not allowed but not in dangerous_patterns list
        with pytest.raises(
            ValueError, match="Query contains characters outside allowed set"
        ):
            InputValidation.validate_query("valid query with # hash")

        # Check if logger was called for the invalid char '#'
        mock_logger.warning.assert_any_call(
            "invalid_char_detected", char="#", query="valid query with # hash"
        )


class TestSanitizePathComponent:
    """Tests for PathSanitizer.sanitize_path_component static method."""

    def test_removes_null_bytes(self):
        """Test that null bytes are removed."""
        result = PathSanitizer.sanitize_path_component("test\x00file")
        assert "\x00" not in result
        assert result == "testfile"

    def test_removes_directory_traversal(self):
        """Test that directory traversal patterns are removed."""
        result = PathSanitizer.sanitize_path_component("../malicious")
        assert ".." not in result
        assert "/" not in result

    def test_replaces_slashes(self):
        """Test that slashes are replaced with dashes."""
        result = PathSanitizer.sanitize_path_component("path/to/file")
        assert "/" not in result
        assert result == "path-to-file"

    def test_replaces_backslashes(self):
        """Test that backslashes are replaced with dashes."""
        result = PathSanitizer.sanitize_path_component("path\\to\\file")
        assert "\\" not in result
        assert result == "path-to-file"

    def test_replaces_invalid_filesystem_chars(self):
        """Test that invalid filesystem characters are replaced."""
        result = PathSanitizer.sanitize_path_component("file<name>:test|?*")
        for char in '<>:"|?*':
            assert char not in result

    def test_collapses_multiple_dashes(self):
        """Test that multiple dashes are collapsed to single dash."""
        result = PathSanitizer.sanitize_path_component("test---file")
        assert "---" not in result
        assert "--" not in result
        assert result == "test-file"

    def test_strips_leading_trailing_dashes(self):
        """Test that leading/trailing dashes are stripped."""
        result = PathSanitizer.sanitize_path_component("-test-file-")
        assert not result.startswith("-")
        assert not result.endswith("-")
        assert result == "test-file"

    def test_strips_leading_trailing_dots_and_spaces(self):
        """Test that leading/trailing dots and spaces are stripped."""
        result = PathSanitizer.sanitize_path_component("...test file...")
        assert not result.startswith(".")
        assert not result.endswith(".")

    def test_fallback_for_empty_input(self):
        """Test that empty input returns 'unnamed'."""
        result = PathSanitizer.sanitize_path_component("")
        assert result == "unnamed"

    def test_fallback_for_all_invalid_chars(self):
        """Test that input with only invalid chars returns 'unnamed'."""
        result = PathSanitizer.sanitize_path_component("...")
        assert result == "unnamed"

        result = PathSanitizer.sanitize_path_component("///")
        assert result == "unnamed"

    def test_normal_input_unchanged(self):
        """Test that normal input is returned unchanged."""
        result = PathSanitizer.sanitize_path_component("valid-topic-name")
        assert result == "valid-topic-name"

    def test_preserves_underscores(self):
        """Test that underscores are preserved."""
        result = PathSanitizer.sanitize_path_component("my_topic_name")
        assert result == "my_topic_name"

"""Unit tests for the phase spec validation script.

Tests cover:
- Status extraction from spec files
- Completion indicator detection
- Planning indicator detection
- Validation issue generation
- End-to-end validation scenarios
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Import from scripts directory (path configured in conftest.py)
from validate_phase_specs import (
    ValidationIssue,
    extract_status,
    has_completion_indicators,
    has_planning_indicators,
    validate_spec_file,
    validate_all_specs,
)


class TestExtractStatus:
    """Tests for status extraction."""

    def test_extracts_complete_status(self) -> None:
        content = "**Status:** ✅ **COMPLETED** (Feb 28, 2026)"
        assert extract_status(content) == "✅ **COMPLETED** (Feb 28, 2026)"

    def test_extracts_planning_status(self) -> None:
        content = "**Status:** 📋 Planning"
        assert extract_status(content) == "📋 Planning"

    def test_extracts_in_progress_status(self) -> None:
        content = "**Status:** 🔄 **IN PROGRESS**"
        assert extract_status(content) == "🔄 **IN PROGRESS**"

    def test_returns_none_when_no_status(self) -> None:
        content = "# Phase 1\n\nSome content without status line."
        assert extract_status(content) is None

    def test_extracts_multiline_content(self) -> None:
        content = """# Phase 5.3
**Version:** 1.1
**Status:** ✅ Complete
**Timeline:** 2 days
"""
        assert extract_status(content) == "✅ Complete"


class TestHasCompletionIndicators:
    """Tests for completion indicator detection."""

    def test_detects_checkmark_complete(self) -> None:
        content = "**Status:** ✅ Complete"
        assert has_completion_indicators(content) is True

    def test_detects_checkmark_completed(self) -> None:
        content = "✅ COMPLETED"
        assert has_completion_indicators(content) is True

    def test_detects_status_checkmark(self) -> None:
        content = "**Status:** ✅"
        assert has_completion_indicators(content) is True

    def test_detects_completed_date(self) -> None:
        content = "Completed February 28, 2026"
        assert has_completion_indicators(content) is True

    def test_detects_file_size_results(self) -> None:
        content = "## 9. File Size Results\n\n| File | Size |"
        assert has_completion_indicators(content) is True

    def test_detects_verification_results(self) -> None:
        content = "## 7. Verification Results\n\nAll tests passed."
        assert has_completion_indicators(content) is True

    def test_no_indicators_returns_false(self) -> None:
        content = "# Phase 5.4\n\nThis phase is still in planning."
        assert has_completion_indicators(content) is False


class TestHasPlanningIndicators:
    """Tests for planning indicator detection."""

    def test_detects_emoji_planning(self) -> None:
        content = "**Status:** 📋 Planning"
        assert has_planning_indicators(content) is True

    def test_detects_status_emoji(self) -> None:
        content = "**Status:** 📋"
        assert has_planning_indicators(content) is True

    def test_detects_text_planning(self) -> None:
        content = "Status: Planning"
        assert has_planning_indicators(content) is True

    def test_no_planning_returns_false(self) -> None:
        content = "**Status:** ✅ Complete"
        assert has_planning_indicators(content) is False


class TestValidateSpecFile:
    """Tests for spec file validation."""

    def test_detects_planning_with_completion_indicators(self) -> None:
        content = """# Phase 5.3
**Status:** 📋 Planning

## 9. File Size Results
| File | Size |
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(content)
            f.flush()
            issues = validate_spec_file(Path(f.name))

        assert len(issues) == 1
        assert issues[0].severity == "WARN"
        assert "Planning" in issues[0].message
        assert "completion indicators" in issues[0].message

    def test_passes_consistent_complete(self) -> None:
        content = """# Phase 5.3
**Status:** ✅ **COMPLETED** (Feb 28, 2026)

## 9. File Size Results
| File | Size |
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(content)
            f.flush()
            issues = validate_spec_file(Path(f.name))

        assert len(issues) == 0

    def test_passes_consistent_planning(self) -> None:
        content = """# Phase 5.4
**Status:** 📋 Planning

This phase is not yet started.
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(content)
            f.flush()
            issues = validate_spec_file(Path(f.name))

        assert len(issues) == 0

    def test_handles_missing_status(self) -> None:
        content = """# Phase Info

Some content without a status line.
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(content)
            f.flush()
            issues = validate_spec_file(Path(f.name))

        assert len(issues) == 0

    def test_handles_unreadable_file(self) -> None:
        issues = validate_spec_file(Path("/nonexistent/file.md"))
        assert len(issues) == 1
        assert issues[0].severity == "ERROR"
        assert "Cannot read file" in issues[0].message


class TestValidationIssue:
    """Tests for ValidationIssue dataclass."""

    def test_str_format(self) -> None:
        issue = ValidationIssue("PHASE_5.3_SPEC.md", "WARN", "Test message")
        assert str(issue) == "WARN: PHASE_5.3_SPEC.md - Test message"

    def test_error_format(self) -> None:
        issue = ValidationIssue("test.md", "ERROR", "Critical issue")
        assert str(issue) == "ERROR: test.md - Critical issue"


class TestValidateAllSpecs:
    """Tests for full validation run."""

    def test_returns_empty_when_no_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            specs_dir = Path(tmpdir) / "docs" / "specs"
            specs_dir.mkdir(parents=True)

            # Create a valid spec file
            spec_file = specs_dir / "PHASE_1_SPEC.md"
            spec_file.write_text(
                "# Phase 1\n**Status:** ✅ Complete\n\n## 9. File Size Results\n"
            )

            with patch(
                "validate_phase_specs.SPECS_DIR", specs_dir
            ):
                issues, count = validate_all_specs()

            assert count == 1
            assert len(issues) == 0

    def test_handles_missing_directory(self) -> None:
        with patch(
            "validate_phase_specs.SPECS_DIR", Path("/nonexistent/path")
        ):
            issues, count = validate_all_specs()

        assert count == 0
        assert len(issues) == 1
        assert issues[0].severity == "ERROR"


# Integration test
class TestIntegration:
    """Integration tests running against actual project files."""

    def test_validate_real_specs_no_errors(self) -> None:
        """Ensure validation runs without errors on real specs."""
        issues, count = validate_all_specs()

        # Should have checked files
        assert count > 0

        # Should have no ERROR level issues
        errors = [i for i in issues if i.severity == "ERROR"]
        assert len(errors) == 0, f"Unexpected errors: {errors}"

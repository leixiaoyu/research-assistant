"""Tests for ResponseParser module.

Phase 5.1: Tests for response parsing and validation.
"""

import pytest
from unittest.mock import MagicMock

from src.services.llm.response_parser import ResponseParser
from src.models.extraction import ExtractionTarget
from src.utils.exceptions import JSONParseError


class TestResponseParser:
    """Tests for ResponseParser class."""

    @pytest.fixture
    def parser(self) -> ResponseParser:
        """Create test response parser."""
        return ResponseParser()

    @pytest.fixture
    def extraction_targets(self) -> list[ExtractionTarget]:
        """Create test extraction targets."""
        return [
            ExtractionTarget(
                name="summary",
                description="Extract summary",
                output_format="text",
                required=True,
                examples=[],
            ),
            ExtractionTarget(
                name="code",
                description="Extract code",
                output_format="code",
                required=False,
                examples=[],
            ),
        ]

    def test_parse_valid_response(
        self,
        parser: ResponseParser,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing valid JSON response."""
        json_content = """{
            "extractions": [
                {
                    "target_name": "summary",
                    "success": true,
                    "content": "This is a test summary.",
                    "confidence": 0.95,
                    "error": null
                },
                {
                    "target_name": "code",
                    "success": true,
                    "content": "def test(): pass",
                    "confidence": 0.8,
                    "error": null
                }
            ]
        }"""

        results = parser.parse_from_text(json_content, extraction_targets)

        assert len(results) == 2
        assert results[0].target_name == "summary"
        assert results[0].success is True
        assert results[0].content == "This is a test summary."
        assert results[0].confidence == 0.95

    def test_parse_with_code_blocks(
        self,
        parser: ResponseParser,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing response with markdown code blocks."""
        json_content = """```json
{
    "extractions": [
        {
            "target_name": "summary",
            "success": true,
            "content": "Test summary",
            "confidence": 0.9,
            "error": null
        }
    ]
}
```"""

        results = parser.parse_from_text(json_content, extraction_targets)

        assert len(results) == 1
        assert results[0].target_name == "summary"

    def test_parse_invalid_json(
        self,
        parser: ResponseParser,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing invalid JSON raises error."""
        invalid_json = "{ invalid json }"

        with pytest.raises(JSONParseError) as exc_info:
            parser.parse_from_text(invalid_json, extraction_targets)

        assert "Invalid JSON" in str(exc_info.value)

    def test_parse_missing_extractions_key(
        self,
        parser: ResponseParser,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing response missing 'extractions' key."""
        json_content = '{"results": []}'

        with pytest.raises(JSONParseError) as exc_info:
            parser.parse_from_text(json_content, extraction_targets)

        assert "extractions" in str(exc_info.value).lower()

    def test_parse_extractions_not_list(
        self,
        parser: ResponseParser,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing response where extractions is not a list."""
        json_content = '{"extractions": "not a list"}'

        with pytest.raises(JSONParseError) as exc_info:
            parser.parse_from_text(json_content, extraction_targets)

        assert "list" in str(exc_info.value).lower()

    def test_parse_missing_required_target(
        self,
        parser: ResponseParser,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing adds error for missing required target."""
        # Only return the optional target, missing required 'summary'
        json_content = """{
            "extractions": [
                {
                    "target_name": "code",
                    "success": true,
                    "content": "def test(): pass",
                    "confidence": 0.8,
                    "error": null
                }
            ]
        }"""

        results = parser.parse_from_text(json_content, extraction_targets)

        # Should have 2 results: code (from response) and summary (error)
        assert len(results) == 2

        summary_result = next(r for r in results if r.target_name == "summary")
        assert summary_result.success is False
        assert "not found" in summary_result.error.lower()

    def test_parse_ignores_unknown_targets(
        self,
        parser: ResponseParser,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing ignores targets not in the target list."""
        json_content = """{
            "extractions": [
                {
                    "target_name": "summary",
                    "success": true,
                    "content": "Test",
                    "confidence": 0.9,
                    "error": null
                },
                {
                    "target_name": "unknown_target",
                    "success": true,
                    "content": "Should be ignored",
                    "confidence": 0.5,
                    "error": null
                }
            ]
        }"""

        results = parser.parse_from_text(json_content, extraction_targets)

        # Should only have 1 result (summary) since unknown_target is ignored
        target_names = [r.target_name for r in results]
        assert "unknown_target" not in target_names
        assert "summary" in target_names

    def test_parse_extraction_without_target_name(
        self,
        parser: ResponseParser,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing skips extractions without target_name."""
        json_content = """{
            "extractions": [
                {
                    "target_name": "summary",
                    "success": true,
                    "content": "Test",
                    "confidence": 0.9,
                    "error": null
                },
                {
                    "success": true,
                    "content": "No target name",
                    "confidence": 0.5,
                    "error": null
                }
            ]
        }"""

        results = parser.parse_from_text(json_content, extraction_targets)

        # Only the valid extraction should be parsed
        valid_results = [r for r in results if r.success]
        assert len(valid_results) == 1
        assert valid_results[0].target_name == "summary"

    def test_parse_defaults_for_missing_fields(
        self,
        parser: ResponseParser,
        extraction_targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing uses defaults for missing optional fields."""
        json_content = """{
            "extractions": [
                {
                    "target_name": "summary"
                }
            ]
        }"""

        results = parser.parse_from_text(json_content, extraction_targets)

        summary = next(r for r in results if r.target_name == "summary")
        assert summary.success is True  # Default
        assert summary.confidence == 0.0  # Default
        assert summary.content is None  # Default


class TestResponseParserProviderFormats:
    """Tests for parsing different provider response formats."""

    @pytest.fixture
    def parser(self) -> ResponseParser:
        """Create test response parser."""
        return ResponseParser()

    @pytest.fixture
    def targets(self) -> list[ExtractionTarget]:
        """Create simple test targets."""
        return [
            ExtractionTarget(
                name="test",
                description="Test",
                output_format="text",
                required=True,
                examples=[],
            )
        ]

    def test_parse_anthropic_response(
        self,
        parser: ResponseParser,
        targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing Anthropic (Claude) response format."""
        # Mock Anthropic response structure
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = """{
            "extractions": [
                {
                    "target_name": "test",
                    "success": true,
                    "content": "Test result",
                    "confidence": 0.9,
                    "error": null
                }
            ]
        }"""
        mock_response.content = [mock_content]

        results = parser.parse(mock_response, targets, "anthropic")

        assert len(results) == 1
        assert results[0].target_name == "test"
        assert results[0].success is True

    def test_parse_google_response(
        self,
        parser: ResponseParser,
        targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing Google (Gemini) response format."""
        # Mock Google response structure
        mock_response = MagicMock()
        mock_response.text = """{
            "extractions": [
                {
                    "target_name": "test",
                    "success": true,
                    "content": "Test result",
                    "confidence": 0.85,
                    "error": null
                }
            ]
        }"""

        results = parser.parse(mock_response, targets, "google")

        assert len(results) == 1
        assert results[0].target_name == "test"
        assert results[0].confidence == 0.85

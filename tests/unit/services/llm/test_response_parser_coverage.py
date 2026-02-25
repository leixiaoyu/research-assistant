"""Additional coverage tests for ResponseParser module.

Phase 5.1: Coverage improvement tests for response_parser.py.
"""

import pytest
from unittest.mock import MagicMock

from src.services.llm.response_parser import ResponseParser
from src.models.extraction import ExtractionTarget


class TestResponseParserContentExtraction:
    """Tests for content extraction edge cases."""

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

    def test_extract_content_empty_anthropic_response(
        self,
        parser: ResponseParser,
    ) -> None:
        """Test extracting content from empty Anthropic response."""
        # Anthropic response with empty content list
        mock_response = MagicMock()
        mock_response.content = []

        # Use private method directly
        content = parser._extract_content(mock_response, "anthropic")

        # Should return empty string for empty content
        # Note: This tests line 117 which returns str(response.content[0].text)
        # but if content is empty, it falls through to line 123
        assert content == ""

    def test_extract_content_no_text_attribute_google(
        self,
        parser: ResponseParser,
    ) -> None:
        """Test extracting content from Google response without text attr."""
        # Google response without text attribute
        mock_response = MagicMock(spec=[])  # No attributes

        content = parser._extract_content(mock_response, "google")

        # Should return empty string (line 123)
        assert content == ""

    def test_extract_content_anthropic_no_content_attribute(
        self,
        parser: ResponseParser,
    ) -> None:
        """Test extracting content from response without content attribute."""
        # Response without content attribute at all
        mock_response = MagicMock(spec=[])

        content = parser._extract_content(mock_response, "anthropic")

        # Should return empty string (line 123)
        assert content == ""

    def test_extract_content_google_no_text_attribute(
        self,
        parser: ResponseParser,
    ) -> None:
        """Test Google response without text returns empty."""
        mock_response = MagicMock()
        # Remove text attribute
        del mock_response.text

        content = parser._extract_content(mock_response, "google")

        assert content == ""


class TestResponseParserCodeBlockCleaning:
    """Tests for code block cleaning edge cases."""

    @pytest.fixture
    def parser(self) -> ResponseParser:
        """Create test response parser."""
        return ResponseParser()

    def test_clean_json_content_plain_code_block(
        self,
        parser: ResponseParser,
    ) -> None:
        """Test cleaning plain code block without json specifier."""
        # Code block without 'json' specifier (line 139-140)
        content = """```
{
    "extractions": []
}
```"""

        cleaned = parser._clean_json_content(content)

        # Should strip the ``` markers
        assert cleaned == '{\n    "extractions": []\n}'
        assert "```" not in cleaned

    def test_clean_json_content_with_json_specifier(
        self,
        parser: ResponseParser,
    ) -> None:
        """Test cleaning code block with json specifier."""
        content = """```json
{
    "extractions": []
}
```"""

        cleaned = parser._clean_json_content(content)

        assert cleaned == '{\n    "extractions": []\n}'
        assert "```json" not in cleaned
        assert "```" not in cleaned

    def test_clean_json_content_no_code_blocks(
        self,
        parser: ResponseParser,
    ) -> None:
        """Test cleaning content without code blocks."""
        content = '{"extractions": []}'

        cleaned = parser._clean_json_content(content)

        assert cleaned == '{"extractions": []}'

    def test_clean_json_content_with_whitespace(
        self,
        parser: ResponseParser,
    ) -> None:
        """Test cleaning content with surrounding whitespace."""
        content = """

   {"extractions": []}

   """

        cleaned = parser._clean_json_content(content)

        assert cleaned == '{"extractions": []}'


class TestResponseParserFullParse:
    """Tests for full parse method with various response types."""

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

    def test_parse_with_llm_response_object(
        self,
        parser: ResponseParser,
        targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing LLMResponse object directly."""
        from src.services.llm.providers.base import LLMResponse

        json_content = """{
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

        response = LLMResponse(
            content=json_content,
            input_tokens=100,
            output_tokens=50,
            model="test-model",
            provider="anthropic",
            latency_ms=150.0,
        )

        results = parser.parse(response, targets, "anthropic")

        assert len(results) == 1
        assert results[0].target_name == "test"
        assert results[0].success is True

    def test_parse_anthropic_empty_content_list(
        self,
        parser: ResponseParser,
        targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing Anthropic response with empty content list."""
        from src.utils.exceptions import JSONParseError

        mock_response = MagicMock()
        mock_response.content = []  # Empty content list

        # This should raise JSONParseError because empty string is not valid JSON
        with pytest.raises(JSONParseError):
            parser.parse(mock_response, targets, "anthropic")

    def test_parse_google_no_text_attribute(
        self,
        parser: ResponseParser,
        targets: list[ExtractionTarget],
    ) -> None:
        """Test parsing Google response without text attribute."""
        from src.utils.exceptions import JSONParseError

        mock_response = MagicMock(spec=["other_attr"])  # No text or content

        # This should raise JSONParseError because empty string is not valid JSON
        with pytest.raises(JSONParseError):
            parser.parse(mock_response, targets, "google")

"""Response Parser Module

Phase 5.1: Extracted JSON response parsing logic from LLMService.

This module handles:
- Parsing LLM JSON responses
- Validating against expected schema
- Handling malformed responses gracefully
- Creating ExtractionResult objects
"""

import json
from typing import List, Any, Set
import structlog

from src.models.extraction import ExtractionTarget, ExtractionResult
from src.utils.exceptions import JSONParseError

logger = structlog.get_logger()


class ResponseParser:
    """Parses LLM responses into structured extraction results.

    This class is responsible for:
    - Extracting JSON from LLM responses (handling code blocks)
    - Validating the response structure
    - Creating ExtractionResult objects
    - Handling missing required targets
    """

    def parse(
        self,
        response: Any,
        targets: List[ExtractionTarget],
        provider: str,
    ) -> List[ExtractionResult]:
        """Parse LLM response into extraction results.

        Args:
            response: Raw LLM response object
            targets: List of extraction targets
            provider: Provider name (anthropic, google)

        Returns:
            List of ExtractionResult objects

        Raises:
            JSONParseError: If response cannot be parsed as valid JSON
        """
        # Extract text content based on provider
        content = self._extract_content(response, provider)

        # Clean up JSON (remove code blocks)
        content = self._clean_json_content(content)

        # Parse JSON
        data = self._parse_json(content)

        # Validate structure
        extractions = self._validate_structure(data)

        # Build results
        results = self._build_results(extractions, targets)

        logger.debug(
            "response_parsed",
            provider=provider,
            extractions_found=len(results),
            targets_count=len(targets),
        )

        return results

    def parse_from_text(
        self,
        text: str,
        targets: List[ExtractionTarget],
    ) -> List[ExtractionResult]:
        """Parse text content directly into extraction results.

        This is useful when you already have the text content
        extracted from the response.

        Args:
            text: Text content (potentially with JSON)
            targets: List of extraction targets

        Returns:
            List of ExtractionResult objects

        Raises:
            JSONParseError: If content cannot be parsed as valid JSON
        """
        content = self._clean_json_content(text)
        data = self._parse_json(content)
        extractions = self._validate_structure(data)
        return self._build_results(extractions, targets)

    def _extract_content(self, response: Any, provider: str) -> str:
        """Extract text content from provider response.

        Args:
            response: Raw response object or LLMResponse
            provider: Provider name

        Returns:
            Text content string
        """
        # Check if this is an LLMResponse dataclass (has content as string)
        if hasattr(response, "content") and isinstance(response.content, str):
            return response.content

        if provider == "anthropic":
            # Anthropic: response.content[0].text
            if hasattr(response, "content") and response.content:
                return str(response.content[0].text)
        else:
            # Google: response.text
            if hasattr(response, "text"):
                return str(response.text)

        return ""

    def _clean_json_content(self, content: str) -> str:
        """Clean JSON content by removing code block markers.

        Args:
            content: Raw content string

        Returns:
            Cleaned content string
        """
        content = content.strip()

        # Remove ```json prefix
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]

        # Remove ``` suffix
        if content.endswith("```"):
            content = content[:-3]

        return content.strip()

    def _parse_json(self, content: str) -> dict[str, Any]:
        """Parse JSON content.

        Args:
            content: Cleaned JSON string

        Returns:
            Parsed dictionary

        Raises:
            JSONParseError: If JSON is invalid
        """
        try:
            result: dict[str, Any] = json.loads(content)
            return result
        except json.JSONDecodeError as e:
            raise JSONParseError(
                f"Invalid JSON in LLM response: {e}\nContent: {content[:500]}"
            )

    def _validate_structure(self, data: dict) -> list:
        """Validate response structure.

        Args:
            data: Parsed JSON data

        Returns:
            List of extraction dictionaries

        Raises:
            JSONParseError: If structure is invalid
        """
        if "extractions" not in data:
            raise JSONParseError("Missing 'extractions' key in response")

        extractions = data["extractions"]
        if not isinstance(extractions, list):
            raise JSONParseError("'extractions' must be a list")

        return extractions

    def _build_results(
        self,
        extractions: list,
        targets: List[ExtractionTarget],
    ) -> List[ExtractionResult]:
        """Build ExtractionResult objects from parsed data.

        Args:
            extractions: List of extraction dictionaries
            targets: Original extraction targets

        Returns:
            List of ExtractionResult objects
        """
        results: List[ExtractionResult] = []
        target_names: Set[str] = {t.name for t in targets}

        for ext in extractions:
            if "target_name" not in ext:
                logger.warning("extraction_missing_target_name", extraction=ext)
                continue

            target_name = ext["target_name"]
            if target_name not in target_names:
                logger.warning("extraction_unknown_target", target_name=target_name)
                continue

            results.append(
                ExtractionResult(
                    target_name=target_name,
                    success=ext.get("success", True),
                    content=ext.get("content"),
                    confidence=ext.get("confidence", 0.0),
                    error=ext.get("error"),
                )
            )

        # Check for missing required targets
        extracted_names: Set[str] = {r.target_name for r in results}
        for target in targets:
            if target.required and target.name not in extracted_names:
                logger.error("required_target_missing", target_name=target.name)
                results.append(
                    ExtractionResult(
                        target_name=target.name,
                        success=False,
                        content=None,
                        confidence=0.0,
                        error="Required target not found in LLM response",
                    )
                )

        return results

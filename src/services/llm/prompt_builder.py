"""Prompt Builder Module

Phase 5.1: Extracted prompt construction logic from LLMService.

This module handles:
- Building structured extraction prompts
- Formatting paper metadata for context
- Generating JSON schema instructions
"""

import json
from typing import List
import structlog

from src.models.extraction import ExtractionTarget
from src.models.paper import PaperMetadata

logger = structlog.get_logger()


class PromptBuilder:
    """Builds structured extraction prompts for LLM.

    This class is responsible for constructing well-formatted prompts
    that guide the LLM to extract specific information from papers.
    The prompts include:
    - Paper metadata for context
    - Extraction target specifications
    - JSON schema for structured output
    - Clear instructions for extraction
    """

    def build(
        self,
        markdown_content: str,
        targets: List[ExtractionTarget],
        paper_metadata: PaperMetadata,
    ) -> str:
        """Build extraction prompt for LLM.

        Args:
            markdown_content: Full paper content in markdown format
            targets: List of extraction targets
            paper_metadata: Paper metadata for context

        Returns:
            Formatted prompt string
        """
        # Format targets as JSON for clear specification
        targets_json = self._format_targets(targets)

        # Format author names
        author_names = self._format_authors(paper_metadata)

        # Build the complete prompt
        prompt = self._build_prompt_template(
            markdown=markdown_content,
            targets_json=targets_json,
            author_names=author_names,
            metadata=paper_metadata,
        )

        logger.debug(
            "prompt_built",
            paper_id=paper_metadata.paper_id,
            targets_count=len(targets),
            prompt_length=len(prompt),
        )

        return prompt

    def _format_targets(self, targets: List[ExtractionTarget]) -> str:
        """Format extraction targets as JSON.

        Args:
            targets: List of extraction targets

        Returns:
            JSON string of target specifications
        """
        targets_data = [
            {
                "name": t.name,
                "description": t.description,
                "output_format": t.output_format,
                "required": t.required,
                "examples": t.examples,
            }
            for t in targets
        ]
        return json.dumps(targets_data, indent=2)

    def _format_authors(self, metadata: PaperMetadata) -> str:
        """Format author names from metadata.

        Args:
            metadata: Paper metadata

        Returns:
            Comma-separated author names or 'Unknown'
        """
        if not metadata.authors:
            return "Unknown"
        return ", ".join(a.name for a in metadata.authors)

    def _build_prompt_template(
        self,
        markdown: str,
        targets_json: str,
        author_names: str,
        metadata: PaperMetadata,
    ) -> str:
        """Build the complete prompt from template.

        Args:
            markdown: Paper content
            targets_json: Formatted targets
            author_names: Formatted authors
            metadata: Paper metadata

        Returns:
            Complete prompt string
        """
        # This template matches the original exactly for behavioral equivalence
        prompt = f"""You are a research paper analyst specialized in
extracting structured information from academic papers.

**Paper Metadata:**
- Title: {metadata.title}
- Authors: {author_names}
- Year: {metadata.year or 'Unknown'}
- Paper ID: {metadata.paper_id}

**Extraction Targets:**
{targets_json}

**Instructions:**
1. Read the paper content carefully
2. For each extraction target, extract the requested information
3. Follow the specified output_format for each target (text, code, json, list)
4. If a target cannot be found and is NOT required, return null for content
5. If a target is required and not found, set success=false with an error message
6. Provide a confidence score (0.0-1.0) for each extraction
7. Return ONLY valid JSON with NO additional text before or after

**Required JSON Structure:**
{{
  "extractions": [
    {{
      "target_name": "string",
      "success": boolean,
      "content": any,
      "confidence": float,
      "error": "string or null"
    }}
  ]
}}

**Paper Content:**

{markdown}

**Now extract the information and return ONLY the JSON response:**"""

        return prompt

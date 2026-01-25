"""Extraction data models for Phase 2: PDF Processing & LLM Extraction

This module defines the data structures for:
- Extraction targets (what to extract from papers)
- Extraction results (extracted content)
- Paper extractions (complete extraction for a paper)
- Extracted papers (papers with metadata and extractions)
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime

from src.models.paper import PaperMetadata


class ExtractionTarget(BaseModel):
    """Definition of what to extract from a paper

    Examples:
        - Extract system prompts used in the paper
        - Extract code snippets implementing the methodology
        - Extract evaluation metrics and benchmarks
    """

    name: str = Field(
        ...,
        description="Unique name for this extraction target (e.g., 'system_prompts')",
        min_length=1,
    )
    description: str = Field(
        ..., description="Clear description of what to extract", min_length=1
    )
    output_format: Literal["text", "code", "json", "list"] = Field(
        default="text", description="Expected format of extracted content"
    )
    required: bool = Field(
        default=False, description="Whether extraction must succeed (fail if not found)"
    )
    examples: Optional[List[str]] = Field(
        default=None, description="Example extractions to guide the LLM"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "system_prompts",
                "description": "Extract all LLM system prompts used in the paper",
                "output_format": "list",
                "required": False,
                "examples": ["You are a helpful AI assistant..."],
            }
        }
    )


class ExtractionResult(BaseModel):
    """Result of extracting a single target from a paper

    Contains the extracted content, success status, and confidence level.
    """

    target_name: str = Field(..., description="Name of the extraction target")
    success: bool = Field(..., description="Whether extraction succeeded")
    content: Any = Field(
        default=None,
        description="Extracted content (format depends on target's output_format)",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="LLM confidence in extraction (0.0-1.0)",
    )
    error: Optional[str] = Field(
        default=None, description="Error message if extraction failed"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "target_name": "system_prompts",
                "success": True,
                "content": [
                    "You are a helpful AI assistant...",
                    "You are an expert translator...",
                ],
                "confidence": 0.95,
                "error": None,
            }
        }
    )


class PaperExtraction(BaseModel):
    """Complete extraction results for a single paper

    Tracks all extraction results, token usage, cost, and timestamp.
    """

    paper_id: str = Field(..., description="Unique paper identifier")
    extraction_results: List[ExtractionResult] = Field(
        default_factory=list, description="Results for each extraction target"
    )
    tokens_used: int = Field(
        default=0, ge=0, description="Total tokens consumed by LLM"
    )
    cost_usd: float = Field(default=0.0, ge=0.0, description="Total cost in USD")
    extraction_timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="When extraction was performed"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "paper_id": "2301.12345",
                "extraction_results": [],
                "tokens_used": 45000,
                "cost_usd": 0.15,
                "extraction_timestamp": "2025-01-24T10:00:00Z",
            }
        }
    )


class ExtractedPaper(BaseModel):
    """Paper with metadata, PDF status, and extraction results

    This is the complete representation of a processed paper including:
    - Original metadata (title, authors, etc.)
    - PDF availability and paths
    - Extraction results from LLM
    """

    metadata: PaperMetadata = Field(..., description="Original paper metadata")
    pdf_available: bool = Field(
        default=False, description="Whether PDF was successfully downloaded"
    )
    pdf_path: Optional[str] = Field(
        default=None, description="Path to downloaded PDF file"
    )
    markdown_path: Optional[str] = Field(
        default=None, description="Path to converted markdown file"
    )
    extraction: Optional[PaperExtraction] = Field(
        default=None, description="LLM extraction results"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "metadata": {
                    "paper_id": "2301.12345",
                    "title": "Sample Paper",
                    "abstract": "This is a sample abstract...",
                    "authors": [{"name": "John Doe"}],
                    "year": 2023,
                },
                "pdf_available": True,
                "pdf_path": "/temp/pdfs/2301.12345.pdf",
                "markdown_path": "/temp/markdown/2301.12345.md",
                "extraction": None,
            }
        }
    )

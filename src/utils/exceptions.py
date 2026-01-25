"""Custom exceptions for Phase 2: PDF Processing & LLM Extraction

This module defines the exception hierarchy for the extraction pipeline:
- Base exception for all pipeline errors
- Specific exceptions for each stage (PDF, conversion, LLM, cost)

All exceptions inherit from PipelineError to allow catching all pipeline-related
errors in a single except block when needed.
"""


class PipelineError(Exception):
    """Base exception for all pipeline errors

    Use this to catch any error in the extraction pipeline:
    ```python
    try:
        await extraction_service.process_paper(paper, targets)
    except PipelineError as e:
        logger.error("Pipeline failed", error=str(e))
    ```
    """

    pass


class PDFDownloadError(PipelineError):
    """PDF download failed after retries

    Raised when:
    - HTTP request fails (non-200 status)
    - Network timeout
    - Connection errors
    - All retry attempts exhausted
    """

    pass


class FileSizeError(PipelineError):
    """File size exceeds maximum allowed

    Raised when:
    - PDF file is larger than configured max_file_size_mb
    - Prevents downloading excessively large files

    This is a non-retryable error as the file size won't change.
    """

    pass


class PDFValidationError(PipelineError):
    """PDF file validation failed

    Raised when:
    - File is empty (0 bytes)
    - File doesn't have PDF magic bytes (%PDF)
    - File is corrupted or invalid
    """

    pass


class ConversionError(PipelineError):
    """PDF to markdown conversion failed

    Raised when:
    - marker-pdf command fails
    - Conversion timeout
    - No markdown file generated
    - marker-pdf crashes
    """

    pass


class ExtractionError(PipelineError):
    """LLM extraction failed

    Raised when:
    - LLM API call fails
    - Response parsing fails
    - Invalid JSON in LLM response
    - Required extraction target not found
    """

    pass


class CostLimitExceeded(PipelineError):
    """Budget limit exceeded

    Raised when:
    - Daily spending limit reached
    - Total spending limit reached
    - Per-paper token limit would be exceeded

    This prevents runaway costs by failing fast when budgets are exhausted.
    """

    pass


class LLMAPIError(ExtractionError):
    """LLM API call failed

    Raised when:
    - API returns error status
    - API timeout
    - Rate limit exceeded (429)
    - Authentication failed (401)
    """

    pass


class JSONParseError(ExtractionError):
    """Failed to parse LLM JSON response

    Raised when:
    - LLM response is not valid JSON
    - JSON structure doesn't match expected schema
    - Missing required fields in extraction results
    """

    pass

# Proposal 002: PDF Extraction Reliability Strategy (Phase 2.5)

**Author:** Gemini CLI
**Date:** 2026-01-26
**Status:** Review
**Related Spec:** [Phase 2.5 Specification](../specs/PHASE_2.5_SPEC.md)

## 1. Background & Problem Statement

Phase 2 successfully integrated `marker-pdf` for converting PDFs to Markdown. However, production testing and research have identified critical reliability issues that threaten the stability of the research assistant:

*   **Instability:** `marker-pdf` relies on heavy ML models that can cause segmentation faults and crashes, particularly on Apple Silicon and non-GPU environments.
*   **Performance:** Model loading introduces significant cold-start latency (2-3 minutes) and high memory usage (4-8GB).
*   **Timeouts:** Processing large papers often exceeds reasonable timeout limits.
*   **Single Point of Failure:** Currently, if `marker-pdf` fails, the system falls back immediately to abstract-only, losing valuable content like code snippets and tables.

## 2. Requirements

### 2.1 Functional Requirements
*   **Reliability:** Achieve ≥95% PDF-to-Markdown conversion success rate on arXiv papers.
*   **Performance:** Process average papers (15-20 pages) in <10 seconds.
*   **Fidelity:** Preserve code blocks and tables whenever possible.
*   **Fallback:** Automatically degrade to alternative extractors if the primary fails or produces low-quality output.

### 2.2 Non-Functional Requirements
*   **Security:** Prevent command injection (pandoc) and path traversal attacks.
*   **Resource Efficiency:** Eliminate mandatory ML model downloads (reduce footprint by ~1.5GB).
*   **Maintainability:** Use standard Pydantic models and strict typing.

## 3. Proposed Solution: Multi-Backend Fallback Architecture

We propose moving from a single extraction engine to a **Fallback Chain** architecture. This system will attempt extraction using a prioritized list of backends, validated by a quality scoring system.

### 3.1 Backend Selection

Based on our benchmarking research (see `tests/research/BACKEND_SELECTION.md`), we have selected the following backends:

| Priority | Backend | Role | Pros | Cons |
|:---:|:---|:---|:---|:---|
| **1** | **PyMuPDF (fitz)** | **Primary** | ⚡️ Extremely fast (1s/paper)<br>🛡️ High reliability (No ML)<br>📦 Lightweight | No built-in semantic analysis |
| **2** | **pdfplumber** | **Secondary** | 📊 Excellent table extraction<br>🛡️ Reliable Python-native | Slower than PyMuPDF |
| **3** | **marker-pdf** | **Tertiary** | 🧠 High semantic fidelity<br>🧮 Good equation support | Unstable, Slow, Heavy |
| **4** | **pandoc** | **Fallback** | 🛡️ Robust system utility | Basic text only |

### 3.2 Architecture Components

1.  **Orchestrator (`FallbackPDFService`)**: Manages the extraction chain and quality validation.
2.  **Extractors**: Implement a common `PDFExtractor` interface.
3.  **Validator**: `QualityValidator` scores output to determine if fallback is needed.

### 3.3 Fallback Chain Configuration

The chain will be configurable in `research_config.yaml`:

```yaml
pdf_settings:
  fallback_chain:
    - backend: pymupdf
      timeout_seconds: 30
      min_quality: 0.5

    - backend: pdfplumber
      timeout_seconds: 45
      min_quality: 0.5

    - backend: marker
      timeout_seconds: 300
      min_quality: 0.7  # Higher threshold due to cost
      enabled: false    # Disabled by default

    - backend: pandoc
      timeout_seconds: 60
      min_quality: 0.3  # Last resort

  stop_on_success: true # Stop after first success >= min_quality
```

### 3.4 Quality Scoring Algorithm

The `QualityValidator` calculates a score (0.0 - 1.0) using this weighted formula:

```python
quality_score = (
    0.40 * text_density_score +      # Text length vs page count
    0.30 * structure_score +         # Headers, lists, formatting
    0.15 * code_detection_score +    # Code blocks found
    0.15 * table_detection_score     # Tables found
)
```

**Thresholds:**
*   `MIN_QUALITY_SCORE`: 0.5 (Accept first result ≥0.5)
*   `POOR_QUALITY`: <0.3 (Immediate fallback)

## 4. Data Models

We will define strict Pydantic models for the extraction process:

```python
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

class PDFBackend(str, Enum):
    """PDF extraction backend identifier"""
    PYMUPDF = "pymupdf"
    PDFPLUMBER = "pdfplumber"
    MARKER = "marker"
    PANDOC = "pandoc"
    TEXT_ONLY = "text_only"

class ExtractionMetadata(BaseModel):
    """Metadata about PDF extraction process"""
    backend: PDFBackend
    duration_seconds: float = Field(ge=0.0)
    page_count: int = Field(ge=0)
    file_size_bytes: int = Field(ge=0)
    
    # Quality indicators
    text_length: int = Field(ge=0)
    code_blocks_found: int = Field(0, ge=0)
    tables_found: int = Field(0, ge=0)

class PDFExtractionResult(BaseModel):
    """Result of PDF extraction with quality metrics"""
    success: bool
    markdown: Optional[str] = None
    metadata: ExtractionMetadata
    quality_score: float = Field(ge=0.0, le=1.0)
    error: Optional[str] = None
```

## 5. Security Analysis

### 5.1 Input Validation
*   **Path Sanitization:** All PDF paths will be validated using `PathSanitizer` (or `Path.resolve()`) to prevent directory traversal.
*   **File Validation:** PDF magic bytes (`%PDF`) must be verified before processing.
*   **Size Limits:** Enforce 50MB limit to prevent DoS.

### 5.2 Command Injection Prevention
**Risk:** The `PandocExtractor` executes an external subprocess.
**Mitigation:**
*   NEVER use `shell=True`.
*   Use `subprocess.run(["pandoc", str(safe_path), ...])` passing arguments as a list.
*   Validate `pandoc` binary path availability.

### 5.3 Resource Limits
*   **Timeouts:** Each backend has a strict timeout (default 60s) using `asyncio.wait_for`.
*   **Concurrency:** Phase 3 will introduce semaphores, but Phase 2.5 remains sequential for safety.
*   **Cleanup:** Temporary files are created in isolated `tempfile.mkdtemp` directories and cleaned up via `try...finally` blocks.

## 6. Testing Strategy

### 6.1 Unit Tests (`src/tests/unit/pdf_extractors/`)
*   **`test_pymupdf_extractor.py`**: Test text/code/table extraction, mock failures.
*   **`test_quality_validator.py`**: Test scoring logic against sample markdown strings.
*   **`test_fallback_service.py`**:
    *   Test chain progression (Primary fails -> Secondary runs).
    *   Test quality threshold logic (Primary low quality -> Secondary runs).
    *   Test complete failure (All fail -> Abstract fallback).

### 6.2 Integration Tests (`src/tests/integration/`)
*   **Dataset**: 20 benchmark arXiv PDFs (already gathered in research phase).
*   **`test_pdf_pipeline_e2e.py`**:
    *   Verify success rate > 95%.
    *   Verify average speed < 30s.
    *   Verify code block preservation.

## 7. Implementation Timeline

**Total Duration:** 7 Days

*   **Day 1:** Core Infrastructure
    *   `PDFExtractor` abstract base class.
    *   Data models (`PDFExtractionResult`, etc.).
    *   `QualityValidator` implementation & tests.
*   **Day 2:** Primary Backend
    *   `PyMuPDFExtractor` implementation & tests.
*   **Day 3:** Secondary/Fallback Backends
    *   `PDFPlumberExtractor` implementation.
    *   `PandocExtractor` implementation (with security controls).
*   **Day 4:** Fallback Service
    *   `FallbackPDFService` logic (chaining, scoring).
    *   Configuration updates.
*   **Day 5:** Integration
    *   Update `ExtractionService` to use `FallbackPDFService`.
    *   Update `PDFService` to handle download-only (separation of concerns).
*   **Day 6-7:** Validation & Docs
    *   Integration tests with benchmark dataset.
    *   Performance verification.
    *   Documentation updates.

## 8. Rollback Plan

This feature uses a new service class (`FallbackPDFService`). If major issues occur:
1.  Revert `ExtractionService` to use the original `PDFService` logic.
2.  Disable `fallback_chain` in configuration.

## 9. Recommendation

Proceed with implementation immediately. The research phase has validated PyMuPDF as a viable primary candidate, effectively solving the current stability blocking issue.
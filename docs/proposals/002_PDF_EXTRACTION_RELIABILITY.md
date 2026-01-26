# Proposal 002: PDF Extraction Reliability Strategy (Phase 2.5)

**Author:** Gemini CLI
**Date:** 2026-01-26
**Status:** Draft
**Related Spec:** [Phase 2.5 Specification](../specs/PHASE_2.5_SPEC.md)

## 1. Problem Statement

Phase 2 successfully integrated `marker-pdf` for converting PDFs to Markdown. However, production testing and research have identified critical reliability issues that threaten the stability of the research assistant:

*   **Instability:** `marker-pdf` relies on heavy ML models that can cause segmentation faults and crashes, particularly on Apple Silicon and non-GPU environments.
*   **Performance:** Model loading introduces significant cold-start latency (2-3 minutes) and high memory usage (4-8GB).
*   **Timeouts:** Processing large papers often exceeds reasonable timeout limits.
*   **Single Point of Failure:** Currently, if `marker-pdf` fails, the system falls back immediately to abstract-only, losing valuable content like code snippets and tables.

## 2. Proposed Solution: Multi-Backend Fallback Architecture

We propose moving from a single extraction engine to a **Fallback Chain** architecture. This system will attempt extraction using a prioritized list of backends, validated by a quality scoring system.

### 2.1 Selected Backends

Based on our benchmarking research (see `tests/research/BACKEND_SELECTION.md`), we have selected the following backends:

| Priority | Backend | Role | Pros | Cons |
|:---:|:---|:---|:---|:---|
| **1** | **PyMuPDF (fitz)** | **Primary** | ⚡️ Extremely fast (1s/paper)<br>🛡️ High reliability (No ML)<br>📦 Lightweight | No built-in semantic analysis |
| **2** | **pdfplumber** | **Secondary** | 📊 Excellent table extraction<br>🛡️ Reliable Python-native | Slower than PyMuPDF |
| **3** | **marker-pdf** | **Tertiary** | 🧠 High semantic fidelity<br>🧮 Good equation support | Unstable, Slow, Heavy |
| **4** | **pandoc** | **Fallback** | 🛡️ Robust system utility | Basic text only |

### 2.2 Architecture Design

We will introduce a `FallbackPDFService` that orchestrates the extraction process:

1.  **Orchestration**: The service iterates through the `FALLBACK_CHAIN`.
2.  **Extraction**: Each backend implements a common `PDFExtractor` interface.
3.  **Validation**: A `QualityValidator` scores the output (0.0 - 1.0) based on:
    *   Text length vs. page count
    *   Structural elements (headers, lists)
    *   Code block detection
    *   Table detection
4.  **Selection**: The service accepts the first result that meets the `MIN_QUALITY_SCORE` (default 0.5) or picks the best available result if all fail.

### 2.3 Graceful Degradation Strategy

The system will degrade gracefully across three levels:

1.  **Level 1 (Ideal)**: High-quality Markdown with code blocks and tables (PyMuPDF/pdfplumber success).
2.  **Level 2 (Acceptable)**: Text-heavy Markdown (Pandoc success).
3.  **Level 3 (Fail-safe)**: Abstract & Metadata only (All extractors failed).

## 3. Implementation Plan

The implementation will follow the Phase 2.5 Specification:

1.  **Core Infrastructure**:
    *   `PDFExtractor` abstract base class.
    *   `PDFExtractionResult` and `ExtractionMetadata` models.
    *   `QualityValidator` implementation.

2.  **Backend Implementation**:
    *   `PyMuPDFExtractor` (Completed in research).
    *   `PDFPlumberExtractor`.
    *   `PandocExtractor`.
    *   `MarkerExtractor` (Adapter for existing logic).

3.  **Service Layer**:
    *   `FallbackPDFService` to manage the chain.
    *   Integration into the main `ExtractionService`.

4.  **Validation**:
    *   Unit tests for all extractors.
    *   Integration tests with the benchmark dataset.

## 4. Pros/Cons Analysis

**Pros:**
*   **Reliability**: Removes the single point of failure.
*   **Speed**: Primary path (PyMuPDF) is ~10x faster than marker-pdf.
*   **Efficiency**: Reduces default memory footprint by gigabytes.
*   **Experience**: Users get results faster with higher success rates.

**Cons:**
*   **Complexity**: Managing multiple dependencies and code paths.
*   **Consistency**: Markdown output format may vary slightly between backends (mitigated by common post-processing).

## 5. Recommendation

We recommend proceeding immediately with the implementation of this architecture. The prototype research has already validated the effectiveness of PyMuPDF as a primary replacement, solving the immediate stability concerns.

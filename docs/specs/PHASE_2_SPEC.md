# Phase 2: PDF Processing & LLM Extraction
**Version:** 1.0
**Status:** Draft
**Timeline:** 2 weeks
**Dependencies:** Phase 1 Complete

## Overview

Extend the pipeline to download PDFs, convert them to markdown using marker-pdf, and extract structured information using LLM (Claude or Gemini). This phase adds the core value proposition of the system: intelligent extraction of prompts, code, and insights from research papers.

## Objectives

### Primary Objectives
1. ✅ Implement PDF download with retry and validation
2. ✅ Integrate marker-pdf for PDF to Markdown conversion
3. ✅ Implement LLM integration (Claude 3.5 Sonnet / Gemini 1.5 Pro)
4. ✅ Support configurable extraction targets per topic
5. ✅ Generate enhanced output with extracted content
6. ✅ Implement robust error handling and fallback strategies

### Success Criteria
- [ ] Can download PDFs from open access links
- [ ] Can convert PDFs to markdown preserving code formatting
- [ ] Can extract configurable targets using LLM
- [ ] Can handle papers without PDFs (abstract-only mode)
- [ ] Can recover from partial failures
- [ ] Output includes extracted prompts, code, and summaries
- [ ] LLM costs stay within budget limits

## Architecture Additions

### Updated Module Structure
```
research-assist/
├── src/
│   ├── models/
│   │   ├── extraction.py        # NEW: Extraction models
│   │   └── llm.py               # NEW: LLM models
│   ├── services/
│   │   ├── pdf_service.py       # NEW: PDF download/conversion
│   │   ├── llm_service.py       # NEW: LLM extraction
│   │   └── extraction_service.py # NEW: Orchestrate extraction
│   ├── output/
│   │   └── enhanced_generator.py # UPDATED: Include extractions
│   └── utils/
│       ├── file_utils.py        # NEW: File operations
│       └── retry.py             # NEW: Retry logic
├── temp/                         # NEW: Temporary files
│   ├── pdfs/
│   └── markdown/
└── config/
    └── extraction_config.yaml   # NEW: Extraction templates
```

## Technical Specifications

### 1. Data Models

#### 1.1 Extraction Models (`src/models/extraction.py`)
```python
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal

class ExtractionTarget(BaseModel):
    """Definition of what to extract from a paper"""
    name: str = Field(..., description="Unique name for this extraction target")
    description: str = Field(..., description="What to extract")
    output_format: Literal["text", "code", "json", "list"] = "text"
    required: bool = Field(False, description="Fail if not found")
    examples: Optional[List[str]] = Field(None, description="Example extractions")

class ExtractionResult(BaseModel):
    """Result of extracting a single target"""
    target_name: str
    success: bool
    content: Any  # str, list, dict depending on output_format
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    error: Optional[str] = None

class PaperExtraction(BaseModel):
    """Complete extraction for a single paper"""
    paper_id: str
    extraction_results: List[ExtractionResult]
    tokens_used: int = 0
    cost_usd: float = 0.0
    extraction_timestamp: datetime

class ExtractedPaper(BaseModel):
    """Paper with metadata and extractions"""
    metadata: PaperMetadata
    pdf_available: bool
    pdf_path: Optional[str] = None
    markdown_path: Optional[str] = None
    extraction: Optional[PaperExtraction] = None
```

#### 1.2 LLM Models (`src/models/llm.py`)
```python
from pydantic import BaseModel, Field
from typing import Literal, Optional

class LLMConfig(BaseModel):
    """LLM provider configuration"""
    provider: Literal["anthropic", "google"] = "anthropic"
    model: str = "claude-3-5-sonnet-20250122"
    api_key: str
    max_tokens: int = Field(100000, description="Max tokens per paper")
    temperature: float = Field(0.0, ge=0.0, le=1.0)
    timeout: int = Field(300, description="Timeout in seconds")

class CostLimits(BaseModel):
    """Cost control configuration"""
    max_tokens_per_paper: int = 100000
    max_daily_spend_usd: float = 50.0
    max_total_spend_usd: float = 500.0

class UsageStats(BaseModel):
    """Track LLM usage"""
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    papers_processed: int = 0
    last_reset: datetime = Field(default_factory=datetime.utcnow)
```

### 2. Updated Research Config

```yaml
# config/research_config.yaml
research_topics:
  - query: "Tree of Thoughts AND machine translation"
    timeframe:
      type: "recent"
      value: "48h"
    max_papers: 50
    # NEW: Extraction configuration
    extraction_targets:
      - name: "system_prompts"
        description: "Extract all LLM system prompts used in the paper"
        output_format: "list"
        required: false
      - name: "user_prompts"
        description: "Extract example user prompts or prompt templates"
        output_format: "list"
        required: false
      - name: "code_snippets"
        description: "Extract Python code implementing the methodology"
        output_format: "code"
        required: false
      - name: "evaluation_metrics"
        description: "Extract benchmark results and performance metrics"
        output_format: "json"
        required: false
      - name: "engineering_summary"
        description: "Write a 2-paragraph summary for engineering teams"
        output_format: "text"
        required: true

settings:
  output_base_dir: "./output"
  enable_duplicate_detection: true
  semantic_scholar_api_key: "${SEMANTIC_SCHOLAR_API_KEY}"

  # NEW: PDF and LLM settings
  pdf_settings:
    temp_dir: "./temp"
    keep_pdfs: true
    max_file_size_mb: 50
    timeout_seconds: 300

  llm_settings:
    provider: "anthropic"
    model: "claude-3-5-sonnet-20250122"
    api_key: "${LLM_API_KEY}"
    max_tokens: 100000
    temperature: 0.0

  cost_limits:
    max_tokens_per_paper: 100000
    max_daily_spend_usd: 50.0
```

### 3. PDF Service (`src/services/pdf_service.py`)

**Responsibilities:**
- Download PDFs with retry logic
- Validate PDF files
- Convert PDF to markdown using marker-pdf
- Clean up temporary files

**Key Functions:**
```python
from tenacity import retry, stop_after_attempt, wait_exponential
import aiohttp
import subprocess
from pathlib import Path

class PDFService:
    def __init__(self, temp_dir: Path, max_size_mb: int = 50):
        """Initialize PDF service"""
        self.temp_dir = temp_dir
        self.max_size_bytes = max_size_mb * 1024 * 1024

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def download_pdf(
        self,
        url: str,
        output_path: Path,
        timeout: int = 300
    ) -> bool:
        """Download PDF from URL

        Returns:
            True if successful, False otherwise

        Raises:
            PDFDownloadError: If download fails after retries
            FileSizeError: If PDF exceeds max size
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    raise PDFDownloadError(f"HTTP {response.status}")

                # Check size before downloading
                size = int(response.headers.get('content-length', 0))
                if size > self.max_size_bytes:
                    raise FileSizeError(f"PDF too large: {size} bytes")

                # Stream download
                with open(output_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)

                return True

    def convert_to_markdown(
        self,
        pdf_path: Path,
        output_dir: Path
    ) -> Path:
        """Convert PDF to markdown using marker-pdf

        Returns:
            Path to generated markdown file

        Raises:
            ConversionError: If marker-pdf fails
        """
        # Run marker_single
        cmd = [
            "marker_single",
            str(pdf_path),
            "--output_dir", str(output_dir),
            "--batch_multiplier", "2"  # For better quality
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                check=True
            )

            # Find generated markdown file
            md_files = list(output_dir.glob("*.md"))
            if not md_files:
                raise ConversionError("No markdown file generated")

            return md_files[0]

        except subprocess.TimeoutExpired:
            raise ConversionError("Conversion timeout")
        except subprocess.CalledProcessError as e:
            raise ConversionError(f"marker-pdf failed: {e.stderr}")

    def validate_pdf(self, pdf_path: Path) -> bool:
        """Validate PDF file integrity"""
        # Check file exists and is not empty
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            return False

        # Check PDF magic bytes
        with open(pdf_path, 'rb') as f:
            header = f.read(4)
            return header == b'%PDF'
```

### 4. LLM Service (`src/services/llm_service.py`)

**Responsibilities:**
- Abstract LLM provider (Anthropic/Google)
- Build extraction prompts
- Parse LLM responses
- Track usage and costs
- Enforce cost limits

**Key Functions:**
```python
from anthropic import AsyncAnthropic
from google.generativeai import GenerativeModel
import json

class LLMService:
    def __init__(self, config: LLMConfig, cost_limits: CostLimits):
        """Initialize LLM service"""
        self.config = config
        self.cost_limits = cost_limits
        self.usage_stats = UsageStats()

        if config.provider == "anthropic":
            self.client = AsyncAnthropic(api_key=config.api_key)
        else:
            self.client = GenerativeModel(config.model)

    async def extract(
        self,
        markdown_content: str,
        targets: List[ExtractionTarget],
        paper_metadata: PaperMetadata
    ) -> PaperExtraction:
        """Extract information from markdown using LLM

        Args:
            markdown_content: Full paper in markdown
            targets: List of extraction targets
            paper_metadata: Paper metadata for context

        Returns:
            PaperExtraction with results

        Raises:
            CostLimitExceeded: If cost limits exceeded
            ExtractionError: If extraction fails
        """
        # Check cost limits
        self._check_cost_limits()

        # Build prompt
        prompt = self._build_extraction_prompt(
            markdown_content,
            targets,
            paper_metadata
        )

        # Call LLM
        if self.config.provider == "anthropic":
            response = await self._call_anthropic(prompt)
        else:
            response = await self._call_google(prompt)

        # Parse response
        results = self._parse_response(response, targets)

        # Update usage stats
        self._update_usage(response)

        return PaperExtraction(
            paper_id=paper_metadata.paper_id,
            extraction_results=results,
            tokens_used=response.usage.total_tokens,
            cost_usd=self._calculate_cost(response.usage),
            extraction_timestamp=datetime.utcnow()
        )

    def _build_extraction_prompt(
        self,
        markdown: str,
        targets: List[ExtractionTarget],
        metadata: PaperMetadata
    ) -> str:
        """Build structured extraction prompt"""

        targets_json = [
            {
                "name": t.name,
                "description": t.description,
                "output_format": t.output_format,
                "required": t.required
            }
            for t in targets
        ]

        prompt = f"""You are a research paper analyst. Extract specific information from the paper below.

Paper Metadata:
- Title: {metadata.title}
- Authors: {', '.join(a.name for a in metadata.authors)}
- Year: {metadata.year}

Extraction Targets:
{json.dumps(targets_json, indent=2)}

Instructions:
1. Read the paper carefully
2. For each target, extract the requested information
3. If a target is not found and not required, return null
4. Return valid JSON with this structure:
{{
    "extractions": [
        {{
            "target_name": "system_prompts",
            "success": true,
            "content": [...],
            "confidence": 0.95
        }},
        ...
    ]
}}

Paper Content:
{markdown}

Now extract the information:"""

        return prompt

    def _parse_response(
        self,
        response: Any,
        targets: List[ExtractionTarget]
    ) -> List[ExtractionResult]:
        """Parse LLM response into structured results"""

        # Extract JSON from response
        if self.config.provider == "anthropic":
            content = response.content[0].text
        else:
            content = response.text

        # Parse JSON
        try:
            data = json.loads(content)
            extractions = data.get("extractions", [])

            results = []
            for ext in extractions:
                results.append(ExtractionResult(
                    target_name=ext["target_name"],
                    success=ext.get("success", True),
                    content=ext.get("content"),
                    confidence=ext.get("confidence", 0.0)
                ))

            return results

        except json.JSONDecodeError as e:
            raise ExtractionError(f"Failed to parse LLM response: {e}")

    def _calculate_cost(self, usage: Any) -> float:
        """Calculate cost based on token usage"""
        # Claude 3.5 Sonnet pricing (as of 2025)
        input_cost_per_mtok = 3.00  # $3 per million tokens
        output_cost_per_mtok = 15.00  # $15 per million tokens

        input_cost = (usage.input_tokens / 1_000_000) * input_cost_per_mtok
        output_cost = (usage.output_tokens / 1_000_000) * output_cost_per_mtok

        return input_cost + output_cost

    def _check_cost_limits(self):
        """Check if cost limits would be exceeded"""
        if self.usage_stats.total_cost_usd >= self.cost_limits.max_total_spend_usd:
            raise CostLimitExceeded(
                f"Total spend limit reached: ${self.usage_stats.total_cost_usd}"
            )
```

### 5. Extraction Service (`src/services/extraction_service.py`)

**Responsibilities:**
- Orchestrate PDF download → conversion → extraction
- Handle papers without PDFs (abstract-only)
- Implement fallback strategies
- Manage temporary files

**Key Functions:**
```python
class ExtractionService:
    def __init__(
        self,
        pdf_service: PDFService,
        llm_service: LLMService,
        temp_dir: Path
    ):
        """Initialize extraction service"""

    async def process_paper(
        self,
        paper: PaperMetadata,
        targets: List[ExtractionTarget]
    ) -> ExtractedPaper:
        """Process a single paper through the full pipeline

        1. Try to download PDF
        2. If successful, convert to markdown
        3. Extract using LLM
        4. If PDF fails, use abstract only

        Returns:
            ExtractedPaper with results
        """
        extracted = ExtractedPaper(
            metadata=paper,
            pdf_available=False
        )

        # Try PDF path
        if paper.open_access_pdf:
            try:
                pdf_path = await self._download_and_convert(paper)
                extracted.pdf_available = True
                extracted.pdf_path = str(pdf_path)

                # Read markdown
                md_path = pdf_path.with_suffix('.md')
                markdown_content = md_path.read_text()
                extracted.markdown_path = str(md_path)

            except (PDFDownloadError, ConversionError) as e:
                logger.warning(
                    "PDF processing failed, falling back to abstract",
                    paper_id=paper.paper_id,
                    error=str(e)
                )
                markdown_content = self._format_abstract(paper)
        else:
            # No PDF available, use abstract
            markdown_content = self._format_abstract(paper)

        # Extract using LLM
        try:
            extraction = await self.llm_service.extract(
                markdown_content,
                targets,
                paper
            )
            extracted.extraction = extraction

        except ExtractionError as e:
            logger.error(
                "Extraction failed",
                paper_id=paper.paper_id,
                error=str(e)
            )

        return extracted

    def _format_abstract(self, paper: PaperMetadata) -> str:
        """Format paper metadata as markdown when PDF unavailable"""
        return f"""# {paper.title}

**Authors:** {', '.join(a.name for a in paper.authors)}
**Year:** {paper.year}
**Citations:** {paper.citation_count}

## Abstract

{paper.abstract or 'No abstract available'}
"""
```

### 6. Enhanced Output Generator

**Updated Output Format:**
```markdown
---
topic: "Tree of Thoughts AND machine translation"
date: 2025-01-23
papers_processed: 15
papers_with_pdfs: 12
papers_with_extractions: 15
total_tokens_used: 450000
total_cost_usd: 5.25
run_id: "20250123-143052"
---

# Research Brief: Tree of Thoughts AND Machine Translation

## Summary

Processed 15 papers, 12 with full PDF access. Total LLM cost: $5.25

## Papers

### 1. [Enhancing Translation with Tree-of-Thought Prompting](https://doi.org/...)

**Authors:** John Doe, Jane Smith
**Published:** 2025-01-22
**Citations:** 5
**PDF Available:** ✅

#### Extracted System Prompts

```
You are a multilingual translation expert. Your task is to...
```

#### Extracted Code

```python
def tree_of_thoughts_translate(text, source_lang, target_lang):
    # Generate multiple translation candidates
    candidates = []
    for i in range(3):
        prompt = build_candidate_prompt(text, i)
        candidate = llm.generate(prompt)
        candidates.append(candidate)

    # Evaluate and select best
    best = evaluate_translations(candidates)
    return best
```

#### Evaluation Metrics

| Metric | Value |
|--------|-------|
| BLEU | 42.3 |
| COMET | 0.87 |

#### Engineering Summary

This paper introduces a Tree of Thoughts (ToT) approach to machine translation...

---

### 2. [Another Paper](https://doi.org/...)
**PDF Available:** ❌ (Abstract only)

...
```

## Implementation Requirements

### Updated Dependencies
```txt
# Add to requirements.txt
anthropic>=0.18.0
google-generativeai>=0.3.0
aiohttp>=3.9.0
tenacity>=8.2.0
marker-pdf>=0.2.0  # or specific version
```

### Error Handling

**Error Hierarchy:**
```python
class PipelineError(Exception):
    """Base exception"""

class PDFDownloadError(PipelineError):
    """PDF download failed"""

class FileSizeError(PipelineError):
    """File too large"""

class ConversionError(PipelineError):
    """PDF conversion failed"""

class ExtractionError(PipelineError):
    """LLM extraction failed"""

class CostLimitExceeded(PipelineError):
    """Budget exceeded"""
```

**Fallback Strategy:**
```
PDF Available?
  ├─ Yes → Download
  │   ├─ Success → Convert to MD
  │   │   ├─ Success → Extract with LLM
  │   │   └─ Fail → Use Abstract + Extract
  │   └─ Fail → Use Abstract + Extract
  └─ No → Use Abstract + Extract
```

## Testing Requirements

### Unit Tests
```python
# tests/unit/test_pdf_service.py
async def test_pdf_download_success():
    """Test successful PDF download"""

async def test_pdf_download_retry():
    """Test retry on transient failures"""

def test_pdf_validation():
    """Test PDF file validation"""

# tests/unit/test_llm_service.py
async def test_extraction_success():
    """Test successful LLM extraction"""

def test_cost_calculation():
    """Test cost calculation accuracy"""

def test_cost_limit_enforcement():
    """Test cost limits are enforced"""
```

### Integration Tests
```python
# tests/integration/test_extraction_pipeline.py
async def test_full_extraction_pipeline():
    """Test PDF → markdown → LLM extraction"""

async def test_fallback_to_abstract():
    """Test fallback when PDF unavailable"""
```

### Mock Data
```python
# tests/fixtures/sample_paper.pdf
# tests/fixtures/sample_paper.md
# tests/fixtures/sample_extraction.json
```

## Acceptance Criteria

### Functional Requirements
- [ ] Can download PDFs from open access URLs
- [ ] Can convert PDFs to markdown using marker-pdf
- [ ] Can extract all configured targets using LLM
- [ ] Can handle papers without PDFs gracefully
- [ ] Can recover from individual paper failures
- [ ] Enforces cost limits correctly
- [ ] Generates enhanced markdown with extractions
- [ ] Tracks usage statistics accurately

### Non-Functional Requirements
- [ ] PDF download timeout: 5 minutes
- [ ] PDF conversion timeout: 5 minutes
- [ ] LLM extraction timeout: 5 minutes
- [ ] Retry on transient failures (3 attempts)
- [ ] Cost tracking accurate to $0.01
- [ ] Test coverage >80%

### Performance Requirements
- [ ] Single paper extraction < 10 minutes
- [ ] Handles PDFs up to 50MB
- [ ] LLM tokens per paper < 100k

## Deliverables

1. ✅ PDF service with retry logic
2. ✅ LLM service supporting Claude and Gemini
3. ✅ Extraction orchestration service
4. ✅ Enhanced output generator
5. ✅ Cost tracking and limits
6. ✅ Comprehensive tests
7. ✅ Updated documentation

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM costs exceed budget | HIGH | Implement strict cost limits, monitoring |
| marker-pdf crashes | MEDIUM | Timeout, fallback to abstract |
| API rate limits | MEDIUM | Exponential backoff, queueing |
| Large PDFs cause OOM | LOW | File size limits, streaming |

## Future Considerations (Not in Phase 2)

- Concurrent paper processing (Phase 3)
- Caching of extractions (Phase 3)
- Alternative PDF parsers (Phase 3)
- Structured output validation (Phase 3)

## Sign-off

- [ ] Product Owner Approval
- [ ] Technical Lead Approval
- [ ] Security Review Complete
- [ ] Ready for Development

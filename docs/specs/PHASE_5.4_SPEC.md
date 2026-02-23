# Phase 5.4: Utility Pattern Extraction
**Version:** 1.0
**Status:** 📋 Planning
**Timeline:** 2 days
**Dependencies:**
- Phase 5.1 Complete (LLMService Decomposition)
- All existing utility tests passing

---

## Architecture Reference

This phase creates reusable utilities as defined in [SYSTEM_ARCHITECTURE.md §6 Utils Layer](../SYSTEM_ARCHITECTURE.md#utils-layer).

**Architectural Gaps Addressed:**
- ❌ Gap: Cost calculation logic duplicated across 3+ locations
- ❌ Gap: Markdown generation patterns duplicated across 4+ locations
- ❌ Gap: Retry patterns implemented inconsistently
- ❌ Gap: No standardized utility interfaces

**Components Modified:**
- Utils: New utility modules
- Services: LLMService, SynthesisEngine, CrossSynthesisService (consume utilities)
- Output: MarkdownGenerator, EnhancedMarkdownGenerator (consume utilities)

**Coverage Targets:**
- All new utility modules: ≥99%
- Overall coverage: Maintain ≥99%

---

## 1. Executive Summary

Phase 5.4 extracts common patterns found duplicated across the codebase into reusable utility modules. This follows the DRY (Don't Repeat Yourself) principle and creates a consistent foundation for future development.

**What This Phase Is:**
- ✅ Extraction of cost calculation utilities.
- ✅ Extraction of markdown building utilities.
- ✅ Consolidation of retry patterns.
- ✅ Creation of standardized utility interfaces.

**What This Phase Is NOT:**
- ❌ Changing cost calculation formulas.
- ❌ Changing markdown output formats.
- ❌ Modifying retry behavior.
- ❌ Breaking existing callers.

**Key Achievement:** Eliminate 200+ lines of duplicate code across the codebase.

---

## 2. Problem Statement

### 2.1 Cost Calculation Duplication
Cost calculation appears in multiple places with identical logic:

**Location 1:** `LLMService._calculate_cost_anthropic` (lines 761-770)
```python
input_cost = input_tokens * 3.00 / 1_000_000  # $3/M tokens
output_cost = output_tokens * 15.00 / 1_000_000  # $15/M tokens
return input_cost + output_cost
```

**Location 2:** `LLMService._calculate_cost_google` (lines 771-777)
```python
input_cost = input_tokens * 0.075 / 1_000_000  # $0.075/M tokens
output_cost = output_tokens * 0.30 / 1_000_000  # $0.30/M tokens
return input_cost + output_cost
```

**Location 3:** `CostReportJob._calculate_cumulative_cost`

### 2.2 Markdown Generation Duplication
Similar YAML frontmatter and section generation patterns exist in:
- `MarkdownGenerator.generate`
- `EnhancedMarkdownGenerator.generate_enhanced`
- `SynthesisEngine._format_kb_entry_as_markdown`
- `CrossSynthesisGenerator._build_synthesis_section`

### 2.3 Inconsistent Retry Handling
While `RetryHandler` exists, some services implement their own retry logic:
- `PDFService.download_pdf` - Uses custom retry decorator
- `DiscoveryService._search_with_provider` - Manual retry loop

---

## 3. Requirements

### 3.1 Cost Calculation Utility

#### REQ-5.4.1: Cost Calculator Class
A `CostCalculator` utility SHALL provide centralized cost calculation.

**Responsibilities:**
- Calculate costs for Anthropic models (Claude)
- Calculate costs for Google models (Gemini)
- Support future provider additions
- Provide pricing configuration

#### REQ-5.4.2: Provider Pricing Configuration
Provider pricing SHALL be configurable via environment or config.

**Default Pricing (per million tokens):**
| Provider | Model | Input | Output |
|----------|-------|-------|--------|
| Anthropic | Claude 3.5 Sonnet | $3.00 | $15.00 |
| Google | Gemini 1.5 Pro | $0.075 | $0.30 |

### 3.2 Markdown Building Utility

#### REQ-5.4.3: Markdown Builder Class
A `MarkdownBuilder` utility SHALL provide consistent markdown generation.

**Responsibilities:**
- Generate YAML frontmatter
- Build section headers with consistent formatting
- Create bullet lists and tables
- Handle special character escaping

#### REQ-5.4.4: Frontmatter Generation
YAML frontmatter generation SHALL be standardized.

```python
builder = MarkdownBuilder()
frontmatter = builder.frontmatter({
    "title": "Research Brief",
    "date": "2025-01-23",
    "tags": ["research", "ML"],
})
# Output:
# ---
# title: Research Brief
# date: 2025-01-23
# tags:
#   - research
#   - ML
# ---
```

### 3.3 Retry Consolidation

#### REQ-5.4.5: Unified Retry Handler
All retry logic SHALL use the existing `RetryHandler` from `src/utils/retry.py`.

**Services to Update:**
- PDFService: Replace custom decorator with RetryHandler
- DiscoveryService: Replace manual loop with RetryHandler

### 3.4 Package Structure

#### REQ-5.4.6: Utility Organization

```
src/utils/
├── __init__.py           # Re-export public utilities
├── logging.py            # Existing logging config
├── retry.py              # Existing retry handler
├── path_sanitizer.py     # Existing path utilities
├── author_utils.py       # Existing author normalization (Phase 3.x)
├── cost_calculator.py    # NEW: Cost calculation utilities
├── markdown_builder.py   # NEW: Markdown generation utilities
└── formatting.py         # NEW: Text formatting utilities
```

---

## 4. Technical Design

### 4.1 Cost Calculator

```python
# src/utils/cost_calculator.py
from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum


class Provider(Enum):
    ANTHROPIC = "anthropic"
    GOOGLE = "google"


@dataclass(frozen=True)
class ModelPricing:
    """Pricing for a model (per million tokens)."""
    input_cost: float
    output_cost: float


# Default pricing (easily configurable)
DEFAULT_PRICING: Dict[str, ModelPricing] = {
    "claude-3-5-sonnet": ModelPricing(input_cost=3.00, output_cost=15.00),
    "claude-3-opus": ModelPricing(input_cost=15.00, output_cost=75.00),
    "claude-3-haiku": ModelPricing(input_cost=0.25, output_cost=1.25),
    "gemini-1.5-pro": ModelPricing(input_cost=0.075, output_cost=0.30),
    "gemini-1.5-flash": ModelPricing(input_cost=0.0375, output_cost=0.15),
}


class CostCalculator:
    """Centralized LLM cost calculation."""

    def __init__(self, custom_pricing: Optional[Dict[str, ModelPricing]] = None):
        self._pricing = {**DEFAULT_PRICING}
        if custom_pricing:
            self._pricing.update(custom_pricing)

    def calculate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Calculate cost in USD for token usage.

        Args:
            model: Model identifier (e.g., "claude-3-5-sonnet")
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD

        Raises:
            ValueError: If model pricing not found
        """
        pricing = self._pricing.get(model)
        if not pricing:
            raise ValueError(f"Unknown model: {model}")

        input_cost = input_tokens * pricing.input_cost / 1_000_000
        output_cost = output_tokens * pricing.output_cost / 1_000_000
        return input_cost + output_cost

    def get_pricing(self, model: str) -> Optional[ModelPricing]:
        """Get pricing for a model."""
        return self._pricing.get(model)

    def list_models(self) -> list[str]:
        """List all known models."""
        return list(self._pricing.keys())
```

### 4.2 Markdown Builder

```python
# src/utils/markdown_builder.py
from typing import Any, Dict, List, Optional
import yaml


class MarkdownBuilder:
    """Fluent builder for consistent markdown generation."""

    def __init__(self):
        self._parts: List[str] = []

    def frontmatter(self, metadata: Dict[str, Any]) -> "MarkdownBuilder":
        """Add YAML frontmatter."""
        yaml_content = yaml.dump(
            metadata,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        self._parts.append(f"---\n{yaml_content}---\n")
        return self

    def heading(self, text: str, level: int = 1) -> "MarkdownBuilder":
        """Add a heading."""
        prefix = "#" * min(max(level, 1), 6)
        self._parts.append(f"\n{prefix} {text}\n")
        return self

    def paragraph(self, text: str) -> "MarkdownBuilder":
        """Add a paragraph."""
        self._parts.append(f"\n{text}\n")
        return self

    def bullet_list(self, items: List[str]) -> "MarkdownBuilder":
        """Add a bullet list."""
        lines = [f"- {item}" for item in items]
        self._parts.append("\n" + "\n".join(lines) + "\n")
        return self

    def numbered_list(self, items: List[str]) -> "MarkdownBuilder":
        """Add a numbered list."""
        lines = [f"{i+1}. {item}" for i, item in enumerate(items)]
        self._parts.append("\n" + "\n".join(lines) + "\n")
        return self

    def code_block(
        self, code: str, language: Optional[str] = None
    ) -> "MarkdownBuilder":
        """Add a code block."""
        lang = language or ""
        self._parts.append(f"\n```{lang}\n{code}\n```\n")
        return self

    def table(
        self, headers: List[str], rows: List[List[str]]
    ) -> "MarkdownBuilder":
        """Add a markdown table."""
        header_row = "| " + " | ".join(headers) + " |"
        separator = "| " + " | ".join(["---"] * len(headers)) + " |"
        data_rows = [
            "| " + " | ".join(row) + " |"
            for row in rows
        ]
        self._parts.append(
            "\n" + "\n".join([header_row, separator] + data_rows) + "\n"
        )
        return self

    def horizontal_rule(self) -> "MarkdownBuilder":
        """Add a horizontal rule."""
        self._parts.append("\n---\n")
        return self

    def build(self) -> str:
        """Build the final markdown string."""
        return "".join(self._parts)

    def clear(self) -> "MarkdownBuilder":
        """Clear all parts and return self."""
        self._parts.clear()
        return self
```

### 4.3 Formatting Utilities

```python
# src/utils/formatting.py
from typing import List, Optional
import re


def truncate(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate text to max length with suffix."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def escape_markdown(text: str) -> str:
    """Escape markdown special characters."""
    special_chars = r"[\*_`\[\]()#>+\-\.!]"
    return re.sub(special_chars, r"\\\g<0>", text)


def format_bytes(size: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def format_duration(seconds: float) -> str:
    """Format seconds to human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


def format_number(n: int) -> str:
    """Format number with thousands separators."""
    return f"{n:,}"


def slugify(text: str, separator: str = "-") -> str:
    """Convert text to URL-safe slug."""
    # Remove special characters, lowercase, replace spaces
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", separator, text)
    return text.strip(separator)
```

---

## 5. Security Requirements (MANDATORY) 🔒

### SR-5.4.1: Cost Calculator Security
- [ ] No hardcoded API keys in pricing configuration.
- [ ] Cost calculations auditable via logging.
- [ ] No overflow vulnerabilities in token calculations.

### SR-5.4.2: Markdown Builder Security
- [ ] XSS prevention: Escape user content where needed.
- [ ] No code injection via markdown generation.
- [ ] Handle malformed input gracefully.

### SR-5.4.3: Formatting Security
- [ ] No regex denial of service (ReDoS) vulnerabilities.
- [ ] Input length limits enforced.
- [ ] Unicode handling safe.

---

## 6. Implementation Tasks

### Task 1: Create Cost Calculator (0.5 day)
**Files:** src/utils/cost_calculator.py

1. Implement CostCalculator class.
2. Define default pricing for all supported models.
3. Add comprehensive unit tests.
4. Update LLMService to use CostCalculator.

### Task 2: Create Markdown Builder (0.5 day)
**Files:** src/utils/markdown_builder.py

1. Implement MarkdownBuilder class.
2. Add all markdown element methods.
3. Add comprehensive unit tests.
4. Document usage examples.

### Task 3: Create Formatting Utilities (0.25 day)
**Files:** src/utils/formatting.py

1. Implement text formatting utilities.
2. Add comprehensive unit tests.
3. Document usage examples.

### Task 4: Update Callers - Cost (0.25 day)
**Files:** src/services/llm_service.py, src/scheduling/jobs.py

1. Update LLMService to use CostCalculator.
2. Update CostReportJob to use CostCalculator.
3. Remove duplicate cost calculation code.

### Task 5: Update Callers - Markdown (0.25 day)
**Files:** src/output/*.py, src/services/*_synthesis*.py

1. Update MarkdownGenerator to use MarkdownBuilder.
2. Update SynthesisEngine to use MarkdownBuilder.
3. Reduce code duplication.

### Task 6: Consolidate Retry Usage (0.25 day)
**Files:** src/services/pdf_service.py, src/services/discovery_service.py

1. Update PDFService to use RetryHandler.
2. Update DiscoveryService to use RetryHandler.
3. Remove custom retry implementations.

---

## 7. Verification Criteria

### 7.1 Unit Tests (New)
- `test_cost_calculator_anthropic`: Anthropic cost calculation correct.
- `test_cost_calculator_google`: Google cost calculation correct.
- `test_cost_calculator_unknown_model`: Raises ValueError.
- `test_markdown_builder_frontmatter`: YAML frontmatter correct.
- `test_markdown_builder_table`: Table generation correct.
- `test_markdown_builder_fluent`: Fluent API chains correctly.
- `test_formatting_truncate`: Truncation works correctly.
- `test_formatting_slugify`: Slugification correct.

### 7.2 Regression Tests
- All existing tests MUST pass unchanged.
- Coverage MUST remain ≥99%.
- Cost calculations MUST produce identical results.
- Markdown output MUST be identical.

### 7.3 Integration Tests
- `test_llm_service_uses_calculator`: LLMService uses CostCalculator.
- `test_synthesis_uses_builder`: SynthesisEngine uses MarkdownBuilder.

---

## 8. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Cost calculation drift | High | Low | Identical formulas, comparison tests |
| Markdown format changes | Medium | Low | Output comparison tests |
| Breaking caller imports | Low | Low | Deprecation warnings |

---

## 9. File Size Targets

| File | Target |
|------|--------|
| cost_calculator.py | <100 lines |
| markdown_builder.py | <150 lines |
| formatting.py | <80 lines |

---

## 10. Code Reduction Estimate

| Source | Lines Removed | Replaced By |
|--------|---------------|-------------|
| LLMService cost methods | ~20 lines | CostCalculator |
| CostReportJob calculation | ~15 lines | CostCalculator |
| MarkdownGenerator | ~30 lines | MarkdownBuilder |
| EnhancedMarkdownGenerator | ~40 lines | MarkdownBuilder |
| SynthesisEngine markdown | ~30 lines | MarkdownBuilder |
| CrossSynthesisGenerator | ~25 lines | MarkdownBuilder |
| Custom retry in PDFService | ~20 lines | RetryHandler |
| Custom retry in Discovery | ~25 lines | RetryHandler |

**Total Estimated Reduction:** ~205 lines of duplicate code

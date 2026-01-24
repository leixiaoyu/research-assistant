# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Development Philosophy

### 🔒 Security First (Non-Negotiable)

**Security is the #1 priority and cannot be compromised under any circumstances.**

Before writing ANY code, you must:
1. **Never hardcode secrets** - All credentials via environment variables
2. **Validate all inputs** - Use Pydantic models for runtime validation
3. **Sanitize all paths** - Prevent directory traversal attacks
4. **Log security events** - But never log secrets or credentials
5. **Scan for secrets** - Check before committing

**Security Checklist (Required for Every Change):**
- [ ] No hardcoded credentials in code
- [ ] All user inputs validated with Pydantic
- [ ] No command injection vulnerabilities
- [ ] No SQL injection vulnerabilities
- [ ] All file paths sanitized
- [ ] No directory traversal vulnerabilities
- [ ] Rate limiting implemented where needed
- [ ] Security events logged appropriately
- [ ] No secrets in logs or commits

See [SYSTEM_ARCHITECTURE.md §9 Security](docs/SYSTEM_ARCHITECTURE.md#security) for complete security requirements.

### 🧪 Test-Driven Development (Required)

**No code should be pushed to remote without complete verification.**

Every feature must have:
1. **Automated Tests** (preferred):
   - Unit tests for all functions
   - Integration tests for service interactions
   - End-to-end tests for critical workflows
   - Test coverage >80%

2. **Manual Verification** (when automated tests insufficient):
   - Step-by-step manual testing by Claude Code
   - Detailed logging of each test step
   - Screenshots/outputs captured as evidence
   - Results documented in verification report

**Verification Report Format:**
```markdown
## Feature Verification Report

**Feature:** [Feature name]
**Date:** [Date]
**Tested By:** Claude Code
**Status:** [PASS/FAIL]

### Test Cases
1. [Test case 1]
   - Steps: [...]
   - Expected: [...]
   - Actual: [...]
   - Status: PASS ✅

2. [Test case 2]
   - Steps: [...]
   - Expected: [...]
   - Actual: [...]
   - Status: PASS ✅

### Coverage
- Unit Tests: X%
- Integration Tests: Y%
- Manual Tests: Z test cases

### Security Verification
- [ ] All security checklist items verified
- [ ] No vulnerabilities detected
- [ ] Secret scanning passed

### Conclusion
[Summary of verification results]
```

### 📋 Feature Completeness (Required)

Every feature must function **100% of the time** according to its specification before being pushed.

**Definition of Complete:**
- All specified functionality implemented
- All edge cases handled
- All error cases handled gracefully
- All inputs validated
- All security requirements met
- All tests passing
- All documentation updated
- Verification report generated

**If ANY requirement is not met, the feature is INCOMPLETE and must not be pushed.**

---

## Project Overview

**Automated Research Ingestion & Synthesis Pipeline (ARISP)** automates the discovery, extraction, and synthesis of cutting-edge AI research papers based on user-defined research topics. The pipeline runs on-demand or scheduled, fetches PDFs, converts them to Markdown, extracts code and prompts using an LLM, and outputs Obsidian-ready markdown briefs for engineering teams.

**Key Features:**
- **Configurable Topics:** Research topics are read from `research_config.yaml` (user-editable)
- **Flexible Timeframes:** Query papers from any time period (48 hours, 1 year, since 2008, etc.)
- **Intelligent Cataloging:** Detects duplicate/overlapping topics and appends to existing research folders
- **Daily Variation:** Topics can change each day via config updates

## Tech Stack
* **Language:** Python 3.10+
* **Data Models:** Pydantic V2 (Strict)
* **PDF Parser:** `marker-pdf` (preserves code syntax during PDF-to-MD conversion)
* **APIs:** Semantic Scholar API (discovery), Gemini 1.5 Pro or Claude 3.5 Sonnet (extraction)
* **Environment:** `pip` + `venv` / `dotenv` for secrets

## Development Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.template .env
# Then edit .env and add your API keys
```

## Configuration Files

### `.env` (API Keys - DO NOT commit)
```bash
SEMANTIC_SCHOLAR_API_KEY=your_key_here
LLM_API_KEY=your_gemini_or_anthropic_key
```

### `research_config.yaml` (User-editable research parameters)
```yaml
research_topics:
  - query: "Tree of Thoughts AND machine translation"
    timeframe:
      type: "recent"  # or "since_year", "date_range"
      value: "48h"    # or year: 2008, or start/end dates
  - query: "reinforcement learning AND robotics"
    timeframe:
      type: "since_year"
      value: 2020

# Global settings
max_papers_per_topic: 50
output_base_dir: "./output"
enable_duplicate_detection: true
```

**Timeframe Options:**
- `recent`: Last N hours/days (e.g., "48h", "7d")
- `since_year`: All papers from specified year onwards (e.g., 2008)
- `date_range`: Custom start and end dates

## Common Development Commands

```bash
# Run the full pipeline (reads from research_config.yaml)
python -m src.cli run

# Run with custom config file
python -m src.cli run --config custom_research.yaml

# Test configuration loading
python -m src.cli validate config/research_config.yaml

# View catalog
python -m src.cli catalog show

# Run tests
pytest tests/

# Check coverage
pytest --cov=src tests/ --cov-report=term-missing

# Type checking
mypy src/
```

## Architecture

The pipeline consists of five main modules:

1. **`src/services/config_manager.py`** - Configuration and catalog management
   - Reads and validates `research_config.yaml` using Pydantic V2
   - Manages output directory structure: `./output/{topic_slug}/`
   - Detects duplicate/overlapping topics using topic normalization and hashing
   - Determines whether to create new folder or append to existing
   - Maintains a catalog index (e.g., `catalog.json`) tracking all research runs

2. **`src/services/discovery_service.py`** - Semantic Scholar integration
   - Reads topics from config manager
   - Builds queries with configurable timeframes
   - Returns list of `PaperMetadata` objects with `title`, `abstract`, `url`, `openAccessPdf`, `publicationDate`
   - Handles API rate limiting and retries

3. **`src/services/catalog_service.py`** - Catalog Logic
   - Handles deduplication logic and run tracking
   - Updates `catalog.json` atomically

4. **`src/cli.py`** - Pipeline orchestration (Typer CLI)
   - Loads config via `config_manager`
   - Processes each topic in `research_config.yaml`
   - For each topic, determines output location (new or existing)
   - Generates markdown: `./output/{topic_slug}/YYYY-MM-DD_Research.md`
   - Updates catalog index

5. **`src/output/markdown_generator.py`** - Output Generation
   - Formats `PaperMetadata` into Obsidian-compatible markdown with YAML frontmatter

**Phase 2 Modules (To Be Implemented):**
- **`src/services/pdf_processor.py`**: PDF download and conversion
- **`src/services/llm_extractor.py`**: Code and prompt extraction using LLM

## Development Workflow

### Before Starting Any Work
1. Review [SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) for architectural guidance
2. Review relevant phase specification in `docs/specs/`
3. Understand security requirements for the component
4. Plan test strategy before writing code

### During Development
1. Write tests first (TDD) or alongside code
2. Validate all inputs with Pydantic
3. Never hardcode secrets
4. Log appropriately (info for operations, never secrets)
5. Handle all error cases gracefully
6. Document security considerations

### Before Committing
1. Run all tests: `pytest tests/`
2. Check test coverage: `pytest --cov=src --cov-report=term`
3. Format code: `black .`
4. Type check: `mypy src/`
5. Security scan: Check for hardcoded secrets
6. Review security checklist
7. Generate verification report

### Before Pushing
1. **All tests must pass** (100%)
2. **Coverage must be >80%**
3. **Security checklist complete**
4. **Verification report generated**
5. **Feature specification 100% met**

**If ANY requirement fails, do NOT push. Fix issues first.**

---

## Coding Standards

### Security Standards (CRITICAL)
* **Never hardcode secrets**: Use environment variables exclusively
* **Validate all inputs**: Use Pydantic models with strict validation
* **Sanitize paths**: Use PathSanitizer for all file operations
* **Log securely**: Log operations, never credentials
* **Rate limit**: All external API calls must be rate limited

### Code Quality Standards
* **Modularity:** Separate concerns across the five main modules
* **Error Handling:** Implement robust try/except blocks and exponential backoff for API rate limits
* **Logging:** Use `structlog` for structured JSON logging, not `print()`
* **Type Hints:** Required for all function signatures (enforced by mypy)
* **Documentation:** All public functions must have docstrings with type annotations

### Testing Standards
* **Coverage Target:** >80% for all modules
* **Test Types:**
  - Unit tests: All functions and methods
  - Integration tests: Service interactions
  - End-to-end tests: Full pipeline workflows
* **Security Tests:** Validate input validation, path sanitization, etc.
* **Test Naming:** `test_<function>_<scenario>` (e.g., `test_validate_query_rejects_injection`)

## Key Implementation Details

### Configuration Management (`config_manager.py`)
- **Topic Normalization:** Convert query strings to slugs for folder names (e.g., `"Tree of Thoughts AND machine translation"` → `tot-machine-translation`)
- **Duplicate Detection:** Use normalized topic strings or hash to match existing research
- **Catalog Structure:** Maintain `catalog.json` with:
  ```json
  {
    "tot-machine-translation": {
      "query": "Tree of Thoughts AND machine translation",
      "folder": "tot-machine-translation",
      "runs": [
        {"date": "2025-01-23", "papers_found": 15, "timeframe": "48h"},
        {"date": "2025-01-25", "papers_found": 8, "timeframe": "48h"}
      ]
    }
  }
  ```
- **Appending Logic:** If topic exists in catalog, append to existing folder; otherwise create new

### Semantic Scholar API (`search.py`)
- **Query:** Read from `research_config.yaml` (e.g., `"Tree of Thoughts AND machine translation"`)
- **Timeframe Handling:**
  - For `recent`: Convert to date range (e.g., "48h" → last 2 days)
  - For `since_year`: Filter `publicationDateOrYear >= 2008`
  - For `date_range`: Use exact start/end dates
- **Output format:** List of dicts with `title`, `abstract`, `url`, `openAccessPdf`, `publicationDate`

### PDF Conversion (`pdf_processor.py`)
- **Tool:** `marker_single {pdf_path} --output_dir ./temp_md/`
- Use `subprocess` module for better error handling than `os.system`
- Handle cases where PDFs are not open access or conversion fails

### LLM Extraction (`llm_extractor.py`)
- **Required output fields:** `tot_system_prompt`, `tot_user_prompt_template`, `python_code_snippet`, `engineering_summary`
- Must return valid JSON
- Handle LLM API rate limits and long documents (1M+ tokens)

### Output Format (`main.py`)
- **Directory Structure:**
  ```
  ./output/
    ├── catalog.json                    # Master index of all research
    ├── tot-machine-translation/        # Topic-based folders
    │   ├── 2025-01-23_Research.md
    │   ├── 2025-01-25_Research.md
    │   └── papers/                     # Downloaded PDFs
    └── rl-robotics/
        ├── 2025-01-24_Research.md
        └── papers/
  ```
- **Markdown Format:** Obsidian-compatible with YAML frontmatter
  ```markdown
  ---
  topic: "Tree of Thoughts AND machine translation"
  date: 2025-01-23
  papers_processed: 15
  timeframe: "48h"
  ---

  # Research Brief: ToT in Machine Translation

  ## Papers Found
  ...

  ## Extracted Prompts & Code
  ...

  ## Engineering Summary
  ...
  ```
- **Appending Behavior:** When topic is rerun, create new dated file in same folder, don't overwrite

## Dependencies (requirements.txt)
```
requests
python-dotenv
google-generativeai  # or anthropic
marker-pdf
pyyaml              # for config file parsing
```

## Output Directory Management

**Critical Behaviors:**
1. **Topic Slug Generation:** Normalize queries to filesystem-safe folder names
2. **Duplicate Detection:** Before creating new folder, check if normalized topic exists in `catalog.json`
3. **Appending:** When re-running same topic, add new dated markdown file to existing folder
4. **Catalog Updates:** After each run, update `catalog.json` with run metadata
5. **Paper Deduplication:** Within a topic folder, track paper DOIs/IDs to avoid re-processing same papers

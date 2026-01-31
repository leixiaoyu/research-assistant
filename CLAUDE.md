# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Development Philosophy

**⚠️ NON-NEGOTIABLE BLOCKING REQUIREMENTS**

The following requirements are **absolute** and **block all commits and pushes** without exception:

1. **🔒 Security:** All security checklist items must pass
2. **🧪 Test Coverage:** ≥95% coverage for all modules (target 100%)
3. **✅ Tests Passing:** 100% pass rate (0 failures)
4. **📋 Completeness:** All feature requirements fully implemented
5. **🔏 Branch Protection:** No direct pushes to `main`. All changes via PR only.

**If ANY of these fail, you MUST stop and fix before committing or pushing. No exceptions.**

---

## Workflow & Branch Protection (Strict)

**Direct pushes to `main` are disabled and strictly forbidden.**

### PR Requirements (Non-Negotiable)
Before a Pull Request can be merged into `main`:
1. **CI Status:** The "test (3.10)" workflow must pass with **100% success rate**.
2. **Linting & Types:** **Flake8**, **Black** (formatting), and **Mypy** (static analysis) must pass with zero issues.
3. **Coverage:** The "test (3.10)" workflow must verify **≥95% test coverage per module**.
4. **Approval:** At least **one approving review** from a human teammate is required.
5. **Admin Enforcement:** These rules apply to **all users**, including administrators. No bypasses.

### Pull Request Review Protocol (High Standard)
Reviewers must maintain **extreme engineering rigor** and keep the bar exceptionally high. A "High Standard" review is a non-negotiable requirement and must include:

1. **Executive Summary:** A concise overview of the PR's purpose and its impact on the project state.
2. **Requirements Verification:**
   - **Functional:** Ensure 100% of the features specified in the relevant `PHASE_X_SPEC.md` are implemented and function correctly.
   - **Non-Functional:** Verify performance, observability (logging), and resilience (error handling) meet project standards.
3. **Local Verification (Mandatory Isolated Review):** Reviewers MUST fetch the branch and verify results locally in an isolated environment to prevent workspace pollution and ensure reproducible verification that matches CI results.

   **Scope:** This is **MANDATORY** for "Complex PRs" (involving code changes in `src/` or `tests/`, configuration updates, or architectural docs) and **RECOMMENDED** for all others.

   **Workflow:**
   1. **Isolate:** Create a clean worktree:
      ```bash
      git fetch origin pull/ID/head:pr-ID
      git worktree add ../pr-review-ID pr-ID
      cd ../pr-review-ID
      ```
   2. **Initialize:** Set up the environment (crucial for accurate testing):
      ```bash
      python3.10 -m venv venv
      source venv/bin/activate
      pip install -r requirements.txt
      cp .env.template .env
      # Add dummy keys to .env if needed for non-integration tests
      ```
      *Note: This setup adds ~1-2 minutes per review but is essential to prevent false positives/negatives caused by dirty environments.*
   3. **Verify:** Run the verification suite:
      ```bash
      ./verify.sh
      ```
      - **100% Pass Rate** for automated tests.
      - **≥95% Coverage** per module.
      - **Zero Formatting/Linting/Type Issues.**
   4. **Cleanup:** Safely remove the worktree:
      ```bash
      cd ..
      git worktree remove pr-review-ID
      # Only if directory remains: rm -rf pr-review-ID
      ```

   **Environment Integrity Checks:**
   - [ ] No hardcoded paths (e.g., `/Users/username/...`)
   - [ ] No environment-specific imports (e.g., local-only packages)
   - [ ] No reliance on files outside repository (e.g., `~/config.yaml`)
   - [ ] All dependencies listed in `requirements.txt`
   - [ ] No OS-specific commands without cross-platform fallbacks
4. **Technical Assessment & Rigor:**
   - **Engineering Best Practices:** Adherence to SOLID, DRY, and KISS principles is mandatory.
   - **API Implementation:** Verify protocol security (HTTPS), parameter accuracy, and graceful error handling.
   - **Type Safety & Validation:** Ensure robust Pydantic usage and centralized validation.
   - **Architecture Alignment:** Check for proper delegation patterns and adherence to layered design.
5. **Security & Path Safety (Non-Negotiable):**
   - **Security First:** Verify all security checklist items are met. No compromises.
   - **Secrets Management:** Ensure no real keys are committed.
   - **Path Security:** Audit `.gitignore` and path sanitization logic.
6. **Final Assessment:** A clear "Status" (APPROVED or CHANGES REQUESTED) with a recommendation for action.

---

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

### 🧪 Test Coverage (Non-Negotiable)

**Test coverage is a BLOCKING requirement for all commits and pushes to remote.**

**Coverage Requirements:**
- **Target:** 100% test coverage for all new code
- **Minimum Acceptable:** 95% coverage per module
- **Overall Project:** Must maintain ≥95% coverage at all times

**If coverage falls below 95%, you MUST NOT commit or push. No exceptions.**

**Pragmatic Approach:**
- Aim for 100%, accept 95%+ with clear justification
- Every uncovered line must be documented with reason (e.g., "unreachable defensive code", "external library limitation")
- Coverage gaps must be tracked as technical debt and resolved within 1 sprint

**Coverage Verification Checklist:**
- [ ] Unit tests cover 100% of new functions/methods
- [ ] Integration tests cover all service interactions
- [ ] Edge cases have dedicated tests
- [ ] Error paths are fully tested
- [ ] `pytest --cov=src --cov-report=term-missing` shows ≥95%
- [ ] Any uncovered lines documented in verification report

### 🧪 Test-Driven Development (Required)

**No code should be pushed to remote without complete verification.**

Every feature must have:
1. **Automated Tests** (required):
   - Unit tests for all functions
   - Integration tests for service interactions
   - End-to-end tests for critical workflows
   - **Test coverage ≥95% (see Test Coverage section above)**
   - **100% pass rate required for all CI pipelines**

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
- **Overall Coverage:** X% (MUST be ≥95%)
- Unit Tests: X%
- Integration Tests: Y%
- Manual Tests: Z test cases

### Uncovered Lines (if any)
- `file.py:123` - Reason: [Defensive code for impossible state]
- `file.py:456` - Reason: [External library error handling]

**Coverage Status:** [PASS ✅ if ≥95%, FAIL ❌ if <95%]

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
- **All tests passing (100% pass rate)**
- **Test coverage ≥95% for all modified modules**
- All documentation updated
- Verification report generated with coverage proof

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
# Create virtual environment (requires Python 3.10+)
python3.10 -m venv venv
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

**Phase 2 Modules (✅ Complete & Production Ready):**
- **`src/services/pdf_service.py`**: PDF download, conversion, and cleanup management
- **`src/services/llm_service.py`**: Multi-provider LLM service (Claude/Gemini) with cost tracking
- **`src/services/extraction_service.py`**: Pipeline orchestration (PDF → conversion → LLM extraction)
- **`src/output/enhanced_generator.py`**: Enhanced markdown with extraction results and statistics

**Phase 3.1 Modules (✅ Complete - Concurrent Orchestration):**
- **`src/orchestration/concurrent_pipeline.py`**: Async producer-consumer pattern with worker pools
- **`src/models/concurrency.py`**: Resource limiting and backpressure models

**Test Coverage:**
- **408 automated tests** (100% pass rate)
- **98.12% overall coverage** (exceeds ≥95% requirement)
- **Production E2E verified** with real ArXiv papers and live Gemini LLM
- **Concurrent orchestration verified** with async worker pools and resource limiting

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

### Verification Script

**Always use `./verify.sh` before committing.**

The project includes a comprehensive verification script that runs all required checks:

```bash
./verify.sh
```

**What it checks:**
1. ✅ **Black** - Code formatting (zero changes required)
2. ✅ **Flake8** - Linting (zero issues)
3. ✅ **Mypy** - Type checking (zero errors)
4. ✅ **Pytest** - All tests pass with ≥95% coverage

**This script MUST pass 100% before:**
- Committing code
- Pushing to remote
- Creating a Pull Request

**If `./verify.sh` fails, you MUST NOT proceed. Fix all issues first.**

---

### Before Committing
1. **Run verification script:** `./verify.sh` (MUST pass 100%)
2. Review output for any warnings or issues
3. Security scan: Check for hardcoded secrets
4. Review security checklist
5. Generate verification report with coverage proof

### Before Pushing to Remote

**⚠️ BLOCKING REQUIREMENTS - ALL must pass:**

1. **`./verify.sh` must pass 100%** (Formatting, Linting, Types, Tests)
2. **All tests must pass** (100% pass rate, 0 failures)
3. **Coverage must be ≥95%** for all modified modules
   - Run: `pytest --cov=src --cov-report=term-missing --cov-fail-under=95`
   - Any module below 95% BLOCKS the push
   - Overall project coverage must remain ≥95%
4. **No linting errors** (Flake8 clean)
5. **No type errors** (Mypy clean)
6. **No formatting issues** (Black clean)
7. **Security checklist complete** (all items checked)
8. **Verification report generated** (includes coverage analysis)
9. **Feature specification 100% met** (all requirements implemented)

**If ANY requirement fails, you MUST NOT push. Fix issues first. No exceptions.**

**Coverage Enforcement:**
- If coverage < 95%: Add tests until ≥95%
- If legitimately uncoverable: Document in verification report
- If uncertain: Ask for clarification, do NOT push

### Pull Request Quality Checklist

**⚠️ CRITICAL: Run `./verify.sh` BEFORE creating a Pull Request**

**This checklist must be completed 100% before creating or updating any PR:**

1. **✅ Format Check (Black)**
   ```bash
   black .  # Format all files
   black --check .  # Verify no changes needed
   ```
   - Status: MUST show "All done! ✨ 🍰 ✨ ... files would be left unchanged"
   - If fails: Run `black .` and commit the formatting changes

2. **✅ Linting Check (Flake8)**
   ```bash
   flake8 src/ tests/
   ```
   - Status: MUST show 0 errors
   - Common issues to fix:
     - Unused imports (F401)
     - Line too long (E501) - max 88 characters
     - Undefined names (F821)

3. **✅ Type Check (Mypy)**
   ```bash
   mypy src/
   ```
   - Status: MUST show "Success: no issues found"
   - If fails: Fix all type errors before proceeding

4. **✅ Module-Level Coverage Check**
   ```bash
   pytest --cov=src --cov-report=term-missing
   ```
   - **CRITICAL:** Check coverage for EVERY modified module
   - **Minimum per module:** ≥95% (hard requirement)
   - **Overall project:** ≥95% (hard requirement)
   - If any module < 95%:
     - Add comprehensive tests for uncovered lines
     - Test exception handling, error paths, edge cases
     - Do NOT create PR until all modules ≥95%

5. **✅ Test Pass Rate**
   ```bash
   pytest tests/
   ```
   - Status: MUST show "X passed, 0 failed"
   - 100% pass rate required (zero failures allowed)

6. **✅ Verification Script**
   ```bash
   ./verify.sh
   ```
   - Status: MUST show "✅ All checks passed!"
   - This runs all checks above in one command
   - **If this fails, do NOT create PR**

7. **✅ Dependency Pinning**
   - All dependencies in `requirements.txt` use exact versions (`==`)
   - No loose version constraints (`>=`, `~=`, `^`)
   - Example: `diskcache==5.6.3` ✅, NOT `diskcache>=5.6.0` ❌

**After completing checklist:**
- Review the PR description to ensure it clearly explains what was changed and why
- Ensure all commits have clear, descriptive messages
- Link to relevant issues or documentation
- If addressing review feedback, respond to all comments

**Common Quality Gate Failures and Fixes:**

| Issue | Fix |
|-------|-----|
| Black formatting fails | Run `black .` and commit changes |
| Module coverage < 95% | Add tests for uncovered lines (exception handling, edge cases) |
| Flake8 unused imports | Remove unused imports |
| Flake8 line too long | Break line into multiple lines (max 88 chars) |
| Mypy type errors | Add proper type hints or use `# type: ignore` with justification |
| Test failures | Fix the code or test logic causing failure |
| Dependency not pinned | Change `>=X.Y.Z` to `==X.Y.Z` in requirements.txt |

**Remember: Quality gates exist to maintain code quality and prevent regressions. Running `./verify.sh` before creating a PR saves everyone time and ensures smooth reviews.**

### CI/CD Enforcement

**The CI pipeline enforces all quality gates automatically.**

**GitHub Actions Workflow (`ci.yml`):**
- Runs on: All pull requests and pushes to `main`
- Python Version: 3.10 (enforced)
- Checks:
  1. Black formatting
  2. Flake8 linting
  3. Mypy type checking
  4. Pytest with ≥95% coverage

**If CI fails, the PR cannot be merged.**

**Branch Protection Rules:**
- Direct pushes to `main` are **disabled**
- All changes must go through Pull Request
- At least 1 approving review required
- CI must pass (status checks required)
- Rules apply to all users, including admins

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
* **Coverage Requirements (BLOCKING):**
  - **Minimum:** ≥95% for all modules (hard requirement)
  - **Target:** 100% for all new code
  - **Project-wide:** Must maintain ≥95% at all times
  - **Verification:** Use `pytest --cov=src --cov-report=term-missing`
  - **Documentation:** Any line below 100% must be justified in verification report

* **Test Types:**
  - Unit tests: All functions and methods (100% coverage)
  - Integration tests: Service interactions
  - End-to-end tests: Full pipeline workflows
  - Edge case tests: Boundary conditions, error paths
  - Security tests: Input validation, path sanitization, injection attacks

* **Test Quality:**
  - Test both happy path and error paths
  - Test edge cases and boundary conditions
  - Test concurrent/async behavior where applicable
  - Use mocking for external dependencies
  - Assert on all return values and side effects

* **Test Naming:** `test_<function>_<scenario>` (e.g., `test_validate_query_rejects_injection`)

* **Coverage Enforcement:**
  - Pre-commit hook should reject commits with coverage <95%
  - CI/CD pipeline must fail on coverage <95%
  - Pull requests require coverage proof in description

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

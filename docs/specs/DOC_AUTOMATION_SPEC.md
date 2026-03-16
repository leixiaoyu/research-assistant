# Documentation Automation Specification
**Version:** 1.1
**Status:** 🔄 **Phase A In Progress** (Foundation)
**Timeline:** 2-3 weeks (phased implementation)
**Last Updated:** 2026-03-15
**Dependencies:**
- Existing spec-workflow MCP integration
- GitHub Actions infrastructure
- Pre-commit framework support

---

## Architecture Reference

This specification defines infrastructure tooling for documentation maintenance, supporting the development workflow as defined in [CLAUDE.md](../../CLAUDE.md).

**Architectural Gaps Addressed:**
- ❌ Gap: No automated enforcement of doc updates when code changes
- ❌ Gap: Manual process relies on humans to remember
- ❌ Gap: No CI check for code vs docs synchronization
- ❌ Gap: Documentation drift goes undetected until manual review

**Components Modified:**
- CI/CD: GitHub Actions workflows
- Development: Pre-commit hooks, verify.sh
- Documentation: PR template, CLAUDE.md

**Coverage Targets:**
- Validation scripts: ≥99%
- Zero false positives on existing codebase

---

## 1. Executive Summary

This specification defines an automated documentation maintenance system to ensure project documentation remains synchronized with code changes. The system addresses the documentation drift problem identified when Phase 5.3 implementation was complete but documentation still showed "Planning" status.

**What This Specification Is:**
- ✅ Pre-commit hooks for markdown linting and spell checking
- ✅ GitHub Actions CI for documentation drift detection
- ✅ Phase spec validation for status consistency
- ✅ PR template with documentation checklist

**What This Specification Is NOT:**
- ❌ AI-generated documentation content
- ❌ Hosted documentation site (Mintlify, ReadTheDocs)
- ❌ API documentation generation (Sphinx) - deferred to future
- ❌ Changes to existing spec content or format

**Key Achievement:** Make it impossible to merge code without corresponding documentation updates.

---

## 2. Problem Statement

### 2.1 The Documentation Drift Problem
Recent example: Phase 5.3 (CLI Command Splitting) was completed Feb 28, 2026 but documentation showed "📋 Planning" status until manually corrected on Mar 14, 2026.

### 2.2 Root Causes
1. **No automated enforcement** - Code can be merged without doc updates
2. **Manual process** - Relies on humans to remember
3. **No drift detection** - No CI check for code vs docs synchronization
4. **No validation** - Phase spec statuses not verified against implementation

### 2.3 Impact
- Stale documentation misleads developers and stakeholders
- Project status unclear from documentation alone
- Technical debt accumulates in documentation

---

## 3. Requirements

### 3.1 Pre-commit Validation

#### REQ-DOC-1.1: Markdown Linting
All markdown files SHALL be validated for formatting consistency before commit.

**Acceptance Criteria:**
- WHEN a markdown file is modified THEN markdownlint SHALL validate formatting
- IF formatting errors exist THEN commit SHALL be blocked with actionable error messages
- WHEN `--fix` flag is used THEN auto-fixable issues SHALL be corrected

#### REQ-DOC-1.2: Spell Checking
Documentation files SHALL be spell-checked before commit.

**Acceptance Criteria:**
- WHEN a markdown file is modified THEN codespell SHALL check for typos
- IF spelling errors are detected THEN commit SHALL be blocked
- WHEN technical terms are used THEN custom dictionary SHALL prevent false positives

### 3.2 CI/CD Enforcement

#### REQ-DOC-2.1: Documentation Drift Detection
CI pipeline SHALL detect when code changes without corresponding documentation updates.

**Acceptance Criteria:**
- WHEN files in `src/` are modified THEN CI SHALL check if relevant docs are updated
- IF code changes but no doc changes exist THEN PR status check SHALL fail
- WHEN only tests are added THEN doc requirement MAY be waived via label

#### REQ-DOC-2.2: Phase Status Validation
CI pipeline SHALL validate phase specification statuses match implementation state.

**Acceptance Criteria:**
- WHEN a phase spec shows "Complete" THEN completion indicators SHALL exist
- IF spec status is "Planning" but completion indicators exist THEN warning SHALL be emitted

### 3.3 Developer Experience

#### REQ-DOC-3.1: PR Documentation Checklist
All PRs SHALL include a documentation checklist in the template.

**Acceptance Criteria:**
- WHEN PR is created THEN documentation checklist SHALL be included
- IF checklist items are unchecked THEN reviewer SHALL verify justification

#### REQ-DOC-3.2: Escape Hatches
Developers SHALL have mechanisms to bypass checks when justified.

**Acceptance Criteria:**
- WHEN `docs-not-required` label is added THEN drift check SHALL pass
- WHEN `--no-verify` flag is used THEN pre-commit SHALL be skipped (local only)

---

## 4. Technical Design

### 4.1 Pre-commit Configuration

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/DavidAnson/markdownlint-cli2
    rev: v0.13.0
    hooks:
      - id: markdownlint-cli2
        args: ["--fix"]
        files: \.(md|markdown)$

  - repo: https://github.com/codespell-project/codespell
    rev: v2.3.0
    hooks:
      - id: codespell
        args:
          - "--skip=*.json,*.lock,*.csv,venv/*,__pycache__/*"
          - "--ignore-words=.codespell-ignore"
        files: \.(md|py|yaml|yml|txt)$
```

### 4.2 Markdownlint Configuration

```json
// .markdownlint.json
{
  "default": true,
  "MD013": {
    "line_length": 120,
    "code_blocks": false,
    "tables": false
  },
  "MD024": { "siblings_only": true },
  "MD033": { "allowed_elements": ["br", "sup", "sub", "details", "summary"] },
  "MD041": false,
  "MD046": { "style": "fenced" }
}
```

### 4.3 GitHub Actions Workflow

```yaml
# .github/workflows/docs-validation.yml
name: Documentation Validation

on:
  pull_request:
    branches: [main]
    paths:
      - '**.md'
      - 'src/**'
      - 'docs/**'

jobs:
  lint-markdown:
    name: Lint Markdown
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: DavidAnson/markdownlint-cli2-action@v16
        with:
          globs: "**/*.md"
          config: ".markdownlint.json"

  check-spelling:
    name: Check Spelling
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: codespell-project/actions-codespell@v2
        with:
          skip: "*.json,*.lock,*.csv"
          ignore_words_file: .codespell-ignore

  check-doc-drift:
    name: Documentation Drift
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Check for documentation drift
        run: |
          BASE_SHA="${{ github.event.pull_request.base.sha }}"
          HEAD_SHA="${{ github.event.pull_request.head.sha }}"

          CHANGED_SRC=$(git diff --name-only $BASE_SHA...$HEAD_SHA | grep "^src/" || true)
          CHANGED_DOCS=$(git diff --name-only $BASE_SHA...$HEAD_SHA | grep -E "^(docs/|CLAUDE.md)" || true)

          if [ -n "$CHANGED_SRC" ] && [ -z "$CHANGED_DOCS" ]; then
            echo "::error::Source code changed but no documentation updated"
            exit 1
          fi
          echo "Documentation check passed"

  validate-phase-specs:
    name: Validate Phase Specs
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.14'
      - name: Validate phase specifications
        run: python scripts/validate_phase_specs.py
```

### 4.4 Phase Spec Validation Script

```python
#!/usr/bin/env python3
"""scripts/validate_phase_specs.py - Validate phase spec statuses."""

import re
import sys
from pathlib import Path

SPECS_DIR = Path("docs/specs")

COMPLETION_PATTERNS = [
    r"✅\s*(Complete|COMPLETED)",
    r"Completed\s+\w+\s+\d+,\s+\d{4}",
    r"##\s*\d+\.\s*File Size Results",
]

def validate_specs():
    issues = []
    for spec_file in SPECS_DIR.glob("PHASE_*.md"):
        content = spec_file.read_text()
        status_match = re.search(r'\*\*Status:\*\*\s*(.+)', content)
        if not status_match:
            continue

        status = status_match.group(1).strip()
        has_completion = any(re.search(p, content) for p in COMPLETION_PATTERNS)

        if "Planning" in status and has_completion:
            issues.append(f"WARN: {spec_file.name} shows 'Planning' but has completion indicators")
        if "Complete" in status and "📋" not in status and not has_completion:
            issues.append(f"ERROR: {spec_file.name} shows 'Complete' but no indicators found")

    return issues

if __name__ == "__main__":
    issues = validate_specs()
    for issue in issues:
        print(issue)
    sys.exit(1 if any("ERROR" in i for i in issues) else 0)
```

### 4.5 PR Template Update

```markdown
<!-- Add to .github/pull_request_template.md -->

## Documentation Checklist

**Required for code changes:**
- [ ] CLAUDE.md updated if workflow changes
- [ ] Phase spec status updated if phase completed
- [ ] PHASED_DELIVERY_PLAN.md timeline updated
- [ ] Test stats updated if coverage changes

**Documentation not needed because:**
- [ ] Test-only changes
- [ ] Internal refactoring with no API changes
```

### 4.6 verify.sh Integration

```bash
# Add to verify.sh

echo "Running documentation checks..."

if command -v markdownlint-cli2 &> /dev/null; then
    markdownlint-cli2 "**/*.md" --config .markdownlint.json && \
      echo "  Markdown formatting valid" || \
      { echo "  Markdown issues found"; FAILED=1; }
fi

if command -v codespell &> /dev/null; then
    codespell docs/ CLAUDE.md --skip="*.json" -q 3 && \
      echo "  Spelling check passed" || \
      { echo "  Spelling errors found"; FAILED=1; }
fi

if [ -f "scripts/validate_phase_specs.py" ]; then
    python scripts/validate_phase_specs.py && \
      echo "  Phase specifications valid" || \
      { echo "  Phase spec issues found"; FAILED=1; }
fi
```

---

## 5. Security Requirements 🔒

### SR-DOC-1: No Secrets in Documentation
- [ ] Documentation SHALL NOT contain API keys or credentials
- [ ] Example configs SHALL use placeholder values

### SR-DOC-2: Safe Script Execution
- [ ] Validation scripts SHALL NOT modify files
- [ ] Scripts SHALL use read-only operations

---

## 6. Implementation Tasks

### Task 1: Pre-commit Setup (0.5 day)
**Files:** `.pre-commit-config.yaml`, `.markdownlint.json`, `.codespell-ignore`

1. Create pre-commit configuration
2. Add markdownlint rules
3. Add codespell custom dictionary
4. Test on existing codebase

### Task 2: GitHub Actions Workflow (0.5 day)
**Files:** `.github/workflows/docs-validation.yml`

1. Create markdown linting job
2. Create doc drift detection job
3. Add phase spec validation job
4. Test with sample PR

### Task 3: Phase Spec Validation Script (0.5 day)
**Files:** `scripts/validate_phase_specs.py`

1. Create validation script
2. Add unit tests for script
3. Integrate with CI workflow

### Task 4: PR Template Update (0.25 day)
**Files:** `.github/pull_request_template.md`

1. Add documentation checklist section
2. Add justification options

### Task 5: verify.sh Integration (0.25 day)
**Files:** `verify.sh`

1. Add markdown linting check
2. Add spell check
3. Add phase validation

### Task 6: Documentation & Rollout (0.5 day)
**Files:** `CLAUDE.md`

1. Document new requirements in CLAUDE.md
2. Add installation instructions
3. Communicate to team

---

## 7. Verification Criteria

### 7.1 Unit Tests
- `test_phase_spec_validation_detects_mismatch`: Script detects status inconsistencies
- `test_phase_spec_validation_passes_valid`: Script passes valid specs

### 7.2 Integration Tests
- `test_pr_without_docs_fails`: PR with code but no docs fails CI
- `test_pr_with_docs_passes`: PR with code and docs passes CI
- `test_precommit_catches_errors`: Pre-commit blocks bad markdown

### 7.3 Manual Verification
- [ ] Pre-commit hooks work locally
- [ ] GitHub Actions workflow runs on PR
- [ ] verify.sh includes doc validation

---

## 8. Rollout Plan

### Phase A: Foundation (Week 1)
**Goal:** Basic validation without blocking

1. Add pre-commit hooks (optional for developers)
2. Add GitHub Actions (warning only)
3. Update verify.sh
4. Gather feedback on false positives

### Phase B: Enforcement (Week 2)
**Goal:** Enforce documentation requirements

1. Enable branch protection for doc checks
2. Make checks required in CI
3. Add PR template checklist
4. Address false positive feedback

### Phase C: Enhancement (Week 3)
**Goal:** Add optional advanced features

1. Add doctest validation (if ready)
2. Consider Sphinx API documentation
3. Document lessons learned

---

## 9. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| False positives blocking PRs | High | Medium | Start with warnings, then enforce |
| Developer friction | Medium | Medium | Clear error messages, escape hatches |
| Slow CI pipeline | Low | Low | Run doc checks in parallel |

---

## 10. Related Documents

- [CLAUDE.md](../../CLAUDE.md) - Project instructions and conventions
- [SYSTEM_ARCHITECTURE.md](../SYSTEM_ARCHITECTURE.md) - Architecture overview
- [PHASED_DELIVERY_PLAN.md](../PHASED_DELIVERY_PLAN.md) - Project timeline
- [PHASE_5_OVERVIEW.md](./PHASE_5_OVERVIEW.md) - Code health initiative (related)

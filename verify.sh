#!/bin/bash
set -e

# ARISP Quality Verification Script
# This script runs all checks required for PR approval.
# Automatically uses venv Python if available for complete dependency coverage.

# Get repository root
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

# Detect Python 3.14 command - prefer venv Python for full dependency coverage
if [ -f "$REPO_ROOT/venv/bin/python3.14" ]; then
    PYTHON_CMD="$REPO_ROOT/venv/bin/python3.14"
elif [ -f "$REPO_ROOT/venv/bin/python3" ]; then
    PYTHON_CMD="$REPO_ROOT/venv/bin/python3"
elif command -v python3.14 &> /dev/null; then
    PYTHON_CMD="python3.14"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    echo "❌ Error: Python 3.14+ not found. Please install Python 3.14 or higher."
    exit 1
fi

# Verify Python version is 3.14+
PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 14 ]); then
    echo "❌ Error: Python 3.14+ required, found $PYTHON_VERSION"
    exit 1
fi

echo "🐍 Using Python: $("$PYTHON_CMD" --version)"
echo ""

echo "🔍 Running Black (formatting)..."
"$PYTHON_CMD" -m black --check src/ tests/

echo "🔍 Running Flake8 (linting)..."
"$PYTHON_CMD" -m flake8 src/ tests/

echo "🔍 Running Mypy (type checking)..."
"$PYTHON_CMD" -m mypy src/

echo "🔍 Running Pragma Audit..."
# Comprehensive pragma audit across all code
# Different limits per category based on legitimate use cases

# Total count across all source code
TOTAL_PRAGMA_COUNT=$(grep -r "pragma: no cover" src/ --include="*.py" 2>/dev/null | wc -l | tr -d ' ')
TOTAL_PRAGMA_LIMIT=102  # Overall limit for entire codebase (Phase 8 DRA adds 7, Phase 9 Intelligence adds 17: 13 Protocol abstracts + 4 defensive)

echo "   Total pragma count: $TOTAL_PRAGMA_COUNT (limit: $TOTAL_PRAGMA_LIMIT)"

# Critical paths: orchestration, persistence, security (strict limits)
ORCH_PRAGMA_COUNT=$(grep -r "pragma: no cover" src/orchestration/ --include="*.py" 2>/dev/null | wc -l | tr -d ' ')
ORCH_PRAGMA_LIMIT=5

# Security code (utils/security.py) - should have minimal pragmas
SECURITY_PRAGMA_COUNT=$(grep -c "pragma: no cover" src/utils/security.py 2>/dev/null || true)
SECURITY_PRAGMA_COUNT=${SECURITY_PRAGMA_COUNT:-0}
SECURITY_PRAGMA_COUNT=$(echo "$SECURITY_PRAGMA_COUNT" | tr -d '[:space:]')
SECURITY_PRAGMA_LIMIT=8

# Models should have zero pragmas (pure data structures)
MODELS_PRAGMA_COUNT=$(grep -r "pragma: no cover" src/models/ --include="*.py" 2>/dev/null | wc -l | tr -d ' ')
MODELS_PRAGMA_LIMIT=0

AUDIT_FAILED=0

if [ "$TOTAL_PRAGMA_COUNT" -gt "$TOTAL_PRAGMA_LIMIT" ]; then
    echo "❌ Error: Too many pragma: no cover tags overall ($TOTAL_PRAGMA_COUNT > $TOTAL_PRAGMA_LIMIT)"
    AUDIT_FAILED=1
fi

if [ "$ORCH_PRAGMA_COUNT" -gt "$ORCH_PRAGMA_LIMIT" ]; then
    echo "❌ Error: Too many pragma tags in orchestration code ($ORCH_PRAGMA_COUNT > $ORCH_PRAGMA_LIMIT)"
    echo "   Coverage exclusions are prohibited for orchestration code."
    grep -rn "pragma: no cover" src/orchestration/ --include="*.py"
    AUDIT_FAILED=1
else
    echo "   Orchestration: $ORCH_PRAGMA_COUNT (limit: $ORCH_PRAGMA_LIMIT) ✓"
fi

if [ "$SECURITY_PRAGMA_COUNT" -gt "$SECURITY_PRAGMA_LIMIT" ]; then
    echo "❌ Error: Too many pragma tags in security code ($SECURITY_PRAGMA_COUNT > $SECURITY_PRAGMA_LIMIT)"
    grep -n "pragma: no cover" src/utils/security.py
    AUDIT_FAILED=1
else
    echo "   Security: $SECURITY_PRAGMA_COUNT (limit: $SECURITY_PRAGMA_LIMIT) ✓"
fi

if [ "$MODELS_PRAGMA_COUNT" -gt "$MODELS_PRAGMA_LIMIT" ]; then
    echo "❌ Error: Pragma tags found in models code ($MODELS_PRAGMA_COUNT > $MODELS_PRAGMA_LIMIT)"
    echo "   Models are pure data structures and should have 100% coverage."
    grep -rn "pragma: no cover" src/models/ --include="*.py"
    AUDIT_FAILED=1
else
    echo "   Models: $MODELS_PRAGMA_COUNT (limit: $MODELS_PRAGMA_LIMIT) ✓"
fi

if [ "$AUDIT_FAILED" -eq 1 ]; then
    echo ""
    echo "❌ Pragma audit failed. Review coverage exclusions."
    exit 1
fi

echo "   ✓ Pragma audit passed"

echo "📝 Running Documentation Validation..."
DOC_FAILED=0

# Markdown linting (optional - only if markdownlint-cli2 is installed)
if command -v markdownlint-cli2 &> /dev/null; then
    echo "   Running markdownlint..."
    if markdownlint-cli2 "**/*.md" --config .markdownlint.json 2>/dev/null; then
        echo "   ✓ Markdown formatting valid"
    else
        echo "   ⚠ Markdown issues found (non-blocking in Phase A)"
    fi
else
    echo "   ⊘ markdownlint-cli2 not installed, skipping"
fi

# Spell checking (optional - only if codespell is installed)
if command -v codespell &> /dev/null; then
    echo "   Running codespell..."
    if codespell docs/ CLAUDE.md README.md --skip="*.json,*.lock" -q 3 2>/dev/null; then
        echo "   ✓ Spelling check passed"
    else
        echo "   ⚠ Spelling errors found (non-blocking in Phase A)"
    fi
else
    echo "   ⊘ codespell not installed, skipping"
fi

# Phase spec validation
if [ -f "scripts/validate_phase_specs.py" ]; then
    echo "   Running phase spec validation..."
    if "$PYTHON_CMD" scripts/validate_phase_specs.py; then
        echo "   ✓ Phase specifications valid"
    else
        echo "   ⚠ Phase spec issues found (non-blocking in Phase A)"
    fi
else
    echo "   ⊘ Phase spec validation script not found, skipping"
fi

echo "🧪 Running Tests with Coverage (>=99% required, branch coverage enabled)..."
# Use absolute path for coverage to ensure consistency
# Note: branch coverage is now enabled in pyproject.toml
"$PYTHON_CMD" -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=99 tests/

echo "✅ All checks passed!"

#!/bin/bash
set -e

# ARISP Quality Verification Script
# This script runs all checks required for PR approval.
# IMPORTANT: Run this script inside an activated virtual environment.

# Detect Python 3.10 command
if command -v python3.10 &> /dev/null; then
    PYTHON_CMD="python3.10"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
    # Verify it's Python 3.10+
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
    MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 10 ]); then
        echo "❌ Error: Python 3.10+ required, found $PYTHON_VERSION"
        exit 1
    fi
else
    echo "❌ Error: Python 3.10+ not found. Please install Python 3.10 or higher."
    exit 1
fi

echo "🐍 Using Python: $($PYTHON_CMD --version)"
echo ""

echo "🔍 Running Black (formatting)..."
$PYTHON_CMD -m black --check src/ tests/

echo "🔍 Running Flake8 (linting)..."
$PYTHON_CMD -m flake8 src/ tests/

echo "🔍 Running Mypy (type checking)..."
$PYTHON_CMD -m mypy src/

echo "🔍 Running Pragma Audit..."
# Count pragma: no cover occurrences in orchestration code specifically
# (where pragma masking is prohibited per CLAUDE.md)
ORCH_PRAGMA_COUNT=$(grep -r "pragma: no cover" src/orchestration/ --include="*.py" 2>/dev/null | wc -l | tr -d ' ')
ORCH_PRAGMA_LIMIT=5  # Orchestration code should have minimal pragmas

if [ "$ORCH_PRAGMA_COUNT" -gt "$ORCH_PRAGMA_LIMIT" ]; then
    echo "❌ Error: Too many pragma: no cover tags in orchestration code ($ORCH_PRAGMA_COUNT > $ORCH_PRAGMA_LIMIT)"
    echo "   Coverage exclusions are prohibited for orchestration, persistence, and security code."
    echo "   Found occurrences:"
    grep -rn "pragma: no cover" src/orchestration/ --include="*.py"
    exit 1
else
    echo "   Orchestration pragma count: $ORCH_PRAGMA_COUNT (limit: $ORCH_PRAGMA_LIMIT) ✓"
fi

echo "🧪 Running Tests with Coverage (>=99% required)..."
# Use absolute path for coverage to ensure consistency
$PYTHON_CMD -m pytest --cov=src --cov-report=term-missing --cov-fail-under=99 tests/

echo "✅ All checks passed!"

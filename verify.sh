#!/bin/bash
set -e

# ARISP Quality Verification Script
# This script runs all checks required for PR approval.

echo "🔍 Running Black (formatting)..."
python -m black --check src/ tests/

echo "🔍 Running Flake8 (linting)..."
python -m flake8 src/ tests/

echo "🔍 Running Mypy (type checking)..."
python -m mypy src/

echo "🧪 Running Tests with Coverage (>=95% required)..."
# Use absolute path for coverage to ensure consistency
python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=95 tests/

echo "✅ All checks passed!"

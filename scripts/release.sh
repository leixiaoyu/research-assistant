#!/bin/bash
set -e

VERSION=$1
ALLOW_LOW_EXCEPTIONS=false

# Parse flags
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --allow-low-exceptions) ALLOW_LOW_EXCEPTIONS=true ;;
        *) VERSION=$1 ;;
    esac
    shift
done

if [ -z "$VERSION" ]; then
    echo "Usage: ./scripts/release.sh <version> [--allow-low-exceptions]"
    exit 1
fi

echo "🔒 Running mandatory security review..."
REPORT_FILE="security-review-${VERSION}.md"
EXCEPTIONS_FILE="security-exceptions-${VERSION}.md"

# Run Claude Code security review (REQUIRED)
if ! command -v claude &> /dev/null; then
    echo "❌ Claude Code CLI not installed. Cannot proceed with release."
    echo "Install: https://claude.ai/code"
    exit 1
fi

if ! claude "/oh-my-claudecode:security-review src/" > "$REPORT_FILE" 2>&1; then
    echo "❌ Security review command failed"
    echo "Output:"
    cat "$REPORT_FILE" 2>/dev/null || echo "(no output)"
    exit 1
fi

# CRITICAL FIX: Check if report exists AND is non-empty
if [ ! -f "$REPORT_FILE" ]; then
    echo "❌ Security review report was not generated"
    exit 1
fi

if [ ! -s "$REPORT_FILE" ]; then
    echo "❌ Security review report is empty"
    exit 1
fi

# Check for CRITICAL/HIGH/MEDIUM findings (always block)
if grep -qE "CRITICAL|HIGH|MEDIUM" "$REPORT_FILE"; then
    echo "❌ Security review found issues that MUST be resolved:"
    grep -E "CRITICAL|HIGH|MEDIUM" "$REPORT_FILE"
    echo ""
    echo "All CRITICAL, HIGH, and MEDIUM issues must be fixed before release."
    echo "Review full report: $REPORT_FILE"
    exit 1
fi

# Check for LOW findings
if grep -q "LOW" "$REPORT_FILE"; then
    LOW_COUNT=$(grep -c "LOW" "$REPORT_FILE" || echo "0")
    echo "⚠️  Found $LOW_COUNT LOW severity findings."

    if [ "$ALLOW_LOW_EXCEPTIONS" = true ]; then
        if [ ! -f "$EXCEPTIONS_FILE" ]; then
            echo "❌ --allow-low-exceptions requires $EXCEPTIONS_FILE"
            echo ""
            echo "Create exceptions file with justification for each LOW finding:"
            echo "  ## LOW-001: [Finding title]"
            echo "  **Justification:** [Why this cannot be fixed now]"
            echo "  **Tracking:** [Issue/ticket number for future fix]"
            exit 1
        fi

        echo "✅ LOW exceptions documented in $EXCEPTIONS_FILE"
        echo "⚠️  These will be reviewed in the next release cycle."
    else
        echo "❌ LOW severity issues must be resolved OR use --allow-low-exceptions"
        echo ""
        echo "Options:"
        echo "  1. Fix all LOW issues (recommended)"
        echo "  2. Document justifications in $EXCEPTIONS_FILE and use:"
        echo "     ./scripts/release.sh $VERSION --allow-low-exceptions"
        exit 1
    fi
fi

echo "✅ Security review passed (no CRITICAL/HIGH/MEDIUM issues)"

# Run all CI checks locally
echo "🧪 Running full verification..."
./verify.sh || { echo "❌ Verification failed"; exit 1; }

# Create release artifacts
echo "📦 Creating release tag v${VERSION}..."

if [ -f "$EXCEPTIONS_FILE" ]; then
    git add "$EXCEPTIONS_FILE"
    git commit -m "docs: Add security exceptions for v${VERSION}"
fi

git tag -a "v${VERSION}" -m "Release v${VERSION}" \
    -m "Security review: $REPORT_FILE" \
    -m "Exceptions: ${EXCEPTIONS_FILE:-none}"

echo "✅ Release v${VERSION} ready. Push with: git push origin v${VERSION}"

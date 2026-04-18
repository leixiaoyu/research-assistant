#!/bin/bash
#
# Setup Git hooks for the ARISP project.
# This script installs all project hooks from scripts/hooks/ to .git/hooks/
#
# Usage:
#   ./scripts/setup_hooks.sh
#
# What it does:
#   1. Copies hooks from scripts/hooks/ to .git/hooks/
#   2. Makes them executable
#   3. Preserves any existing custom hooks (backs them up)
#
# Hooks installed:
#   - pre-commit: Runs ./verify.sh before each commit

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Git Hooks Setup for ARISP${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Get script directory and repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Verify we're in the right place
if [ ! -d "$REPO_ROOT/.git" ]; then
    echo -e "${RED}ERROR: Not in a git repository${NC}"
    exit 1
fi

if [ ! -d "$SCRIPT_DIR/hooks" ]; then
    echo -e "${RED}ERROR: hooks directory not found at $SCRIPT_DIR/hooks${NC}"
    exit 1
fi

# Create .git/hooks if it doesn't exist
mkdir -p "$REPO_ROOT/.git/hooks"

# Track what we install
INSTALLED=0
BACKED_UP=0

# Install each hook
for hook in "$SCRIPT_DIR/hooks"/*; do
    if [ -f "$hook" ]; then
        HOOK_NAME=$(basename "$hook")
        TARGET="$REPO_ROOT/.git/hooks/$HOOK_NAME"

        # Check if there's an existing custom hook (not a sample)
        if [ -f "$TARGET" ] && [ ! -f "$TARGET.sample" ]; then
            # Compare to see if it's different from ours
            if ! cmp -s "$hook" "$TARGET"; then
                BACKUP="$TARGET.backup.$(date +%Y%m%d_%H%M%S)"
                echo -e "${YELLOW}Backing up existing $HOOK_NAME to ${BACKUP}${NC}"
                cp "$TARGET" "$BACKUP"
                ((BACKED_UP++))
            fi
        fi

        # Copy the hook
        cp "$hook" "$TARGET"
        chmod +x "$TARGET"
        echo -e "${GREEN}✓ Installed: $HOOK_NAME${NC}"
        ((INSTALLED++))
    fi
done

echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Hooks installed: ${GREEN}$INSTALLED${NC}"
if [ $BACKED_UP -gt 0 ]; then
    echo -e "  Existing hooks backed up: ${YELLOW}$BACKED_UP${NC}"
fi

echo -e "\n${BLUE}What happens now:${NC}"
echo -e "  • Before each commit, ./verify.sh will run automatically"
echo -e "  • If any check fails, the commit will be blocked"
echo -e "  • To bypass (emergencies only): git commit --no-verify"

echo -e "\n${YELLOW}Tip: Add this to your onboarding docs:${NC}"
echo -e "  ${BLUE}./scripts/setup_hooks.sh${NC}"

#!/bin/bash
# =============================================================================
# setup_git_aliases.sh - Configure required git aliases for this project
# =============================================================================
#
# This script sets up git aliases required by the project's development
# workflow, including the worktree protection alias.
#
# Usage:
#   ./scripts/setup_git_aliases.sh
#
# =============================================================================

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo "=============================================="
echo " Git Alias Setup for research-assist"
echo "=============================================="
echo ""

# Get the repository root
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo -e "${BLUE}[INFO]${NC} Repository root: $REPO_ROOT"
echo ""

# =============================================================================
# Alias: git wt-remove (Worktree Safe Removal)
# =============================================================================

echo -e "${BLUE}[1/1]${NC} Configuring 'git wt-remove' alias..."

# Check if alias already exists
EXISTING_ALIAS=$(git config --global --get alias.wt-remove 2>/dev/null || echo "")

if [ -n "$EXISTING_ALIAS" ]; then
    echo -e "${YELLOW}[WARNING]${NC} Alias 'wt-remove' already exists:"
    echo "  Current: $EXISTING_ALIAS"
    echo ""
    read -p "Do you want to overwrite it? [y/N]: " overwrite
    if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}[INFO]${NC} Skipping wt-remove alias"
    else
        git config --global alias.wt-remove '!f() {
            SCRIPT="$(git rev-parse --show-toplevel)/scripts/safe_worktree_remove.sh"
            if [ -f "$SCRIPT" ]; then
                "$SCRIPT" "$@"
            else
                echo "ERROR: safe_worktree_remove.sh not found at $SCRIPT"
                echo "Make sure you are in a repository with the worktree protection script."
                exit 1
            fi
        }; f'
        echo -e "${GREEN}[OK]${NC} Alias 'wt-remove' updated"
    fi
else
    git config --global alias.wt-remove '!f() {
        SCRIPT="$(git rev-parse --show-toplevel)/scripts/safe_worktree_remove.sh"
        if [ -f "$SCRIPT" ]; then
            "$SCRIPT" "$@"
        else
            echo "ERROR: safe_worktree_remove.sh not found at $SCRIPT"
            echo "Make sure you are in a repository with the worktree protection script."
            exit 1
        fi
    }; f'
    echo -e "${GREEN}[OK]${NC} Alias 'wt-remove' configured"
fi

echo ""
echo "=============================================="
echo -e "${GREEN} Setup Complete!${NC}"
echo "=============================================="
echo ""
echo "Available aliases:"
echo "  git wt-remove <path>  - Safely remove a worktree with validation"
echo ""
echo "Usage example:"
echo "  git wt-remove /path/to/worktree"
echo ""
echo "To verify:"
echo "  git config --global --get alias.wt-remove"
echo ""

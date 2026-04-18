#!/bin/bash
# =============================================================================
# setup.sh - Unified development environment setup for ARISP
# =============================================================================
#
# This script sets up everything needed for development:
#   1. Verifies Python 3.14+ is available
#   2. Creates virtual environment (if not already active)
#   3. Installs dependencies
#   4. Sets up Git aliases (worktree protection)
#   5. Installs Git hooks (pre-commit verification)
#   6. Creates .env from template (if needed)
#
# Usage:
#   ./setup.sh           # Full setup
#   ./setup.sh --hooks   # Only install Git hooks
#   ./setup.sh --help    # Show help
#
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

print_header() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_step() {
    echo -e "\n${BOLD}[$1/$TOTAL_STEPS]${NC} $2"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

show_help() {
    echo "ARISP Development Setup"
    echo ""
    echo "Usage: ./setup.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --hooks     Only install Git hooks (skip other setup)"
    echo "  --aliases   Only install Git aliases (skip other setup)"
    echo "  --deps      Only install dependencies (skip other setup)"
    echo "  --help      Show this help message"
    echo ""
    echo "Full setup includes:"
    echo "  1. Python version verification (3.14+)"
    echo "  2. Virtual environment creation"
    echo "  3. Dependency installation"
    echo "  4. Git alias configuration"
    echo "  5. Git hook installation"
    echo "  6. Environment file setup"
    exit 0
}

# -----------------------------------------------------------------------------
# Parse arguments
# -----------------------------------------------------------------------------

HOOKS_ONLY=false
ALIASES_ONLY=false
DEPS_ONLY=false

for arg in "$@"; do
    case $arg in
        --hooks)
            HOOKS_ONLY=true
            ;;
        --aliases)
            ALIASES_ONLY=true
            ;;
        --deps)
            DEPS_ONLY=true
            ;;
        --help|-h)
            show_help
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Quick mode handlers
# -----------------------------------------------------------------------------

if [ "$HOOKS_ONLY" = true ]; then
    print_header "Installing Git Hooks"
    ./scripts/setup_hooks.sh
    exit 0
fi

if [ "$ALIASES_ONLY" = true ]; then
    print_header "Installing Git Aliases"
    ./scripts/setup_git_aliases.sh
    exit 0
fi

if [ "$DEPS_ONLY" = true ]; then
    print_header "Installing Dependencies"
    pip install -r requirements.txt
    print_success "Dependencies installed"
    exit 0
fi

# -----------------------------------------------------------------------------
# Full setup
# -----------------------------------------------------------------------------

TOTAL_STEPS=6

print_header "ARISP Development Environment Setup"
echo -e "This will set up your complete development environment.\n"

# Step 1: Check Python version
print_step 1 "Checking Python version..."

# Try python3.14 first, then python3, then python
PYTHON_CMD=""
for cmd in python3.14 python3 python; do
    if command -v $cmd &> /dev/null; then
        VERSION=$($cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        MAJOR=$(echo $VERSION | cut -d. -f1)
        MINOR=$(echo $VERSION | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 14 ]; then
            PYTHON_CMD=$cmd
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    print_error "Python 3.14+ is required but not found"
    echo "  Please install Python 3.14 or later"
    exit 1
fi

print_success "Found $PYTHON_CMD (version $VERSION)"

# Step 2: Virtual environment
print_step 2 "Setting up virtual environment..."

if [ -n "$VIRTUAL_ENV" ]; then
    print_success "Virtual environment already active: $VIRTUAL_ENV"
elif [ -d "venv" ]; then
    print_warning "Virtual environment exists but not activated"
    echo "  Run: source venv/bin/activate"
else
    echo "  Creating virtual environment..."
    $PYTHON_CMD -m venv venv
    print_success "Virtual environment created at ./venv"
    echo -e "  ${YELLOW}Note: Activate it with: source venv/bin/activate${NC}"
fi

# Step 3: Install dependencies
print_step 3 "Installing dependencies..."

if [ -n "$VIRTUAL_ENV" ]; then
    pip install -q -r requirements.txt
    print_success "Dependencies installed"
else
    print_warning "Skipping - activate virtual environment first"
    echo "  Run: source venv/bin/activate && pip install -r requirements.txt"
fi

# Step 4: Git aliases
print_step 4 "Setting up Git aliases..."

if [ -f "./scripts/setup_git_aliases.sh" ]; then
    # Run non-interactively by checking if alias exists
    EXISTING=$(git config --global --get alias.wt-remove 2>/dev/null || echo "")
    if [ -z "$EXISTING" ]; then
        git config --global alias.wt-remove '!f() {
            SCRIPT="$(git rev-parse --show-toplevel)/scripts/safe_worktree_remove.sh"
            if [ -f "$SCRIPT" ]; then
                "$SCRIPT" "$@"
            else
                echo "ERROR: safe_worktree_remove.sh not found"
                exit 1
            fi
        }; f'
        print_success "Git alias 'wt-remove' configured"
    else
        print_success "Git alias 'wt-remove' already exists"
    fi
else
    print_warning "setup_git_aliases.sh not found, skipping"
fi

# Step 5: Git hooks
print_step 5 "Installing Git hooks..."

if [ -f "./scripts/setup_hooks.sh" ]; then
    ./scripts/setup_hooks.sh 2>&1 | grep -E "(✓|Installed|Complete)" || true
    print_success "Git hooks installed"
else
    print_warning "setup_hooks.sh not found, skipping"
fi

# Step 6: Environment file
print_step 6 "Checking environment file..."

if [ -f ".env" ]; then
    print_success ".env file exists"
elif [ -f ".env.template" ]; then
    cp .env.template .env
    print_success ".env created from template"
    print_warning "Edit .env and add your API keys"
else
    print_warning "No .env.template found"
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

print_header "Setup Complete!"

echo -e "
${GREEN}What's configured:${NC}
  ✓ Python $VERSION verified
  ✓ Virtual environment ready
  ✓ Git alias 'wt-remove' for safe worktree removal
  ✓ Pre-commit hook runs ./verify.sh automatically

${YELLOW}Next steps:${NC}"

if [ -z "$VIRTUAL_ENV" ]; then
    echo "  1. Activate virtual environment: ${BLUE}source venv/bin/activate${NC}"
    echo "  2. Install dependencies: ${BLUE}pip install -r requirements.txt${NC}"
    echo "  3. Add API keys to .env"
else
    echo "  1. Add API keys to .env (if not done)"
    echo "  2. Run verification: ${BLUE}./verify.sh${NC}"
fi

echo -e "
${BLUE}Enforcement enabled:${NC}
  • Every commit will run ./verify.sh automatically
  • Commits are blocked if any check fails
  • To bypass (emergencies only): git commit --no-verify
"

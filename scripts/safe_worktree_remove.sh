#!/bin/bash
# =============================================================================
# safe_worktree_remove.sh - Safe Git Worktree Removal with Validation
# =============================================================================
#
# This script validates that a worktree is safe to remove before allowing
# removal. It checks for uncommitted changes, unpushed commits, and untracked
# files that would be lost.
#
# Usage:
#   ./scripts/safe_worktree_remove.sh <worktree-path>
#   ./scripts/safe_worktree_remove.sh <worktree-path> --force  # Skip confirmation
#
# Exit codes:
#   0 - Worktree removed successfully (or safe to remove in dry-run)
#   1 - Invalid arguments
#   2 - Worktree has uncommitted changes (BLOCKED)
#   3 - Worktree has unpushed commits (BLOCKED)
#   4 - User declined confirmation
#   5 - Worktree path does not exist
#
# =============================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script name for logging
SCRIPT_NAME="safe_worktree_remove"

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_block() {
    echo -e "${RED}[BLOCKED]${NC} $1"
}

print_header() {
    echo ""
    echo "=============================================="
    echo " Git Worktree Safe Removal Validator"
    echo "=============================================="
    echo ""
}

print_usage() {
    echo "Usage: $0 <worktree-path> [--force]"
    echo ""
    echo "Options:"
    echo "  --force    Skip confirmation prompt (still validates safety)"
    echo ""
    echo "Examples:"
    echo "  $0 /path/to/worktree"
    echo "  $0 ../my-worktree --force"
}

# =============================================================================
# Validation Functions
# =============================================================================

check_uncommitted_changes() {
    local worktree_path="$1"
    local status_output

    # Filter out untracked files (??) - they are handled separately as warnings
    # Only check for modified/staged/deleted tracked files
    status_output=$(git -C "$worktree_path" status --porcelain 2>/dev/null | grep -v "^??" || echo "")

    if [ -n "$status_output" ]; then
        log_block "Uncommitted changes to TRACKED files detected!"
        echo ""
        echo "The following tracked files have uncommitted changes:"
        echo "----------------------------------------------"
        echo "$status_output"
        echo "----------------------------------------------"
        echo ""
        echo "Action required:"
        echo "  1. cd $worktree_path"
        echo "  2. git add . && git commit -m 'WIP: Save work before cleanup'"
        echo "  3. git push"
        echo "  4. Then run this script again"
        echo ""
        return 2
    fi

    log_success "No uncommitted changes"
    return 0
}

check_unpushed_commits() {
    local worktree_path="$1"
    local unpushed_output

    # Check if there's an upstream branch set
    if ! git -C "$worktree_path" rev-parse --abbrev-ref '@{u}' &>/dev/null; then
        log_warning "No upstream branch set - cannot check for unpushed commits"
        log_warning "Consider pushing this branch before removal"
        return 0
    fi

    unpushed_output=$(git -C "$worktree_path" log '@{u}..HEAD' --oneline 2>/dev/null || echo "")

    if [ -n "$unpushed_output" ]; then
        log_block "Unpushed commits detected!"
        echo ""
        echo "The following commits have not been pushed:"
        echo "----------------------------------------------"
        echo "$unpushed_output"
        echo "----------------------------------------------"
        echo ""
        echo "Action required:"
        echo "  1. cd $worktree_path"
        echo "  2. git push"
        echo "  3. Then run this script again"
        echo ""
        return 3
    fi

    log_success "No unpushed commits"
    return 0
}

check_untracked_files() {
    local worktree_path="$1"
    local untracked_output

    untracked_output=$(git -C "$worktree_path" status --porcelain 2>/dev/null | grep "^??" || echo "")

    if [ -n "$untracked_output" ]; then
        log_warning "Untracked files detected (will be DELETED):"
        echo "----------------------------------------------"
        echo "$untracked_output" | sed 's/^?? /  /'
        echo "----------------------------------------------"
        echo ""
        return 0  # Warning only, not blocking
    fi

    log_success "No untracked files"
    return 0
}

get_branch_name() {
    local worktree_path="$1"
    git -C "$worktree_path" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown"
}

# =============================================================================
# Main Logic
# =============================================================================

main() {
    local worktree_path=""
    local force_mode=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --force)
                force_mode=true
                shift
                ;;
            --help|-h)
                print_usage
                exit 0
                ;;
            *)
                if [ -z "$worktree_path" ]; then
                    worktree_path="$1"
                else
                    log_error "Unexpected argument: $1"
                    print_usage
                    exit 1
                fi
                shift
                ;;
        esac
    done

    # Validate arguments
    if [ -z "$worktree_path" ]; then
        log_error "Worktree path is required"
        print_usage
        exit 1
    fi

    # Resolve to absolute path
    worktree_path=$(cd "$worktree_path" 2>/dev/null && pwd || echo "$worktree_path")

    # Check if path exists
    if [ ! -d "$worktree_path" ]; then
        log_error "Worktree path does not exist: $worktree_path"
        exit 5
    fi

    # Check if it's a git worktree
    if [ ! -d "$worktree_path/.git" ] && [ ! -f "$worktree_path/.git" ]; then
        log_error "Not a git worktree: $worktree_path"
        exit 1
    fi

    print_header

    log_info "Validating worktree: $worktree_path"
    local branch_name
    branch_name=$(get_branch_name "$worktree_path")
    log_info "Branch: $branch_name"
    echo ""

    # Run validation checks
    local has_errors=false

    echo "=== Running Safety Checks ==="
    echo ""

    if ! check_uncommitted_changes "$worktree_path"; then
        has_errors=true
    fi

    if ! check_unpushed_commits "$worktree_path"; then
        has_errors=true
    fi

    check_untracked_files "$worktree_path"  # Warning only

    echo ""

    if [ "$has_errors" = true ]; then
        echo "=============================================="
        log_error "REMOVAL BLOCKED - Worktree is not safe to remove"
        echo "=============================================="
        echo ""
        echo "Please resolve the issues above and try again."
        exit 2
    fi

    echo "=============================================="
    log_success "All safety checks passed!"
    echo "=============================================="
    echo ""

    # Confirmation prompt (unless --force)
    if [ "$force_mode" = false ]; then
        echo "Worktree details:"
        echo "  Path:   $worktree_path"
        echo "  Branch: $branch_name"
        echo ""
        echo -n "Do you want to remove this worktree? [yes/no]: "
        read -r confirmation

        case "$confirmation" in
            yes|Yes|YES|confirm|Confirm|CONFIRM)
                log_info "Confirmation received"
                ;;
            *)
                log_info "Removal cancelled by user"
                exit 4
                ;;
        esac
    fi

    # Perform removal
    # Using --force is SAFE here because:
    # 1. check_uncommitted_changes verified NO tracked files are dirty
    # 2. check_unpushed_commits verified NO unpushed commits exist
    # 3. User has explicitly confirmed removal (including untracked file warning)
    # The --force flag only affects untracked files, which the user accepted losing
    echo ""
    log_info "Removing worktree (with --force for untracked files)..."

    if git worktree remove --force "$worktree_path"; then
        log_success "Worktree removed successfully: $worktree_path"

        # Offer to delete the branch
        echo ""
        if [ "$force_mode" = false ]; then
            echo -n "Do you also want to delete the branch '$branch_name'? [yes/no]: "
            read -r delete_branch

            if [[ "$delete_branch" =~ ^(yes|Yes|YES)$ ]]; then
                if git branch -d "$branch_name" 2>/dev/null; then
                    log_success "Branch deleted: $branch_name"
                else
                    log_warning "Could not delete branch (may not be fully merged)"
                    log_info "Use 'git branch -D $branch_name' to force delete"
                fi
            fi
        fi
    else
        log_error "Failed to remove worktree"
        exit 1
    fi

    echo ""
    log_success "Cleanup complete!"
}

# Run main function
main "$@"

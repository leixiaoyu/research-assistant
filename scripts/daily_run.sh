#!/bin/bash
# daily_run.sh - Daily ARISP Research Pipeline Execution
#
# This script is invoked by launchd at 3:00 AM daily.
# It activates the Python environment, loads API keys,
# and runs the research pipeline.
#
# Usage:
#   ./scripts/daily_run.sh                    # Normal execution
#   ./scripts/daily_run.sh --dry-run          # Validate without running
#   ./scripts/daily_run.sh --config <path>    # Use custom config
#
# Exit Codes:
#   0 - Success
#   1 - Script error (see logs for details)
#   2 - Configuration error
#   3 - Environment error (venv, .env)

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_PATH="$PROJECT_ROOT/venv"
DEFAULT_CONFIG="$PROJECT_ROOT/config/daily_german_mt.yaml"
LOG_DIR="$PROJECT_ROOT/logs"
LOG_RETENTION_DAYS=7

# Parse arguments
DRY_RUN=false
CONFIG_FILE="$DEFAULT_CONFIG"

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 2
            ;;
    esac
done

# Generate log file path
LOG_FILE="$LOG_DIR/daily_run_$(date +%Y-%m-%d).log"

# =============================================================================
# Logging Functions
# =============================================================================

# Ensure log directory exists
mkdir -p "$LOG_DIR"

log() {
    local level="$1"
    local message="$2"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
}

log_info() {
    log "INFO" "$1"
}

log_warn() {
    log "WARN" "$1"
}

log_error() {
    log "ERROR" "$1"
}

log_section() {
    log_info "=========================================="
    log_info "$1"
    log_info "=========================================="
}

# =============================================================================
# Error Handling
# =============================================================================

error_handler() {
    local line_no="$1"
    local exit_code="$2"
    log_error "Script failed at line $line_no with exit code $exit_code"
    log_error "Check $LOG_FILE for details"
    exit 1
}

trap 'error_handler $LINENO $?' ERR

# =============================================================================
# Validation Functions
# =============================================================================

validate_environment() {
    log_info "Validating environment..."

    # Check venv exists
    if [[ ! -d "$VENV_PATH" ]]; then
        log_error "Virtual environment not found at: $VENV_PATH"
        log_error "Run: python3.10 -m venv venv"
        exit 3
    fi

    # Check config exists
    if [[ ! -f "$CONFIG_FILE" ]]; then
        log_error "Config file not found: $CONFIG_FILE"
        exit 2
    fi

    # Check .env exists (warning only)
    if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
        log_warn ".env file not found - API keys may be missing"
    fi

    log_info "Environment validation passed"
}

# =============================================================================
# Main Execution
# =============================================================================

main() {
    log_section "Starting Daily Research Pipeline"

    log_info "Project root: $PROJECT_ROOT"
    log_info "Config file: $CONFIG_FILE"
    log_info "Log file: $LOG_FILE"
    log_info "Dry run: $DRY_RUN"

    # Validate environment
    validate_environment

    # Activate virtual environment
    log_info "Activating virtual environment..."
    # shellcheck source=/dev/null
    source "$VENV_PATH/bin/activate"

    # Load environment variables from .env
    log_info "Loading environment variables..."
    if [[ -f "$PROJECT_ROOT/.env" ]]; then
        set -a
        # shellcheck source=/dev/null
        source "$PROJECT_ROOT/.env"
        set +a
        log_info "Environment variables loaded from .env"
    else
        log_warn "Skipping .env - file not found"
    fi

    # Verify Python version
    PYTHON_VERSION=$(python --version 2>&1)
    log_info "Python version: $PYTHON_VERSION"

    # Verify it's Python 3.10+
    PYTHON_MAJOR=$(python -c "import sys; print(sys.version_info.major)")
    PYTHON_MINOR=$(python -c "import sys; print(sys.version_info.minor)")
    if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 10 ]]; then
        log_error "Python 3.10+ required, found: $PYTHON_VERSION"
        exit 3
    fi

    # Change to project root
    cd "$PROJECT_ROOT"

    # Run the pipeline
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN - Validating configuration only..."
        PYTHONPATH="$PROJECT_ROOT" python -m src.cli validate "$CONFIG_FILE" 2>&1 | tee -a "$LOG_FILE"
        log_info "DRY RUN - Configuration is valid"
    else
        log_section "Executing Research Pipeline"

        START_TIME=$(date +%s)

        # Execute pipeline with PYTHONPATH set
        PYTHONPATH="$PROJECT_ROOT" python -m src.cli run --config "$CONFIG_FILE" 2>&1 | tee -a "$LOG_FILE"

        END_TIME=$(date +%s)
        DURATION=$((END_TIME - START_TIME))

        log_info "Pipeline completed in ${DURATION} seconds ($(( DURATION / 60 )) minutes)"
    fi

    # Cleanup old logs
    log_info "Cleaning up logs older than $LOG_RETENTION_DAYS days..."
    find "$LOG_DIR" -name "daily_run_*.log" -mtime +$LOG_RETENTION_DAYS -delete 2>/dev/null || true

    # Count remaining logs
    LOG_COUNT=$(find "$LOG_DIR" -name "daily_run_*.log" | wc -l | tr -d ' ')
    log_info "Log cleanup complete. Retained logs: $LOG_COUNT"

    log_section "Daily Research Pipeline Finished"

    return 0
}

# =============================================================================
# Entry Point
# =============================================================================

main "$@"

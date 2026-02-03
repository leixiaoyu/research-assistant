# Local Daily Automation Specification

**Version:** 1.0
**Status:** Ready for Implementation
**Created:** 2026-02-02
**Author:** Claude Code
**Dependencies:** Phase 3.1 Complete

---

## Executive Summary

This specification defines the implementation of automated daily execution of the ARISP research pipeline on local macOS workstations. The feature uses macOS native `launchd` for scheduling, ensuring reliable execution even when the machine wakes from sleep.

**Key Benefits:**
- Fresh research briefs available every morning
- No manual intervention required
- Handles machine sleep/wake cycles gracefully
- Conservative cost controls (~$0.10-0.50/day)

**Non-Overlap with Phase 4:**
| Feature | This Spec | Phase 4 |
|---------|-----------|---------|
| Scheduler | macOS launchd (local) | APScheduler, K8s CronJob (server) |
| Monitoring | Log files | Prometheus + Grafana |
| Deployment | Local shell script | Docker, systemd, K8s |
| Target | Single user workstation | Production infrastructure |

---

## 1. Requirements

### 1.1 User Stories

#### US-1: Daily Automated Execution

**As a** research engineer,
**I want** the ARISP pipeline to run automatically at 3 AM daily,
**So that** I have fresh research briefs ready when I wake up.

**Acceptance Criteria:**
- System triggers pipeline at 3:00 AM local time
- Runs when machine wakes if it was asleep at scheduled time
- Completes within 30 minutes for typical workloads

#### US-2: Research Configuration

**As a** research engineer focused on German machine translation,
**I want** pre-configured research topics covering German MT challenges,
**So that** I receive relevant papers without manual configuration.

**Acceptance Criteria:**
- 5 research topics covering German MT challenges
- 48h timeframe to avoid duplicates
- 20-30 papers per topic for manageable reading
- Engineering summary extraction enabled

#### US-3: Environment Isolation

**As a** developer,
**I want** the scheduled job to use the correct Python environment,
**So that** execution doesn't fail due to missing dependencies.

**Acceptance Criteria:**
- Activates project's virtual environment
- Loads environment variables from `.env`
- Uses Python 3.10+ as required

#### US-4: Execution Logging

**As a** user,
**I want** execution logs stored for debugging,
**So that** I can diagnose failures without re-running the pipeline.

**Acceptance Criteria:**
- Dated log files with timestamps
- 7-day retention with automatic cleanup
- Error stack traces captured

### 1.2 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Create launchd plist for 3 AM daily execution | MUST |
| FR-2 | Run missed jobs when machine wakes from sleep | MUST |
| FR-3 | Shell script to activate venv and load .env | MUST |
| FR-4 | Execute pipeline with German MT config | MUST |
| FR-5 | Capture logs with timestamps | MUST |
| FR-6 | Auto-cleanup logs older than 7 days | SHOULD |

### 1.3 Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1 | Execution time | < 30 minutes |
| NFR-2 | Memory usage | < 2 GB |
| NFR-3 | Daily LLM cost | < $0.50 |
| NFR-4 | Setup time | < 15 minutes |
| NFR-5 | Successful runs | > 95% |

---

## 2. Architecture

### 2.1 System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     macOS launchd                                │
│  (~/Library/LaunchAgents/com.arisp.daily-research.plist)       │
└─────────────────────────────┬───────────────────────────────────┘
                              │ 3:00 AM daily (or on wake)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   scripts/daily_run.sh                          │
│  • Activates virtual environment                                │
│  • Loads .env variables                                         │
│  • Executes pipeline with config                                │
│  • Captures logs to ./logs/                                     │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              python -m src.cli run --config                     │
│                 config/daily_german_mt.yaml                     │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ./output/                                   │
│  • german-mt-formality/2026-02-02_Research.md                   │
│  • german-mt-literary/2026-02-02_Research.md                    │
│  • ... (5 topic directories)                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Why launchd (Not cron)

| Aspect | cron | launchd |
|--------|------|---------|
| Setup | One-liner | XML plist file |
| Missed jobs (sleep) | ❌ Skips | ✅ Runs on wake |
| Survives reboot | ✅ Yes | ✅ Yes |
| macOS integration | Basic | Native |

**Decision:** launchd is required because the machine will likely be sleeping at 3 AM. launchd runs missed jobs when the machine wakes; cron does not.

---

## 3. Component Specifications

### 3.1 launchd plist

**File:** `scripts/com.arisp.daily-research.plist`
**Install to:** `~/Library/LaunchAgents/`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.arisp.daily-research</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${PROJECT_ROOT}/scripts/daily_run.sh</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>WorkingDirectory</key>
    <string>${PROJECT_ROOT}</string>

    <key>StandardOutPath</key>
    <string>${PROJECT_ROOT}/logs/launchd_stdout.log</string>

    <key>StandardErrorPath</key>
    <string>${PROJECT_ROOT}/logs/launchd_stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

**Note:** `${PROJECT_ROOT}` must be replaced with actual path during installation.

### 3.2 Execution Script

**File:** `scripts/daily_run.sh`

```bash
#!/bin/bash
# daily_run.sh - Daily ARISP Research Pipeline Execution
#
# Invoked by launchd at 3:00 AM daily.
# Activates Python environment, loads API keys, runs pipeline.

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_PATH="$PROJECT_ROOT/venv"
CONFIG_FILE="$PROJECT_ROOT/config/daily_german_mt.yaml"
LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOG_DIR/daily_run_$(date +%Y-%m-%d).log"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Error handler
error_handler() {
    log "ERROR: Script failed at line $1"
    exit 1
}
trap 'error_handler $LINENO' ERR

# Main execution
main() {
    log "=========================================="
    log "Starting daily research pipeline"
    log "=========================================="

    # Activate virtual environment
    log "Activating virtual environment..."
    source "$VENV_PATH/bin/activate"

    # Load environment variables
    log "Loading environment variables..."
    if [[ -f "$PROJECT_ROOT/.env" ]]; then
        set -a
        source "$PROJECT_ROOT/.env"
        set +a
    else
        log "WARNING: .env file not found"
    fi

    # Verify Python version
    PYTHON_VERSION=$(python --version 2>&1)
    log "Python version: $PYTHON_VERSION"

    # Run the pipeline
    log "Executing research pipeline..."
    cd "$PROJECT_ROOT"

    START_TIME=$(date +%s)
    PYTHONPATH="$PROJECT_ROOT" python -m src.cli run --config "$CONFIG_FILE" 2>&1 | tee -a "$LOG_FILE"
    END_TIME=$(date +%s)

    DURATION=$((END_TIME - START_TIME))
    log "Pipeline completed in ${DURATION} seconds"

    # Cleanup old logs (keep 7 days)
    log "Cleaning up old logs..."
    find "$LOG_DIR" -name "daily_run_*.log" -mtime +7 -delete 2>/dev/null || true

    log "=========================================="
    log "Daily research pipeline finished"
    log "=========================================="
}

main "$@"
```

### 3.3 Research Configuration

**File:** `config/daily_german_mt.yaml`

```yaml
# Daily German MT Research Configuration
# Optimized for automated daily runs

research_topics:
  # Topic 1: Formality and Register
  - query: '"machine translation" AND German AND (formality OR register OR politeness)'
    provider: "arxiv"
    timeframe:
      type: "recent"
      value: "48h"
    max_papers: 20
    extraction_targets:
      - name: "engineering_summary"
        description: "2-paragraph summary focusing on practical applications"
        output_format: "text"
        required: true

  # Topic 2: Long-form and Literary Translation
  - query: '"machine translation" AND German AND ("long document" OR "document-level" OR literary)'
    provider: "arxiv"
    timeframe:
      type: "recent"
      value: "48h"
    max_papers: 20
    extraction_targets:
      - name: "engineering_summary"
        description: "Focus on handling long context and style preservation"
        output_format: "text"
        required: true

  # Topic 3: Prompt Engineering for Translation
  - query: '"prompt engineering" AND translation AND (German OR multilingual)'
    provider: "arxiv"
    timeframe:
      type: "recent"
      value: "48h"
    max_papers: 25
    extraction_targets:
      - name: "engineering_summary"
        description: "Focus on prompt design patterns and examples"
        output_format: "text"
        required: true

  # Topic 4: Context-Aware Translation
  - query: '"context-aware" AND "machine translation" AND (German OR discourse)'
    provider: "arxiv"
    timeframe:
      type: "recent"
      value: "48h"
    max_papers: 20
    extraction_targets:
      - name: "engineering_summary"
        description: "Focus on context modeling techniques"
        output_format: "text"
        required: true

  # Topic 5: Style Preservation in Translation
  - query: 'LLM AND translation AND ("style transfer" OR coherence OR "discourse")'
    provider: "arxiv"
    timeframe:
      type: "recent"
      value: "48h"
    max_papers: 20
    extraction_targets:
      - name: "engineering_summary"
        description: "Focus on maintaining style consistency in long texts"
        output_format: "text"
        required: true

# Global Settings
settings:
  output_base_dir: "./output"
  enable_duplicate_detection: true

  pdf_settings:
    temp_dir: "./temp"
    keep_pdfs: false
    max_file_size_mb: 50
    timeout_seconds: 300

  llm_settings:
    provider: "${LLM_PROVIDER}"
    model: "${LLM_MODEL}"
    api_key: "${LLM_API_KEY}"
    max_tokens: 50000
    temperature: 0.0
    timeout: 300

  cost_limits:
    max_tokens_per_paper: 50000
    max_daily_spend_usd: 5.0
    max_total_spend_usd: 50.0

  concurrency:
    max_concurrent_downloads: 3
    max_concurrent_conversions: 2
    max_concurrent_llm: 1
    queue_size: 50
    checkpoint_interval: 5
    worker_timeout_seconds: 600
    enable_backpressure: true
    backpressure_threshold: 0.8

  cache:
    enabled: true
    cache_dir: "./cache"
    ttl_api_hours: 24
    ttl_pdf_days: 7
    ttl_extraction_days: 30
```

---

## 4. File Structure

```
research-assist/
├── scripts/
│   ├── migrate_to_python310.sh          # Existing
│   ├── daily_run.sh                      # NEW: Execution wrapper
│   └── com.arisp.daily-research.plist    # NEW: launchd template
├── config/
│   ├── research_config.yaml              # Existing default
│   └── daily_german_mt.yaml              # NEW: German MT topics
├── logs/                                  # NEW: Log directory
│   ├── daily_run_YYYY-MM-DD.log
│   ├── launchd_stdout.log
│   └── launchd_stderr.log
└── docs/
    └── operations/
        └── DAILY_AUTOMATION_GUIDE.md      # NEW: Setup guide

~/Library/LaunchAgents/
└── com.arisp.daily-research.plist        # Installed from scripts/
```

---

## 5. Installation Guide

### 5.1 Quick Setup (3 commands)

```bash
# 1. Make script executable
chmod +x scripts/daily_run.sh

# 2. Install launchd plist (after updating paths)
cp scripts/com.arisp.daily-research.plist ~/Library/LaunchAgents/

# 3. Load the service
launchctl load ~/Library/LaunchAgents/com.arisp.daily-research.plist
```

### 5.2 Verification

```bash
# Check service is loaded
launchctl list | grep arisp

# Test immediate execution
launchctl start com.arisp.daily-research

# View logs
tail -f logs/daily_run_$(date +%Y-%m-%d).log
```

### 5.3 Management Commands

| Action | Command |
|--------|---------|
| Load service | `launchctl load ~/Library/LaunchAgents/com.arisp.daily-research.plist` |
| Unload service | `launchctl unload ~/Library/LaunchAgents/com.arisp.daily-research.plist` |
| Check status | `launchctl list \| grep arisp` |
| Run now | `launchctl start com.arisp.daily-research` |
| View logs | `tail -f logs/daily_run_$(date +%Y-%m-%d).log` |

---

## 6. Security Considerations

### 6.1 Secrets Management

- API keys remain in `.env` (not in plist or scripts)
- `.env` loaded at runtime by shell script
- No secrets in log files (ARISP sanitizes output)

### 6.2 File Permissions

| File | Permissions | Reason |
|------|-------------|--------|
| `daily_run.sh` | `755` | Executable |
| `.env` | `600` | Owner-only (secrets) |
| `logs/` | `755` | Directory |
| `*.log` | `644` | Readable |
| `plist` | `644` | launchd requirement |

---

## 7. Error Handling

### 7.1 Script Level

- `set -euo pipefail`: Exit on any error
- `trap`: Capture line number on failure
- Logs include timestamps and error context

### 7.2 Pipeline Level

ARISP handles gracefully:
- Network failures (retry with backoff)
- API rate limits (built-in limiting)
- LLM errors (graceful degradation)
- PDF failures (fallback to abstract)

---

## 8. Testing Checklist

- [ ] Script executes without errors
- [ ] Virtual environment activates correctly
- [ ] .env variables load properly
- [ ] Pipeline runs with German MT config
- [ ] Output files generated in ./output/
- [ ] Logs captured with timestamps
- [ ] Old logs cleaned up (>7 days)
- [ ] launchd service loads successfully
- [ ] Immediate execution works via `launchctl start`
- [ ] Service runs correctly after machine wake from sleep

---

## 9. Rollback Plan

```bash
# 1. Stop the service
launchctl unload ~/Library/LaunchAgents/com.arisp.daily-research.plist

# 2. Remove plist
rm ~/Library/LaunchAgents/com.arisp.daily-research.plist

# 3. Optionally remove new files
rm scripts/daily_run.sh
rm scripts/com.arisp.daily-research.plist
rm config/daily_german_mt.yaml
rm -rf logs/
```

---

## 10. Implementation Tasks

### Task 1: Create Execution Script
- [ ] Create `scripts/daily_run.sh`
- [ ] Test manual execution
- [ ] Verify venv activation
- [ ] Verify .env loading

### Task 2: Create launchd plist
- [ ] Create `scripts/com.arisp.daily-research.plist` template
- [ ] Document path substitution
- [ ] Test load/unload

### Task 3: Create Research Configuration
- [ ] Create `config/daily_german_mt.yaml`
- [ ] Validate with existing CLI
- [ ] Test with `--dry-run` if available

### Task 4: Create logs Directory
- [ ] Add `logs/` to `.gitignore`
- [ ] Create directory structure

### Task 5: Create Setup Guide
- [ ] Create `docs/operations/DAILY_AUTOMATION_GUIDE.md`
- [ ] Include troubleshooting section

### Task 6: End-to-End Testing
- [ ] Install plist
- [ ] Run via launchctl start
- [ ] Verify output in ./output/
- [ ] Verify logs in ./logs/

---

## Approval

- [ ] **Technical Lead:** Specification is complete and feasible
- [ ] **User:** Specification meets requirements

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-02-02 | Claude Code | Initial specification |

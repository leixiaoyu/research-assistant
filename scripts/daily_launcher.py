#!/usr/bin/env python3
"""
daily_launcher.py - Direct Python launcher for launchd

This script bypasses shell interpreters entirely, allowing launchd
to run the research pipeline without requiring Full Disk Access
for /bin/bash or /bin/zsh.

Usage (called by launchd):
    /path/to/venv/bin/python /path/to/scripts/daily_launcher.py

The script:
1. Loads environment variables from .env
2. Runs the CLI pipeline with the daily config
3. Manages log rotation
4. Handles errors gracefully
"""

import os
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# Determine paths relative to this script
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
CONFIG_FILE = PROJECT_ROOT / "config" / "daily_german_mt.yaml"
LOG_DIR = PROJECT_ROOT / "logs"
ENV_FILE = PROJECT_ROOT / ".env"
LOG_RETENTION_DAYS = 7


def setup_logging():
    """Create log directory and return log file path."""
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"daily_run_{datetime.now().strftime('%Y-%m-%d')}.log"
    return log_file


def log(message: str, level: str = "INFO", log_file: Path = None):
    """Write timestamped log message."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] [{level}] {message}"
    print(formatted)
    if log_file:
        with open(log_file, "a") as f:
            f.write(formatted + "\n")


def load_env_file():
    """Load environment variables from .env file."""
    if not ENV_FILE.exists():
        return False

    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ[key] = value
    return True


def cleanup_old_logs(log_file: Path):
    """Remove logs older than LOG_RETENTION_DAYS."""
    cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
    count = 0
    for log_path in LOG_DIR.glob("daily_run_*.log"):
        try:
            # Extract date from filename
            date_str = log_path.stem.replace("daily_run_", "")
            log_date = datetime.strptime(date_str, "%Y-%m-%d")
            if log_date < cutoff:
                log_path.unlink()
                log(f"Removed old log: {log_path.name}", "INFO", log_file)
            else:
                count += 1
        except (ValueError, OSError):
            pass
    log(f"Log cleanup complete. Retained logs: {count}", "INFO", log_file)


def run_pipeline(log_file: Path) -> int:
    """Run the research pipeline CLI."""
    # Use the venv Python to run the CLI module
    python_path = PROJECT_ROOT / "venv" / "bin" / "python"

    if not python_path.exists():
        log(f"Python not found at {python_path}", "ERROR", log_file)
        return 3

    if not CONFIG_FILE.exists():
        log(f"Config not found at {CONFIG_FILE}", "ERROR", log_file)
        return 2

    cmd = [
        str(python_path),
        "-m", "src.cli",
        "run",
        "--config", str(CONFIG_FILE)
    ]

    log(f"Running: {' '.join(cmd)}", "INFO", log_file)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=7200  # 2 hour timeout
        )

        # Log output
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                log(line, "OUTPUT", log_file)

        if result.stderr:
            for line in result.stderr.strip().split("\n"):
                log(line, "STDERR", log_file)

        if result.returncode == 0:
            log("Pipeline completed successfully", "INFO", log_file)
        else:
            log(f"Pipeline failed with exit code {result.returncode}", "ERROR", log_file)

        return result.returncode

    except subprocess.TimeoutExpired:
        log("Pipeline timed out after 2 hours", "ERROR", log_file)
        return 1
    except Exception as e:
        log(f"Pipeline execution error: {e}", "ERROR", log_file)
        return 1


def main():
    """Main entry point."""
    log_file = setup_logging()

    log("=" * 50, "INFO", log_file)
    log("Starting Daily Research Pipeline (Python Launcher)", "INFO", log_file)
    log("=" * 50, "INFO", log_file)
    log(f"Project root: {PROJECT_ROOT}", "INFO", log_file)
    log(f"Config file: {CONFIG_FILE}", "INFO", log_file)
    log(f"Log file: {log_file}", "INFO", log_file)

    # Load environment
    if load_env_file():
        log("Environment variables loaded from .env", "INFO", log_file)
    else:
        log("Warning: .env file not found", "WARN", log_file)

    # Run pipeline
    exit_code = run_pipeline(log_file)

    # Cleanup old logs
    log(f"Cleaning up logs older than {LOG_RETENTION_DAYS} days...", "INFO", log_file)
    cleanup_old_logs(log_file)

    log("=" * 50, "INFO", log_file)
    log(f"Daily pipeline finished with exit code {exit_code}", "INFO", log_file)
    log("=" * 50, "INFO", log_file)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

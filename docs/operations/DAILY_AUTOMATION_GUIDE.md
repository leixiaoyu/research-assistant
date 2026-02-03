# Daily Automation Setup Guide

**Version:** 1.0
**Last Updated:** 2026-02-03

This guide covers setup, management, and troubleshooting for the ARISP daily research automation on macOS.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Setup](#quick-setup)
3. [Configuration](#configuration)
4. [Management Commands](#management-commands)
5. [Customization](#customization)
6. [Troubleshooting](#troubleshooting)
7. [Uninstallation](#uninstallation)

---

## Prerequisites

Before setting up daily automation, ensure:

- [x] ARISP is installed and working (`python -m src.cli --help`)
- [x] Python 3.10+ virtual environment exists (`venv/`)
- [x] `.env` file configured with API keys
- [x] macOS 10.15+ (for launchd support)

### Verify Prerequisites

```bash
# Check Python version
source venv/bin/activate
python --version  # Should be 3.10+

# Verify CLI works
python -m src.cli --help

# Check .env exists
ls -la .env
```

---

## Quick Setup

### Step 1: Make Script Executable

```bash
chmod +x scripts/daily_run.sh
```

### Step 2: Configure launchd plist

Edit `scripts/com.arisp.daily-research.plist` and replace all instances of `${PROJECT_ROOT}` with your actual project path:

```bash
# Example: If your project is at /Users/yourname/Documents/research-assist
sed -i '' 's|\${PROJECT_ROOT}|/Users/yourname/Documents/research-assist|g' \
    scripts/com.arisp.daily-research.plist

# Also replace ${HOME}
sed -i '' 's|\${HOME}|/Users/yourname|g' \
    scripts/com.arisp.daily-research.plist
```

Or manually edit the file and replace:
- `${PROJECT_ROOT}` → `/Users/yourname/Documents/research-assist`
- `${HOME}` → `/Users/yourname`

### Step 3: Install launchd Service

```bash
cp scripts/com.arisp.daily-research.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.arisp.daily-research.plist
```

### Step 4: Verify Installation

```bash
# Check service is loaded
launchctl list | grep arisp

# Should show something like:
# -    0    com.arisp.daily-research
```

### Step 5: Test Execution

```bash
# Run immediately to verify everything works
launchctl start com.arisp.daily-research

# Watch the logs
tail -f logs/daily_run_$(date +%Y-%m-%d).log
```

---

## Configuration

### Research Topics

Edit `config/daily_german_mt.yaml` to customize research topics:

```yaml
research_topics:
  - query: "your search query here"
    provider: "arxiv"
    timeframe:
      type: "recent"
      value: "48h"
    max_papers: 20
    extraction_targets:
      - name: "engineering_summary"
        description: "What to extract"
        output_format: "text"
        required: true
```

### Schedule Time

To change from 3 AM to another time, edit the plist:

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key>
    <integer>6</integer>  <!-- Change to 6 AM -->
    <key>Minute</key>
    <integer>30</integer> <!-- At 30 minutes past -->
</dict>
```

After editing, reload the service:

```bash
launchctl unload ~/Library/LaunchAgents/com.arisp.daily-research.plist
launchctl load ~/Library/LaunchAgents/com.arisp.daily-research.plist
```

### Cost Limits

Adjust in `config/daily_german_mt.yaml`:

```yaml
cost_limits:
  max_daily_spend_usd: 5.0    # Daily limit
  max_total_spend_usd: 50.0   # Monthly limit
```

---

## Management Commands

| Action | Command |
|--------|---------|
| **Load service** | `launchctl load ~/Library/LaunchAgents/com.arisp.daily-research.plist` |
| **Unload service** | `launchctl unload ~/Library/LaunchAgents/com.arisp.daily-research.plist` |
| **Check status** | `launchctl list \| grep arisp` |
| **Run now** | `launchctl start com.arisp.daily-research` |
| **View today's log** | `tail -f logs/daily_run_$(date +%Y-%m-%d).log` |
| **View launchd errors** | `cat logs/launchd_stderr.log` |
| **List all logs** | `ls -la logs/` |
| **Manual dry run** | `./scripts/daily_run.sh --dry-run` |

---

## Customization

### Using a Different Config File

```bash
# Edit the plist ProgramArguments to add --config flag:
<key>ProgramArguments</key>
<array>
    <string>/bin/bash</string>
    <string>/path/to/scripts/daily_run.sh</string>
    <string>--config</string>
    <string>/path/to/custom_config.yaml</string>
</array>
```

### Running Multiple Schedules

Create multiple plist files with different:
- `Label` (unique identifier)
- `StartCalendarInterval` (different times)
- Config file paths

### Disabling Temporarily

```bash
# Unload without removing
launchctl unload ~/Library/LaunchAgents/com.arisp.daily-research.plist

# Re-enable later
launchctl load ~/Library/LaunchAgents/com.arisp.daily-research.plist
```

---

## Troubleshooting

### Service Not Running

**Symptom:** `launchctl list | grep arisp` shows nothing

**Solutions:**
1. Check plist syntax:
   ```bash
   plutil -lint ~/Library/LaunchAgents/com.arisp.daily-research.plist
   ```
2. Verify paths are absolute (no `${PROJECT_ROOT}` placeholders)
3. Check macOS Console.app for launchd errors

### Script Fails to Execute

**Symptom:** Service loaded but nothing happens

**Check:**
1. Script is executable:
   ```bash
   ls -la scripts/daily_run.sh  # Should show -rwxr-xr-x
   ```
2. launchd errors:
   ```bash
   cat logs/launchd_stderr.log
   ```
3. Manual test:
   ```bash
   ./scripts/daily_run.sh --dry-run
   ```

### Python Not Found

**Symptom:** Logs show "Python not found" or wrong version

**Solutions:**
1. Verify venv exists:
   ```bash
   ls -la venv/bin/python
   ```
2. Check script uses correct path (should auto-detect via `$PROJECT_ROOT/venv`)

### API Key Errors

**Symptom:** Logs show authentication errors

**Check:**
1. `.env` file exists and has correct keys:
   ```bash
   cat .env | grep -E "LLM_|SEMANTIC"
   ```
2. Keys are not expired
3. Script loads `.env` (check logs for "Environment variables loaded")

### No Output Generated

**Symptom:** Script runs but no files in `./output/`

**Check:**
1. ArXiv rate limits (wait and retry)
2. Network connectivity
3. Query returns results (test manually):
   ```bash
   python -m src.cli run --config config/daily_german_mt.yaml
   ```

### High Costs

**Symptom:** LLM costs exceeding expected amounts

**Solutions:**
1. Reduce `max_papers` per topic
2. Lower `max_tokens` in llm_settings
3. Reduce cost limits:
   ```yaml
   cost_limits:
     max_daily_spend_usd: 1.0
   ```

---

## Uninstallation

To completely remove the daily automation:

```bash
# 1. Stop and unload the service
launchctl unload ~/Library/LaunchAgents/com.arisp.daily-research.plist

# 2. Remove the plist
rm ~/Library/LaunchAgents/com.arisp.daily-research.plist

# 3. (Optional) Remove logs
rm -rf logs/

# 4. (Optional) Remove the config
rm config/daily_german_mt.yaml

# 5. (Optional) Remove the script
rm scripts/daily_run.sh
rm scripts/com.arisp.daily-research.plist
```

---

## Log Files

| File | Description | Retention |
|------|-------------|-----------|
| `logs/daily_run_YYYY-MM-DD.log` | Full execution log | 7 days (auto) |
| `logs/launchd_stdout.log` | launchd stdout | Manual |
| `logs/launchd_stderr.log` | launchd errors | Manual |

### Log Format

```
[2026-02-03 03:00:01] [INFO] ==========================================
[2026-02-03 03:00:01] [INFO] Starting Daily Research Pipeline
[2026-02-03 03:00:01] [INFO] ==========================================
[2026-02-03 03:00:01] [INFO] Project root: /Users/name/research-assist
[2026-02-03 03:00:01] [INFO] Config file: config/daily_german_mt.yaml
...
[2026-02-03 03:15:45] [INFO] Pipeline completed in 883 seconds (14 minutes)
```

---

## FAQ

### Q: What if my Mac is asleep at 3 AM?

**A:** launchd will run the job when your Mac wakes up. This is the key advantage over cron.

### Q: How do I change the schedule?

**A:** Edit the `StartCalendarInterval` in the plist, then unload and reload the service.

### Q: Can I run multiple topics at different times?

**A:** Yes, create multiple plist files with unique `Label` values and different schedules.

### Q: How do I check if it ran today?

**A:** Check for today's log: `ls logs/daily_run_$(date +%Y-%m-%d).log`

### Q: What's the expected cost per day?

**A:** With default settings (5 topics × 20 papers × engineering_summary only): ~$0.10-0.50/day using Gemini Flash.

---

## Support

For issues:
1. Check logs: `cat logs/daily_run_$(date +%Y-%m-%d).log`
2. Check launchd errors: `cat logs/launchd_stderr.log`
3. Run manual test: `./scripts/daily_run.sh --dry-run`
4. Review this guide's troubleshooting section

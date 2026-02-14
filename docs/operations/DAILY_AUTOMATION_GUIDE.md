# Daily Automation Setup Guide

**Version:** 1.1
**Last Updated:** 2026-02-14

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

### Slack Notifications (Phase 3.7)

The pipeline can send Slack notifications after each run with status, statistics, and key learnings extracted from papers.

#### Step 1: Create a Slack Webhook

1. Go to [Slack Apps](https://api.slack.com/apps) and create a new app
2. Enable **Incoming Webhooks** for your app
3. Add a new webhook to your desired channel
4. Copy the webhook URL (format: `https://hooks.slack.com/services/T.../B.../XXX...`)

#### Step 2: Add Webhook to Environment

Add to your `.env` file:

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T00/B00/XXXXX
```

#### Step 3: Enable in Configuration

Add `notification_settings` to your config file (e.g., `config/daily_german_mt.yaml`):

```yaml
notification_settings:
  slack:
    enabled: true
    webhook_url: "${SLACK_WEBHOOK_URL}"  # Uses env variable
    notify_on_success: true              # Send on successful runs
    notify_on_failure: true              # Send on failed runs
    notify_on_partial: true              # Send on partial success
    include_cost_summary: true           # Include LLM cost in message
    include_key_learnings: true          # Include paper summaries
    max_learnings_per_topic: 2           # Learnings shown per topic
    mention_on_failure: "<!channel>"     # Mention @channel on failure
    timeout_seconds: 10.0                # HTTP timeout
```

#### Notification Options

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Enable/disable Slack notifications |
| `webhook_url` | `None` | Slack webhook URL (use env var) |
| `channel_override` | `None` | Override default channel (e.g., `#alerts`) |
| `notify_on_success` | `true` | Send notification on success |
| `notify_on_failure` | `true` | Send notification on failure |
| `notify_on_partial` | `true` | Send notification on partial success |
| `include_cost_summary` | `true` | Include LLM token/cost stats |
| `include_key_learnings` | `true` | Include extracted paper summaries |
| `max_learnings_per_topic` | `2` | Max learnings per topic (1-10) |
| `mention_on_failure` | `None` | Slack mention on failure (`<!channel>`, `<!here>`, `<@USER_ID>`) |
| `timeout_seconds` | `10.0` | HTTP request timeout (1-60 seconds) |

#### Example Slack Message

```
┌─────────────────────────────────────────────────────────────┐
│ ✅ Daily Research Pipeline Completed Successfully           │
├─────────────────────────────────────────────────────────────┤
│ *Date:* 2026-02-14 09:00 UTC                                │
│ *Topics:* 3 processed, 0 failed                             │
│ *Papers:* 45 discovered, 38 processed                       │
│ *Extractions:* 32 with LLM extraction                       │
├─────────────────────────────────────────────────────────────┤
│ 💰 *LLM Cost:* $0.0234 (12,500 tokens)                      │
├─────────────────────────────────────────────────────────────┤
│ 📚 *Key Learnings*                                          │
│ *german-mt-advances*                                        │
│ > _"New approach achieves 2.3 BLEU improvement..."_         │
├─────────────────────────────────────────────────────────────┤
│ ARISP Pipeline | 2026-02-14                                 │
└─────────────────────────────────────────────────────────────┘
```

#### Fail-Safe Behavior

Notifications are **fail-safe**: if Slack is unreachable or the webhook fails, the pipeline continues normally. Errors are logged but never break the pipeline.

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

### Slack Notifications Not Working

**Symptom:** Pipeline runs but no Slack messages appear

**Check:**
1. Verify webhook URL is set:
   ```bash
   grep SLACK_WEBHOOK_URL .env
   ```
2. Verify notifications are enabled in config:
   ```bash
   grep -A5 "notification_settings:" config/daily_german_mt.yaml
   ```
3. Check logs for notification errors:
   ```bash
   grep -i "slack\|notification" logs/daily_run_$(date +%Y-%m-%d).log
   ```
4. Test webhook manually:
   ```bash
   curl -X POST -H 'Content-type: application/json' \
     --data '{"text":"Test message"}' \
     "$SLACK_WEBHOOK_URL"
   ```

**Common Issues:**
- Webhook URL contains `${SLACK_WEBHOOK_URL}` placeholder (not resolved)
- `enabled: false` in config
- Webhook URL expired or revoked
- Firewall blocking outbound HTTPS

**Note:** Slack errors are logged but never break the pipeline (fail-safe design).

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

### Q: How do I set up Slack notifications?

**A:** Add `SLACK_WEBHOOK_URL` to your `.env` file, then enable `notification_settings.slack.enabled: true` in your config. See the [Slack Notifications](#slack-notifications-phase-37) section for full setup instructions.

### Q: Slack notifications aren't appearing, but the pipeline runs fine?

**A:** This is expected fail-safe behavior. Check logs for notification errors: `grep -i slack logs/daily_run_*.log`. Common causes: webhook URL not set, `enabled: false`, or network issues.

---

## Support

For issues:
1. Check logs: `cat logs/daily_run_$(date +%Y-%m-%d).log`
2. Check launchd errors: `cat logs/launchd_stderr.log`
3. Run manual test: `./scripts/daily_run.sh --dry-run`
4. Review this guide's troubleshooting section

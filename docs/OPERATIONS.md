# Operations Guide

This document covers how to run the trading infrastructure autonomously.

## Quick Start

```bash
# 1. Make sure IBKR TWS is running on port 7497

# 2. Run tests to verify everything works
python test_all.py

# 3. Start the scheduler
python main.py scheduler
```

## Autonomous Operation

### Using systemd (Recommended for Linux)

```bash
# Install the service
cd deploy
./setup.sh install

# Start the service
sudo systemctl start trading-scheduler@$USER

# Enable on boot
sudo systemctl enable trading-scheduler@$USER

# Check status
sudo systemctl status trading-scheduler@$USER
```

### Manual Background Run

```bash
# Using nohup
nohup python main.py scheduler > logs/scheduler.stdout.log 2>&1 &

# Or using screen
screen -S trading
python main.py scheduler
# Ctrl+A, D to detach
```

## Monitoring

### Health Check Endpoints

When the scheduler is running, it exposes HTTP endpoints on port 8080:

```bash
# Simple health check
curl http://127.0.0.1:8080/health
# Returns: OK

# Detailed status
curl http://127.0.0.1:8080/status
# Returns JSON with job status, last run times, etc.
```

### Status File

The scheduler writes status to `logs/scheduler_status.json`:

```json
{
  "scheduler_started": "2026-01-30T10:00:00+00:00",
  "last_heartbeat": "2026-01-30T16:30:00+00:00",
  "jobs": {
    "daily_snapshot": {
      "last_start": "2026-01-30T16:35:00+00:00",
      "last_end": "2026-01-30T16:35:45+00:00",
      "status": "success",
      "last_success": "2026-01-30T16:35:45+00:00"
    }
  }
}
```

### Failure Notifications

Set the `SCHEDULER_WEBHOOK_URL` environment variable to receive failure notifications:

```bash
export SCHEDULER_WEBHOOK_URL="https://your-webhook-endpoint.com/notify"
```

The webhook receives JSON payloads:
```json
{
  "subject": "Scheduler Job Failed: daily_snapshot",
  "body": "Snapshot job failed: Connection refused",
  "timestamp": "2026-01-30T16:35:00+00:00"
}
```

## Scheduled Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| Daily Snapshot | 16:35 UTC | Saves portfolio state after LSE close |
| Weekly Rebalance | Sunday 20:00 UTC | Generates momentum signal & trade recommendations |
| Weekly Report | Sunday 21:00 UTC | Generates PDF report for the previous week |

The weekly schedule runs on Sunday evening to prepare for Monday trading.

## IBKR TWS Requirements

- TWS must be running on port 7497 (paper) or 7496 (live)
- TWS requires daily restart (typically around 23:45-00:15 UTC)
- The scheduler handles TWS restarts via retry logic

### TWS Auto-Restart Configuration

1. In TWS: Configure > Settings > Lock and Exit
2. Enable "Auto restart"
3. Set restart time (recommended: 23:45 local time)
4. Enable "Auto logon"

## Retry Logic

Jobs automatically retry on failure with exponential backoff:

- Attempt 1: Immediate
- Attempt 2: Wait 60 seconds
- Attempt 3: Wait 120 seconds
- After 3 failures: Notification sent, job marked as failed

## Manual Commands

```bash
# Take a snapshot now
python main.py snapshot

# Generate momentum signal
python main.py signal

# Generate rebalance trade recommendations
python main.py rebalance

# Generate weekly report (current week or specified)
python main.py weekly-report
python main.py weekly-report 2026-W05

# Generate monthly report
python main.py report 2026-01

# Check performance
python main.py stats

# Start dashboard
python main.py dashboard

# Manually run a scheduler job
python main.py run-job snapshot
python main.py run-job rebalance
python main.py run-job report
```

## Logs

- `logs/scheduler.log` - Scheduler operations
- `logs/execution_logger.log` - IBKR connection logs
- `logs/scheduler_status.json` - Machine-readable status

## Troubleshooting

### Scheduler won't start

1. Check IBKR TWS is running: `./deploy/setup.sh test`
2. Check port 8080 is available
3. Check config/config.yaml exists and is valid

### Jobs failing

1. Check `logs/scheduler.log` for errors
2. Check status endpoint: `curl http://127.0.0.1:8080/status`
3. Test IBKR connection: `./deploy/setup.sh test`

### No market data

- Check IBKR market data subscriptions
- Delayed data (type 3) is used as fallback
- See `price_source` field in snapshots

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│   IBKR TWS      │────▶│    Scheduler    │
│   Port 7497     │     │                 │
└─────────────────┘     │  ┌───────────┐  │
                        │  │ Snapshot  │  │
                        │  │   Job     │  │
                        │  └───────────┘  │
                        │  ┌───────────┐  │
                        │  │  Signal   │  │
                        │  │   Job     │  │
                        │  └───────────┘  │
                        │  ┌───────────┐  │
                        │  │  Health   │  │
                        │  │  Server   │  │
                        │  │ Port 8080 │  │
                        │  └───────────┘  │
                        └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │   Data Files    │
                        │  - snapshots/   │
                        │  - logs/        │
                        │  - signals/     │
                        └─────────────────┘
```

## Configuration Reference

See `config/config.yaml`:

```yaml
scheduler:
  health_port: 8080          # HTTP health check port
  snapshot_time: "16:35"     # Daily snapshot time (UTC)
  rebalance_day: "sunday"    # Day for weekly rebalance
  rebalance_time: "20:00"    # Weekly rebalance time (UTC)
  report_time: "21:00"       # Weekly report time (UTC)
  max_retries: 3             # Retry attempts per job
  retry_base_delay: 60       # Base delay between retries (seconds)
```

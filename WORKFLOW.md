# Operational Workflow Guide

This guide covers the day-to-day and monthly operational procedures for the live trading track record infrastructure.

## Table of Contents

- [Daily Workflow](#daily-workflow)
- [Monthly Rebalance Workflow](#monthly-rebalance-workflow)
- [Monthly Report Workflow](#monthly-report-workflow)
- [Scheduler Setup](#scheduler-setup)
- [Troubleshooting](#troubleshooting)

---

## Daily Workflow

### End of Day (After Market Close)

The London Stock Exchange closes at 16:30 UTC. Run the daily snapshot shortly after:

```bash
# 1. Ensure IBKR TWS/Gateway is running and connected

# 2. Save portfolio snapshot
python main.py snapshot

# Expected output:
# Saving portfolio snapshot...
# Snapshot saved to: data/snapshots/2026-01-27.json
```

### If You Executed Trades Today

```bash
# 1. Pull today's executions
python main.py pull

# Expected output:
# Pulling executions from IBKR...
# Executions saved to: data/executions/2026-01-27.csv

# 2. Annotate trades (optional but recommended)
python main.py annotate --list          # View existing annotations
python main.py annotate <trade_id> --post  # Add post-trade notes
```

### Quick Performance Check

```bash
# View current stats
python main.py stats

# View slippage analysis
python main.py slippage
```

---

## Monthly Rebalance Workflow

### On the 1st Trading Day of Each Month

#### Step 1: Generate Momentum Signal

```bash
python main.py signal

# Output:
# MOMENTUM SIGNAL - 2026-02-01
# ============================================================
# Rank  Symbol  Sector              12-1 Mom    Target
# ------------------------------------------------------------
# 1     SXLK    Technology          +24.3%      33.3%
# 2     SXLI    Industrials         +19.2%      33.3%
# 3     SXLU    Utilities           +15.7%      33.3%
# 4     SXLF    Financials          +12.1%       0.0%
# ...
```

#### Step 2: Compare to Current Portfolio

```bash
python main.py rebalance

# Output:
# REBALANCE TRADES - 2026-02-01
# ============================================================
# Current Portfolio:
#   SXLK: 30.5% (target: 33.3%)
#   SXLI: 35.2% (target: 33.3%)
#   SXLV: 29.3% (target:  0.0%)  <- SELL
#
# Required Trades:
# ------------------------------------------------------------
# SELL  SXLV   150 shares @ ~£42.50 = -£6,375
# SELL  SXLI    10 shares @ ~£38.20 = -£382
# BUY   SXLU   160 shares @ ~£28.75 = +£4,600
# BUY   SXLK    15 shares @ ~£185.00 = +£2,775
```

#### Step 3: Create Pre-Trade Annotations

```bash
python main.py annotate new --pre

# Interactive prompts:
# Symbol: SXLU
# Thesis: Top 3 momentum sector, utilities showing strength
# Intended entry price: 28.75
# Position size rationale: 33% target weight per strategy
# Exit plan: Hold until next rebalance or stop at -10%
```

#### Step 4: Execute Trades in IBKR

1. Open TWS or IBKR mobile
2. Execute the trades from the rebalance list
3. Use LIMIT orders slightly above ask (for buys) or below bid (for sells)
4. Verify all fills

#### Step 5: Log Executions

```bash
# Pull executions from IBKR
python main.py pull

# Save updated portfolio snapshot
python main.py snapshot
```

#### Step 6: Complete Post-Trade Annotations

```bash
python main.py annotate --list  # Find trade IDs

python main.py annotate <trade_id> --post

# Interactive prompts:
# Outcome: Filled at £28.80, 5 bps slippage
# Matched expectation: yes
# Lesson: Limit orders work well for liquid ETFs
```

---

## Monthly Report Workflow

### At Month End

#### Step 1: Add Commentary (Optional)

Create a markdown file with your monthly commentary:

```bash
mkdir -p data/annotations/monthly

cat > data/annotations/monthly/2026-01.md << 'EOF'
## January 2026 Commentary

Strong month driven by technology sector outperformance. The momentum signal correctly identified SXLK as top sector.

### Key Events
- Fed held rates steady
- Tech earnings exceeded expectations
- UK GDP growth surprised to upside

### Execution Quality
All trades executed within 5 bps of intended prices. Liquidity was excellent.

### Lessons Learned
- Morning execution (08:30-09:30) provided tightest spreads
- SXLB showed lower liquidity than expected
EOF
```

#### Step 2: Generate PDF Report

```bash
python main.py report 2026-01

# Output:
# Generating report for 2026-01...
# Report saved to: reports/monthly/2026-01-report.pdf
```

#### Step 3: Review Report

```bash
open reports/monthly/2026-01-report.pdf  # macOS
```

The report includes:
- Monthly performance summary
- Equity curve chart
- Position breakdown
- Trade list with slippage analysis
- Your monthly commentary

---

## Scheduler Setup

For automated daily snapshots and monthly signals:

### Running the Scheduler

```bash
python main.py scheduler

# Output:
# Scheduler started. Press Ctrl+C to stop.
# Scheduled jobs:
#   - Daily snapshot at 16:35 UTC
#   - Monthly signal on 1st at 08:00 UTC
```

### Running as Background Service (macOS)

Create a launch agent for persistent operation:

```bash
mkdir -p ~/Library/LaunchAgents

cat > ~/Library/LaunchAgents/com.trading.scheduler.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trading.scheduler</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/venv/bin/python</string>
        <string>/path/to/live-trading-jan2026/main.py</string>
        <string>scheduler</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/live-trading-jan2026</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/path/to/live-trading-jan2026/logs/scheduler.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/live-trading-jan2026/logs/scheduler.stderr.log</string>
</dict>
</plist>
EOF

# Load the service
launchctl load ~/Library/LaunchAgents/com.trading.scheduler.plist

# Check status
launchctl list | grep trading
```

### Running as systemd Service (Linux)

```bash
sudo cat > /etc/systemd/system/trading-scheduler.service << 'EOF'
[Unit]
Description=Trading Track Record Scheduler
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/live-trading-jan2026
ExecStart=/path/to/venv/bin/python main.py scheduler
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable trading-scheduler
sudo systemctl start trading-scheduler
```

---

## Dashboard Usage

### Starting the Dashboard

```bash
python main.py dashboard --port 5050

# Open in browser: http://localhost:5050
```

### Dashboard Features

- **Summary Cards**: Total equity, cash, daily P&L, total return
- **Equity Curve**: Interactive chart showing portfolio value over time
- **Positions Table**: Current holdings with weights and unrealized P&L
- **Momentum Signal**: Ranked sectors with target weights
- **Rebalance Countdown**: Days until next monthly rebalance

---

## Troubleshooting

### IBKR Connection Issues

**Error: "Connection refused"**

1. Ensure TWS/Gateway is running
2. Check API settings in TWS: File → Global Configuration → API → Settings
3. Verify socket port (7497 for paper, 7496 for live)
4. Ensure "Enable ActiveX and Socket Clients" is checked
5. Add 127.0.0.1 to trusted IPs

**Error: "Client ID already in use"**

```bash
# Use a different client ID in config/config.yaml
ibkr:
  client_id: 2  # Change from default
```

### No Executions Found

1. Check the date filter - executions are pulled for today only
2. Verify trades were executed in the connected account
3. Ensure you're connected to the correct account (paper vs live)

### Dashboard Won't Start

**Error: "Address already in use"**

```bash
# Find process using the port
lsof -i :5050

# Kill it or use different port
python main.py dashboard --port 5051
```

**Error: "Access denied" on macOS**

Port 5000 is used by AirPlay Receiver. Use a different port:

```bash
python main.py dashboard --port 5050
```

### Momentum Signal Errors

**Error: "No data found for symbol"**

1. Check internet connection
2. Verify ETF symbols are correct (.L suffix for LSE)
3. Try again - yfinance occasionally has temporary issues

**Error: "Not enough price history"**

The 12-1 momentum signal requires 13 months of data. New ETFs may not have sufficient history.

### Report Generation Issues

**Error: "No snapshots found"**

Ensure you have saved at least one portfolio snapshot:

```bash
python main.py snapshot
```

**Error: "ReportLab error"**

Check that reportlab is installed:

```bash
pip install reportlab>=4.0.0
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Generate signal | `python main.py signal` |
| Get rebalance trades | `python main.py rebalance` |
| Pull executions | `python main.py pull` |
| Save snapshot | `python main.py snapshot` |
| View stats | `python main.py stats` |
| View slippage | `python main.py slippage` |
| Generate report | `python main.py report 2026-01` |
| Start dashboard | `python main.py dashboard --port 5050` |
| Start scheduler | `python main.py scheduler` |
| Annotate trade | `python main.py annotate <id> --post` |

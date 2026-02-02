# Live Trading Track Record Infrastructure

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A systematic trading infrastructure for building a verifiable live track record, designed for institutional trading recruitment.

## Table of Contents

- [Purpose](#purpose)
- [Strategy Overview](#strategy-overview)
- [System Architecture](#system-architecture)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Automated Execution](#automated-execution)
- [CLI Commands](#cli-commands)
- [Dashboard](#dashboard)
- [Data Schemas](#data-schemas)
- [ETF Universe](#etf-universe)
- [Performance Metrics](#performance-metrics)
- [Workflows](#workflows)
- [Documentation](#documentation)
- [Disclaimer](#disclaimer)

## Purpose

This system provides infrastructure for:

- **Execution Logging**: Automatically pull and log trades from Interactive Brokers
- **Performance Tracking**: Calculate Sharpe ratio, drawdown, win rate, and other metrics
- **Slippage Analysis**: Compare intended vs actual execution prices
- **Signal Generation**: Systematic 12-1 momentum signal for sector rotation
- **Report Generation**: Professional monthly PDF reports for recruiters
- **Trade Documentation**: Pre/post-trade annotations for learning and compliance

## Strategy Overview

### Cross-Sectional Momentum on UK Sector ETFs

The strategy implements **12-1 momentum** (also known as "Jegadeesh-Titman momentum"):

- **Signal**: 12-month cumulative return, excluding the most recent month
- **Universe**: 9 UK-listed UCITS sector ETFs on London Stock Exchange
- **Selection**: Top 3 sectors by momentum
- **Weighting**: Equal weight (33.3% each)
- **Rebalance**: Monthly, on the 1st trading day

### Academic Basis

The momentum anomaly is one of the most robust findings in empirical finance:

- **Jegadeesh & Titman (1993)**: "Returns to Buying Winners and Selling Losers"
- **Moskowitz & Grinblatt (1999)**: "Do Industries Explain Momentum?"
- **Asness, Moskowitz & Pedersen (2013)**: "Value and Momentum Everywhere"

The 12-1 formulation skips the most recent month to avoid short-term reversal effects.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         IBKR TWS/Gateway                            │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │ ib_insync
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      execution_logger.py                            │
│                    (Pull executions & snapshots)                    │
└──────────────┬─────────────────────────────────────┬────────────────┘
               │                                     │
               ▼                                     ▼
┌──────────────────────────┐          ┌──────────────────────────────┐
│  data/executions/*.csv   │          │   data/snapshots/*.json      │
└──────────────┬───────────┘          └──────────────┬───────────────┘
               │                                     │
               ▼                                     ▼
┌──────────────────────────┐          ┌──────────────────────────────┐
│  slippage_analyzer.py    │          │     performance.py           │
└──────────────────────────┘          └──────────────┬───────────────┘
                                                     │
               ┌─────────────────────────────────────┼─────────────┐
               │                                     │             │
               ▼                                     ▼             ▼
┌──────────────────────┐    ┌────────────────────┐    ┌───────────────┐
│     export.py        │    │   dashboard.py     │    │  CLI stats    │
│  (Monthly PDF)       │    │  (Web UI :5050)    │    │               │
└──────────────────────┘    └────────────────────┘    └───────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      Signal Generation                              │
├─────────────────────────────────────────────────────────────────────┤
│  yfinance  ──►  momentum.py  ──►  rebalance.py  ──►  Trade List    │
│  (Prices)       (12-1 Signal)     (vs Portfolio)                    │
└─────────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
live-trading-jan2026/
├── main.py                      # CLI entry point
├── README.md                    # This file
├── WORKFLOW.md                  # Operational guide
├── LICENSE                      # MIT License
├── requirements.txt             # Production dependencies
├── requirements-dev.txt         # Development dependencies
├── config/
│   ├── config.yaml              # Your settings (gitignored)
│   └── config.example.yaml      # Template configuration
├── src/
│   ├── __init__.py
│   ├── execution_logger.py      # IBKR connection, execution pulling
│   ├── slippage_analyzer.py     # Execution quality analysis
│   ├── performance.py           # Sharpe, drawdown, win rate
│   ├── annotations.py           # Trade thesis documentation
│   ├── export.py                # Monthly PDF report generation
│   ├── dashboard.py             # Flask web dashboard
│   ├── scheduler.py             # Automated task scheduling
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── momentum.py          # 12-1 momentum signal generator
│   │   └── rebalance.py         # Portfolio rebalancing logic
│   └── execution/               # Automated execution module
│       ├── __init__.py
│       ├── engine.py            # Signal-to-execution orchestrator
│       ├── order_manager.py     # IBKR order submission
│       ├── position_sizer.py    # Share quantity calculations
│       ├── risk_manager.py      # Safeguards & kill switch
│       └── signal_logger.py     # Signal audit trail
├── templates/
│   ├── dashboard.html           # Web dashboard template
│   └── signals.html             # Signals log page template
├── data/
│   ├── executions/              # Trade execution CSVs (gitignored)
│   ├── snapshots/               # Portfolio snapshots JSON (gitignored)
│   ├── signals/                 # Signal logs JSON (gitignored)
│   └── annotations/             # Trade notes (gitignored)
│       └── monthly/             # Monthly commentary
├── reports/
│   └── monthly/                 # Generated PDF reports (gitignored)
├── notebooks/
│   └── analysis.ipynb           # Ad-hoc analysis
├── tests/
│   ├── __init__.py
│   ├── test_performance.py      # Performance unit tests
│   └── test_scheduler.py        # Scheduler unit tests
├── deploy/
│   ├── setup.sh                 # Deployment setup script
│   └── trading-scheduler.service # systemd service file
├── logs/                        # Application logs (gitignored)
└── docs/
    ├── STRATEGY.md              # Strategy documentation
    ├── ARCHITECTURE.md          # Technical documentation
    └── OPERATIONS.md            # Operations guide
```

## Installation

### Prerequisites

- Python 3.10+
- Interactive Brokers TWS or IB Gateway
- IBKR account (paper trading supported)

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/amr-coding1/live-trading-jan2026.git
cd live-trading-jan2026

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure IBKR connection
cp config/config.example.yaml config/config.yaml
# Edit config/config.yaml with your settings
```

### IBKR TWS Configuration

1. Open TWS or IB Gateway
2. Go to **File → Global Configuration → API → Settings**
3. Enable "Enable ActiveX and Socket Clients"
4. Set Socket port: `7497` (paper) or `7496` (live)
5. Disable "Read-Only API" for order capabilities
6. Add `127.0.0.1` to trusted IPs

## Quick Start

```bash
# Generate momentum signal
python main.py signal

# Output:
# MOMENTUM SIGNAL - 2026-01-27
# ============================================================
# Rank  Symbol  Sector        12-1 Mom    Target
# ------------------------------------------------------------
# 1     SXLK    Technology    +24.3%      33.3%
# 2     SXLI    Industrials   +19.2%      33.3%
# 3     SXLU    Utilities     +15.7%      33.3%
# ...

# Start web dashboard
python main.py dashboard --port 5050
# Open http://localhost:5050
```

## Automated Execution

The system supports fully automated signal-to-execution with comprehensive safeguards.

### Quick Start (Dry-Run Mode)

```bash
# Run execution pipeline in dry-run mode (default)
python main.py execute

# This will:
# 1. Generate momentum signal
# 2. Load current portfolio
# 3. Calculate required trades
# 4. Validate against risk limits
# 5. Log everything (no actual orders)
```

### Live Mode (Requires Confirmation)

```bash
# Run in live mode (submits orders to IBKR)
python main.py execute --live
# Type 'CONFIRM' when prompted
```

### Configuration

Add to `config/config.yaml`:

```yaml
execution:
  mode: "dry_run"              # "dry_run" or "live"
  order_type: "MOC"            # "MKT", "MOC", "LMT"

position_sizing:
  top_n: 3                     # Top sectors to hold
  exit_rank_threshold: 5       # Exit when rank drops below

risk_limits:
  max_position_pct: 0.25       # 25% max single position
  max_turnover_pct: 0.50       # 50% max daily turnover
  kill_switch_file: "data/.kill_switch"
```

### Kill Switch

Emergency trading halt:

```bash
# Check status
python main.py kill-switch status

# Activate (blocks all trading)
python main.py kill-switch activate "Market volatility"

# Deactivate (requires confirmation)
python main.py kill-switch deactivate
```

### Dashboard Signals Page

View signal history at `http://localhost:5000/signals`:

- Historical signals with rankings
- Trade decisions (buy/sell)
- Execution status (dry-run vs live)
- Kill switch status

### Scheduled Execution

The scheduler runs the execution pipeline daily after market close:

```bash
python main.py scheduler

# Scheduled jobs:
# - 16:35 UTC: Daily snapshot
# - 16:40 UTC: Execute signals (respects dry_run config)
# - Sunday 20:00 UTC: Weekly rebalance
# - Sunday 21:00 UTC: Weekly report
```

### Safety Features

1. **Dry-run by default** - Must explicitly enable live mode
2. **Kill switch** - File-based emergency stop
3. **Position limits** - Max 25% in single position
4. **Turnover limits** - Max 50% daily turnover
5. **Confirmation prompts** - Live mode requires "CONFIRM"
6. **Full audit trail** - Every decision logged to `data/signals/`

## CLI Commands

| Command | Description |
|---------|-------------|
| `python main.py signal` | Generate momentum signal, show rankings |
| `python main.py signal --top-n 5` | Select top 5 sectors instead of 3 |
| `python main.py rebalance` | Compare portfolio to signal, show trades |
| `python main.py execute` | Run execution pipeline (dry-run mode) |
| `python main.py execute --live` | Run execution pipeline (live mode) |
| `python main.py kill-switch status` | Check kill switch status |
| `python main.py kill-switch activate "reason"` | Activate kill switch |
| `python main.py kill-switch deactivate` | Deactivate kill switch |
| `python main.py pull` | Pull today's executions from IBKR |
| `python main.py snapshot` | Save current portfolio state |
| `python main.py stats` | Print performance summary |
| `python main.py stats 2026-01-01 2026-01-31` | Stats for date range |
| `python main.py slippage` | Analyze execution slippage |
| `python main.py report 2026-01` | Generate January 2026 PDF report |
| `python main.py annotate new --pre` | Create pre-trade annotation |
| `python main.py annotate <id> --post` | Add post-trade notes |
| `python main.py dashboard` | Start web dashboard |
| `python main.py dashboard --port 5050` | Dashboard on custom port |
| `python main.py scheduler` | Start automated task scheduler |
| `python main.py weekly-report` | Generate weekly performance report |
| `python main.py run-job <job_name>` | Manually run a scheduler job |

## Dashboard

The web dashboard displays real-time portfolio information:

- **Summary Stats**: Total equity, cash, daily/total P&L
- **Equity Curve**: Interactive Chart.js visualization
- **Positions Table**: Current holdings with weights and P&L
- **Momentum Signal**: Ranked sectors with target weights
- **Rebalance Countdown**: Days until next monthly rebalance

```bash
python main.py dashboard --port 5050
# Open http://localhost:5050
```

## Data Schemas

### Executions CSV (`data/executions/YYYY-MM-DD.csv`)

| Column | Type | Description |
|--------|------|-------------|
| trade_id | UUID | Unique trade identifier |
| timestamp | ISO 8601 | Execution time (UTC) |
| symbol | string | Instrument ticker |
| asset_class | string | STK, FUT, CRYPTO, etc. |
| side | string | BUY or SELL |
| quantity | float | Shares/contracts |
| intended_price | float | Expected fill price |
| fill_price | float | Actual fill price |
| slippage_bps | float | Slippage in basis points |
| commission | float | Commission paid |
| commission_currency | string | Commission currency |

### Snapshots JSON (`data/snapshots/YYYY-MM-DD.json`)

```json
{
  "timestamp": "2026-01-27T16:35:00Z",
  "total_equity": 100000.00,
  "cash": 5000.00,
  "positions": [
    {
      "symbol": "SXLK",
      "quantity": 150,
      "avg_cost": 185.50,
      "market_price": 190.25,
      "market_value": 28537.50,
      "unrealized_pnl": 712.50
    }
  ]
}
```

### Annotations JSON (`data/annotations/<trade_id>.json`)

```json
{
  "trade_id": "uuid-here",
  "created_at": "2026-01-27T14:30:00Z",
  "pre_trade": {
    "symbol": "SXLK",
    "thesis": "Top momentum sector, technology leading",
    "intended_entry": 188.00,
    "position_size_rationale": "33% target weight per strategy",
    "exit_plan": "Hold until next rebalance or stop at -10%"
  },
  "post_trade": {
    "outcome": "Filled at 188.25, holding",
    "matched_expectation": true,
    "lesson": "Limit orders work well for liquid ETFs"
  }
}
```

## ETF Universe

UK-listed UCITS sector ETFs on London Stock Exchange:

| Ticker | Sector | Full Name |
|--------|--------|-----------|
| SXLK.L | Technology | SPDR S&P US Technology Select Sector |
| SXLF.L | Financials | SPDR S&P US Financials Select Sector |
| SXLE.L | Energy | SPDR S&P US Energy Select Sector |
| SXLV.L | Health Care | SPDR S&P US Health Care Select Sector |
| SXLY.L | Consumer Discretionary | SPDR S&P US Consumer Discretionary |
| SXLP.L | Consumer Staples | SPDR S&P US Consumer Staples |
| SXLI.L | Industrials | SPDR S&P US Industrials Select Sector |
| SXLB.L | Materials | SPDR S&P US Materials Select Sector |
| SXLU.L | Utilities | SPDR S&P US Utilities Select Sector |

## Performance Metrics

| Metric | Description |
|--------|-------------|
| Total Return | Cumulative return over period |
| Annualized Return | Compound annual growth rate (CAGR) |
| Annualized Volatility | Standard deviation × √252 |
| Sharpe Ratio | Excess return / volatility (0% risk-free) |
| Max Drawdown | Largest peak-to-trough decline |
| Max Drawdown Duration | Longest time to recover |
| Win Rate | % of profitable trades |
| Profit Factor | Gross profits / gross losses |

## Workflows

### Monthly Rebalance (1st of each month)

```bash
# 1. Generate signal
python main.py signal

# 2. Get trade list
python main.py rebalance

# 3. Execute trades manually in IBKR

# 4. Log executions
python main.py pull
python main.py snapshot

# 5. Document trades
python main.py annotate <trade_id> --post
```

### Monthly Report Generation

```bash
# 1. Add commentary (optional)
echo "Strong month driven by tech outperformance..." > data/annotations/monthly/2026-01.md

# 2. Generate PDF
python main.py report 2026-01

# 3. Review
open reports/monthly/2026-01-report.pdf
```

See [WORKFLOW.md](WORKFLOW.md) for detailed operational procedures.

## Documentation

- [WORKFLOW.md](WORKFLOW.md) - Daily/monthly operational guide
- [docs/STRATEGY.md](docs/STRATEGY.md) - Strategy design and rationale
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - Technical architecture
- [docs/OPERATIONS.md](docs/OPERATIONS.md) - Deployment and operations guide

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

## Disclaimer

**This project is for educational and paper trading purposes only.**

- Not financial advice
- Past performance does not guarantee future results
- The author is not responsible for any trading losses
- Always do your own research before trading
- This system is designed for building a track record, not for live trading with real money without proper risk management

## License

MIT License - see [LICENSE](LICENSE) for details.

---

Built for institutional trading recruitment. Questions? Open an issue.

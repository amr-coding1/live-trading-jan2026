# Technical Architecture

## Overview

This document describes the technical architecture of the live trading track record infrastructure.

## System Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              External Systems                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  Interactive Brokers TWS/Gateway          Yahoo Finance API                 │
│  (Portfolio data, executions)             (Historical prices)               │
└───────────────────┬───────────────────────────────┬─────────────────────────┘
                    │                               │
                    │ ib_insync                     │ yfinance
                    ▼                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Core Modules                                    │
├──────────────────────┬──────────────────────┬───────────────────────────────┤
│  execution_logger.py │  signals/momentum.py │  signals/rebalance.py        │
│  - IBKR connection   │  - Price fetching    │  - Portfolio comparison      │
│  - Pull executions   │  - 12-1 calculation  │  - Trade generation          │
│  - Save snapshots    │  - Sector ranking    │  - Weight thresholds         │
└──────────────────────┴──────────────────────┴───────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Data Storage                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  data/executions/*.csv     data/snapshots/*.json     data/annotations/*.json│
│  (Trade records)           (Portfolio states)        (Trade documentation)  │
└─────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Analysis & Reporting                               │
├──────────────────────┬──────────────────────┬───────────────────────────────┤
│  performance.py      │  slippage_analyzer.py│  export.py                   │
│  - Returns calc      │  - Slippage metrics  │  - PDF generation            │
│  - Sharpe ratio      │  - Outlier detection │  - Monthly reports           │
│  - Max drawdown      │  - Cost analysis     │  - ReportLab                 │
└──────────────────────┴──────────────────────┴───────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           User Interfaces                                    │
├──────────────────────┬──────────────────────┬───────────────────────────────┤
│  main.py (CLI)       │  dashboard.py        │  scheduler.py                │
│  - argparse commands │  - Flask web app     │  - schedule library          │
│  - Interactive I/O   │  - Chart.js charts   │  - Automated tasks           │
└──────────────────────┴──────────────────────┴───────────────────────────────┘
```

---

## Module Details

### execution_logger.py

**Purpose**: Interface with Interactive Brokers for trade and portfolio data.

**Key Classes**:
```python
class IBKRConnection:
    """Manages connection to IBKR TWS/Gateway."""

    def __init__(self, config: dict)
    def connect(self, max_retries: int = 3) -> bool
    def disconnect() -> None
```

**Key Functions**:
```python
def get_todays_executions(ib: IB) -> list[dict]
    """Pull execution reports for today."""

def get_portfolio_snapshot(ib: IB) -> dict
    """Get current portfolio state."""

def save_executions(executions: list[dict], output_dir: str) -> Path
    """Write executions to dated CSV file."""

def save_snapshot(snapshot: dict, output_dir: str) -> Path
    """Write snapshot to dated JSON file."""
```

**Dependencies**: `ib_insync`

---

### signals/momentum.py

**Purpose**: Generate 12-1 momentum signal for sector ETFs.

**Key Constants**:
```python
SECTOR_ETFS = [
    "SXLK.L", "SXLF.L", "SXLE.L", "SXLV.L", "SXLY.L",
    "SXLP.L", "SXLI.L", "SXLB.L", "SXLU.L"
]

SECTOR_NAMES = {
    "SXLK.L": "Technology",
    "SXLF.L": "Financials",
    # ...
}
```

**Key Functions**:
```python
def calculate_momentum_12_1(prices: pd.Series) -> float
    """Calculate 12-month return excluding most recent month."""

def generate_momentum_signal(top_n: int = 3) -> dict
    """Generate complete momentum signal with rankings."""
    # Returns: {
    #     "signal_date": "2026-01-27",
    #     "ranked": pd.DataFrame,
    #     "selected": ["SXLK.L", "SXLI.L", "SXLU.L"],
    #     "target_weight": 0.333
    # }

def format_signal_report(signal: dict, cash: float = 0) -> str
    """Format signal as human-readable report."""
```

**Dependencies**: `yfinance`, `pandas`, `numpy`

---

### signals/rebalance.py

**Purpose**: Compare current portfolio to signal and generate trade list.

**Key Functions**:
```python
def load_latest_snapshot(snapshots_dir: str) -> Optional[dict]
    """Load most recent portfolio snapshot."""

def calculate_current_weights(snapshot: dict) -> dict[str, float]
    """Calculate current position weights."""

def generate_rebalance_trades(
    snapshots_dir: str,
    top_n: int = 3,
    min_threshold: float = 0.02
) -> dict
    """Generate list of trades to reach target allocation."""
    # Returns: {
    #     "date": "2026-01-27",
    #     "current_positions": {...},
    #     "target_weights": {...},
    #     "trades": [
    #         {"symbol": "SXLU", "action": "BUY", "shares": 160, ...}
    #     ]
    # }
```

---

### performance.py

**Purpose**: Calculate portfolio performance metrics.

**Key Functions**:
```python
def load_snapshots(snapshots_dir: str) -> pd.DataFrame
    """Load all snapshots into DataFrame."""

def compute_equity_curve(snapshots: pd.DataFrame) -> pd.Series
    """Extract equity curve from snapshots."""

def total_return(equity_curve: pd.Series) -> float
def annualized_return(equity_curve: pd.Series) -> float
def annualized_volatility(equity_curve: pd.Series) -> float
def sharpe_ratio(equity_curve: pd.Series, risk_free: float = 0) -> float
def max_drawdown(equity_curve: pd.Series) -> tuple[float, int]

def load_executions(executions_dir: str) -> pd.DataFrame
    """Load all execution CSVs into DataFrame."""

def win_rate(executions: pd.DataFrame) -> float
def profit_factor(executions: pd.DataFrame) -> float

def compute_all_metrics(
    snapshots_dir: str,
    executions_dir: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> dict
    """Compute all performance metrics."""
```

**Dependencies**: `pandas`, `numpy`

---

### slippage_analyzer.py

**Purpose**: Analyze execution quality by comparing intended vs fill prices.

**Key Functions**:
```python
def analyze_slippage(
    executions_dir: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    outlier_threshold_bps: float = 10.0
) -> dict
    """Analyze slippage across all executions."""
    # Returns: {
    #     "total_trades": 50,
    #     "mean_slippage_bps": 2.5,
    #     "median_slippage_bps": 1.8,
    #     "std_slippage_bps": 3.2,
    #     "outliers": [...],
    #     "by_symbol": {...}
    # }
```

**Slippage Calculation**:
```
slippage_bps = (fill_price - intended_price) / intended_price * 10000
```
- Positive = paid more than intended (unfavorable for buys)
- Negative = paid less than intended (favorable for buys)

---

### export.py

**Purpose**: Generate PDF reports for monthly performance.

**Key Functions**:
```python
def generate_monthly_report(
    year_month: str,  # "2026-01"
    snapshots_dir: str,
    executions_dir: str,
    annotations_dir: str,
    output_dir: str
) -> Path
    """Generate PDF report for specified month."""
```

**Report Contents**:
1. Header with month/year and portfolio name
2. Performance summary table (return, Sharpe, drawdown)
3. Equity curve chart
4. Position breakdown
5. Trade list with slippage
6. Monthly commentary (if provided)

**Dependencies**: `reportlab`, `matplotlib`

---

### annotations.py

**Purpose**: Document trade rationale before and after execution.

**Data Schema**:
```python
{
    "trade_id": "uuid",
    "created_at": "2026-01-27T14:30:00Z",
    "pre_trade": {
        "symbol": "SXLK",
        "thesis": "Top momentum sector",
        "intended_entry": 188.00,
        "position_size_rationale": "33% target weight",
        "exit_plan": "Hold until next rebalance"
    },
    "post_trade": {
        "outcome": "Filled at 188.25",
        "matched_expectation": True,
        "lesson": "Limit orders work well"
    }
}
```

**Key Functions**:
```python
def interactive_annotate(
    annotations_dir: str,
    trade_id: Optional[str],
    pre_trade: bool,
    post_trade: bool
) -> None
    """Interactive CLI for creating/updating annotations."""

def list_annotations(annotations_dir: str) -> list[dict]
    """List all annotations with summary info."""
```

---

### dashboard.py

**Purpose**: Web interface for portfolio monitoring.

**Stack**:
- **Backend**: Flask
- **Frontend**: Bootstrap 5, Chart.js
- **Template**: Jinja2

**Routes**:
```python
@app.route("/")
def dashboard():
    """Main dashboard view."""
```

**Data Flow**:
```
Request → load_latest_snapshot() → get_equity_chart_data()
        → get_signal_data() → render_template()
```

---

### scheduler.py

**Purpose**: Automated task execution.

**Scheduled Jobs**:
| Job | Schedule | Function |
|-----|----------|----------|
| Daily Snapshot | 16:35 UTC | `job_daily_snapshot()` |
| Monthly Signal | 1st @ 08:00 UTC | `job_monthly_signal()` |

**Dependencies**: `schedule`

---

## Data Flow Diagrams

### Daily Snapshot Flow

```
IBKR TWS ──► IBKRConnection.connect() ──► get_portfolio_snapshot()
                                                    │
                                                    ▼
                                          save_snapshot()
                                                    │
                                                    ▼
                                    data/snapshots/2026-01-27.json
```

### Monthly Rebalance Flow

```
yfinance ──► generate_momentum_signal() ──► signal with rankings
                                                    │
                                                    ▼
snapshot ──► load_latest_snapshot() ──► generate_rebalance_trades()
                                                    │
                                                    ▼
                                          Trade list for execution
```

### Report Generation Flow

```
snapshots/*.json ─┐
                  ├──► compute_all_metrics() ──► generate_monthly_report()
executions/*.csv ─┤                                       │
                  │                                       ▼
annotations/*.json┘                           reports/monthly/2026-01.pdf
```

---

## Configuration

### config/config.yaml

```yaml
ibkr:
  host: "127.0.0.1"
  port: 7497          # 7497 for paper, 7496 for live
  client_id: 1
  account: ""         # Leave empty to use default account

paths:
  executions: "data/executions"
  snapshots: "data/snapshots"
  annotations: "data/annotations"
  reports: "reports/monthly"
  logs: "logs"

strategy:
  top_n: 3            # Number of sectors to select
  min_threshold: 0.02 # Minimum weight diff to trade (2%)
```

---

## Error Handling

### Connection Errors

```python
try:
    conn.connect(max_retries=3)
except ConnectionError as e:
    logger.error(f"IBKR connection failed: {e}")
    # Graceful degradation - use cached data
```

### Data Fetch Errors

```python
try:
    prices = yf.download(symbol, period="14mo")
except Exception as e:
    logger.warning(f"Failed to fetch {symbol}: {e}")
    # Skip symbol, continue with others
```

### Missing Data

- Missing snapshots: Return empty DataFrame, display warning
- Missing executions: Skip P&L calculations
- Missing annotations: Generate report without commentary

---

## Testing

### Unit Tests

Location: `tests/test_performance.py`

```python
def test_total_return():
    """Test total return calculation."""

def test_sharpe_ratio():
    """Test Sharpe ratio calculation."""

def test_max_drawdown():
    """Test maximum drawdown calculation."""
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

---

## Security Considerations

### Sensitive Data

The following should NEVER be committed to git:
- `config/config.yaml` (contains account info)
- `data/` directory (contains portfolio data)
- `reports/` directory (contains performance data)
- `logs/` directory (may contain account info)

### API Security

- IBKR API runs locally only (127.0.0.1)
- No external network exposure
- Dashboard binds to localhost by default

### Credentials

- No API keys stored in code
- IBKR authentication handled by TWS/Gateway
- yfinance requires no authentication

---

## Deployment

### Local Development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config/config.example.yaml config/config.yaml
# Edit config.yaml with your settings
```

### Production (Personal Use)

1. Set up on dedicated machine/VM
2. Configure scheduler as system service
3. Ensure TWS/Gateway runs at startup
4. Set up log rotation

### NOT Recommended

- Cloud deployment (IBKR API is local-only)
- Docker (TWS requires GUI for initial setup)
- Shared hosting (security concerns)

---

## Dependencies

### Production

| Package | Version | Purpose |
|---------|---------|---------|
| ib_insync | ≥0.9.86 | IBKR API wrapper |
| pandas | ≥2.0.0 | Data manipulation |
| numpy | ≥1.24.0 | Numerical operations |
| matplotlib | ≥3.7.0 | Chart generation |
| reportlab | ≥4.0.0 | PDF generation |
| pyyaml | ≥6.0 | Config parsing |
| yfinance | ≥0.2.0 | Price data |
| flask | ≥3.0.0 | Web dashboard |
| schedule | ≥1.2.0 | Task scheduling |

### Development

| Package | Version | Purpose |
|---------|---------|---------|
| pytest | ≥7.0.0 | Testing |
| pytest-mock | ≥3.10.0 | Mocking |
| pytest-cov | ≥4.0.0 | Coverage |
| black | ≥23.0.0 | Formatting |
| ruff | ≥0.1.0 | Linting |
| mypy | ≥1.0.0 | Type checking |

---

## Future Considerations

### Potential Enhancements

1. **Database Backend**: Replace JSON/CSV with SQLite or PostgreSQL
2. **Real-time Updates**: WebSocket dashboard updates
3. **Backtesting Module**: Historical strategy testing
4. **Alert System**: Email/SMS notifications
5. **Multi-strategy Support**: Run multiple strategies in parallel

### Not Planned

- Automated order execution (intentionally manual)
- Machine learning signals (keeping it simple)
- High-frequency features (not the use case)

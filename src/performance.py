"""Performance metrics calculation for trading track record.

Computes standard portfolio performance metrics including returns,
volatility, Sharpe ratio, drawdown, and win rate statistics.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


def load_snapshots(
    snapshots_dir: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Load portfolio snapshots from JSON files.

    Args:
        snapshots_dir: Directory containing snapshot JSON files.
        start_date: Start date string (YYYY-MM-DD), inclusive.
        end_date: End date string (YYYY-MM-DD), inclusive.

    Returns:
        DataFrame with date index and portfolio values.
    """
    snap_path = Path(snapshots_dir)
    if not snap_path.exists():
        logger.warning(f"Snapshots directory not found: {snapshots_dir}")
        return pd.DataFrame()

    all_files = sorted(snap_path.glob("*.json"))
    if not all_files:
        logger.warning("No snapshot files found")
        return pd.DataFrame()

    records = []
    for json_file in all_files:
        file_date = json_file.stem

        if start_date and file_date < start_date:
            continue
        if end_date and file_date > end_date:
            continue

        try:
            with open(json_file) as f:
                data = json.load(f)
                records.append({
                    "date": file_date,
                    "timestamp": data.get("timestamp"),
                    "total_equity": data.get("total_equity", 0),
                    "cash": data.get("cash", 0),
                    "num_positions": len(data.get("positions", [])),
                })
        except Exception as e:
            logger.warning(f"Failed to load {json_file}: {e}")

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    return df


def compute_equity_curve(snapshots: pd.DataFrame) -> pd.Series:
    """Extract equity curve from snapshots.

    Args:
        snapshots: DataFrame from load_snapshots().

    Returns:
        Series of daily equity values indexed by date.
    """
    if snapshots.empty:
        return pd.Series(dtype=float)

    return snapshots["total_equity"]


def compute_returns(equity: pd.Series) -> pd.Series:
    """Compute daily returns from equity curve.

    Args:
        equity: Series of equity values.

    Returns:
        Series of daily percentage returns.
    """
    if len(equity) < 2:
        return pd.Series(dtype=float)

    return equity.pct_change().dropna()


def total_return(equity: pd.Series) -> float:
    """Calculate total return over the period.

    Args:
        equity: Series of equity values.

    Returns:
        Total return as decimal (0.10 = 10%).
    """
    if len(equity) < 2:
        return 0.0

    return (equity.iloc[-1] / equity.iloc[0]) - 1


def annualized_return(equity: pd.Series) -> float:
    """Calculate annualized return.

    Args:
        equity: Series of equity values.

    Returns:
        Annualized return as decimal.
    """
    if len(equity) < 2:
        return 0.0

    total_ret = total_return(equity)
    days = (equity.index[-1] - equity.index[0]).days

    if days <= 0:
        return 0.0

    years = days / 365.25
    if years < 1 / 365.25:
        return total_ret

    return (1 + total_ret) ** (1 / years) - 1


def annualized_volatility(returns: pd.Series) -> float:
    """Calculate annualized volatility.

    Args:
        returns: Series of daily returns.

    Returns:
        Annualized volatility as decimal.
    """
    if len(returns) < 2:
        return 0.0

    return returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Calculate Sharpe ratio.

    Args:
        returns: Series of daily returns.
        risk_free_rate: Annual risk-free rate (default 0%).

    Returns:
        Annualized Sharpe ratio.
    """
    if len(returns) < 2:
        return 0.0

    excess_returns = returns - (risk_free_rate / TRADING_DAYS_PER_YEAR)
    if excess_returns.std() == 0:
        return 0.0

    return (excess_returns.mean() / excess_returns.std()) * np.sqrt(TRADING_DAYS_PER_YEAR)


def rolling_sharpe(
    returns: pd.Series,
    window: int = 30,
    risk_free_rate: float = 0.0,
) -> pd.Series:
    """Calculate rolling Sharpe ratio.

    Args:
        returns: Series of daily returns.
        window: Rolling window in days.
        risk_free_rate: Annual risk-free rate.

    Returns:
        Series of rolling Sharpe ratios.
    """
    if len(returns) < window:
        return pd.Series(dtype=float)

    daily_rf = risk_free_rate / TRADING_DAYS_PER_YEAR
    excess = returns - daily_rf

    rolling_mean = excess.rolling(window).mean()
    rolling_std = excess.rolling(window).std()

    # Avoid division by zero - replace zero std with NaN
    rolling_std = rolling_std.replace(0, np.nan)

    rolling_sharpe_values = (rolling_mean / rolling_std) * np.sqrt(TRADING_DAYS_PER_YEAR)
    return rolling_sharpe_values.dropna()


def max_drawdown(equity: pd.Series) -> float:
    """Calculate maximum drawdown.

    Args:
        equity: Series of equity values.

    Returns:
        Maximum drawdown as positive decimal (0.10 = 10% drawdown).
    """
    if len(equity) < 2:
        return 0.0

    cummax = equity.cummax()

    # Avoid division by zero - replace zero cummax with NaN
    cummax_safe = cummax.replace(0, np.nan)
    drawdown = (equity - cummax) / cummax_safe

    if drawdown.dropna().empty:
        return 0.0

    return abs(drawdown.min())


def max_drawdown_duration(equity: pd.Series) -> int:
    """Calculate maximum drawdown duration in days.

    Args:
        equity: Series of equity values.

    Returns:
        Maximum number of days in drawdown.
    """
    if len(equity) < 2:
        return 0

    cummax = equity.cummax()
    is_drawdown = equity < cummax

    if not is_drawdown.any():
        return 0

    duration = 0
    max_duration = 0
    prev_in_dd = False

    for in_dd in is_drawdown:
        if in_dd:
            duration += 1
            max_duration = max(max_duration, duration)
            prev_in_dd = True
        else:
            duration = 0
            prev_in_dd = False

    return max_duration


def drawdown_series(equity: pd.Series) -> pd.Series:
    """Calculate drawdown series.

    Args:
        equity: Series of equity values.

    Returns:
        Series of drawdown values (negative decimals).
    """
    if len(equity) < 2:
        return pd.Series(dtype=float)

    cummax = equity.cummax()

    # Avoid division by zero - replace zero cummax with NaN
    cummax_safe = cummax.replace(0, np.nan)
    return (equity - cummax) / cummax_safe


def load_executions_for_performance(
    executions_dir: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Load executions for win rate analysis.

    Args:
        executions_dir: Directory containing execution CSV files.
        start_date: Start date string (YYYY-MM-DD), inclusive.
        end_date: End date string (YYYY-MM-DD), inclusive.

    Returns:
        Combined DataFrame of all executions in range.
    """
    exec_path = Path(executions_dir)
    if not exec_path.exists():
        return pd.DataFrame()

    all_files = sorted(exec_path.glob("*.csv"))
    if not all_files:
        return pd.DataFrame()

    dfs = []
    for csv_file in all_files:
        file_date = csv_file.stem
        if start_date and file_date < start_date:
            continue
        if end_date and file_date > end_date:
            continue

        try:
            df = pd.read_csv(csv_file)
            dfs.append(df)
        except Exception as e:
            logger.warning(f"Failed to load {csv_file}: {e}")

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True)


def compute_trade_pnl(executions: pd.DataFrame) -> pd.DataFrame:
    """Compute P&L for round-trip trades.

    Matches buys and sells by symbol using FIFO.

    Args:
        executions: DataFrame of executions.

    Returns:
        DataFrame of completed round-trip trades with P&L.
    """
    if executions.empty:
        return pd.DataFrame()

    executions = executions.sort_values("timestamp").copy()
    trades = []
    open_positions: dict[str, list] = {}

    for _, row in executions.iterrows():
        symbol = row["symbol"]
        side = row["side"]
        qty = row["quantity"]
        price = row["fill_price"]
        commission = row.get("commission", 0) or 0

        if symbol not in open_positions:
            open_positions[symbol] = []

        if side == "BUY":
            open_positions[symbol].append({
                "quantity": qty,
                "price": price,
                "commission": commission,
                "timestamp": row["timestamp"],
            })
        else:
            remaining = qty
            total_cost = 0
            total_entry_commission = 0

            while remaining > 0 and open_positions[symbol]:
                pos = open_positions[symbol][0]
                close_qty = min(remaining, pos["quantity"])

                total_cost += close_qty * pos["price"]
                total_entry_commission += pos["commission"] * (close_qty / pos["quantity"])

                pos["quantity"] -= close_qty
                remaining -= close_qty

                if pos["quantity"] <= 0:
                    open_positions[symbol].pop(0)

            closed_qty = qty - remaining
            if closed_qty > 0:
                avg_entry = total_cost / closed_qty
                gross_pnl = (price - avg_entry) * closed_qty
                net_pnl = gross_pnl - total_entry_commission - commission

                trades.append({
                    "symbol": symbol,
                    "quantity": closed_qty,
                    "entry_price": avg_entry,
                    "exit_price": price,
                    "gross_pnl": gross_pnl,
                    "commission": total_entry_commission + commission,
                    "net_pnl": net_pnl,
                    "exit_timestamp": row["timestamp"],
                })

    return pd.DataFrame(trades)


def win_rate(trades: pd.DataFrame) -> float:
    """Calculate win rate from completed trades.

    Args:
        trades: DataFrame with net_pnl column.

    Returns:
        Win rate as decimal (0.55 = 55%).
    """
    if trades.empty:
        return 0.0

    return (trades["net_pnl"] > 0).mean()


def profit_factor(trades: pd.DataFrame) -> float:
    """Calculate profit factor (gross profits / gross losses).

    Args:
        trades: DataFrame with net_pnl column.

    Returns:
        Profit factor (>1 is profitable).
    """
    if trades.empty:
        return 0.0

    profits = trades[trades["net_pnl"] > 0]["net_pnl"].sum()
    losses = abs(trades[trades["net_pnl"] < 0]["net_pnl"].sum())

    if losses == 0:
        return float("inf") if profits > 0 else 0.0

    return profits / losses


def compute_all_metrics(
    snapshots_dir: str,
    executions_dir: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Compute all performance metrics.

    Args:
        snapshots_dir: Directory containing snapshot JSON files.
        executions_dir: Directory containing execution CSV files.
        start_date: Start date string (YYYY-MM-DD), inclusive.
        end_date: End date string (YYYY-MM-DD), inclusive.

    Returns:
        Dictionary of all performance metrics.
    """
    snapshots = load_snapshots(snapshots_dir, start_date, end_date)
    equity = compute_equity_curve(snapshots)
    returns = compute_returns(equity)

    executions = load_executions_for_performance(executions_dir, start_date, end_date)
    trades = compute_trade_pnl(executions)

    metrics = {
        "period": {
            "start_date": str(equity.index[0].date()) if len(equity) > 0 else None,
            "end_date": str(equity.index[-1].date()) if len(equity) > 0 else None,
            "trading_days": len(equity),
        },
        "returns": {
            "total_return": round(total_return(equity) * 100, 2),
            "annualized_return": round(annualized_return(equity) * 100, 2),
        },
        "risk": {
            "annualized_volatility": round(annualized_volatility(returns) * 100, 2),
            "sharpe_ratio": round(sharpe_ratio(returns), 2),
            "max_drawdown": round(max_drawdown(equity) * 100, 2),
            "max_drawdown_duration_days": max_drawdown_duration(equity),
        },
        "trades": {
            "total_trades": len(trades),
            "win_rate": round(win_rate(trades) * 100, 1),
            "profit_factor": round(profit_factor(trades), 2),
        },
        "equity": {
            "starting_equity": equity.iloc[0] if len(equity) > 0 else 0,
            "ending_equity": equity.iloc[-1] if len(equity) > 0 else 0,
        },
    }

    return metrics


def format_performance_report(metrics: dict) -> str:
    """Format performance metrics as readable text report.

    Args:
        metrics: Output from compute_all_metrics().

    Returns:
        Formatted text report.
    """
    lines = ["=" * 50, "PERFORMANCE REPORT", "=" * 50, ""]

    period = metrics["period"]
    lines.append("PERIOD")
    lines.append("-" * 30)
    lines.append(f"Start: {period['start_date']}")
    lines.append(f"End: {period['end_date']}")
    lines.append(f"Trading days: {period['trading_days']}")
    lines.append("")

    equity = metrics["equity"]
    lines.append("EQUITY")
    lines.append("-" * 30)
    lines.append(f"Starting: ${equity['starting_equity']:,.2f}")
    lines.append(f"Ending: ${equity['ending_equity']:,.2f}")
    lines.append("")

    returns = metrics["returns"]
    lines.append("RETURNS")
    lines.append("-" * 30)
    lines.append(f"Total return: {returns['total_return']:.2f}%")
    lines.append(f"Annualized return: {returns['annualized_return']:.2f}%")
    lines.append("")

    risk = metrics["risk"]
    lines.append("RISK METRICS")
    lines.append("-" * 30)
    lines.append(f"Annualized volatility: {risk['annualized_volatility']:.2f}%")
    lines.append(f"Sharpe ratio: {risk['sharpe_ratio']:.2f}")
    lines.append(f"Max drawdown: {risk['max_drawdown']:.2f}%")
    lines.append(f"Max drawdown duration: {risk['max_drawdown_duration_days']} days")
    lines.append("")

    trades = metrics["trades"]
    lines.append("TRADE STATISTICS")
    lines.append("-" * 30)
    lines.append(f"Total trades: {trades['total_trades']}")
    lines.append(f"Win rate: {trades['win_rate']:.1f}%")
    lines.append(f"Profit factor: {trades['profit_factor']:.2f}")
    lines.append("")

    lines.append("=" * 50)
    return "\n".join(lines)

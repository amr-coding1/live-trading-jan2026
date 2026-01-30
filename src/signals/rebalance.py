"""Portfolio rebalancing logic.

Compares current portfolio to target weights from momentum signal
and generates a trade list for manual execution.
"""

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from .momentum import generate_momentum_signal, SECTOR_ETFS

logger = logging.getLogger(__name__)

DEFAULT_MIN_TRADE_THRESHOLD = 0.02


def load_latest_snapshot(snapshots_dir: str) -> Optional[dict]:
    """Load most recent portfolio snapshot.

    Args:
        snapshots_dir: Path to snapshots directory.

    Returns:
        Snapshot dictionary or None if no snapshots found.
    """
    snap_path = Path(snapshots_dir)

    if not snap_path.exists():
        logger.warning(f"Snapshots directory not found: {snapshots_dir}")
        return None

    json_files = sorted(snap_path.glob("*.json"), reverse=True)

    if not json_files:
        logger.warning("No snapshot files found")
        return None

    latest = json_files[0]
    logger.info(f"Loading snapshot from {latest.name}")

    with open(latest) as f:
        return json.load(f)


def get_current_weights(snapshot: dict) -> dict[str, float]:
    """Calculate current portfolio weights from snapshot.

    Args:
        snapshot: Portfolio snapshot dictionary.

    Returns:
        Dictionary mapping symbol to weight (0-1).
    """
    total_equity = snapshot.get("total_equity", 0)

    if total_equity <= 0:
        return {}

    weights = {}
    for pos in snapshot.get("positions", []):
        symbol = pos.get("symbol")
        market_value = pos.get("market_value", 0)

        if symbol and market_value:
            weights[symbol] = market_value / total_equity

    return weights


def get_current_prices(symbols: list[str]) -> dict[str, float]:
    """Get current prices for symbols.

    Args:
        symbols: List of ticker symbols.

    Returns:
        Dictionary mapping symbol to current price.

    Raises:
        ValueError: If price fetch fails for any required symbol.
    """
    prices = {}
    failed_symbols = []

    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d")
            if not hist.empty:
                price = hist["Close"].iloc[-1]
                if price > 0:
                    prices[symbol] = price
                else:
                    logger.warning(f"Invalid price (zero/negative) for {symbol}")
                    failed_symbols.append(symbol)
            else:
                logger.warning(f"No price data returned for {symbol}")
                failed_symbols.append(symbol)
        except Exception as e:
            logger.warning(f"Failed to get price for {symbol}: {e}")
            failed_symbols.append(symbol)

    if failed_symbols:
        logger.error(f"Failed to get prices for: {failed_symbols}")

    return prices


def calculate_trades(
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    total_equity: float,
    current_prices: dict[str, float],
    current_positions: dict[str, float],
    min_threshold: float = DEFAULT_MIN_TRADE_THRESHOLD,
) -> pd.DataFrame:
    """Calculate required trades to rebalance portfolio.

    Args:
        current_weights: Current weight by symbol.
        target_weights: Target weight by symbol.
        total_equity: Total portfolio value.
        current_prices: Current price by symbol.
        current_positions: Current shares held by symbol.
        min_threshold: Minimum weight difference to trigger trade.

    Returns:
        DataFrame with trade details.
    """
    all_symbols = set(current_weights.keys()) | set(target_weights.keys())

    trades = []
    for symbol in sorted(all_symbols):
        current = current_weights.get(symbol, 0)
        target = target_weights.get(symbol, 0)
        diff = target - current

        price = current_prices.get(symbol, 0)

        if abs(diff) < min_threshold:
            action = "HOLD"
            shares_to_trade = 0
        elif price <= 0:
            # Skip trade if price unavailable - log and continue
            logger.warning(f"Skipping {symbol}: no valid price available")
            action = "HOLD"
            shares_to_trade = 0
        elif diff > 0:
            action = "BUY"
            target_value = target * total_equity
            current_value = current * total_equity
            value_diff = target_value - current_value

            # Use math.floor to avoid over-buying
            shares_to_trade = math.floor(value_diff / price)
            remainder = value_diff - (shares_to_trade * price)
            if remainder > 0:
                logger.debug(f"{symbol}: {remainder:.2f} cash remainder from rounding")
        else:
            action = "SELL"
            current_shares = current_positions.get(symbol, 0)
            target_value = target * total_equity
            current_value = current * total_equity
            value_diff = current_value - target_value

            # Use math.floor to avoid over-selling
            shares_to_sell = math.floor(value_diff / price)
            shares_to_trade = min(shares_to_sell, current_shares)

        trades.append({
            "symbol": symbol,
            "current_weight": current,
            "target_weight": target,
            "weight_diff": diff,
            "action": action,
            "shares_to_trade": abs(shares_to_trade),
            "price": current_prices.get(symbol, 0),
        })

    df = pd.DataFrame(trades)

    df = df[df["action"] != "HOLD"]

    df = df.sort_values(
        ["action", "weight_diff"],
        ascending=[True, False]
    ).reset_index(drop=True)

    return df


def generate_rebalance_trades(
    snapshots_dir: str,
    top_n: int = 3,
    min_threshold: float = DEFAULT_MIN_TRADE_THRESHOLD,
) -> dict:
    """Generate rebalance trade list.

    Args:
        snapshots_dir: Path to snapshots directory.
        top_n: Number of top sectors to select.
        min_threshold: Minimum weight difference to trigger trade.

    Returns:
        Dictionary containing:
            - date: Rebalance date
            - signal: Momentum signal data
            - snapshot: Current portfolio snapshot
            - trades: DataFrame of required trades
            - current_weights: Current portfolio weights
            - target_weights: Target portfolio weights
    """
    snapshot = load_latest_snapshot(snapshots_dir)

    if snapshot is None:
        raise ValueError("No portfolio snapshot found. Run 'python main.py snapshot' first.")

    signal = generate_momentum_signal(top_n=top_n)

    current_weights = get_current_weights(snapshot)
    target_weights = signal["target_weights"]

    all_symbols = list(set(current_weights.keys()) | set(target_weights.keys()))
    current_prices = get_current_prices(all_symbols)

    current_positions = {}
    for pos in snapshot.get("positions", []):
        symbol = pos.get("symbol")
        qty = pos.get("quantity", 0)
        if symbol:
            current_positions[symbol] = qty

    trades = calculate_trades(
        current_weights=current_weights,
        target_weights=target_weights,
        total_equity=snapshot.get("total_equity", 0),
        current_prices=current_prices,
        current_positions=current_positions,
        min_threshold=min_threshold,
    )

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "signal": signal,
        "snapshot": snapshot,
        "trades": trades,
        "current_weights": current_weights,
        "target_weights": target_weights,
        "total_equity": snapshot.get("total_equity", 0),
        "cash": snapshot.get("cash", 0),
    }


def format_rebalance_report(rebalance: dict) -> str:
    """Format rebalance trades as readable text report.

    Args:
        rebalance: Output from generate_rebalance_trades().

    Returns:
        Formatted text report.
    """
    lines = [
        f"REBALANCE TRADES - {rebalance['date']}",
        "=" * 60,
        "",
        f"Total Equity: ${rebalance['total_equity']:,.2f}",
        f"Cash Available: ${rebalance['cash']:,.2f}",
        "",
    ]

    trades = rebalance["trades"]

    if trades.empty:
        lines.append("No trades required. Portfolio is within threshold.")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"{'Symbol':<8}{'Current':<10}{'Target':<10}{'Action':<8}{'Shares':<8}{'Est. Value'}")
    lines.append("-" * 60)

    for _, row in trades.iterrows():
        current_str = f"{row['current_weight']*100:.1f}%"
        target_str = f"{row['target_weight']*100:.1f}%"
        est_value = row['shares_to_trade'] * row['price']

        lines.append(
            f"{row['symbol']:<8}{current_str:<10}{target_str:<10}"
            f"{row['action']:<8}{row['shares_to_trade']:<8}${est_value:,.0f}"
        )

    lines.append("")
    lines.append("-" * 60)

    buy_count = len(trades[trades["action"] == "BUY"])
    sell_count = len(trades[trades["action"] == "SELL"])
    lines.append(f"Total trades: {len(trades)} ({buy_count} buys, {sell_count} sells)")

    buy_value = trades[trades["action"] == "BUY"].apply(
        lambda r: r["shares_to_trade"] * r["price"], axis=1
    ).sum() if buy_count > 0 else 0

    sell_value = trades[trades["action"] == "SELL"].apply(
        lambda r: r["shares_to_trade"] * r["price"], axis=1
    ).sum() if sell_count > 0 else 0

    lines.append(f"Estimated buy value: ${buy_value:,.2f}")
    lines.append(f"Estimated sell value: ${sell_value:,.2f}")
    lines.append(f"Net cash flow: ${sell_value - buy_value:,.2f}")

    lines.append("")
    lines.append("Execute these trades manually in IBKR, then run:")
    lines.append("  python main.py pull")
    lines.append("  python main.py snapshot")
    lines.append("")

    return "\n".join(lines)

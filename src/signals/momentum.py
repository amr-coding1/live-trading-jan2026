"""Momentum signal generator for sector rotation strategy.

Computes 12-1 momentum (12-month return excluding most recent month)
for sector ETFs and ranks them to generate target portfolio weights.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Minimum momentum threshold - don't buy if all sectors are negative
MIN_MOMENTUM_THRESHOLD = -0.20  # -20%

# UK-listed UCITS sector ETFs on London Stock Exchange
SECTOR_ETFS = [
    "SXLK.L",  # Technology
    "SXLF.L",  # Financials
    "SXLE.L",  # Energy
    "SXLV.L",  # Health Care
    "SXLY.L",  # Consumer Discretionary
    "SXLP.L",  # Consumer Staples
    "SXLI.L",  # Industrials
    "SXLB.L",  # Materials
    "SXLU.L",  # Utilities
]

# Mapping of tickers to sector names for display
SECTOR_NAMES = {
    "SXLK.L": "Technology",
    "SXLF.L": "Financials",
    "SXLE.L": "Energy",
    "SXLV.L": "Health Care",
    "SXLY.L": "Cons Discr",
    "SXLP.L": "Cons Staples",
    "SXLI.L": "Industrials",
    "SXLB.L": "Materials",
    "SXLU.L": "Utilities",
}


def display_symbol(symbol: str) -> str:
    """Format symbol for clean display, stripping exchange suffix.

    Args:
        symbol: Full ticker symbol (e.g., "SXLK.L").

    Returns:
        Clean display name (e.g., "SXLK").
    """
    return symbol.replace(".L", "")


def download_prices(
    symbols: list[str],
    months: int = 13,
    end_date: Optional[datetime] = None,
) -> pd.DataFrame:
    """Download historical prices for symbols.

    Args:
        symbols: List of ticker symbols.
        months: Number of months of history to download.
        end_date: End date for data. Defaults to today (UTC).

    Returns:
        DataFrame with adjusted close prices indexed by date.

    Raises:
        ValueError: If no data could be downloaded for any symbol.
    """
    if end_date is None:
        end_date = datetime.now(timezone.utc)

    start_date = end_date - timedelta(days=months * 31 + 10)

    logger.info(f"Downloading prices for {len(symbols)} symbols")

    try:
        data = yf.download(
            symbols,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )

        if data.empty:
            raise ValueError("No price data downloaded from yfinance")

        if isinstance(data.columns, pd.MultiIndex):
            prices = data["Close"]
        else:
            prices = data[["Close"]]
            prices.columns = symbols

        prices = prices.dropna(how="all")

        # Validate all symbols have data
        missing_symbols = [s for s in symbols if s not in prices.columns or prices[s].isna().all()]
        if missing_symbols:
            logger.warning(f"Missing data for symbols: {missing_symbols}")

        if prices.empty:
            raise ValueError("No valid price data after cleaning")

        logger.info(f"Downloaded {len(prices)} days of price data for {len(prices.columns)} symbols")
        return prices

    except Exception as e:
        logger.error(f"Failed to download prices: {e}")
        raise


def compute_monthly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute monthly returns from daily prices.

    Args:
        prices: DataFrame of daily adjusted close prices.

    Returns:
        DataFrame of monthly returns indexed by month-end date.
    """
    monthly_prices = prices.resample("ME").last()

    monthly_returns = monthly_prices.pct_change()

    return monthly_returns.dropna()


def compute_12_1_momentum(monthly_returns: pd.DataFrame) -> pd.Series:
    """Compute 12-1 momentum (12-month return excluding most recent month).

    Args:
        monthly_returns: DataFrame of monthly returns.

    Returns:
        Series of 12-1 momentum values by symbol.
    """
    if len(monthly_returns) < 13:
        raise ValueError(
            f"Need at least 13 months of data, got {len(monthly_returns)}"
        )

    returns_12_months = monthly_returns.iloc[-13:-1]

    cumulative_return = (1 + returns_12_months).prod() - 1

    return cumulative_return


def rank_by_momentum(momentum: pd.Series) -> pd.DataFrame:
    """Rank symbols by momentum.

    Args:
        momentum: Series of momentum values indexed by symbol.

    Returns:
        DataFrame with symbol, momentum, and rank columns.
    """
    ranked = pd.DataFrame({
        "symbol": momentum.index,
        "momentum_12_1": momentum.values,
    })

    ranked = ranked.sort_values("momentum_12_1", ascending=False)
    ranked["rank"] = range(1, len(ranked) + 1)
    ranked = ranked.reset_index(drop=True)

    return ranked


def generate_target_weights(
    ranked: pd.DataFrame,
    top_n: int = 3,
    min_momentum: float = MIN_MOMENTUM_THRESHOLD,
) -> pd.DataFrame:
    """Generate target portfolio weights for top N sectors.

    Args:
        ranked: DataFrame with ranked symbols.
        top_n: Number of top sectors to include.
        min_momentum: Minimum momentum to allocate (avoids buying losers in crash).

    Returns:
        DataFrame with symbol and target_weight columns.
    """
    ranked = ranked.copy()

    # Only allocate to sectors above minimum momentum threshold
    eligible = ranked[
        (ranked["rank"] <= top_n) &
        (ranked["momentum_12_1"] >= min_momentum)
    ]

    if len(eligible) == 0:
        logger.warning(f"No sectors meet minimum momentum threshold of {min_momentum:.1%}")
        ranked["target_weight"] = 0.0
        return ranked

    # Equal weight among eligible sectors
    weight = 1.0 / len(eligible)
    ranked["target_weight"] = 0.0
    ranked.loc[eligible.index, "target_weight"] = weight

    if len(eligible) < top_n:
        logger.info(f"Only {len(eligible)} sectors meet momentum threshold, holding {(1 - len(eligible) * weight):.1%} cash")

    return ranked


def generate_momentum_signal(
    symbols: Optional[list[str]] = None,
    top_n: int = 3,
    end_date: Optional[datetime] = None,
) -> dict:
    """Generate complete momentum signal.

    Args:
        symbols: List of symbols to analyze. Defaults to sector ETFs.
        top_n: Number of top sectors to select.
        end_date: End date for analysis. Defaults to today.

    Returns:
        Dictionary containing:
            - signal_date: Date of signal
            - ranked: DataFrame of ranked symbols with weights
            - top_sectors: List of selected sectors
            - target_weights: Dict mapping symbol to weight
    """
    if symbols is None:
        symbols = SECTOR_ETFS

    if end_date is None:
        end_date = datetime.now(timezone.utc)

    prices = download_prices(symbols, months=13, end_date=end_date)

    monthly_returns = compute_monthly_returns(prices)

    momentum = compute_12_1_momentum(monthly_returns)

    ranked = rank_by_momentum(momentum)

    ranked = generate_target_weights(ranked, top_n=top_n)

    top_sectors = ranked[ranked["target_weight"] > 0]["symbol"].tolist()
    target_weights = dict(zip(ranked["symbol"], ranked["target_weight"]))

    return {
        "signal_date": end_date.strftime("%Y-%m-%d"),
        "ranked": ranked,
        "top_sectors": top_sectors,
        "target_weights": target_weights,
        "top_n": top_n,
    }


def format_signal_report(signal: dict, cash: float = 0.0) -> str:
    """Format momentum signal as readable text report.

    Args:
        signal: Output from generate_momentum_signal().
        cash: Current cash balance for display.

    Returns:
        Formatted text report.
    """
    lines = [
        f"MOMENTUM SIGNAL - {signal['signal_date']}",
        "=" * 60,
        "",
        f"{'Rank':<6}{'Symbol':<8}{'Sector':<14}{'12-1 Mom':<12}{'Target'}",
        "-" * 60,
    ]

    for _, row in signal["ranked"].iterrows():
        symbol = row["symbol"]
        display_sym = display_symbol(symbol)
        sector = SECTOR_NAMES.get(symbol, "")
        mom_str = f"{row['momentum_12_1']*100:+.1f}%"
        weight_str = f"{row['target_weight']*100:.1f}%"
        lines.append(
            f"{row['rank']:<6}{display_sym:<8}{sector:<14}{mom_str:<12}{weight_str}"
        )

    lines.append("")
    lines.append("-" * 60)

    top_display = [display_symbol(s) for s in signal["top_sectors"]]
    lines.append(f"Top {signal['top_n']} sectors: {', '.join(top_display)}")

    if cash > 0:
        lines.append(f"Current cash: £{cash:,.2f}")

    lines.append("")

    return "\n".join(lines)

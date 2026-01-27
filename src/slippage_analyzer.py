"""Slippage analysis for trade executions.

Analyzes execution slippage across symbols, time of day,
and flags outliers for review.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def load_executions(
    executions_dir: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Load executions from CSV files within date range.

    Args:
        executions_dir: Directory containing execution CSV files.
        start_date: Start date string (YYYY-MM-DD), inclusive.
        end_date: End date string (YYYY-MM-DD), inclusive.

    Returns:
        Combined DataFrame of all executions in range.
    """
    exec_path = Path(executions_dir)
    if not exec_path.exists():
        logger.warning(f"Executions directory not found: {executions_dir}")
        return pd.DataFrame()

    all_files = sorted(exec_path.glob("*.csv"))
    if not all_files:
        logger.warning("No execution files found")
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

    combined = pd.concat(dfs, ignore_index=True)
    combined["timestamp"] = pd.to_datetime(combined["timestamp"])

    return combined


def compute_slippage_summary(df: pd.DataFrame) -> dict:
    """Compute summary statistics for slippage.

    Args:
        df: DataFrame with slippage_bps column.

    Returns:
        Dictionary of summary statistics.
    """
    slippage = df["slippage_bps"].dropna()

    if slippage.empty:
        return {
            "count": 0,
            "count_with_slippage": 0,
            "mean_bps": None,
            "median_bps": None,
            "std_bps": None,
            "min_bps": None,
            "max_bps": None,
            "pct_favorable": None,
            "pct_unfavorable": None,
        }

    return {
        "count": len(df),
        "count_with_slippage": len(slippage),
        "mean_bps": round(slippage.mean(), 2),
        "median_bps": round(slippage.median(), 2),
        "std_bps": round(slippage.std(), 2),
        "min_bps": round(slippage.min(), 2),
        "max_bps": round(slippage.max(), 2),
        "pct_favorable": round((slippage < 0).mean() * 100, 1),
        "pct_unfavorable": round((slippage > 0).mean() * 100, 1),
    }


def slippage_by_symbol(df: pd.DataFrame) -> pd.DataFrame:
    """Compute slippage statistics grouped by symbol.

    Args:
        df: DataFrame with symbol and slippage_bps columns.

    Returns:
        DataFrame with per-symbol slippage statistics.
    """
    slippage_df = df.dropna(subset=["slippage_bps"])

    if slippage_df.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "trade_count",
                "mean_bps",
                "median_bps",
                "std_bps",
                "total_slippage_bps",
            ]
        )

    grouped = slippage_df.groupby("symbol")["slippage_bps"].agg(
        trade_count="count",
        mean_bps="mean",
        median_bps="median",
        std_bps="std",
        total_slippage_bps="sum",
    )

    result = grouped.reset_index()
    for col in ["mean_bps", "median_bps", "std_bps", "total_slippage_bps"]:
        result[col] = result[col].round(2)

    return result.sort_values("total_slippage_bps", ascending=False)


def slippage_by_time_of_day(df: pd.DataFrame) -> pd.DataFrame:
    """Compute slippage statistics grouped by hour of day (UTC).

    Args:
        df: DataFrame with timestamp and slippage_bps columns.

    Returns:
        DataFrame with per-hour slippage statistics.
    """
    slippage_df = df.dropna(subset=["slippage_bps"]).copy()

    if slippage_df.empty:
        return pd.DataFrame(
            columns=["hour_utc", "trade_count", "mean_bps", "median_bps"]
        )

    slippage_df["hour_utc"] = slippage_df["timestamp"].dt.hour

    grouped = slippage_df.groupby("hour_utc")["slippage_bps"].agg(
        trade_count="count",
        mean_bps="mean",
        median_bps="median",
    )

    result = grouped.reset_index()
    result["mean_bps"] = result["mean_bps"].round(2)
    result["median_bps"] = result["median_bps"].round(2)

    return result.sort_values("hour_utc")


def slippage_by_asset_class(df: pd.DataFrame) -> pd.DataFrame:
    """Compute slippage statistics grouped by asset class.

    Args:
        df: DataFrame with asset_class and slippage_bps columns.

    Returns:
        DataFrame with per-asset-class slippage statistics.
    """
    slippage_df = df.dropna(subset=["slippage_bps"])

    if slippage_df.empty:
        return pd.DataFrame(
            columns=["asset_class", "trade_count", "mean_bps", "median_bps", "std_bps"]
        )

    grouped = slippage_df.groupby("asset_class")["slippage_bps"].agg(
        trade_count="count",
        mean_bps="mean",
        median_bps="median",
        std_bps="std",
    )

    result = grouped.reset_index()
    for col in ["mean_bps", "median_bps", "std_bps"]:
        result[col] = result[col].round(2)

    return result.sort_values("mean_bps", ascending=False)


def flag_outliers(df: pd.DataFrame, threshold_bps: float = 10.0) -> pd.DataFrame:
    """Flag trades with slippage exceeding threshold.

    Args:
        df: DataFrame with slippage_bps column.
        threshold_bps: Slippage threshold in basis points.

    Returns:
        DataFrame of outlier trades.
    """
    slippage_df = df.dropna(subset=["slippage_bps"])

    if slippage_df.empty:
        return pd.DataFrame()

    outliers = slippage_df[abs(slippage_df["slippage_bps"]) > threshold_bps].copy()
    outliers = outliers.sort_values("slippage_bps", ascending=False)

    return outliers[
        [
            "trade_id",
            "timestamp",
            "symbol",
            "side",
            "quantity",
            "intended_price",
            "fill_price",
            "slippage_bps",
        ]
    ]


def analyze_slippage(
    executions_dir: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    outlier_threshold_bps: float = 10.0,
) -> dict:
    """Run full slippage analysis.

    Args:
        executions_dir: Directory containing execution CSV files.
        start_date: Start date string (YYYY-MM-DD), inclusive.
        end_date: End date string (YYYY-MM-DD), inclusive.
        outlier_threshold_bps: Threshold for flagging outliers.

    Returns:
        Dictionary containing:
            - summary: Overall slippage statistics
            - by_symbol: DataFrame of per-symbol stats
            - by_time: DataFrame of per-hour stats
            - by_asset_class: DataFrame of per-asset-class stats
            - outliers: DataFrame of flagged trades
            - executions: Full executions DataFrame
    """
    df = load_executions(executions_dir, start_date, end_date)

    if df.empty:
        logger.warning("No executions found for analysis")
        return {
            "summary": compute_slippage_summary(pd.DataFrame(columns=["slippage_bps"])),
            "by_symbol": pd.DataFrame(),
            "by_time": pd.DataFrame(),
            "by_asset_class": pd.DataFrame(),
            "outliers": pd.DataFrame(),
            "executions": df,
        }

    return {
        "summary": compute_slippage_summary(df),
        "by_symbol": slippage_by_symbol(df),
        "by_time": slippage_by_time_of_day(df),
        "by_asset_class": slippage_by_asset_class(df),
        "outliers": flag_outliers(df, outlier_threshold_bps),
        "executions": df,
    }


def format_slippage_report(analysis: dict) -> str:
    """Format slippage analysis as readable text report.

    Args:
        analysis: Output from analyze_slippage().

    Returns:
        Formatted text report.
    """
    lines = ["=" * 50, "SLIPPAGE ANALYSIS REPORT", "=" * 50, ""]

    summary = analysis["summary"]
    lines.append("OVERALL SUMMARY")
    lines.append("-" * 30)
    lines.append(f"Total trades: {summary['count']}")
    lines.append(f"Trades with slippage data: {summary['count_with_slippage']}")

    if summary["mean_bps"] is not None:
        lines.append(f"Mean slippage: {summary['mean_bps']:.2f} bps")
        lines.append(f"Median slippage: {summary['median_bps']:.2f} bps")
        lines.append(f"Std deviation: {summary['std_bps']:.2f} bps")
        lines.append(f"Range: {summary['min_bps']:.2f} to {summary['max_bps']:.2f} bps")
        lines.append(f"Favorable executions: {summary['pct_favorable']:.1f}%")
        lines.append(f"Unfavorable executions: {summary['pct_unfavorable']:.1f}%")
    else:
        lines.append("No slippage data available")

    lines.append("")

    if not analysis["by_symbol"].empty:
        lines.append("SLIPPAGE BY SYMBOL (Top 10)")
        lines.append("-" * 30)
        for _, row in analysis["by_symbol"].head(10).iterrows():
            lines.append(
                f"  {row['symbol']}: {row['mean_bps']:.2f} bps mean "
                f"({row['trade_count']} trades)"
            )
        lines.append("")

    if not analysis["by_time"].empty:
        lines.append("SLIPPAGE BY HOUR (UTC)")
        lines.append("-" * 30)
        for _, row in analysis["by_time"].iterrows():
            lines.append(
                f"  {row['hour_utc']:02d}:00: {row['mean_bps']:.2f} bps mean "
                f"({row['trade_count']} trades)"
            )
        lines.append("")

    if not analysis["outliers"].empty:
        lines.append(f"OUTLIER TRADES (>{10} bps)")
        lines.append("-" * 30)
        for _, row in analysis["outliers"].head(10).iterrows():
            lines.append(
                f"  {row['symbol']} {row['side']}: {row['slippage_bps']:.2f} bps "
                f"(intended: {row['intended_price']}, fill: {row['fill_price']})"
            )
        lines.append("")

    lines.append("=" * 50)
    return "\n".join(lines)

"""Monthly PDF report generation.

Generates professional PDF reports with performance metrics,
equity curves, and trade analysis for recruitment purposes.
"""

import io
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from . import performance, slippage_analyzer

logger = logging.getLogger(__name__)


YEAR_MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_year_month(year_month: str) -> bool:
    """Validate year_month format.

    Args:
        year_month: String to validate.

    Returns:
        True if valid YYYY-MM format.
    """
    return bool(YEAR_MONTH_PATTERN.match(year_month))


def load_monthly_commentary(annotations_dir: str, year_month: str) -> str:
    """Load monthly commentary from markdown file.

    Args:
        annotations_dir: Path to annotations directory.
        year_month: Month in YYYY-MM format.

    Returns:
        Commentary text or empty string if not found or on error.
    """
    commentary_path = Path(annotations_dir) / "monthly" / f"{year_month}.md"

    if not commentary_path.exists():
        return ""

    try:
        with open(commentary_path, encoding="utf-8") as f:
            return f.read()
    except (IOError, OSError, UnicodeDecodeError) as e:
        logger.warning(f"Failed to load commentary: {e}")
        return ""


def get_month_date_range(year_month: str) -> tuple[str, str]:
    """Get start and end dates for a month.

    Args:
        year_month: Month in YYYY-MM format.

    Returns:
        Tuple of (start_date, end_date) in YYYY-MM-DD format.

    Raises:
        ValueError: If year_month is invalid format.
    """
    if not validate_year_month(year_month):
        raise ValueError(f"Invalid year_month format: {year_month}. Expected YYYY-MM.")

    year, month = map(int, year_month.split("-"))

    start_date = f"{year}-{month:02d}-01"

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    from datetime import date, timedelta
    end = date(next_year, next_month, 1) - timedelta(days=1)
    end_date = end.strftime("%Y-%m-%d")

    return start_date, end_date


def get_week_date_range(year_week: str) -> tuple[str, str]:
    """Get start and end dates for a week.

    Args:
        year_week: Week in YYYY-Www format (e.g., 2026-W05).

    Returns:
        Tuple of (start_date, end_date) in YYYY-MM-DD format.

    Raises:
        ValueError: If year_week is invalid format.
    """
    from datetime import date, timedelta

    week_pattern = re.compile(r"^(\d{4})-W(\d{2})$")
    match = week_pattern.match(year_week)

    if not match:
        raise ValueError(f"Invalid year_week format: {year_week}. Expected YYYY-Www (e.g., 2026-W05).")

    year, week = int(match.group(1)), int(match.group(2))

    if not (1 <= week <= 53):
        raise ValueError(f"Invalid week number: {week}. Must be 1-53.")

    # ISO week date: Monday is day 1
    jan_4 = date(year, 1, 4)  # Jan 4 is always in week 1
    start_of_week_1 = jan_4 - timedelta(days=jan_4.isoweekday() - 1)
    start_date = start_of_week_1 + timedelta(weeks=week - 1)
    end_date = start_date + timedelta(days=6)

    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def get_current_week() -> str:
    """Get current ISO week string.

    Returns:
        Current week in YYYY-Www format.
    """
    now = datetime.now(timezone.utc)
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


def create_equity_chart(
    equity: pd.Series,
    output_path: Path,
    title: str = "Equity Curve",
) -> Optional[Path]:
    """Create and save equity curve chart.

    Args:
        equity: Series of equity values indexed by date.
        output_path: Path to save PNG file.
        title: Chart title.

    Returns:
        Path to saved chart, or None on error.
    """
    if equity.empty:
        return None

    try:
        fig, ax = plt.subplots(figsize=(10, 5))

        ax.plot(equity.index, equity.values, linewidth=2, color="#2E86AB")
        ax.fill_between(equity.index, equity.values, alpha=0.3, color="#2E86AB")

        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.set_ylabel("Portfolio Value ($)", fontsize=10)
        ax.set_xlabel("Date", fontsize=10)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        plt.xticks(rotation=45, ha="right")

        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${x:,.0f}"))

        ax.grid(True, alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()

        return output_path
    except Exception as e:
        logger.warning(f"Failed to create equity chart: {e}")
        plt.close()
        return None


def create_drawdown_chart(
    drawdown: pd.Series,
    output_path: Path,
    title: str = "Drawdown",
) -> Optional[Path]:
    """Create and save drawdown chart.

    Args:
        drawdown: Series of drawdown values (negative decimals).
        output_path: Path to save PNG file.
        title: Chart title.

    Returns:
        Path to saved chart, or None on error.
    """
    if drawdown.empty:
        return None

    try:
        fig, ax = plt.subplots(figsize=(10, 3))

        ax.fill_between(
            drawdown.index,
            drawdown.values * 100,
            0,
            color="#E74C3C",
            alpha=0.7,
        )
        ax.plot(drawdown.index, drawdown.values * 100, color="#C0392B", linewidth=1)

        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.set_ylabel("Drawdown (%)", fontsize=10)
        ax.set_xlabel("Date", fontsize=10)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        plt.xticks(rotation=45, ha="right")

        ax.grid(True, alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()

        return output_path
    except Exception as e:
        logger.warning(f"Failed to create drawdown chart: {e}")
        plt.close()
        return None


def get_top_winners_losers(
    trades: pd.DataFrame,
    n: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Get top winning and losing trades.

    Args:
        trades: DataFrame of completed trades with net_pnl.
        n: Number of top trades to return.

    Returns:
        Tuple of (winners DataFrame, losers DataFrame).
    """
    if trades.empty:
        empty = pd.DataFrame(columns=["symbol", "net_pnl", "exit_timestamp"])
        return empty, empty

    sorted_trades = trades.sort_values("net_pnl", ascending=False)
    winners = sorted_trades.head(n)[["symbol", "quantity", "net_pnl", "exit_timestamp"]]
    losers = sorted_trades.tail(n)[["symbol", "quantity", "net_pnl", "exit_timestamp"]]

    return winners, losers.iloc[::-1]


def count_by_asset_class(executions: pd.DataFrame) -> pd.DataFrame:
    """Count executions by asset class.

    Args:
        executions: DataFrame of executions.

    Returns:
        DataFrame with asset class counts.
    """
    if executions.empty or "asset_class" not in executions.columns:
        return pd.DataFrame(columns=["asset_class", "count", "percentage"])

    counts = executions["asset_class"].value_counts()
    total = counts.sum()

    result = pd.DataFrame({
        "asset_class": counts.index,
        "count": counts.values,
        "percentage": (counts.values / total * 100).round(1),
    })

    return result


def generate_monthly_report(
    year_month: str,
    snapshots_dir: str,
    executions_dir: str,
    annotations_dir: str,
    output_dir: str,
) -> Path:
    """Generate monthly PDF report.

    Args:
        year_month: Month in YYYY-MM format.
        snapshots_dir: Path to snapshots directory.
        executions_dir: Path to executions directory.
        annotations_dir: Path to annotations directory.
        output_dir: Path to save PDF report.

    Returns:
        Path to generated PDF.
    """
    start_date, end_date = get_month_date_range(year_month)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    pdf_path = output_path / f"{year_month}-report.pdf"

    snapshots = performance.load_snapshots(snapshots_dir, start_date, end_date)
    equity = performance.compute_equity_curve(snapshots)
    returns = performance.compute_returns(equity)
    drawdown = performance.drawdown_series(equity)

    slippage_data = slippage_analyzer.analyze_slippage(
        executions_dir, start_date, end_date
    )
    executions = slippage_data["executions"]

    trades = performance.compute_trade_pnl(executions)
    winners, losers = get_top_winners_losers(trades)
    asset_counts = count_by_asset_class(executions)

    commentary = load_monthly_commentary(annotations_dir, year_month)

    equity_chart = None
    drawdown_chart = None
    if not equity.empty:
        equity_chart = create_equity_chart(
            equity, output_path / f"{year_month}-equity.png"
        )
        if not drawdown.empty:
            drawdown_chart = create_drawdown_chart(
                drawdown, output_path / f"{year_month}-drawdown.png"
            )

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        spaceAfter=20,
        alignment=1,
    )
    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading2"],
        fontSize=14,
        spaceBefore=15,
        spaceAfter=10,
    )
    body_style = styles["BodyText"]

    elements = []

    elements.append(Paragraph(f"Monthly Trading Report", title_style))
    elements.append(Paragraph(f"{year_month}", styles["Heading2"]))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("Performance Summary", heading_style))

    total_ret = performance.total_return(equity) * 100 if not equity.empty else 0
    vol = performance.annualized_volatility(returns) * 100 if not returns.empty else 0
    sharpe = performance.sharpe_ratio(returns) if not returns.empty else 0
    max_dd = performance.max_drawdown(equity) * 100 if not equity.empty else 0
    win_r = performance.win_rate(trades) * 100 if not trades.empty else 0

    summary_data = [
        ["Metric", "Value"],
        ["Total Return", f"{total_ret:.2f}%"],
        ["Annualized Volatility", f"{vol:.2f}%"],
        ["Sharpe Ratio", f"{sharpe:.2f}"],
        ["Max Drawdown", f"{max_dd:.2f}%"],
        ["Win Rate", f"{win_r:.1f}%"],
        ["Total Trades", str(len(trades))],
    ]

    summary_table = Table(summary_data, colWidths=[2.5 * inch, 2 * inch])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.18, 0.53, 0.67)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 11),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
        ("BACKGROUND", (0, 1), (-1, -1), colors.Color(0.95, 0.95, 0.95)),
        ("GRID", (0, 0), (-1, -1), 1, colors.white),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("TOPPADDING", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))

    if equity_chart and equity_chart.exists():
        elements.append(Paragraph("Equity Curve", heading_style))
        elements.append(Image(str(equity_chart), width=6.5 * inch, height=3.25 * inch))
        elements.append(Spacer(1, 10))

    if drawdown_chart and drawdown_chart.exists():
        elements.append(Paragraph("Drawdown", heading_style))
        elements.append(Image(str(drawdown_chart), width=6.5 * inch, height=2 * inch))
        elements.append(Spacer(1, 20))

    if not winners.empty:
        elements.append(Paragraph("Top 5 Winners", heading_style))
        winner_data = [["Symbol", "Quantity", "P&L"]]
        for _, row in winners.iterrows():
            winner_data.append([
                row["symbol"],
                f"{row['quantity']:.0f}",
                f"${row['net_pnl']:,.2f}",
            ])

        winner_table = Table(winner_data, colWidths=[2 * inch, 1.5 * inch, 2 * inch])
        winner_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.18, 0.53, 0.67)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),
            ("BACKGROUND", (0, 1), (-1, -1), colors.Color(0.9, 1, 0.9)),
        ]))
        elements.append(winner_table)
        elements.append(Spacer(1, 15))

    if not losers.empty:
        elements.append(Paragraph("Top 5 Losers", heading_style))
        loser_data = [["Symbol", "Quantity", "P&L"]]
        for _, row in losers.iterrows():
            loser_data.append([
                row["symbol"],
                f"{row['quantity']:.0f}",
                f"${row['net_pnl']:,.2f}",
            ])

        loser_table = Table(loser_data, colWidths=[2 * inch, 1.5 * inch, 2 * inch])
        loser_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.18, 0.53, 0.67)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),
            ("BACKGROUND", (0, 1), (-1, -1), colors.Color(1, 0.9, 0.9)),
        ]))
        elements.append(loser_table)
        elements.append(Spacer(1, 15))

    elements.append(PageBreak())

    elements.append(Paragraph("Slippage Analysis", heading_style))
    slippage_summary = slippage_data["summary"]

    if slippage_summary["mean_bps"] is not None:
        slip_data = [
            ["Metric", "Value"],
            ["Mean Slippage", f"{slippage_summary['mean_bps']:.2f} bps"],
            ["Median Slippage", f"{slippage_summary['median_bps']:.2f} bps"],
            ["Trades with Slippage Data", str(slippage_summary["count_with_slippage"])],
            ["Favorable Executions", f"{slippage_summary['pct_favorable']:.1f}%"],
        ]

        slip_table = Table(slip_data, colWidths=[2.5 * inch, 2 * inch])
        slip_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.18, 0.53, 0.67)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),
            ("BACKGROUND", (0, 1), (-1, -1), colors.Color(0.95, 0.95, 0.95)),
        ]))
        elements.append(slip_table)
    else:
        elements.append(Paragraph("No slippage data available for this period.", body_style))
    elements.append(Spacer(1, 20))

    if not asset_counts.empty:
        elements.append(Paragraph("Execution Count by Asset Class", heading_style))
        asset_data = [["Asset Class", "Count", "Percentage"]]
        for _, row in asset_counts.iterrows():
            asset_data.append([
                row["asset_class"],
                str(row["count"]),
                f"{row['percentage']:.1f}%",
            ])

        asset_table = Table(asset_data, colWidths=[2 * inch, 1.5 * inch, 1.5 * inch])
        asset_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.18, 0.53, 0.67)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),
            ("BACKGROUND", (0, 1), (-1, -1), colors.Color(0.95, 0.95, 0.95)),
        ]))
        elements.append(asset_table)
        elements.append(Spacer(1, 20))

    if commentary:
        elements.append(Paragraph("Commentary", heading_style))
        for para in commentary.split("\n\n"):
            if para.strip():
                # Escape HTML entities in commentary to prevent injection
                safe_text = (para.strip()
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
                )
                elements.append(Paragraph(safe_text, body_style))
                elements.append(Spacer(1, 8))

    elements.append(Spacer(1, 30))
    elements.append(Paragraph(
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        ParagraphStyle("Footer", parent=body_style, fontSize=8, textColor=colors.grey),
    ))

    try:
        doc.build(elements)
        logger.info(f"Generated report: {pdf_path}")
    finally:
        # Clean up temporary chart files
        if equity_chart and equity_chart.exists():
            try:
                equity_chart.unlink()
            except OSError:
                pass
        if drawdown_chart and drawdown_chart.exists():
            try:
                drawdown_chart.unlink()
            except OSError:
                pass

    return pdf_path


def generate_weekly_report(
    year_week: str,
    snapshots_dir: str,
    executions_dir: str,
    annotations_dir: str,
    output_dir: str,
) -> Path:
    """Generate weekly PDF report.

    Args:
        year_week: Week in YYYY-Www format (e.g., 2026-W05).
        snapshots_dir: Path to snapshots directory.
        executions_dir: Path to executions directory.
        annotations_dir: Path to annotations directory.
        output_dir: Path to save PDF report.

    Returns:
        Path to generated PDF.
    """
    start_date, end_date = get_week_date_range(year_week)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    pdf_path = output_path / f"{year_week}-report.pdf"

    snapshots = performance.load_snapshots(snapshots_dir, start_date, end_date)
    equity = performance.compute_equity_curve(snapshots)
    returns = performance.compute_returns(equity)
    drawdown = performance.drawdown_series(equity)

    slippage_data = slippage_analyzer.analyze_slippage(
        executions_dir, start_date, end_date
    )
    executions = slippage_data["executions"]

    trades = performance.compute_trade_pnl(executions)
    winners, losers = get_top_winners_losers(trades, n=3)  # Top 3 for weekly
    asset_counts = count_by_asset_class(executions)

    equity_chart = None
    drawdown_chart = None
    if not equity.empty:
        equity_chart = create_equity_chart(
            equity, output_path / f"{year_week}-equity.png",
            title=f"Equity Curve ({start_date} to {end_date})"
        )
        if not drawdown.empty:
            drawdown_chart = create_drawdown_chart(
                drawdown, output_path / f"{year_week}-drawdown.png"
            )

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        spaceAfter=20,
        alignment=1,
    )
    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading2"],
        fontSize=14,
        spaceBefore=15,
        spaceAfter=10,
    )
    body_style = styles["BodyText"]

    elements = []

    elements.append(Paragraph("Weekly Trading Report", title_style))
    elements.append(Paragraph(f"{year_week} ({start_date} to {end_date})", styles["Heading2"]))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("Performance Summary", heading_style))

    total_ret = performance.total_return(equity) * 100 if not equity.empty else 0
    vol = performance.annualized_volatility(returns) * 100 if not returns.empty else 0
    sharpe = performance.sharpe_ratio(returns) if not returns.empty else 0
    max_dd = performance.max_drawdown(equity) * 100 if not equity.empty else 0
    win_r = performance.win_rate(trades) * 100 if not trades.empty else 0

    summary_data = [
        ["Metric", "Value"],
        ["Weekly Return", f"{total_ret:.2f}%"],
        ["Annualized Volatility", f"{vol:.2f}%"],
        ["Sharpe Ratio", f"{sharpe:.2f}"],
        ["Max Drawdown", f"{max_dd:.2f}%"],
        ["Win Rate", f"{win_r:.1f}%"],
        ["Total Trades", str(len(trades))],
    ]

    summary_table = Table(summary_data, colWidths=[2.5 * inch, 2 * inch])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.18, 0.53, 0.67)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 11),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
        ("BACKGROUND", (0, 1), (-1, -1), colors.Color(0.95, 0.95, 0.95)),
        ("GRID", (0, 0), (-1, -1), 1, colors.white),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("TOPPADDING", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))

    if equity_chart and equity_chart.exists():
        elements.append(Paragraph("Equity Curve", heading_style))
        elements.append(Image(str(equity_chart), width=6.5 * inch, height=3.25 * inch))
        elements.append(Spacer(1, 10))

    if drawdown_chart and drawdown_chart.exists():
        elements.append(Paragraph("Drawdown", heading_style))
        elements.append(Image(str(drawdown_chart), width=6.5 * inch, height=2 * inch))
        elements.append(Spacer(1, 20))

    if not winners.empty:
        elements.append(Paragraph("Top Winners", heading_style))
        winner_data = [["Symbol", "Quantity", "P&L"]]
        for _, row in winners.iterrows():
            winner_data.append([
                row["symbol"],
                f"{row['quantity']:.0f}",
                f"${row['net_pnl']:,.2f}",
            ])

        winner_table = Table(winner_data, colWidths=[2 * inch, 1.5 * inch, 2 * inch])
        winner_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.18, 0.53, 0.67)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),
            ("BACKGROUND", (0, 1), (-1, -1), colors.Color(0.9, 1, 0.9)),
        ]))
        elements.append(winner_table)
        elements.append(Spacer(1, 15))

    if not losers.empty:
        elements.append(Paragraph("Top Losers", heading_style))
        loser_data = [["Symbol", "Quantity", "P&L"]]
        for _, row in losers.iterrows():
            loser_data.append([
                row["symbol"],
                f"{row['quantity']:.0f}",
                f"${row['net_pnl']:,.2f}",
            ])

        loser_table = Table(loser_data, colWidths=[2 * inch, 1.5 * inch, 2 * inch])
        loser_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.18, 0.53, 0.67)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),
            ("BACKGROUND", (0, 1), (-1, -1), colors.Color(1, 0.9, 0.9)),
        ]))
        elements.append(loser_table)
        elements.append(Spacer(1, 15))

    slippage_summary = slippage_data["summary"]
    if slippage_summary["mean_bps"] is not None:
        elements.append(Paragraph("Slippage Analysis", heading_style))
        slip_data = [
            ["Metric", "Value"],
            ["Mean Slippage", f"{slippage_summary['mean_bps']:.2f} bps"],
            ["Median Slippage", f"{slippage_summary['median_bps']:.2f} bps"],
            ["Trades with Slippage Data", str(slippage_summary["count_with_slippage"])],
        ]

        slip_table = Table(slip_data, colWidths=[2.5 * inch, 2 * inch])
        slip_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.18, 0.53, 0.67)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),
            ("BACKGROUND", (0, 1), (-1, -1), colors.Color(0.95, 0.95, 0.95)),
        ]))
        elements.append(slip_table)
        elements.append(Spacer(1, 20))

    elements.append(Spacer(1, 30))
    elements.append(Paragraph(
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        ParagraphStyle("Footer", parent=body_style, fontSize=8, textColor=colors.grey),
    ))

    try:
        doc.build(elements)
        logger.info(f"Generated weekly report: {pdf_path}")
    finally:
        if equity_chart and equity_chart.exists():
            try:
                equity_chart.unlink()
            except OSError:
                pass
        if drawdown_chart and drawdown_chart.exists():
            try:
                drawdown_chart.unlink()
            except OSError:
                pass

    return pdf_path

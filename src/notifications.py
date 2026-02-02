"""Email notification module for trading system."""

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Send email notifications for trading events."""

    def __init__(self, config: dict):
        """Initialize email notifier.

        Args:
            config: Application configuration with email settings.
        """
        email_config = config.get("email", {})
        self.enabled = email_config.get("enabled", False)
        self.smtp_host = email_config.get("smtp_host", "smtp.gmail.com")
        self.smtp_port = email_config.get("smtp_port", 587)
        self.sender_email = email_config.get("sender_email", "")
        self.sender_password = email_config.get("sender_password", "")
        self.recipient_email = email_config.get("recipient_email", "")

    def send_email(
        self,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        attachment_path: Optional[Path] = None,
    ) -> bool:
        """Send an email.

        Args:
            subject: Email subject line.
            body_text: Plain text body.
            body_html: Optional HTML body.
            attachment_path: Optional file to attach.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self.enabled:
            logger.info("Email notifications disabled")
            return False

        if not all([self.sender_email, self.sender_password, self.recipient_email]):
            logger.error("Email configuration incomplete")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.sender_email
            msg["To"] = self.recipient_email

            # Add text body
            msg.attach(MIMEText(body_text, "plain"))

            # Add HTML body if provided
            if body_html:
                msg.attach(MIMEText(body_html, "html"))

            # Add attachment if provided
            if attachment_path and attachment_path.exists():
                with open(attachment_path, "rb") as f:
                    attachment = MIMEApplication(f.read(), _subtype="pdf")
                    attachment.add_header(
                        "Content-Disposition",
                        "attachment",
                        filename=attachment_path.name,
                    )
                    msg.attach(attachment)

            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, self.recipient_email, msg.as_string())

            logger.info(f"Email sent: {subject}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def send_daily_summary(
        self,
        signal_data: dict,
        portfolio_data: dict,
        trades_executed: list,
    ) -> bool:
        """Send daily trading summary email.

        Args:
            signal_data: Today's signal information.
            portfolio_data: Current portfolio state.
            trades_executed: List of trades executed today.

        Returns:
            True if sent successfully.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Build summary
        total_equity = portfolio_data.get("total_equity", 0)
        daily_pnl = portfolio_data.get("daily_pnl", 0)
        daily_pnl_pct = portfolio_data.get("daily_pnl_pct", 0)

        top_sectors = signal_data.get("top_sectors", [])
        rankings = signal_data.get("rankings", [])

        # Determine if any trades
        trade_count = len(trades_executed)
        trade_summary = "No trades today" if trade_count == 0 else f"{trade_count} trade(s) executed"

        # Format rankings
        rankings_text = ""
        for i, r in enumerate(rankings[:5], 1):
            symbol = r.get("symbol", "")
            momentum = r.get("momentum_12_1", 0) * 100
            rankings_text += f"  {i}. {symbol}: {momentum:+.1f}%\n"

        # Format trades
        trades_text = ""
        if trades_executed:
            for t in trades_executed:
                action = t.get("action", "")
                symbol = t.get("symbol", "")
                shares = t.get("shares", 0)
                price = t.get("price", 0)
                trades_text += f"  {action} {shares} {symbol} @ ${price:.2f}\n"
        else:
            trades_text = "  None\n"

        # Build email body
        subject = f"Trading Summary - {today} | {trade_summary}"

        body_text = f"""
DAILY TRADING SUMMARY - {today}
{'=' * 50}

PORTFOLIO
  Total Equity: ${total_equity:,.2f}
  Daily P&L: ${daily_pnl:,.2f} ({daily_pnl_pct:+.2f}%)

TOP SECTORS (Momentum Signal)
  {', '.join(top_sectors) if top_sectors else 'N/A'}

SECTOR RANKINGS
{rankings_text}

TRADES EXECUTED
{trades_text}

---
View dashboard: http://localhost:5050/signals
"""

        body_html = f"""
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px;">
    Daily Trading Summary - {today}
</h2>

<div style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <h3 style="margin-top: 0; color: #495057;">Portfolio</h3>
    <p style="font-size: 24px; margin: 5px 0;">
        <strong>${total_equity:,.2f}</strong>
    </p>
    <p style="color: {'#28a745' if daily_pnl >= 0 else '#dc3545'}; margin: 5px 0;">
        Daily P&L: ${daily_pnl:,.2f} ({daily_pnl_pct:+.2f}%)
    </p>
</div>

<div style="margin: 15px 0;">
    <h3 style="color: #495057;">Top Sectors</h3>
    <p style="font-size: 18px;">
        <strong>{', '.join(top_sectors) if top_sectors else 'N/A'}</strong>
    </p>
</div>

<div style="margin: 15px 0;">
    <h3 style="color: #495057;">Trades Executed</h3>
    <p style="font-size: 16px; color: {'#28a745' if trade_count > 0 else '#6c757d'};">
        <strong>{trade_summary}</strong>
    </p>
    {''.join(f'<p>{t.get("action")} {t.get("shares")} {t.get("symbol")} @ ${t.get("price", 0):.2f}</p>' for t in trades_executed) if trades_executed else ''}
</div>

<hr style="border: none; border-top: 1px solid #dee2e6; margin: 20px 0;">
<p style="color: #6c757d; font-size: 12px;">
    Automated by Live Trading System
</p>
</body>
</html>
"""

        return self.send_email(subject, body_text, body_html)

    def send_weekly_report(
        self,
        week_start: str,
        week_end: str,
        stats: dict,
        trades: list,
        pdf_path: Optional[Path] = None,
    ) -> bool:
        """Send weekly performance report.

        Args:
            week_start: Week start date string.
            week_end: Week end date string.
            stats: Performance statistics for the week.
            trades: All trades executed during the week.
            pdf_path: Optional PDF report to attach.

        Returns:
            True if sent successfully.
        """
        weekly_return = stats.get("weekly_return_pct", 0)
        total_equity = stats.get("total_equity", 0)
        trade_count = len(trades)

        subject = f"Weekly Report - {week_start} to {week_end} | {weekly_return:+.2f}%"

        body_text = f"""
WEEKLY TRADING REPORT
{week_start} to {week_end}
{'=' * 50}

PERFORMANCE
  Weekly Return: {weekly_return:+.2f}%
  Total Equity: ${total_equity:,.2f}
  Trades: {trade_count}

STATISTICS
  Sharpe Ratio: {stats.get('sharpe_ratio', 'N/A')}
  Max Drawdown: {stats.get('max_drawdown_pct', 0):.2f}%
  Win Rate: {stats.get('win_rate', 0):.1f}%

---
Full report attached (if available).
View dashboard: http://localhost:5050/signals
"""

        return self.send_email(subject, body_text, attachment_path=pdf_path)

    def send_monthly_report(
        self,
        month: str,
        stats: dict,
        pdf_path: Optional[Path] = None,
    ) -> bool:
        """Send monthly performance report.

        Args:
            month: Month string (e.g., "2026-01").
            stats: Performance statistics for the month.
            pdf_path: Optional PDF report to attach.

        Returns:
            True if sent successfully.
        """
        monthly_return = stats.get("monthly_return_pct", 0)
        total_equity = stats.get("total_equity", 0)

        subject = f"Monthly Report - {month} | {monthly_return:+.2f}%"

        body_text = f"""
MONTHLY TRADING REPORT - {month}
{'=' * 50}

PERFORMANCE
  Monthly Return: {monthly_return:+.2f}%
  Total Equity: ${total_equity:,.2f}
  Total Trades: {stats.get('trade_count', 0)}

STATISTICS
  Sharpe Ratio (Annualized): {stats.get('sharpe_ratio', 'N/A')}
  Max Drawdown: {stats.get('max_drawdown_pct', 0):.2f}%
  Win Rate: {stats.get('win_rate', 0):.1f}%

POSITIONS
  Current Holdings: {', '.join(stats.get('current_positions', []))}

---
Full PDF report attached.
This report is suitable for track record documentation.
"""

        return self.send_email(subject, body_text, attachment_path=pdf_path)


def get_daily_summary_data(config: dict) -> tuple:
    """Gather data for daily summary email.

    Args:
        config: Application configuration.

    Returns:
        Tuple of (signal_data, portfolio_data, trades_executed).
    """
    from .execution.signal_logger import SignalLogger
    from .performance import load_snapshots, compute_equity_curve

    # Get today's signal
    signals_dir = config.get("signals", {}).get("log_dir", "data/signals")
    signal_logger = SignalLogger(signals_dir)
    signals = signal_logger.get_signals_history(limit=1)

    signal_data = signals[0] if signals else {
        "top_sectors": [],
        "rankings": [],
    }

    # Get portfolio data
    snapshots_dir = config.get("paths", {}).get("snapshots", "data/snapshots")
    snapshots = load_snapshots(snapshots_dir)

    if len(snapshots) >= 2:
        latest = snapshots.iloc[-1]
        previous = snapshots.iloc[-2]
        daily_pnl = latest["total_equity"] - previous["total_equity"]
        daily_pnl_pct = (daily_pnl / previous["total_equity"]) * 100 if previous["total_equity"] > 0 else 0
    else:
        latest = snapshots.iloc[-1] if len(snapshots) > 0 else None
        daily_pnl = 0
        daily_pnl_pct = 0

    portfolio_data = {
        "total_equity": latest["total_equity"] if latest is not None else 0,
        "daily_pnl": daily_pnl,
        "daily_pnl_pct": daily_pnl_pct,
    }

    # Get today's trades
    trades_executed = signal_data.get("trades", [])

    return signal_data, portfolio_data, trades_executed

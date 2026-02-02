"""Automated task scheduler for trading infrastructure.

Schedules daily snapshots and monthly signal generation
using the schedule library. Includes health checks, status tracking,
and failure notifications for production autonomous operation.
"""

import json
import logging
import os
import time
import threading
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Callable
from functools import wraps

import schedule

from .execution_logger import IBKRConnection, get_portfolio_snapshot, save_snapshot, load_config
from .signals.momentum import generate_momentum_signal, format_signal_report
from .signals.rebalance import generate_rebalance_trades, format_rebalance_report
from .export import generate_weekly_report, get_current_week
from .execution.engine import ExecutionEngine, format_execution_report
from .execution.risk_manager import KillSwitchActive
from .notifications import EmailNotifier, get_daily_summary_data

logger = logging.getLogger(__name__)

# Default retry settings
MAX_RETRIES = 3
RETRY_BASE_DELAY = 60  # seconds


class SchedulerStatus:
    """Tracks scheduler status for monitoring."""

    def __init__(self, status_file: Path):
        self.status_file = status_file
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._status = {
            "scheduler_started": None,
            "last_heartbeat": None,
            "jobs": {},
        }
        self._load()

    def _load(self) -> None:
        """Load status from file if exists."""
        if self.status_file.exists():
            try:
                with open(self.status_file) as f:
                    self._status = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

    def _save(self) -> None:
        """Save status to file atomically."""
        temp_file = self.status_file.with_suffix(".tmp")
        with open(temp_file, "w") as f:
            json.dump(self._status, f, indent=2)
        temp_file.replace(self.status_file)

    def set_started(self) -> None:
        """Mark scheduler as started."""
        with self._lock:
            self._status["scheduler_started"] = datetime.now(timezone.utc).isoformat()
            self._save()

    def heartbeat(self) -> None:
        """Update heartbeat timestamp."""
        with self._lock:
            self._status["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
            self._save()

    def job_started(self, job_name: str) -> None:
        """Mark a job as started."""
        with self._lock:
            if job_name not in self._status["jobs"]:
                self._status["jobs"][job_name] = {}
            self._status["jobs"][job_name]["last_start"] = datetime.now(timezone.utc).isoformat()
            self._status["jobs"][job_name]["status"] = "running"
            self._save()

    def job_completed(self, job_name: str, success: bool, message: str = "") -> None:
        """Mark a job as completed."""
        with self._lock:
            if job_name not in self._status["jobs"]:
                self._status["jobs"][job_name] = {}
            self._status["jobs"][job_name]["last_end"] = datetime.now(timezone.utc).isoformat()
            self._status["jobs"][job_name]["status"] = "success" if success else "failed"
            self._status["jobs"][job_name]["message"] = message
            if success:
                self._status["jobs"][job_name]["last_success"] = datetime.now(timezone.utc).isoformat()
            self._save()

    def get_status(self) -> dict:
        """Get current status."""
        with self._lock:
            return self._status.copy()


def with_retry(max_retries: int = MAX_RETRIES, base_delay: int = RETRY_BASE_DELAY):
    """Decorator to add retry logic with exponential backoff."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}): {e}. "
                            f"Retrying in {delay}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"{func.__name__} failed after {max_retries} attempts: {e}")
            raise last_error
        return wrapper
    return decorator


def send_notification(config: dict, subject: str, body: str) -> None:
    """Send notification on job failure.

    Supports webhook notifications via SCHEDULER_WEBHOOK_URL env var.
    Can be extended to support email, Slack, etc.

    Args:
        config: Configuration dictionary.
        subject: Notification subject.
        body: Notification body.
    """
    webhook_url = os.environ.get("SCHEDULER_WEBHOOK_URL")

    if webhook_url:
        try:
            import urllib.request
            data = json.dumps({
                "subject": subject,
                "body": body,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    logger.info(f"Notification sent: {subject}")
                else:
                    logger.warning(f"Notification failed with status {resp.status}")
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")
    else:
        # Log notification for systems without webhook configured
        logger.info(f"NOTIFICATION: {subject} - {body}")


class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP handler for health check endpoint."""

    scheduler_status: Optional[SchedulerStatus] = None

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health" or self.path == "/":
            self._handle_health()
        elif self.path == "/status":
            self._handle_status()
        else:
            self.send_error(404)

    def _handle_health(self):
        """Return simple health check."""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def _handle_status(self):
        """Return detailed status JSON."""
        if self.scheduler_status:
            status = self.scheduler_status.get_status()
            status["healthy"] = True
        else:
            status = {"healthy": False, "error": "Status not initialized"}

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(status, indent=2).encode("utf-8"))


def start_health_server(port: int, status: SchedulerStatus) -> HTTPServer:
    """Start health check HTTP server in background thread.

    Args:
        port: Port to listen on.
        status: SchedulerStatus instance for status endpoint.

    Returns:
        HTTPServer instance.
    """
    HealthCheckHandler.scheduler_status = status

    server = HTTPServer(("127.0.0.1", port), HealthCheckHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    logger.info(f"Health check server started on port {port}")
    return server


def setup_scheduler_logging(config: dict) -> None:
    """Configure logging for scheduler.

    Args:
        config: Configuration dictionary.
    """
    log_dir = Path(config["paths"]["logs"])
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "scheduler.log"

    handler = RotatingFileHandler(
        log_file,
        maxBytes=10485760,
        backupCount=5,
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )

    scheduler_logger = logging.getLogger("scheduler")
    scheduler_logger.setLevel(logging.INFO)
    scheduler_logger.addHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
    scheduler_logger.addHandler(console)


def job_daily_snapshot(config: dict, status: Optional[SchedulerStatus] = None) -> None:
    """Run daily portfolio snapshot job with retry logic.

    Args:
        config: Configuration dictionary.
        status: Optional SchedulerStatus for tracking.
    """
    sched_logger = logging.getLogger("scheduler")
    job_name = "daily_snapshot"

    if status:
        status.job_started(job_name)

    sched_logger.info("Starting daily snapshot job")

    @with_retry(max_retries=MAX_RETRIES, base_delay=RETRY_BASE_DELAY)
    def _run_snapshot():
        conn = IBKRConnection(config)

        if conn.connect(max_retries=2):
            try:
                snapshot = get_portfolio_snapshot(conn.ib)
                path = save_snapshot(snapshot, config["paths"]["snapshots"])
                sched_logger.info(f"Snapshot saved to {path}")
                return path
            finally:
                conn.disconnect()
        else:
            raise ConnectionError("Could not connect to IBKR")

    try:
        path = _run_snapshot()
        if status:
            status.job_completed(job_name, success=True, message=f"Saved to {path}")
        sched_logger.info(f"Daily snapshot job completed successfully")

    except Exception as e:
        error_msg = f"Snapshot job failed: {e}"
        sched_logger.error(error_msg)
        if status:
            status.job_completed(job_name, success=False, message=str(e))
        send_notification(config, "Scheduler Job Failed: daily_snapshot", error_msg)


def job_monthly_signal(config: dict, status: Optional[SchedulerStatus] = None) -> None:
    """Run monthly momentum signal job with retry logic.

    Args:
        config: Configuration dictionary.
        status: Optional SchedulerStatus for tracking.
    """
    sched_logger = logging.getLogger("scheduler")
    job_name = "monthly_signal"

    if status:
        status.job_started(job_name)

    sched_logger.info("Starting monthly signal job")

    @with_retry(max_retries=MAX_RETRIES, base_delay=RETRY_BASE_DELAY)
    def _run_signal():
        signal = generate_momentum_signal()
        report = format_signal_report(signal)

        sched_logger.info("Monthly momentum signal generated:")
        for line in report.split("\n"):
            sched_logger.info(line)

        signal_file = Path(config["paths"]["logs"]) / f"signal_{signal['signal_date']}.txt"
        with open(signal_file, "w") as f:
            f.write(report)

        return signal_file

    try:
        signal_file = _run_signal()
        if status:
            status.job_completed(job_name, success=True, message=f"Saved to {signal_file}")
        sched_logger.info(f"Monthly signal job completed successfully")

    except Exception as e:
        error_msg = f"Signal job failed: {e}"
        sched_logger.error(error_msg)
        if status:
            status.job_completed(job_name, success=False, message=str(e))
        send_notification(config, "Scheduler Job Failed: monthly_signal", error_msg)


def job_weekly_rebalance(config: dict, status: Optional[SchedulerStatus] = None) -> None:
    """Run weekly rebalance signal job with retry logic.

    Generates momentum signals and rebalance trade recommendations.

    Args:
        config: Configuration dictionary.
        status: Optional SchedulerStatus for tracking.
    """
    sched_logger = logging.getLogger("scheduler")
    job_name = "weekly_rebalance"

    if status:
        status.job_started(job_name)

    sched_logger.info("Starting weekly rebalance job")

    @with_retry(max_retries=MAX_RETRIES, base_delay=RETRY_BASE_DELAY)
    def _run_rebalance():
        # Generate rebalance trades
        rebalance_data = generate_rebalance_trades(config["paths"]["snapshots"])
        report = format_rebalance_report(rebalance_data)

        sched_logger.info("Weekly rebalance signal generated:")
        for line in report.split("\n"):
            sched_logger.info(line)

        # Save to file
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        signal_file = Path(config["paths"]["logs"]) / f"rebalance_{date_str}.txt"
        with open(signal_file, "w") as f:
            f.write(report)

        return signal_file, rebalance_data

    try:
        signal_file, rebalance_data = _run_rebalance()

        # Count trades for notification
        trades = rebalance_data.get("trades")
        trade_count = len(trades) if trades is not None and not trades.empty else 0

        if status:
            status.job_completed(job_name, success=True, message=f"{trade_count} trades recommended")
        sched_logger.info(f"Weekly rebalance job completed: {trade_count} trades recommended")

        # Send notification with trade summary if there are trades
        if trade_count > 0:
            report = format_rebalance_report(rebalance_data)
            send_notification(
                config,
                f"Weekly Rebalance: {trade_count} trades recommended",
                report[:1000]  # Truncate for notification
            )

    except Exception as e:
        error_msg = f"Rebalance job failed: {e}"
        sched_logger.error(error_msg)
        if status:
            status.job_completed(job_name, success=False, message=str(e))
        send_notification(config, "Scheduler Job Failed: weekly_rebalance", error_msg)


def job_weekly_report(config: dict, status: Optional[SchedulerStatus] = None) -> None:
    """Run weekly report generation job with retry logic.

    Args:
        config: Configuration dictionary.
        status: Optional SchedulerStatus for tracking.
    """
    sched_logger = logging.getLogger("scheduler")
    job_name = "weekly_report"

    if status:
        status.job_started(job_name)

    sched_logger.info("Starting weekly report job")

    @with_retry(max_retries=MAX_RETRIES, base_delay=RETRY_BASE_DELAY)
    def _run_report():
        # Get the previous week (report for last week's data)
        now = datetime.now(timezone.utc)
        # Calculate previous week
        prev_week_date = now - timedelta(days=7)
        year_week = f"{prev_week_date.year}-W{prev_week_date.isocalendar()[1]:02d}"

        pdf_path = generate_weekly_report(
            year_week=year_week,
            snapshots_dir=config["paths"]["snapshots"],
            executions_dir=config["paths"]["executions"],
            annotations_dir=config["paths"]["annotations"],
            output_dir=config["paths"]["reports"],
        )

        return pdf_path, year_week

    try:
        pdf_path, year_week = _run_report()
        if status:
            status.job_completed(job_name, success=True, message=f"Report: {year_week}")
        sched_logger.info(f"Weekly report generated: {pdf_path}")

        send_notification(
            config,
            f"Weekly Report Generated: {year_week}",
            f"Report saved to {pdf_path}"
        )

    except Exception as e:
        error_msg = f"Report job failed: {e}"
        sched_logger.error(error_msg)
        if status:
            status.job_completed(job_name, success=False, message=str(e))
        send_notification(config, "Scheduler Job Failed: weekly_report", error_msg)


def job_execute_signals(config: dict, status: Optional[SchedulerStatus] = None) -> None:
    """Run daily signal execution job.

    Generates momentum signal, calculates trades, and executes them
    (or logs in dry-run mode based on config).

    Args:
        config: Configuration dictionary.
        status: Optional SchedulerStatus for tracking.
    """
    sched_logger = logging.getLogger("scheduler")
    job_name = "execute_signals"

    if status:
        status.job_started(job_name)

    sched_logger.info("Starting execute signals job")

    # Determine execution mode from config
    exec_config = config.get("execution", {})
    dry_run = exec_config.get("mode", "dry_run") == "dry_run"
    mode_str = "DRY RUN" if dry_run else "LIVE"

    sched_logger.info(f"Execution mode: {mode_str}")

    @with_retry(max_retries=MAX_RETRIES, base_delay=RETRY_BASE_DELAY)
    def _run_execution():
        engine = ExecutionEngine(config, dry_run=dry_run)
        report = engine.run()
        return report

    try:
        report = _run_execution()

        # Format report for logging
        report_text = format_execution_report(report)
        for line in report_text.split("\n"):
            sched_logger.info(line)

        # Save report to log file
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = Path(config["paths"]["logs"]) / f"execution_{date_str}.txt"
        with open(log_file, "w") as f:
            f.write(report_text)

        if report.success:
            trade_count = len(report.trades)
            if status:
                status.job_completed(
                    job_name,
                    success=True,
                    message=f"{mode_str}: {trade_count} trades"
                )
            sched_logger.info(f"Execute signals job completed: {trade_count} trades [{mode_str}]")

            # Notify if trades were executed
            if trade_count > 0:
                send_notification(
                    config,
                    f"Execution Complete [{mode_str}]: {trade_count} trades",
                    report_text[:1000]
                )
        else:
            if status:
                status.job_completed(
                    job_name,
                    success=False,
                    message=report.error_message
                )
            sched_logger.warning(f"Execute signals job completed with issues: {report.error_message}")

    except KillSwitchActive as e:
        error_msg = f"Execution blocked by kill switch: {e}"
        sched_logger.warning(error_msg)
        if status:
            status.job_completed(job_name, success=False, message=str(e))
        send_notification(config, "Execution Blocked: Kill Switch Active", error_msg)

    except Exception as e:
        error_msg = f"Execute signals job failed: {e}"
        sched_logger.error(error_msg)
        if status:
            status.job_completed(job_name, success=False, message=str(e))
        send_notification(config, "Scheduler Job Failed: execute_signals", error_msg)


def job_daily_email(config: dict, status: Optional[SchedulerStatus] = None) -> None:
    """Send daily summary email.

    Args:
        config: Configuration dictionary.
        status: Optional SchedulerStatus for tracking.
    """
    sched_logger = logging.getLogger("scheduler")
    job_name = "daily_email"

    if status:
        status.job_started(job_name)

    sched_logger.info("Starting daily email job")

    try:
        notifier = EmailNotifier(config)

        if not notifier.enabled:
            sched_logger.info("Email notifications disabled, skipping")
            if status:
                status.job_completed(job_name, success=True, message="Disabled")
            return

        # Get daily summary data
        signal_data, portfolio_data, trades_executed = get_daily_summary_data(config)

        # Send email
        success = notifier.send_daily_summary(signal_data, portfolio_data, trades_executed)

        if status:
            status.job_completed(job_name, success=success, message="Sent" if success else "Failed")
        sched_logger.info(f"Daily email {'sent' if success else 'failed'}")

    except Exception as e:
        error_msg = f"Daily email job failed: {e}"
        sched_logger.error(error_msg)
        if status:
            status.job_completed(job_name, success=False, message=str(e))


def job_weekly_email(config: dict, status: Optional[SchedulerStatus] = None) -> None:
    """Send weekly report email with PDF attachment.

    Args:
        config: Configuration dictionary.
        status: Optional SchedulerStatus for tracking.
    """
    sched_logger = logging.getLogger("scheduler")
    job_name = "weekly_email"

    if status:
        status.job_started(job_name)

    sched_logger.info("Starting weekly email job")

    try:
        notifier = EmailNotifier(config)

        if not notifier.enabled:
            sched_logger.info("Email notifications disabled, skipping")
            if status:
                status.job_completed(job_name, success=True, message="Disabled")
            return

        # Get week info
        now = datetime.now(timezone.utc)
        prev_week = now - timedelta(days=7)
        week_start = (prev_week - timedelta(days=prev_week.weekday())).strftime("%Y-%m-%d")
        week_end = (prev_week + timedelta(days=6 - prev_week.weekday())).strftime("%Y-%m-%d")

        # Find latest weekly report PDF
        reports_dir = Path(config["paths"]["reports"])
        pdf_files = sorted(reports_dir.glob("*.pdf"), reverse=True)
        pdf_path = pdf_files[0] if pdf_files else None

        # Get stats (basic for now)
        from .performance import load_snapshots, compute_equity_curve, total_return
        snapshots = load_snapshots(config["paths"]["snapshots"])
        if len(snapshots) >= 2:
            weekly_return = ((snapshots.iloc[-1]["total_equity"] / snapshots.iloc[-7]["total_equity"]) - 1) * 100 if len(snapshots) > 7 else 0
        else:
            weekly_return = 0

        stats = {
            "weekly_return_pct": weekly_return,
            "total_equity": snapshots.iloc[-1]["total_equity"] if len(snapshots) > 0 else 0,
            "sharpe_ratio": "N/A",
            "max_drawdown_pct": 0,
            "win_rate": 0,
        }

        # Get trades from signals
        from .execution.signal_logger import SignalLogger
        signals_dir = config.get("signals", {}).get("log_dir", "data/signals")
        signal_logger = SignalLogger(signals_dir)
        signals = signal_logger.get_signals_history(limit=7)
        trades = []
        for sig in signals:
            trades.extend(sig.get("trades", []))

        success = notifier.send_weekly_report(week_start, week_end, stats, trades, pdf_path)

        if status:
            status.job_completed(job_name, success=success, message="Sent" if success else "Failed")
        sched_logger.info(f"Weekly email {'sent' if success else 'failed'}")

    except Exception as e:
        error_msg = f"Weekly email job failed: {e}"
        sched_logger.error(error_msg)
        if status:
            status.job_completed(job_name, success=False, message=str(e))


def job_monthly_email(config: dict, status: Optional[SchedulerStatus] = None) -> None:
    """Send monthly report email with PDF attachment.

    Args:
        config: Configuration dictionary.
        status: Optional SchedulerStatus for tracking.
    """
    sched_logger = logging.getLogger("scheduler")
    job_name = "monthly_email"

    if status:
        status.job_started(job_name)

    sched_logger.info("Starting monthly email job")

    try:
        notifier = EmailNotifier(config)

        if not notifier.enabled:
            sched_logger.info("Email notifications disabled, skipping")
            if status:
                status.job_completed(job_name, success=True, message="Disabled")
            return

        # Get previous month
        now = datetime.now(timezone.utc)
        first_of_month = now.replace(day=1)
        last_month = first_of_month - timedelta(days=1)
        month_str = last_month.strftime("%Y-%m")

        # Try to generate monthly report
        try:
            from .export import generate_monthly_report
            pdf_path = generate_monthly_report(
                month=month_str,
                snapshots_dir=config["paths"]["snapshots"],
                executions_dir=config["paths"]["executions"],
                annotations_dir=config["paths"]["annotations"],
                output_dir=config["paths"]["reports"],
            )
        except Exception as e:
            sched_logger.warning(f"Could not generate monthly report: {e}")
            pdf_path = None

        # Get stats
        from .performance import load_snapshots
        snapshots = load_snapshots(config["paths"]["snapshots"])

        stats = {
            "monthly_return_pct": 0,  # Would need more calculation
            "total_equity": snapshots.iloc[-1]["total_equity"] if len(snapshots) > 0 else 0,
            "trade_count": 0,
            "sharpe_ratio": "N/A",
            "max_drawdown_pct": 0,
            "win_rate": 0,
            "current_positions": [],
        }

        success = notifier.send_monthly_report(month_str, stats, pdf_path)

        if status:
            status.job_completed(job_name, success=success, message="Sent" if success else "Failed")
        sched_logger.info(f"Monthly email {'sent' if success else 'failed'}")

    except Exception as e:
        error_msg = f"Monthly email job failed: {e}"
        sched_logger.error(error_msg)
        if status:
            status.job_completed(job_name, success=False, message=str(e))


def run_scheduler(config: dict, health_port: int = 8080) -> None:
    """Start the background scheduler with health monitoring.

    Schedules:
        - Daily snapshot at 16:35 UTC (after LSE close)
        - Monthly signal on 1st at 08:00 UTC

    Args:
        config: Configuration dictionary.
        health_port: Port for health check HTTP server.
    """
    setup_scheduler_logging(config)
    sched_logger = logging.getLogger("scheduler")

    # Initialize status tracking
    status_file = Path(config["paths"]["logs"]) / "scheduler_status.json"
    status = SchedulerStatus(status_file)
    status.set_started()

    # Start health check server
    health_server = None
    try:
        health_server = start_health_server(health_port, status)
    except OSError as e:
        sched_logger.warning(f"Could not start health server on port {health_port}: {e}")

    # Schedule jobs with status tracking
    # Get schedule times from config or use defaults
    sched_config = config.get("scheduler", {})
    snapshot_time = sched_config.get("snapshot_time", "16:35")
    execute_time = sched_config.get("execute_time", "16:40")
    rebalance_day = sched_config.get("rebalance_day", "sunday")
    rebalance_time = sched_config.get("rebalance_time", "20:00")
    report_time = sched_config.get("report_time", "21:00")

    # Get execution mode for display
    exec_mode = config.get("execution", {}).get("mode", "dry_run")

    # Daily snapshot (after market close)
    schedule.every().day.at(snapshot_time).do(job_daily_snapshot, config=config, status=status)
    sched_logger.info(f"Scheduled: Daily snapshot at {snapshot_time} UTC")

    # Daily execution (after snapshot)
    schedule.every().day.at(execute_time).do(job_execute_signals, config=config, status=status)
    sched_logger.info(f"Scheduled: Daily execution at {execute_time} UTC (mode: {exec_mode})")

    # Weekly rebalance signal (Sunday evening to prepare for Monday)
    getattr(schedule.every(), rebalance_day).at(rebalance_time).do(
        job_weekly_rebalance, config=config, status=status
    )
    sched_logger.info(f"Scheduled: Weekly rebalance on {rebalance_day} at {rebalance_time} UTC")

    # Weekly report (Sunday evening after rebalance)
    getattr(schedule.every(), rebalance_day).at(report_time).do(
        job_weekly_report, config=config, status=status
    )
    sched_logger.info(f"Scheduled: Weekly report on {rebalance_day} at {report_time} UTC")

    # Email notification jobs
    email_config = config.get("email", {})
    if email_config.get("enabled", False):
        daily_email_time = email_config.get("daily_summary_time", "17:00")
        weekly_email_day = email_config.get("weekly_report_day", "sunday")
        weekly_email_time = email_config.get("weekly_report_time", "21:30")
        monthly_email_day = email_config.get("monthly_report_day", 1)
        monthly_email_time = email_config.get("monthly_report_time", "09:00")

        # Daily email summary (after execution completes)
        schedule.every().day.at(daily_email_time).do(job_daily_email, config=config, status=status)
        sched_logger.info(f"Scheduled: Daily email at {daily_email_time} UTC")

        # Weekly email with report (after weekly report generated)
        getattr(schedule.every(), weekly_email_day).at(weekly_email_time).do(
            job_weekly_email, config=config, status=status
        )
        sched_logger.info(f"Scheduled: Weekly email on {weekly_email_day} at {weekly_email_time} UTC")

        # Monthly email (1st of month)
        # Note: schedule doesn't support day-of-month directly, so we check in job
        schedule.every().day.at(monthly_email_time).do(
            lambda: job_monthly_email(config, status) if datetime.now(timezone.utc).day == monthly_email_day else None
        )
        sched_logger.info(f"Scheduled: Monthly email on day {monthly_email_day} at {monthly_email_time} UTC")
    else:
        sched_logger.info("Email notifications disabled")

    sched_logger.info("Scheduler started. Press Ctrl+C to stop.")
    print("Scheduler started. Press Ctrl+C to stop.")
    print("Scheduled jobs:")
    print(f"  - Daily snapshot at {snapshot_time} UTC")
    print(f"  - Daily execution at {execute_time} UTC (mode: {exec_mode})")
    print(f"  - Weekly rebalance on {rebalance_day} at {rebalance_time} UTC")
    print(f"  - Weekly report on {rebalance_day} at {report_time} UTC")

    if email_config.get("enabled", False):
        print(f"  - Daily email at {email_config.get('daily_summary_time', '17:00')} UTC")
        print(f"  - Weekly email on {email_config.get('weekly_report_day', 'sunday')} at {email_config.get('weekly_report_time', '21:30')} UTC")
        print(f"  - Monthly email on day {email_config.get('monthly_report_day', 1)} at {email_config.get('monthly_report_time', '09:00')} UTC")
        print(f"\nEmail: {email_config.get('recipient_email', 'not configured')}")

    print(f"\nHealth check: http://127.0.0.1:{health_port}/health")
    print(f"Status JSON: http://127.0.0.1:{health_port}/status")

    heartbeat_interval = 60  # seconds
    last_heartbeat = time.time()

    try:
        while True:
            schedule.run_pending()

            # Update heartbeat periodically
            if time.time() - last_heartbeat >= heartbeat_interval:
                status.heartbeat()
                last_heartbeat = time.time()

            time.sleep(10)  # Check more frequently for responsiveness
    except KeyboardInterrupt:
        sched_logger.info("Scheduler stopped by user")
        print("\nScheduler stopped.")
    finally:
        if health_server:
            health_server.shutdown()


def check_monthly_signal(config: dict, status: Optional[SchedulerStatus] = None) -> None:
    """Check if today is 1st of month and run signal job.

    Args:
        config: Configuration dictionary.
        status: Optional SchedulerStatus for tracking.
    """
    if datetime.now(timezone.utc).day == 1:
        job_monthly_signal(config, status=status)


def run_job_now(config: dict, job_name: str) -> None:
    """Run a specific job immediately.

    Args:
        config: Configuration dictionary.
        job_name: Name of job to run ("snapshot", "signal", "rebalance", "report", "execute").
    """
    setup_scheduler_logging(config)

    # Create status tracker for manual runs
    status_file = Path(config["paths"]["logs"]) / "scheduler_status.json"
    status = SchedulerStatus(status_file)

    if job_name == "snapshot":
        job_daily_snapshot(config, status=status)
    elif job_name == "signal":
        job_monthly_signal(config, status=status)
    elif job_name == "rebalance":
        job_weekly_rebalance(config, status=status)
    elif job_name == "report":
        job_weekly_report(config, status=status)
    elif job_name == "execute":
        job_execute_signals(config, status=status)
    else:
        print(f"Unknown job: {job_name}")
        print("Available jobs: snapshot, signal, rebalance, report, execute")


def check_tws_connection(config: dict) -> bool:
    """Check if TWS is available for connection.

    Args:
        config: Configuration dictionary.

    Returns:
        True if TWS is accessible, False otherwise.
    """
    try:
        conn = IBKRConnection(config)
        if conn.connect(max_retries=1):
            conn.disconnect()
            return True
        return False
    except Exception:
        return False

"""Automated task scheduler for trading infrastructure.

Schedules daily snapshots and monthly signal generation
using the schedule library.
"""

import logging
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import schedule

from .execution_logger import IBKRConnection, get_portfolio_snapshot, save_snapshot
from .signals.momentum import generate_momentum_signal, format_signal_report

logger = logging.getLogger(__name__)


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


def job_daily_snapshot(config: dict) -> None:
    """Run daily portfolio snapshot job.

    Args:
        config: Configuration dictionary.
    """
    sched_logger = logging.getLogger("scheduler")
    sched_logger.info("Starting daily snapshot job")

    try:
        conn = IBKRConnection(config)

        if conn.connect(max_retries=2):
            snapshot = get_portfolio_snapshot(conn.ib)
            path = save_snapshot(snapshot, config["paths"]["snapshots"])
            sched_logger.info(f"Snapshot saved to {path}")
            conn.disconnect()
        else:
            sched_logger.warning("Could not connect to IBKR - skipping snapshot")

    except Exception as e:
        sched_logger.error(f"Snapshot job failed: {e}")


def job_monthly_signal(config: dict) -> None:
    """Run monthly momentum signal job.

    Args:
        config: Configuration dictionary.
    """
    sched_logger = logging.getLogger("scheduler")
    sched_logger.info("Starting monthly signal job")

    try:
        signal = generate_momentum_signal()
        report = format_signal_report(signal)

        sched_logger.info("Monthly momentum signal generated:")
        for line in report.split("\n"):
            sched_logger.info(line)

        signal_file = Path(config["paths"]["logs"]) / f"signal_{signal['signal_date']}.txt"
        with open(signal_file, "w") as f:
            f.write(report)

        sched_logger.info(f"Signal saved to {signal_file}")

    except Exception as e:
        sched_logger.error(f"Signal job failed: {e}")


def run_scheduler(config: dict) -> None:
    """Start the background scheduler.

    Schedules:
        - Daily snapshot at 16:35 UTC (after LSE close)
        - Monthly signal on 1st at 08:00 UTC

    Args:
        config: Configuration dictionary.
    """
    setup_scheduler_logging(config)
    sched_logger = logging.getLogger("scheduler")

    schedule.every().day.at("16:35").do(job_daily_snapshot, config=config)
    sched_logger.info("Scheduled: Daily snapshot at 16:35 UTC")

    schedule.every().day.at("08:00").do(check_monthly_signal, config=config)
    sched_logger.info("Scheduled: Monthly signal check at 08:00 UTC")

    sched_logger.info("Scheduler started. Press Ctrl+C to stop.")
    print("Scheduler started. Press Ctrl+C to stop.")
    print("Scheduled jobs:")
    print("  - Daily snapshot at 16:35 UTC")
    print("  - Monthly signal on 1st at 08:00 UTC")

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        sched_logger.info("Scheduler stopped by user")
        print("\nScheduler stopped.")


def check_monthly_signal(config: dict) -> None:
    """Check if today is 1st of month and run signal job.

    Args:
        config: Configuration dictionary.
    """
    if datetime.now().day == 1:
        job_monthly_signal(config)


def run_job_now(config: dict, job_name: str) -> None:
    """Run a specific job immediately.

    Args:
        config: Configuration dictionary.
        job_name: Name of job to run ("snapshot" or "signal").
    """
    setup_scheduler_logging(config)

    if job_name == "snapshot":
        job_daily_snapshot(config)
    elif job_name == "signal":
        job_monthly_signal(config)
    else:
        print(f"Unknown job: {job_name}")

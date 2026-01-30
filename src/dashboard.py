"""Flask web dashboard for trading track record.

Displays portfolio positions, equity curve, P&L, and momentum signals
in a simple web interface on localhost:5000.
"""

import json
import logging
import os
import html
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from flask import Flask, render_template

from .performance import load_snapshots, compute_equity_curve, total_return
from .signals.momentum import (
    generate_momentum_signal,
    display_symbol,
    SECTOR_NAMES,
)

logger = logging.getLogger(__name__)


def create_app(config: dict) -> Flask:
    """Create and configure Flask application.

    Args:
        config: Application configuration dictionary.

    Returns:
        Configured Flask app instance.
    """
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent.parent / "templates"),
    )

    # Security configuration
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex())

    # Security headers middleware
    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "font-src 'self' https://cdn.jsdelivr.net;"
        )
        return response

    @app.route("/")
    def dashboard():
        """Main dashboard view."""
        data = get_dashboard_data(config)
        return render_template("dashboard.html", **data)

    return app


def load_latest_snapshot(snapshots_dir: str) -> Optional[dict]:
    """Load most recent portfolio snapshot.

    Args:
        snapshots_dir: Path to snapshots directory.

    Returns:
        Snapshot dictionary or None if not found.
    """
    snap_path = Path(snapshots_dir)

    if not snap_path.exists():
        return None

    json_files = sorted(snap_path.glob("*.json"), reverse=True)

    if not json_files:
        return None

    with open(json_files[0]) as f:
        return json.load(f)


def get_equity_chart_data(snapshots_dir: str) -> dict:
    """Get equity curve data for Chart.js.

    Args:
        snapshots_dir: Path to snapshots directory.

    Returns:
        Dictionary with dates and values lists.
    """
    snapshots = load_snapshots(snapshots_dir)

    if snapshots.empty:
        return {"dates": [], "values": []}

    equity = compute_equity_curve(snapshots)

    return {
        "dates": [d.strftime("%Y-%m-%d") for d in equity.index],
        "values": [round(v, 2) for v in equity.values],
    }


def get_signal_data() -> list[dict]:
    """Get momentum signal data for display.

    Returns:
        List of signal row dictionaries.
    """
    try:
        signal = generate_momentum_signal()
        rows = []

        for _, row in signal["ranked"].iterrows():
            symbol = row["symbol"]
            rows.append({
                "rank": row["rank"],
                "symbol": display_symbol(symbol),
                "sector": SECTOR_NAMES.get(symbol, ""),
                "momentum": row["momentum_12_1"],
                "target_weight": row["target_weight"],
            })

        return rows
    except Exception as e:
        logger.error(f"Failed to generate signal: {e}")
        return []


def calculate_days_to_rebalance() -> int:
    """Calculate days until 1st of next month.

    Returns:
        Number of days until rebalance date.
    """
    today = date.today()

    if today.month == 12:
        next_rebalance = date(today.year + 1, 1, 1)
    else:
        next_rebalance = date(today.year, today.month + 1, 1)

    return (next_rebalance - today).days


def get_dashboard_data(config: dict) -> dict:
    """Gather all data for dashboard display.

    Args:
        config: Application configuration dictionary.

    Returns:
        Dictionary of template variables.
    """
    snapshots_dir = config["paths"]["snapshots"]

    snapshot = load_latest_snapshot(snapshots_dir)

    if snapshot:
        total_equity = snapshot.get("total_equity", 0)
        cash = snapshot.get("cash", 0)
        positions = snapshot.get("positions", [])
        snapshot_timestamp = snapshot.get("timestamp", "Unknown")

        for pos in positions:
            if total_equity > 0:
                pos["weight"] = pos.get("market_value", 0) / total_equity
            else:
                pos["weight"] = 0
    else:
        total_equity = 0
        cash = 0
        positions = []
        snapshot_timestamp = "No snapshot available"

    snapshots_df = load_snapshots(snapshots_dir)
    if len(snapshots_df) >= 2:
        today_pnl = snapshots_df["total_equity"].iloc[-1] - snapshots_df["total_equity"].iloc[-2]
        starting_equity = snapshots_df["total_equity"].iloc[0]
        total_pnl = total_equity - starting_equity
        total_ret = (total_equity / starting_equity - 1) * 100 if starting_equity > 0 else 0
    else:
        today_pnl = 0
        total_pnl = 0
        total_ret = 0

    equity_data = get_equity_chart_data(snapshots_dir)

    signal_data = get_signal_data()

    days_to_rebalance = calculate_days_to_rebalance()

    # Sanitize string values to prevent XSS
    def sanitize_str(val):
        if isinstance(val, str):
            return html.escape(val)
        return val

    sanitized_snapshot_timestamp = sanitize_str(snapshot_timestamp)

    return {
        "total_equity": total_equity,
        "cash": cash,
        "today_pnl": today_pnl,
        "total_pnl": total_pnl,
        "total_return": total_ret,
        "positions": positions,
        "equity_data": json.dumps(equity_data),
        "signal_data": signal_data,
        "days_to_rebalance": days_to_rebalance,
        "snapshot_timestamp": sanitized_snapshot_timestamp,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def run_dashboard(config: dict, host: str = "127.0.0.1", port: int = 5000) -> None:
    """Run the Flask dashboard server.

    Args:
        config: Application configuration dictionary.
        host: Host to bind to.
        port: Port to listen on.
    """
    app = create_app(config)

    print(f"Starting dashboard at http://{host}:{port}")
    print("Press Ctrl+C to stop")

    app.run(host=host, port=port, debug=False)

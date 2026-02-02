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
from .execution.signal_logger import SignalLogger
from .execution.risk_manager import RiskManager

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

    @app.route("/signals")
    def signals():
        """Signals history view."""
        data = get_signals_data(config)
        return render_template("signals.html", **data)

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


def get_signals_data(config: dict) -> dict:
    """Gather data for signals history page.

    Args:
        config: Application configuration dictionary.

    Returns:
        Dictionary of template variables for signals page.
    """
    signals_dir = config.get("signals", {}).get("log_dir", "data/signals")
    signal_logger = SignalLogger(signals_dir)

    # Get recent signals
    signals = signal_logger.get_signals_history(limit=30)

    # Get kill switch status
    risk_manager = RiskManager(config)
    kill_switch_active = risk_manager.is_kill_switch_active()
    kill_switch_reason = risk_manager.get_kill_switch_reason()

    # Get execution mode
    exec_mode = config.get("execution", {}).get("mode", "dry_run")

    # Format signals for display
    formatted_signals = []
    for sig in signals:
        # Get trade summary
        trades = sig.get("trades", [])
        buy_count = sum(1 for t in trades if t.get("action") == "BUY")
        sell_count = sum(1 for t in trades if t.get("action") == "SELL")

        # Get execution results summary
        exec_results = sig.get("execution_results", [])
        executed_count = sum(1 for r in exec_results if r.get("status") in ("submitted", "filled", "dry_run"))

        formatted_signals.append({
            "date": sig.get("signal_date", sig.get("file_date", "Unknown")),
            "timestamp": sig.get("timestamp", ""),
            "mode": sig.get("execution_mode", "unknown"),
            "top_sectors": sig.get("top_sectors", []),
            "trade_count": len(trades),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "executed_count": executed_count,
            "validation_status": "Passed" if sig.get("validation", {}).get("valid", False) else "Failed",
            "trades": trades,
            "rankings": sig.get("rankings", []),
        })

    return {
        "signals": formatted_signals,
        "signal_count": len(formatted_signals),
        "kill_switch_active": kill_switch_active,
        "kill_switch_reason": kill_switch_reason,
        "execution_mode": exec_mode,
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

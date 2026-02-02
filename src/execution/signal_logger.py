"""Signal logging for audit trail and dashboard display.

Logs all signals, trade decisions, and execution results to JSON files
for compliance, debugging, and dashboard visualization.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class SignalLogger:
    """Logs signals and execution decisions for audit trail."""

    def __init__(self, signals_dir: str):
        """Initialize signal logger.

        Args:
            signals_dir: Directory to store signal log files.
        """
        self.signals_dir = Path(signals_dir)
        self.signals_dir.mkdir(parents=True, exist_ok=True)

    def log_signal(
        self,
        signal: dict,
        trades: list[dict],
        execution_mode: str,
        validation_result: Optional[dict] = None,
        execution_results: Optional[list[dict]] = None,
        reasoning: Optional[str] = None,
    ) -> Path:
        """Log a signal with trades and execution status.

        Args:
            signal: Momentum signal data from generate_momentum_signal().
            trades: List of trade dictionaries.
            execution_mode: "dry_run" or "live".
            validation_result: Risk validation results.
            execution_results: Order execution results (if live).
            reasoning: Human-readable reasoning for trade decisions.

        Returns:
            Path to saved signal log file.
        """
        timestamp = datetime.now(timezone.utc)
        date_str = timestamp.strftime("%Y-%m-%d")
        time_str = timestamp.strftime("%H-%M-%S")

        # Convert ranked DataFrame to list of dicts if present
        ranked_data = None
        if "ranked" in signal and isinstance(signal["ranked"], pd.DataFrame):
            ranked_data = signal["ranked"].to_dict(orient="records")
        elif "ranked" in signal:
            ranked_data = signal["ranked"]

        log_entry = {
            "timestamp": timestamp.isoformat(),
            "signal_date": signal.get("signal_date", date_str),
            "execution_mode": execution_mode,
            "rankings": ranked_data,
            "top_sectors": signal.get("top_sectors", []),
            "target_weights": signal.get("target_weights", {}),
            "trades": trades,
            "trade_count": len(trades),
            "validation": validation_result,
            "execution_results": execution_results,
            "reasoning": reasoning,
        }

        # Use date for filename, append time if multiple signals per day
        file_path = self.signals_dir / f"{date_str}.json"

        # If file exists, load and append (for multiple runs per day)
        if file_path.exists():
            try:
                with open(file_path) as f:
                    existing = json.load(f)
                if isinstance(existing, list):
                    existing.append(log_entry)
                    log_entry = existing
                else:
                    # Convert single entry to list
                    log_entry = [existing, log_entry]
            except (json.JSONDecodeError, IOError):
                # If corrupt, just overwrite
                log_entry = [log_entry]
        else:
            log_entry = [log_entry]

        # Atomic write
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            json.dump(log_entry, f, indent=2, default=str)
        temp_path.replace(file_path)

        logger.info(f"Signal logged to {file_path}")
        return file_path

    def get_signals_history(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 30,
    ) -> list[dict]:
        """Load historical signals for dashboard display.

        Args:
            start_date: Start date filter (YYYY-MM-DD).
            end_date: End date filter (YYYY-MM-DD).
            limit: Maximum number of signals to return.

        Returns:
            List of signal log entries, newest first.
        """
        signals = []

        # Get all signal files, sorted by date descending
        json_files = sorted(self.signals_dir.glob("*.json"), reverse=True)

        for json_file in json_files:
            if len(signals) >= limit:
                break

            # Filter by date if specified
            file_date = json_file.stem  # YYYY-MM-DD
            if start_date and file_date < start_date:
                continue
            if end_date and file_date > end_date:
                continue

            try:
                with open(json_file) as f:
                    data = json.load(f)

                # Handle both single entry and list formats
                if isinstance(data, list):
                    for entry in reversed(data):  # Most recent first within day
                        if len(signals) < limit:
                            entry["file_date"] = file_date
                            signals.append(entry)
                else:
                    data["file_date"] = file_date
                    signals.append(data)

            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load signal file {json_file}: {e}")
                continue

        return signals[:limit]

    def get_latest_signal(self) -> Optional[dict]:
        """Get the most recent signal.

        Returns:
            Latest signal entry or None if no signals exist.
        """
        signals = self.get_signals_history(limit=1)
        return signals[0] if signals else None

    def get_signal_by_date(self, date: str) -> Optional[list[dict]]:
        """Get all signals for a specific date.

        Args:
            date: Date string (YYYY-MM-DD).

        Returns:
            List of signals for that date, or None if not found.
        """
        file_path = self.signals_dir / f"{date}.json"

        if not file_path.exists():
            return None

        try:
            with open(file_path) as f:
                data = json.load(f)
            return data if isinstance(data, list) else [data]
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load signal file {file_path}: {e}")
            return None


def format_signal_reasoning(
    rankings: list[dict],
    current_holdings: list[str],
    buys: list[str],
    sells: list[str],
    exit_threshold: int,
) -> str:
    """Generate human-readable reasoning for signal decisions.

    Args:
        rankings: List of ranked sector dictionaries.
        current_holdings: List of currently held symbols.
        buys: List of symbols to buy.
        sells: List of symbols to sell.
        exit_threshold: Rank threshold for exits.

    Returns:
        Formatted reasoning string.
    """
    lines = ["Signal Decision Reasoning:", "=" * 40]

    # Show rankings
    lines.append("\nSector Rankings (12-1 Momentum):")
    for r in rankings:
        symbol = r.get("symbol", "")
        momentum = r.get("momentum_12_1", 0)
        rank = r.get("rank", 0)
        weight = r.get("target_weight", 0)
        status = ""
        if symbol in current_holdings:
            status = " [HOLDING]"
        if weight > 0:
            status += " [TARGET]"
        lines.append(f"  {rank}. {symbol}: {momentum*100:+.1f}%{status}")

    # Explain holdings
    if current_holdings:
        lines.append(f"\nCurrent Holdings: {', '.join(current_holdings)}")
    else:
        lines.append("\nCurrent Holdings: None")

    # Explain buys
    if buys:
        lines.append(f"\nBuying: {', '.join(buys)}")
        for buy in buys:
            rank_info = next((r for r in rankings if r.get("symbol") == buy), None)
            if rank_info:
                lines.append(f"  - {buy}: Rank {rank_info.get('rank')} (above threshold), momentum {rank_info.get('momentum_12_1', 0)*100:+.1f}%")
    else:
        lines.append("\nBuying: None")

    # Explain sells
    if sells:
        lines.append(f"\nSelling: {', '.join(sells)}")
        for sell in sells:
            rank_info = next((r for r in rankings if r.get("symbol") == sell), None)
            if rank_info:
                reason = f"Rank {rank_info.get('rank')} dropped below threshold ({exit_threshold})"
            else:
                reason = "No longer in target portfolio"
            lines.append(f"  - {sell}: {reason}")
    else:
        lines.append("\nSelling: None")

    lines.append("")
    return "\n".join(lines)

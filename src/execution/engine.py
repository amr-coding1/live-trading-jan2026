"""Execution engine orchestrating the signal-to-order pipeline.

Main entry point for automated execution that coordinates:
1. Signal generation (momentum calculation)
2. Portfolio analysis (current vs target)
3. Trade calculation (position sizing)
4. Risk validation (safeguards)
5. Order execution (dry-run or live)
6. Logging and audit trail
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from ..signals.momentum import generate_momentum_signal, SECTOR_ETFS
from ..signals.rebalance import (
    load_latest_snapshot,
    get_current_weights,
    get_current_prices,
)
from .order_manager import OrderManager, ExecutionResult
from .position_sizer import PositionSizer, SizedTrade
from .risk_manager import RiskManager, KillSwitchActive, BatchValidationResult
from .signal_logger import SignalLogger, format_signal_reasoning

logger = logging.getLogger(__name__)


@dataclass
class ExecutionReport:
    """Complete report of an execution run."""
    timestamp: str
    execution_mode: str  # "dry_run" or "live"
    signal_date: str
    rankings: list[dict]
    top_sectors: list[str]
    target_weights: dict[str, float]
    current_weights: dict[str, float]
    trades: list[dict]
    validation_result: Optional[dict]
    execution_results: list[dict]
    total_equity: float
    cash: float
    reasoning: str
    success: bool
    error_message: str = ""


class ExecutionEngine:
    """Orchestrates the signal-to-execution pipeline."""

    def __init__(self, config: dict, dry_run: bool = True):
        """Initialize execution engine.

        Args:
            config: Full configuration dictionary.
            dry_run: If True (default), log trades but don't submit orders.
        """
        self.config = config
        self.dry_run = dry_run

        # Initialize components
        self.risk_manager = RiskManager(config)
        self.signal_logger = SignalLogger(
            config.get("signals", {}).get("log_dir", "data/signals")
        )
        self.order_manager = OrderManager(config, dry_run=dry_run)

        # Get paths from config
        self.snapshots_dir = config["paths"]["snapshots"]

        # Position sizing config
        sizing_config = config.get("position_sizing", {})
        self.top_n = sizing_config.get("top_n", 3)
        self.exit_rank_threshold = sizing_config.get("exit_rank_threshold", 5)
        self.min_trade_threshold = sizing_config.get("min_trade_threshold", 0.02)

        mode_str = "DRY RUN" if dry_run else "LIVE"
        logger.info(f"ExecutionEngine initialized in {mode_str} mode")

    def run(self) -> ExecutionReport:
        """Run the full execution pipeline.

        Returns:
            ExecutionReport with all details.

        Raises:
            KillSwitchActive: If kill switch is active.
        """
        timestamp = datetime.now(timezone.utc)
        logger.info(f"Starting execution pipeline at {timestamp.isoformat()}")

        # Check kill switch first
        self.risk_manager.check_kill_switch()

        try:
            # Step 1: Generate momentum signal
            logger.info("Step 1: Generating momentum signal...")
            signal = generate_momentum_signal(top_n=self.top_n)
            rankings = signal["ranked"].to_dict(orient="records")
            target_weights = signal["target_weights"]

            logger.info(f"Top {self.top_n} sectors: {signal['top_sectors']}")

            # Step 2: Load current portfolio state
            logger.info("Step 2: Loading portfolio snapshot...")
            snapshot = load_latest_snapshot(self.snapshots_dir)

            if snapshot is None:
                raise ValueError(
                    "No portfolio snapshot found. Run 'python main.py snapshot' first."
                )

            # Stale snapshot protection: reject snapshots older than 48 hours
            snapshot_ts = snapshot.get("timestamp", "")
            if snapshot_ts:
                try:
                    snap_dt = datetime.fromisoformat(snapshot_ts.replace("Z", "+00:00"))
                    age_hours = (datetime.now(timezone.utc) - snap_dt).total_seconds() / 3600
                    if age_hours > 48:
                        raise ValueError(
                            f"Snapshot is {age_hours:.0f} hours old (from {snapshot_ts}). "
                            f"Maximum allowed age is 48 hours. "
                            f"Run 'python main.py snapshot' to refresh."
                        )
                    elif age_hours > 24:
                        logger.warning(
                            f"Snapshot is {age_hours:.0f} hours old — consider refreshing"
                        )
                except (ValueError, TypeError) as e:
                    if "Snapshot is" in str(e):
                        raise
                    logger.warning(f"Could not parse snapshot timestamp: {snapshot_ts}")

            total_equity = snapshot.get("total_equity", 0)
            cash = snapshot.get("cash", 0)
            current_weights = get_current_weights(snapshot)

            # Build current positions dict for position sizer
            current_positions = {}
            for pos in snapshot.get("positions", []):
                symbol = pos.get("symbol")
                if symbol:
                    # Add .L suffix if not present (for matching with signal)
                    if not symbol.endswith(".L"):
                        symbol = f"{symbol}.L"
                    current_positions[symbol] = pos

            logger.info(
                f"Portfolio: equity={total_equity:,.2f}, cash={cash:,.2f}, "
                f"positions={len(current_positions)}"
            )

            # Step 3: Get current prices
            logger.info("Step 3: Fetching current prices...")
            all_symbols = list(set(target_weights.keys()) | set(current_positions.keys()))
            current_prices = get_current_prices(all_symbols)

            # Step 4: Calculate trades
            logger.info("Step 4: Calculating trades...")
            position_sizer = PositionSizer(
                total_equity=total_equity,
                cash_available=cash,
                current_positions=current_positions,
                config=self.config,
            )

            sized_trades = position_sizer.generate_trades(
                target_weights=target_weights,
                current_prices=current_prices,
                min_threshold=self.min_trade_threshold,
            )

            # Convert to dict format
            trades = [
                {
                    "symbol": t.symbol,
                    "action": t.action,
                    "shares": t.shares,
                    "price": t.price,
                    "target_weight": t.target_weight,
                    "current_weight": t.current_weight,
                    "trade_value": t.trade_value,
                    "reason": t.reason,
                }
                for t in sized_trades
            ]

            # Step 5: Validate trades
            logger.info("Step 5: Validating trades...")
            current_position_values = {
                symbol: pos.get("market_value", 0)
                for symbol, pos in current_positions.items()
            }

            validation = self.risk_manager.validate_batch(
                trades=trades,
                total_equity=total_equity,
                current_positions=current_position_values,
            )

            validation_dict = {
                "valid": validation.valid,
                "total_turnover_pct": validation.total_turnover_pct,
                "rejected_count": validation.rejected_count,
                "reason": validation.reason,
            }

            if not validation.valid:
                logger.warning(f"Trade validation failed: {validation.reason}")
                # Still log the signal, but don't execute
                reasoning = self._generate_reasoning(
                    rankings, current_positions, trades, validation
                )

                self.signal_logger.log_signal(
                    signal=signal,
                    trades=trades,
                    execution_mode="dry_run" if self.dry_run else "live",
                    validation_result=validation_dict,
                    execution_results=None,
                    reasoning=reasoning,
                )

                return ExecutionReport(
                    timestamp=timestamp.isoformat(),
                    execution_mode="dry_run" if self.dry_run else "live",
                    signal_date=signal["signal_date"],
                    rankings=rankings,
                    top_sectors=signal["top_sectors"],
                    target_weights=target_weights,
                    current_weights=current_weights,
                    trades=trades,
                    validation_result=validation_dict,
                    execution_results=[],
                    total_equity=total_equity,
                    cash=cash,
                    reasoning=reasoning,
                    success=False,
                    error_message=f"Validation failed: {validation.reason}",
                )

            # Step 6: Execute trades
            logger.info(f"Step 6: Executing {len(trades)} trades...")

            if not trades:
                logger.info("No trades to execute")
                execution_results = []
            else:
                # Connect to IBKR if live mode
                if not self.dry_run:
                    if not self.order_manager.connect():
                        raise ConnectionError("Failed to connect to IBKR")

                try:
                    results = self.order_manager.submit_batch(trades)
                    execution_results = [
                        {
                            "order_id": r.order_id,
                            "symbol": r.symbol,
                            "action": r.action,
                            "shares": r.shares,
                            "order_type": r.order_type,
                            "status": r.status,
                            "fill_price": r.fill_price,
                            "fill_time": r.fill_time,
                            "message": r.message,
                            "dry_run": r.dry_run,
                        }
                        for r in results
                    ]
                finally:
                    if not self.dry_run:
                        self.order_manager.disconnect()

            # Step 7: Log signal
            logger.info("Step 7: Logging signal...")
            reasoning = self._generate_reasoning(
                rankings, current_positions, trades, validation
            )

            self.signal_logger.log_signal(
                signal=signal,
                trades=trades,
                execution_mode="dry_run" if self.dry_run else "live",
                validation_result=validation_dict,
                execution_results=execution_results,
                reasoning=reasoning,
            )

            mode_str = "DRY RUN" if self.dry_run else "LIVE"
            logger.info(f"Execution complete [{mode_str}]: {len(trades)} trades")

            return ExecutionReport(
                timestamp=timestamp.isoformat(),
                execution_mode="dry_run" if self.dry_run else "live",
                signal_date=signal["signal_date"],
                rankings=rankings,
                top_sectors=signal["top_sectors"],
                target_weights=target_weights,
                current_weights=current_weights,
                trades=trades,
                validation_result=validation_dict,
                execution_results=execution_results,
                total_equity=total_equity,
                cash=cash,
                reasoning=reasoning,
                success=True,
            )

        except KillSwitchActive:
            raise
        except Exception as e:
            logger.error(f"Execution pipeline failed: {e}")
            return ExecutionReport(
                timestamp=timestamp.isoformat(),
                execution_mode="dry_run" if self.dry_run else "live",
                signal_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                rankings=[],
                top_sectors=[],
                target_weights={},
                current_weights={},
                trades=[],
                validation_result=None,
                execution_results=[],
                total_equity=0,
                cash=0,
                reasoning="",
                success=False,
                error_message=str(e),
            )

    def _generate_reasoning(
        self,
        rankings: list[dict],
        current_positions: dict[str, dict],
        trades: list[dict],
        validation: BatchValidationResult,
    ) -> str:
        """Generate human-readable reasoning for trade decisions.

        Args:
            rankings: List of ranked sector dicts.
            current_positions: Current position dict.
            trades: List of trade dicts.
            validation: Validation result.

        Returns:
            Formatted reasoning string.
        """
        # Get current holdings (just the symbols)
        current_holdings = list(current_positions.keys())

        # Get buys and sells
        buys = [t["symbol"] for t in trades if t["action"] == "BUY"]
        sells = [t["symbol"] for t in trades if t["action"] == "SELL"]

        return format_signal_reasoning(
            rankings=rankings,
            current_holdings=current_holdings,
            buys=buys,
            sells=sells,
            exit_threshold=self.exit_rank_threshold,
        )


def run_execution_pipeline(
    config: dict,
    dry_run: bool = True,
) -> ExecutionReport:
    """Run the execution pipeline.

    Convenience function for running the pipeline without
    instantiating the engine directly.

    Args:
        config: Configuration dictionary.
        dry_run: If True (default), log trades but don't submit.

    Returns:
        ExecutionReport with results.
    """
    engine = ExecutionEngine(config, dry_run=dry_run)
    return engine.run()


def format_execution_report(report: ExecutionReport) -> str:
    """Format execution report as readable text.

    Args:
        report: ExecutionReport from pipeline run.

    Returns:
        Formatted text report.
    """
    lines = [
        f"EXECUTION REPORT - {report.signal_date}",
        "=" * 60,
        f"Mode: {report.execution_mode.upper()}",
        f"Timestamp: {report.timestamp}",
        f"Status: {'SUCCESS' if report.success else 'FAILED'}",
        "",
    ]

    if report.error_message:
        lines.append(f"ERROR: {report.error_message}")
        lines.append("")

    lines.extend([
        f"Total Equity: ${report.total_equity:,.2f}",
        f"Cash: ${report.cash:,.2f}",
        "",
        f"Top Sectors: {', '.join(report.top_sectors)}",
        "",
    ])

    # Rankings
    lines.append("Sector Rankings:")
    lines.append("-" * 40)
    for r in report.rankings:
        symbol = r.get("symbol", "")
        mom = r.get("momentum_12_1", 0)
        rank = r.get("rank", 0)
        weight = r.get("target_weight", 0)
        lines.append(f"  {rank}. {symbol}: {mom*100:+.1f}% (target: {weight*100:.0f}%)")

    # Trades
    lines.append("")
    lines.append(f"Trades ({len(report.trades)}):")
    lines.append("-" * 40)

    if not report.trades:
        lines.append("  No trades")
    else:
        for t in report.trades:
            lines.append(
                f"  {t['action']} {t['shares']} {t['symbol']} @ {t['price']:.2f} "
                f"(${t['trade_value']:,.0f})"
            )

    # Validation
    if report.validation_result:
        lines.extend([
            "",
            "Validation:",
            f"  Status: {'PASSED' if report.validation_result['valid'] else 'FAILED'}",
            f"  Turnover: {report.validation_result['total_turnover_pct']*100:.1f}%",
            f"  Message: {report.validation_result['reason']}",
        ])

    # Execution results
    if report.execution_results:
        lines.extend([
            "",
            "Execution Results:",
            "-" * 40,
        ])
        for r in report.execution_results:
            status = r.get("status", "")
            symbol = r.get("symbol", "")
            action = r.get("action", "")
            shares = r.get("shares", 0)
            lines.append(f"  [{status.upper()}] {action} {shares} {symbol}")

    lines.append("")
    return "\n".join(lines)

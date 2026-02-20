"""Risk management and safeguards for automated execution.

Provides pre-trade validation, position limits, turnover caps,
and a kill switch mechanism for emergency stops.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class KillSwitchActive(Exception):
    """Raised when kill switch is active and blocking execution."""
    pass


@dataclass
class ValidationResult:
    """Result of a single trade validation."""
    valid: bool
    symbol: str
    reason: str
    details: Optional[dict] = None


@dataclass
class BatchValidationResult:
    """Result of batch trade validation."""
    valid: bool
    results: list[ValidationResult]
    total_turnover_pct: float
    rejected_count: int
    reason: str


class RiskManager:
    """Pre-trade risk validation and kill switch management."""

    def __init__(self, config: dict):
        """Initialize risk manager.

        Args:
            config: Configuration dictionary with risk_limits section.
        """
        risk_config = config.get("risk_limits", {})

        self.max_position_pct = risk_config.get("max_position_pct", 0.25)
        self.max_turnover_pct = risk_config.get("max_turnover_pct", 0.50)
        self.exit_rank_threshold = config.get("position_sizing", {}).get("exit_rank_threshold", 5)

        kill_switch_path = risk_config.get("kill_switch_file", "data/.kill_switch")
        self.kill_switch_file = Path(kill_switch_path)

        logger.info(
            f"RiskManager initialized: max_position={self.max_position_pct:.0%}, "
            f"max_turnover={self.max_turnover_pct:.0%}, "
            f"exit_threshold=rank>{self.exit_rank_threshold}"
        )

    def is_kill_switch_active(self) -> bool:
        """Check if kill switch file exists.

        Returns:
            True if kill switch is active (file exists).
        """
        return self.kill_switch_file.exists()

    def get_kill_switch_reason(self) -> Optional[str]:
        """Get the reason for kill switch activation.

        Returns:
            Reason string from kill switch file, or None if not active.
        """
        if not self.kill_switch_file.exists():
            return None

        try:
            return self.kill_switch_file.read_text().strip()
        except IOError:
            return "Unknown reason"

    def activate_kill_switch(self, reason: str) -> None:
        """Activate kill switch by creating the file.

        Args:
            reason: Human-readable reason for activation.
        """
        self.kill_switch_file.parent.mkdir(parents=True, exist_ok=True)

        content = f"{reason}\nActivated: {datetime.now(timezone.utc).isoformat()}"
        self.kill_switch_file.write_text(content)

        logger.warning(f"KILL SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self) -> bool:
        """Deactivate kill switch by removing the file.

        Returns:
            True if deactivated, False if was not active.
        """
        if not self.kill_switch_file.exists():
            return False

        self.kill_switch_file.unlink()
        logger.info("Kill switch deactivated")
        return True

    def check_kill_switch(self) -> None:
        """Check kill switch and raise exception if active.

        Raises:
            KillSwitchActive: If kill switch is active.
        """
        if self.is_kill_switch_active():
            reason = self.get_kill_switch_reason()
            raise KillSwitchActive(f"Kill switch active: {reason}")

    def validate_trade(
        self,
        trade: dict,
        total_equity: float,
        current_position_value: float = 0,
    ) -> ValidationResult:
        """Validate a single trade against risk limits.

        Args:
            trade: Trade dictionary with symbol, action, shares_to_trade, price.
            total_equity: Total portfolio value.
            current_position_value: Current value of position in this symbol.

        Returns:
            ValidationResult with valid flag and reason.
        """
        symbol = trade.get("symbol", "UNKNOWN")
        action = trade.get("action", "")
        # Support both key names: "shares" (from engine) and "shares_to_trade" (legacy)
        shares = trade.get("shares", trade.get("shares_to_trade", 0))
        price = trade.get("price", 0)

        # Calculate trade value
        trade_value = shares * price if shares and price else 0

        # For buys, check if resulting position exceeds limit
        if action == "BUY":
            resulting_position = current_position_value + trade_value
            resulting_weight = resulting_position / total_equity if total_equity > 0 else 0

            if resulting_weight > self.max_position_pct:
                return ValidationResult(
                    valid=False,
                    symbol=symbol,
                    reason=f"Position would exceed {self.max_position_pct:.0%} limit ({resulting_weight:.1%})",
                    details={
                        "resulting_weight": resulting_weight,
                        "max_allowed": self.max_position_pct,
                        "trade_value": trade_value,
                    }
                )

        # Validate price is reasonable (not zero/negative)
        if price <= 0:
            return ValidationResult(
                valid=False,
                symbol=symbol,
                reason=f"Invalid price: {price}",
                details={"price": price}
            )

        # Validate shares is positive
        if shares <= 0:
            return ValidationResult(
                valid=False,
                symbol=symbol,
                reason=f"Invalid share count: {shares}",
                details={"shares": shares}
            )

        return ValidationResult(
            valid=True,
            symbol=symbol,
            reason="Passed all checks",
            details={
                "trade_value": trade_value,
                "trade_pct": trade_value / total_equity if total_equity > 0 else 0,
            }
        )

    def validate_batch(
        self,
        trades: list[dict],
        total_equity: float,
        current_positions: dict[str, float],
    ) -> BatchValidationResult:
        """Validate entire batch of trades.

        Args:
            trades: List of trade dictionaries.
            total_equity: Total portfolio value.
            current_positions: Dict mapping symbol to current position value.

        Returns:
            BatchValidationResult with overall validity and details.
        """
        # First check kill switch
        if self.is_kill_switch_active():
            reason = self.get_kill_switch_reason()
            return BatchValidationResult(
                valid=False,
                results=[],
                total_turnover_pct=0,
                rejected_count=len(trades),
                reason=f"Kill switch active: {reason}"
            )

        results = []
        total_turnover = 0
        rejected_count = 0

        for trade in trades:
            symbol = trade.get("symbol", "")
            current_value = current_positions.get(symbol, 0)

            result = self.validate_trade(trade, total_equity, current_value)
            results.append(result)

            if not result.valid:
                rejected_count += 1

            # Calculate turnover contribution
            shares = trade.get("shares", trade.get("shares_to_trade", 0))
            price = trade.get("price", 0)
            total_turnover += shares * price if shares and price else 0

        # Calculate turnover percentage
        turnover_pct = total_turnover / total_equity if total_equity > 0 else 0

        # Check turnover limit
        if turnover_pct > self.max_turnover_pct:
            return BatchValidationResult(
                valid=False,
                results=results,
                total_turnover_pct=turnover_pct,
                rejected_count=len(trades),
                reason=f"Total turnover {turnover_pct:.1%} exceeds {self.max_turnover_pct:.0%} limit"
            )

        # Check if any individual trades failed
        if rejected_count > 0:
            failed_symbols = [r.symbol for r in results if not r.valid]
            return BatchValidationResult(
                valid=False,
                results=results,
                total_turnover_pct=turnover_pct,
                rejected_count=rejected_count,
                reason=f"{rejected_count} trades failed validation: {', '.join(failed_symbols)}"
            )

        return BatchValidationResult(
            valid=True,
            results=results,
            total_turnover_pct=turnover_pct,
            rejected_count=0,
            reason="All trades passed validation"
        )

    def should_exit_position(self, symbol: str, rank: int) -> bool:
        """Check if a position should be exited based on rank.

        Args:
            symbol: Symbol of the position.
            rank: Current momentum rank (1 = best).

        Returns:
            True if position should be sold due to rank drop.
        """
        return rank > self.exit_rank_threshold

    def get_status(self) -> dict:
        """Get current risk manager status.

        Returns:
            Dictionary with current settings and kill switch status.
        """
        return {
            "max_position_pct": self.max_position_pct,
            "max_turnover_pct": self.max_turnover_pct,
            "exit_rank_threshold": self.exit_rank_threshold,
            "kill_switch_active": self.is_kill_switch_active(),
            "kill_switch_reason": self.get_kill_switch_reason(),
        }

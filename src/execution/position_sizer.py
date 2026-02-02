"""Position sizing calculations for automated execution.

Calculates share quantities based on target weights, respecting
position limits and handling fractional share rounding.
"""

import logging
import math
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SizedTrade:
    """A trade with calculated share quantity."""
    symbol: str
    action: str  # "BUY" or "SELL"
    shares: int
    price: float
    target_weight: float
    current_weight: float
    trade_value: float
    reason: str


class PositionSizer:
    """Calculates position sizes with risk constraints."""

    def __init__(
        self,
        total_equity: float,
        cash_available: float,
        current_positions: dict[str, dict],
        config: dict,
    ):
        """Initialize position sizer.

        Args:
            total_equity: Total portfolio value.
            cash_available: Cash available for trading.
            current_positions: Dict mapping symbol to position info.
            config: Configuration with position_sizing and risk_limits.
        """
        self.total_equity = total_equity
        self.cash = cash_available
        self.positions = current_positions

        sizing_config = config.get("position_sizing", {})
        risk_config = config.get("risk_limits", {})

        self.top_n = sizing_config.get("top_n", 3)
        self.min_trade_shares = sizing_config.get("min_trade_shares", 1)
        self.min_trade_value = sizing_config.get("min_trade_value", 100)
        self.max_position_pct = risk_config.get("max_position_pct", 0.25)

        logger.info(
            f"PositionSizer initialized: equity={total_equity:,.2f}, "
            f"cash={cash_available:,.2f}, top_n={self.top_n}"
        )

    def get_current_weight(self, symbol: str) -> float:
        """Get current portfolio weight for a symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            Current weight (0-1), or 0 if not held.
        """
        if self.total_equity <= 0:
            return 0

        pos = self.positions.get(symbol, {})
        market_value = pos.get("market_value", 0)
        return market_value / self.total_equity

    def get_current_shares(self, symbol: str) -> float:
        """Get current share count for a symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            Current shares held, or 0 if not held.
        """
        pos = self.positions.get(symbol, {})
        return pos.get("quantity", 0)

    def calculate_target_shares(
        self,
        symbol: str,
        target_weight: float,
        current_price: float,
    ) -> int:
        """Calculate shares needed to reach target weight.

        Args:
            symbol: Ticker symbol.
            target_weight: Target portfolio weight (0-1).
            current_price: Current market price.

        Returns:
            Number of shares to hold (absolute, not delta).
        """
        if current_price <= 0:
            logger.warning(f"Invalid price for {symbol}: {current_price}")
            return 0

        # Cap at max position size
        effective_weight = min(target_weight, self.max_position_pct)
        if effective_weight < target_weight:
            logger.info(
                f"{symbol}: Target {target_weight:.1%} capped to {effective_weight:.1%}"
            )

        target_value = self.total_equity * effective_weight
        target_shares = math.floor(target_value / current_price)

        return max(0, target_shares)

    def calculate_trade(
        self,
        symbol: str,
        target_weight: float,
        current_price: float,
        min_threshold: float = 0.02,
    ) -> Optional[SizedTrade]:
        """Calculate trade needed to move from current to target weight.

        Args:
            symbol: Ticker symbol.
            target_weight: Target portfolio weight (0-1).
            current_price: Current market price.
            min_threshold: Minimum weight difference to trigger trade.

        Returns:
            SizedTrade if trade needed, None if within threshold.
        """
        current_weight = self.get_current_weight(symbol)
        current_shares = self.get_current_shares(symbol)
        weight_diff = target_weight - current_weight

        # Skip if within threshold
        if abs(weight_diff) < min_threshold:
            logger.debug(f"{symbol}: Within threshold ({weight_diff:+.2%}), no trade")
            return None

        # Skip if no valid price
        if current_price <= 0:
            logger.warning(f"{symbol}: No valid price, skipping")
            return None

        # Calculate target shares
        target_shares = self.calculate_target_shares(symbol, target_weight, current_price)
        shares_diff = target_shares - current_shares

        if shares_diff > 0:
            # BUY
            action = "BUY"
            shares_to_trade = shares_diff
            reason = f"Weight {current_weight:.1%} -> {target_weight:.1%}"
        elif shares_diff < 0:
            # SELL
            action = "SELL"
            shares_to_trade = abs(shares_diff)
            # Don't sell more than we have
            shares_to_trade = min(shares_to_trade, current_shares)
            reason = f"Weight {current_weight:.1%} -> {target_weight:.1%}"
        else:
            # No change needed
            return None

        # Check minimum trade size
        trade_value = shares_to_trade * current_price
        if shares_to_trade < self.min_trade_shares:
            logger.debug(f"{symbol}: Trade {shares_to_trade} shares below minimum")
            return None
        if trade_value < self.min_trade_value:
            logger.debug(f"{symbol}: Trade value {trade_value:.2f} below minimum")
            return None

        return SizedTrade(
            symbol=symbol,
            action=action,
            shares=int(shares_to_trade),
            price=current_price,
            target_weight=target_weight,
            current_weight=current_weight,
            trade_value=trade_value,
            reason=reason,
        )

    def generate_trades(
        self,
        target_weights: dict[str, float],
        current_prices: dict[str, float],
        min_threshold: float = 0.02,
    ) -> list[SizedTrade]:
        """Generate full trade list from target weights.

        Processes sells first (to free up cash), then buys.

        Args:
            target_weights: Dict mapping symbol to target weight.
            current_prices: Dict mapping symbol to current price.
            min_threshold: Minimum weight difference to trigger trade.

        Returns:
            List of SizedTrade objects, sells first then buys.
        """
        # Get all symbols we need to consider
        all_symbols = set(target_weights.keys()) | set(self.positions.keys())

        sells = []
        buys = []

        for symbol in all_symbols:
            target = target_weights.get(symbol, 0)
            price = current_prices.get(symbol, 0)

            # Get price from positions if not in current_prices
            if price <= 0 and symbol in self.positions:
                price = self.positions[symbol].get("market_price", 0)

            trade = self.calculate_trade(symbol, target, price, min_threshold)

            if trade:
                if trade.action == "SELL":
                    sells.append(trade)
                else:
                    buys.append(trade)

        # Sort sells by value descending (larger sells first to free cash)
        sells.sort(key=lambda t: t.trade_value, reverse=True)

        # Sort buys by target weight descending (highest conviction first)
        buys.sort(key=lambda t: t.target_weight, reverse=True)

        # Check if we have enough cash for buys after sells
        sell_proceeds = sum(t.trade_value for t in sells)
        buy_cost = sum(t.trade_value for t in buys)
        available_cash = self.cash + sell_proceeds

        if buy_cost > available_cash:
            logger.warning(
                f"Insufficient cash: need {buy_cost:,.2f}, have {available_cash:,.2f}"
            )
            # Reduce buys to fit available cash
            buys = self._reduce_buys_to_cash(buys, available_cash)

        # Log summary
        logger.info(
            f"Generated {len(sells)} sells ({sell_proceeds:,.2f}) and "
            f"{len(buys)} buys ({sum(t.trade_value for t in buys):,.2f})"
        )

        return sells + buys

    def _reduce_buys_to_cash(
        self,
        buys: list[SizedTrade],
        available_cash: float,
    ) -> list[SizedTrade]:
        """Reduce buy list to fit within available cash.

        Args:
            buys: List of buy trades.
            available_cash: Cash available for buys.

        Returns:
            Reduced list of trades that fit within cash.
        """
        result = []
        remaining_cash = available_cash

        for trade in buys:
            if trade.trade_value <= remaining_cash:
                result.append(trade)
                remaining_cash -= trade.trade_value
            else:
                # Try to reduce share count to fit
                affordable_shares = math.floor(remaining_cash / trade.price)
                if affordable_shares >= self.min_trade_shares:
                    reduced = SizedTrade(
                        symbol=trade.symbol,
                        action=trade.action,
                        shares=affordable_shares,
                        price=trade.price,
                        target_weight=trade.target_weight,
                        current_weight=trade.current_weight,
                        trade_value=affordable_shares * trade.price,
                        reason=f"{trade.reason} (reduced due to cash)"
                    )
                    result.append(reduced)
                    remaining_cash -= reduced.trade_value
                    logger.info(
                        f"{trade.symbol}: Reduced from {trade.shares} to "
                        f"{affordable_shares} shares due to cash"
                    )
                else:
                    logger.warning(f"{trade.symbol}: Skipped, insufficient cash")

        return result

    def validate_turnover(self, trades: list[SizedTrade]) -> tuple[bool, float]:
        """Check if total turnover exceeds limit.

        Args:
            trades: List of trades.

        Returns:
            Tuple of (is_valid, turnover_percentage).
        """
        total_turnover = sum(t.trade_value for t in trades)
        turnover_pct = total_turnover / self.total_equity if self.total_equity > 0 else 0

        # Get max turnover from config (accessed via calculate_trades)
        max_turnover = 0.50  # Default 50%

        return turnover_pct <= max_turnover, turnover_pct

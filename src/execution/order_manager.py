"""Order submission to IBKR with dry-run support.

Handles order creation, submission, and status tracking.
Supports dry-run mode for testing without real orders.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ib_insync import IB, Contract, Stock, Order, Trade, LimitOrder, MarketOrder

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of an order execution attempt."""
    order_id: str
    symbol: str
    action: str
    shares: int
    order_type: str
    status: str  # "submitted", "filled", "cancelled", "rejected", "dry_run"
    fill_price: Optional[float] = None
    fill_time: Optional[str] = None
    message: str = ""
    dry_run: bool = False


@dataclass
class OrderBatch:
    """A batch of orders to execute together."""
    orders: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    execution_results: list[ExecutionResult] = field(default_factory=list)


class OrderManager:
    """Manages order creation and submission to IBKR."""

    # Exchange for UK sector ETFs
    UK_ETF_EXCHANGE = "LSEETF"
    UK_ETF_CURRENCY = "USD"  # SPDR ETFs are USD-denominated

    def __init__(self, config: dict, dry_run: bool = True):
        """Initialize order manager.

        Args:
            config: Configuration dictionary with broker and execution settings.
            dry_run: If True (default), log orders but don't submit to IBKR.
        """
        self.config = config
        self.dry_run = dry_run
        self.ib: Optional[IB] = None
        self._connected = False

        exec_config = config.get("execution", {})
        self.order_type = exec_config.get("order_type", "MOC")
        self.limit_offset_bps = exec_config.get("limit_offset_bps", 10)
        self.fill_timeout = exec_config.get("fill_timeout", 300)

        mode_str = "DRY RUN" if dry_run else "LIVE"
        logger.info(f"OrderManager initialized in {mode_str} mode, order_type={self.order_type}")

    def connect(self) -> bool:
        """Connect to IBKR.

        Returns:
            True if connected (or dry-run mode), False otherwise.
        """
        if self.dry_run:
            logger.info("Dry-run mode: Skipping IBKR connection")
            return True

        # Import here to avoid circular dependency
        from ..execution_logger import IBKRConnection

        try:
            conn = IBKRConnection(self.config)
            if conn.connect():
                self.ib = conn.ib
                self._connected = True
                logger.info("Connected to IBKR for order submission")
                return True
            else:
                logger.error("Failed to connect to IBKR")
                return False
        except Exception as e:
            logger.error(f"IBKR connection error: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from IBKR."""
        if self._connected and self.ib:
            self.ib.disconnect()
            self._connected = False
            logger.info("Disconnected from IBKR")

    def create_contract(self, symbol: str) -> Contract:
        """Create IBKR Contract for a UK sector ETF.

        Args:
            symbol: Ticker symbol (with or without .L suffix).

        Returns:
            IBKR Stock Contract object.
        """
        # Remove .L suffix if present for IBKR
        clean_symbol = symbol.replace(".L", "")

        contract = Stock(
            symbol=clean_symbol,
            exchange=self.UK_ETF_EXCHANGE,
            currency=self.UK_ETF_CURRENCY,
        )

        return contract

    def create_order(
        self,
        action: str,
        quantity: int,
        order_type: Optional[str] = None,
        limit_price: Optional[float] = None,
    ) -> Order:
        """Create IBKR Order object.

        Args:
            action: "BUY" or "SELL".
            quantity: Number of shares.
            order_type: "MKT", "MOC", or "LMT". Uses config default if None.
            limit_price: Limit price for LMT orders.

        Returns:
            IBKR Order object.
        """
        if order_type is None:
            order_type = self.order_type

        if order_type == "LMT":
            if limit_price is None:
                raise ValueError("Limit price required for LMT orders")
            order = LimitOrder(action=action, totalQuantity=quantity, lmtPrice=limit_price)
        elif order_type == "MOC":
            # Market-on-close order
            order = Order(
                action=action,
                totalQuantity=quantity,
                orderType="MOC",
            )
        else:  # MKT
            order = MarketOrder(action=action, totalQuantity=quantity)

        return order

    def calculate_limit_price(
        self,
        action: str,
        current_price: float,
    ) -> float:
        """Calculate limit price with offset.

        Args:
            action: "BUY" or "SELL".
            current_price: Current market price.

        Returns:
            Limit price with offset applied.
        """
        offset_pct = self.limit_offset_bps / 10000

        if action == "BUY":
            # Buy slightly above market to increase fill probability
            return round(current_price * (1 + offset_pct), 2)
        else:
            # Sell slightly below market
            return round(current_price * (1 - offset_pct), 2)

    def submit_order(
        self,
        symbol: str,
        action: str,
        shares: int,
        price: float,
        order_type: Optional[str] = None,
    ) -> ExecutionResult:
        """Submit a single order to IBKR or log in dry-run mode.

        Args:
            symbol: Ticker symbol.
            action: "BUY" or "SELL".
            shares: Number of shares.
            price: Current price (used for limit orders and logging).
            order_type: Order type override.

        Returns:
            ExecutionResult with status and details.
        """
        order_id = str(uuid.uuid4())[:8]

        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would submit: {action} {shares} {symbol} @ "
                f"{order_type or self.order_type} (price ~{price:.2f})"
            )
            return ExecutionResult(
                order_id=order_id,
                symbol=symbol,
                action=action,
                shares=shares,
                order_type=order_type or self.order_type,
                status="dry_run",
                fill_price=price,
                fill_time=datetime.now(timezone.utc).isoformat(),
                message="Dry run - order not submitted",
                dry_run=True,
            )

        if not self._connected or not self.ib:
            return ExecutionResult(
                order_id=order_id,
                symbol=symbol,
                action=action,
                shares=shares,
                order_type=order_type or self.order_type,
                status="rejected",
                message="Not connected to IBKR",
                dry_run=False,
            )

        try:
            contract = self.create_contract(symbol)

            # Qualify the contract
            self.ib.qualifyContracts(contract)

            # Determine limit price if needed
            effective_order_type = order_type or self.order_type
            limit_price = None
            if effective_order_type == "LMT":
                limit_price = self.calculate_limit_price(action, price)

            order = self.create_order(action, shares, effective_order_type, limit_price)

            # Submit order
            trade = self.ib.placeOrder(contract, order)

            logger.info(
                f"Order submitted: {action} {shares} {symbol} @ {effective_order_type}"
            )

            return ExecutionResult(
                order_id=str(trade.order.orderId),
                symbol=symbol,
                action=action,
                shares=shares,
                order_type=effective_order_type,
                status="submitted",
                message=f"Order submitted to IBKR",
                dry_run=False,
            )

        except Exception as e:
            logger.error(f"Order submission failed for {symbol}: {e}")
            return ExecutionResult(
                order_id=order_id,
                symbol=symbol,
                action=action,
                shares=shares,
                order_type=order_type or self.order_type,
                status="rejected",
                message=f"Submission error: {e}",
                dry_run=False,
            )

    def submit_batch(
        self,
        trades: list[dict],
    ) -> list[ExecutionResult]:
        """Submit multiple orders with proper sequencing.

        Executes SELL orders first to free up cash, then BUY orders.

        Args:
            trades: List of trade dicts with symbol, action, shares, price.

        Returns:
            List of ExecutionResult for each trade.
        """
        results = []

        # Separate sells and buys
        sells = [t for t in trades if t.get("action") == "SELL"]
        buys = [t for t in trades if t.get("action") == "BUY"]

        logger.info(f"Executing batch: {len(sells)} sells, {len(buys)} buys")

        # Execute sells first
        for trade in sells:
            result = self.submit_order(
                symbol=trade["symbol"],
                action=trade["action"],
                shares=trade["shares"],
                price=trade["price"],
            )
            results.append(result)

        # Execute buys
        for trade in buys:
            result = self.submit_order(
                symbol=trade["symbol"],
                action=trade["action"],
                shares=trade["shares"],
                price=trade["price"],
            )
            results.append(result)

        # Summary
        submitted = sum(1 for r in results if r.status in ("submitted", "dry_run"))
        rejected = sum(1 for r in results if r.status == "rejected")
        logger.info(f"Batch complete: {submitted} submitted, {rejected} rejected")

        return results

    def cancel_all(self) -> int:
        """Cancel all open orders.

        Returns:
            Number of orders cancelled.
        """
        if self.dry_run:
            logger.info("[DRY RUN] Would cancel all open orders")
            return 0

        if not self._connected or not self.ib:
            logger.warning("Cannot cancel orders: not connected")
            return 0

        try:
            open_trades = self.ib.openTrades()
            count = 0
            for trade in open_trades:
                self.ib.cancelOrder(trade.order)
                count += 1
                logger.info(f"Cancelled order: {trade.order.orderId}")
            return count
        except Exception as e:
            logger.error(f"Error cancelling orders: {e}")
            return 0

    def get_order_status(self, order_id: str) -> Optional[dict]:
        """Get status of a submitted order.

        Args:
            order_id: IBKR order ID.

        Returns:
            Order status dict or None if not found.
        """
        if self.dry_run or not self._connected:
            return None

        try:
            for trade in self.ib.trades():
                if str(trade.order.orderId) == order_id:
                    return {
                        "order_id": order_id,
                        "status": trade.orderStatus.status,
                        "filled": trade.orderStatus.filled,
                        "remaining": trade.orderStatus.remaining,
                        "avg_fill_price": trade.orderStatus.avgFillPrice,
                    }
            return None
        except Exception as e:
            logger.error(f"Error getting order status: {e}")
            return None

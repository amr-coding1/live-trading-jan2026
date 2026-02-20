"""Execution logger for IBKR trades.

Connects to Interactive Brokers TWS/Gateway via ib_insync,
pulls executions, and saves them to CSV files with portfolio snapshots.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml
from ib_insync import IB, Execution, Fill, util

logger = logging.getLogger(__name__)


def setup_logging(config: dict) -> None:
    """Configure logging with rotation.

    Args:
        config: Configuration dictionary with logging settings.
    """
    from logging.handlers import RotatingFileHandler

    log_dir = Path(config["paths"]["logs"])
    log_dir.mkdir(parents=True, exist_ok=True)

    log_config = config.get("logging", {})
    level = getattr(logging, log_config.get("level", "INFO"))
    max_bytes = log_config.get("max_bytes", 10485760)
    backup_count = log_config.get("backup_count", 5)

    handler = RotatingFileHandler(
        log_dir / "execution_logger.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root_logger.addHandler(console_handler)


def load_config(config_path: str = "config/config.yaml") -> dict:
    """Load configuration from YAML file.

    Args:
        config_path: Path to the configuration file.

    Returns:
        Configuration dictionary.

    Raises:
        FileNotFoundError: If config file doesn't exist.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. "
            "Copy config/config.example.yaml to config/config.yaml and update settings."
        )

    with open(path) as f:
        return yaml.safe_load(f)


def load_annotations(annotations_dir: Path) -> dict[str, dict]:
    """Load all trade annotations into a lookup dict.

    Args:
        annotations_dir: Path to annotations directory.

    Returns:
        Dictionary mapping trade_id to annotation data.
    """
    annotations = {}
    annotations_path = Path(annotations_dir)

    if not annotations_path.exists():
        return annotations

    for json_file in annotations_path.glob("*.json"):
        if json_file.name.startswith("monthly"):
            continue
        try:
            with open(json_file) as f:
                data = json.load(f)
                if "trade_id" in data:
                    annotations[data["trade_id"]] = data
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load annotation {json_file}: {e}")

    return annotations


class IBKRConnection:
    """Manages connection to Interactive Brokers TWS/Gateway."""

    def __init__(self, config: dict):
        """Initialize IBKR connection manager.

        Args:
            config: Configuration dictionary with broker settings.
        """
        self.config = config
        self.ib = IB()
        self._connected = False

    def connect(self, max_retries: int = 2) -> bool:
        """Connect to IBKR TWS/Gateway with retry logic.

        Supports environment variable overrides for Docker deployment:
        - IB_HOST: Override broker host (default: config value)
        - IB_PORT: Override broker port (default: config value)

        Args:
            max_retries: Maximum connection attempts.

        Returns:
            True if connected successfully, False otherwise.
        """
        import os
        broker_config = self.config["broker"]

        # Environment variable overrides for Docker
        host = os.environ.get("IB_HOST", broker_config["host"])
        port = int(os.environ.get("IB_PORT", str(broker_config["port"])))

        for attempt in range(max_retries):
            try:
                self.ib.connect(
                    host=host,
                    port=port,
                    clientId=broker_config["client_id"],
                    timeout=broker_config.get("timeout", 30),
                    readonly=broker_config.get("readonly", False),
                )
                self._connected = True
                logger.info(
                    f"Connected to IBKR at {host}:{port}"
                )
                return True
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    util.sleep(2 ** attempt)

        logger.error(f"Failed to connect after {max_retries} attempts")
        return False

    def disconnect(self) -> None:
        """Disconnect from IBKR."""
        if self._connected:
            self.ib.disconnect()
            self._connected = False
            logger.info("Disconnected from IBKR")

    @property
    def connected(self) -> bool:
        """Check if currently connected."""
        return self._connected and self.ib.isConnected()

    def __enter__(self):
        """Context manager entry."""
        if not self.connect():
            raise ConnectionError("Failed to connect to IBKR in context manager")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


def get_asset_class(sec_type: str) -> str:
    """Map IBKR security type to simplified asset class.

    Args:
        sec_type: IBKR security type code.

    Returns:
        Simplified asset class string.
    """
    mapping = {
        "STK": "STK",
        "FUT": "FUT",
        "OPT": "OPT",
        "CASH": "FX",
        "CRYPTO": "CRYPTO",
        "CMDTY": "CMDTY",
        "ETF": "STK",
        "IND": "IND",
    }
    return mapping.get(sec_type, sec_type)


def calculate_slippage_bps(
    intended_price: Optional[float], fill_price: float, side: str
) -> Optional[float]:
    """Calculate slippage in basis points.

    Args:
        intended_price: Expected fill price (nullable).
        fill_price: Actual fill price.
        side: Trade side (BUY or SELL).

    Returns:
        Slippage in basis points, or None if intended_price not provided.
        Positive slippage means unfavorable execution.
    """
    if intended_price is None or intended_price == 0:
        return None

    if side == "BUY":
        slippage = (fill_price - intended_price) / intended_price
    else:
        slippage = (intended_price - fill_price) / intended_price

    return round(slippage * 10000, 2)


def fill_to_record(
    fill: Fill,
    annotations: dict[str, dict],
    excluded_types: list[str],
) -> Optional[dict]:
    """Convert IBKR Fill to execution record.

    Args:
        fill: IBKR Fill object.
        annotations: Dictionary of trade annotations.
        excluded_types: List of excluded instrument types.

    Returns:
        Execution record dictionary, or None if excluded.
    """
    contract = fill.contract
    execution = fill.execution

    if contract.secType in excluded_types:
        logger.debug(f"Skipping excluded instrument type: {contract.secType}")
        return None

    trade_id = str(uuid.uuid4())
    side = "BUY" if execution.side == "BOT" else "SELL"

    intended_price = None
    for ann_id, ann_data in annotations.items():
        pre_trade = ann_data.get("pre_trade", {})
        if pre_trade.get("symbol") == contract.symbol:
            intended_price = pre_trade.get("intended_entry")
            trade_id = ann_id
            break

    slippage_bps = calculate_slippage_bps(intended_price, execution.avgPrice, side)

    return {
        "trade_id": trade_id,
        "timestamp": execution.time.isoformat(),
        "symbol": contract.symbol,
        "asset_class": get_asset_class(contract.secType),
        "side": side,
        "quantity": abs(execution.shares),
        "intended_price": intended_price,
        "fill_price": execution.avgPrice,
        "slippage_bps": slippage_bps,
        "commission": fill.commissionReport.commission if fill.commissionReport else 0,
        "commission_currency": (
            fill.commissionReport.currency if fill.commissionReport else "USD"
        ),
    }


def pull_executions(
    ib: IB,
    config: dict,
    since: Optional[datetime] = None,
) -> pd.DataFrame:
    """Pull executions from IBKR.

    Args:
        ib: Connected IB instance.
        config: Configuration dictionary.
        since: Only include executions after this time (UTC).

    Returns:
        DataFrame of execution records.
    """
    annotations = load_annotations(Path(config["paths"]["annotations"]))
    excluded_types = config.get("excluded_instrument_types", [])

    try:
        fills = ib.fills()
        logger.info(f"Retrieved {len(fills)} fills from IBKR")
    except Exception as e:
        logger.error(f"Failed to retrieve fills from IBKR: {e}")
        return pd.DataFrame(columns=[
            "trade_id", "timestamp", "symbol", "asset_class", "side",
            "quantity", "intended_price", "fill_price", "slippage_bps",
            "commission", "commission_currency"
        ])

    records = []
    for fill in fills:
        try:
            if since and fill.execution.time < since:
                continue

            record = fill_to_record(fill, annotations, excluded_types)
            if record:
                records.append(record)
        except Exception as e:
            logger.warning(f"Failed to process fill: {e}")
            continue

    df = pd.DataFrame(records) if records else pd.DataFrame(columns=[
        "trade_id", "timestamp", "symbol", "asset_class", "side",
        "quantity", "intended_price", "fill_price", "slippage_bps",
        "commission", "commission_currency"
    ])

    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")

    logger.info(f"Processed {len(df)} executions")
    return df


def save_executions(df: pd.DataFrame, output_dir: str) -> Path:
    """Save executions to dated CSV file.

    Uses atomic write with temp file to prevent corruption.

    Args:
        df: DataFrame of executions.
        output_dir: Directory to save CSV files.

    Returns:
        Path to saved file.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    file_path = output_path / f"{date_str}.csv"
    temp_path = output_path / f"{date_str}.csv.tmp"

    if file_path.exists():
        try:
            existing = pd.read_csv(file_path)
            df = pd.concat([existing, df]).drop_duplicates(subset=["trade_id"])
        except Exception as e:
            logger.warning(f"Failed to read existing file, overwriting: {e}")

    # Atomic write using temp file
    df.to_csv(temp_path, index=False)
    temp_path.replace(file_path)

    logger.info(f"Saved executions to {file_path}")
    return file_path


def get_portfolio_snapshot(ib: IB) -> dict:
    """Get current portfolio snapshot.

    Args:
        ib: Connected IB instance.

    Returns:
        Portfolio snapshot dictionary.
    """
    try:
        account_values = {av.tag: av.value for av in ib.accountValues()}
    except Exception as e:
        logger.error(f"Failed to get account values: {e}")
        account_values = {}

    positions = []
    try:
        ib_positions = ib.positions()
    except Exception as e:
        logger.error(f"Failed to get positions: {e}")
        ib_positions = []

    for pos in ib_positions:
        ib.qualifyContracts(pos.contract)

        # First try live market data (type 1)
        ib.reqMarketDataType(1)
        ticker = ib.reqMktData(pos.contract, "", False, False)
        ib.sleep(2)  # Wait for market data

        # Try multiple price sources before falling back to avg_cost
        market_price = ticker.marketPrice()
        price_source = "market"

        if market_price != market_price:  # NaN check - try delayed data
            ib.cancelMktData(pos.contract)

            # Switch to delayed data (type 3) and retry
            ib.reqMarketDataType(3)
            ticker = ib.reqMktData(pos.contract, "", False, False)
            ib.sleep(2)

            market_price = ticker.marketPrice()
            if market_price == market_price:  # Got delayed data
                price_source = "delayed"
            else:
                # Try last traded price
                if ticker.last and ticker.last == ticker.last:
                    market_price = ticker.last
                    price_source = "delayed_last"
                # Try close price
                elif ticker.close and ticker.close == ticker.close:
                    market_price = ticker.close
                    price_source = "close"
                # Try bid/ask midpoint
                elif ticker.bid and ticker.ask and ticker.bid == ticker.bid and ticker.ask == ticker.ask:
                    market_price = (ticker.bid + ticker.ask) / 2
                    price_source = "mid"
                # Final fallback to avg_cost
                else:
                    market_price = pos.avgCost
                    price_source = "avg_cost"
                    logger.warning(
                        f"No market data for {pos.contract.symbol}, using avg_cost as fallback"
                    )

        logger.debug(f"{pos.contract.symbol}: price={market_price} (source={price_source})")

        market_value = pos.position * market_price
        unrealized_pnl = market_value - (pos.position * pos.avgCost)

        positions.append({
            "symbol": pos.contract.symbol if pos.contract.symbol.endswith(".L") else f"{pos.contract.symbol}.L",
            "quantity": pos.position,
            "avg_cost": pos.avgCost,
            "market_price": market_price,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "price_source": price_source,  # Track where price came from
        })

        ib.cancelMktData(pos.contract)

    total_equity = float(account_values.get("NetLiquidation", 0))
    cash = float(account_values.get("TotalCashValue", 0))

    # Integrity validation: catch cases where IBKR didn't return positions
    # Note: IBKR's NetLiquidation != cash + sum(market_value) exactly,
    # because of margin, unsettled cash, etc. So we check for the specific
    # failure mode: equity >> cash but no positions loaded.
    positions_value = sum(p.get("market_value", 0) for p in positions)
    if total_equity > 0 and len(positions) == 0 and total_equity > cash * 1.1:
        missing_value = total_equity - cash
        logger.error(
            f"SNAPSHOT INTEGRITY FAILURE: equity={total_equity:,.2f} but "
            f"no positions loaded and cash={cash:,.2f}. "
            f"Missing ~{missing_value:,.2f} in unloaded positions. "
            f"IBKR API likely returned empty positions list."
        )
        raise ValueError(
            f"Snapshot integrity check failed: equity ({total_equity:,.2f}) is "
            f"significantly higher than cash ({cash:,.2f}) but 0 positions loaded. "
            f"IBKR may not have returned positions correctly."
        )

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_equity": total_equity,
        "cash": cash,
        "positions": positions,
    }


def save_snapshot(snapshot: dict, output_dir: str) -> Path:
    """Save portfolio snapshot to dated JSON file.

    Args:
        snapshot: Portfolio snapshot dictionary.
        output_dir: Directory to save snapshot files.

    Returns:
        Path to saved file.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    file_path = output_path / f"{date_str}.json"

    with open(file_path, "w") as f:
        json.dump(snapshot, f, indent=2)

    logger.info(f"Saved snapshot to {file_path}")
    return file_path


def pull_and_save(config: Optional[dict] = None) -> tuple[Path, Path]:
    """Pull executions and snapshot, save both.

    Args:
        config: Configuration dictionary. Loads from file if None.

    Returns:
        Tuple of (executions_path, snapshot_path).
    """
    if config is None:
        config = load_config()

    setup_logging(config)

    with IBKRConnection(config) as conn:
        if not conn.connected:
            raise ConnectionError("Failed to connect to IBKR")

        executions_df = pull_executions(conn.ib, config)
        executions_path = save_executions(executions_df, config["paths"]["executions"])

        snapshot = get_portfolio_snapshot(conn.ib)
        snapshot_path = save_snapshot(snapshot, config["paths"]["snapshots"])

    return executions_path, snapshot_path


def pull_executions_only(config: Optional[dict] = None) -> Path:
    """Pull and save executions only (no snapshot).

    Args:
        config: Configuration dictionary. Loads from file if None.

    Returns:
        Path to saved executions file.
    """
    if config is None:
        config = load_config()

    setup_logging(config)

    with IBKRConnection(config) as conn:
        if not conn.connected:
            raise ConnectionError("Failed to connect to IBKR")

        executions_df = pull_executions(conn.ib, config)
        return save_executions(executions_df, config["paths"]["executions"])


def save_snapshot_only(config: Optional[dict] = None) -> Path:
    """Pull and save portfolio snapshot only.

    Args:
        config: Configuration dictionary. Loads from file if None.

    Returns:
        Path to saved snapshot file.
    """
    if config is None:
        config = load_config()

    setup_logging(config)

    with IBKRConnection(config) as conn:
        if not conn.connected:
            raise ConnectionError("Failed to connect to IBKR")

        snapshot = get_portfolio_snapshot(conn.ib)
        return save_snapshot(snapshot, config["paths"]["snapshots"])

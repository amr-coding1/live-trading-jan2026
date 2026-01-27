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

    def connect(self, max_retries: int = 3) -> bool:
        """Connect to IBKR TWS/Gateway with retry logic.

        Args:
            max_retries: Maximum connection attempts.

        Returns:
            True if connected successfully, False otherwise.
        """
        broker_config = self.config["broker"]

        for attempt in range(max_retries):
            try:
                self.ib.connect(
                    host=broker_config["host"],
                    port=broker_config["port"],
                    clientId=broker_config["client_id"],
                    timeout=broker_config.get("timeout", 30),
                    readonly=broker_config.get("readonly", False),
                )
                self._connected = True
                logger.info(
                    f"Connected to IBKR at {broker_config['host']}:{broker_config['port']}"
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
        self.connect()
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

    fills = ib.fills()
    logger.info(f"Retrieved {len(fills)} fills from IBKR")

    records = []
    for fill in fills:
        if since and fill.execution.time < since:
            continue

        record = fill_to_record(fill, annotations, excluded_types)
        if record:
            records.append(record)

    df = pd.DataFrame(records)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")

    logger.info(f"Processed {len(df)} executions")
    return df


def save_executions(df: pd.DataFrame, output_dir: str) -> Path:
    """Save executions to dated CSV file.

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

    if file_path.exists():
        existing = pd.read_csv(file_path)
        df = pd.concat([existing, df]).drop_duplicates(subset=["trade_id"])

    df.to_csv(file_path, index=False)
    logger.info(f"Saved executions to {file_path}")
    return file_path


def get_portfolio_snapshot(ib: IB) -> dict:
    """Get current portfolio snapshot.

    Args:
        ib: Connected IB instance.

    Returns:
        Portfolio snapshot dictionary.
    """
    account_values = {av.tag: av.value for av in ib.accountValues()}

    positions = []
    for pos in ib.positions():
        ib.qualifyContracts(pos.contract)
        ticker = ib.reqMktData(pos.contract, "", False, False)
        ib.sleep(1)

        market_price = ticker.marketPrice()
        if market_price != market_price:
            market_price = pos.avgCost

        market_value = pos.position * market_price
        unrealized_pnl = market_value - (pos.position * pos.avgCost)

        positions.append({
            "symbol": pos.contract.symbol,
            "quantity": pos.position,
            "avg_cost": pos.avgCost,
            "market_price": market_price,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
        })

        ib.cancelMktData(pos.contract)

    total_equity = float(account_values.get("NetLiquidation", 0))
    cash = float(account_values.get("TotalCashValue", 0))

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

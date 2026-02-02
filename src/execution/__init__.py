"""Automated execution module for signal-to-order pipeline.

This module provides automated trading execution with:
- Signal processing and order generation
- Position sizing with risk constraints
- Order submission to IBKR (with dry-run mode)
- Kill switch and safeguards
- Full audit trail logging
"""

from .engine import ExecutionEngine, run_execution_pipeline
from .order_manager import OrderManager
from .position_sizer import PositionSizer
from .risk_manager import RiskManager, KillSwitchActive
from .signal_logger import SignalLogger

__all__ = [
    "ExecutionEngine",
    "run_execution_pipeline",
    "OrderManager",
    "PositionSizer",
    "RiskManager",
    "KillSwitchActive",
    "SignalLogger",
]

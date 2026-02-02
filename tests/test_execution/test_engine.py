"""Tests for execution engine."""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd


@pytest.fixture
def config(tmp_path):
    """Sample configuration."""
    # Create required directories
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "signals").mkdir()
    (tmp_path / "logs").mkdir()

    return {
        "paths": {
            "snapshots": str(tmp_path / "snapshots"),
            "logs": str(tmp_path / "logs"),
        },
        "execution": {
            "mode": "dry_run",
            "order_type": "MOC",
        },
        "position_sizing": {
            "top_n": 3,
            "exit_rank_threshold": 5,
            "min_trade_threshold": 0.02,
            "min_trade_shares": 1,
            "min_trade_value": 100,
        },
        "risk_limits": {
            "max_position_pct": 0.25,
            "max_turnover_pct": 0.50,
            "kill_switch_file": str(tmp_path / ".kill_switch"),
        },
        "signals": {
            "log_dir": str(tmp_path / "signals"),
        },
    }


@pytest.fixture
def sample_snapshot(config):
    """Create a sample snapshot file."""
    snapshot = {
        "timestamp": "2026-02-02T16:35:00+00:00",
        "total_equity": 100000,
        "cash": 35000,
        "positions": [
            {
                "symbol": "SXLK",
                "quantity": 100,
                "avg_cost": 150,
                "market_price": 160,
                "market_value": 16000,
                "unrealized_pnl": 1000,
            },
            {
                "symbol": "SXLI",
                "quantity": 200,
                "avg_cost": 70,
                "market_price": 75,
                "market_value": 15000,
                "unrealized_pnl": 1000,
            },
        ],
    }
    snapshot_path = Path(config["paths"]["snapshots"]) / "2026-02-02.json"
    with open(snapshot_path, "w") as f:
        json.dump(snapshot, f)
    return snapshot


@pytest.fixture
def mock_momentum_signal():
    """Mock momentum signal."""
    return {
        "signal_date": "2026-02-02",
        "ranked": pd.DataFrame({
            "symbol": ["SXLK.L", "SXLI.L", "SXLU.L", "SXLF.L", "SXLE.L"],
            "momentum_12_1": [0.15, 0.12, 0.10, 0.05, 0.02],
            "rank": [1, 2, 3, 4, 5],
            "target_weight": [0.333, 0.333, 0.333, 0.0, 0.0],
        }),
        "top_sectors": ["SXLK.L", "SXLI.L", "SXLU.L"],
        "target_weights": {
            "SXLK.L": 0.333,
            "SXLI.L": 0.333,
            "SXLU.L": 0.333,
            "SXLF.L": 0.0,
            "SXLE.L": 0.0,
        },
        "top_n": 3,
    }


class TestExecutionEngine:
    """Tests for ExecutionEngine class."""

    def test_engine_initialization(self, config):
        """Test engine initializes correctly."""
        from src.execution.engine import ExecutionEngine

        engine = ExecutionEngine(config, dry_run=True)
        assert engine.dry_run is True
        assert engine.top_n == 3

    def test_engine_dry_run_mode(self, config, sample_snapshot, mock_momentum_signal):
        """Test engine runs in dry-run mode without errors."""
        from src.execution.engine import ExecutionEngine

        with patch("src.execution.engine.generate_momentum_signal") as mock_signal:
            mock_signal.return_value = mock_momentum_signal

            with patch("src.execution.engine.get_current_prices") as mock_prices:
                mock_prices.return_value = {
                    "SXLK.L": 160,
                    "SXLI.L": 75,
                    "SXLU.L": 55,
                }

                engine = ExecutionEngine(config, dry_run=True)
                report = engine.run()

                assert report.execution_mode == "dry_run"
                assert report.signal_date == "2026-02-02"
                # Should have top sectors
                assert len(report.top_sectors) == 3

    def test_engine_blocked_by_kill_switch(self, config, sample_snapshot):
        """Test engine raises when kill switch is active."""
        from src.execution.engine import ExecutionEngine
        from src.execution.risk_manager import KillSwitchActive, RiskManager

        # Activate kill switch
        risk_manager = RiskManager(config)
        risk_manager.activate_kill_switch("Test")

        engine = ExecutionEngine(config, dry_run=True)

        with pytest.raises(KillSwitchActive):
            engine.run()

    def test_engine_logs_signal(self, config, sample_snapshot, mock_momentum_signal):
        """Test engine logs signal to file."""
        from src.execution.engine import ExecutionEngine

        with patch("src.execution.engine.generate_momentum_signal") as mock_signal:
            mock_signal.return_value = mock_momentum_signal

            with patch("src.execution.engine.get_current_prices") as mock_prices:
                mock_prices.return_value = {
                    "SXLK.L": 160,
                    "SXLI.L": 75,
                    "SXLU.L": 55,
                }

                engine = ExecutionEngine(config, dry_run=True)
                engine.run()

                # Check signal was logged
                signals_dir = Path(config["signals"]["log_dir"])
                signal_files = list(signals_dir.glob("*.json"))
                assert len(signal_files) >= 1


class TestFormatExecutionReport:
    """Tests for execution report formatting."""

    def test_format_report_success(self):
        """Test formatting successful report."""
        from src.execution.engine import ExecutionReport, format_execution_report

        report = ExecutionReport(
            timestamp="2026-02-02T16:40:00+00:00",
            execution_mode="dry_run",
            signal_date="2026-02-02",
            rankings=[
                {"symbol": "SXLK.L", "momentum_12_1": 0.15, "rank": 1, "target_weight": 0.333},
            ],
            top_sectors=["SXLK.L", "SXLI.L", "SXLU.L"],
            target_weights={"SXLK.L": 0.333},
            current_weights={"SXLK.L": 0.16},
            trades=[
                {
                    "symbol": "SXLK.L",
                    "action": "BUY",
                    "shares": 50,
                    "price": 160,
                    "trade_value": 8000,
                }
            ],
            validation_result={"valid": True, "total_turnover_pct": 0.08, "reason": "OK"},
            execution_results=[],
            total_equity=100000,
            cash=35000,
            reasoning="Test",
            success=True,
        )

        text = format_execution_report(report)
        assert "EXECUTION REPORT" in text
        assert "DRY_RUN" in text
        assert "SUCCESS" in text
        assert "SXLK.L" in text

    def test_format_report_failure(self):
        """Test formatting failed report."""
        from src.execution.engine import ExecutionReport, format_execution_report

        report = ExecutionReport(
            timestamp="2026-02-02T16:40:00+00:00",
            execution_mode="dry_run",
            signal_date="2026-02-02",
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
            error_message="Connection failed",
        )

        text = format_execution_report(report)
        assert "FAILED" in text
        assert "Connection failed" in text

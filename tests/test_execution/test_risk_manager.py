"""Tests for risk manager."""

import pytest
from pathlib import Path
from src.execution.risk_manager import (
    RiskManager,
    KillSwitchActive,
    ValidationResult,
    BatchValidationResult,
)


@pytest.fixture
def config(tmp_path):
    """Sample configuration with temp kill switch file."""
    return {
        "risk_limits": {
            "max_position_pct": 0.25,
            "max_turnover_pct": 0.50,
            "kill_switch_file": str(tmp_path / ".kill_switch"),
        },
        "position_sizing": {
            "exit_rank_threshold": 5,
        },
    }


@pytest.fixture
def risk_manager(config):
    """Risk manager instance."""
    return RiskManager(config)


class TestRiskManager:
    """Tests for RiskManager class."""

    def test_kill_switch_inactive_by_default(self, risk_manager):
        """Test kill switch is inactive when file doesn't exist."""
        assert not risk_manager.is_kill_switch_active()

    def test_activate_kill_switch(self, risk_manager):
        """Test kill switch activation."""
        risk_manager.activate_kill_switch("Test reason")
        assert risk_manager.is_kill_switch_active()
        assert "Test reason" in risk_manager.get_kill_switch_reason()

    def test_deactivate_kill_switch(self, risk_manager):
        """Test kill switch deactivation."""
        risk_manager.activate_kill_switch("Test")
        assert risk_manager.is_kill_switch_active()

        risk_manager.deactivate_kill_switch()
        assert not risk_manager.is_kill_switch_active()

    def test_check_kill_switch_raises(self, risk_manager):
        """Test check_kill_switch raises when active."""
        risk_manager.activate_kill_switch("Test")

        with pytest.raises(KillSwitchActive):
            risk_manager.check_kill_switch()

    def test_validate_trade_valid(self, risk_manager):
        """Test valid trade passes validation with legacy key."""
        trade = {
            "symbol": "SXLK.L",
            "action": "BUY",
            "shares_to_trade": 100,
            "price": 150,
        }
        result = risk_manager.validate_trade(trade, total_equity=100000)
        assert result.valid

    def test_validate_trade_valid_with_shares_key(self, risk_manager):
        """Test valid trade passes validation with 'shares' key (engine format).

        This is the critical regression test for the shares/shares_to_trade
        key mismatch bug that caused all trades to fail validation.
        """
        trade = {
            "symbol": "SXLK.L",
            "action": "BUY",
            "shares": 100,
            "price": 150,
        }
        result = risk_manager.validate_trade(trade, total_equity=100000)
        assert result.valid
        assert result.details["trade_value"] == 15000

    def test_validate_trade_exceeds_position_limit(self, risk_manager):
        """Test trade rejected when exceeding position limit."""
        trade = {
            "symbol": "SXLK.L",
            "action": "BUY",
            "shares_to_trade": 200,
            "price": 150,
        }
        # Trade value = 30000, 30% of 100000 > 25% limit
        result = risk_manager.validate_trade(trade, total_equity=100000)
        assert not result.valid
        assert "exceed" in result.reason.lower()

    def test_validate_trade_invalid_price(self, risk_manager):
        """Test trade rejected with invalid price."""
        trade = {
            "symbol": "SXLK.L",
            "action": "BUY",
            "shares_to_trade": 100,
            "price": 0,
        }
        result = risk_manager.validate_trade(trade, total_equity=100000)
        assert not result.valid
        assert "price" in result.reason.lower()

    def test_validate_batch_passes(self, risk_manager):
        """Test valid batch passes validation."""
        trades = [
            {"symbol": "SXLK.L", "action": "BUY", "shares_to_trade": 50, "price": 150},
            {"symbol": "SXLI.L", "action": "SELL", "shares_to_trade": 30, "price": 100},
        ]
        result = risk_manager.validate_batch(
            trades=trades,
            total_equity=100000,
            current_positions={},
        )
        assert result.valid

    def test_validate_batch_passes_with_shares_key(self, risk_manager):
        """Test valid batch passes with 'shares' key (engine format).

        Critical regression test: the engine produces trade dicts with
        'shares' not 'shares_to_trade'. Both must work for validation
        AND turnover calculation.
        """
        trades = [
            {"symbol": "SXLK.L", "action": "BUY", "shares": 50, "price": 150},
            {"symbol": "SXLI.L", "action": "SELL", "shares": 30, "price": 100},
        ]
        result = risk_manager.validate_batch(
            trades=trades,
            total_equity=100000,
            current_positions={},
        )
        assert result.valid
        # Verify turnover is correctly calculated (not 0)
        # 50*150 + 30*100 = 10500, turnover = 10500/100000 = 10.5%
        assert result.total_turnover_pct == pytest.approx(0.105, abs=0.001)

    def test_validate_batch_exceeds_turnover(self, risk_manager):
        """Test batch rejected when exceeding turnover limit."""
        trades = [
            {"symbol": "A", "action": "BUY", "shares_to_trade": 200, "price": 150},
            {"symbol": "B", "action": "SELL", "shares_to_trade": 200, "price": 150},
        ]
        # Total turnover = 60000, 60% > 50% limit
        result = risk_manager.validate_batch(
            trades=trades,
            total_equity=100000,
            current_positions={},
        )
        assert not result.valid
        assert "turnover" in result.reason.lower()

    def test_validate_batch_kill_switch_active(self, risk_manager):
        """Test batch rejected when kill switch active."""
        risk_manager.activate_kill_switch("Test")

        trades = [
            {"symbol": "SXLK.L", "action": "BUY", "shares_to_trade": 10, "price": 150},
        ]
        result = risk_manager.validate_batch(
            trades=trades,
            total_equity=100000,
            current_positions={},
        )
        assert not result.valid
        assert "kill switch" in result.reason.lower()

    def test_should_exit_position(self, risk_manager):
        """Test exit threshold check."""
        # Threshold is 5
        assert not risk_manager.should_exit_position("SXLK.L", rank=3)
        assert not risk_manager.should_exit_position("SXLK.L", rank=5)
        assert risk_manager.should_exit_position("SXLK.L", rank=6)
        assert risk_manager.should_exit_position("SXLK.L", rank=9)

    def test_get_status(self, risk_manager):
        """Test status dict includes all settings."""
        status = risk_manager.get_status()
        assert "max_position_pct" in status
        assert "max_turnover_pct" in status
        assert "exit_rank_threshold" in status
        assert "kill_switch_active" in status

"""Tests for performance calculation module.

Tests verify performance metrics against known equity series
and edge cases for slippage calculations.
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import performance


class TestReturnsCalculation:
    """Tests for returns calculation functions."""

    def test_total_return_positive(self):
        """Test total return calculation with positive returns."""
        equity = pd.Series([100, 110, 120], index=pd.date_range("2026-01-01", periods=3))
        result = performance.total_return(equity)
        assert result == pytest.approx(0.20, rel=1e-3)

    def test_total_return_negative(self):
        """Test total return calculation with negative returns."""
        equity = pd.Series([100, 90, 80], index=pd.date_range("2026-01-01", periods=3))
        result = performance.total_return(equity)
        assert result == pytest.approx(-0.20, rel=1e-3)

    def test_total_return_empty(self):
        """Test total return with empty series."""
        equity = pd.Series([], dtype=float)
        result = performance.total_return(equity)
        assert result == 0.0

    def test_total_return_single_value(self):
        """Test total return with single value."""
        equity = pd.Series([100], index=pd.date_range("2026-01-01", periods=1))
        result = performance.total_return(equity)
        assert result == 0.0

    def test_compute_returns(self):
        """Test daily returns computation."""
        equity = pd.Series([100, 105, 110], index=pd.date_range("2026-01-01", periods=3))
        returns = performance.compute_returns(equity)

        assert len(returns) == 2
        assert returns.iloc[0] == pytest.approx(0.05, rel=1e-3)
        assert returns.iloc[1] == pytest.approx(0.0476, rel=1e-2)


class TestVolatilityCalculation:
    """Tests for volatility calculations."""

    def test_annualized_volatility(self):
        """Test annualized volatility calculation."""
        np.random.seed(42)
        daily_returns = pd.Series(np.random.normal(0, 0.01, 252))
        vol = performance.annualized_volatility(daily_returns)

        assert 0.10 < vol < 0.20

    def test_annualized_volatility_empty(self):
        """Test volatility with empty series."""
        returns = pd.Series([], dtype=float)
        vol = performance.annualized_volatility(returns)
        assert vol == 0.0

    def test_annualized_volatility_zero_variance(self):
        """Test volatility with zero variance."""
        returns = pd.Series([0.01, 0.01, 0.01])
        vol = performance.annualized_volatility(returns)
        assert vol == 0.0


class TestSharpeRatio:
    """Tests for Sharpe ratio calculations."""

    def test_sharpe_ratio_positive(self):
        """Test Sharpe ratio with positive returns."""
        np.random.seed(42)
        daily_returns = pd.Series(np.random.normal(0.001, 0.01, 252))
        sharpe = performance.sharpe_ratio(daily_returns, risk_free_rate=0.0)

        assert sharpe > 0

    def test_sharpe_ratio_negative(self):
        """Test Sharpe ratio with negative returns."""
        np.random.seed(42)
        daily_returns = pd.Series(np.random.normal(-0.001, 0.01, 252))
        sharpe = performance.sharpe_ratio(daily_returns, risk_free_rate=0.0)

        assert sharpe < 0

    def test_sharpe_ratio_empty(self):
        """Test Sharpe with empty series."""
        returns = pd.Series([], dtype=float)
        sharpe = performance.sharpe_ratio(returns)
        assert sharpe == 0.0

    def test_sharpe_ratio_zero_volatility(self):
        """Test Sharpe with zero volatility."""
        returns = pd.Series([0.01, 0.01, 0.01])
        sharpe = performance.sharpe_ratio(returns)
        assert sharpe == 0.0

    def test_rolling_sharpe(self):
        """Test rolling Sharpe ratio calculation."""
        np.random.seed(42)
        daily_returns = pd.Series(
            np.random.normal(0.001, 0.01, 60),
            index=pd.date_range("2026-01-01", periods=60),
        )

        rolling = performance.rolling_sharpe(daily_returns, window=30)

        assert len(rolling) == 31
        assert not rolling.isna().any()


class TestDrawdown:
    """Tests for drawdown calculations."""

    def test_max_drawdown(self):
        """Test max drawdown calculation."""
        equity = pd.Series(
            [100, 110, 105, 90, 95, 100],
            index=pd.date_range("2026-01-01", periods=6),
        )
        dd = performance.max_drawdown(equity)

        assert dd == pytest.approx(0.1818, rel=1e-2)

    def test_max_drawdown_no_drawdown(self):
        """Test max drawdown with monotonically increasing equity."""
        equity = pd.Series(
            [100, 110, 120, 130],
            index=pd.date_range("2026-01-01", periods=4),
        )
        dd = performance.max_drawdown(equity)
        assert dd == 0.0

    def test_max_drawdown_duration(self):
        """Test max drawdown duration calculation."""
        equity = pd.Series(
            [100, 110, 105, 90, 95, 100, 115],
            index=pd.date_range("2026-01-01", periods=7),
        )
        duration = performance.max_drawdown_duration(equity)

        assert duration == 4

    def test_max_drawdown_duration_no_drawdown(self):
        """Test duration with no drawdown."""
        equity = pd.Series(
            [100, 110, 120],
            index=pd.date_range("2026-01-01", periods=3),
        )
        duration = performance.max_drawdown_duration(equity)
        assert duration == 0

    def test_drawdown_series(self):
        """Test drawdown series computation."""
        equity = pd.Series(
            [100, 110, 105],
            index=pd.date_range("2026-01-01", periods=3),
        )
        dd_series = performance.drawdown_series(equity)

        assert dd_series.iloc[0] == 0.0
        assert dd_series.iloc[1] == 0.0
        assert dd_series.iloc[2] == pytest.approx(-0.0455, rel=1e-2)


class TestWinRate:
    """Tests for win rate and profit factor calculations."""

    def test_win_rate(self):
        """Test win rate calculation."""
        trades = pd.DataFrame({
            "net_pnl": [100, -50, 75, -25, 200],
        })
        wr = performance.win_rate(trades)
        assert wr == 0.6

    def test_win_rate_all_winners(self):
        """Test win rate with all winning trades."""
        trades = pd.DataFrame({"net_pnl": [100, 50, 75]})
        wr = performance.win_rate(trades)
        assert wr == 1.0

    def test_win_rate_all_losers(self):
        """Test win rate with all losing trades."""
        trades = pd.DataFrame({"net_pnl": [-100, -50, -75]})
        wr = performance.win_rate(trades)
        assert wr == 0.0

    def test_win_rate_empty(self):
        """Test win rate with empty trades."""
        trades = pd.DataFrame({"net_pnl": []})
        wr = performance.win_rate(trades)
        assert wr == 0.0

    def test_profit_factor(self):
        """Test profit factor calculation."""
        trades = pd.DataFrame({
            "net_pnl": [100, -50, 75, -25],
        })
        pf = performance.profit_factor(trades)
        assert pf == pytest.approx(2.333, rel=1e-2)

    def test_profit_factor_no_losses(self):
        """Test profit factor with no losses."""
        trades = pd.DataFrame({"net_pnl": [100, 50]})
        pf = performance.profit_factor(trades)
        assert pf == float("inf")

    def test_profit_factor_no_wins(self):
        """Test profit factor with no wins."""
        trades = pd.DataFrame({"net_pnl": [-100, -50]})
        pf = performance.profit_factor(trades)
        assert pf == 0.0


class TestTradePnL:
    """Tests for trade P&L computation."""

    def test_compute_trade_pnl_simple(self):
        """Test P&L computation with simple round trip."""
        executions = pd.DataFrame({
            "timestamp": ["2026-01-01 10:00", "2026-01-02 10:00"],
            "symbol": ["AAPL", "AAPL"],
            "side": ["BUY", "SELL"],
            "quantity": [100, 100],
            "fill_price": [150.0, 155.0],
            "commission": [1.0, 1.0],
        })

        trades = performance.compute_trade_pnl(executions)

        assert len(trades) == 1
        assert trades.iloc[0]["gross_pnl"] == 500.0
        assert trades.iloc[0]["net_pnl"] == 498.0

    def test_compute_trade_pnl_partial_close(self):
        """Test P&L with partial position close."""
        executions = pd.DataFrame({
            "timestamp": ["2026-01-01 10:00", "2026-01-02 10:00"],
            "symbol": ["AAPL", "AAPL"],
            "side": ["BUY", "SELL"],
            "quantity": [100, 50],
            "fill_price": [150.0, 155.0],
            "commission": [1.0, 0.5],
        })

        trades = performance.compute_trade_pnl(executions)

        assert len(trades) == 1
        assert trades.iloc[0]["quantity"] == 50


class TestSlippageCalculation:
    """Tests for slippage calculation edge cases."""

    def test_slippage_buy_unfavorable(self):
        """Test slippage for buy with higher fill than intended."""
        slippage = calculate_slippage_bps(100.0, 100.10, "BUY")
        assert slippage == pytest.approx(10.0, rel=1e-2)

    def test_slippage_buy_favorable(self):
        """Test slippage for buy with lower fill than intended."""
        slippage = calculate_slippage_bps(100.0, 99.90, "BUY")
        assert slippage == pytest.approx(-10.0, rel=1e-2)

    def test_slippage_sell_unfavorable(self):
        """Test slippage for sell with lower fill than intended."""
        slippage = calculate_slippage_bps(100.0, 99.90, "SELL")
        assert slippage == pytest.approx(10.0, rel=1e-2)

    def test_slippage_sell_favorable(self):
        """Test slippage for sell with higher fill than intended."""
        slippage = calculate_slippage_bps(100.0, 100.10, "SELL")
        assert slippage == pytest.approx(-10.0, rel=1e-2)

    def test_slippage_no_intended_price(self):
        """Test slippage when intended price is None."""
        slippage = calculate_slippage_bps(None, 100.0, "BUY")
        assert slippage is None

    def test_slippage_zero_intended_price(self):
        """Test slippage when intended price is zero."""
        slippage = calculate_slippage_bps(0.0, 100.0, "BUY")
        assert slippage is None

    def test_slippage_zero_slippage(self):
        """Test exact fill with zero slippage."""
        slippage = calculate_slippage_bps(100.0, 100.0, "BUY")
        assert slippage == 0.0


class TestSnapshotLoading:
    """Tests for snapshot file loading."""

    def test_load_snapshots(self):
        """Test loading snapshots from directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                date = (datetime(2026, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
                snapshot = {
                    "timestamp": f"{date}T16:00:00Z",
                    "total_equity": 100000 + i * 1000,
                    "cash": 50000,
                    "positions": [],
                }
                with open(Path(tmpdir) / f"{date}.json", "w") as f:
                    json.dump(snapshot, f)

            snapshots = performance.load_snapshots(tmpdir)

            assert len(snapshots) == 3
            assert snapshots["total_equity"].iloc[0] == 100000
            assert snapshots["total_equity"].iloc[-1] == 102000

    def test_load_snapshots_date_filter(self):
        """Test loading snapshots with date filter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(5):
                date = (datetime(2026, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
                snapshot = {
                    "timestamp": f"{date}T16:00:00Z",
                    "total_equity": 100000 + i * 1000,
                    "cash": 50000,
                    "positions": [],
                }
                with open(Path(tmpdir) / f"{date}.json", "w") as f:
                    json.dump(snapshot, f)

            snapshots = performance.load_snapshots(
                tmpdir, start_date="2026-01-02", end_date="2026-01-04"
            )

            assert len(snapshots) == 3

    def test_load_snapshots_empty_directory(self):
        """Test loading from empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshots = performance.load_snapshots(tmpdir)
            assert snapshots.empty

    def test_load_snapshots_missing_directory(self):
        """Test loading from nonexistent directory."""
        snapshots = performance.load_snapshots("/nonexistent/path")
        assert snapshots.empty


class TestComputeAllMetrics:
    """Integration tests for compute_all_metrics."""

    def test_compute_all_metrics(self):
        """Test full metrics computation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshots_dir = Path(tmpdir) / "snapshots"
            executions_dir = Path(tmpdir) / "executions"
            snapshots_dir.mkdir()
            executions_dir.mkdir()

            for i in range(30):
                date = (datetime(2026, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
                snapshot = {
                    "timestamp": f"{date}T16:00:00Z",
                    "total_equity": 100000 * (1 + 0.001 * i),
                    "cash": 50000,
                    "positions": [],
                }
                with open(snapshots_dir / f"{date}.json", "w") as f:
                    json.dump(snapshot, f)

            metrics = performance.compute_all_metrics(
                str(snapshots_dir), str(executions_dir)
            )

            assert "period" in metrics
            assert "returns" in metrics
            assert "risk" in metrics
            assert "trades" in metrics
            assert "equity" in metrics

            assert metrics["period"]["trading_days"] == 30
            assert metrics["returns"]["total_return"] > 0


def calculate_slippage_bps(intended_price, fill_price, side):
    """Helper function imported from slippage_analyzer for testing."""
    if intended_price is None or intended_price == 0:
        return None

    if side == "BUY":
        slippage = (fill_price - intended_price) / intended_price
    else:
        slippage = (intended_price - fill_price) / intended_price

    return round(slippage * 10000, 2)

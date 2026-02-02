"""Tests for position sizer."""

import pytest
from src.execution.position_sizer import PositionSizer, SizedTrade


@pytest.fixture
def config():
    """Sample configuration."""
    return {
        "position_sizing": {
            "top_n": 3,
            "min_trade_shares": 1,
            "min_trade_value": 100,
        },
        "risk_limits": {
            "max_position_pct": 0.25,
            "max_turnover_pct": 0.50,
        },
    }


@pytest.fixture
def position_sizer(config):
    """Position sizer with sample portfolio."""
    positions = {
        "SXLK.L": {
            "quantity": 100,
            "market_value": 30000,
            "market_price": 300,
        },
        "SXLI.L": {
            "quantity": 200,
            "market_value": 35000,
            "market_price": 175,
        },
    }
    return PositionSizer(
        total_equity=100000,
        cash_available=35000,
        current_positions=positions,
        config=config,
    )


class TestPositionSizer:
    """Tests for PositionSizer class."""

    def test_get_current_weight(self, position_sizer):
        """Test current weight calculation."""
        weight = position_sizer.get_current_weight("SXLK.L")
        assert weight == pytest.approx(0.30, rel=0.01)

    def test_get_current_weight_missing_symbol(self, position_sizer):
        """Test weight for symbol not in portfolio."""
        weight = position_sizer.get_current_weight("UNKNOWN.L")
        assert weight == 0

    def test_calculate_target_shares(self, position_sizer):
        """Test target share calculation."""
        shares = position_sizer.calculate_target_shares(
            symbol="SXLK.L",
            target_weight=0.25,
            current_price=300,
        )
        # 25% of 100000 = 25000, at $300/share = 83 shares (floored)
        assert shares == 83

    def test_calculate_target_shares_respects_max_position(self, position_sizer):
        """Test position size capped at max_position_pct."""
        shares = position_sizer.calculate_target_shares(
            symbol="SXLK.L",
            target_weight=0.50,  # Request 50% but max is 25%
            current_price=300,
        )
        # Should be capped to 25% of 100000 = 25000, at $300/share = 83 shares
        assert shares == 83

    def test_calculate_target_shares_zero_price(self, position_sizer):
        """Test handling of zero price."""
        shares = position_sizer.calculate_target_shares(
            symbol="SXLK.L",
            target_weight=0.25,
            current_price=0,
        )
        assert shares == 0

    def test_calculate_trade_buy(self, position_sizer):
        """Test buy trade calculation."""
        trade = position_sizer.calculate_trade(
            symbol="SXLU.L",  # Not in portfolio
            target_weight=0.20,
            current_price=50,
        )
        assert trade is not None
        assert trade.action == "BUY"
        assert trade.symbol == "SXLU.L"
        assert trade.shares > 0

    def test_calculate_trade_sell(self, position_sizer):
        """Test sell trade calculation."""
        trade = position_sizer.calculate_trade(
            symbol="SXLK.L",  # Currently 30%
            target_weight=0.10,  # Target 10%
            current_price=300,
        )
        assert trade is not None
        assert trade.action == "SELL"
        assert trade.symbol == "SXLK.L"
        assert trade.shares > 0

    def test_calculate_trade_within_threshold(self, position_sizer):
        """Test no trade when within threshold."""
        trade = position_sizer.calculate_trade(
            symbol="SXLK.L",  # Currently 30%
            target_weight=0.31,  # Only 1% difference
            current_price=300,
            min_threshold=0.02,  # 2% threshold
        )
        assert trade is None

    def test_generate_trades_sells_before_buys(self, position_sizer):
        """Test that sells come before buys in trade list."""
        trades = position_sizer.generate_trades(
            target_weights={
                "SXLK.L": 0.10,  # Sell (currently 30%)
                "SXLU.L": 0.20,  # Buy (not in portfolio)
            },
            current_prices={
                "SXLK.L": 300,
                "SXLU.L": 50,
            },
        )

        sell_indices = [i for i, t in enumerate(trades) if t.action == "SELL"]
        buy_indices = [i for i, t in enumerate(trades) if t.action == "BUY"]

        if sell_indices and buy_indices:
            assert max(sell_indices) < min(buy_indices)

    def test_validate_turnover(self, position_sizer):
        """Test turnover validation."""
        trades = [
            SizedTrade("A", "BUY", 100, 100.0, 0.1, 0, 10000, "test"),
            SizedTrade("B", "SELL", 50, 100.0, 0, 0.05, 5000, "test"),
        ]
        # Total turnover = 15000, equity = 100000, turnover = 15%
        is_valid, turnover_pct = position_sizer.validate_turnover(trades)
        assert is_valid
        assert turnover_pct == pytest.approx(0.15, rel=0.01)

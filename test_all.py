#!/usr/bin/env python3
"""Quick test script to verify all fixes work with live IBKR connection."""

import sys
from pathlib import Path

def test_pull():
    """Test pulling executions from IBKR."""
    print("\n" + "="*50)
    print("TEST 1: Pull Executions from IBKR")
    print("="*50)

    from src.execution_logger import IBKRConnection, load_config

    config = load_config()

    with IBKRConnection(config) as ib:
        print(f"✓ Connected to IBKR")

        # Test account values
        account_values = ib.ib.accountValues()
        print(f"✓ Got {len(account_values)} account values")

        # Test positions
        positions = ib.ib.positions()
        print(f"✓ Got {len(positions)} positions")

        # Test fills
        fills = ib.ib.fills()
        print(f"✓ Got {len(fills)} fills today")

    print("✓ Connection closed cleanly")
    return True


def test_snapshot():
    """Test portfolio snapshot with market prices."""
    print("\n" + "="*50)
    print("TEST 2: Portfolio Snapshot (Market Prices)")
    print("="*50)

    from src.execution_logger import IBKRConnection, get_portfolio_snapshot, load_config

    config = load_config()

    with IBKRConnection(config) as ib:
        snapshot = get_portfolio_snapshot(ib.ib)

        print(f"✓ Snapshot timestamp: {snapshot['timestamp']}")
        print(f"✓ Total equity: ${snapshot['total_equity']:,.2f}")
        print(f"✓ Cash balance: ${snapshot['cash']:,.2f}")

        print(f"\nPositions ({len(snapshot['positions'])}):")
        for pos in snapshot['positions'][:5]:  # Show first 5
            print(f"  {pos['symbol']}: {pos['quantity']} @ ${pos['market_price']:.2f} (source: {pos.get('price_source', 'unknown')})")

        if len(snapshot['positions']) > 5:
            print(f"  ... and {len(snapshot['positions']) - 5} more")

    return True


def test_dashboard_security():
    """Test dashboard has security headers."""
    print("\n" + "="*50)
    print("TEST 3: Dashboard Security Headers")
    print("="*50)

    from src.dashboard import create_app
    from src.execution_logger import load_config

    config = load_config()
    app = create_app(config)

    # Check SECRET_KEY is set
    assert app.config.get("SECRET_KEY"), "SECRET_KEY not configured!"
    print("✓ SECRET_KEY configured")

    # Test security headers by making a test request
    with app.test_client() as client:
        response = client.get('/')
        headers = dict(response.headers)

        assert 'X-Content-Type-Options' in headers, "Missing X-Content-Type-Options"
        assert 'X-Frame-Options' in headers, "Missing X-Frame-Options"
        print("✓ X-Content-Type-Options header present")
        print("✓ X-Frame-Options header present")
        print("✓ Security headers working")

    return True


def test_performance():
    """Test performance calculations with edge cases."""
    print("\n" + "="*50)
    print("TEST 4: Performance Calculations")
    print("="*50)

    import pandas as pd
    import numpy as np
    from src import performance

    # Normal case
    dates = pd.date_range('2026-01-01', periods=30, freq='D')
    equity = pd.Series(np.cumsum(np.random.randn(30) * 100) + 100000, index=dates)

    print(f"✓ Total return: {performance.total_return(equity)*100:.2f}%")
    print(f"✓ Max drawdown: {performance.max_drawdown(equity)*100:.2f}%")

    # Edge case: flat equity (division by zero test)
    flat_equity = pd.Series([100000, 100000, 100000], index=dates[:3])
    dd = performance.max_drawdown(flat_equity)
    print(f"✓ Flat equity max drawdown: {dd*100:.2f}% (should be 0)")

    dd_series = performance.drawdown_series(flat_equity)
    print(f"✓ Drawdown series for flat equity: {dd_series.values}")

    return True


def test_stats():
    """Test stats command."""
    print("\n" + "="*50)
    print("TEST 5: Stats Command")
    print("="*50)

    from src import performance
    from src.execution_logger import load_config

    config = load_config()
    snapshots_dir = config["paths"]["snapshots"]

    # Try to load any existing snapshots
    snapshots = performance.load_snapshots(snapshots_dir)

    if snapshots.empty:
        print("⚠ No snapshots found - run 'python main.py snapshot' first")
        return True

    equity = performance.compute_equity_curve(snapshots)
    returns = performance.compute_returns(equity)

    print(f"✓ Loaded {len(snapshots)} snapshots")
    print(f"✓ Total return: {performance.total_return(equity)*100:.2f}%")
    print(f"✓ Sharpe ratio: {performance.sharpe_ratio(returns):.2f}")
    print(f"✓ Max drawdown: {performance.max_drawdown(equity)*100:.2f}%")

    return True


def main():
    print("="*50)
    print("LIVE TRADING SYSTEM - TEST SUITE")
    print("="*50)
    print("Make sure IBKR TWS/Gateway is running!")

    tests = [
        ("IBKR Connection", test_pull),
        ("Portfolio Snapshot", test_snapshot),
        ("Dashboard Security", test_dashboard_security),
        ("Performance Calcs", test_performance),
        ("Stats Command", test_stats),
    ]

    results = []
    for name, test_func in tests:
        try:
            test_func()
            results.append((name, "✓ PASSED"))
        except Exception as e:
            results.append((name, f"✗ FAILED: {e}"))
            print(f"\n✗ FAILED: {e}")

    print("\n" + "="*50)
    print("TEST RESULTS SUMMARY")
    print("="*50)
    for name, result in results:
        print(f"{name}: {result}")

    passed = sum(1 for _, r in results if "PASSED" in r)
    print(f"\n{passed}/{len(tests)} tests passed")

    return passed == len(tests)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

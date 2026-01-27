# Strategy Documentation

## Overview

This system implements a **cross-sectional momentum** strategy on UK-listed sector ETFs, designed to capture the well-documented momentum anomaly in a systematic, rules-based manner.

## Strategy Summary

| Parameter | Value |
|-----------|-------|
| Strategy Type | Cross-sectional momentum |
| Signal | 12-1 momentum (Jegadeesh-Titman) |
| Universe | 9 UK UCITS sector ETFs |
| Selection | Top 3 sectors by momentum |
| Weighting | Equal weight (33.3% each) |
| Rebalance | Monthly, 1st trading day |

---

## Academic Foundation

### The Momentum Anomaly

Momentum is one of the most robust and persistent anomalies in financial markets. Assets that have performed well in the recent past tend to continue performing well in the near future, while underperformers continue to underperform.

### Key Papers

1. **Jegadeesh & Titman (1993)** - "Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency"
   - Documented 3-12 month momentum effect in US stocks
   - Found that 12-month formation period with 1-month skip produces strong results
   - Returns not explained by systematic risk

2. **Moskowitz & Grinblatt (1999)** - "Do Industries Explain Momentum?"
   - Found that industry momentum is a significant driver of stock momentum
   - Sector/industry rotation captures much of the momentum premium
   - Supports our sector-level approach

3. **Asness, Moskowitz & Pedersen (2013)** - "Value and Momentum Everywhere"
   - Documented momentum across multiple asset classes globally
   - Found momentum works in equities, bonds, currencies, and commodities
   - Effect is robust and economically significant

4. **Fama & French (2012)** - "Size, Value, and Momentum in International Stock Returns"
   - Confirmed momentum effect in international markets
   - Present in Europe, Japan, and Asia Pacific

### Why 12-1 Momentum?

The "12-1" formulation means:
- **12 months**: Look at returns over the past 12 months
- **Skip 1 month**: Exclude the most recent month

**Rationale for skipping the most recent month:**
- Short-term reversal effect: Assets that performed well in the very recent past (1 month) tend to reverse
- This reversal contaminates the momentum signal
- Skipping it provides cleaner momentum exposure

---

## Universe Selection

### Why Sector ETFs?

1. **Diversification**: Each ETF holds dozens of stocks, reducing idiosyncratic risk
2. **Liquidity**: ETFs are highly liquid with tight bid-ask spreads
3. **Simplicity**: 9 positions maximum, easy to manage
4. **Cost efficiency**: No individual stock trading costs
5. **Tax efficiency**: UK UCITS ETFs have favorable tax treatment

### Why UK-Listed UCITS?

1. **Regulatory compliance**: UCITS funds meet EU/UK regulatory standards
2. **Tax efficiency**: No US dividend withholding issues
3. **Currency**: Denominated in GBP, avoiding FX exposure
4. **Accessibility**: Available on LSE for UK investors

### ETF Universe

| Ticker | Sector | Full Name | TER |
|--------|--------|-----------|-----|
| SXLK.L | Technology | SPDR S&P US Technology Select Sector UCITS ETF | 0.15% |
| SXLF.L | Financials | SPDR S&P US Financials Select Sector UCITS ETF | 0.15% |
| SXLE.L | Energy | SPDR S&P US Energy Select Sector UCITS ETF | 0.15% |
| SXLV.L | Health Care | SPDR S&P US Health Care Select Sector UCITS ETF | 0.15% |
| SXLY.L | Consumer Discretionary | SPDR S&P US Consumer Discretionary Select Sector UCITS ETF | 0.15% |
| SXLP.L | Consumer Staples | SPDR S&P US Consumer Staples Select Sector UCITS ETF | 0.15% |
| SXLI.L | Industrials | SPDR S&P US Industrials Select Sector UCITS ETF | 0.15% |
| SXLB.L | Materials | SPDR S&P US Materials Select Sector UCITS ETF | 0.15% |
| SXLU.L | Utilities | SPDR S&P US Utilities Select Sector UCITS ETF | 0.15% |

**Note**: These are US sector exposures via UK-listed UCITS wrappers, providing US equity exposure without US tax complications.

---

## Signal Construction

### Step 1: Calculate 12-Month Return

For each ETF, calculate the cumulative return over the past 12 months:

```
R_12m = (P_today / P_12_months_ago) - 1
```

### Step 2: Skip Most Recent Month

Exclude the most recent month's return:

```
R_12_1 = (P_1_month_ago / P_13_months_ago) - 1
```

This is equivalent to:
```
R_12_1 = (1 + R_12m) / (1 + R_1m) - 1
```

### Step 3: Rank Sectors

Rank all 9 sectors by their 12-1 momentum score, from highest to lowest.

### Step 4: Select Top N

Select the top 3 sectors (configurable via `--top-n` flag).

### Step 5: Equal Weight

Assign equal weight to selected sectors:
- Top 3: 33.3% each
- Remaining 6: 0%

---

## Rebalancing Rules

### Timing

- **Frequency**: Monthly
- **Day**: 1st trading day of each month
- **Time**: Execute during market hours (08:00-16:30 LSE)

### Execution

1. Generate new momentum signal
2. Compare current portfolio to target weights
3. Calculate required trades
4. Execute sells first (generate cash)
5. Execute buys with available cash

### Threshold

A minimum weight difference threshold (default: 2%) prevents unnecessary trading:
- If |target_weight - current_weight| < 2%, skip the trade
- Reduces transaction costs and slippage

### No Intra-Month Trading

The strategy does NOT trade intra-month. Positions are held until the next monthly rebalance regardless of performance. This:
- Reduces transaction costs
- Avoids overtrading
- Maintains systematic discipline

---

## Risk Management

### Position Limits

- Maximum 3 positions at any time
- Each position limited to ~33% of portfolio
- Provides natural diversification

### Drawdown

- No explicit stop-loss on individual positions
- Portfolio-level drawdown monitoring via dashboard
- Historical momentum strategies can have significant drawdowns (20-30%)

### Liquidity

All ETFs in the universe have:
- Daily volume > £1M
- Bid-ask spread < 0.1%
- No liquidity constraints for typical portfolio sizes

### What This Strategy Does NOT Do

- **No leverage**: Long-only, no margin
- **No shorting**: Cannot short ETFs in this implementation
- **No derivatives**: No options or futures overlays
- **No market timing**: Always fully invested in top 3 sectors

---

## Expected Performance Characteristics

Based on academic research and historical backtests:

| Metric | Expected Range |
|--------|----------------|
| Annual Return | 8-15% |
| Annual Volatility | 15-20% |
| Sharpe Ratio | 0.4-0.8 |
| Max Drawdown | 20-35% |
| Turnover | ~50% annual |

**Important**: Past performance does not guarantee future results. Momentum strategies can underperform for extended periods.

### When Momentum Works

- Trending markets
- Low correlation regimes
- Normal volatility environments

### When Momentum Struggles

- Market reversals (momentum crash)
- High volatility / crisis periods
- Mean-reverting markets

---

## Compliance Notes

### Permissible Instruments

This system is designed for:
- ✅ Equities
- ✅ ETFs
- ✅ Futures (with modification)
- ✅ Commodities
- ✅ Crypto spot

### Excluded Instruments

The following are explicitly excluded:
- ❌ Bonds (interest-based)
- ❌ CFDs (interest-based margin)
- ❌ Margin trading
- ❌ Options (for this implementation)

---

## Strategy Limitations

1. **Historical bias**: Strategy is based on historical patterns that may not persist
2. **Crowding**: Momentum is a popular strategy, potentially reducing future returns
3. **Transaction costs**: Not fully accounted for in signal generation
4. **Tax**: Strategy does not optimize for tax efficiency
5. **Slippage**: Execution quality impacts returns

---

## References

- Jegadeesh, N., & Titman, S. (1993). Returns to buying winners and selling losers: Implications for stock market efficiency. *The Journal of Finance*, 48(1), 65-91.

- Moskowitz, T. J., & Grinblatt, M. (1999). Do industries explain momentum?. *The Journal of Finance*, 54(4), 1249-1290.

- Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013). Value and momentum everywhere. *The Journal of Finance*, 68(3), 929-985.

- Fama, E. F., & French, K. R. (2012). Size, value, and momentum in international stock returns. *Journal of Financial Economics*, 105(3), 457-472.

- Carhart, M. M. (1997). On persistence in mutual fund performance. *The Journal of Finance*, 52(1), 57-82.

# Trade Analyzer

### Institutional-Grade Weekly Trading Algorithm for NSE

A deterministic, probabilistic signal-selection engine designed to identify momentum stocks with favorable risk-reward profiles while maintaining strict capital preservation protocols.

## Philosophy

**The goal is NOT "maximum profit every week."**

The true objective is to generate a small set of statistically asymmetric bets each week where:
- Expected value (EV) > 0
- Downside is pre-defined
- Upside is convex

**What this system CAN do:**
- Generate 15-30% annual returns with proper execution
- Provide structured, unemotional decision-making
- Scale with capital (liquid stocks only)
- Compound over long periods (years)

**What this system CANNOT do:**
- Predict the market
- Avoid all drawdowns (expect 15-25% max drawdown)
- Generate consistent weekly profits (variance is high)
- Work in all market regimes (that's why we have a regime gate)

## System Overview

The framework operates on a **weekend analysis, weekday execution** model, generating 3-7 high-probability trade setups every week.

### Pipeline Architecture

```
REGIME GATE (Can stop entire pipeline if Risk-Off)
    ↓
Universe (~500) → Sanitization (~350) → Factor Scoring (~80)
    → Setup Detection (~20) → Risk Geometry (~10)
    → Correlation Filter (~7) → Portfolio (3-7 positions)
```

| Stage | Name | Output |
|-------|------|--------|
| 0 | Regime Gate | Risk-On / Choppy / Risk-Off |
| 1 | Universe Sanitization | ~350 liquid, tradable stocks |
| 2 | Factor Scoring | ~80 momentum + consistency qualified |
| 3 | Setup Detection | ~20 actionable setups |
| 4 | Risk Geometry | ~10 asymmetric opportunities |
| 5 | Portfolio Construction | 3-7 final positions |

## Realistic Expectations

| Metric | Target Range |
|--------|--------------|
| Win Rate | 50-55% |
| Average Winner | 1.2R |
| Average Loser | 1.1R |
| Expectancy (after costs) | 0.05-0.10R per trade |
| Annual Return | 15-30% |
| Max Drawdown | 15-25% |
| Weeks with "No Trade" | 10-20% |

**Transaction Costs (India):** ~0.27% round-trip + 15% STCG tax on profits

## Key Filters

### Regime Gate (MOST CRITICAL)
- **Risk-On:** Full system active (3-7 trades)
- **Choppy:** Pullbacks only, 50% position size (1-3 trades)
- **Risk-Off:** No new positions (0 trades)

### Universe Selection
- Nifty 200/500 constituents + F&O-eligible stocks
- Average daily turnover ≥ ₹5 crores
- Market cap ≥ ₹1,000 crores
- Circuit hits ≤ 2 in last 30 days
- Trading days ≥ 90% in last 6 months

### Momentum Filters
- Within 10% of 52-week high
- Price > 50-DMA > 200-DMA (all rising)
- Relative strength vs Nifty 50 ≥ +10% (3M & 6M)

### Weekly Consistency (with Statistical Significance)
- Positive weeks ≥ 55%
- Must pass binomial significance test (p < 0.10)
- Weekly std dev: 3-7% (ideal range)

### Risk Management
- Fixed fractional: 1.5% risk per trade (regime-adjusted)
- Reward:Risk ratio ≥ 2:1 (Risk-On) or 2.5:1 (Choppy)
- Stop-loss: tighter of swing low or 2×ATR
- Max 3 stocks per sector
- Max correlation 0.70 between positions
- 20-30% cash reserve

## Installation

**Prerequisites:** [UV](https://github.com/astral-sh/uv) and [Make](https://gnuwin32.sourceforge.net/packages/make.htm)

```bash
git clone <repository-url>
cd trade_analyzer
uv sync
```

## Usage

```bash
# Run the full analysis pipeline
make dev

# Run with production settings
make prod
```

## Development

```bash
make test      # Run tests
make cov       # Run tests with coverage
make check     # Lint code
make format    # Format code
make type      # Type check
make allci     # Run all CI steps
make doc       # Serve documentation
```

## System Output

Every run produces:

1. **Regime Assessment** - Risk-On / Choppy / Risk-Off with confidence
2. **Trade Sheets** - Per-stock thesis, entry/stop logic, gap contingency
3. **Portfolio View** - Total risk deployed, sector exposure, cash reserve
4. **Order Instructions** - Specific entry zones, stops, targets

### Example Trade Setup

```
═══════════════════════════════════════════════════════════════
 RELIANCE INDUSTRIES (RELIANCE.NS)
═══════════════════════════════════════════════════════════════
 Setup Type: PULLBACK
 Sector: Energy

 ENTRY
 Zone: ₹2,450 - ₹2,470
 Trigger: Bounce from 20-DMA with bullish candle

 RISK MANAGEMENT
 Stop Loss: ₹2,390 (below swing low)
 Risk/Share: ₹60-80 (2.5-3.2%)

 TARGETS
 Target 1: ₹2,550 (R:R 2:1)
 Target 2: ₹2,650 (R:R 3:1)

 POSITION SIZING
 Shares: 200
 Capital: ₹4,90,000
 Risk Amount: ₹15,000 (1.5% of portfolio)

 GAP CONTINGENCY
 If Monday open < ₹2,390: SKIP
 If Monday open < ₹2,450: ENTER_AT_OPEN
 If Monday open > ₹2,520: SKIP - Don't chase
═══════════════════════════════════════════════════════════════
```

## Weekly Workflow

| Day | Activity |
|-----|----------|
| Weekend | Run full analysis pipeline |
| Monday AM | Review gaps, execute valid setups |
| Mon-Thu | Monitor positions, trail stops on winners |
| Friday | Book profits, weekly performance review |

## Health Monitoring

The system includes built-in health checks:

| Health Score | Action |
|--------------|--------|
| ≥ 70 | Continue normally |
| 50-70 | Reduce sizes, review parameters |
| 30-50 | Paper trade only, investigate |
| < 30 | Stop trading, full system review |

**Drawdown Limits:**
- Weekly > 5%: Pause new trades
- Monthly > 10%: Reduce size 50%
- Total > 20%: Stop system, review

## Documentation

See the `docs/` folder for:
- [Implementation Plan](docs/implementation_plan.md) - Detailed development guide with code templates

Run `make doc` to serve the documentation locally.

## Data Sources

| Source | Use Case | Cost |
|--------|----------|------|
| yfinance | OHLCV data (.NS suffix) | Free |
| NSE Website | Index constituents, F&O list | Free |
| Screener.in | Fundamental data | Free tier |
| India VIX | Volatility data | Free |

## Key Insights

1. **Regime Gate prevents most drawdowns** - Not trading in bad environments is more important than finding good trades.

2. **"No trade" is a valid output** - Don't force trades to meet quotas. Selection discipline is the edge.

3. **Statistical significance matters** - 52 weeks is a small sample. Test that consistency isn't just luck.

4. **Monday gaps are the execution killer** - Always have gap contingency plans.

5. **Transaction costs eat small edges** - ~0.27% round-trip means you need real edge to profit.

6. **System decay is real** - Monitor health metrics from day 1. Edges diminish over time.

## License

MIT

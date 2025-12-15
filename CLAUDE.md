# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Trade Analyzer is an institutional-grade weekly trading algorithm for NSE (National Stock Exchange of India). It's a rules-based system that operates on a **weekend analysis, weekday execution** model, generating 3-7 high-probability trade setups every week.

The system progressively filters ~500 stocks down to 3-7 high-conviction trades through multiple stages of analysis.

## Build & Development Commands

This project uses UV for Python/dependency management and Make for task running.

- `make dev` - Run the package in development mode
- `make test` - Run tests with pytest
- `make cov` - Run tests with coverage report
- `make check` - Lint code with Ruff (staged files only)
- `make format` - Format code with Ruff (staged files only)
- `make type` - Type check with ty (staged files only)
- `make allci` - Run all CI steps (check, format, type, cov)
- `make doc` - Serve documentation locally with MkDocs
- `make build` - Build package wheel with uv
- `make publish` - Publish to PyPI

To run a single test: `uv run pytest tests/test_main.py::test_function_name -v`

## Critical System Insights

### Realistic Expectations

| Metric | Optimistic | Realistic |
|--------|------------|-----------|
| Win Rate | 55-60% | 50-55% |
| Average Win | 1.5R | 1.2R |
| Average Loss | 1.0R | 1.1R |
| EV per Trade (gross) | 0.44R | 0.11R |
| EV per Trade (net) | 0.35R | 0.05-0.10R |
| Annual Return | 50%+ | 15-30% |
| Max Drawdown | 10% | 15-25% |

### Transaction Costs (India)

```python
# Round-trip costs for ₹1,00,000 trade
STT (0.1% buy + 0.1% sell) = ₹200
Brokerage (discount broker) = ₹40
GST on brokerage = ₹7
Exchange + SEBI fees = ₹7
Stamp duty = ₹15
# Total: ~₹270 (0.27%)
# Plus 15% STCG tax on profits

# CRITICAL: Need >0.2R gross per trade just to break even
```

### Where the Edge Actually Comes From

1. **Regime Awareness** - Not trading in Risk-Off environments
2. **Selection Discipline** - "No trade" is a valid output
3. **Risk Management** - Surviving drawdowns to compound
4. **Consistency** - Running the system for years, not weeks

## Architecture

### Directory Structure
```
src/trade_analyzer/
├── pipeline/                    # Multi-stage filtering pipeline
│   ├── regime.py               # CRITICAL: Market regime gate
│   ├── universe.py             # Universe sanitization
│   ├── factors.py              # Factor scoring engine
│   ├── setups.py               # Technical setup detection
│   ├── risk.py                 # Risk geometry filter
│   └── portfolio.py            # Portfolio construction
├── data/
│   ├── providers/              # NSE, yfinance, screener adapters
│   ├── cache.py                # Local caching layer
│   └── validation.py           # Data quality checks
├── models/                     # Dataclasses for all entities
├── indicators/                 # Technical indicator calculations
├── execution/                  # Gap handling, order generation
├── monitoring/                 # Health metrics, trade tracking
├── output/                     # Report generation
└── utils/
tests/
docs/
```

### Pipeline Flow

```
REGIME GATE (FIRST - Can stop entire pipeline)
    ↓ if Risk-Off: OUTPUT EMPTY PORTFOLIO
    ↓ if Risk-On/Choppy: Continue
Universe (~500) → Sanitization (~350) → Factor Scoring (~80)
    → Setup Detection (~20) → Risk Geometry (~10)
    → Correlation Filter (~7) → Portfolio (3-7 positions)
```

## Key Formulas & Thresholds

### Regime Assessment (MOST CRITICAL)

```python
class RegimeState(Enum):
    RISK_ON = "risk_on"      # Full system active
    CHOPPY = "choppy"        # Pullbacks only, 50% size
    RISK_OFF = "risk_off"    # NO NEW POSITIONS

# Regime indicators (equal 25% weights)
# 1. Trend: Nifty vs 20/50/200 DMA, MA slopes
# 2. Breadth: % stocks above 200 DMA
# 3. Volatility: India VIX level and trend
# 4. Leadership: Cyclicals vs Defensives spread

# Position multiplier
def position_multiplier(risk_on_prob: float) -> float:
    if risk_on_prob > 0.70: return 1.0
    elif risk_on_prob > 0.50: return 0.7
    elif risk_off_prob > 0.50: return 0.0  # NO TRADES
    else: return 0.5
```

### Universe Filters

```python
# Liquidity
avg_daily_turnover >= 5_00_00_000  # ₹5 crores

# Market cap
market_cap >= 1000_00_00_000  # ₹1,000 crores

# Circuit filter
circuit_hits_30d <= 2

# Trading days
trading_days_pct >= 0.90  # 90% of days
```

### Momentum Filters

```python
# 52-week high proximity
(high_52w - close) / high_52w <= 0.10  # Within 10%

# MA alignment
close > sma_50 > sma_200  # All must be true
slope_50dma > 0  # Rising
slope_200dma > 0  # Rising

# Relative strength vs Nifty 50
stock_return_3m >= nifty_return_3m + 0.10  # +10pp
stock_return_6m >= nifty_return_6m + 0.10  # +10pp
```

### Weekly Consistency (WITH STATISTICAL SIGNIFICANCE)

```python
from scipy import stats

# Weekly return
weekly_return = (close_friday / close_prev_friday) - 1

# Metrics (52-week lookback)
pct_positive_weeks >= 0.55  # Lowered for statistical validity

# CRITICAL: Statistical significance test
p_value = stats.binom_test(positive_weeks, 52, 0.50, alternative='greater')
is_significant = p_value < 0.10  # 90% confidence

# If not significant, reject stock (could be noise)
```

### Risk Management

```python
# Stop-loss (tighter of two methods)
stop_swing = recent_swing_low * 0.99
stop_atr = entry - (2 * atr_14)
stop_loss = max(stop_swing, stop_atr)  # Higher = tighter

# Position sizing (regime-adjusted)
base_risk = capital * 0.015  # 1.5%
adjusted_risk = base_risk * regime.position_multiplier()
shares = int(adjusted_risk / (entry - stop_loss))

# Reward:Risk requirement
min_rr_ratio = 2.0  # In Risk-On
min_rr_ratio = 2.5  # In Choppy

# Max stop distance
max_stop_pct = 0.07  # 7%
```

### Monday Gap Handling

```python
@dataclass
class GapContingency:
    # If Monday open < stop_loss
    action_gap_through_stop: str = "SKIP"

    # If Monday open < entry_zone but > stop
    action_small_gap_against: str = "ENTER_AT_OPEN"

    # If Monday open > entry_zone * 1.02
    action_gap_above_entry: str = "SKIP - Don't chase"
```

## Key Data Models

```python
@dataclass
class RegimeAssessment:
    state: RegimeState
    risk_on_prob: float
    choppy_prob: float
    risk_off_prob: float
    confidence: float
    indicators: dict
    timestamp: datetime

@dataclass
class ConsistencyScore:
    pct_positive_weeks: float
    pct_weeks_above_3pct: float
    avg_weekly_return: float
    weekly_std_dev: float
    worst_week: float
    sharpe_like_ratio: float
    is_statistically_significant: bool  # CRITICAL
    p_value: float
    composite_score: float

@dataclass
class TradeSetup:
    stock: Stock
    setup_type: Literal['pullback', 'breakout', 'retest']
    entry_zone: tuple[float, float]
    stop_loss: float
    stop_logic: str
    target_1: float
    target_2: float
    reward_risk_ratio: float
    thesis: str
    gap_contingency: str
    invalidation_conditions: list[str]

@dataclass
class SystemHealth:
    win_rate_12w: float
    win_rate_52w: float
    expectancy_12w: float
    avg_slippage: float
    current_drawdown: float

    def health_score(self) -> float:
        """0-100, <50 = concerning, <30 = stop trading"""

    def recommended_action(self) -> str:
        """CONTINUE / REDUCE / PAUSE / STOP"""
```

## Technical Setup Types

### Type A: Trend Pullback (Primary)
- Stock in uptrend (higher highs/lows)
- Pullback 3-10% to rising 20/50 DMA
- Volume contracting during pullback
- Entry: Near MA, Stop: Below swing low

### Type B: Consolidation Breakout
- Sideways 3-8 weeks, range ≤12%
- Declining volume during consolidation
- Breakout with volume >1.5x average
- Entry: At breakout, Stop: Below consolidation low

### Type C: Breakout Retest
- Breakout 1-3 weeks ago
- Retesting breakout zone
- Holding above former resistance
- Lower volume on retest

## Configuration

- Python 3.13+ required
- Build system: uv_build
- Linting/formatting: Ruff (target py313)
- Type checking: ty
- Testing: pytest with pytest-cov
- Pre-commit hooks configured

## Domain Rules

### Portfolio Constraints
- Max risk per trade: 1.5% (regime-adjusted)
- Max 3 stocks per sector
- Max 25% sector exposure
- Cash reserve: 20-30%
- Max 10 positions (Risk-On), 5 (Choppy), 0 (Risk-Off)
- Max correlation between positions: 0.70

### Hard Rejections
- Stop > 7% from entry
- Reward:Risk < 2.0 (Risk-On) or < 2.5 (Choppy)
- Not statistically significant consistency
- Circuit-prone stocks (>2 hits/month)
- Low liquidity (< ₹5 Cr turnover)
- Gapped through stop on Monday

### Drawdown Controls
- Weekly drawdown > 5%: Pause new trades
- Monthly drawdown > 10%: Reduce size 50%
- Total drawdown > 20%: Stop system, review

### System Health Protocol
- Score ≥ 70: Continue normally
- Score 50-70: Reduce sizes, review parameters
- Score 30-50: Paper trade only
- Score < 30: Stop trading, full system review

## Common Pitfalls to Avoid

1. **Survivorship Bias** - Today's Nifty 500 only contains survivors. Backtests overstate returns by 2-5% annually.

2. **Small Sample Size** - 52 weeks = 52 data points. A 60% win rate could be 50% true rate with lucky variance. Always test statistical significance.

3. **Monday Gaps** - Weekend analysis assumes Friday close. Monday can gap 2-5% either way. Always have gap contingency.

4. **Transaction Costs** - ~0.27% round-trip + 15% tax on profits. Small edges get killed by costs.

5. **Regime Blindness** - Most retail systems ignore regime. Trading in Risk-Off destroys capital.

6. **Forcing Trades** - "No trade" is valid. Don't lower standards to meet quotas.

7. **System Decay** - Edges decay over time. Monitor health metrics from day 1.

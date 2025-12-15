# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Trade Analyzer is an institutional-grade weekly trading algorithm for NSE (National Stock Exchange of India). It's a rules-based system that operates on a **weekend analysis, weekday execution** model, generating 3-7 high-probability trade setups every week.

The system progressively filters ~500 stocks down to 3-7 high-conviction trades through multiple stages of analysis.

## Current Implementation Status

### Completed Components

1. **MongoDB Database Layer** (`src/trade_analyzer/db/`)
   - Connection management with singleton pattern
   - Pydantic models for all document types
   - Repository pattern for data access (stocks, trades, setups, regime)
   - Connected to DigitalOcean MongoDB Atlas

2. **Upstox Data Provider** (`src/trade_analyzer/data/providers/`)
   - Fetches NSE equity instruments from Upstox API
   - Fetches MTF (Margin Trading Facility) instruments
   - Transforms and stores in MongoDB

3. **Streamlit UI** (`src/trade_analyzer/ui/`)
   - Dashboard with universe stats
   - Paginated stock lists (NSE EQ and MTF)
   - Refresh button to update trading universe
   - Settings page

4. **Temporal Workflows** (`src/trade_analyzer/workflows/`, `src/trade_analyzer/activities/`)
   - Universe refresh workflow with retry policies
   - Activities for fetching and saving instruments
   - Worker configuration for Temporal Cloud

5. **Docker Infrastructure**
   - Multi-stage Dockerfile for optimized builds
   - docker-compose.yml for orchestration
   - Support for both local Temporal and Temporal Cloud

6. **Quality Scoring System** (`src/trade_analyzer/activities/universe_setup.py`)
   - Tier-based scoring: A (MTF + Nifty 50), B (MTF + Nifty 100), C (MTF + Nifty 500), D (MTF only)
   - Liquidity tier calculation based on index membership
   - UniverseSetupWorkflow for orchestrating quality enrichment

### Implementation Plan

For detailed development tracking, decisions, and roadmap, see **[docs/implementation_plan.md](docs/implementation_plan.md)**.

### Cloud Services (Always Connected)

All credentials are configured in `src/trade_analyzer/config.py`. No environment variables needed.

**MongoDB (DigitalOcean)**
```
Host: mongodb+srv://db-trading-setup-4aad9e87.mongo.ondigitalocean.com
Database: trade_analysis
```

**Temporal Cloud**
```
Address: ap-south-1.aws.api.temporal.io:7233
Namespace: trade-discovere.y8vfp
Region: Asia Pacific (Mumbai)
```

## Commands

### Run Locally
```bash
make ui        # Start Streamlit UI (localhost:8501)
make worker    # Start Temporal worker
make refresh   # Trigger universe refresh workflow
```

### Run in Docker
```bash
make up        # Start UI + Worker in Docker
make down      # Stop all services
make logs      # View logs
```

### Development
```bash
make test      # Run tests
make cov       # Run tests with coverage
make check     # Lint with Ruff
make format    # Format with Ruff
make allci     # Run all CI steps
```

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

### Current Directory Structure (Implemented)
```
src/trade_analyzer/
├── config.py                   # Configuration (MongoDB, Temporal)
├── db/                         # Database layer
│   ├── connection.py           # MongoDB connection manager
│   ├── models.py               # Pydantic document models
│   └── repositories.py         # Data access repositories
├── data/
│   └── providers/
│       ├── upstox.py           # Upstox instruments provider
│       └── nse.py              # NSE Nifty indices provider
├── ui/
│   └── app.py                  # Streamlit dashboard (all-in-one)
├── workflows/                  # Temporal workflows
│   ├── universe.py             # Basic universe refresh workflow
│   └── universe_setup.py       # Full universe setup with quality scoring
├── activities/                 # Temporal activities
│   ├── universe.py             # Basic fetch/save activities
│   └── universe_setup.py       # Quality scoring activities
└── workers/                    # Temporal workers
    ├── client.py               # Temporal client configuration
    ├── universe_worker.py      # Universe refresh worker
    └── start_workflow.py       # Workflow starter script
```

### Planned Directory Structure (To Be Implemented)
```
src/trade_analyzer/
├── pipeline/                    # Multi-stage filtering pipeline
│   ├── regime.py               # CRITICAL: Market regime gate
│   ├── universe.py             # Universe sanitization
│   ├── factors.py              # Factor scoring engine
│   ├── setups.py               # Technical setup detection
│   ├── risk.py                 # Risk geometry filter
│   └── portfolio.py            # Portfolio construction
├── indicators/                 # Technical indicator calculations
├── execution/                  # Gap handling, order generation
├── monitoring/                 # Health metrics, trade tracking
└── output/                     # Report generation
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

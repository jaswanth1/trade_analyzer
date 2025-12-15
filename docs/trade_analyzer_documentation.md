# Trade Analyzer Documentation

## Complete Guide to the NSE Weekly Trading System

**Version:** 1.0
**Last Updated:** December 2024
**Target Market:** National Stock Exchange of India (NSE)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
3. [Getting Started](#3-getting-started)
4. [The 8-Phase Pipeline](#4-the-8-phase-pipeline)
5. [Phase 1: Universe Setup](#5-phase-1-universe-setup)
6. [Phase 2: Momentum Filter](#6-phase-2-momentum-filter)
7. [Phase 3: Consistency Filter](#7-phase-3-consistency-filter)
8. [Phase 4: Volume, Liquidity & Setup Detection](#8-phase-4-volume-liquidity--setup-detection)
9. [Phase 5: Risk Geometry](#9-phase-5-risk-geometry)
10. [Phase 6: Portfolio Construction](#10-phase-6-portfolio-construction)
11. [Phase 7: Execution Display](#11-phase-7-execution-display)
12. [Phase 8: Weekly Recommendations](#12-phase-8-weekly-recommendations)
13. [Database Schema](#13-database-schema)
14. [API Reference](#14-api-reference)
15. [Configuration Guide](#15-configuration-guide)
16. [Operational Procedures](#16-operational-procedures)
17. [Performance Expectations](#17-performance-expectations)
18. [Troubleshooting](#18-troubleshooting)

---

## 1. Executive Summary

### What is Trade Analyzer?

Trade Analyzer is an institutional-grade weekly trading algorithm designed for the National Stock Exchange of India (NSE). It operates on a **weekend analysis, weekday execution** model, systematically filtering ~2,400 stocks down to 3-7 high-conviction trade recommendations.

### Key Features

| Feature | Description |
|---------|-------------|
| **Systematic Approach** | Rules-based filtering eliminates emotional bias |
| **Multi-Phase Pipeline** | 8 sequential filters ensure quality |
| **Regime Awareness** | Automatically adjusts to market conditions |
| **Risk Management** | Built-in position sizing and correlation controls |
| **Production Ready** | Complete with Temporal workflows and MongoDB persistence |

### The Filtering Funnel

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TRADE ANALYZER FUNNEL                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ~2,400 NSE Equity Instruments                                     │
│        │                                                            │
│        ▼ Phase 1: Universe Setup                                    │
│   ~1,400 High-Quality Stocks (MTF + Nifty Index)                    │
│        │                                                            │
│        ▼ Phase 2: Momentum Filter                                   │
│   ~60-80 Momentum Qualified (4+/5 filters)                          │
│        │                                                            │
│        ▼ Phase 3: Consistency Filter                                │
│   ~30-40 Consistency Qualified (5+/6 filters)                       │
│        │                                                            │
│        ▼ Phase 4A: Volume & Liquidity                               │
│   ~15-20 Liquidity Qualified                                        │
│        │                                                            │
│        ▼ Phase 4B: Setup Detection                                  │
│   ~8-12 Technical Setups Detected                                   │
│        │                                                            │
│        ▼ Phase 5: Risk Geometry                                     │
│   ~5-8 Risk-Qualified Setups                                        │
│        │                                                            │
│        ▼ Phase 6: Portfolio Construction                            │
│   ~3-7 Final Positions (correlation + sector limits)                │
│        │                                                            │
│        ▼ Phase 7-8: Execution & Recommendations                     │
│   3-7 Production Trade Templates                                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              TRADE ANALYZER                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │  Streamlit  │    │  Temporal   │    │   MongoDB   │    │   External  │  │
│  │     UI      │    │   Cloud     │    │   Atlas     │    │    APIs     │  │
│  │ (Dashboard) │    │ (Workflows) │    │(Persistence)│    │   (Data)    │  │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │
│         │                  │                  │                  │         │
│         └──────────────────┼──────────────────┼──────────────────┘         │
│                            │                  │                            │
│                    ┌───────▼──────────────────▼───────┐                    │
│                    │         Python Backend           │                    │
│                    │  ├─ Workflows (orchestration)    │                    │
│                    │  ├─ Activities (business logic)  │                    │
│                    │  └─ Workers (execution)          │                    │
│                    └──────────────────────────────────┘                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Overview

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Frontend** | Streamlit | Interactive dashboard for triggering workflows and viewing results |
| **Orchestration** | Temporal Cloud | Reliable workflow execution with retry policies |
| **Database** | MongoDB Atlas | Document storage for all pipeline data |
| **Data Sources** | Yahoo Finance, Upstox, NSE, FMP, Alpha Vantage | Market data and fundamentals |

### Directory Structure

```
src/trade_analyzer/
├── config.py                    # Central configuration
├── db/
│   ├── connection.py            # MongoDB singleton connection
│   ├── models.py                # Pydantic document models (30+)
│   └── repositories.py          # Data access layer
├── data/providers/
│   ├── upstox.py                # NSE instrument data
│   ├── nse.py                   # Nifty index constituents
│   ├── market_data.py           # Yahoo Finance OHLCV + indicators
│   ├── fundamental.py           # FMP + Alpha Vantage financials
│   └── nse_holdings.py          # FII/DII shareholding patterns
├── activities/
│   ├── universe.py              # Universe fetch/save
│   ├── universe_setup.py        # Quality scoring
│   ├── momentum.py              # 5 momentum filters
│   ├── consistency.py           # 9-metric consistency
│   ├── volume_liquidity.py      # Volume & liquidity filters
│   ├── setup_detection.py       # Technical setup detection
│   ├── fundamental.py           # Fundamental analysis
│   ├── risk_geometry.py         # Stop-loss & position sizing
│   ├── portfolio_construction.py # Correlation & sector limits
│   ├── execution.py             # Gap analysis & position tracking
│   └── recommendation.py        # Template generation
├── workflows/
│   ├── universe_setup.py        # Phase 1
│   ├── momentum_filter.py       # Phase 2
│   ├── consistency_filter.py    # Phase 3
│   ├── volume_filter.py         # Phase 4A
│   ├── setup_detection.py       # Phase 4B
│   ├── risk_geometry.py         # Phase 5
│   ├── portfolio_construction.py # Phase 6
│   ├── execution.py             # Phase 7
│   └── weekly_recommendation.py # Phase 8
├── templates/
│   └── trade_setup.py           # Recommendation card generator
├── workers/
│   ├── client.py                # Temporal client configuration
│   ├── universe_worker.py       # Worker process (all workflows)
│   └── start_workflow.py        # Workflow trigger scripts
└── ui/
    └── app.py                   # Streamlit dashboard
```

---

## 3. Getting Started

### Prerequisites

- Python 3.13+
- MongoDB Atlas account (or local MongoDB)
- Temporal Cloud account (or local Temporal)
- API keys for FMP and Alpha Vantage (optional, for fundamentals)

### Installation

```bash
# Clone repository
git clone <repository-url>
cd trade_analyzer

# Install dependencies using uv
uv sync

# Or using pip
pip install -e .
```

### Quick Start

```bash
# Terminal 1: Start the Temporal worker
make worker

# Terminal 2: Start the Streamlit UI
make ui

# Open browser to http://localhost:8501
```

### First Run Checklist

1. **Start Worker** - Ensure Temporal worker is running
2. **Click "Setup Universe"** - Fetches and scores ~2,400 NSE stocks
3. **Run Momentum Filter** - Filters to ~60-80 momentum stocks
4. **Run Consistency Filter** - Further reduces to ~30-40 stocks
5. **Run Full Pipeline** - Generates final recommendations

---

## 4. The 8-Phase Pipeline

### Pipeline Overview

The Trade Analyzer uses an 8-phase sequential filtering pipeline. Each phase progressively narrows down the stock universe using specific criteria.

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         WEEKLY PIPELINE FLOW                                │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐│
│  │   PHASE 1    │   │   PHASE 2    │   │   PHASE 3    │   │   PHASE 4    ││
│  │   Universe   │──▶│   Momentum   │──▶│ Consistency  │──▶│Volume+Setup  ││
│  │    Setup     │   │    Filter    │   │    Filter    │   │  Detection   ││
│  │  (~1,400)    │   │   (~60-80)   │   │   (~30-40)   │   │   (~8-12)    ││
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘│
│                                                                            │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐│
│  │   PHASE 5    │   │   PHASE 6    │   │   PHASE 7    │   │   PHASE 8    ││
│  │    Risk      │──▶│  Portfolio   │──▶│  Execution   │──▶│    Weekly    ││
│  │   Geometry   │   │Construction  │   │   Display    │   │   Recs       ││
│  │    (~5-8)    │   │   (~3-7)     │   │   (UI Only)  │   │   (3-7)      ││
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘│
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### Phase Summary Table

| Phase | Name | Input | Output | Key Filters |
|-------|------|-------|--------|-------------|
| 1 | Universe Setup | ~2,400 NSE EQ | ~1,400 | MTF eligibility, Nifty index membership |
| 2 | Momentum Filter | ~1,400 | ~60-80 | 52W proximity, MA alignment, RS |
| 3 | Consistency Filter | ~60-80 | ~30-40 | Weekly returns, Sharpe, regime |
| 4A | Volume & Liquidity | ~30-40 | ~15-20 | Turnover, circuits, gaps |
| 4B | Setup Detection | ~15-20 | ~8-12 | Pullback, VCP, Retest, Gap-Fill |
| 5 | Risk Geometry | ~8-12 | ~5-8 | R:R ratio, stop distance |
| 6 | Portfolio Construction | ~5-8 | ~3-7 | Correlation, sector limits |
| 7 | Execution Display | ~3-7 | UI | Gap analysis, position tracking |
| 8 | Weekly Recommendations | ~3-7 | 3-7 | Final trade templates |

### Workflow Orchestration

All workflows are orchestrated using Temporal, providing:

- **Durability**: Workflows survive worker restarts
- **Retry Policies**: Automatic retries with exponential backoff
- **Visibility**: Full execution history in Temporal UI
- **Timeouts**: Configurable timeouts for each activity

---

## 5. Phase 1: Universe Setup

### Purpose

Create a high-quality trading universe by filtering NSE equity instruments based on MTF (Margin Trading Facility) eligibility and Nifty index membership.

### Workflow: `UniverseSetupWorkflow`

**File:** `workflows/universe_setup.py`

```python
@workflow.defn
class UniverseSetupWorkflow:
    """
    Phase 1: Create high-quality trading universe.

    Steps:
    1. Fetch NSE EQ instruments from Upstox
    2. Fetch MTF-eligible symbols from Upstox
    3. Fetch Nifty 50/100/200/500 constituents from NSE
    4. Calculate quality scores and tier classifications
    5. Save enriched universe to MongoDB
    """
```

### Quality Scoring System

The system assigns quality scores (0-100) based on:

| Tier | Score Range | Criteria | Typical Count |
|------|-------------|----------|---------------|
| **A** | 90-100 | MTF + Nifty 50 | ~30-40 |
| **B** | 75-89 | MTF + Nifty 100 | ~50-70 |
| **C** | 60-74 | MTF + Nifty 500 | ~200-300 |
| **D** | 40-59 | MTF only | ~100-150 |
| **Below** | <40 | Not in any index | Excluded |

### Scoring Formula

```python
def calculate_quality_score(stock: dict) -> int:
    """
    Calculate quality score based on MTF and index membership.

    Base score: 40 (MTF eligibility required)
    Bonuses:
    - Nifty 50: +50 points
    - Nifty 100: +35 points
    - Nifty 200: +25 points
    - Nifty 500: +20 points
    """
    if not stock["is_mtf"]:
        return 0  # Excluded

    score = 40  # Base MTF score

    if stock["in_nifty_50"]:
        score += 50
    elif stock["in_nifty_100"]:
        score += 35
    elif stock["in_nifty_200"]:
        score += 25
    elif stock["in_nifty_500"]:
        score += 20

    return score
```

### Activities

| Activity | Description | Timeout |
|----------|-------------|---------|
| `fetch_base_universe()` | Fetches NSE EQ + MTF from Upstox | 3 min |
| `fetch_nifty_indices()` | Fetches Nifty 50/100/200/500 from NSE | 2 min |
| `enrich_and_score_universe()` | Calculates quality scores | 5 min |
| `save_enriched_universe()` | Persists to MongoDB | 5 min |

### Output: `UniverseSetupResult`

```python
@dataclass
class UniverseSetupResult:
    success: bool
    total_nse_eq: int      # ~2,400
    total_mtf: int         # ~600
    high_quality_count: int # ~450 (score >= 60)
    tier_a_count: int      # ~30-40
    tier_b_count: int      # ~50-70
    tier_c_count: int      # ~200-300
    error: str | None
```

### UI Trigger

**Dashboard Section:** Phase 1 - Universe Setup
**Button:** "Setup Universe"

---

## 6. Phase 2: Momentum Filter

### Purpose

Identify stocks with strong price momentum relative to the market. Uses 5 independent filters to ensure robust momentum qualification.

### Workflow: `MomentumFilterWorkflow`

**File:** `workflows/momentum_filter.py`

### The 5 Momentum Filters

#### Filter 2A: 52-Week High Proximity

Identifies stocks trading near their 52-week highs, indicating strength.

```python
def filter_2a_proximity(stock: dict) -> bool:
    """
    Pass if close within 10% of 52W high,
    OR within 20% with volume surge > 1.5x
    """
    proximity = (stock["close"] - stock["low_52w"]) / (stock["high_52w"] - stock["low_52w"])

    if proximity >= 0.90:  # Within 10% of high
        return True
    if proximity >= 0.80 and stock["volume_surge"] >= 1.5:
        return True
    return False
```

| Metric | Primary Threshold | Secondary Threshold |
|--------|-------------------|---------------------|
| Proximity to 52W High | >= 90% | >= 80% with volume surge |
| Volume Surge | N/A | >= 1.5x 20-day average |

#### Filter 2B: Moving Average Alignment (5-Layer)

Checks for perfect trend alignment across multiple timeframes.

```
Layer 1: Close > 20-DMA  (short-term trend)
Layer 2: Close > 50-DMA  (intermediate trend)
Layer 3: Close > 200-DMA (long-term trend)
Layer 4: 20-DMA > 50-DMA > 200-DMA (perfect alignment)
Layer 5: All MAs sloping UP
```

**Pass Criteria:** 4+ layers must pass

**Slope Thresholds:**
- 20-DMA: >= 0.1% per day
- 50-DMA: >= 0.05% per day
- 200-DMA: >= 0.02% per day

#### Filter 2C: Multi-Timeframe Relative Strength

Compares stock performance to Nifty 50 benchmark.

| Timeframe | Required Outperformance |
|-----------|-------------------------|
| 1-Month | Stock > Nifty + 5% |
| 3-Month | Stock > Nifty + 10% |
| 6-Month | Stock > Nifty + 15% |

**Pass Criteria:** 2/3 timeframes must pass

#### Filter 2D: Composite Momentum Score

Weighted composite score (0-100):

```
Momentum Score = 25% × 52W Proximity Score +
                 25% × Relative Strength Score +
                 25% × MA Alignment Score (0-5 normalized) +
                 25% × Price Acceleration
```

**Pass Criteria:** Score >= 75

#### Filter 2E: Volatility-Adjusted Momentum

Controls for excessive volatility that could indicate instability.

```python
def filter_2e_volatility(stock: dict, nifty_volatility: float) -> bool:
    """
    Stock volatility must not exceed 1.5x market volatility.
    """
    volatility_ratio = stock["volatility_30d"] / nifty_volatility
    return volatility_ratio <= 1.5
```

### Qualification Rule

**A stock must pass 4 out of 5 filters to qualify.**

### Output: `MomentumResult`

```python
@dataclass
class MomentumResult:
    symbol: str
    proximity_52w: float      # 0-100
    filter_2a_pass: bool
    ma_alignment_score: int   # 0-5
    filter_2b_pass: bool
    rs_1m: float              # Relative strength vs Nifty
    rs_3m: float
    rs_6m: float
    filter_2c_pass: bool
    momentum_score: float     # 0-100 composite
    filter_2d_pass: bool
    volatility_ratio: float
    filter_2e_pass: bool
    filters_passed: int       # 0-5
    qualifies: bool           # True if 4+ filters passed
```

### UI Display

**Dashboard Section:** Phase 2 - Momentum Analysis
**Metrics Shown:**
- Momentum Qualified count
- Total Analyzed
- Pass Rate %

**Tab:** "Momentum Qualified" with filter details

---

## 7. Phase 3: Consistency Filter

### Purpose

Identify stocks with consistent weekly returns that aren't just one-time winners. Uses regime-adaptive thresholds to adjust for market conditions.

### Workflow: `ConsistencyFilterWorkflow`

**File:** `workflows/consistency_filter.py`

### Market Regime Detection

Before applying filters, the system detects the current market regime:

```python
class MarketRegime(Enum):
    BULL = "bull"        # Nifty > 50-DMA by 5%+
    SIDEWAYS = "sideways" # Between
    BEAR = "bear"        # Nifty < 200-DMA
```

**Regime impacts all thresholds:**

| Metric | BULL | SIDEWAYS | BEAR |
|--------|------|----------|------|
| Positive Weeks % Min | 60% | 65% | 70% |
| +3% Weeks Min | 22% | 25% | 20% |
| +3% Weeks Max | 40% | 35% | 30% |
| Volatility Max | 6.5% | 6.0% | 4.5% |
| Sharpe Min | 0.12 | 0.15 | 0.18 |

### The 9 Consistency Metrics

#### Core Metrics (52-Week Lookback)

| # | Metric | Description | Typical Threshold |
|---|--------|-------------|-------------------|
| 1 | **Positive Weeks %** | % of weeks with positive returns | >= 65% |
| 2 | **+3% Weeks %** | % of weeks with >= 3% returns | 25-35% |
| 3 | **+5% Weeks %** | % of weeks with >= 5% returns | Informational |
| 4 | **Weekly Std Dev** | Volatility of weekly returns | <= 6% |
| 5 | **Avg Weekly Return** | Mean weekly percentage return | > 0 |
| 6 | **Sharpe Ratio** | Risk-adjusted returns | >= 0.15 |
| 7 | **Sortino Ratio** | Downside risk-adjusted | Informational |

#### Composite Scores

| # | Score | Formula |
|---|-------|---------|
| 8 | **Consistency Score (0-100)** | 25% × Pos% + 25% × +3% + 20% × (1/Vol) + 15% × Sharpe + 15% × WinStreak |
| 9 | **Regime Score** | 13W Performance / 52W Performance (>= 1.0 = improving) |

### Final Score Calculation

```python
Final Score = 40% × Consistency Score +
              25% × Regime Score (normalized) +
              20% × Percentile Rank +
              15% × Sharpe (normalized)
```

### Qualification Rule

**A stock must pass 5 out of 6 filters to qualify.**

### Output: `ConsistencyResult`

```python
@dataclass
class ConsistencyResult:
    symbol: str
    pos_pct_52w: float        # % positive weeks
    plus3_pct_52w: float      # % weeks with +3%
    std_dev_52w: float        # Weekly volatility
    sharpe_52w: float         # Sharpe ratio
    sortino_52w: float        # Sortino ratio
    consistency_score: float  # 0-100 composite
    regime_score: float       # 13W/52W ratio
    final_score: float        # Ranking score
    market_regime: str        # BULL/SIDEWAYS/BEAR
    filters_passed: int       # 0-6
    qualifies: bool           # True if 5+ filters passed
```

---

## 8. Phase 4: Volume, Liquidity & Setup Detection

Phase 4 consists of two sub-phases: 4A (Volume & Liquidity) and 4B (Setup Detection).

### Phase 4A: Volume & Liquidity Filter

#### Purpose

Ensure stocks have sufficient liquidity for institutional-size trades without excessive slippage.

#### Workflow: `VolumeFilterWorkflow`

**File:** `workflows/volume_filter.py`

#### Liquidity Scoring Formula

```python
Liquidity Score = 40% × Turnover_20D (normalized) +
                  30% × Turnover_60D (normalized) +
                  20% × Peak_Turnover_30D (normalized) +
                  10% × Volume_Stability
```

#### Filter Criteria

| Filter | Threshold | Purpose |
|--------|-----------|---------|
| Liquidity Score | >= 75 | Overall liquidity health |
| 20D Avg Turnover | >= ₹10 Cr | Minimum daily liquidity |
| Circuit Hits (30D) | <= 1 | Avoid volatile stocks |
| Average Gap % | <= 2% | Avoid gapping stocks |

#### Output

```python
@dataclass
class LiquidityResult:
    symbol: str
    liquidity_score: float    # 0-100
    turnover_20d_cr: float    # In crores
    turnover_60d_cr: float
    peak_turnover_30d_cr: float
    circuit_hits_30d: int
    avg_gap_pct: float
    qualifies: bool           # True if all filters pass
```

### Phase 4B: Setup Detection

#### Purpose

Identify specific technical chart patterns that indicate high-probability trade entries.

#### Workflow: `SetupDetectionWorkflow`

**File:** `workflows/setup_detection.py`

#### The 4 Setup Types

##### Type A: PULLBACK (Trend Pullback)

The primary setup type - buying dips in strong uptrends.

```
Criteria:
├─ Price near 20/50-DMA (95-103% of MA)
├─ Volume contracting (last 3 days <= 70% of 20D avg)
├─ RSI(14) in 35-55 zone (not overbought)
├─ MACD histogram turning positive
├─ In uptrend (price > 50-DMA > 200-DMA)
└─ Optional: Hammer candlestick pattern
```

**Entry:** Near moving average support
**Stop:** Below recent swing low
**Target:** Previous high or 2-3R

##### Type B: VCP_BREAKOUT (Volatility Contraction Pattern)

Identifies consolidations about to break out.

```
Criteria:
├─ Range contraction (<= 12% over 3-8 weeks)
├─ Price within 5% of range midpoint
├─ Declining volatility (ATR14 < ATR14 from 21 days ago)
├─ Near breakout level (upper 70% of range)
└─ Weekly range tightening pattern
```

**Entry:** At breakout of consolidation
**Stop:** Below consolidation low
**Target:** Measured move (range height added to breakout)

##### Type C: RETEST (Breakout Retest)

Buying the retest of a recent breakout level.

```
Criteria:
├─ Recent breakout (1-3 weeks ago) with high volume (>= 2.5x)
├─ Price holding above breakout level (>= 97%)
├─ Volume dry-up on retest (<= 60% of breakout volume)
└─ Higher low formation during retest
```

**Entry:** At or slightly above breakout level
**Stop:** Below breakout level
**Target:** Original breakout target

##### Type D: GAP_FILL (Gap-Fill Continuation)

Buying after a gap partially fills in a strong trend.

```
Criteria:
├─ Recent gap up (0.5-2%) in established uptrend
├─ Gap partially filled (50-75%)
├─ Volume expansion on gap day (>= 1.8x average)
└─ Gap above rising 20-DMA
```

**Entry:** After gap fills to support
**Stop:** Below gap low
**Target:** New highs

#### Entry/Stop/Target Calculation

```python
def calculate_levels(stock: dict, setup_type: str) -> dict:
    """
    Calculate entry zone, stop loss, and targets.
    """
    atr = stock["atr_14"]

    # Entry zone: Support level ± 0.5 ATR
    entry_low = stock["support_level"] - (0.5 * atr)
    entry_high = stock["support_level"] + (0.5 * atr)

    # Stop loss: Tighter of two methods
    stop_structure = stock["swing_low"] * 0.99  # 1% below swing
    stop_volatility = entry_low - (2 * atr)      # 2 ATR below entry
    stop_loss = max(stop_structure, stop_volatility)  # Higher = tighter

    # Risk per share
    risk = entry_low - stop_loss

    # Targets
    target_1 = entry_low + (2 * risk)  # 2R
    target_2 = min(entry_low + (3 * risk), stock["high_52w"])  # 3R or 52W high

    return {
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "target_2": target_2,
        "rr_ratio": (target_1 - entry_low) / risk
    }
```

#### Output: `TradeSetup`

```python
@dataclass
class TradeSetup:
    symbol: str
    setup_type: str           # PULLBACK, VCP_BREAKOUT, RETEST, GAP_FILL
    rank: int                 # Quality ranking
    entry_low: float
    entry_high: float
    stop_loss: float
    target_1: float
    target_2: float
    rr_ratio: float           # Reward:Risk ratio
    confidence: float         # 0-100 setup quality
    momentum_score: float     # From Phase 2
    consistency_score: float  # From Phase 3
    liquidity_score: float    # From Phase 4A
    detected_at: datetime
```

---

## 9. Phase 5: Risk Geometry

### Purpose

Calculate precise stop-loss levels and position sizes based on volatility and portfolio risk parameters.

### Workflow: `RiskGeometryWorkflow`

**File:** `workflows/risk_geometry.py`

### Multi-Method Stop-Loss Calculation

The system uses the TIGHTER of two stop-loss methods:

```python
def calculate_stop_loss(stock: dict, entry: float) -> tuple[float, str]:
    """
    Calculate stop loss using two methods, return tighter one.
    """
    # Method 1: Structure-based (below swing low)
    stop_structure = stock["swing_low"] * 0.99  # 1% below

    # Method 2: Volatility-based (2 ATR)
    stop_volatility = entry - (2 * stock["atr_14"])

    # Use tighter stop (higher price)
    if stop_structure > stop_volatility:
        return stop_structure, "structure"
    else:
        return stop_volatility, "volatility"
```

### Position Sizing Formula

```python
def calculate_position_size(
    portfolio_value: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
    stock_atr: float,
    nifty_atr: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    regime_multiplier: float
) -> int:
    """
    Calculate shares using volatility-adjusted Kelly sizing.
    """
    # Base position from fixed risk
    risk_per_share = entry_price - stop_loss
    base_risk = portfolio_value * risk_pct
    base_shares = base_risk / risk_per_share

    # Volatility adjustment (reduce size for volatile stocks)
    vol_adjustment = nifty_atr / stock_atr
    vol_adjustment = max(0.5, min(1.5, vol_adjustment))  # Cap at 0.5-1.5x

    # Kelly fraction (theoretical optimal sizing)
    kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
    kelly = max(0, min(1.0, kelly))  # Cap at 0-100%

    # Final calculation
    final_shares = int(base_shares * vol_adjustment * kelly * regime_multiplier)

    return final_shares
```

### Risk Constraints

| Constraint | Value | Purpose |
|------------|-------|---------|
| Max Risk Per Trade | 1.5% | Capital preservation |
| Max Stop Distance | 8% | Avoid distant stops |
| Min R:R (Risk-On) | 2.0 | Ensure positive expectancy |
| Min R:R (Choppy) | 2.5 | Higher bar in uncertain markets |
| Max Kelly Fraction | 1.0 | Prevent over-betting |

### Regime Multipliers

| Regime State | Multiplier | Effect |
|--------------|------------|--------|
| Risk-On (>70% confidence) | 1.0 | Full position sizes |
| Risk-On (50-70% confidence) | 0.7 | Reduced sizes |
| Choppy | 0.5 | Half sizes |
| Risk-Off | 0.0 | NO NEW POSITIONS |

### Output: `PositionSize`

```python
@dataclass
class PositionSize:
    symbol: str
    setup_id: str
    portfolio_value: float
    entry_price: float
    stop_loss: float
    stop_method: str          # "structure" or "volatility"
    stop_distance_pct: float
    risk_per_share: float
    base_shares: int
    vol_adjustment: float
    kelly_fraction: float
    regime_multiplier: float
    final_shares: int
    final_position_value: float
    final_risk_amount: float
    position_pct: float       # % of portfolio
    risk_qualifies: bool      # Meets all constraints
```

---

## 10. Phase 6: Portfolio Construction

### Purpose

Build a diversified portfolio from qualified setups by applying correlation and sector limits.

### Workflow: `PortfolioConstructionWorkflow`

**File:** `workflows/portfolio_construction.py`

### Correlation Filter

Prevents holding highly correlated positions that would amplify risk.

```python
def apply_correlation_filter(
    setups: list[dict],
    correlation_matrix: pd.DataFrame,
    max_correlation: float = 0.70
) -> list[dict]:
    """
    Remove lower-ranked stock from highly correlated pairs.
    """
    filtered = []
    for setup in sorted(setups, key=lambda x: x["rank"]):
        # Check correlation with already selected stocks
        is_correlated = False
        for selected in filtered:
            corr = correlation_matrix.loc[setup["symbol"], selected["symbol"]]
            if abs(corr) > max_correlation:
                is_correlated = True
                break

        if not is_correlated:
            filtered.append(setup)

    return filtered
```

### Sector Concentration Limits

| Limit | Value | Purpose |
|-------|-------|---------|
| Max Stocks Per Sector | 3 | Sector diversification |
| Max Sector Allocation | 25% | Prevent concentration |
| Max Single Position | 8% | Individual stock limit |
| Min Cash Reserve | 25-35% | Dry powder for opportunities |
| Max Total Positions | 12 | Portfolio manageability |

### Portfolio Construction Algorithm

```python
def construct_portfolio(setups: list[dict], config: PortfolioConfig) -> Portfolio:
    """
    Build final portfolio from qualified setups.

    Steps:
    1. Rank setups by overall quality score
    2. Apply correlation filter (remove highly correlated)
    3. Apply sector limits (max 3 per sector, 25% exposure)
    4. Select top positions up to capital limit
    5. Calculate final allocations
    """
    # Step 1: Rank by quality
    ranked = sorted(setups, key=lambda x: x["overall_quality"], reverse=True)

    # Step 2: Correlation filter
    uncorrelated = apply_correlation_filter(ranked, config.max_correlation)

    # Step 3: Sector limits
    sector_limited = apply_sector_limits(uncorrelated, config)

    # Step 4: Select positions
    selected = []
    total_allocated = 0
    max_allocation = config.portfolio_value * (1 - config.cash_reserve_pct)

    for setup in sector_limited:
        if len(selected) >= config.max_positions:
            break
        if total_allocated + setup["position_value"] > max_allocation:
            continue
        selected.append(setup)
        total_allocated += setup["position_value"]

    # Step 5: Calculate allocations
    return Portfolio(
        positions=selected,
        total_allocated=total_allocated,
        allocated_pct=total_allocated / config.portfolio_value * 100,
        cash_reserve=config.portfolio_value - total_allocated
    )
```

### Output: `PortfolioAllocation`

```python
@dataclass
class PortfolioAllocation:
    allocation_date: datetime
    regime_state: str
    regime_confidence: float
    portfolio_value: float
    positions: list[dict]     # Final selected positions
    sector_allocation: dict   # {"IT": 25%, "Banks": 20%, ...}
    total_allocated: float
    allocated_pct: float
    cash_reserve: float
    cash_pct: float
    total_risk_pct: float
    correlation_filtered: int # Count removed by correlation
    sector_filtered: int      # Count removed by sector limits
    status: str               # "pending", "approved", "executed"
```

---

## 11. Phase 7: Execution Display

### Purpose

Provide real-time execution support including gap analysis, position tracking, and weekly summaries.

### Workflow: `ExecutionDisplayWorkflow`

**File:** `workflows/execution.py`

### Monday Pre-Market Analysis

Evaluates how Monday's expected gap affects each setup.

```python
@dataclass
class GapContingency:
    """Rules for handling Monday gaps."""

    # If Monday open < stop_loss
    action_gap_through_stop: str = "SKIP"  # Don't enter

    # If Monday open in entry zone
    action_within_zone: str = "ENTER_AT_OPEN"

    # If Monday open < entry but > stop
    action_small_gap_against: str = "ENTER_AT_OPEN"  # Small gap okay

    # If Monday open > entry_high * 1.02
    action_gap_above_entry: str = "SKIP"  # Don't chase
```

### Gap Analysis Decision Tree

```
                    Monday Open Price
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
      < Stop Loss    In Entry Zone    > Entry + 2%
           │               │               │
           ▼               ▼               ▼
        SKIP           ENTER           SKIP
    (Invalidated)   (Execute)    (Don't Chase)
```

### Position Status Tracking

Real-time monitoring of active positions:

```python
@dataclass
class PositionStatus:
    symbol: str
    entry_price: float
    current_price: float
    shares: int
    unrealized_pnl: float
    unrealized_pnl_pct: float
    r_multiple: float         # Current P&L in R terms
    distance_to_stop_pct: float
    distance_to_target_pct: float
    alerts: list[str]         # ["Approaching stop", "At target 1", etc.]
```

### Friday Close Summary

Weekly performance report:

```python
@dataclass
class FridaySummary:
    week_start: datetime
    week_end: datetime
    realized_pnl: float       # Closed trades
    unrealized_pnl: float     # Open positions
    total_pnl: float
    total_r: float            # Performance in R
    trades_closed: int
    trades_won: int
    win_rate: float
    open_positions: list[dict]
    closed_positions: list[dict]
    system_health_score: float  # 0-100
    recommended_action: str   # CONTINUE/REDUCE/PAUSE/STOP
```

### System Health Scoring

```python
def calculate_system_health(metrics: dict) -> tuple[float, str]:
    """
    Calculate system health score and recommended action.

    Score Components:
    - Rolling win rate (40%)
    - Recent expectancy (30%)
    - Drawdown level (20%)
    - Execution quality (10%)
    """
    score = (
        metrics["win_rate_12w"] * 0.4 +
        metrics["expectancy_12w"] * 0.3 +
        (100 - metrics["current_drawdown"]) * 0.2 +
        metrics["execution_score"] * 0.1
    )

    if score >= 70:
        action = "CONTINUE"
    elif score >= 50:
        action = "REDUCE"  # Reduce position sizes
    elif score >= 30:
        action = "PAUSE"   # Paper trade only
    else:
        action = "STOP"    # Full system review

    return score, action
```

---

## 12. Phase 8: Weekly Recommendations

### Purpose

Generate production-ready trade recommendation cards with all necessary execution details.

### Workflow: `WeeklyRecommendationWorkflow`

**File:** `workflows/weekly_recommendation.py`

### Trade Setup Template

```python
@dataclass
class TradeSetupTemplate:
    """Complete trade recommendation card."""

    # Identification
    symbol: str
    company_name: str
    sector: str
    week_display: str         # "December 16, 2024"

    # Phase Scores (0-100)
    momentum_score: float
    consistency_score: float
    liquidity_score: float
    fundamental_score: float
    setup_confidence: float

    # Final Conviction (0-10 scale)
    final_conviction: float
    conviction_label: str     # "Very High", "High", "Medium", etc.

    # Technical Context
    current_price: float
    high_52w: float
    low_52w: float
    dma_20: float
    dma_50: float
    dma_200: float
    from_52w_high_pct: float

    # Setup Details
    setup_type: str           # PULLBACK, VCP_BREAKOUT, etc.
    entry_low: float
    entry_high: float
    stop_loss: float
    stop_method: str
    stop_distance_pct: float
    target_1: float
    target_2: float
    rr_ratio_1: float
    rr_ratio_2: float

    # Position Sizing
    shares: int
    investment_amount: float
    risk_amount: float
    position_pct: float       # % of portfolio

    # Execution
    action_steps: list[str]
    gap_contingency: str

    # Metadata
    market_regime: str
    regime_confidence: float
    generated_at: str
```

### Conviction Score Calculation

```python
def calculate_conviction(
    momentum: float,
    consistency: float,
    liquidity: float,
    fundamental: float,
    setup_confidence: float
) -> tuple[float, str]:
    """
    Calculate final conviction score (0-10).

    Weights:
    - Momentum: 25%
    - Consistency: 20%
    - Liquidity: 15%
    - Fundamental: 20%
    - Setup Confidence: 20%
    """
    weighted = (
        momentum * 0.25 +
        consistency * 0.20 +
        liquidity * 0.15 +
        fundamental * 0.20 +
        setup_confidence * 0.20
    )

    conviction = weighted / 10  # Convert to 0-10 scale

    if conviction >= 8:
        label = "Very High"
    elif conviction >= 6.5:
        label = "High"
    elif conviction >= 5:
        label = "Medium"
    elif conviction >= 3.5:
        label = "Low"
    else:
        label = "Very Low"

    return round(conviction, 1), label
```

### Sample Output

```
================================================================================
                    TRADE RECOMMENDATION CARD
                    Week of December 16, 2024
================================================================================

SYMBOL: RELIANCE
Company: Reliance Industries Ltd
Sector: Oil & Gas
Setup Type: PULLBACK

--------------------------------------------------------------------------------
                         CONVICTION SCORES
--------------------------------------------------------------------------------
Final Conviction: 7.5/10 (High)

Phase Scores:
  - Momentum Score:    85/100
  - Consistency Score: 78/100
  - Liquidity Score:   92/100
  - Fundamental Score: 75/100
  - Setup Confidence:  80/100

Market Regime: RISK_ON (85% confidence)

--------------------------------------------------------------------------------
                         TECHNICAL DATA
--------------------------------------------------------------------------------
Current Price:     Rs.2,450.00
52-Week High:      Rs.2,856.50 (14.2% from high)
52-Week Low:       Rs.2,180.00
20 DMA:            Rs.2,420.00
50 DMA:            Rs.2,380.00
200 DMA:           Rs.2,250.00

--------------------------------------------------------------------------------
                         TRADE PARAMETERS
--------------------------------------------------------------------------------
Entry Zone:        Rs.2,430.00 - Rs.2,460.00
Stop Loss:         Rs.2,380.00 (2.9% risk)
Stop Method:       STRUCTURE

Target 1 (2R):     Rs.2,550.00 (R:R 2.1)
Target 2 (3R):     Rs.2,620.00 (R:R 3.2)

--------------------------------------------------------------------------------
                         POSITION SIZING
--------------------------------------------------------------------------------
Shares:            167
Investment:        Rs.4,09,150.00
Risk Amount:       Rs.11,690.00
Portfolio %:       40.9%

--------------------------------------------------------------------------------
                         ACTION STEPS
--------------------------------------------------------------------------------
  1. Place limit buy order at Rs.2,430.00 - Rs.2,460.00
  2. Set stop-loss at Rs.2,380.00 (2.9% below entry, structure method)
  3. Buy 167 shares (Rs.4,09,150, 40.9% of portfolio)
  4. Target 1: Rs.2,550.00 (2.1R) - Take 50% profit
  5. Target 2: Rs.2,620.00 (3.2R) - Exit remaining
  6. At 1R profit (+3%), move stop to breakeven
  7. At 2R profit (+6%), trail stop to +2%

--------------------------------------------------------------------------------
                         GAP CONTINGENCY (MONDAY)
--------------------------------------------------------------------------------
If Monday open < Rs.2,380.00 (stop): SKIP trade
If Monday open in Rs.2,430.00-Rs.2,460.00: ENTER at open
If Monday open > Rs.2,509.20 (+2%): SKIP - don't chase
If Monday open < Rs.2,430.00 but > Rs.2,380.00: ENTER at open (small gap against)

================================================================================
Generated: 2024-12-15T10:30:00Z
================================================================================
```

---

## 13. Database Schema

### Collections Overview

| Collection | Purpose | Updated By |
|------------|---------|------------|
| `stocks` | Master stock universe | Phase 1 |
| `momentum_scores` | Momentum analysis results | Phase 2 |
| `consistency_scores` | Consistency analysis results | Phase 3 |
| `liquidity_scores` | Liquidity analysis results | Phase 4A |
| `trade_setups` | Detected trading setups | Phase 4B |
| `fundamental_scores` | Fundamental analysis | Phase 5 (optional) |
| `institutional_holdings` | FII/DII data | Phase 5 (optional) |
| `position_sizes` | Risk-adjusted positions | Phase 5 |
| `portfolio_allocations` | Final portfolios | Phase 6 |
| `monday_premarket` | Gap analysis | Phase 7 |
| `friday_summaries` | Weekly summaries | Phase 7 |
| `weekly_recommendations` | Final recommendations | Phase 8 |
| `regime_assessments` | Market regime history | Phase 3 |

### Key Document Schemas

#### stocks

```javascript
{
  _id: ObjectId(),
  symbol: "RELIANCE",
  name: "Reliance Industries Ltd",
  isin: "INE002A01018",
  instrument_key: "NSE_EQ|INE002A01018",
  segment: "NSE_EQ",
  instrument_type: "EQ",
  lot_size: 1,
  tick_size: 0.05,

  // Quality scoring
  is_mtf: true,
  in_nifty_50: true,
  in_nifty_100: true,
  in_nifty_200: true,
  in_nifty_500: true,
  quality_score: 95,
  liquidity_tier: "A",

  // Fundamental qualification (Phase 1)
  fundamentally_qualified: true,
  fundamental_score: 78.5,
  fundamental_updated_at: ISODate(),

  // Status
  is_active: true,
  last_updated: ISODate()
}
```

#### trade_setups

```javascript
{
  _id: ObjectId(),
  symbol: "RELIANCE",
  setup_type: "PULLBACK",
  status: "active",
  rank: 1,

  // Price levels
  entry_low: 2430,
  entry_high: 2460,
  stop_loss: 2380,
  target_1: 2550,
  target_2: 2620,
  rr_ratio: 2.1,

  // Scores
  confidence: 92,
  overall_quality: 88.5,
  momentum_score: 85.2,
  consistency_score: 78.4,
  liquidity_score: 94.2,

  // Context
  market_regime: "risk_on",
  week_start: ISODate(),
  detected_at: ISODate()
}
```

#### weekly_recommendations

```javascript
{
  _id: ObjectId(),
  week_start: ISODate(),
  week_end: ISODate(),
  week_display: "Dec 16-20, 2024",

  // Market context
  market_regime: "risk_on",
  regime_confidence: 0.85,
  position_multiplier: 1.0,

  // Recommendations
  total_setups: 5,
  recommendations: [
    {
      symbol: "RELIANCE",
      company_name: "Reliance Industries Ltd",
      sector: "Oil & Gas",
      setup_type: "PULLBACK",
      final_conviction: 7.5,
      conviction_label: "High",
      entry_low: 2430,
      entry_high: 2460,
      stop_loss: 2380,
      target_1: 2550,
      target_2: 2620,
      shares: 167,
      investment_amount: 409150,
      risk_amount: 11690,
      position_pct: 40.9,
      action_steps: [...],
      gap_contingency: "..."
    }
  ],

  // Portfolio summary
  portfolio_value: 1000000,
  allocated_capital: 732150,
  allocated_pct: 73.2,
  total_risk_pct: 2.8,

  // Status
  status: "draft",  // draft -> approved -> executed
  created_at: ISODate()
}
```

### Indexes

```python
# stocks collection
db.stocks.create_index("symbol", unique=True)
db.stocks.create_index("is_active")
db.stocks.create_index("quality_score")
db.stocks.create_index("fundamentally_qualified")
db.stocks.create_index([("quality_score", -1), ("fundamentally_qualified", 1)])

# trade_setups collection
db.trade_setups.create_index("symbol")
db.trade_setups.create_index("status")
db.trade_setups.create_index("week_start")
db.trade_setups.create_index([("status", 1), ("rank", 1)])

# weekly_recommendations collection
db.weekly_recommendations.create_index("week_start")
db.weekly_recommendations.create_index("status")
```

---

## 14. API Reference

### Workflows

| Workflow | Task Queue | Description |
|----------|------------|-------------|
| `UniverseSetupWorkflow` | `trade-analyzer-universe-refresh` | Phase 1: Setup trading universe |
| `MomentumFilterWorkflow` | `trade-analyzer-universe-refresh` | Phase 2: Apply momentum filters |
| `ConsistencyFilterWorkflow` | `trade-analyzer-universe-refresh` | Phase 3: Apply consistency filters |
| `VolumeFilterWorkflow` | `trade-analyzer-universe-refresh` | Phase 4A: Apply liquidity filters |
| `SetupDetectionWorkflow` | `trade-analyzer-universe-refresh` | Phase 4B: Detect technical setups |
| `RiskGeometryWorkflow` | `trade-analyzer-universe-refresh` | Phase 5: Calculate risk parameters |
| `PortfolioConstructionWorkflow` | `trade-analyzer-universe-refresh` | Phase 6: Build final portfolio |
| `ExecutionDisplayWorkflow` | `trade-analyzer-universe-refresh` | Phase 7: Execution support |
| `WeeklyRecommendationWorkflow` | `trade-analyzer-universe-refresh` | Phase 8: Generate recommendations |

### Combined Pipelines

| Workflow | Phases Included | Use Case |
|----------|-----------------|----------|
| `UniverseAndMomentumWorkflow` | 1 + 2 | Quick universe + momentum |
| `FullPipelineWorkflow` | 1 + 2 + 3 | Through consistency |
| `Phase4PipelineWorkflow` | 4A + 4B | Volume + setup detection |
| `FullAnalysisPipelineWorkflow` | 1 through 4B | Complete analysis |
| `WeeklyFullPipelineWorkflow` | 4B through 8 | Full recommendations |

### Activity Reference

#### Phase 1 Activities

| Activity | Input | Output |
|----------|-------|--------|
| `fetch_base_universe()` | None | `BaseUniverseData` |
| `fetch_nifty_indices()` | None | `NiftyData` |
| `enrich_and_score_universe()` | instruments, mtf_symbols, nifty_lists | `list[dict]` |
| `save_enriched_universe()` | enriched_stocks | `dict` (stats) |

#### Phase 2 Activities

| Activity | Input | Output |
|----------|-------|--------|
| `fetch_high_quality_symbols()` | None | `list[str]` |
| `fetch_market_data_batch()` | symbols, delay | `dict` |
| `fetch_nifty_benchmark_data()` | None | `dict` |
| `calculate_momentum_scores()` | market_data, nifty_data | `list[MomentumResult]` |
| `save_momentum_results()` | results | `dict` (stats) |

#### Phase 3 Activities

| Activity | Input | Output |
|----------|-------|--------|
| `fetch_momentum_qualified_symbols()` | None | `list[str]` |
| `fetch_weekly_data_batch()` | symbols | `dict` |
| `detect_current_regime()` | None | `dict` |
| `calculate_consistency_scores()` | weekly_data, regime | `list[ConsistencyResult]` |
| `save_consistency_results()` | results | `dict` (stats) |

---

## 15. Configuration Guide

### Environment Configuration

All configuration is centralized in `src/trade_analyzer/config.py`:

```python
# MongoDB Configuration
MONGODB_URI = "mongodb+srv://..."
MONGODB_DATABASE = "trade_analysis"

# Temporal Cloud Configuration
TEMPORAL_ADDRESS = "ap-south-1.aws.api.temporal.io:7233"
TEMPORAL_NAMESPACE = "trade-discovere.y8vfp"
TEMPORAL_API_KEY = "..."

# Task Queue
TASK_QUEUE = "trade-analyzer-universe-refresh"

# External APIs (optional)
FMP_API_KEY = "..."           # Financial Modeling Prep
ALPHA_VANTAGE_API_KEY = "..." # Alpha Vantage

# Portfolio Defaults
DEFAULT_PORTFOLIO_VALUE = 1_000_000  # Rs. 10 Lakhs
DEFAULT_RISK_PCT = 0.015             # 1.5% per trade
MAX_POSITIONS = 12
MAX_SECTOR_PCT = 0.25                # 25% sector limit
CASH_RESERVE_PCT = 0.30              # 30% cash reserve
```

### Environment Variable Overrides

```bash
# MongoDB
export MONGODB_URI="mongodb+srv://..."
export MONGODB_DATABASE="trade_analysis"

# Temporal
export TEMPORAL_ADDRESS="..."
export TEMPORAL_NAMESPACE="..."
export TEMPORAL_API_KEY="..."

# APIs
export FMP_API_KEY="..."
export ALPHA_VANTAGE_API_KEY="..."

# Portfolio
export DEFAULT_PORTFOLIO_VALUE=1000000
export DEFAULT_RISK_PCT=0.015
```

### Retry Policies

Default retry policy for all activities:

```python
RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
    backoff_coefficient=2.0,
)
```

### Activity Timeouts

| Phase | Activity | Timeout |
|-------|----------|---------|
| 1 | fetch_base_universe | 3 min |
| 1 | fetch_nifty_indices | 2 min |
| 1 | enrich_and_score_universe | 5 min |
| 2 | fetch_market_data_batch | 10 min |
| 2 | calculate_momentum_scores | 5 min |
| 3 | fetch_weekly_data_batch | 10 min |
| 3 | calculate_consistency_scores | 5 min |
| 4B | detect_setups_batch | 10 min |

---

## 16. Operational Procedures

### Weekly Cycle

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          WEEKLY OPERATING CYCLE                             │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  SATURDAY/SUNDAY (Weekend Analysis)                                        │
│  ─────────────────────────────────────                                     │
│  09:00  Start Temporal worker: make worker                                 │
│  09:05  Start UI: make ui                                                  │
│  09:10  Click "Setup Universe" (Phase 1)                                   │
│  09:20  Click "Full Weekend Run" (Phase 1+2)                               │
│  10:00  Click "Full Pipeline (1-3)" (Phase 1-3)                            │
│  11:00  Click "Full Analysis (1-4)" (Phase 1-4B)                           │
│  12:00  Review detected setups in UI                                       │
│  14:00  Click "Full Pipeline (4B-9)" (Full recommendations)                │
│  16:00  Review final recommendations                                       │
│  17:00  Approve/reject individual setups                                   │
│  18:00  Export approved recommendations                                    │
│                                                                            │
│  MONDAY (Execution)                                                        │
│  ─────────────────                                                         │
│  08:30  Run Pre-Market Analysis                                            │
│  08:45  Review gap contingency actions                                     │
│  09:15  Execute trades per contingency rules                               │
│  09:30  Log entries in system                                              │
│                                                                            │
│  TUESDAY-THURSDAY (Monitoring)                                             │
│  ─────────────────────────────                                             │
│  Daily  Check position status                                              │
│  Daily  Monitor stops and targets                                          │
│  Daily  Log any exits                                                      │
│                                                                            │
│  FRIDAY (Close)                                                            │
│  ─────────────                                                             │
│  15:30  Run Friday Close workflow                                          │
│  16:00  Review week summary                                                │
│  16:30  Check system health score                                          │
│  17:00  Note any adjustments for next week                                 │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### Monthly Tasks

1. **Review System Health Metrics**
   - 12-week rolling win rate
   - Average R-multiple
   - Maximum drawdown
   - Execution slippage

2. **Refresh Fundamental Data** (if using Phase 5 fundamentals)
   - Run `FundamentalDataRefreshWorkflow`
   - Update fundamental scores for universe

3. **Review and Adjust**
   - Sector exposure trends
   - Setup type performance
   - Regime detection accuracy

### Maintenance Commands

```bash
# Daily operations
make worker              # Start Temporal worker
make ui                  # Start Streamlit UI

# Docker operations
make up                  # Start all services
make down                # Stop all services
make logs                # View logs
make rebuild             # Rebuild containers

# Development
make test                # Run tests
make cov                 # Test coverage
make check               # Lint with Ruff
make format              # Format with Ruff
make allci               # All CI checks
```

---

## 17. Performance Expectations

### Realistic Return Expectations

| Metric | Optimistic | Realistic |
|--------|------------|-----------|
| Win Rate | 55-60% | 50-55% |
| Average Win | 1.5R | 1.2R |
| Average Loss | 1.0R | 1.1R |
| EV per Trade (gross) | 0.44R | 0.11R |
| EV per Trade (net) | 0.35R | 0.05-0.10R |
| Annual Return | 50%+ | 15-30% |
| Max Drawdown | 10% | 15-25% |

### Transaction Costs (India-Specific)

For a Rs. 1,00,000 trade:

| Cost Component | Amount | Percentage |
|----------------|--------|------------|
| STT (buy + sell) | Rs. 200 | 0.20% |
| Brokerage | Rs. 40 | 0.04% |
| GST on brokerage | Rs. 7 | 0.01% |
| Exchange fees | Rs. 7 | 0.01% |
| Stamp duty | Rs. 15 | 0.02% |
| **Total Round-Trip** | **Rs. 270** | **0.27%** |

Plus 15% Short-Term Capital Gains (STCG) tax on profits.

**Critical Insight:** You need >0.2R gross per trade just to break even after costs.

### Where the Edge Comes From

1. **Regime Awareness** - Not trading in Risk-Off environments
2. **Selection Discipline** - "No trade" is a valid output
3. **Risk Management** - Surviving drawdowns to compound
4. **Consistency** - Running the system for years, not weeks

### Success Metrics (After 52 Weeks)

| Metric | Minimum | Target |
|--------|---------|--------|
| Win Rate | 48% | 53% |
| Avg R-Multiple | 0.05R | 0.15R |
| Expectancy (after costs) | Break-even | 0.10R |
| Max Drawdown | <25% | <15% |
| Sharpe Ratio | >0.5 | >1.0 |
| System Uptime | >95% | >99% |

---

## 18. Troubleshooting

### Common Issues

#### Worker Not Starting

```bash
# Check Temporal connection
temporal operator namespace describe --namespace trade-discovere.y8vfp

# Check API key
echo $TEMPORAL_API_KEY

# Restart worker
make worker
```

#### MongoDB Connection Failed

```bash
# Test connection
mongosh "mongodb+srv://..." --eval "db.stats()"

# Check credentials in config.py
grep MONGODB config.py
```

#### Workflow Timeout

```python
# Increase activity timeout
await workflow.execute_activity(
    fetch_market_data_batch,
    args=[symbols, delay],
    start_to_close_timeout=timedelta(minutes=15),  # Increase from 10
    retry_policy=retry_policy,
)
```

#### API Rate Limiting

```python
# Increase delay between API calls
@activity.defn
async def fetch_market_data_batch(symbols: list[str], delay: float = 0.5):
    # Increase delay to 1.0 or higher
    await asyncio.sleep(delay)
```

### Debugging Workflows

1. **Check Temporal UI**
   - Go to Temporal Cloud console
   - View workflow execution history
   - Check for failed activities

2. **Enable Debug Logging**
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

3. **Check MongoDB Data**
   ```javascript
   // Check latest universe stats
   db.stocks.aggregate([
     {$match: {is_active: true}},
     {$group: {_id: "$liquidity_tier", count: {$sum: 1}}}
   ])

   // Check latest setups
   db.trade_setups.find({status: "active"}).sort({rank: 1})
   ```

### Error Recovery

| Error | Recovery |
|-------|----------|
| Partial pipeline failure | Re-run failed phase only |
| Data corruption | Delete collection, re-run from Phase 1 |
| API outage | Wait and retry, or skip affected phase |
| Worker crash | Temporal auto-retries, just restart worker |

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **ATR** | Average True Range - volatility indicator |
| **DMA** | Daily Moving Average |
| **FII** | Foreign Institutional Investors |
| **DII** | Domestic Institutional Investors |
| **MTF** | Margin Trading Facility - broker-eligible stocks |
| **R** | Risk unit (1R = risk per trade, typically 1.5%) |
| **R:R** | Reward to Risk ratio |
| **RS** | Relative Strength vs benchmark |
| **VCP** | Volatility Contraction Pattern |

## Appendix B: File Reference

| File | Purpose |
|------|---------|
| `config.py` | Central configuration |
| `db/connection.py` | MongoDB singleton |
| `db/models.py` | Pydantic models (30+) |
| `db/repositories.py` | Data access layer |
| `activities/*.py` | Temporal activities (60+) |
| `workflows/*.py` | Temporal workflows (22) |
| `workers/universe_worker.py` | Worker process |
| `workers/start_workflow.py` | Workflow triggers |
| `ui/app.py` | Streamlit dashboard |
| `templates/trade_setup.py` | Recommendation cards |

---

**Document Version:** 1.0
**Last Updated:** December 2024
**Maintainer:** Trade Analyzer Team

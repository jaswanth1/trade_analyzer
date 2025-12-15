# Trade Analyzer - Implementation Plan

## Overview

This document tracks the implementation progress and roadmap for the Trade Analyzer system - an institutional-grade weekly trading algorithm for NSE (National Stock Exchange of India).

**Target Output:** 3-7 trade setups every weekend with defined entry, stop, target, and position size.

---

## Current Status Summary

### Workflows Implemented

| Workflow | Status | UI Trigger | UI Display |
|----------|--------|------------|------------|
| UniverseSetupWorkflow | DONE | Dashboard: "Setup Universe" | Stats, Stock Lists |
| MomentumFilterWorkflow | DONE | Dashboard: "Run Momentum Filter" | Momentum Qualified List |
| UniverseAndMomentumWorkflow | DONE | Dashboard: "Full Weekend Run" | Combined Results |
| ConsistencyFilterWorkflow | DONE | Dashboard: "Run Consistency Filter" | Consistency Qualified List |
| FullPipelineWorkflow | DONE | Dashboard: "Full Pipeline (1-3)" | Complete Pipeline Results |
| RegimeAssessmentWorkflow | INTEGRATED | Auto (in Consistency) | Market Regime Display |
| VolumeFilterWorkflow | DONE | Dashboard: "Run Volume Filter" | Liquidity Qualified List |
| SetupDetectionWorkflow | DONE | Dashboard: "Run Setup Detection" | Trade Setups List |
| Phase4PipelineWorkflow | DONE | Dashboard: "Phase 4 Pipeline" | Volume + Setup Results |
| FullAnalysisPipelineWorkflow | DONE | Dashboard: "Full Analysis (1-4)" | Complete Pipeline Results |
| RiskGeometryWorkflow | NOT STARTED | Auto | Position Sizes |
| PortfolioConstructionWorkflow | NOT STARTED | Auto | Final Approvals |

### Infrastructure Status

| Component | Status | Notes |
|-----------|--------|-------|
| MongoDB Atlas | DONE | DigitalOcean, trade_analysis DB |
| Temporal Cloud | DONE | ap-south-1, trade-discovere namespace |
| Streamlit UI | DONE | Dashboard + Momentum Filter tab |
| Docker Compose | DONE | UI + Worker services |
| Yahoo Finance | DONE | Free OHLCV data (no auth needed) |
| Upstox OAuth | NOT STARTED | Optional for real-time data |

---

## How to Run

```bash
# Terminal 1: Start Temporal worker
make worker

# Terminal 2: Start Streamlit UI
make ui

# Then click "Setup Universe" button in the Dashboard
```

---

## Development Log & Decisions

### Session 1: Foundation Setup (Dec 2024)

#### What Was Built

| Component | File(s) | Status |
|-----------|---------|--------|
| MongoDB Connection | `db/connection.py` | Done |
| Pydantic Models | `db/models.py` | Done |
| Repositories | `db/repositories.py` | Done |
| Config (hardcoded credentials) | `config.py` | Done |
| Upstox Provider | `data/providers/upstox.py` | Done |
| NSE Provider (Nifty indices) | `data/providers/nse.py` | Done |
| Basic Universe Activities | `activities/universe.py` | Done |
| Universe Setup Activities | `activities/universe_setup.py` | Done |
| Basic Universe Workflow | `workflows/universe.py` | Done |
| Universe Setup Workflow | `workflows/universe_setup.py` | Done |
| Temporal Worker | `workers/universe_worker.py` | Done |
| Temporal Client | `workers/client.py` | Done |
| Workflow Starter | `workers/start_workflow.py` | Done |
| Streamlit UI | `ui/app.py` | Done |
| Docker Compose | `docker-compose.yml` | Done |
| Makefile | `Makefile` | Done |

#### Key Decisions Made

1. **Simplified Environment Strategy**
   - *Decision*: Single environment connecting to cloud services (Temporal Cloud + MongoDB Atlas) from anywhere
   - *Reasoning*: Personal project - no need for complex dev/staging/prod environments
   - *Impact*: Credentials hardcoded in `config.py` with env var fallback

2. **MTF Priority Over F&O**
   - *Decision*: Use NSE EQ + MTF lists instead of F&O list for universe
   - *Reasoning*: User explicitly requested "do not use f&o list only use nse eq and mtfs"
   - *Impact*: Quality scoring prioritizes MTF stocks (margin trading eligible = higher liquidity)

3. **Quality Scoring System**
   - *Decision*: Tier-based scoring with MTF as primary factor
   - *Scoring Logic*:
     ```
     Tier A (90-95): MTF + Nifty 50/100
     Tier B (60-75): MTF + Nifty 200/500 or MTF only
     Tier C (40-55): Non-MTF but in Nifty indices
     Tier D (10): Not in any index, not MTF (excluded)
     ```
   - *Reasoning*: MTF eligibility is a strong proxy for liquidity and institutional interest

4. **Merged Dashboard UI**
   - *Decision*: Combine all stock universe functionality into Dashboard page
   - *Reasoning*: User requested "merge everything into one dashboard - easier and faster"
   - *Impact*: Removed separate Stocks page, all on Dashboard

5. **Temporal Cloud from Day 1**
   - *Decision*: Use Temporal Cloud (ap-south-1) instead of local Temporal
   - *Reasoning*: Simpler deployment, reliable, user provided API key
   - *Impact*: No local Temporal setup needed

### Session 2: Phase 2 - Enhanced Momentum & Trend Filters (Dec 2024)

#### What Was Built

| Component | File(s) | Status |
|-----------|---------|--------|
| Market Data Provider | `data/providers/market_data.py` | Done |
| Momentum Filter Activities | `activities/momentum.py` | Done |
| Momentum Filter Workflow | `workflows/momentum_filter.py` | Done |
| Combined Workflow | `workflows/momentum_filter.py` (UniverseAndMomentumWorkflow) | Done |
| Worker Updates | `workers/universe_worker.py` | Done |
| UI Updates | `ui/app.py` | Done |

#### 5 Momentum Filters Implemented

**Filter 2A: 52-Week High Proximity (Quantitative)**
- Primary: Close within 0-10% of 52W High
- Secondary: Close within 10-20% + Volume Surge > 1.5x 20D Avg
- Formula: `Proximity_Score = (Close - 52W_Low) / (52W_High - 52W_Low) * 100`

**Filter 2B: Advanced Moving Average System (5-Layer)**
1. Close > 20-DMA (Short-term trend)
2. Close > 50-DMA (Intermediate trend)
3. Close > 200-DMA (Long-term trend)
4. 20-DMA > 50-DMA > 200-DMA (Perfect alignment)
5. ALL MAs sloping UP (thresholds: 20D >= 0.1%, 50D >= 0.05%, 200D >= 0.02%)
- Pass if 4+ conditions met

**Filter 2C: Multi-Timeframe Relative Strength**
- 1-Month RS: Stock > Nifty50 + 5%
- 3-Month RS: Stock > Nifty50 + 10%
- 6-Month RS: Stock > Nifty50 + 15%
- Pass if 2/3 horizons pass

**Filter 2D: Composite Momentum Score (0-100)**
```
Momentum_Score = 25% × 52W Proximity +
                 25% × RS Score (normalized) +
                 25% × MA Strength (out of 5) +
                 25% × Price Acceleration
```
- Pass if score >= 75

**Filter 2E: Volatility-Adjusted Momentum**
- Stock volatility <= 1.5x Nifty volatility
- Volatility-Adjusted RS = Raw RS / Volatility Ratio

**Qualification Rule:** Stock must pass 4 out of 5 filters

#### Data Source: Yahoo Finance (Free)

Instead of implementing complex Upstox OAuth, we use Yahoo Finance API:
- No authentication required
- 52-week historical data for all NSE stocks
- Nifty 50 benchmark data
- Rate-limited with 0.3s delay between calls

#### MongoDB Collections Added

```javascript
// momentum_scores collection
{
  symbol: "RELIANCE",
  momentum_score: 87.5,
  filters_passed: 5,
  qualifies: true,
  proximity_52w: 92.3,
  high_52w: 2856.50,
  close: 2780.25,
  volume_surge: 1.8,
  filter_2a_pass: true,
  ma_alignment_score: 5,
  filter_2b_pass: true,
  rs_1m: 8.5,
  rs_3m: 15.2,
  rs_6m: 22.1,
  filter_2c_pass: true,
  filter_2d_pass: true,
  volatility_ratio: 1.1,
  filter_2e_pass: true,
  calculated_at: ISODate()
}
```

#### UI Enhancements

- New "Momentum Analysis (Phase 2)" section on Dashboard
- Three metrics: Momentum Qualified, Total Analyzed, Pass Rate
- Two buttons: "Run Momentum Filter" and "Full Weekend Run"
- New "Momentum Qualified" tab showing stocks that pass 4+ filters
- Styled dataframe with green/red highlighting for filter pass/fail

### Session 3: Phase 3 - Weekly Return Consistency Engine (Dec 2024)

#### What Was Built

| Component | File(s) | Status |
|-----------|---------|--------|
| Weekly Data Fetcher | `data/providers/market_data.py` (extended) | Done |
| Consistency Filter Activities | `activities/consistency.py` | Done |
| Consistency Filter Workflow | `workflows/consistency_filter.py` | Done |
| Full Pipeline Workflow | `workflows/consistency_filter.py` (FullPipelineWorkflow) | Done |
| Worker Updates | `workers/universe_worker.py` | Done |
| UI Updates | `ui/app.py` | Done |

#### 9-Metric Consistency Framework Implemented

**Core Metrics (52W):**
1. **Positive Weeks %**: Percentage of weeks with positive returns (≥65% threshold, regime-adjusted)
2. **+3% Weeks %**: Percentage of weeks with ≥3% returns (25-35% sweet spot)
3. **+5% Weeks %**: Percentage of weeks with ≥5% returns
4. **Weekly Std Dev**: Volatility control (≤6% threshold, regime-adjusted)
5. **Avg Weekly Return**: Average weekly percentage return
6. **Sharpe Ratio (Weekly)**: Risk-adjusted returns (≥0.15 threshold, regime-adjusted)
7. **Sortino Ratio**: Downside risk-adjusted returns

**Composite Scores:**
8. **Consistency Score (0-100)**: Weighted composite of normalized metrics
   ```
   25% × Pos%_norm + 25% × Plus3%_norm + 20% × (1/Vol_norm) + 15% × Sharpe_norm + 15% × WinStreak_norm
   ```
9. **Regime Score**: 13W vs 52W performance ratio (≥1.0 = maintaining or improving)
10. **Final Score**: Ranking score for stock selection
    ```
    40% × Consistency + 25% × Regime_norm + 20% × Percentile + 15% × Sharpe_norm
    ```

#### Dynamic Regime-Adaptive Thresholds

| Metric | BULL | SIDEWAYS | BEAR |
|--------|------|----------|------|
| Positive % Min | 60% | 65% | 70% |
| +3% Weeks Min | 22% | 25% | 20% |
| +3% Weeks Max | 40% | 35% | 30% |
| Volatility Max | 6.5% | 6.0% | 4.5% |
| Sharpe Min | 0.12 | 0.15 | 0.18 |

**Regime Detection:**
- BULL: Nifty > 50 DMA by 5%+
- BEAR: Nifty < 200 DMA
- SIDEWAYS: Between

#### MongoDB Collections Added

```javascript
// consistency_scores collection
{
  symbol: "RELIANCE",
  pos_pct_52w: 67.3,
  plus3_pct_52w: 28.8,
  std_dev_52w: 4.2,
  sharpe_52w: 0.22,
  sortino_52w: 0.35,
  consistency_score: 84.6,
  regime_score: 1.28,
  final_score: 89.3,
  market_regime: "BULL",
  filters_passed: 6,
  qualifies: true,
  passes_pos_pct: true,
  passes_plus3_pct: true,
  passes_volatility: true,
  passes_sharpe: true,
  passes_consistency: true,
  passes_regime: true,
  calculated_at: ISODate()
}
```

#### UI Enhancements (Phase 3)

- New "Consistency Analysis (Phase 3)" section on Dashboard
- Metrics: Consistency Qualified, Total Analyzed, Pass Rate, Market Regime
- Two buttons: "Run Consistency Filter" and "Full Pipeline (1-3)"
- New "Consistency Qualified" tab showing stocks that pass 5+ filters
- Styled dataframe with green/red highlighting for filter pass/fail
- Market regime indicator (BULL/SIDEWAYS/BEAR)

#### Pipeline Summary

```
Phase 1: Universe Setup
~2400 NSE EQ → ~1400 High Quality (score ≥ 60)

Phase 2: Momentum Filter
~1400 → ~50-100 Momentum Qualified (4+/5 filters)

Phase 3: Consistency Filter
~50-100 → ~30-50 Consistency Qualified (5+/6 filters)
```

### Session 4: Phase 4 - Volume & Liquidity + Setup Detection (Dec 2024)

#### What Was Built

| Component | File(s) | Status |
|-----------|---------|--------|
| Volume & Liquidity Methods | `data/providers/market_data.py` (extended) | Done |
| Setup Detection Methods | `data/providers/market_data.py` (extended) | Done |
| Volume Liquidity Activities | `activities/volume_liquidity.py` | Done |
| Setup Detection Activities | `activities/setup_detection.py` | Done |
| Volume Filter Workflow | `workflows/volume_filter.py` | Done |
| Setup Detection Workflow | `workflows/setup_detection.py` | Done |
| Phase 4 Pipeline Workflow | `workflows/setup_detection.py` (Phase4PipelineWorkflow) | Done |
| Full Analysis Pipeline | `workflows/setup_detection.py` (FullAnalysisPipelineWorkflow) | Done |
| Worker Updates | `workers/universe_worker.py` | Done |
| UI Updates | `ui/app.py` | Done |

#### Phase 4A: Volume & Liquidity Filters

**Multi-Dimensional Liquidity Scoring (0-100):**
```
Liquidity_Score = 40% × Turnover_20D_norm +
                  30% × Turnover_60D_norm +
                  20% × Peak_Turnover_norm +
                  10% × Volume_Stability

Thresholds:
- Turnover_20D: ≥ Rs.10 Cr
- Turnover_60D: ≥ Rs.8 Cr
- Peak_Turnover_30D: ≥ Rs.50 Cr
- Liquidity_Score: ≥ 75
```

**Filter Criteria:**
1. Liquidity Score ≥ 75
2. 20D Avg Turnover ≥ Rs.10 Cr
3. Circuit Hits (30D) ≤ 1
4. Average Gap ≤ 2%

**Reduces:** ~30-50 → ~15-25 stocks

#### Phase 4B: Technical Setup Detection

**4 Setup Types Implemented:**

**Type A: PULLBACK (Enhanced Trend Pullback)**
- Price near 20/50-DMA (95-103%)
- Volume contraction (last 3 days ≤ 70% of 20D avg)
- RSI(14) in 35-55 zone
- MACD histogram turning positive
- In uptrend (price > 50-DMA > 200-DMA)
- Hammer candlestick detection

**Type B: VCP_BREAKOUT (Volatility Contraction Pattern)**
- Range contraction (≤ 12%)
- Consolidation (price within 5% of range midpoint)
- Declining volatility (ATR14 < ATR14_21d_ago)
- Near breakout (upper 70% of range)
- Weekly range tightening

**Type C: RETEST (Breakout Retest)**
- Recent breakout (last 2-3 weeks) with high volume (≥2.5x)
- Price holding above breakout level (≥97%)
- Volume dry-up on retest (≤60% of breakout volume)
- Higher low formation

**Type D: GAP_FILL (Gap-Fill Continuation)**
- Recent gap up (0.5-2%) in uptrend
- Gap partially filled (50-75%)
- Volume expansion on gap day (≥1.8x)
- Gap above rising 20-DMA

**Entry/Stop/Target Calculation:**
- Entry Zone: Support level ± 0.5 × ATR14
- Stop Loss: min(Swing_Low × 0.99, Entry - 2 × ATR14)
- Target 1: Entry + 2R
- Target 2: Entry + 3R (or 52W high)

**Reduces:** ~15-25 → ~8-15 trade setups

#### MongoDB Collections Added

```javascript
// liquidity_scores collection
{
  symbol: "RELIANCE",
  liquidity_score: 94.2,
  turnover_20d_cr: 2450,
  turnover_60d_cr: 2100,
  peak_turnover_30d_cr: 5200,
  vol_ratio_5d: 2.8,
  vol_stability: 85.2,
  circuit_hits_30d: 0,
  avg_gap_pct: 0.8,
  liq_qualifies: true,
  passes_liq_score: true,
  passes_turnover: true,
  passes_circuit: true,
  passes_gap: true,
  calculated_at: ISODate()
}

// trade_setups collection
{
  symbol: "TCS",
  type: "PULLBACK",
  rank: 1,
  entry_low: 3200,
  entry_high: 3220,
  stop: 3150,
  target_1: 3360,
  target_2: 3440,
  rr_ratio: 2.1,
  confidence: 92,
  overall_quality: 88.5,
  momentum_score: 85.2,
  consistency_score: 78.4,
  liquidity_score: 94.2,
  market_regime: "BULL",
  status: "active",
  qualifies: true,
  detected_at: ISODate()
}
```

#### UI Enhancements (Phase 4)

- New "Volume & Liquidity (Phase 4A)" section on Dashboard
- Metrics: Liquidity Qualified, Total Analyzed, Pass Rate
- Buttons: "Run Volume Filter" and "Phase 4 Pipeline"
- New "Trade Setups (Phase 4B)" section on Dashboard
- Metrics: Trade Setups, Setups Found, Qualified Rate, Regime
- Buttons: "Run Setup Detection" and "Full Analysis (1-4)"
- New "Trade Setups" tab showing setups with entry/stop/target levels
- New "Liquidity Qualified" tab showing liquidity scores
- Setup type filter dropdown

#### Complete Pipeline Summary

```
Phase 1: Universe Setup
~2400 NSE EQ → ~1400 High Quality (score ≥ 60)

Phase 2: Momentum Filter
~1400 → ~50-100 Momentum Qualified (4+/5 filters)

Phase 3: Consistency Filter
~50-100 → ~30-50 Consistency Qualified (5+/6 filters)

Phase 4A: Volume & Liquidity Filter
~30-50 → ~15-25 Liquidity Qualified (3+/4 filters)

Phase 4B: Setup Detection
~15-25 → ~8-15 Trade Setups (Pullback, VCP, Retest, Gap-Fill)
```

#### Current Files Structure

```
src/trade_analyzer/
├── __init__.py
├── main.py
├── config.py                    # Hardcoded credentials (MongoDB, Temporal)
├── db/
│   ├── __init__.py
│   ├── connection.py            # MongoDB singleton connection
│   ├── models.py                # Pydantic models (StockDoc, TradeDoc, etc.)
│   └── repositories.py          # Data access layer
├── data/
│   ├── __init__.py
│   └── providers/
│       ├── __init__.py
│       ├── upstox.py            # Upstox instrument fetcher
│       ├── nse.py               # NSE Nifty indices fetcher
│       └── market_data.py       # Yahoo Finance OHLCV + weekly + indicators + setups
├── activities/
│   ├── __init__.py
│   ├── universe.py              # Basic fetch/save activities
│   ├── universe_setup.py        # Enriched universe with quality scoring
│   ├── momentum.py              # 5 momentum filter activities (Phase 2)
│   ├── consistency.py           # 9-metric consistency activities (Phase 3)
│   ├── volume_liquidity.py      # Volume & liquidity activities (Phase 4A)
│   └── setup_detection.py       # Setup detection activities (Phase 4B)
├── workflows/
│   ├── __init__.py
│   ├── universe.py              # Basic refresh workflow
│   ├── universe_setup.py        # Full setup workflow with enrichment
│   ├── momentum_filter.py       # Momentum + Combined workflows (Phase 2)
│   ├── consistency_filter.py    # Consistency + Full Pipeline (Phase 3)
│   ├── volume_filter.py         # Volume & Liquidity workflow (Phase 4A)
│   └── setup_detection.py       # Setup Detection + Phase 4 Pipeline + Full Analysis (Phase 4B)
├── workers/
│   ├── __init__.py
│   ├── client.py                # Temporal Cloud client
│   ├── universe_worker.py       # Worker process (all phases)
│   └── start_workflow.py        # Workflow trigger script (all phases)
└── ui/
    ├── __init__.py
    ├── app.py                   # Streamlit app (Phase 1-4 complete)
    └── pages/
        └── __init__.py
```

#### Workflow: UniverseSetupWorkflow

```
Step 1: fetch_base_universe()
  - Fetches NSE.json.gz from Upstox
  - Filters for NSE_EQ segment, instrument_type=EQ
  - Fetches MTF.json.gz from Upstox
  - Returns: ~2370 NSE EQ instruments, ~1426 MTF symbols

Step 2: fetch_nifty_indices()
  - Fetches Nifty 50/100/200/500 constituents from NSE API
  - Returns: ~50, ~100, ~200, ~500 symbols respectively

Step 3: enrich_and_score_universe()
  - For each NSE EQ instrument:
    - Check if in MTF list (highest priority)
    - Check Nifty index membership
    - Calculate quality_score and liquidity_tier
  - Returns: Enriched list sorted by quality_score

Step 4: save_enriched_universe()
  - Marks all existing stocks as inactive
  - Upserts enriched stocks
  - Creates indexes for efficient queries
  - Returns: Stats (tier counts, high quality count)
```

---

## Critical Insights (Read First)

### Realistic Expectations

| Metric | Optimistic | Realistic |
|--------|------------|-----------|
| Win Rate | 55-60% | 50-55% |
| Average Win | 1.5R | 1.2R |
| Average Loss | 1.0R | 1.1R |
| EV per Trade (gross) | 0.44R | 0.11R |
| EV per Trade (after costs/taxes) | 0.35R | 0.05-0.10R |
| Weekly Return | 3-5% | 0.5-1.5% |
| Annual Return | 100%+ | 15-30% |
| Max Drawdown | 10% | 15-25% |

### Transaction Costs (India-Specific)

For Rs.1,00,000 trade value:
- STT (buy + sell): Rs.200 (0.2%)
- Brokerage: Rs.40 (0.04%)
- GST on brokerage: Rs.7
- Exchange fees: Rs.7
- Stamp duty: Rs.15
- **Total round-trip: ~Rs.270 (0.27%)**

Plus 15% STCG tax on profits.

**Critical:** You need >0.2R per trade GROSS just to break even after costs.

### Where the Edge Actually Comes From

1. **Regime Awareness** - Not trading in bad environments
2. **Selection Discipline** - "No trade" is valid output
3. **Risk Management** - Surviving drawdowns to compound
4. **Consistency** - Running the system for years, not weeks

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              TRADE ANALYZER                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │  Streamlit  │    │  Temporal   │    │   MongoDB   │    │   Upstox    │  │
│  │     UI      │    │   Cloud     │    │   Atlas     │    │    API      │  │
│  │  (Decisions)│    │ (Workflows) │    │ (Persistence│    │   (Data)    │  │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │
│         │                  │                  │                  │         │
│         └──────────────────┼──────────────────┼──────────────────┘         │
│                            │                  │                            │
│                    ┌───────▼──────────────────▼───────┐                    │
│                    │         Python Backend           │                    │
│                    │  - Workflows (Temporal)          │                    │
│                    │  - Activities (Business Logic)   │                    │
│                    │  - Workers (Execution)           │                    │
│                    └──────────────────────────────────┘                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Workflow-Driven Recommendation Pipeline

The entire system is built around **Temporal workflows** that produce actionable recommendations. The **Streamlit UI** serves as the decision interface where users can:
- Trigger workflows
- Review intermediate results
- Override automated decisions
- Approve final recommendations

### Master Workflow: WeeklyRecommendationWorkflow

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    WEEKLY RECOMMENDATION WORKFLOW                           │
│                    (Triggered: Saturday/Sunday)                            │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  STEP 1: UniverseSetupWorkflow (DONE)                                      │
│  ├─ fetch_base_universe()          - NSE EQ + MTF from Upstox             │
│  ├─ fetch_nifty_indices()          - Nifty 50/100/200/500                 │
│  ├─ enrich_and_score_universe()    - Quality scoring                      │
│  └─ save_enriched_universe()       - Persist to MongoDB                   │
│      │                                                                     │
│      ▼ UI: Dashboard shows stats, user can review universe                │
│                                                                            │
│  STEP 2: MarketDataWorkflow (Phase 2)                                      │
│  ├─ fetch_historical_ohlcv()       - Last 52 weeks daily data             │
│  ├─ calculate_indicators()         - MA, ATR, RSI, Volume                 │
│  ├─ fetch_index_data()             - Nifty 50/500, VIX                    │
│  └─ save_market_data()             - Persist to MongoDB                   │
│      │                                                                     │
│      ▼ UI: Show data freshness, any gaps/issues                           │
│                                                                            │
│  STEP 3: RegimeAssessmentWorkflow (Phase 3) - CRITICAL GATE               │
│  ├─ calculate_trend_score()        - Nifty vs MAs, slopes                 │
│  ├─ calculate_breadth_score()      - % stocks above 200 DMA               │
│  ├─ calculate_volatility_score()   - VIX level and trend                  │
│  ├─ calculate_leadership_score()   - Cyclicals vs Defensives              │
│  └─ classify_regime()              - Risk-On / Choppy / Risk-Off          │
│      │                                                                     │
│      ▼ UI DECISION POINT: Review regime, can OVERRIDE                     │
│      │ if Risk-Off: STOP (no recommendations this week)                   │
│      │ if Choppy:   Continue with reduced size                            │
│      │ if Risk-On:  Continue with full size                               │
│                                                                            │
│  STEP 4: UniverseFilterWorkflow (Phase 3)                                  │
│  ├─ apply_liquidity_filters()      - Turnover, market cap                 │
│  ├─ apply_momentum_filters()       - 52w high, MA alignment, RS           │
│  ├─ apply_consistency_filters()    - Weekly win %, statistical sig        │
│  └─ rank_by_factors()              - Composite score ranking              │
│      │                                                                     │
│      ▼ UI: Show filtered universe (~80 stocks), filter stats              │
│                                                                            │
│  STEP 5: SetupDetectionWorkflow (Phase 3)                                  │
│  ├─ detect_pullback_setups()       - Type A: Trend pullback               │
│  ├─ detect_breakout_setups()       - Type B: Consolidation breakout       │
│  ├─ detect_retest_setups()         - Type C: Breakout retest              │
│  └─ calculate_entry_stop_target()  - Price levels for each                │
│      │                                                                     │
│      ▼ UI: Show detected setups (~15-20), setup details                   │
│                                                                            │
│  STEP 6: RiskGeometryWorkflow (Phase 4)                                    │
│  ├─ validate_reward_risk()         - Min 2.0R (Risk-On), 2.5R (Choppy)    │
│  ├─ validate_stop_distance()       - Max 7% from entry                    │
│  ├─ calculate_position_size()      - Based on 1.5% risk                   │
│  └─ apply_regime_multiplier()      - Adjust for regime state              │
│      │                                                                     │
│      ▼ UI: Show valid setups with position sizes (~8-12)                  │
│                                                                            │
│  STEP 7: PortfolioConstructionWorkflow (Phase 4)                           │
│  ├─ calculate_correlations()       - Max 0.70 correlation                 │
│  ├─ apply_sector_limits()          - Max 3 per sector, 25% exposure       │
│  ├─ select_final_positions()       - Top 3-7 by composite score           │
│  └─ generate_recommendations()     - Final trade recommendations          │
│      │                                                                     │
│      ▼ UI DECISION POINT: FINAL APPROVAL                                  │
│        - Review 3-7 recommendations                                        │
│        - Modify entry/stop/target if needed                                │
│        - Approve for execution                                             │
│        - Reject individual setups                                          │
│                                                                            │
│  OUTPUT: 3-7 Trade Recommendations with:                                   │
│  - Symbol, Entry Zone, Stop Loss, Target 1, Target 2                       │
│  - Position Size, Risk Amount, R:R Ratio                                   │
│  - Setup Type, Thesis, Invalidation Conditions                             │
│  - Gap Contingency Rules                                                   │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### UI Decision Points Summary

| Workflow Step | UI Page | User Actions |
|--------------|---------|--------------|
| UniverseSetup | Dashboard | Trigger refresh, review stats |
| MarketData | Dashboard | View data freshness, flag issues |
| RegimeAssessment | **Regime** | **CRITICAL: Override regime if needed** |
| UniverseFilter | Dashboard | Review filtered universe |
| SetupDetection | **Setups** | View all detected setups |
| RiskGeometry | Setups | Review position sizes |
| PortfolioConstruction | **Setups** | **FINAL: Approve/reject recommendations** |

### Workflow Files Structure (Planned)

```
src/trade_analyzer/
├── workflows/
│   ├── universe.py              # Basic refresh (DONE)
│   ├── universe_setup.py        # Full setup with enrichment (DONE)
│   ├── market_data.py           # Historical data + indicators (Phase 2)
│   ├── regime.py                # Regime assessment (Phase 3)
│   ├── universe_filter.py       # Universe filtering (Phase 3)
│   ├── setup_detection.py       # Setup pattern detection (Phase 3)
│   ├── risk_geometry.py         # Risk validation (Phase 4)
│   ├── portfolio.py             # Portfolio construction (Phase 4)
│   └── weekly_recommendation.py # Master workflow (Phase 4)
├── activities/
│   ├── universe.py              # Universe fetch/save (DONE)
│   ├── universe_setup.py        # Enrichment activities (DONE)
│   ├── market_data.py           # OHLCV + indicators (Phase 2)
│   ├── regime.py                # Regime calculation (Phase 3)
│   ├── filters.py               # Universe filtering (Phase 3)
│   ├── setups.py                # Setup detection (Phase 3)
│   ├── risk.py                  # Risk calculation (Phase 4)
│   └── portfolio.py             # Portfolio construction (Phase 4)
└── workers/
    ├── universe_worker.py       # Universe workflows (DONE)
    ├── market_data_worker.py    # Market data workflows (Phase 2)
    └── recommendation_worker.py # Analysis + recommendation (Phase 3-4)
```

### Task Queues

| Queue | Workflows | Worker |
|-------|-----------|--------|
| `trade-analyzer-universe-refresh` | UniverseSetup | universe_worker.py |
| `trade-analyzer-market-data` | MarketData | market_data_worker.py |
| `trade-analyzer-recommendation` | Regime, Filter, Setup, Risk, Portfolio | recommendation_worker.py |

---

## UI Pages & Workflow Integration

### Dashboard Page (Current)
**Workflows:** UniverseSetupWorkflow
**Functions:**
- Display universe statistics (Total, MTF, Tiers, High Quality)
- "Setup Universe" button triggers UniverseSetupWorkflow
- Show stock lists (All, High Quality, MTF Only)
- Display last updated timestamp
- (Phase 2) Show market data freshness

### Regime Page (Phase 3)
**Workflows:** RegimeAssessmentWorkflow
**Functions:**
- Display current regime state with probabilities
- Show 4-factor breakdown (Trend, Breadth, Volatility, Leadership)
- **OVERRIDE CONTROL**: Manually set regime if automated assessment seems wrong
- Historical regime chart
- Position multiplier display

### Setups Page (Phase 3-4)
**Workflows:** SetupDetectionWorkflow, RiskGeometryWorkflow, PortfolioConstructionWorkflow
**Functions:**
- Display all detected setups with details
- Filter by setup type (Pullback, Breakout, Retest)
- Show position sizing for each setup
- **APPROVAL CONTROLS**:
  - Approve/Reject individual setups
  - Modify entry/stop/target values
  - Approve final portfolio
- Export approved setups as order list

### Trades Page (Phase 5)
**Workflows:** (Manual entry or execution integration)
**Functions:**
- Track executed trades
- P&L and R-multiple tracking
- Trade history
- Performance metrics

### Settings Page (Current - Placeholder)
**Functions:**
- Risk parameters (max risk %, R:R requirements)
- Sector exposure limits
- Position limits per regime
- (Future) Notification settings

## Implementation Phases (Workflow-Centric)

### Phase 1: Foundation (COMPLETED)

**Workflow:** UniverseSetupWorkflow
**UI:** Dashboard (trigger + display)

| Component | File | Status |
|-----------|------|--------|
| MongoDB Connection | `db/connection.py` | Done |
| Pydantic Models | `db/models.py` | Done |
| Repositories | `db/repositories.py` | Done |
| Config | `config.py` | Done |
| Upstox Provider | `data/providers/upstox.py` | Done |
| NSE Provider | `data/providers/nse.py` | Done |
| Universe Activities | `activities/universe.py`, `activities/universe_setup.py` | Done |
| Universe Workflows | `workflows/universe.py`, `workflows/universe_setup.py` | Done |
| Universe Worker | `workers/universe_worker.py` | Done |
| Streamlit UI | `ui/app.py` | Done |
| Docker + Makefile | `docker-compose.yml`, `Makefile` | Done |

---

### Phase 2: Momentum & Trend Filters (COMPLETED)

**Workflow:** MomentumFilterWorkflow, UniverseAndMomentumWorkflow
**UI:** Dashboard (Momentum Analysis section + Momentum Qualified tab)

#### 2.1 MomentumFilterWorkflow Activities
| Activity | Description | Status |
|----------|-------------|--------|
| `fetch_high_quality_symbols()` | Get stocks with quality_score >= 60 | Done |
| `fetch_market_data_batch()` | Get 52-week daily OHLCV from Yahoo Finance | Done |
| `fetch_nifty_benchmark_data()` | Nifty 50 prices and returns | Done |
| `calculate_momentum_scores()` | Apply 5 filters, calculate composite score | Done |
| `save_momentum_results()` | Save to momentum_scores collection | Done |

#### 2.2 5 Momentum Filters
| Filter | Description | Threshold |
|--------|-------------|-----------|
| 2A: 52W Proximity | Close within 10% of 52W High | proximity >= 90% OR (proximity >= 80% AND volume >= 1.5x) |
| 2B: MA Alignment | 5-layer MA check | 4+ conditions pass |
| 2C: Relative Strength | Outperformance vs Nifty 50 | 2/3 horizons pass |
| 2D: Momentum Score | Composite 0-100 score | score >= 75 |
| 2E: Volatility Control | Risk-adjusted momentum | vol_ratio <= 1.5x |

**Qualification:** Stock must pass 4 out of 5 filters

#### 2.3 Data Source
- Yahoo Finance (free, no auth required)
- ~400 days of OHLCV history for 200 DMA calculation
- Rate-limited with 0.3s delay between API calls

#### 2.4 UI Updates
- [x] Dashboard: Momentum Analysis section with metrics
- [x] Dashboard: "Run Momentum Filter" button
- [x] Dashboard: "Full Weekend Run" button (Universe + Momentum)
- [x] Dashboard: "Momentum Qualified" tab with filter details

---

### Phase 3: Analysis Pipeline

#### 3.1 RegimeAssessmentWorkflow (CRITICAL GATE)

**UI:** Regime Page (display + OVERRIDE)

| Activity | Description | Status |
|----------|-------------|--------|
| `calculate_trend_score()` | Nifty vs 20/50/200 DMA, MA slopes | Not Started |
| `calculate_breadth_score()` | % universe above 200 DMA | Not Started |
| `calculate_volatility_score()` | VIX level (12-18-25 bands), trend | Not Started |
| `calculate_leadership_score()` | Cyclicals vs Defensives ratio | Not Started |
| `classify_regime()` | Combine scores -> Risk-On/Choppy/Risk-Off | Not Started |

**Regime Logic:**
```python
class RegimeState(Enum):
    RISK_ON = "risk_on"      # Full system active
    CHOPPY = "choppy"        # Pullbacks only, 50% size
    RISK_OFF = "risk_off"    # NO NEW POSITIONS

# Position multiplier based on risk_on probability
if risk_on_prob > 0.70: multiplier = 1.0
elif risk_on_prob > 0.50: multiplier = 0.7
elif risk_off_prob > 0.50: multiplier = 0.0  # STOP
else: multiplier = 0.5
```

**UI Decision Point:**
- Display regime with probabilities and confidence
- Show 4-factor breakdown with charts
- **OVERRIDE BUTTON**: User can manually set regime
- Saved regime applies to all downstream workflows

#### 3.2 UniverseFilterWorkflow

**UI:** Dashboard (filtered list display)

| Activity | Description | Status |
|----------|-------------|--------|
| `apply_liquidity_filters()` | Turnover >= Rs.5 Cr, Market cap >= Rs.1000 Cr | Not Started |
| `apply_momentum_filters()` | Within 10% of 52w high, MA alignment, RS > Nifty | Not Started |
| `apply_consistency_filters()` | >55% positive weeks, statistical significance | Not Started |
| `rank_by_factors()` | Composite score from momentum + consistency | Not Started |

**Output:** ~80 stocks ranked by composite score

#### 3.3 SetupDetectionWorkflow

**UI:** Setups Page (display detected setups)

| Activity | Description | Status |
|----------|-------------|--------|
| `detect_pullback_setups()` | Uptrend + 3-10% pullback to rising MA | Not Started |
| `detect_breakout_setups()` | 3-8 week consolidation + volume breakout | Not Started |
| `detect_retest_setups()` | Recent breakout + retest of former resistance | Not Started |
| `calculate_entry_stop_target()` | Entry zone, stop (swing/ATR), targets | Not Started |

**Output:** ~15-20 setups with price levels

---

### Phase 4: Risk & Portfolio

#### 4.1 RiskGeometryWorkflow

**UI:** Setups Page (position sizing display)

| Activity | Description | Status |
|----------|-------------|--------|
| `validate_reward_risk()` | Min 2.0R (Risk-On), 2.5R (Choppy) | Not Started |
| `validate_stop_distance()` | Max 7% from entry | Not Started |
| `calculate_position_size()` | Based on 1.5% risk per trade | Not Started |
| `apply_regime_multiplier()` | Adjust size by regime state | Not Started |

**Output:** ~8-12 valid setups with position sizes

#### 4.2 PortfolioConstructionWorkflow

**UI:** Setups Page (FINAL APPROVAL)

| Activity | Description | Status |
|----------|-------------|--------|
| `calculate_correlations()` | Reject if correlation > 0.70 | Not Started |
| `apply_sector_limits()` | Max 3 per sector, 25% exposure | Not Started |
| `select_final_positions()` | Top 3-7 by composite score | Not Started |
| `generate_recommendations()` | Full trade recommendation with all details | Not Started |

**Output:** 3-7 Trade Recommendations

**UI Decision Point (FINAL APPROVAL):**
- Display final recommendations with all details
- **APPROVE/REJECT** buttons per setup
- **MODIFY** entry/stop/target values
- **EXPORT** approved as order list
- Gap contingency rules displayed

---

### Phase 5: Execution & Monitoring

#### 5.1 Trade Tracking

**UI:** Trades Page

| Feature | Description | Status |
|---------|-------------|--------|
| Manual trade entry | Record executed trades | Not Started |
| P&L calculation | Real-time P&L tracking | Not Started |
| R-multiple tracking | Track performance in R terms | Not Started |
| Trade history | All closed trades with details | Not Started |

#### 5.2 System Health Monitoring

| Feature | Description | Status |
|---------|-------------|--------|
| Win rate (12w, 52w) | Rolling win rate calculation | Not Started |
| Expectancy | Average R per trade | Not Started |
| Drawdown monitor | Current and max drawdown | Not Started |
| Health score | 0-100 composite score | Not Started |
| Alerts | Warning when health < 50 | Not Started |

---

## Configuration

All credentials configured in `src/trade_analyzer/config.py`. No environment variables needed.

### MongoDB (DigitalOcean)
```
Host: mongodb+srv://db-trading-setup-4aad9e87.mongo.ondigitalocean.com
Database: trade_analysis
Username: doadmin
```

### Temporal Cloud
```
Address: ap-south-1.aws.api.temporal.io:7233
Namespace: trade-discovere.y8vfp
Region: Asia Pacific (Mumbai)
Authentication: API Key
```

### Task Queues
- `trade-analyzer-universe-refresh` - Universe data refresh
- `trade-analyzer-regime-analysis` - Regime assessment (planned)
- `trade-analyzer-pipeline` - Trading pipeline (planned)

---

## Commands

```bash
# Run locally
make ui        # Start Streamlit UI
make worker    # Start Temporal worker
make refresh   # Trigger universe refresh

# Run in Docker
make up        # Start all services
make down      # Stop services
make logs      # View logs

# CI
make test      # Run tests
make allci     # Run all CI steps
```

---

## Weekly Cycle (Workflow-Driven)

### Weekend Analysis (Saturday/Sunday)

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: UniverseSetupWorkflow                                  │
│  [Dashboard] Click "Setup Universe"                             │
│  -> Fetches NSE EQ + MTF + Nifty indices                        │
│  -> Enriches with quality scores                                │
│  -> Dashboard shows updated stats                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: MarketDataWorkflow                                     │
│  [Dashboard] Click "Refresh Market Data"                        │
│  -> Fetches 52-week OHLCV for high-quality stocks               │
│  -> Calculates indicators (MA, ATR, RSI)                        │
│  -> Dashboard shows data freshness                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: RegimeAssessmentWorkflow (GATE)                        │
│  [Regime] Click "Run Regime Analysis"                           │
│  -> Calculates 4 factors (Trend, Breadth, VIX, Leadership)      │
│  -> Classifies: Risk-On / Choppy / Risk-Off                     │
│                                                                 │
│  ** USER DECISION **                                            │
│  - Review regime assessment                                     │
│  - Can OVERRIDE if automated assessment seems wrong             │
│  - If Risk-Off: STOP HERE (no trades this week)                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (if Risk-On or Choppy)
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: UniverseFilterWorkflow                                 │
│  [Runs automatically after regime approval]                     │
│  -> Applies liquidity, momentum, consistency filters            │
│  -> Dashboard shows ~80 filtered stocks                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 5: SetupDetectionWorkflow                                 │
│  [Runs automatically]                                           │
│  -> Detects Pullback, Breakout, Retest setups                   │
│  -> Setups page shows ~15-20 candidates                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 6: RiskGeometryWorkflow                                   │
│  [Runs automatically]                                           │
│  -> Validates R:R ratio, stop distance                          │
│  -> Calculates position sizes                                   │
│  -> Setups page shows ~8-12 valid setups                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 7: PortfolioConstructionWorkflow                          │
│  [Runs automatically]                                           │
│  -> Applies correlation, sector limits                          │
│  -> Selects final 3-7 positions                                 │
│                                                                 │
│  ** USER DECISION (FINAL) **                                    │
│  [Setups] Review final recommendations                          │
│  - APPROVE individual setups                                    │
│  - REJECT if not comfortable                                    │
│  - MODIFY entry/stop/target if needed                           │
│  - EXPORT approved list for execution                           │
└─────────────────────────────────────────────────────────────────┘
```

### Weekday Execution (Monday-Friday)

```
Monday Morning:
- Check gap contingency for each approved setup
- Execute valid orders (those not invalidated by gap)

Daily:
- Track active positions in Trades page
- Update P&L (manual entry or API integration)
- Monitor stop-loss/target hits
- Log trade closures with R-multiple
```

---

## Collections Schema

### stocks (Updated with Quality Fields)
```javascript
{
  symbol: "RELIANCE",
  name: "Reliance Industries Ltd",
  isin: "INE002A01018",
  instrument_key: "NSE_EQ|INE002A01018",
  exchange_token: "2885",
  segment: "NSE_EQ",
  instrument_type: "EQ",
  lot_size: 1,
  tick_size: 0.05,
  security_type: "EQ",
  short_name: "RELIANCE",

  // Quality enrichment
  is_mtf: true,
  in_nifty_50: true,
  in_nifty_100: true,
  in_nifty_200: true,
  in_nifty_500: true,
  quality_score: 95,        // 0-100
  liquidity_tier: "A",      // A, B, C, D

  is_active: true,
  last_updated: ISODate()
}
```

### trade_setups
```javascript
{
  stock_symbol: "RELIANCE",
  setup_type: "pullback",
  status: "active",
  entry_low: 2450,
  entry_high: 2480,
  stop_loss: 2380,
  target_1: 2600,
  target_2: 2750,
  reward_risk_ratio: 2.1,
  week_start: ISODate(),
  regime_state: "risk_on",
  composite_score: 78.5
}
```

### trades
```javascript
{
  stock_symbol: "RELIANCE",
  setup_id: ObjectId(),
  status: "active",
  entry_date: ISODate(),
  entry_price: 2465,
  shares: 40,
  stop_loss: 2380,
  target_1: 2600,
  exit_price: null,
  pnl: 0,
  r_multiple: 0
}
```

### regime_assessments
```javascript
{
  state: "risk_on",
  risk_on_prob: 0.72,
  choppy_prob: 0.20,
  risk_off_prob: 0.08,
  confidence: 0.85,
  position_multiplier: 1.0,
  timestamp: ISODate(),
  indicators: {
    nifty_vs_20dma: 1.02,
    breadth_above_200dma: 0.65,
    india_vix: 14.5
  }
}
```

---

## Data Sources

| Source | Data | Cost | Reliability |
|--------|------|------|-------------|
| Upstox | Instruments, OHLCV | Free API | Good |
| NSE Website | Index constituents | Free | Rate limited |
| India VIX | NSE website | Free | Daily only |

---

## Success Metrics

After 52 weeks of live/paper trading:

| Metric | Minimum | Target |
|--------|---------|--------|
| Win Rate | 48% | 53% |
| Avg R-Multiple | 0.05R | 0.15R |
| Expectancy (after costs) | Break-even | 0.10R |
| Max Drawdown | <25% | <15% |
| Sharpe Ratio | >0.5 | >1.0 |
| System Uptime | >95% | >99% |

---

## Next Steps

### Immediate: Test Phase 1-4
1. **Start Worker** - Run `make worker` to start Temporal worker
2. **Start UI** - Run `make ui` to start Streamlit dashboard
3. **Test Universe Setup** - Click "Setup Universe" button
4. **Test Momentum Filter** - Click "Run Momentum Filter" button
5. **Test Consistency Filter** - Click "Run Consistency Filter" button
6. **Test Volume Filter** - Click "Run Volume Filter" button
7. **Test Setup Detection** - Click "Run Setup Detection" button
8. **Test Full Analysis** - Click "Full Analysis (1-4)" for end-to-end run
9. **Verify Results** - Check all tabs for filtered stocks and trade setups

### Phase 5: Risk Geometry & Portfolio (NEXT)
10. Create `workflows/risk_geometry.py` with RiskGeometryWorkflow
11. Implement R:R validation (min 2.0R Risk-On, 2.5R Choppy)
12. Position sizing based on 1.5% risk per trade
13. Regime multiplier adjustment
14. Create `workflows/portfolio.py` with PortfolioConstructionWorkflow
15. Implement correlation filter (max 0.70), sector limits (3/sector, 25% max)
16. Add approval controls to Setups page

### Phase 6: Execution & Tracking
17. Build Trades page with manual entry
18. Add P&L and R-multiple tracking
19. Implement system health monitoring (win rate, expectancy, drawdown)
20. Create master `workflows/weekly_recommendation.py`

---

## Completed Phases Summary

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Universe Setup (NSE EQ + MTF + Quality Scoring) | ✅ DONE |
| Phase 2 | Momentum Filter (5 filters, ~50-100 qualified) | ✅ DONE |
| Phase 3 | Consistency Filter (9 metrics, regime-adaptive) | ✅ DONE |
| Phase 4 | Setup Detection (Pullback, Breakout, Retest) | NOT STARTED |
| Phase 5 | Risk Geometry & Portfolio Construction | NOT STARTED |
| Phase 6 | Execution & Trade Tracking | NOT STARTED |

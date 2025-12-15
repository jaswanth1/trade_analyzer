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
| FundamentalFilterWorkflow | DONE | Dashboard: "Run Fundamental Filter" | Fundamental Scores |
| Phase5PipelineWorkflow | DONE | Dashboard: "Phase 5 Pipeline" | Fundamental + Holdings |
| RiskGeometryWorkflow | DONE | Dashboard: "Run Risk Geometry" | Position Sizes |
| Phase6PipelineWorkflow | DONE | Dashboard: "Phase 6 Pipeline" | Risk-Qualified Setups |
| PortfolioConstructionWorkflow | DONE | Dashboard: "Run Portfolio Construction" | Final Positions |
| Phase7PipelineWorkflow | DONE | Dashboard: "Phase 7 Pipeline" | Portfolio Allocation |
| PreMarketAnalysisWorkflow | DONE | Dashboard: "Run Pre-Market Analysis" | Monday Gap Analysis |
| PositionStatusWorkflow | DONE | Dashboard: "Update Position Status" | Position Alerts |
| FridayCloseWorkflow | DONE | Dashboard: "Run Friday Close" | Week Summary |
| ExecutionDisplayWorkflow | DONE | Dashboard: "Run Execution Display" | Full Execution View |
| WeeklyRecommendationWorkflow | DONE | Dashboard: "Generate Recommendations" | Trade Templates |
| WeeklyFullPipelineWorkflow | DONE | Dashboard: "Full Pipeline (4B-9)" | Complete Recommendations |

### Infrastructure Status

| Component | Status | Notes |
|-----------|--------|-------|
| MongoDB Atlas | DONE | DigitalOcean, trade_analysis DB |
| Temporal Cloud | DONE | ap-south-1, trade-discovere namespace |
| Streamlit UI | DONE | Dashboard with Phases 1-9 |
| Docker Compose | DONE | UI + Worker services |
| Yahoo Finance | DONE | Free OHLCV data (no auth needed) |
| FMP API | DONE | Financial statements (income, balance, cash flow) |
| Alpha Vantage API | DONE | Company overview data |
| NSE Holdings | DONE | FII/DII shareholding patterns |
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

### Session 5: Phases 5-9 - Fundamental Intelligence, Risk Management & Recommendations (Dec 2024)

#### What Was Built

| Component | File(s) | Status |
|-----------|---------|--------|
| Fundamental Data Provider | `data/providers/fundamental.py` | Done |
| NSE Holdings Provider | `data/providers/nse_holdings.py` | Done |
| Fundamental Activities | `activities/fundamental.py` | Done |
| Risk Geometry Activities | `activities/risk_geometry.py` | Done |
| Portfolio Construction Activities | `activities/portfolio_construction.py` | Done |
| Execution Activities | `activities/execution.py` | Done |
| Recommendation Activities | `activities/recommendation.py` | Done |
| Trade Setup Templates | `templates/trade_setup.py` | Done |
| Fundamental Filter Workflow | `workflows/fundamental_filter.py` | Done |
| Risk Geometry Workflow | `workflows/risk_geometry.py` | Done |
| Portfolio Construction Workflow | `workflows/portfolio_construction.py` | Done |
| Execution Workflows | `workflows/execution.py` | Done |
| Weekly Recommendation Workflow | `workflows/weekly_recommendation.py` | Done |
| Worker Updates | `workers/universe_worker.py` | Done |
| Workflow Starters | `workers/start_workflow.py` | Done |
| UI Updates (Phases 5-9) | `ui/app.py` | Done |
| Database Models (10 new) | `db/models.py` | Done |
| Database Indexes | `db/connection.py` | Done |
| Config Updates | `config.py` | Done |

#### Phase 5: AI-Enhanced Fundamental Intelligence

**Data Sources:**
- **FMP API**: Income statements, balance sheets, cash flow statements
- **Alpha Vantage API**: Company overview, EPS, PE ratios
- **NSE API**: FII/DII shareholding patterns, promoter pledge data

**5-Dimensional Fundamental Scoring (0-100):**
```
FUNDAMENTAL_SCORE = 30% × Growth_Score +
                   25% × Profitability_Score +
                   20% × Leverage_Score +
                   15% × Cash_Flow_Score +
                   10% × Earnings_Quality_Score
```

**Metrics Calculated:**
| Category | Metrics |
|----------|---------|
| Growth | EPS QoQ Growth, Revenue YoY Growth |
| Profitability | ROE, ROCE, Operating Margin |
| Leverage | Debt/Equity Ratio |
| Cash Flow | FCF Yield, Cash EPS vs Reported EPS |
| Earnings Quality | Cash EPS / Reported EPS ratio |

**Institutional Holdings Filter:**
- FII Holding ≥ 10%
- Total Institutional (FII + DII) ≥ 35%
- Promoter Pledge ≤ 20%
- FII Net Change (30D) ≥ 0

**Qualification Rule:** At least 3/5 fundamental filters must pass

**Activities (6):**
- `fetch_setup_qualified_symbols()` → Get symbols with active setups
- `fetch_fundamental_data_batch()` → Fetch from FMP + Alpha Vantage
- `calculate_fundamental_scores()` → Apply 5-dimensional scoring
- `fetch_institutional_holdings_batch()` → Get FII/DII from NSE
- `save_fundamental_results()` → Persist to MongoDB
- `get_fundamentally_qualified_symbols()` → Return qualified symbols

#### Phase 6: Dynamic Risk Geometry

**Multi-Method Stop-Loss Calculation:**
```python
Stop_Structure = Swing_Low × 0.99  # 1% below recent low
Stop_Volatility = Entry - (2 × ATR14)  # 2 ATR distance
Final_Stop = max(Stop_Structure, Stop_Volatility)  # Tighter of two
```

**Position Sizing Formula:**
```python
Base_Size = (Portfolio × Risk_Pct) / Risk_Per_Share
Vol_Adjusted = Base_Size × (Nifty_ATR / Stock_ATR)
Kelly_Fraction = (Win% × AvgWin - Loss% × AvgLoss) / AvgWin
FINAL_SIZE = Base_Size × Vol_Adjusted × min(1.0, Kelly) × Regime_Mult
```

**Risk Constraints:**
| Constraint | Value |
|------------|-------|
| Max Risk Per Trade | 1.5% |
| Max Stop Distance | 8% |
| Min R:R Ratio (Risk-On) | 2.0 |
| Min R:R Ratio (Choppy) | 2.5 |
| Max Kelly Fraction | 1.0 |

**Activities (4):**
- `fetch_fundamentally_enriched_setups()` → Get Phase 5 qualified setups
- `calculate_risk_geometry_batch()` → Calculate stops and targets
- `calculate_position_sizes()` → Apply sizing formula
- `save_risk_geometry_results()` → Persist to MongoDB

#### Phase 7: Portfolio Construction

**Correlation Filter:**
- Calculate rolling 60-day correlation matrix
- Reject pairs with correlation > 0.70
- Keep higher-ranked stock in correlated pairs

**Sector Concentration Limits:**
| Limit | Value |
|-------|-------|
| Max Stocks Per Sector | 3 |
| Max Sector Allocation | 25% |
| Max Single Position | 8% |
| Min Cash Reserve | 25-35% |
| Max Total Positions | 12 |

**Portfolio Construction Algorithm:**
1. Rank setups by overall quality score
2. Apply correlation filter (remove highly correlated)
3. Apply sector limits (max 3 per sector)
4. Select top positions up to capital limit
5. Calculate final allocations

**Activities (7):**
- `fetch_position_sized_setups()` → Get Phase 6 sized setups
- `calculate_correlation_matrix()` → 60-day rolling correlations
- `apply_correlation_filter()` → Remove correlated pairs
- `apply_sector_limits()` → Enforce sector constraints
- `construct_final_portfolio()` → Build final allocation
- `save_portfolio_allocation()` → Persist to MongoDB
- `get_latest_portfolio_allocation()` → Retrieve current portfolio

#### Phase 8: Execution Display (UI Only)

**Monday Pre-Market Analysis:**
```python
Gap Analysis Rules:
- Gap Through Stop: SKIP (don't enter)
- Small Gap Against (<2%): ENTER_AT_OPEN
- Gap Above Entry (>2%): SKIP (don't chase)
- Gap Below Entry (1-3%): WAIT_AND_WATCH
```

**Position Status Tracking:**
- Current price vs entry price
- Unrealized P&L and R-multiple
- Distance to stop and targets
- Alert generation (approaching stop, at target, etc.)

**Friday Close Summary:**
- Week's realized P&L
- Unrealized P&L on open positions
- Total R earned
- Win rate for the week
- System health score
- Recommended action for next week

**Activities (9):**
- `fetch_current_prices()` → Get live prices
- `analyze_monday_gaps()` → Gap contingency analysis
- `calculate_sector_momentum()` → Sector strength
- `update_position_status()` → Track active positions
- `generate_position_alerts()` → Create alerts
- `generate_friday_summary()` → Week summary
- `calculate_system_health()` → Health metrics
- `save_monday_premarket_analysis()` → Persist analysis
- `get_latest_premarket_analysis()` → Retrieve analysis

**Workflows (4):**
- `PreMarketAnalysisWorkflow` → Monday 8:30 AM analysis
- `PositionStatusWorkflow` → Intraday position updates
- `FridayCloseWorkflow` → Week summary and review
- `ExecutionDisplayWorkflow` → Full execution view

#### Phase 9: Production Trade Setup Templates

**Trade Setup Template Structure:**
```python
@dataclass
class TradeSetupTemplate:
    # Identification
    week_display: str  # "Dec 16-20, 2024"
    symbol: str
    company_name: str
    sector: str

    # Phase Scores (0-100)
    momentum_score: float
    consistency_score: float
    liquidity_score: float
    fundamental_score: float
    setup_confidence: float
    final_conviction: float  # 0-10 scale

    # Technical Context
    current_price: float
    high_52w: float
    dma_20: float
    dma_50: float
    dma_200: float
    atr_14: float

    # Setup Details
    setup_type: str
    entry_low: float
    entry_high: float
    stop_loss: float
    stop_distance_pct: float
    target_1: float
    target_2: float
    rr_ratio: float

    # Position Sizing
    shares: int
    investment_amount: float
    risk_amount: float
    position_pct: float

    # Execution
    gap_contingency: str
    action_steps: list[str]
    invalidation_conditions: list[str]
```

**Activities (6):**
- `aggregate_phase_results()` → Combine all phase data
- `generate_recommendation_templates()` → Create trade cards
- `save_weekly_recommendation()` → Persist recommendations
- `get_latest_weekly_recommendation()` → Retrieve current
- `approve_weekly_recommendation()` → Mark as approved
- `expire_old_recommendations()` → Clean up old entries

**Workflows (2):**
- `WeeklyRecommendationWorkflow` → Generate recommendation templates
- `FullPipelineWorkflow` → Run complete Phase 4B-9 pipeline

#### New MongoDB Collections (8)

```javascript
// fundamental_scores - Phase 5 scoring
{
  symbol: "RELIANCE",
  eps_qoq_growth: 15.2,
  revenue_yoy_growth: 12.8,
  roce: 18.5,
  roe: 22.3,
  debt_equity: 0.45,
  opm_margin: 16.2,
  fcf_yield: 5.8,
  earnings_quality_score: 92.5,
  growth_score: 78.4,
  profitability_score: 85.2,
  leverage_score: 72.1,
  cash_flow_score: 68.9,
  fundamental_score: 78.6,
  qualifies: true,
  calculated_at: ISODate()
}

// institutional_holdings - FII/DII ownership
{
  symbol: "RELIANCE",
  fii_holding_pct: 25.4,
  dii_holding_pct: 18.2,
  total_institutional: 43.6,
  fii_net_30d: 0.8,
  promoter_pledge_pct: 2.1,
  qualifies: true,
  fetched_at: ISODate()
}

// position_sizes - Phase 6 sizing
{
  symbol: "RELIANCE",
  setup_id: "setup_123",
  portfolio_value: 1000000,
  risk_pct: 0.015,
  entry_price: 2450,
  stop_loss: 2380,
  stop_distance_pct: 2.86,
  risk_per_share: 70,
  base_shares: 214,
  vol_adjustment: 0.92,
  kelly_fraction: 0.85,
  regime_multiplier: 1.0,
  final_shares: 167,
  final_value: 409150,
  final_risk: 11690,
  position_pct: 40.9,
  risk_qualifies: true,
  calculated_at: ISODate()
}

// portfolio_allocations - Phase 7 final portfolio
{
  allocation_date: ISODate(),
  regime_state: "risk_on",
  regime_confidence: 0.85,
  portfolio_value: 1000000,
  positions: [
    {symbol: "RELIANCE", shares: 167, value: 409150, weight: 40.9},
    {symbol: "TCS", shares: 85, value: 323000, weight: 32.3}
  ],
  sector_allocation: {"Energy": 40.9, "IT": 32.3},
  total_allocated: 732150,
  allocated_pct: 73.2,
  cash_reserve: 267850,
  cash_pct: 26.8,
  total_risk_pct: 2.8,
  correlation_filtered: 2,
  sector_filtered: 1,
  status: "pending",
  created_at: ISODate()
}

// monday_premarket - Phase 8 gap analysis
{
  analysis_date: ISODate(),
  nifty_prev_close: 24500,
  nifty_gap_pct: 0.45,
  regime_state: "risk_on",
  setup_analyses: [
    {
      symbol: "RELIANCE",
      prev_close: 2450,
      expected_open: 2462,
      gap_pct: 0.49,
      gap_vs_entry: "within_zone",
      action: "ENTER_AT_OPEN",
      reason: "Gap within entry zone"
    }
  ],
  enter_count: 3,
  skip_count: 1,
  wait_count: 1,
  sector_momentum: {"Energy": 1.2, "IT": 0.8}
}

// friday_summaries - Phase 8 week summary
{
  week_start: ISODate(),
  week_end: ISODate(),
  realized_pnl: 15420,
  unrealized_pnl: 8750,
  total_pnl: 24170,
  total_r: 2.8,
  trades_closed: 2,
  trades_won: 2,
  win_rate: 100,
  open_positions: [...],
  closed_positions: [...],
  system_health_score: 85,
  recommended_action: "CONTINUE"
}

// weekly_recommendations - Phase 9 master output
{
  week_start: ISODate(),
  week_end: ISODate(),
  week_display: "Dec 16-20, 2024",
  market_regime: "risk_on",
  regime_confidence: 0.85,
  position_multiplier: 1.0,
  total_setups: 5,
  recommendations: [...],  // Full TradeSetupTemplate objects
  portfolio_value: 1000000,
  allocated_capital: 732150,
  allocated_pct: 73.2,
  total_risk_pct: 2.8,
  status: "draft",
  created_at: ISODate()
}
```

#### UI Enhancements (Phases 5-9)

**Phase 5 Section:**
- Fundamental Qualified count, Total Analyzed, Pass Rate
- Buttons: "Run Fundamental Filter", "Phase 5 Pipeline"
- New "Fundamental Qualified" tab with scores

**Phase 6 Section:**
- Risk Qualified count, Average Stop %, Average R:R
- Buttons: "Run Risk Geometry", "Phase 6 Pipeline"
- New "Position Sizes" tab with sizing details

**Phase 7 Section:**
- Final Positions count, Allocated %, Cash Reserve %
- Buttons: "Run Portfolio Construction", "Phase 7 Pipeline"
- New "Portfolio Allocation" tab with positions

**Phase 8 Section:**
- Tabs: Monday Pre-Market, Position Status, Friday Summary
- Monday: Gap analysis table with enter/skip/wait actions
- Position: Current P&L, R-multiple, alerts
- Friday: Week summary, system health, recommended action

**Phase 9 Section:**
- Market context banner (regime, confidence, multiplier)
- Recommendation cards with full trade details
- Buttons: "Generate Recommendations", "Full Pipeline (4B-9)"
- Export functionality for trade templates

#### Extended Pipeline Summary

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

Phase 5: Fundamental Intelligence
~8-15 → ~6-10 Fundamentally Qualified (3+/5 filters + institutional)

Phase 6: Risk Geometry
~6-10 → ~5-8 Risk Qualified (R:R ≥ 2.0, stop ≤ 8%)

Phase 7: Portfolio Construction
~5-8 → ~3-7 Final Positions (correlation + sector limits)

Phase 8: Execution Display
UI only: Gap analysis, position tracking, week summary

Phase 9: Weekly Recommendations
~3-7 → Production trade setup templates with full details
```

#### Current Files Structure

```
src/trade_analyzer/
├── __init__.py
├── main.py
├── config.py                         # Config (MongoDB, Temporal, API keys, Portfolio defaults)
├── db/
│   ├── __init__.py
│   ├── connection.py                 # MongoDB singleton + indexes for all collections
│   ├── models.py                     # Pydantic models (30+ document models)
│   └── repositories.py               # Data access layer
├── data/
│   ├── __init__.py
│   └── providers/
│       ├── __init__.py
│       ├── upstox.py                 # Upstox instrument fetcher
│       ├── nse.py                    # NSE Nifty indices fetcher
│       ├── market_data.py            # Yahoo Finance OHLCV + indicators + setups
│       ├── fundamental.py            # FMP + Alpha Vantage integration (Phase 5)
│       └── nse_holdings.py           # NSE shareholding patterns (Phase 5)
├── activities/
│   ├── __init__.py
│   ├── universe.py                   # Basic fetch/save activities
│   ├── universe_setup.py             # Quality scoring activities
│   ├── momentum.py                   # 5 momentum filter activities (Phase 2)
│   ├── consistency.py                # 9-metric consistency activities (Phase 3)
│   ├── volume_liquidity.py           # Volume & liquidity activities (Phase 4A)
│   ├── setup_detection.py            # Setup detection activities (Phase 4B)
│   ├── fundamental.py                # 6 fundamental activities (Phase 5)
│   ├── risk_geometry.py              # 4 risk geometry activities (Phase 6)
│   ├── portfolio_construction.py     # 7 portfolio activities (Phase 7)
│   ├── execution.py                  # 9 execution activities (Phase 8)
│   └── recommendation.py             # 6 recommendation activities (Phase 9)
├── templates/
│   ├── __init__.py
│   └── trade_setup.py                # Trade setup template generator (Phase 9)
├── workflows/
│   ├── __init__.py
│   ├── universe.py                   # Basic refresh workflow
│   ├── universe_setup.py             # Full setup workflow with enrichment
│   ├── momentum_filter.py            # Momentum + Combined workflows (Phase 2)
│   ├── consistency_filter.py         # Consistency + Full Pipeline (Phase 3)
│   ├── volume_filter.py              # Volume & Liquidity workflow (Phase 4A)
│   ├── setup_detection.py            # Setup Detection + Phase 4 Pipeline (Phase 4B)
│   ├── fundamental_filter.py         # Fundamental Filter + Phase 5 Pipeline
│   ├── risk_geometry.py              # Risk Geometry + Phase 6 Pipeline
│   ├── portfolio_construction.py     # Portfolio Construction + Phase 7 Pipeline
│   ├── execution.py                  # PreMarket, PositionStatus, FridayClose (Phase 8)
│   └── weekly_recommendation.py      # Weekly Recommendations + Full Pipeline (Phase 9)
├── workers/
│   ├── __init__.py
│   ├── client.py                     # Temporal Cloud client
│   ├── universe_worker.py            # Worker process (all 22 workflows, 60+ activities)
│   └── start_workflow.py             # Workflow trigger script (all workflows)
└── ui/
    ├── __init__.py
    ├── app.py                        # Streamlit app (Phases 1-9 complete)
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

### Workflow Files Structure (IMPLEMENTED)

```
src/trade_analyzer/
├── workflows/
│   ├── universe.py              # Basic refresh ✅
│   ├── universe_setup.py        # Full setup with enrichment ✅
│   ├── momentum_filter.py       # Momentum + Combined workflows ✅
│   ├── consistency_filter.py    # Consistency + Full Pipeline (1-3) ✅
│   ├── volume_filter.py         # Volume & Liquidity ✅
│   ├── setup_detection.py       # Setup Detection + Phase 4 Pipeline ✅
│   ├── fundamental_filter.py    # Fundamental Filter + Phase 5 Pipeline ✅
│   ├── risk_geometry.py         # Risk Geometry + Phase 6 Pipeline ✅
│   ├── portfolio_construction.py # Portfolio + Phase 7 Pipeline ✅
│   ├── execution.py             # PreMarket, PositionStatus, FridayClose ✅
│   └── weekly_recommendation.py # Master workflow + Full Pipeline (4B-9) ✅
├── activities/
│   ├── universe.py              # Universe fetch/save ✅
│   ├── universe_setup.py        # Enrichment activities ✅
│   ├── momentum.py              # 5 momentum filters ✅
│   ├── consistency.py           # 9-metric consistency ✅
│   ├── volume_liquidity.py      # Volume & liquidity ✅
│   ├── setup_detection.py       # Setup detection ✅
│   ├── fundamental.py           # Fundamental analysis ✅
│   ├── risk_geometry.py         # Risk calculation ✅
│   ├── portfolio_construction.py # Portfolio building ✅
│   ├── execution.py             # Execution display ✅
│   └── recommendation.py        # Recommendations ✅
└── workers/
    ├── client.py                # Temporal Cloud client ✅
    ├── universe_worker.py       # All workflows (22 total) ✅
    └── start_workflow.py        # All workflow starters ✅
```

### Task Queues

| Queue | Workflows | Worker |
|-------|-----------|--------|
| `trade-analyzer-universe-refresh` | All 22 workflows (Phases 1-9) | universe_worker.py |

**Note:** A single worker handles all workflows for simplicity. All activities and workflows are registered in `universe_worker.py`.

---

## UI Pages & Workflow Integration

### Dashboard Page (All Phases Implemented)

The dashboard is a single-page application with expandable sections for each phase:

**Phase 1: Universe Setup**
- Display universe statistics (Total, MTF, Tiers, High Quality)
- "Setup Universe" button triggers UniverseSetupWorkflow
- Tabs: All Stocks, High Quality, MTF Only

**Phase 2: Momentum Analysis**
- Metrics: Momentum Qualified, Total Analyzed, Pass Rate
- Buttons: "Run Momentum Filter", "Full Weekend Run"
- Tab: Momentum Qualified

**Phase 3: Consistency Analysis**
- Metrics: Consistency Qualified, Total Analyzed, Pass Rate, Market Regime
- Buttons: "Run Consistency Filter", "Full Pipeline (1-3)"
- Tab: Consistency Qualified

**Phase 4A: Volume & Liquidity**
- Metrics: Liquidity Qualified, Total Analyzed, Pass Rate
- Buttons: "Run Volume Filter"
- Tab: Liquidity Qualified

**Phase 4B: Trade Setups**
- Metrics: Trade Setups, Setups Found, Qualified Rate
- Buttons: "Run Setup Detection", "Phase 4 Pipeline", "Full Analysis (1-4)"
- Tab: Trade Setups

**Phase 5: Fundamental Analysis**
- Metrics: Fundamental Qualified, Total Analyzed, Pass Rate
- Buttons: "Run Fundamental Filter", "Phase 5 Pipeline"
- Tab: Fundamental Qualified

**Phase 6: Risk Geometry**
- Metrics: Risk Qualified, Average Stop %, Average R:R
- Buttons: "Run Risk Geometry", "Phase 6 Pipeline"
- Tab: Position Sizes

**Phase 7: Portfolio Construction**
- Metrics: Final Positions, Allocated %, Cash Reserve %
- Buttons: "Run Portfolio Construction", "Phase 7 Pipeline"
- Tab: Portfolio Allocation

**Phase 8: Execution Display**
- Tabs: Monday Pre-Market, Position Status, Friday Summary
- Buttons for each workflow type

**Phase 9: Weekly Recommendations**
- Market context banner (regime, confidence, multiplier)
- Recommendation cards with full trade details
- Buttons: "Generate Recommendations", "Full Pipeline (4B-9)"
- Tab: Weekly Recommendations

### Settings Page
- Risk parameters configuration
- Sector exposure limits
- Position limits per regime
- API key management

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

**UI:** Integrated in Consistency Filter (auto-detected)

| Activity | Description | Status |
|----------|-------------|--------|
| `detect_current_regime()` | Nifty trend analysis for regime state | Done |

**Note:** Regime detection is integrated into the Consistency Filter workflow. The system automatically detects BULL/SIDEWAYS/BEAR based on Nifty's position relative to 50/200 DMA.

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

**Status:** ✅ DONE - Integrated across Phases 2-4

The universe filtering is implemented across multiple phases:
- **Phase 2** (Momentum): 52W proximity, MA alignment, RS vs Nifty
- **Phase 3** (Consistency): Weekly return consistency, regime-adaptive thresholds
- **Phase 4A** (Volume/Liquidity): Turnover, circuit limits, gap analysis

**Output:** ~15-25 stocks after all filters

#### 3.3 SetupDetectionWorkflow

**Status:** ✅ DONE - Phase 4B

| Activity | Description | Status |
|----------|-------------|--------|
| `detect_setups_batch()` | Pullback, VCP, Retest, Gap-Fill detection | Done |
| `filter_and_rank_setups()` | R:R validation, confidence scoring | Done |
| `enrich_setups_with_context()` | Add momentum/consistency context | Done |
| `save_setup_results()` | Persist to trade_setups collection | Done |

**Output:** ~8-15 setups with price levels

---

### Phase 4: Risk & Portfolio

**Note:** The original Phase 4 has been reorganized. Risk Geometry is now Phase 6, and Portfolio Construction is Phase 7. See Session 5 documentation for full details.

#### 4.1 RiskGeometryWorkflow (Now Phase 6)

**Status:** ✅ DONE

| Activity | Description | Status |
|----------|-------------|--------|
| `fetch_fundamentally_enriched_setups()` | Get Phase 5 qualified setups | Done |
| `calculate_risk_geometry_batch()` | Multi-method stop-loss calculation | Done |
| `calculate_position_sizes()` | Volatility-adjusted Kelly sizing | Done |
| `save_risk_geometry_results()` | Persist to position_sizes collection | Done |

**Output:** ~5-8 risk-qualified setups with position sizes

#### 4.2 PortfolioConstructionWorkflow (Now Phase 7)

**Status:** ✅ DONE

| Activity | Description | Status |
|----------|-------------|--------|
| `fetch_position_sized_setups()` | Get Phase 6 sized setups | Done |
| `calculate_correlation_matrix()` | 60-day rolling correlations | Done |
| `apply_correlation_filter()` | Reject pairs with correlation > 0.70 | Done |
| `apply_sector_limits()` | Max 3 per sector, 25% exposure | Done |
| `construct_final_portfolio()` | Build final allocation | Done |
| `save_portfolio_allocation()` | Persist to portfolio_allocations | Done |

**Output:** 3-7 Final Positions with allocations

---

### Phase 5: Execution & Monitoring (Now Phase 8)

**Status:** ✅ DONE - UI Display Only

#### 5.1 Pre-Market Analysis

| Feature | Description | Status |
|---------|-------------|--------|
| Monday gap analysis | Gap contingency evaluation | Done |
| Sector momentum | Sector strength calculation | Done |
| Entry/Skip decisions | Based on gap rules | Done |

#### 5.2 Position Status Tracking

| Feature | Description | Status |
|---------|-------------|--------|
| Current P&L | Real-time unrealized P&L | Done |
| R-multiple tracking | Performance in R terms | Done |
| Position alerts | Stop/target proximity alerts | Done |

#### 5.3 System Health Monitoring

| Feature | Description | Status |
|---------|-------------|--------|
| Friday summary | Week P&L and R totals | Done |
| Win rate calculation | Rolling win rate | Done |
| System health score | 0-100 composite score | Done |
| Recommended action | CONTINUE/REDUCE/PAUSE/STOP | Done |

---

## Configuration

All credentials configured in `src/trade_analyzer/config.py`. Environment variables can override defaults.

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

### Fundamental Data APIs (Phase 5)
```
FMP_API_KEY: Financial Modeling Prep API key
ALPHA_VANTAGE_API_KEY: Alpha Vantage API key
```

### Portfolio Configuration
```python
DEFAULT_PORTFOLIO_VALUE = 1_000_000  # Rs. 10 Lakhs
DEFAULT_RISK_PCT = 0.015             # 1.5% per trade
MAX_POSITIONS = 12
MAX_SECTOR_PCT = 0.25                # 25% sector limit
CASH_RESERVE_PCT = 0.30              # 30% cash reserve
```

### Task Queues
- `trade-analyzer-universe-refresh` - All workflows (Phases 1-9)

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

### Core Collections

#### stocks (Updated with Quality Fields)
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
  is_mtf: true,
  in_nifty_50: true,
  in_nifty_100: true,
  in_nifty_200: true,
  in_nifty_500: true,
  quality_score: 95,
  liquidity_tier: "A",
  is_active: true,
  last_updated: ISODate()
}
```

#### trade_setups
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

#### regime_assessments
```javascript
{
  state: "risk_on",
  confidence: 0.85,
  position_multiplier: 1.0,
  timestamp: ISODate()
}
```

### Phase 5-9 Collections

#### fundamental_scores (Phase 5)
```javascript
{
  symbol: "RELIANCE",
  eps_qoq_growth: 15.2,
  revenue_yoy_growth: 12.8,
  roce: 18.5,
  roe: 22.3,
  debt_equity: 0.45,
  opm_margin: 16.2,
  fcf_yield: 5.8,
  fundamental_score: 78.6,
  qualifies: true,
  calculated_at: ISODate()
}
```

#### institutional_holdings (Phase 5)
```javascript
{
  symbol: "RELIANCE",
  fii_holding_pct: 25.4,
  dii_holding_pct: 18.2,
  total_institutional: 43.6,
  fii_net_30d: 0.8,
  promoter_pledge_pct: 2.1,
  qualifies: true,
  fetched_at: ISODate()
}
```

#### position_sizes (Phase 6)
```javascript
{
  symbol: "RELIANCE",
  setup_id: "setup_123",
  portfolio_value: 1000000,
  risk_pct: 0.015,
  entry_price: 2450,
  stop_loss: 2380,
  final_shares: 167,
  final_value: 409150,
  risk_qualifies: true,
  calculated_at: ISODate()
}
```

#### portfolio_allocations (Phase 7)
```javascript
{
  allocation_date: ISODate(),
  regime_state: "risk_on",
  portfolio_value: 1000000,
  positions: [...],
  sector_allocation: {...},
  total_allocated: 732150,
  allocated_pct: 73.2,
  cash_reserve: 267850,
  status: "pending",
  created_at: ISODate()
}
```

#### monday_premarket (Phase 8)
```javascript
{
  analysis_date: ISODate(),
  nifty_gap_pct: 0.45,
  setup_analyses: [...],
  enter_count: 3,
  skip_count: 1,
  wait_count: 1
}
```

#### friday_summaries (Phase 8)
```javascript
{
  week_start: ISODate(),
  realized_pnl: 15420,
  unrealized_pnl: 8750,
  total_r: 2.8,
  win_rate: 100,
  system_health_score: 85,
  recommended_action: "CONTINUE"
}
```

#### weekly_recommendations (Phase 9)
```javascript
{
  week_start: ISODate(),
  week_display: "Dec 16-20, 2024",
  market_regime: "risk_on",
  recommendations: [...],
  allocated_capital: 732150,
  allocated_pct: 73.2,
  status: "draft",
  created_at: ISODate()
}
```

---

## Data Sources

| Source | Data | Cost | Status |
|--------|------|------|--------|
| Upstox | Instruments, OHLCV | Free API | ✅ Implemented |
| Yahoo Finance | Historical OHLCV, Indicators | Free | ✅ Implemented |
| NSE Website | Index constituents, Holdings | Free | ✅ Implemented |
| FMP (Financial Modeling Prep) | Financial statements | Free tier + Paid | ✅ Implemented |
| Alpha Vantage | Company overview | Free tier + Paid | ✅ Implemented |
| India VIX | NSE website | Free | ✅ Integrated |

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

### All Core Phases Complete ✅

The Trade Analyzer system is now fully implemented with all 9 phases complete:
- Phase 1-4: Universe → Momentum → Consistency → Volume/Liquidity → Setup Detection
- Phase 5: Fundamental Intelligence with FMP + Alpha Vantage + NSE Holdings
- Phase 6-7: Risk Geometry + Portfolio Construction
- Phase 8: Execution Display (UI only)
- Phase 9: Weekly Recommendations

### Testing the System

1. **Start Worker** - Run `make worker` to start Temporal worker
2. **Start UI** - Run `make ui` to start Streamlit dashboard
3. **Set API Keys** - Configure FMP_API_KEY and ALPHA_VANTAGE_API_KEY in environment
4. **Run Full Pipeline** - Click "Full Pipeline (4B-9)" in Phase 9 section
5. **Review Results** - Check all tabs for filtered stocks and trade recommendations

### Recommended Test Sequence

```bash
# Terminal 1: Start worker
make worker

# Terminal 2: Start UI
make ui

# In browser (localhost:8501):
# 1. Click "Setup Universe" in Phase 1 section
# 2. Click "Full Weekend Run" in Phase 2 section
# 3. Click "Full Pipeline (1-3)" in Phase 3 section
# 4. Click "Full Analysis (1-4)" in Phase 4B section
# 5. Click "Full Pipeline (4B-9)" in Phase 9 section
# 6. Review recommendations in "Weekly Recommendations" tab
```

### Future Enhancements (Optional)

| Enhancement | Description | Priority |
|-------------|-------------|----------|
| Upstox OAuth | Real-time price data integration | Low |
| Broker Integration | Actual order placement | Low |
| SMS/Email Alerts | Position alerts via notification | Medium |
| Backtesting Module | Historical performance validation | Medium |
| PDF Export | Generate PDF trade reports | Low |
| Mobile App | React Native companion app | Low |

### Maintenance Tasks

1. **Weekly**: Run full pipeline on weekends
2. **Monthly**: Review system health metrics
3. **Quarterly**: Update fundamental scoring weights if needed
4. **Annually**: Review and adjust all thresholds based on performance

---

## Completed Phases Summary

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Universe Setup (NSE EQ + MTF + Quality Scoring) | ✅ DONE |
| Phase 2 | Momentum Filter (5 filters, ~50-100 qualified) | ✅ DONE |
| Phase 3 | Consistency Filter (9 metrics, regime-adaptive) | ✅ DONE |
| Phase 4A | Volume & Liquidity Filter (4 filters, ~15-25 qualified) | ✅ DONE |
| Phase 4B | Setup Detection (Pullback, VCP, Retest, Gap-Fill) | ✅ DONE |
| Phase 5 | Fundamental Intelligence (FMP, Alpha Vantage, NSE Holdings) | ✅ DONE |
| Phase 6 | Risk Geometry (Multi-method stops, volatility-adjusted sizing) | ✅ DONE |
| Phase 7 | Portfolio Construction (Correlation filter, sector limits) | ✅ DONE |
| Phase 8 | Execution Display (Gap analysis, position tracking, UI only) | ✅ DONE |
| Phase 9 | Weekly Recommendations (Production trade templates) | ✅ DONE |

### System Capabilities Summary

**Input:** ~2400 NSE EQ stocks
**Output:** 3-7 production trade setup templates with full execution details

**Complete Pipeline:**
```
~2400 → Phase 1 → ~1400 → Phase 2 → ~80 → Phase 3 → ~40
    → Phase 4A → ~20 → Phase 4B → ~12 → Phase 5 → ~8
    → Phase 6 → ~6 → Phase 7 → ~4 → Phase 8/9 → 3-7 Templates
```

**Total Implementation:**
- 22 Temporal workflows
- 60+ Temporal activities
- 30+ MongoDB document models
- 8 new collections
- Full Streamlit dashboard with all phases

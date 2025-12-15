# Activities Module Documentation

Complete documentation for all activity files in `/src/trade_analyzer/activities/`.

## Overview

Activities are Temporal workflow tasks that execute business logic. Each file corresponds to a phase in the trading pipeline.

---

## Pipeline Flow

```
Phase 0: Universe Setup (universe.py, universe_setup.py)
    ↓
Phase 1: Fundamental Filter (fundamental.py)
    ↓
Phase 2: Momentum Filter (momentum.py)
    ↓
Phase 3: Consistency Filter (consistency.py)
    ↓
Phase 4A: Volume/Liquidity Filter (volume_liquidity.py)
    ↓
Phase 4B: Setup Detection (setup_detection.py)
    ↓
Phase 5: (Fundamental enrichment already done in Phase 1)
    ↓
Phase 6: Risk Geometry (risk_geometry.py)
    ↓
Phase 7: Portfolio Construction (portfolio_construction.py)
    ↓
Phase 8: Execution Monitoring (execution.py)
    ↓
Phase 9: Recommendations (recommendation.py)
```

---

## File: universe.py

**Purpose**: Basic universe refresh (NSE EQ + MTF instruments from Upstox)

### Activities

#### `refresh_nse_instruments() -> InstrumentData`
- Fetches ~2000 NSE equity instruments
- Filters to NSE_EQ segment only
- Returns list of equity instruments

#### `refresh_mtf_instruments() -> InstrumentData`
- Fetches ~200-300 MTF-eligible symbols
- MTF = Margin Trading Facility (highest quality signal)
- Returns list of MTF instruments

#### `save_instruments_to_db(nse_instruments, mtf_symbols) -> dict`
- Upserts all instruments to MongoDB stocks collection
- Marks existing stocks as inactive
- Creates indexes: symbol (unique), is_mtf, is_active

#### `get_universe_stats() -> UniverseStats`
- Returns counts of active NSE EQ and MTF stocks
- Used for UI display and monitoring

---

## File: universe_setup.py

**Purpose**: Full quality-scored universe setup with tier classification

### Key Concepts

**Quality Tiers:**
- **Tier A** (90-100): MTF + Nifty 50/100 - Highest quality
- **Tier B** (70-90): MTF + Nifty 200/500 OR MTF only
- **Tier C** (40-70): Nifty 500 (non-MTF)
- **Tier D** (<40): Excluded

**MTF Priority**: MTF eligibility is PRIMARY signal (exchange-approved quality)

### Activities

#### `fetch_base_universe() -> BaseUniverseData`
- Fetches NSE EQ + MTF from Upstox
- Combines both datasets for enrichment

#### `fetch_nifty_indices() -> NiftyData`
- Fetches Nifty 50/100/200/500 constituents from NSE
- Index membership = quality signal
- Includes 0.3s delay between requests (rate limiting)

#### `enrich_and_score_universe(...) -> list[dict]`
- **Core quality scoring algorithm**
- For each stock:
  1. Check MTF eligibility
  2. Check Nifty index membership
  3. Assign quality score (0-100)
  4. Assign liquidity tier (A/B/C/D)
- Returns ~200-400 Tier A/B stocks

**Scoring Logic:**
```python
MTF-Eligible:
    MTF + Nifty 50  -> Score 95, Tier A
    MTF + Nifty 100 -> Score 85, Tier A
    MTF + Nifty 200 -> Score 75, Tier B
    MTF + Nifty 500 -> Score 70, Tier B
    MTF only        -> Score 60, Tier B

Non-MTF:
    Nifty 50  -> Score 55, Tier C
    Nifty 100 -> Score 50, Tier C
    Nifty 200 -> Score 45, Tier C
    Nifty 500 -> Score 40, Tier C
    Others    -> Score 10, Tier D (excluded)
```

#### `save_enriched_universe(enriched_stocks) -> dict`
- Saves to MongoDB stocks collection
- Creates compound indexes for efficient filtering
- Returns tier counts and statistics

---

## File: momentum.py

**Purpose**: Phase 2 - Enhanced Momentum & Trend Filters

### Implements 5 Filters

#### Filter 2A: 52-Week High Proximity
- Primary: Within 10% of 52W high
- Secondary: Within 20% + volume surge >1.5x
- Formula: `proximity = (close - low_52w) / (high_52w - low_52w) * 100`

#### Filter 2B: Advanced Moving Average System (5-Layer)
- Close > 20/50/200 DMA
- Perfect alignment: 20 > 50 > 200 DMA
- All MAs sloping UP (thresholds: 20D≥0.1%, 50D≥0.05%, 200D≥0.02%)
- Pass if 4+ conditions met

#### Filter 2C: Multi-Timeframe Relative Strength
- 1M RS: Stock > Nifty50 + 5%
- 3M RS: Stock > Nifty50 + 10%
- 6M RS: Stock > Nifty50 + 15%
- Pass if 2/3 horizons met

#### Filter 2D: Composite Momentum Score (0-100)
```
Score = 25% × 52W_Proximity +
        25% × RS_Score +
        25% × MA_Strength +
        25% × Price_Acceleration
```

#### Filter 2E: Volatility-Adjusted Momentum
- Stock volatility ≤ 1.5x Nifty volatility
- Vol-Adjusted RS = Raw RS / Volatility Ratio

### Activities

#### `fetch_high_quality_symbols(min_score=60) -> list[str]`
- Fetches symbols with quality_score >= 60 AND fundamentally_qualified=True
- Input for momentum filter

#### `fetch_market_data_batch(symbols, fetch_delay=0.3) -> dict`
- Fetches 400 days of OHLCV data for each symbol
- Returns dict: symbol -> OHLCV data

#### `fetch_nifty_benchmark_data() -> dict`
- Fetches Nifty 50 data for RS calculations
- Returns benchmark returns (1M, 3M, 6M) and volatility

#### `calculate_momentum_scores(market_data, nifty_data, symbols) -> list[dict]`
- Calculates all 5 momentum filters for each stock
- Returns list of MomentumResult dicts
- Qualifies if 4+ filters pass

#### `save_momentum_results(results, nifty_returns) -> dict`
- Saves to momentum_scores collection
- Updates stocks collection with momentum fields
- Creates indexes for querying

**Expected Output**: ~50-100 stocks pass 4+ filters

---

## File: consistency.py

**Purpose**: Phase 3 - Weekly Return Consistency Filter

### Implements 9-Metric Framework

1. **Positive Weeks % (52W)**: ≥65% (regime-adaptive)
2. **+3% Weeks % (52W)**: 25-35%
3. **+5% Weeks % (52W)**: 10-20%
4. **Weekly Std Dev (52W)**: 3-6%
5. **Avg Weekly Return (52W)**: ≥0.8%
6. **Sharpe Ratio (52W)**: ≥0.15
7. **Win Streak Probability (26W)**: ≥62%
8. **Consistency Score (52W)**: ≥75
9. **Regime Score (13W/52W)**: ≥1.2

### Key Formula

```python
Consistency_Score = 25% × Pos%_norm +
                   25% × Plus3%_norm +
                   20% × (1/Volatility_norm) +
                   15% × Sharpe_norm +
                   15% × WinStreak_norm

Regime_Score = Avg_Return_13W / Avg_Return_52W

Final_Score = 40% × Consistency_Score +
              25% × Regime_Score_norm +
              20% × Percentile +
              15% × Sharpe_norm
```

### Activities

#### `fetch_momentum_qualified_symbols() -> list[str]`
- Fetches symbols from Phase 2 (momentum_qualifies=True)

#### `fetch_weekly_data_batch(symbols, fetch_delay=0.3) -> dict`
- Fetches 60 weeks of OHLCV data
- Resamples to weekly frequency

#### `detect_current_regime() -> dict`
- Detects market regime: BULL/SIDEWAYS/BEAR
- Returns regime-adaptive thresholds

#### `calculate_consistency_scores(weekly_data, regime_info, symbols) -> list[dict]`
- Calculates all 9 consistency metrics
- Applies regime-adaptive filters
- Qualifies if 5+ filters pass

#### `save_consistency_results(results, regime_info) -> dict`
- Saves to consistency_scores collection
- Updates stocks collection
- Returns statistics

**Expected Output**: ~30-50 stocks with high consistency

---

## File: volume_liquidity.py

**Purpose**: Phase 4A - Volume & Liquidity Filter

### Implements Multi-Dimensional Liquidity Scoring

**Metrics:**
- **Turnover** (20D avg in Crores): ≥10 Cr
- **Volume Expansion**: Recent vs historical
- **Circuit Hits** (30D): ≤1
- **Gap Analysis**: Avg gap ≤2%
- **Impact Cost**: Estimated slippage
- **Liquidity Score** (0-100): ≥75

### Activities

#### `fetch_consistency_qualified_symbols() -> list[str]`
- Fetches from Phase 3 (consistency_qualifies=True)

#### `calculate_volume_liquidity_batch(symbols, fetch_delay=0.3) -> list[dict]`
- Fetches 90 days of daily data
- Calculates liquidity metrics
- Detects circuit hits

#### `filter_by_liquidity(liquidity_data, min_liquidity_score=75) -> list[dict]`
- Applies 4 filters
- Requires 3/4 to pass

#### `save_liquidity_results(results) -> dict`
- Saves to liquidity_scores collection

**Expected Output**: ~20-30 highly liquid stocks

---

## File: setup_detection.py

**Purpose**: Phase 4B - Technical Setup Detection

### Setup Types

#### Type A+: Enhanced Trend Pullback
- Stock in uptrend (higher highs/lows)
- Pullback 3-10% to rising 20/50 DMA
- Volume contracting on pullback
- Entry: Near MA, Stop: Below swing low

#### Type B+: Volatility Contraction Pattern (VCP)
- Sideways 3-8 weeks, range ≤12%
- Declining volume during consolidation
- Breakout with volume >1.5x average

#### Type C+: Confirmed Breakout Retest
- Breakout 1-3 weeks ago
- Retesting breakout zone
- Holding above former resistance

#### Type D: Gap-Fill Continuation
- Recent gap up (>3%)
- Pullback to fill gap
- Resuming uptrend

### Activities

#### `fetch_liquidity_qualified_symbols() -> list[str]`
- Fetches from Phase 4A

#### `detect_setups_batch(symbols, fetch_delay=0.3) -> list[dict]`
- Detects all 4 setup types
- Returns entry/stop/target levels

#### `filter_and_rank_setups(setups, min_rr=2.0, min_confidence=70) -> list[dict]`
- Filters by R:R ratio, confidence, stop distance
- Ranks by composite score

#### `enrich_setups_with_context(setups) -> list[dict]`
- Adds momentum/consistency/liquidity scores
- Calculates overall_quality score

#### `save_setup_results(setups, market_regime) -> dict`
- Saves to trade_setups collection

**Expected Output**: 8-15 high-conviction setups

---

## File: fundamental.py

**Purpose**: Fundamental Intelligence (Phase 1 & Phase 5)

### Architecture

- **Monthly**: FundamentalDataRefreshWorkflow fetches API data
- **Weekly**: Phases 1 & 5 use cached data (NO API calls)

### Formula

```python
FUNDAMENTAL_SCORE = 30% × Growth +
                   25% × Profitability +
                   20% × Leverage +
                   15% × Cash_Flow +
                   10% × Earnings_Quality

Growth: EPS QoQ growth, Revenue YoY growth
Profitability: ROCE, ROE, OPM margin
Leverage: Debt/Equity ratio
Cash Flow: FCF yield
Quality: Cash EPS vs Reported EPS
```

### Activities

#### Phase 1 Activities (Weekly):

##### `fetch_universe_for_fundamentals(min_quality_score=60) -> list[str]`
- Gets high-quality stocks from universe

##### `apply_fundamental_filter(min_score=60) -> dict`
- Uses CACHED fundamental_scores (no API)
- Updates stocks.fundamentally_qualified field
- Combined with institutional holdings

##### `get_fundamentally_qualified_for_momentum() -> list[str]`
- Returns stocks ready for Phase 2 momentum filter

#### Phase 5 Activities (Monthly):

##### `fetch_fundamental_data_batch(symbols, fetch_delay=1.0) -> list[dict]`
- Fetches from FMP API (with rate limiting)
- Returns fundamental metrics

##### `calculate_fundamental_scores(fundamental_data) -> list[dict]`
- Calculates 5-component score
- Applies sector-relative thresholds

##### `fetch_institutional_holdings_batch(symbols) -> list[dict]`
- Fetches from NSE
- FII/DII holding percentages

##### `save_fundamental_results(fundamental_scores, institutional_holdings) -> dict`
- Saves to fundamental_scores and institutional_holdings collections

**Expected Output**: ~60-80% of stocks pass (cached in Phase 1)

---

## File: risk_geometry.py

**Purpose**: Phase 6 - Risk Geometry & Position Sizing

### Multi-Method Stop-Loss Calculation

#### Method 1: Structure Stop
```python
swing_low = df["low"].tail(10).min()
stop_structure = swing_low * 0.99  # 1% below
```

#### Method 2: Volatility Stop
```python
ATR_14 = rolling_14D_avg(TrueRange)
stop_volatility = entry - (2.0 * ATR_14)
```

#### Final Stop
```python
final_stop = max(stop_structure, stop_volatility)  # Tighter (higher)
```

### Position Sizing Formula

```python
Base_Size = (Portfolio * Risk%) / Risk_per_share

Vol_Adjustment = Nifty_ATR / Stock_ATR  # Bounded [0.5, 1.5]

Kelly_Fraction = (Win% × AvgWin - Loss% × AvgLoss) / AvgWin

Regime_Mult = {
    "risk_on": 1.0,
    "choppy": 0.5,
    "risk_off": 0.0
}

FINAL_SIZE = Base_Size × Vol_Adjustment × Kelly × Regime_Mult
```

### Activities

#### `fetch_fundamentally_enriched_setups() -> list[dict]`
- Gets setups from Phase 4B + fundamental data

#### `calculate_risk_geometry_batch(setups, min_rr_risk_on=2.0) -> list[dict]`
- Calculates multi-method stops
- Calculates R:R ratios (Target 1 = 2R, Target 2 = 3R+)
- Validates: R:R ≥ min, Stop ≤ 7%

#### `calculate_position_sizes(risk_geometries, portfolio_value) -> list[dict]`
- Applies Kelly + Volatility adjustments
- Enforces max position (8%) and max positions (12)
- Returns final share quantities

#### `save_risk_geometry_results(results) -> dict`
- Saves to position_sizes collection

**Expected Output**: 5-12 position-sized setups

---

## File: portfolio_construction.py

**Purpose**: Phase 7 - Portfolio Construction with Constraints

### Constraints

- **Max Positions**: 10 (Risk-On), 5 (Choppy), 0 (Risk-Off)
- **Max Sector Exposure**: 25%
- **Max Single Position**: 8%
- **Max Correlation**: 0.70
- **Cash Reserve**: 20-30%

### Activities

#### `fetch_position_sized_setups() -> list[dict]`
- Gets from Phase 6

#### `calculate_correlation_matrix(symbols, days=60) -> dict`
- Calculates 60-day return correlations
- Returns nested dict: {sym1: {sym2: corr}}

#### `apply_correlation_filter(setups, correlations, max_correlation=0.70) -> list[dict]`
- Greedy algorithm: always keep best setup
- Reject correlated setups iteratively

#### `apply_sector_limits(setups, max_per_sector=3, max_sector_pct=0.25) -> list[dict]`
- Max 3 positions per sector
- Max 25% portfolio in any sector

#### `construct_final_portfolio(setups, max_positions, cash_reserve_pct) -> dict`
- Applies all constraints
- Validates sector/cash/correlation limits
- Returns portfolio allocation

#### `save_portfolio_allocation(portfolio) -> dict`
- Saves to portfolio_allocations collection
- Status: "pending" (requires approval)

**Expected Output**: 3-10 final positions (3-7 typical)

---

## File: execution.py

**Purpose**: Phase 8 - Execution Monitoring (UI Display Only)

**Note**: NO actual order placement. UI display and analysis only.

### Monday Gap Contingency Rules

```python
if current <= stop:
    action = "SKIP"  # Gapped through stop
elif current > entry_high * 1.02:
    action = "SKIP"  # Don't chase
elif entry_low <= current <= entry_high:
    action = "ENTER"  # In entry zone
elif current < entry_low and gap < -2%:
    action = "WAIT"  # Large gap against
else:
    action = "ENTER_AT_OPEN"  # Small gap against
```

### Activities

#### `fetch_current_prices(symbols) -> dict`
- Fetches latest/pre-market prices
- Returns current, open, high, low, volume

#### `analyze_monday_gaps(setups, prices, gap_threshold_pct=2.0) -> list[dict]`
- Analyzes Monday morning gaps
- Returns action (ENTER/SKIP/WAIT) for each setup

#### `calculate_sector_momentum() -> dict`
- Fetches Nifty sector indices
- Returns week/month performance by sector

#### `update_position_status(positions, prices) -> list[dict]`
- Updates current P&L and R-multiple
- Status: stopped_out/target_1_hit/target_2_hit/in_profit/in_loss

#### `generate_position_alerts(position) -> list[str]`
- Stop proximity alerts (< 2%)
- Target proximity alerts (< 2%)
- R-multiple milestones (1R, 2R, 3R)
- Trailing stop suggestions

#### `generate_friday_summary(week_start) -> dict`
- End-of-week P&L summary
- Closed trades metrics
- Open positions status
- System health score

#### `calculate_system_health() -> dict`
- Health score (0-100)
- Win rate 12W & 52W
- Expectancy calculation
- Current drawdown
- Recommended action: CONTINUE/REDUCE/PAPER_TRADE/STOP

**System Health Thresholds:**
- Score ≥ 70: CONTINUE
- Score 50-70: REDUCE (50% size)
- Score 30-50: PAPER_TRADE
- Score < 30: STOP

---

## File: recommendation.py

**Purpose**: Phase 9 - Weekly Recommendation Generation

### Activities

#### `aggregate_phase_results() -> dict`
- Aggregates results from Phases 1-7
- Enriches positions with all context:
  - Regime assessment
  - Portfolio allocation
  - Factor scores (momentum, consistency, liquidity)
  - Fundamental scores
  - Technical indicators

#### `generate_recommendation_templates(positions, market_regime, portfolio_value) -> list[dict]`
- Generates recommendation cards for each position
- Includes:
  - Final conviction score
  - All quality scores
  - Technical levels (entry/stop/targets)
  - Position sizing
  - Action steps
  - Gap contingency plan
  - Text template for sharing

#### `save_weekly_recommendation(recommendations, regime, stats) -> dict`
- Saves to weekly_recommendations collection
- Status: "draft" (requires user approval)
- Includes:
  - Week boundaries
  - Market regime and confidence
  - Position multiplier
  - Total capital allocated
  - Total risk percentage
  - Sector breakdown

#### `get_latest_weekly_recommendation() -> dict | None`
- Retrieves most recent recommendation
- Excludes expired recommendations

#### `approve_weekly_recommendation(week_start) -> dict`
- Changes status from "draft" to "approved"
- Records approval timestamp

#### `expire_old_recommendations() -> dict`
- Expires recommendations > 1 week old
- Cleanup to avoid stale data

---

## Common Patterns Across All Files

### Error Handling
```python
try:
    # Activity logic
except Exception as e:
    activity.logger.error(f"Error: {e}")
    # Continue or return default
```

### Rate Limiting
```python
for i, symbol in enumerate(symbols):
    # Process symbol
    await asyncio.sleep(fetch_delay)  # Typically 0.3-1.0s
```

### MongoDB Operations
```python
# Always create indexes after bulk inserts
collection.create_index("field_name")
collection.create_index([("field1", -1), ("field2", 1)])  # Compound

# Use aggregation pipelines for complex queries
pipeline = [
    {"$match": {...}},
    {"$sort": {"field": -1}},
    {"$group": {...}},
]
```

### Logging
```python
activity.logger.info(f"Processed {count} items")
activity.logger.warning(f"Issue with {symbol}: {issue}")
activity.logger.error(f"Failed: {error}")
```

---

## Expected Throughput (Full Pipeline)

```
Phase 0: ~2000 NSE EQ instruments
Phase 1: ~200-400 high quality (Tier A/B)
Phase 1: ~120-320 fundamentally qualified (60-80% pass rate)
Phase 2: ~50-100 momentum qualified (40-80% pass rate)
Phase 3: ~30-50 consistency qualified (60% pass rate)
Phase 4A: ~20-30 liquidity qualified (65% pass rate)
Phase 4B: 8-15 technical setups detected (50% pass rate)
Phase 5: (enrichment only, no filtering)
Phase 6: 5-12 position-sized setups (80% pass rate)
Phase 7: 3-10 final portfolio positions (60-80% pass rate)
Phase 8: (monitoring only)
Phase 9: 3-7 recommendations (typical output)
```

---

## MongoDB Collections Used

| Collection | Purpose | Key Indexes |
|------------|---------|-------------|
| `stocks` | Universe master | symbol, quality_score, liquidity_tier |
| `momentum_scores` | Phase 2 results | symbol, momentum_score, qualifies |
| `consistency_scores` | Phase 3 results | symbol, final_score, qualifies |
| `liquidity_scores` | Phase 4A results | symbol, liquidity_score, liq_qualifies |
| `trade_setups` | Phase 4B results | symbol, detected_at, rank |
| `fundamental_scores` | Phase 1/5 results | symbol, fundamental_score, qualifies |
| `institutional_holdings` | Phase 1/5 results | symbol, fii_holding_pct |
| `position_sizes` | Phase 6 results | symbol, overall_quality |
| `portfolio_allocations` | Phase 7 results | allocation_date, status |
| `monday_premarket` | Phase 8 gap analysis | analysis_date |
| `friday_summaries` | Phase 8 weekly summary | week_start |
| `trades` | Execution tracking | entry_date, status |
| `weekly_recommendations` | Phase 9 output | week_start, status |
| `regime_assessments` | Market regime | timestamp |

---

## Critical Implementation Notes

1. **Caching Strategy**: Phase 1 uses cached fundamental data. Monthly workflow refreshes cache.

2. **Regime Awareness**: Position multiplier adjusts based on regime:
   - Risk-On: 1.0 (full size)
   - Choppy: 0.5 (half size)
   - Risk-Off: 0.0 (no trades)

3. **Statistical Significance**: Consistency filter checks p-value < 0.10 for validity.

4. **Transaction Costs**: ~0.27% round-trip in India. Need >0.2R gross profit to break even.

5. **Gap Contingency**: Critical for Monday execution. Weekend analysis assumes Friday close.

6. **System Health**: Continuously monitored. Auto-suggests REDUCE/PAUSE/STOP based on performance.

7. **Temporal Patterns**:
   - Activities are idempotent (can retry safely)
   - Use activity heartbeats for long-running tasks
   - Serialize complex objects as dicts for Temporal

---

## Testing & Validation

### Unit Tests
```bash
pytest tests/test_activities/
```

### Integration Tests
```bash
pytest tests/test_integration/ -v
```

### Manual Testing
1. Run UniverseSetupWorkflow
2. Check stocks collection tier counts
3. Run each phase workflow sequentially
4. Verify collection counts match expected throughput

---

## Troubleshooting

### Common Issues

**Issue**: Activity timeouts
- **Fix**: Increase timeout in workflow or add heartbeats

**Issue**: Rate limit errors from APIs
- **Fix**: Increase fetch_delay parameter

**Issue**: MongoDB connection errors
- **Fix**: Check connection.py and environment variables

**Issue**: Missing fundamental data
- **Fix**: Run FundamentalDataRefreshWorkflow (monthly)

**Issue**: Zero results from phase
- **Fix**: Check previous phase output and filter thresholds

---

## Performance Optimization

1. **Parallel Processing**: Use asyncio for I/O-bound tasks
2. **Batch Operations**: MongoDB bulk inserts/updates
3. **Indexes**: Compound indexes for common query patterns
4. **Caching**: Fundamental data cached monthly
5. **Rate Limiting**: Balance speed vs API limits

---

## Future Enhancements

- [ ] Add sector rotation logic
- [ ] Implement adaptive filter thresholds
- [ ] Add ML-based setup scoring
- [ ] Implement backtesting framework
- [ ] Add options overlay strategies
- [ ] Implement real-time execution (currently UI only)

---

Generated: 2025-12-15
Maintained by: Trade Analyzer Development Team

# Implementation Plan

## Overview

This document outlines the step-by-step implementation plan for the Trade Analyzer system. The system progressively filters ~500 NSE stocks down to 5-15 high-conviction weekly trades through multiple stages of analysis.

**Target Output:** 3-7 trade setups every weekend with defined entry, stop, target, and position size.

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

For ₹1,00,000 trade value:
- STT (buy + sell): ₹200 (0.2%)
- Brokerage: ₹40 (0.04%)
- GST on brokerage: ₹7
- Exchange fees: ₹7
- Stamp duty: ₹15
- **Total round-trip: ~₹270 (0.27%)**

Plus 15% STCG tax on profits.

**Critical:** You need >0.2R per trade GROSS just to break even after costs.

### Where the Edge Actually Comes From

1. **Regime Awareness** - Not trading in bad environments
2. **Selection Discipline** - "No trade" is valid output
3. **Risk Management** - Surviving drawdowns to compound
4. **Consistency** - Running the system for years, not weeks

---

## Phase 0: Data Quality Foundation (CRITICAL)

This phase is non-negotiable. Bad data = bad decisions.

### 0.1 Survivorship Bias Mitigation

**The Problem:** Today's Nifty 500 only contains survivors. Backtesting on current constituents overstates returns by 2-5% annually.

- [ ] Research point-in-time constituent data sources
  - NSE historical archives
  - Commercial providers (Bloomberg, Refinitiv)
  - Community datasets

- [ ] If point-in-time unavailable, implement bias adjustment
  ```python
  SURVIVORSHIP_BIAS_DRAG = 0.04  # 4% annual drag on backtest returns

  def adjusted_backtest_return(raw_return: float, years: float) -> float:
      return raw_return - (SURVIVORSHIP_BIAS_DRAG * years)
  ```

- [ ] Maintain known failures list
  - Stocks that crashed >80%
  - Delisted stocks
  - Fraud cases (Yes Bank, DHFL, etc.)

### 0.2 Corporate Actions Handling

- [ ] Implement split/bonus adjustment
  ```python
  def adjust_for_split(ohlcv: list[OHLCV], split_ratio: float, split_date: date) -> list[OHLCV]:
      """Adjust historical prices for stock split"""
      return [
          OHLCV(
              date=o.date,
              open=o.open / split_ratio if o.date < split_date else o.open,
              high=o.high / split_ratio if o.date < split_date else o.high,
              low=o.low / split_ratio if o.date < split_date else o.low,
              close=o.close / split_ratio if o.date < split_date else o.close,
              volume=int(o.volume * split_ratio) if o.date < split_date else o.volume,
          )
          for o in ohlcv
      ]
  ```

- [ ] Use adjusted close from yfinance (handles most cases)
- [ ] Validate data after fetching (no >50% single-day moves without corporate action)

### 0.3 Data Validation Pipeline

- [ ] Implement validation checks
  ```python
  def validate_ohlcv(ohlcv: list[OHLCV]) -> tuple[bool, list[str]]:
      errors = []

      for i, bar in enumerate(ohlcv):
          # Basic sanity
          if bar.high < bar.low:
              errors.append(f"{bar.date}: high < low")
          if bar.close > bar.high or bar.close < bar.low:
              errors.append(f"{bar.date}: close outside range")

          # Suspicious moves
          if i > 0:
              prev = ohlcv[i-1]
              change = abs(bar.close - prev.close) / prev.close
              if change > 0.30:  # >30% move
                  errors.append(f"{bar.date}: {change:.0%} move - verify")

      return len(errors) == 0, errors
  ```

- [ ] Log validation failures for manual review
- [ ] Skip stocks with unresolved data issues

### 0.4 Gap Analysis Infrastructure

- [ ] Build Monday gap analyzer
  ```python
  @dataclass
  class GapProfile:
      symbol: str
      mean_gap: float
      std_gap: float
      worst_gap: float
      best_gap: float
      prob_gap_below_minus_2pct: float
      prob_gap_above_plus_2pct: float

  def analyze_monday_gaps(ohlcv: list[OHLCV]) -> GapProfile:
      """Quantify Monday opening gap risk"""
      gaps = []

      for i in range(1, len(ohlcv)):
          if ohlcv[i].date.weekday() == 0:  # Monday
              # Find previous Friday
              for j in range(i-1, max(0, i-4), -1):
                  if ohlcv[j].date.weekday() == 4:  # Friday
                      gap = (ohlcv[i].open - ohlcv[j].close) / ohlcv[j].close
                      gaps.append(gap)
                      break

      if not gaps:
          return None

      return GapProfile(
          symbol=symbol,
          mean_gap=statistics.mean(gaps),
          std_gap=statistics.stdev(gaps) if len(gaps) > 1 else 0,
          worst_gap=min(gaps),
          best_gap=max(gaps),
          prob_gap_below_minus_2pct=sum(1 for g in gaps if g < -0.02) / len(gaps),
          prob_gap_above_plus_2pct=sum(1 for g in gaps if g > 0.02) / len(gaps),
      )
  ```

---

## Phase 1: Regime Assessment (MOST CRITICAL)

**This single component prevents most drawdowns.** Implement before anything else.

### 1.1 Regime Model Design

The regime gate determines WHETHER to trade, not WHAT to trade.

- [ ] Define regime states
  ```python
  from enum import Enum

  class RegimeState(Enum):
      RISK_ON = "risk_on"      # Full system active
      CHOPPY = "choppy"        # Reduced size, pullbacks only
      RISK_OFF = "risk_off"    # No new positions

  @dataclass
  class RegimeAssessment:
      state: RegimeState
      risk_on_prob: float      # 0-1
      choppy_prob: float       # 0-1
      risk_off_prob: float     # 0-1
      confidence: float        # How reliable is this assessment?
      indicators: dict         # Raw indicator values for logging
      timestamp: datetime

      def position_multiplier(self) -> float:
          """Scale ALL position sizes by this"""
          if self.risk_on_prob > 0.70:
              return 1.0
          elif self.risk_on_prob > 0.50:
              return 0.7
          elif self.risk_off_prob > 0.50:
              return 0.0  # NO TRADES
          else:
              return 0.5  # Choppy - half size
  ```

### 1.2 Regime Indicators

- [ ] **Trend Structure (25% weight)**
  ```python
  def trend_score(nifty_ohlcv: list[OHLCV]) -> float:
      """0-100 score for trend health"""
      close = nifty_ohlcv[-1].close
      sma_20 = sma([o.close for o in nifty_ohlcv], 20)[-1]
      sma_50 = sma([o.close for o in nifty_ohlcv], 50)[-1]
      sma_200 = sma([o.close for o in nifty_ohlcv], 200)[-1]

      score = 0

      # Price vs MAs
      if close > sma_20: score += 15
      if close > sma_50: score += 15
      if close > sma_200: score += 20

      # MA alignment
      if sma_20 > sma_50 > sma_200: score += 25
      elif sma_20 > sma_50: score += 15
      elif sma_50 > sma_200: score += 10

      # MA slopes
      slope_50 = (sma_50 - sma([o.close for o in nifty_ohlcv[:-20]], 50)[-1]) / sma_50
      if slope_50 > 0.02: score += 25
      elif slope_50 > 0: score += 15

      return score
  ```

- [ ] **Market Breadth (25% weight)**
  ```python
  def breadth_score(universe_ohlcv: dict[str, list[OHLCV]]) -> float:
      """0-100 score for market breadth"""
      above_200dma = 0
      above_50dma = 0
      total = len(universe_ohlcv)

      for symbol, ohlcv in universe_ohlcv.items():
          close = ohlcv[-1].close
          if len(ohlcv) >= 200:
              sma_200 = sum(o.close for o in ohlcv[-200:]) / 200
              if close > sma_200:
                  above_200dma += 1
          if len(ohlcv) >= 50:
              sma_50 = sum(o.close for o in ohlcv[-50:]) / 50
              if close > sma_50:
                  above_50dma += 1

      pct_above_200 = above_200dma / total
      pct_above_50 = above_50dma / total

      score = 0
      if pct_above_200 > 0.60: score += 50
      elif pct_above_200 > 0.45: score += 35
      elif pct_above_200 > 0.30: score += 20

      if pct_above_50 > 0.60: score += 50
      elif pct_above_50 > 0.45: score += 35
      elif pct_above_50 > 0.30: score += 20

      return score
  ```

- [ ] **Volatility Regime (25% weight)**
  ```python
  def volatility_score(vix_data: list[float]) -> float:
      """0-100 score based on India VIX"""
      current_vix = vix_data[-1]
      vix_10d_avg = sum(vix_data[-10:]) / 10
      vix_trend = (current_vix - vix_10d_avg) / vix_10d_avg

      score = 0

      # Absolute level
      if current_vix < 13: score += 40
      elif current_vix < 16: score += 35
      elif current_vix < 20: score += 25
      elif current_vix < 25: score += 10
      else: score += 0

      # Trend (falling VIX = good)
      if vix_trend < -0.10: score += 40
      elif vix_trend < -0.05: score += 30
      elif vix_trend < 0.05: score += 20
      elif vix_trend < 0.10: score += 10
      else: score += 0

      # VIX spike detection
      if current_vix > vix_10d_avg * 1.3:
          score = max(0, score - 30)  # Penalty for spike

      return score
  ```

- [ ] **Sector Leadership (25% weight)**
  ```python
  def leadership_score(sector_returns: dict[str, float]) -> float:
      """
      0-100 score based on which sectors are leading
      Cyclicals leading = Risk-On
      Defensives leading = Risk-Off
      """
      cyclical = ['NIFTY BANK', 'NIFTY METAL', 'NIFTY REALTY', 'NIFTY AUTO']
      defensive = ['NIFTY PHARMA', 'NIFTY FMCG', 'NIFTY IT']

      cyclical_avg = sum(sector_returns.get(s, 0) for s in cyclical) / len(cyclical)
      defensive_avg = sum(sector_returns.get(s, 0) for s in defensive) / len(defensive)

      spread = cyclical_avg - defensive_avg

      if spread > 0.03: return 100  # Cyclicals leading by 3%+
      elif spread > 0.01: return 75
      elif spread > -0.01: return 50
      elif spread > -0.03: return 25
      else: return 0  # Defensives leading
  ```

### 1.3 Regime Classification

- [ ] Combine indicators into final assessment
  ```python
  def assess_regime(
      nifty_ohlcv: list[OHLCV],
      universe_ohlcv: dict[str, list[OHLCV]],
      vix_data: list[float],
      sector_returns: dict[str, float]
  ) -> RegimeAssessment:
      """
      Weighted combination of all regime indicators
      """
      weights = {
          'trend': 0.25,
          'breadth': 0.25,
          'volatility': 0.25,
          'leadership': 0.25,
      }

      scores = {
          'trend': trend_score(nifty_ohlcv),
          'breadth': breadth_score(universe_ohlcv),
          'volatility': volatility_score(vix_data),
          'leadership': leadership_score(sector_returns),
      }

      composite = sum(scores[k] * weights[k] for k in weights)

      # Convert to probabilities
      if composite >= 70:
          risk_on_prob = 0.8 + (composite - 70) / 150
          choppy_prob = 0.15
          risk_off_prob = 0.05
          state = RegimeState.RISK_ON
      elif composite >= 40:
          risk_on_prob = (composite - 40) / 60
          choppy_prob = 0.5
          risk_off_prob = 1 - risk_on_prob - choppy_prob
          state = RegimeState.CHOPPY
      else:
          risk_on_prob = composite / 80
          choppy_prob = 0.2
          risk_off_prob = 1 - risk_on_prob - choppy_prob
          state = RegimeState.RISK_OFF

      return RegimeAssessment(
          state=state,
          risk_on_prob=risk_on_prob,
          choppy_prob=choppy_prob,
          risk_off_prob=risk_off_prob,
          confidence=0.7,  # Can be adjusted based on indicator agreement
          indicators=scores,
          timestamp=datetime.now(),
      )
  ```

### 1.4 Regime-Based Rules

- [ ] Define system behavior per regime
  ```python
  REGIME_RULES = {
      RegimeState.RISK_ON: {
          'max_positions': 10,
          'position_size_multiplier': 1.0,
          'allowed_setups': ['pullback', 'breakout', 'retest'],
          'min_rr_ratio': 2.0,
      },
      RegimeState.CHOPPY: {
          'max_positions': 5,
          'position_size_multiplier': 0.5,
          'allowed_setups': ['pullback'],  # Only pullbacks in choppy
          'min_rr_ratio': 2.5,  # Higher bar
      },
      RegimeState.RISK_OFF: {
          'max_positions': 0,  # No new positions
          'position_size_multiplier': 0.0,
          'allowed_setups': [],
          'min_rr_ratio': float('inf'),
      },
  }
  ```

---

## Phase 2: Project Foundation

### 2.1 Project Refactoring

- [ ] Rename package from `modern_python_boilerplate` to `trade_analyzer`
  - Update `src/` folder structure
  - Update `pyproject.toml`
  - Update Makefile
  - Update imports

- [ ] Create directory structure
  ```
  src/trade_analyzer/
  ├── __init__.py
  ├── main.py
  ├── config.py
  ├── pipeline/
  │   ├── __init__.py
  │   ├── regime.py          # Phase 1
  │   ├── universe.py        # Phase 3
  │   ├── factors.py         # Phase 4
  │   ├── setups.py          # Phase 5
  │   ├── risk.py            # Phase 6
  │   └── portfolio.py       # Phase 7
  ├── data/
  │   ├── __init__.py
  │   ├── providers/
  │   │   ├── __init__.py
  │   │   ├── nse.py
  │   │   ├── yfinance_provider.py
  │   │   └── fundamentals.py
  │   ├── cache.py
  │   └── validation.py      # Phase 0
  ├── models/
  │   ├── __init__.py
  │   ├── stock.py
  │   ├── ohlcv.py
  │   ├── regime.py
  │   ├── factors.py
  │   ├── setup.py
  │   └── portfolio.py
  ├── indicators/
  │   ├── __init__.py
  │   ├── moving_averages.py
  │   ├── momentum.py
  │   ├── volatility.py
  │   └── volume.py
  ├── execution/             # Phase 8
  │   ├── __init__.py
  │   ├── gaps.py
  │   └── orders.py
  ├── monitoring/            # Phase 9
  │   ├── __init__.py
  │   ├── health.py
  │   └── tracking.py
  ├── output/
  │   ├── __init__.py
  │   ├── reports.py
  │   └── templates/
  └── utils/
      ├── __init__.py
      └── helpers.py
  tests/
  └── ... (mirror src structure)
  ```

### 2.2 Configuration

- [ ] Create `config.py`
  ```python
  from dataclasses import dataclass
  from pathlib import Path

  @dataclass
  class PortfolioConfig:
      total_capital: float = 10_00_000  # ₹10 lakhs
      risk_per_trade: float = 0.015     # 1.5%
      max_positions: int = 10
      cash_reserve: float = 0.20        # 20%
      max_sector_exposure: float = 0.25 # 25%
      max_stocks_per_sector: int = 3

  @dataclass
  class FilterConfig:
      # Universe
      min_turnover: float = 5_00_00_000      # ₹5 crores
      min_market_cap: float = 1000_00_00_000  # ₹1,000 crores
      max_circuit_hits: int = 2
      min_trading_days_pct: float = 0.90

      # Momentum
      max_distance_from_52w_high: float = 0.10  # 10%
      min_relative_strength: float = 0.10       # +10pp vs Nifty

      # Consistency
      min_positive_weeks: float = 0.55  # Lowered from 0.60 for statistical validity
      min_weeks_above_3pct: float = 0.20
      ideal_std_range: tuple = (0.03, 0.07)

      # Risk
      min_reward_risk: float = 2.0
      max_stop_distance: float = 0.07  # 7%

  @dataclass
  class CostConfig:
      brokerage_rate: float = 0.0003
      stt_rate: float = 0.002  # 0.1% buy + 0.1% sell
      other_charges: float = 0.0007
      stcg_tax_rate: float = 0.15

      def round_trip_pct(self) -> float:
          return self.brokerage_rate * 2 + self.stt_rate + self.other_charges

  @dataclass
  class Config:
      portfolio: PortfolioConfig = PortfolioConfig()
      filters: FilterConfig = FilterConfig()
      costs: CostConfig = CostConfig()
      cache_dir: Path = Path.home() / '.trade_analyzer' / 'cache'
      history_days: int = 400  # ~80 weeks
  ```

### 2.3 Data Models

- [ ] `models/stock.py`
  ```python
  @dataclass
  class Stock:
      symbol: str
      name: str
      sector: str
      industry: str
      market_cap: float
      is_nifty200: bool
      is_nifty500: bool
      is_fno: bool
      fno_lot_size: Optional[int] = None
  ```

- [ ] `models/ohlcv.py`
  ```python
  @dataclass
  class OHLCV:
      date: date
      open: float
      high: float
      low: float
      close: float
      volume: int

      @property
      def turnover(self) -> float:
          return self.volume * self.close

  @dataclass
  class WeeklyOHLCV:
      week_start: date
      week_end: date
      open: float
      high: float
      low: float
      close: float
      volume: int

      @classmethod
      def from_daily(cls, daily: list[OHLCV]) -> 'WeeklyOHLCV':
          return cls(
              week_start=daily[0].date,
              week_end=daily[-1].date,
              open=daily[0].open,
              high=max(d.high for d in daily),
              low=min(d.low for d in daily),
              close=daily[-1].close,
              volume=sum(d.volume for d in daily),
          )
  ```

- [ ] `models/factors.py`
  ```python
  @dataclass
  class MomentumScore:
      high_52w_proximity: float  # 0-1, higher = closer to high
      ma_alignment: bool
      ma_alignment_score: float  # 0-100
      slope_50dma: float
      slope_200dma: float
      rs_vs_nifty_3m: float
      rs_vs_nifty_6m: float
      composite_score: float

  @dataclass
  class ConsistencyScore:
      pct_positive_weeks: float
      pct_weeks_above_3pct: float
      pct_weeks_above_5pct: float
      avg_weekly_return: float
      weekly_std_dev: float
      worst_week: float
      best_week: float
      sharpe_like_ratio: float
      is_statistically_significant: bool
      p_value: float
      composite_score: float

  @dataclass
  class VolumeScore:
      avg_turnover_20d: float
      volume_trend: float  # Positive = expanding
      recent_volume_ratio: float  # vs 20d avg
      composite_score: float

  @dataclass
  class CompositeFactorScore:
      stock: Stock
      momentum: MomentumScore
      consistency: ConsistencyScore
      volume: VolumeScore
      final_score: float
      rank: int
  ```

- [ ] `models/setup.py`
  ```python
  @dataclass
  class TradeSetup:
      stock: Stock
      setup_type: Literal['pullback', 'breakout', 'retest']
      setup_quality_score: float  # 0-100

      # Entry
      entry_zone: tuple[float, float]
      entry_trigger: str  # Description

      # Risk
      stop_loss: float
      stop_logic: str
      risk_per_share: float
      risk_pct: float

      # Reward
      target_1: float
      target_2: float
      reward_risk_ratio: float

      # Context
      thesis: str
      factors: CompositeFactorScore
      gap_profile: GapProfile

      # Contingencies
      gap_contingency: str
      invalidation_conditions: list[str]

  @dataclass
  class Position:
      setup: TradeSetup
      shares: int
      capital_deployed: float
      risk_amount: float
      regime_multiplier: float  # Applied size adjustment

  @dataclass
  class Portfolio:
      positions: list[Position]
      regime: RegimeAssessment

      total_capital: float
      deployed_capital: float
      cash_reserve: float
      total_risk: float

      sector_exposure: dict[str, float]

      generation_timestamp: datetime
      valid_until: date  # Usually next Friday
  ```

---

## Phase 3: Universe Sanitization

### 3.1 Universe Sources

- [ ] Implement data fetchers
  ```python
  # data/providers/nse.py

  def get_nifty200_constituents() -> list[str]:
      """Fetch current Nifty 200 symbols"""
      # Source: NSE website or niftyindices.com
      pass

  def get_nifty500_constituents() -> list[str]:
      """Fetch current Nifty 500 symbols"""
      pass

  def get_fno_stocks() -> dict[str, int]:
      """Fetch F&O eligible stocks with lot sizes"""
      # Returns {symbol: lot_size}
      pass

  def merge_universe() -> list[str]:
      """Merge all sources, deduplicate"""
      n200 = set(get_nifty200_constituents())
      n500 = set(get_nifty500_constituents())
      fno = set(get_fno_stocks().keys())
      return list(n200 | n500 | fno)
  ```

### 3.2 Elimination Filters

- [ ] Implement each filter with logging
  ```python
  # pipeline/universe.py

  @dataclass
  class FilterResult:
      passed: list[Stock]
      failed: list[tuple[Stock, str]]  # (stock, reason)

  def filter_liquidity(
      stocks: list[Stock],
      ohlcv_data: dict[str, list[OHLCV]],
      min_turnover: float
  ) -> FilterResult:
      passed = []
      failed = []

      for stock in stocks:
          ohlcv = ohlcv_data.get(stock.symbol)
          if not ohlcv or len(ohlcv) < 20:
              failed.append((stock, "Insufficient data"))
              continue

          avg_turnover = sum(o.turnover for o in ohlcv[-20:]) / 20

          if avg_turnover >= min_turnover:
              passed.append(stock)
          else:
              failed.append((stock, f"Low turnover: ₹{avg_turnover/1e7:.1f}Cr < ₹{min_turnover/1e7:.1f}Cr"))

      return FilterResult(passed, failed)

  def filter_circuits(
      stocks: list[Stock],
      ohlcv_data: dict[str, list[OHLCV]],
      max_circuits: int,
      lookback_days: int = 30
  ) -> FilterResult:
      """Remove stocks that hit circuits frequently"""
      passed = []
      failed = []

      for stock in stocks:
          ohlcv = ohlcv_data.get(stock.symbol)
          if not ohlcv:
              failed.append((stock, "No data"))
              continue

          circuit_count = 0
          for o in ohlcv[-lookback_days:]:
              # Circuit detection: >4.5% move with unusual volume pattern
              # This is approximate - real circuit detection needs intraday data
              daily_range = (o.high - o.low) / o.low
              if daily_range < 0.01:  # Very tight range = likely circuit
                  circuit_count += 1

          if circuit_count <= max_circuits:
              passed.append(stock)
          else:
              failed.append((stock, f"Circuit-prone: {circuit_count} hits"))

      return FilterResult(passed, failed)

  # Similar for: filter_market_cap, filter_trading_days
  ```

### 3.3 Universe Pipeline

- [ ] Combine filters into pipeline
  ```python
  def build_tradable_universe(config: Config) -> tuple[list[Stock], dict]:
      """
      Run all universe filters
      Returns (qualified_stocks, filter_stats)
      """
      # Fetch raw universe
      symbols = merge_universe()
      stocks = [fetch_stock_info(s) for s in symbols]
      ohlcv_data = fetch_all_ohlcv(symbols, days=config.history_days)

      stats = {'initial': len(stocks)}

      # Apply filters in order
      result = filter_liquidity(stocks, ohlcv_data, config.filters.min_turnover)
      stats['after_liquidity'] = len(result.passed)
      stats['liquidity_failed'] = len(result.failed)

      result = filter_market_cap(result.passed, config.filters.min_market_cap)
      stats['after_mcap'] = len(result.passed)

      result = filter_circuits(result.passed, ohlcv_data, config.filters.max_circuit_hits)
      stats['after_circuits'] = len(result.passed)

      result = filter_trading_days(result.passed, ohlcv_data, config.filters.min_trading_days_pct)
      stats['after_trading_days'] = len(result.passed)

      return result.passed, stats
  ```

---

## Phase 4: Factor Scoring Engine

### 4.1 Momentum Scoring

- [ ] Implement momentum calculations
  ```python
  # pipeline/factors.py

  def calculate_momentum_score(
      stock: Stock,
      ohlcv: list[OHLCV],
      nifty_ohlcv: list[OHLCV],
      config: FilterConfig
  ) -> MomentumScore:
      close = ohlcv[-1].close

      # 52-week high proximity
      high_52w = max(o.high for o in ohlcv[-252:])
      proximity = 1 - (high_52w - close) / high_52w

      # MA calculations
      sma_20 = sma([o.close for o in ohlcv], 20)[-1]
      sma_50 = sma([o.close for o in ohlcv], 50)[-1]
      sma_200 = sma([o.close for o in ohlcv], 200)[-1]

      ma_alignment = close > sma_50 > sma_200

      # MA slopes
      sma_50_prev = sma([o.close for o in ohlcv[:-20]], 50)[-1]
      sma_200_prev = sma([o.close for o in ohlcv[:-50]], 200)[-1]
      slope_50 = (sma_50 - sma_50_prev) / sma_50_prev
      slope_200 = (sma_200 - sma_200_prev) / sma_200_prev

      # Relative strength
      stock_return_3m = (ohlcv[-1].close / ohlcv[-63].close) - 1
      stock_return_6m = (ohlcv[-1].close / ohlcv[-126].close) - 1
      nifty_return_3m = (nifty_ohlcv[-1].close / nifty_ohlcv[-63].close) - 1
      nifty_return_6m = (nifty_ohlcv[-1].close / nifty_ohlcv[-126].close) - 1

      rs_3m = stock_return_3m - nifty_return_3m
      rs_6m = stock_return_6m - nifty_return_6m

      # Composite (weighted average of normalized scores)
      composite = (
          proximity * 0.25 +
          (1.0 if ma_alignment else 0.0) * 0.25 +
          min(1.0, max(0, slope_50 / 0.05)) * 0.15 +
          min(1.0, max(0, rs_3m / 0.20)) * 0.175 +
          min(1.0, max(0, rs_6m / 0.20)) * 0.175
      )

      return MomentumScore(
          high_52w_proximity=proximity,
          ma_alignment=ma_alignment,
          ma_alignment_score=100 if ma_alignment else 0,
          slope_50dma=slope_50,
          slope_200dma=slope_200,
          rs_vs_nifty_3m=rs_3m,
          rs_vs_nifty_6m=rs_6m,
          composite_score=composite * 100,
      )
  ```

### 4.2 Consistency Scoring with Statistical Significance

- [ ] Implement consistency with significance testing
  ```python
  from scipy import stats

  def calculate_consistency_score(
      ohlcv: list[OHLCV],
      config: FilterConfig
  ) -> ConsistencyScore:
      # Convert to weekly
      weekly = resample_to_weekly(ohlcv)

      # Calculate returns
      returns = [
          (weekly[i].close / weekly[i-1].close) - 1
          for i in range(1, len(weekly))
      ]

      # Take last 52 weeks
      returns = returns[-52:]

      if len(returns) < 40:  # Need minimum data
          return None

      # Basic metrics
      positive = sum(1 for r in returns if r > 0)
      above_3pct = sum(1 for r in returns if r >= 0.03)
      above_5pct = sum(1 for r in returns if r >= 0.05)

      pct_positive = positive / len(returns)
      pct_above_3pct = above_3pct / len(returns)
      pct_above_5pct = above_5pct / len(returns)

      avg_return = statistics.mean(returns)
      std_dev = statistics.stdev(returns)
      worst = min(returns)
      best = max(returns)

      sharpe_like = avg_return / std_dev if std_dev > 0 else 0

      # Statistical significance test
      # H0: true positive rate = 50%
      # H1: true positive rate > 50%
      p_value = stats.binom_test(positive, len(returns), 0.50, alternative='greater')
      is_significant = p_value < 0.10  # 90% confidence

      # Composite score (only if significant)
      if is_significant:
          composite = (
              min(1.0, pct_positive / 0.65) * 0.30 +
              min(1.0, pct_above_3pct / 0.30) * 0.25 +
              sharpe_like * 0.25 +
              (1 - abs(std_dev - 0.045) / 0.03) * 0.20  # Prefer ~4.5% std dev
          )
      else:
          composite = 0  # Not statistically significant

      return ConsistencyScore(
          pct_positive_weeks=pct_positive,
          pct_weeks_above_3pct=pct_above_3pct,
          pct_weeks_above_5pct=pct_above_5pct,
          avg_weekly_return=avg_return,
          weekly_std_dev=std_dev,
          worst_week=worst,
          best_week=best,
          sharpe_like_ratio=sharpe_like,
          is_statistically_significant=is_significant,
          p_value=p_value,
          composite_score=composite * 100,
      )
  ```

### 4.3 Composite Factor Ranking

- [ ] Combine all factors
  ```python
  def calculate_composite_score(
      stock: Stock,
      ohlcv: list[OHLCV],
      nifty_ohlcv: list[OHLCV],
      config: Config
  ) -> Optional[CompositeFactorScore]:
      """
      Calculate all factor scores and combine
      Returns None if stock fails any hard filter
      """
      momentum = calculate_momentum_score(stock, ohlcv, nifty_ohlcv, config.filters)
      consistency = calculate_consistency_score(ohlcv, config.filters)
      volume = calculate_volume_score(ohlcv, config.filters)

      # Hard filters
      if momentum.high_52w_proximity < 0.90:  # Not within 10% of high
          return None
      if not momentum.ma_alignment:
          return None
      if momentum.rs_vs_nifty_3m < config.filters.min_relative_strength:
          return None
      if momentum.rs_vs_nifty_6m < config.filters.min_relative_strength:
          return None
      if not consistency.is_statistically_significant:
          return None
      if consistency.pct_positive_weeks < config.filters.min_positive_weeks:
          return None

      # Weighted combination
      final_score = (
          momentum.composite_score * 0.35 +
          consistency.composite_score * 0.40 +
          volume.composite_score * 0.25
      )

      return CompositeFactorScore(
          stock=stock,
          momentum=momentum,
          consistency=consistency,
          volume=volume,
          final_score=final_score,
          rank=0,  # Set after ranking all stocks
      )
  ```

---

## Phase 5: Setup Detection

### 5.1 Pullback Detection (Start Here)

- [ ] Implement quality pullback detection
  ```python
  # pipeline/setups.py

  def detect_pullback(
      stock: Stock,
      ohlcv: list[OHLCV],
      factors: CompositeFactorScore
  ) -> Optional[TradeSetup]:
      """
      Detect quality pullback to rising MA
      """
      close = ohlcv[-1].close
      sma_20 = sma([o.close for o in ohlcv], 20)
      sma_50 = sma([o.close for o in ohlcv], 50)

      # Find recent high (impulse peak)
      recent_high = max(o.high for o in ohlcv[-20:])
      pullback_depth = (recent_high - close) / recent_high

      # Check pullback conditions
      if pullback_depth < 0.03:
          return None  # Not enough pullback
      if pullback_depth > 0.10:
          return None  # Too deep

      # Check near rising MA
      ma_20_current = sma_20[-1]
      ma_distance = (close - ma_20_current) / ma_20_current

      if abs(ma_distance) > 0.02:
          return None  # Not near MA

      # Check MA is rising
      ma_slope = (sma_20[-1] - sma_20[-5]) / sma_20[-5]
      if ma_slope < 0.005:
          return None  # MA not rising enough

      # Check volume contracting during pullback
      pullback_bars = [o for o in ohlcv[-10:] if o.close < recent_high * 0.98]
      impulse_bars = [o for o in ohlcv[-20:-10]]

      if pullback_bars and impulse_bars:
          pullback_vol = sum(o.volume for o in pullback_bars) / len(pullback_bars)
          impulse_vol = sum(o.volume for o in impulse_bars) / len(impulse_bars)
          if pullback_vol > impulse_vol:
              return None  # Volume expanding on pullback = distribution

      # Check swing low intact
      swing_low = min(o.low for o in ohlcv[-20:-5])
      recent_low = min(o.low for o in ohlcv[-5:])
      if recent_low < swing_low:
          return None  # Broke swing low

      # Calculate entry, stop, target
      entry_low = ma_20_current * 0.995
      entry_high = ma_20_current * 1.005
      stop_loss = min(swing_low * 0.99, close - 2 * calculate_atr(ohlcv, 14))

      risk_per_share = (entry_low + entry_high) / 2 - stop_loss
      risk_pct = risk_per_share / ((entry_low + entry_high) / 2)

      if risk_pct > 0.07:
          return None  # Stop too wide

      target_1 = (entry_low + entry_high) / 2 + 2 * risk_per_share
      target_2 = (entry_low + entry_high) / 2 + 3 * risk_per_share

      return TradeSetup(
          stock=stock,
          setup_type='pullback',
          setup_quality_score=80,  # Can be refined
          entry_zone=(entry_low, entry_high),
          entry_trigger=f"Bounce from 20-DMA at ₹{ma_20_current:.2f}",
          stop_loss=stop_loss,
          stop_logic=f"Below swing low at ₹{swing_low:.2f}",
          risk_per_share=risk_per_share,
          risk_pct=risk_pct,
          target_1=target_1,
          target_2=target_2,
          reward_risk_ratio=2.0,
          thesis=f"Healthy pullback in uptrend. {pullback_depth:.1%} pullback to rising 20-DMA with volume contraction.",
          factors=factors,
          gap_profile=analyze_monday_gaps(ohlcv),
          gap_contingency="If gap >2% against, skip. If gap favorable, adjust stop.",
          invalidation_conditions=[
              f"Close below ₹{swing_low:.2f}",
              "Break of 50-DMA",
              "Volume expansion on continued decline",
          ],
      )
  ```

### 5.2 Breakout Detection (Add Later)

- [ ] Implement consolidation + breakout detection
  ```python
  def detect_breakout(
      stock: Stock,
      ohlcv: list[OHLCV],
      factors: CompositeFactorScore
  ) -> Optional[TradeSetup]:
      """
      Detect consolidation breakout setup
      """
      # Find consolidation range (3-8 weeks)
      consolidation = find_consolidation(ohlcv, min_weeks=3, max_weeks=8)
      if not consolidation:
          return None

      close = ohlcv[-1].close

      # Check if breaking out
      if close < consolidation['high']:
          return None  # Not breaking out yet

      # Check breakout volume
      avg_vol = sum(o.volume for o in ohlcv[-20:]) / 20
      if ohlcv[-1].volume < avg_vol * 1.3:
          return None  # Weak volume on breakout

      # Build setup
      entry_low = consolidation['high']
      entry_high = consolidation['high'] * 1.02
      stop_loss = consolidation['low'] * 0.99

      # ... rest of setup construction
  ```

### 5.3 Retest Detection (Add Last)

- [ ] Implement breakout retest detection
  ```python
  def detect_retest(
      stock: Stock,
      ohlcv: list[OHLCV],
      factors: CompositeFactorScore
  ) -> Optional[TradeSetup]:
      """
      Detect breakout retest setup
      """
      # Find recent breakout (1-3 weeks ago)
      breakout = find_recent_breakout(ohlcv, min_weeks=1, max_weeks=3)
      if not breakout:
          return None

      close = ohlcv[-1].close

      # Check if retesting breakout level
      distance_from_breakout = abs(close - breakout['level']) / breakout['level']
      if distance_from_breakout > 0.02:
          return None  # Not near breakout level

      # Check holding above breakout
      if close < breakout['level'] * 0.98:
          return None  # Failed retest

      # Check volume lower on retest
      retest_vol = sum(o.volume for o in ohlcv[-5:]) / 5
      if retest_vol > breakout['volume'] * 0.8:
          return None  # Too much volume = selling

      # ... rest of setup construction
  ```

---

## Phase 6: Risk Geometry Filter

### 6.1 Risk Calculations

- [ ] Implement stop and target calculations
  ```python
  # pipeline/risk.py

  def calculate_stop_loss(
      ohlcv: list[OHLCV],
      entry: float,
      setup_type: str
  ) -> tuple[float, str]:
      """
      Returns (stop_price, logic_description)
      Uses tighter of swing low or ATR-based stop
      """
      atr_14 = calculate_atr(ohlcv, 14)

      # Method 1: Recent swing low
      swing_low = min(o.low for o in ohlcv[-20:])

      # Method 2: ATR-based
      atr_stop = entry - (2 * atr_14)

      # Use tighter stop (higher price)
      if swing_low > atr_stop:
          return swing_low * 0.99, f"Below swing low at ₹{swing_low:.2f}"
      else:
          return atr_stop, f"2x ATR (₹{atr_14:.2f}) below entry"

  def validate_risk_geometry(
      setup: TradeSetup,
      config: FilterConfig
  ) -> tuple[bool, str]:
      """
      Validate setup meets risk criteria
      Returns (is_valid, rejection_reason)
      """
      # Check stop distance
      if setup.risk_pct > config.max_stop_distance:
          return False, f"Stop too wide: {setup.risk_pct:.1%} > {config.max_stop_distance:.1%}"

      # Check reward:risk
      if setup.reward_risk_ratio < config.min_reward_risk:
          return False, f"R:R too low: {setup.reward_risk_ratio:.1f} < {config.min_reward_risk:.1f}"

      # Check entry not extended
      # (implementation depends on setup type)

      return True, ""
  ```

### 6.2 Position Sizing

- [ ] Implement position sizing with regime adjustment
  ```python
  def calculate_position_size(
      setup: TradeSetup,
      portfolio_config: PortfolioConfig,
      regime: RegimeAssessment,
      cost_config: CostConfig
  ) -> Position:
      """
      Calculate position size using fixed fractional method
      Adjusted for regime and transaction costs
      """
      # Base risk amount
      base_risk = portfolio_config.total_capital * portfolio_config.risk_per_trade

      # Apply regime multiplier
      regime_multiplier = regime.position_multiplier()
      adjusted_risk = base_risk * regime_multiplier

      # Calculate shares
      risk_per_share = setup.risk_per_share
      shares = int(adjusted_risk / risk_per_share)

      # Adjust for F&O lot size if applicable
      if setup.stock.is_fno and setup.stock.fno_lot_size:
          lots = max(1, round(shares / setup.stock.fno_lot_size))
          shares = lots * setup.stock.fno_lot_size

      # Calculate deployment
      entry_price = (setup.entry_zone[0] + setup.entry_zone[1]) / 2
      capital_deployed = shares * entry_price
      actual_risk = shares * risk_per_share

      # Verify against portfolio constraints
      max_deployment = portfolio_config.total_capital * (1 - portfolio_config.cash_reserve)
      if capital_deployed > max_deployment:
          # Scale down
          shares = int(max_deployment / entry_price)
          capital_deployed = shares * entry_price
          actual_risk = shares * risk_per_share

      return Position(
          setup=setup,
          shares=shares,
          capital_deployed=capital_deployed,
          risk_amount=actual_risk,
          regime_multiplier=regime_multiplier,
      )
  ```

---

## Phase 7: Portfolio Construction

### 7.1 Correlation Filtering

- [ ] Implement correlation-based position selection
  ```python
  def filter_correlated_positions(
      positions: list[Position],
      ohlcv_data: dict[str, list[OHLCV]],
      max_correlation: float = 0.70
  ) -> list[Position]:
      """
      Remove highly correlated positions, keeping highest conviction
      """
      if len(positions) <= 1:
          return positions

      # Sort by conviction (factor score)
      positions = sorted(positions, key=lambda p: p.setup.factors.final_score, reverse=True)

      # Calculate correlation matrix
      symbols = [p.setup.stock.symbol for p in positions]
      returns = {
          s: [
              (ohlcv_data[s][i].close / ohlcv_data[s][i-1].close) - 1
              for i in range(1, len(ohlcv_data[s]))
          ][-52:]  # Last 52 weeks
          for s in symbols
      }

      selected = [positions[0]]  # Always include top pick

      for position in positions[1:]:
          symbol = position.setup.stock.symbol

          # Check correlation with all selected positions
          is_correlated = False
          for selected_pos in selected:
              selected_symbol = selected_pos.setup.stock.symbol
              corr = calculate_correlation(returns[symbol], returns[selected_symbol])

              if abs(corr) > max_correlation:
                  is_correlated = True
                  break

          if not is_correlated:
              selected.append(position)

      return selected
  ```

### 7.2 Sector Constraints

- [ ] Apply sector limits
  ```python
  def apply_sector_constraints(
      positions: list[Position],
      config: PortfolioConfig
  ) -> list[Position]:
      """
      Enforce sector exposure limits
      """
      sector_count = {}
      sector_exposure = {}
      selected = []

      # Sort by conviction
      positions = sorted(positions, key=lambda p: p.setup.factors.final_score, reverse=True)

      for position in positions:
          sector = position.setup.stock.sector

          # Check count limit
          if sector_count.get(sector, 0) >= config.max_stocks_per_sector:
              continue

          # Check exposure limit
          current_exposure = sector_exposure.get(sector, 0)
          new_exposure = current_exposure + position.capital_deployed
          if new_exposure / config.total_capital > config.max_sector_exposure:
              continue

          # Accept position
          selected.append(position)
          sector_count[sector] = sector_count.get(sector, 0) + 1
          sector_exposure[sector] = new_exposure

      return selected
  ```

### 7.3 Final Portfolio Assembly

- [ ] Assemble final portfolio
  ```python
  def construct_portfolio(
      setups: list[TradeSetup],
      regime: RegimeAssessment,
      ohlcv_data: dict[str, list[OHLCV]],
      config: Config
  ) -> Portfolio:
      """
      Construct final portfolio from setups
      """
      # Check regime gate
      if regime.state == RegimeState.RISK_OFF:
          return Portfolio.empty(regime, "Risk-Off: No positions")

      # Filter by allowed setup types
      allowed = REGIME_RULES[regime.state]['allowed_setups']
      setups = [s for s in setups if s.setup_type in allowed]

      # Calculate position sizes
      positions = [
          calculate_position_size(s, config.portfolio, regime, config.costs)
          for s in setups
      ]

      # Apply correlation filter
      positions = filter_correlated_positions(positions, ohlcv_data)

      # Apply sector constraints
      positions = apply_sector_constraints(positions, config.portfolio)

      # Limit position count
      max_pos = REGIME_RULES[regime.state]['max_positions']
      positions = positions[:max_pos]

      # Calculate portfolio metrics
      deployed = sum(p.capital_deployed for p in positions)
      total_risk = sum(p.risk_amount for p in positions)

      sector_exposure = {}
      for p in positions:
          sector = p.setup.stock.sector
          sector_exposure[sector] = sector_exposure.get(sector, 0) + p.capital_deployed

      return Portfolio(
          positions=positions,
          regime=regime,
          total_capital=config.portfolio.total_capital,
          deployed_capital=deployed,
          cash_reserve=config.portfolio.total_capital - deployed,
          total_risk=total_risk,
          sector_exposure=sector_exposure,
          generation_timestamp=datetime.now(),
          valid_until=next_friday(),
      )
  ```

---

## Phase 8: Execution Layer

### 8.1 Gap Contingency Planning

- [ ] Generate gap contingency for each position
  ```python
  # execution/gaps.py

  @dataclass
  class GapContingency:
      position: Position

      # Scenarios
      action_gap_through_stop: str
      action_small_gap_against: str
      action_gap_favorable: str
      action_gap_above_entry: str

      # Thresholds
      max_acceptable_gap_against: float
      gap_favorable_threshold: float

  def create_gap_contingency(position: Position) -> GapContingency:
      """Create Monday gap contingency plan"""
      setup = position.setup
      entry_mid = (setup.entry_zone[0] + setup.entry_zone[1]) / 2

      return GapContingency(
          position=position,
          action_gap_through_stop="SKIP - Gapped through stop, opportunity lost",
          action_small_gap_against="ENTER_AT_OPEN - Accept worse entry if above stop",
          action_gap_favorable="RECALCULATE - New stop based on gap open",
          action_gap_above_entry="SKIP - Do not chase, wait for pullback",
          max_acceptable_gap_against=(entry_mid - setup.stop_loss) / entry_mid * 0.5,
          gap_favorable_threshold=0.02,
      )

  def monday_decision(
      contingency: GapContingency,
      friday_close: float,
      monday_open: float
  ) -> str:
      """Decide action based on Monday open"""
      setup = contingency.position.setup
      gap_pct = (monday_open - friday_close) / friday_close

      # Gapped through stop
      if monday_open < setup.stop_loss:
          return contingency.action_gap_through_stop

      # Gapped above entry zone
      if monday_open > setup.entry_zone[1] * 1.02:
          return contingency.action_gap_above_entry

      # Within entry zone
      if setup.entry_zone[0] <= monday_open <= setup.entry_zone[1]:
          return "ENTER - Within entry zone"

      # Small gap against but above stop
      if monday_open < setup.entry_zone[0]:
          return contingency.action_small_gap_against

      # Gap favorable
      if gap_pct > contingency.gap_favorable_threshold:
          return contingency.action_gap_favorable

      return "ENTER - Proceed with plan"
  ```

### 8.2 Order Generation

- [ ] Generate order instructions
  ```python
  @dataclass
  class OrderInstruction:
      symbol: str
      action: str  # BUY, SELL
      order_type: str  # LIMIT, MARKET
      quantity: int
      limit_price: Optional[float]
      stop_loss: float
      validity: str  # DAY, GTC
      notes: str

  def generate_orders(portfolio: Portfolio) -> list[OrderInstruction]:
      """Generate order instructions for Monday"""
      orders = []

      for position in portfolio.positions:
          setup = position.setup

          orders.append(OrderInstruction(
              symbol=setup.stock.symbol,
              action='BUY',
              order_type='LIMIT',
              quantity=position.shares,
              limit_price=setup.entry_zone[1],  # Upper limit of zone
              stop_loss=setup.stop_loss,
              validity='DAY',
              notes=f"Entry zone: ₹{setup.entry_zone[0]:.2f}-{setup.entry_zone[1]:.2f}. "
                    f"If filled, immediately place SL at ₹{setup.stop_loss:.2f}",
          ))

      return orders
  ```

---

## Phase 9: Monitoring & Feedback

### 9.1 Trade Tracking

- [ ] Implement trade outcome tracking
  ```python
  # monitoring/tracking.py

  @dataclass
  class TradeOutcome:
      position: Position

      # Execution
      actual_entry: Optional[float]
      actual_entry_date: Optional[date]
      was_filled: bool

      # Result
      exit_price: Optional[float]
      exit_date: Optional[date]
      exit_reason: str  # 'target_1', 'target_2', 'stop_loss', 'time_exit'

      # Metrics
      gross_pnl: float
      net_pnl: float  # After costs
      r_multiple: float
      holding_days: int

      # Analysis
      behaved_as_expected: bool
      notes: str

  def record_outcome(
      position: Position,
      actual_entry: float,
      exit_price: float,
      exit_reason: str,
      costs: CostConfig
  ) -> TradeOutcome:
      """Record trade outcome for analysis"""
      setup = position.setup

      gross_pnl = (exit_price - actual_entry) * position.shares
      trade_value = actual_entry * position.shares
      round_trip_cost = trade_value * costs.round_trip_pct()

      # Tax on profit only
      tax = max(0, gross_pnl) * costs.stcg_tax_rate

      net_pnl = gross_pnl - round_trip_cost - tax

      r_multiple = (exit_price - actual_entry) / setup.risk_per_share

      return TradeOutcome(
          position=position,
          actual_entry=actual_entry,
          actual_entry_date=date.today(),  # Would be actual
          was_filled=True,
          exit_price=exit_price,
          exit_date=date.today(),  # Would be actual
          exit_reason=exit_reason,
          gross_pnl=gross_pnl,
          net_pnl=net_pnl,
          r_multiple=r_multiple,
          holding_days=5,  # Would be calculated
          behaved_as_expected=exit_reason in ['target_1', 'target_2'],
          notes="",
      )
  ```

### 9.2 System Health Monitoring

- [ ] Implement health dashboard
  ```python
  # monitoring/health.py

  @dataclass
  class SystemHealth:
      # Rolling metrics
      win_rate_12w: float
      win_rate_52w: float
      avg_r_multiple_12w: float
      avg_r_multiple_52w: float
      expectancy_12w: float
      expectancy_52w: float

      # Execution quality
      avg_slippage: float
      fill_rate: float

      # Drawdown
      current_drawdown: float
      max_drawdown_12w: float

      def health_score(self) -> float:
          """0-100 health score"""
          score = 0

          # Win rate stability
          if self.win_rate_12w >= self.win_rate_52w * 0.85:
              score += 25
          elif self.win_rate_12w >= self.win_rate_52w * 0.70:
              score += 15

          # Expectancy
          if self.expectancy_12w > 0.05:
              score += 25
          elif self.expectancy_12w > 0:
              score += 15

          # Slippage
          if self.avg_slippage < 0.005:
              score += 25
          elif self.avg_slippage < 0.01:
              score += 15

          # Drawdown
          if self.current_drawdown > -0.10:
              score += 25
          elif self.current_drawdown > -0.15:
              score += 15

          return score

      def alerts(self) -> list[str]:
          """Generate alerts for concerning metrics"""
          alerts = []

          if self.win_rate_12w < self.win_rate_52w - 0.10:
              alerts.append(f"WIN RATE DECLINING: {self.win_rate_12w:.0%} vs {self.win_rate_52w:.0%}")

          if self.expectancy_12w < 0:
              alerts.append(f"NEGATIVE EXPECTANCY: {self.expectancy_12w:.2f}R")

          if self.current_drawdown < -0.15:
              alerts.append(f"SIGNIFICANT DRAWDOWN: {self.current_drawdown:.1%}")

          if self.avg_slippage > 0.01:
              alerts.append(f"HIGH SLIPPAGE: {self.avg_slippage:.2%}")

          return alerts

      def recommended_action(self) -> str:
          """Recommend action based on health"""
          score = self.health_score()

          if score >= 70:
              return "CONTINUE - System healthy"
          elif score >= 50:
              return "REDUCE - Cut position sizes 50%, review parameters"
          elif score >= 30:
              return "PAUSE - Paper trade only, investigate issues"
          else:
              return "STOP - System may be broken, full review required"
  ```

### 9.3 Drawdown Controls

- [ ] Implement portfolio-level drawdown limits
  ```python
  @dataclass
  class DrawdownControl:
      max_weekly_drawdown: float = 0.05    # -5%
      max_monthly_drawdown: float = 0.10   # -10%
      max_total_drawdown: float = 0.20     # -20%

      def check_limits(
          self,
          weekly_return: float,
          monthly_return: float,
          drawdown_from_peak: float
      ) -> tuple[bool, str]:
          """
          Check if drawdown limits exceeded
          Returns (can_trade, reason)
          """
          if drawdown_from_peak < -self.max_total_drawdown:
              return False, f"Max drawdown exceeded: {drawdown_from_peak:.1%}"

          if monthly_return < -self.max_monthly_drawdown:
              return False, f"Monthly drawdown limit: {monthly_return:.1%}"

          if weekly_return < -self.max_weekly_drawdown:
              return False, f"Weekly drawdown limit: {weekly_return:.1%}"

          return True, ""
  ```

---

## Phase 10: Output & Reporting

### 10.1 Trade Sheet Template

- [ ] Create detailed trade sheet
  ```python
  def generate_trade_sheet(position: Position, gap_contingency: GapContingency) -> str:
      setup = position.setup
      stock = setup.stock
      factors = setup.factors

      return f"""
  ═══════════════════════════════════════════════════════════════════
   {stock.name} ({stock.symbol})
  ═══════════════════════════════════════════════════════════════════
   Setup Type: {setup.setup_type.upper()}
   Sector: {stock.sector}

   ENTRY
   ─────────────────────────────────────────────────────────────────
   Zone: ₹{setup.entry_zone[0]:,.2f} - ₹{setup.entry_zone[1]:,.2f}
   Trigger: {setup.entry_trigger}

   RISK MANAGEMENT
   ─────────────────────────────────────────────────────────────────
   Stop Loss: ₹{setup.stop_loss:,.2f} ({setup.stop_logic})
   Risk/Share: ₹{setup.risk_per_share:,.2f} ({setup.risk_pct:.1%})

   TARGETS
   ─────────────────────────────────────────────────────────────────
   Target 1: ₹{setup.target_1:,.2f} (R:R {setup.reward_risk_ratio:.1f}:1)
   Target 2: ₹{setup.target_2:,.2f} (R:R {setup.reward_risk_ratio * 1.5:.1f}:1)

   POSITION SIZING
   ─────────────────────────────────────────────────────────────────
   Shares: {position.shares:,}
   Capital: ₹{position.capital_deployed:,.0f}
   Risk Amount: ₹{position.risk_amount:,.0f}
   Regime Adjustment: {position.regime_multiplier:.0%}

   FACTOR SCORES
   ─────────────────────────────────────────────────────────────────
   Momentum: {factors.momentum.composite_score:.0f}/100
     - 52W High Proximity: {factors.momentum.high_52w_proximity:.1%}
     - RS vs Nifty (3M): {factors.momentum.rs_vs_nifty_3m:+.1%}

   Consistency: {factors.consistency.composite_score:.0f}/100
     - Positive Weeks: {factors.consistency.pct_positive_weeks:.0%}
     - Weekly Std Dev: {factors.consistency.weekly_std_dev:.1%}
     - Significant: {'Yes' if factors.consistency.is_statistically_significant else 'No'}

   GAP CONTINGENCY
   ─────────────────────────────────────────────────────────────────
   {gap_contingency.action_gap_through_stop}
   {gap_contingency.action_small_gap_against}
   {gap_contingency.action_gap_favorable}

   THESIS
   ─────────────────────────────────────────────────────────────────
   {setup.thesis}

   INVALIDATION
   ─────────────────────────────────────────────────────────────────
   {chr(10).join('• ' + c for c in setup.invalidation_conditions)}
  ═══════════════════════════════════════════════════════════════════
  """
  ```

### 10.2 Portfolio Summary

- [ ] Create portfolio summary report
  ```python
  def generate_portfolio_summary(portfolio: Portfolio) -> str:
      regime = portfolio.regime

      # Sector breakdown
      sector_lines = [
          f"   {sector}: ₹{exposure:,.0f} ({exposure/portfolio.total_capital:.0%})"
          for sector, exposure in sorted(portfolio.sector_exposure.items(), key=lambda x: -x[1])
      ]

      return f"""
  ═══════════════════════════════════════════════════════════════════
   WEEKLY PORTFOLIO SUMMARY
   Generated: {portfolio.generation_timestamp.strftime('%Y-%m-%d %H:%M')}
   Valid Until: {portfolio.valid_until.strftime('%Y-%m-%d')} (Friday Close)
  ═══════════════════════════════════════════════════════════════════

   REGIME ASSESSMENT
   ─────────────────────────────────────────────────────────────────
   State: {regime.state.value.upper()}
   Risk-On Probability: {regime.risk_on_prob:.0%}
   Position Multiplier: {regime.position_multiplier():.0%}

   CAPITAL ALLOCATION
   ─────────────────────────────────────────────────────────────────
   Total Capital: ₹{portfolio.total_capital:,.0f}
   Deployed: ₹{portfolio.deployed_capital:,.0f} ({portfolio.deployed_capital/portfolio.total_capital:.0%})
   Cash Reserve: ₹{portfolio.cash_reserve:,.0f} ({portfolio.cash_reserve/portfolio.total_capital:.0%})

   RISK SUMMARY
   ─────────────────────────────────────────────────────────────────
   Total Risk: ₹{portfolio.total_risk:,.0f} ({portfolio.total_risk/portfolio.total_capital:.1%} of capital)
   Positions: {len(portfolio.positions)}
   Avg Risk/Trade: ₹{portfolio.total_risk/len(portfolio.positions):,.0f}

   SECTOR EXPOSURE
   ─────────────────────────────────────────────────────────────────
  {chr(10).join(sector_lines)}

   POSITIONS
   ─────────────────────────────────────────────────────────────────
  {chr(10).join(f'   {i+1}. {p.setup.stock.symbol} - {p.setup.setup_type} - ₹{(p.setup.entry_zone[0]+p.setup.entry_zone[1])/2:,.0f}' for i, p in enumerate(portfolio.positions))}
  ═══════════════════════════════════════════════════════════════════
  """
  ```

---

## Phase 11: CLI

### 11.1 Main Commands

- [ ] Implement CLI with Typer
  ```python
  # main.py
  import typer

  app = typer.Typer()

  @app.command()
  def run(
      capital: float = typer.Option(10_00_000, help="Portfolio capital in INR"),
      output: str = typer.Option("./output", help="Output directory"),
  ):
      """Run full weekly analysis pipeline"""
      config = Config()
      config.portfolio.total_capital = capital

      # Phase 0: Data
      typer.echo("Fetching data...")
      universe_data = fetch_all_data(config)

      # Phase 1: Regime
      typer.echo("Assessing market regime...")
      regime = assess_regime(...)
      typer.echo(f"Regime: {regime.state.value} ({regime.risk_on_prob:.0%} Risk-On)")

      if regime.state == RegimeState.RISK_OFF:
          typer.echo("RISK-OFF: No trades this week.")
          return

      # Continue pipeline...

      # Output
      save_portfolio(portfolio, output)
      typer.echo(f"Portfolio saved to {output}")

  @app.command()
  def regime():
      """Check current market regime only"""
      pass

  @app.command()
  def health():
      """Check system health metrics"""
      pass

  if __name__ == "__main__":
      app()
  ```

---

## Implementation Priority (Revised)

```
Week 1-2: Phase 0 + Phase 2
├── Data validation pipeline
├── Project structure
├── Core data models
└── Data fetching (yfinance)

Week 3-4: Phase 1 (CRITICAL)
├── Regime indicators
├── Regime classification
└── Regime-based rules

Week 5-6: Phase 3 + Phase 4
├── Universe filters
├── Factor calculations
└── Statistical significance

Week 7-8: Phase 5 + Phase 6
├── Pullback detection (start simple)
├── Risk geometry
└── Position sizing

Week 9-10: Phase 7 + Phase 8
├── Portfolio construction
├── Correlation filtering
└── Gap contingency

Week 11-12: Phase 9 + Phase 10
├── Trade tracking
├── Health monitoring
└── Report generation

Week 13+: Phase 11 + Iteration
├── CLI polish
├── Paper trading
└── Refinement based on results
```

---

## Data Sources

| Source | Data | Cost | Reliability |
|--------|------|------|-------------|
| yfinance | OHLCV (add .NS suffix) | Free | Good for daily |
| nsepython | Index data, F&O list | Free | Requires maintenance |
| NSE Website | Official constituents | Free | Rate limited |
| Screener.in | Fundamentals | Free tier | Manual/API |
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

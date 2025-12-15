"""
MongoDB document models using Pydantic.

This module defines all Pydantic models used for MongoDB document validation
and serialization throughout the Trade Analyzer application. Models are
organized by their associated pipeline phase.

Architecture:
-------------
All models inherit from Pydantic BaseModel and use Field() for validation.
Enums are used for categorical fields to ensure type safety.

Model Categories:
----------------
1. ENUMS - State machines for regime, setup type, trade status
2. STOCK DOCUMENTS - Trading universe master data
3. REGIME DOCUMENTS - Market regime assessment
4. TRADE SETUP DOCUMENTS - Detected trading opportunities
5. TRADE DOCUMENTS - Executed trades with P&L tracking
6. SYSTEM HEALTH DOCUMENTS - Performance monitoring
7. FUNDAMENTAL DOCUMENTS - Phase 1 fundamental analysis
8. RISK MANAGEMENT DOCUMENTS - Phase 5-6 position sizing
9. PORTFOLIO DOCUMENTS - Phase 6 portfolio construction
10. EXECUTION DOCUMENTS - Phase 7 trade execution
11. RECOMMENDATION DOCUMENTS - Phase 8 final output

Validation:
-----------
Models use Pydantic's validation features:
- Field(...) for required fields
- Field(default=X) for optional fields with defaults
- ge/le/gt/lt for numeric bounds
- Literal[] for restricted string values

Usage:
------
    from trade_analyzer.db.models import StockDoc, RegimeState

    # Create a stock document
    stock = StockDoc(
        symbol="RELIANCE",
        name="Reliance Industries Ltd",
        sector="Oil & Gas",
        market_cap=1500000,
    )

    # Serialize to dict for MongoDB
    stock_dict = stock.model_dump()

    # Deserialize from MongoDB document
    stock = StockDoc.model_validate(mongo_document)

    # Use enum values
    if regime.state == RegimeState.RISK_OFF:
        print("No trading allowed")

Note:
-----
All models have `class Config: use_enum_values = True` to ensure
enum values (strings) are stored in MongoDB, not enum names.

See Also:
---------
- trade_analyzer.db.connection: Database connection handling
- trade_analyzer.db.repositories: Data access patterns
"""

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# =============================================================================
# ENUMERATIONS
# State machines for various entity lifecycles
# =============================================================================


class RegimeState(str, Enum):
    """
    Market regime states for position sizing and trading decisions.

    The regime determines how aggressively the system trades:
    - RISK_ON: Full position sizes, all setup types allowed
    - CHOPPY: 50% position sizes, only pullbacks allowed
    - RISK_OFF: No new positions, focus on capital preservation

    Attributes:
        RISK_ON: Favorable market conditions (>70% probability)
        CHOPPY: Mixed signals, proceed with caution (50-70%)
        RISK_OFF: Unfavorable conditions (<50% risk-on probability)
    """

    RISK_ON = "risk_on"
    CHOPPY = "choppy"
    RISK_OFF = "risk_off"


class SetupType(str, Enum):
    """
    Technical setup types for trade detection.

    Each setup type has specific entry/exit rules:
    - PULLBACK: Stock in uptrend, pulled back to support (primary setup)
    - BREAKOUT: VCP or consolidation breakout with volume
    - RETEST: Successful breakout retesting breakout level

    Attributes:
        PULLBACK: Trend pullback to 20/50 DMA
        BREAKOUT: Volatility contraction breakout
        RETEST: Breakout level retest
    """

    PULLBACK = "pullback"
    BREAKOUT = "breakout"
    RETEST = "retest"


class TradeStatus(str, Enum):
    """
    Trade lifecycle status tracking.

    Attributes:
        PENDING: Setup identified, awaiting entry
        ACTIVE: Position entered, tracking P&L
        CLOSED_WIN: Exited at profit (target hit)
        CLOSED_loss: Exited at loss (stop hit)
        CANCELLED: Trade cancelled before entry
        SKIPPED: Skipped due to gap or other reason
    """

    PENDING = "pending"
    ACTIVE = "active"
    CLOSED_WIN = "closed_win"
    CLOSED_loss = "closed_loss"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class SetupStatus(str, Enum):
    """
    Setup lifecycle status.

    Attributes:
        ACTIVE: Setup valid, awaiting trigger
        TRIGGERED: Entry triggered, trade opened
        EXPIRED: Setup expired (week ended without trigger)
        INVALIDATED: Conditions no longer valid
    """

    ACTIVE = "active"
    TRIGGERED = "triggered"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


# =============================================================================
# STOCK DOCUMENTS (Phase 1: Universe)
# Primary trading universe with quality scores and tier information
# =============================================================================


class StockDoc(BaseModel):
    """
    Stock master data document.

    Represents a single stock in the trading universe with quality scoring,
    fundamental qualification, and tier classification.

    Quality Scoring:
    ---------------
    - Tier A (90-100): MTF + Nifty 50 (highest liquidity)
    - Tier B (80-89): MTF + Nifty 100
    - Tier C (70-79): MTF + Nifty 200/500
    - Tier D (<70): MTF only or non-MTF

    Fundamental Qualification:
    -------------------------
    Stocks must pass both fundamental score (>60) AND institutional
    ownership filters to be marked as fundamentally_qualified.
    """

    symbol: str = Field(..., description="NSE symbol")
    name: str = Field(..., description="Company name")
    sector: str = Field(default="Unknown")
    industry: str = Field(default="Unknown")
    market_cap: float = Field(default=0.0, description="Market cap in crores")
    avg_daily_turnover: float = Field(
        default=0.0, description="30-day avg turnover in crores"
    )
    is_active: bool = Field(default=True)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    # Fundamental qualification (Phase 1 filter using cached data)
    fundamentally_qualified: bool = Field(
        default=False, description="Passes fundamental filter (from cached scores)"
    )
    fundamental_score: Optional[float] = Field(
        default=None, description="Cached fundamental score (0-100)"
    )
    fundamental_updated_at: Optional[datetime] = Field(
        default=None, description="When fundamental data was last refreshed"
    )

    class Config:
        use_enum_values = True


# =============================================================================
# REGIME DOCUMENTS
# Market regime assessment (Risk-On/Choppy/Risk-Off)
# The regime determines position sizing and trading aggressiveness
# =============================================================================


class RegimeIndicators(BaseModel):
    """
    Regime assessment indicator values.

    Four indicator categories with equal 25% weight each:
    1. Trend: Nifty vs 20/50/200 DMA
    2. Breadth: % of stocks above 200 DMA
    3. Volatility: India VIX level and trend
    4. Leadership: Cyclicals vs Defensives spread
    """

    nifty_vs_20dma: float = Field(default=0.0)
    nifty_vs_50dma: float = Field(default=0.0)
    nifty_vs_200dma: float = Field(default=0.0)
    breadth_above_200dma: float = Field(default=0.0, description="% stocks above 200 DMA")
    india_vix: float = Field(default=0.0)
    vix_trend: str = Field(default="neutral")
    cyclicals_vs_defensives: float = Field(default=0.0)


class RegimeAssessmentDoc(BaseModel):
    """Market regime assessment document."""

    state: RegimeState = Field(...)
    risk_on_prob: float = Field(..., ge=0.0, le=1.0)
    choppy_prob: float = Field(..., ge=0.0, le=1.0)
    risk_off_prob: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    indicators: RegimeIndicators = Field(default_factory=RegimeIndicators)
    position_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    notes: str = Field(default="")

    class Config:
        use_enum_values = True


# =============================================================================
# TRADE SETUP DOCUMENTS (Phase 4B)
# Detected trading opportunities from technical pattern analysis
# =============================================================================


class GapContingency(BaseModel):
    """
    Monday gap handling rules.

    Defines actions for different gap scenarios on Monday open:
    - gap_through_stop: Price opened below stop loss
    - small_gap_against: Small adverse gap but above stop
    - gap_above_entry: Large favorable gap above entry zone
    """

    gap_through_stop: str = Field(default="SKIP")
    small_gap_against: str = Field(default="ENTER_AT_OPEN")
    gap_above_entry: str = Field(default="SKIP")


class TradeSetupDoc(BaseModel):
    """Weekly trade setup document."""

    stock_symbol: str = Field(...)
    setup_type: SetupType = Field(...)
    status: SetupStatus = Field(default=SetupStatus.ACTIVE)

    # Entry zone
    entry_low: float = Field(...)
    entry_high: float = Field(...)

    # Risk management
    stop_loss: float = Field(...)
    stop_logic: str = Field(default="")
    target_1: float = Field(...)
    target_2: Optional[float] = Field(default=None)
    reward_risk_ratio: float = Field(...)

    # Analysis
    thesis: str = Field(default="")
    gap_contingency: GapContingency = Field(default_factory=GapContingency)
    invalidation_conditions: list[str] = Field(default_factory=list)

    # Scoring
    factor_score: float = Field(default=0.0)
    consistency_score: float = Field(default=0.0)
    composite_score: float = Field(default=0.0)

    # Metadata
    week_start: datetime = Field(...)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    regime_state: RegimeState = Field(default=RegimeState.RISK_ON)

    class Config:
        use_enum_values = True


# =============================================================================
# TRADE DOCUMENTS
# Executed trades with entry/exit details and P&L tracking
# =============================================================================


class TradeDoc(BaseModel):
    """
    Executed trade document.

    Tracks the full lifecycle of a trade from entry to exit,
    including P&L calculation and R-multiple performance.

    R-Multiple:
    ----------
    R = (Exit - Entry) / (Entry - Stop)
    Positive R = profit, Negative R = loss
    Target trades aim for 2R minimum.
    """

    stock_symbol: str = Field(...)
    setup_id: Optional[str] = Field(default=None, description="Reference to trade_setup")
    status: TradeStatus = Field(default=TradeStatus.PENDING)

    # Entry details
    entry_date: Optional[datetime] = Field(default=None)
    entry_price: float = Field(...)
    shares: int = Field(...)
    position_value: float = Field(default=0.0)
    risk_amount: float = Field(default=0.0)

    # Exit details
    exit_date: Optional[datetime] = Field(default=None)
    exit_price: Optional[float] = Field(default=None)
    exit_reason: str = Field(default="")

    # Risk management
    stop_loss: float = Field(...)
    target_1: float = Field(...)
    target_2: Optional[float] = Field(default=None)

    # Performance
    pnl: float = Field(default=0.0)
    pnl_percent: float = Field(default=0.0)
    r_multiple: float = Field(default=0.0)
    holding_days: int = Field(default=0)

    # Metadata
    notes: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# =============================================================================
# SYSTEM HEALTH DOCUMENTS
# Performance monitoring and trading system health metrics
# =============================================================================


class SystemHealthDoc(BaseModel):
    """
    System health metrics document.

    Tracks key performance indicators to monitor system health:
    - Win rates (12-week and 52-week rolling)
    - Expectancy in R-multiples
    - Drawdown levels
    - Execution quality (slippage, skipped trades)

    Health Score Thresholds:
    -----------------------
    - 70+: Continue normally
    - 50-70: Reduce position sizes
    - 30-50: Paper trade only
    - <30: Stop trading, review system
    """

    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Win rates
    win_rate_12w: float = Field(default=0.0, description="12-week rolling win rate")
    win_rate_52w: float = Field(default=0.0, description="52-week win rate")

    # Expectancy
    expectancy_12w: float = Field(default=0.0, description="12-week expectancy in R")
    avg_win_r: float = Field(default=0.0)
    avg_loss_r: float = Field(default=0.0)

    # Drawdown
    current_drawdown: float = Field(default=0.0)
    max_drawdown_52w: float = Field(default=0.0)

    # Execution quality
    avg_slippage: float = Field(default=0.0)
    trades_skipped_gap: int = Field(default=0)

    # Overall health
    health_score: float = Field(default=100.0, ge=0.0, le=100.0)
    recommended_action: Literal["CONTINUE", "REDUCE", "PAUSE", "STOP"] = Field(
        default="CONTINUE"
    )
    notes: str = Field(default="")

    class Config:
        use_enum_values = True


# =============================================================================
# FUNDAMENTAL DOCUMENTS (Monthly Refresh, Applied in Phase 1)
# Fundamental analysis scores and institutional ownership data
# =============================================================================


class FundamentalScoreDoc(BaseModel):
    """
    Fundamental analysis score document.

    Stores multi-dimensional fundamental scores calculated from:
    - Growth (30%): EPS Q/Q growth, Revenue Y/Y growth
    - Profitability (25%): ROCE, ROE
    - Leverage (20%): Debt/Equity (sector-adjusted)
    - Cash Flow (15%): FCF Yield
    - Earnings Quality (10%): Cash EPS vs Reported EPS

    Qualification:
    -------------
    A stock qualifies if it passes at least 3 of 5 filter criteria.
    Scores are refreshed monthly after quarterly results.
    """

    symbol: str = Field(...)

    # Growth metrics
    eps_qoq_growth: float = Field(default=0.0, description="EPS quarter-over-quarter growth %")
    revenue_yoy_growth: float = Field(default=0.0, description="Revenue year-over-year growth %")

    # Profitability metrics
    roce: float = Field(default=0.0, description="Return on Capital Employed %")
    roe: float = Field(default=0.0, description="Return on Equity %")

    # Leverage
    debt_equity: float = Field(default=0.0, description="Debt to Equity ratio")
    is_financial: bool = Field(default=False, description="Is financial sector stock")

    # Margins
    opm_margin: float = Field(default=0.0, description="Operating Profit Margin %")
    opm_trend: Literal["improving", "stable", "declining"] = Field(default="stable")

    # Cash flow
    fcf_yield: float = Field(default=0.0, description="Free Cash Flow Yield %")

    # Earnings quality
    cash_eps: float = Field(default=0.0)
    reported_eps: float = Field(default=0.0)
    earnings_quality_score: float = Field(default=0.0, ge=0.0, le=100.0)

    # Component scores (0-100)
    growth_score: float = Field(default=0.0, ge=0.0, le=100.0)
    profitability_score: float = Field(default=0.0, ge=0.0, le=100.0)
    leverage_score: float = Field(default=0.0, ge=0.0, le=100.0)
    cash_flow_score: float = Field(default=0.0, ge=0.0, le=100.0)

    # Final fundamental score
    fundamental_score: float = Field(default=0.0, ge=0.0, le=100.0)

    # Filter results
    passes_growth: bool = Field(default=False)
    passes_profitability: bool = Field(default=False)
    passes_leverage: bool = Field(default=False)
    passes_cash_flow: bool = Field(default=False)
    passes_quality: bool = Field(default=False)
    filters_passed: int = Field(default=0)
    qualifies: bool = Field(default=False)

    # Metadata
    calculated_at: datetime = Field(default_factory=datetime.utcnow)
    data_source: str = Field(default="FMP")

    class Config:
        use_enum_values = True


class InstitutionalHoldingDoc(BaseModel):
    """Institutional ownership document."""

    symbol: str = Field(...)

    # Ownership %
    fii_holding_pct: float = Field(default=0.0, description="FII holding %")
    dii_holding_pct: float = Field(default=0.0, description="DII holding %")
    total_institutional: float = Field(default=0.0, description="FII + DII %")

    # Net flows
    fii_net_30d: float = Field(default=0.0, description="FII net buying in 30 days (Cr)")
    fii_trend: Literal["buying", "neutral", "selling"] = Field(default="neutral")

    # Promoter
    promoter_holding_pct: float = Field(default=0.0)
    promoter_pledge_pct: float = Field(default=0.0)

    # Filter results
    passes_institutional_min: bool = Field(default=False)  # >= 35%
    passes_fii_trend: bool = Field(default=False)  # Not selling
    passes_pledge: bool = Field(default=False)  # <= 20%
    holding_score: float = Field(default=0.0, ge=0.0, le=100.0)
    qualifies: bool = Field(default=False)

    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# =============================================================================
# RISK MANAGEMENT DOCUMENTS (Phase 5: Risk Geometry)
# Stop-loss calculations and position sizing
# =============================================================================


class StopLossMethod(str, Enum):
    """
    Stop-loss calculation methods.

    The system uses the tighter of two methods:
    - STRUCTURE: Below recent swing low (99% of swing low)
    - VOLATILITY: Entry price minus 2x ATR(14)
    - TIME: Exit if no 2% move in 5 days (rare)

    Final stop = max(structure_stop, volatility_stop)
    Higher value = tighter stop = less risk per share.
    """

    STRUCTURE = "structure"  # Below swing low
    VOLATILITY = "volatility"  # Entry - 2 * ATR
    TIME = "time"  # 5 days without 2% move


class RiskGeometryDoc(BaseModel):
    """
    Risk geometry analysis document.

    Calculates the complete risk/reward profile for a trade setup:
    - Multi-method stop-loss (structure, volatility)
    - R:R ratio validation (min 2:1 for Risk-On, 2.5:1 for Choppy)
    - Trailing stop rules based on profit levels

    Trailing Stop Rules:
    -------------------
    - +3% profit: Move stop to breakeven
    - +6% profit: Trail at +2%
    - +10% profit: Trail below 20 DMA
    """

    symbol: str = Field(...)
    setup_id: Optional[str] = Field(default=None)

    # Entry
    entry_price: float = Field(...)
    entry_zone_low: float = Field(default=0.0)
    entry_zone_high: float = Field(default=0.0)

    # Multi-method stop-loss
    stop_structure: float = Field(default=0.0, description="Swing low stop")
    stop_volatility: float = Field(default=0.0, description="ATR-based stop")
    final_stop: float = Field(...)
    stop_method: StopLossMethod = Field(default=StopLossMethod.STRUCTURE)
    stop_distance_pct: float = Field(default=0.0)
    atr_14: float = Field(default=0.0)

    # Targets
    target_1: float = Field(...)  # 2R
    target_2: float = Field(default=0.0)  # 3R or resistance
    target_1_pct: float = Field(default=0.0)
    target_2_pct: float = Field(default=0.0)

    # R:R analysis
    risk_per_share: float = Field(default=0.0)
    rr_ratio_1: float = Field(default=0.0)
    rr_ratio_2: float = Field(default=0.0)

    # Trailing stop rules
    trailing_breakeven_at: float = Field(default=0.03)  # +3% -> breakeven
    trailing_plus2_at: float = Field(default=0.06)  # +6% -> +2%
    trail_to_20dma_at: float = Field(default=0.10)  # +10% -> trail 20DMA

    # Validation
    passes_rr_min: bool = Field(default=False)
    passes_stop_max: bool = Field(default=False)
    risk_qualifies: bool = Field(default=False)

    market_regime: str = Field(default="risk_on")
    calculated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class PositionSizeDoc(BaseModel):
    """
    Position sizing document.

    Calculates risk-adjusted position sizes using multiple factors:

    Position Size Formula:
    ---------------------
    Base Shares = (Portfolio × Risk%) / (Entry - Stop)

    Adjustments:
    - Volatility: Scale by Nifty_ATR / Stock_ATR
    - Kelly: Scale by min(1.0, Kelly_Fraction)
    - Regime: Scale by regime multiplier (1.0/0.7/0.5/0)

    Constraints:
    - Max 8% of portfolio in single position
    - Max 1.5% risk per trade
    """

    symbol: str = Field(...)
    setup_id: Optional[str] = Field(default=None)

    # Base calculation
    portfolio_value: float = Field(...)
    risk_pct: float = Field(default=0.015)  # 1.5%
    base_risk_amount: float = Field(default=0.0)

    # Risk per share
    entry_price: float = Field(...)
    stop_loss: float = Field(...)
    risk_per_share: float = Field(default=0.0)

    # Base size
    base_shares: int = Field(default=0)
    base_position_value: float = Field(default=0.0)

    # Volatility adjustment
    stock_atr: float = Field(default=0.0)
    nifty_atr: float = Field(default=0.0)
    vol_adjustment: float = Field(default=1.0)  # Nifty_ATR / Stock_ATR

    # Kelly criterion
    historical_win_rate: float = Field(default=0.50)
    historical_avg_win: float = Field(default=1.2)
    historical_avg_loss: float = Field(default=1.0)
    kelly_fraction: float = Field(default=1.0)
    kelly_adjusted: float = Field(default=1.0)  # min(1.0, Kelly)

    # Regime adjustment
    regime_state: str = Field(default="risk_on")
    regime_multiplier: float = Field(default=1.0)

    # Final size
    final_shares: int = Field(default=0)
    final_position_value: float = Field(default=0.0)
    final_risk_amount: float = Field(default=0.0)
    position_pct_of_portfolio: float = Field(default=0.0)

    # Constraints
    passes_max_position: bool = Field(default=True)  # <= 8% single
    sector: str = Field(default="Unknown")

    calculated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# =============================================================================
# PORTFOLIO DOCUMENTS (Phase 6: Portfolio Construction)
# Final portfolio composition with sector/correlation constraints
# =============================================================================


class PortfolioAllocationDoc(BaseModel):
    """
    Portfolio construction document.

    Builds the final portfolio applying multiple constraints:
    - Max 25% in any single sector
    - Max 70% correlation between positions
    - Max 12 positions (Risk-On), 5 (Choppy), 0 (Risk-Off)
    - Min 30% cash reserve

    The portfolio is built by ranking setups by quality score
    and adding positions until constraints are hit.
    """

    # Portfolio metadata
    allocation_date: datetime = Field(...)
    regime_state: str = Field(...)

    # Selected positions
    positions: list[dict] = Field(default_factory=list)
    position_count: int = Field(default=0)

    # Sector allocation
    sector_allocation: dict[str, float] = Field(default_factory=dict)
    max_sector_pct: float = Field(default=0.25)

    # Correlation
    max_correlation: float = Field(default=0.70)
    correlation_violations: int = Field(default=0)

    # Portfolio risk
    total_invested_pct: float = Field(default=0.0)
    total_risk_pct: float = Field(default=0.0)
    cash_reserve_pct: float = Field(default=0.30)

    # Constraints check
    passes_sector_limit: bool = Field(default=True)
    passes_correlation: bool = Field(default=True)
    passes_position_limit: bool = Field(default=True)
    passes_cash_reserve: bool = Field(default=True)

    # Status
    status: Literal["pending", "approved", "rejected"] = Field(default="pending")

    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# =============================================================================
# EXECUTION DOCUMENTS (Phase 7: Execution Display)
# Monday pre-market analysis and position tracking
# =============================================================================


class MondayPreMarketDoc(BaseModel):
    """
    Monday pre-market gap analysis document.

    Analyzes each setup based on Monday's expected open:
    - Gap through stop: SKIP (invalidated)
    - Small gap against: ENTER_AT_OPEN
    - Gap above entry zone: SKIP (don't chase)

    Generated on Monday before market open using SGX Nifty
    or expected opening prices.
    """

    analysis_date: datetime = Field(...)
    week_start: datetime = Field(...)

    # Market opens
    nifty_open: float = Field(default=0.0)
    nifty_prev_close: float = Field(default=0.0)
    nifty_gap_pct: float = Field(default=0.0)

    # Individual setup analysis
    setup_analyses: list[dict] = Field(default_factory=list)
    # Each: {symbol, friday_close, expected_open, gap_pct, gap_type, action, reason}

    # Summary actions
    total_setups: int = Field(default=0)
    enter_count: int = Field(default=0)
    skip_count: int = Field(default=0)
    wait_count: int = Field(default=0)

    # Sector momentum
    sector_momentum: dict = Field(default_factory=dict)

    analysis_time: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class PositionStatusDoc(BaseModel):
    """Intraday position status document."""

    symbol: str = Field(...)
    status_date: datetime = Field(default_factory=datetime.utcnow)

    # Entry details
    entry_price: float = Field(...)
    entry_date: datetime = Field(...)
    shares: int = Field(...)

    # Current state
    current_price: float = Field(default=0.0)
    current_pnl: float = Field(default=0.0)
    current_pnl_pct: float = Field(default=0.0)
    current_r_multiple: float = Field(default=0.0)

    # Risk levels
    stop_loss: float = Field(...)
    target_1: float = Field(...)
    target_2: Optional[float] = Field(default=None)
    trailing_stop: Optional[float] = Field(default=None)

    # Status flags
    hit_target_1: bool = Field(default=False)
    partial_exit_done: bool = Field(default=False)
    stop_trailing: bool = Field(default=False)

    # Alerts
    alerts: list[str] = Field(default_factory=list)

    # Sector context
    sector: str = Field(default="")
    sector_rs_today: float = Field(default=0.0)

    class Config:
        use_enum_values = True


class FridayCloseDoc(BaseModel):
    """Friday end-of-week summary document."""

    week_start: datetime = Field(...)
    summary_date: datetime = Field(...)

    # Week performance
    total_positions: int = Field(default=0)
    positions_closed: int = Field(default=0)
    positions_open: int = Field(default=0)

    # P&L summary
    realized_pnl: float = Field(default=0.0)
    unrealized_pnl: float = Field(default=0.0)
    total_pnl: float = Field(default=0.0)
    total_pnl_pct: float = Field(default=0.0)

    # R-Multiple summary
    total_r: float = Field(default=0.0)
    avg_r_per_trade: float = Field(default=0.0)
    wins: int = Field(default=0)
    losses: int = Field(default=0)
    win_rate: float = Field(default=0.0)

    # Position reviews
    open_positions: list[dict] = Field(default_factory=list)
    closed_positions: list[dict] = Field(default_factory=list)

    # Next week preparation
    carry_forward_setups: list[str] = Field(default_factory=list)
    new_watchlist: list[str] = Field(default_factory=list)
    regime_outlook: str = Field(default="")

    # System health
    system_health_score: float = Field(default=100.0)
    recommended_action: Literal["CONTINUE", "REDUCE", "PAUSE", "STOP"] = Field(
        default="CONTINUE"
    )

    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# =============================================================================
# RECOMMENDATION DOCUMENTS (Phase 8: Weekly Output)
# Final trade recommendations with action templates
# =============================================================================


class WeeklyRecommendationDoc(BaseModel):
    """
    Weekly trade recommendation document - the master output.

    This is the final output of the entire pipeline, containing:
    - Market regime context
    - Approved trade setups with full details
    - Position sizes and entry/exit rules
    - Gap contingency plans for Monday

    Lifecycle:
    ---------
    1. draft: Generated by pipeline
    2. approved: Reviewed and approved for execution
    3. executed: Trades placed
    4. expired: Week ended
    """

    week_start: datetime = Field(...)
    week_end: datetime = Field(...)
    generation_date: datetime = Field(default_factory=datetime.utcnow)

    # Market context
    market_regime: RegimeState = Field(...)
    regime_confidence: float = Field(ge=0.0, le=1.0)
    position_multiplier: float = Field(ge=0.0, le=1.0)
    nifty_close: float = Field(default=0.0)
    nifty_trend: str = Field(default="")  # "BULLISH", "BEARISH", "SIDEWAYS"
    india_vix: float = Field(default=0.0)

    # Recommendations
    total_setups: int = Field(default=0)
    approved_setups: int = Field(default=0)
    setups: list[dict] = Field(default_factory=list)  # Full setup details

    # Portfolio allocation
    total_capital: float = Field(default=1000000)
    allocated_capital: float = Field(default=0.0)
    cash_reserve_pct: float = Field(default=0.25)

    # Status
    status: Literal["draft", "approved", "executed", "expired"] = Field(default="draft")
    approved_at: Optional[datetime] = Field(default=None)
    approved_by: str = Field(default="")

    # Metadata
    notes: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True

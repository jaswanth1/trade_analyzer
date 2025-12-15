"""MongoDB document models using Pydantic."""

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RegimeState(str, Enum):
    """Market regime states."""

    RISK_ON = "risk_on"
    CHOPPY = "choppy"
    RISK_OFF = "risk_off"


class SetupType(str, Enum):
    """Technical setup types."""

    PULLBACK = "pullback"
    BREAKOUT = "breakout"
    RETEST = "retest"


class TradeStatus(str, Enum):
    """Trade lifecycle status."""

    PENDING = "pending"
    ACTIVE = "active"
    CLOSED_WIN = "closed_win"
    CLOSED_loss = "closed_loss"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class SetupStatus(str, Enum):
    """Setup status."""

    ACTIVE = "active"
    TRIGGERED = "triggered"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


# --- Stock Documents ---


class StockDoc(BaseModel):
    """Stock master data document."""

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

    class Config:
        use_enum_values = True


# --- Regime Documents ---


class RegimeIndicators(BaseModel):
    """Regime assessment indicator values."""

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


# --- Trade Setup Documents ---


class GapContingency(BaseModel):
    """Monday gap handling rules."""

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


# --- Trade Documents ---


class TradeDoc(BaseModel):
    """Executed trade document."""

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


# --- System Health Documents ---


class SystemHealthDoc(BaseModel):
    """System health metrics document."""

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

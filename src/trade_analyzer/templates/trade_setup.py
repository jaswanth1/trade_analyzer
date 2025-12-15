"""
Trade Setup Template generator for Phase 8 (Weekly Recommendations).

This module generates comprehensive trade recommendation cards that combine
all pipeline phase scores into actionable trade parameters. These cards
are the final output of the Trade Analyzer system.

Purpose:
--------
Transform raw position data from the pipeline into human-readable
recommendation cards with:
- Multi-phase conviction scores
- Technical levels (entry, stop, targets)
- Position sizing details
- Actionable step-by-step instructions
- Monday gap contingency plans

Conviction Score Calculation:
----------------------------
Final Conviction (0-10) = weighted average of phase scores:
- Momentum Score (25%): Price strength vs Nifty
- Consistency Score (20%): Weekly return consistency
- Liquidity Score (15%): Volume and turnover quality
- Fundamental Score (20%): Financial health metrics
- Setup Confidence (20%): Technical pattern quality

Labels:
- 8-10: Very High conviction
- 6.5-8: High conviction
- 5-6.5: Medium conviction
- 3.5-5: Low conviction
- 0-3.5: Very Low conviction

Usage:
------
    from trade_analyzer.templates.trade_setup import (
        generate_recommendation_card,
        generate_text_template,
    )

    # Generate a recommendation card
    position = {...}  # Position data from pipeline
    card = generate_recommendation_card(position, portfolio_value=1000000)

    # Generate text output
    text = generate_text_template(card)
    print(text)

Output Example:
--------------
    ================================================================================
                        TRADE RECOMMENDATION CARD
                        Week of December 16, 2024
    ================================================================================

    SYMBOL: RELIANCE
    Company: Reliance Industries Ltd
    Sector: Oil & Gas
    Setup Type: PULLBACK

    Final Conviction: 7.5/10 (High)
    ...

See Also:
---------
- trade_analyzer.activities.recommendation: Creates recommendation data
- trade_analyzer.workflows.weekly_recommendation: Orchestrates generation
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class TradeSetupTemplate:
    """
    Production trade setup template with all scores and parameters.

    This dataclass holds all the information needed for a complete
    trade recommendation card, including scores from all pipeline phases,
    technical levels, position sizing, and action steps.

    Attributes:
        symbol: NSE stock symbol
        company_name: Full company name
        sector: Industry sector
        week_display: Week date string for display

        momentum_score: Phase 2 momentum score (0-100)
        consistency_score: Phase 3 consistency score (0-100)
        liquidity_score: Phase 4A liquidity score (0-100)
        fundamental_score: Phase 1 fundamental score (0-100)
        setup_confidence: Phase 4B setup confidence (0-100)
        final_conviction: Combined conviction (0-10)
        conviction_label: Text label (Very High/High/Medium/Low)

        current_price: Latest closing price
        entry_low/high: Entry zone bounds
        stop_loss: Stop loss price
        target_1/2: Profit targets

        shares: Number of shares to buy
        investment_amount: Total investment value
        risk_amount: Capital at risk
        position_pct: Position as % of portfolio

        action_steps: List of actionable instructions
        gap_contingency: Monday gap handling rules
    """

    # Identification
    symbol: str
    company_name: str = ""
    sector: str = "Unknown"
    week_display: str = ""

    # Phase Scores (0-100)
    momentum_score: float = 0
    consistency_score: float = 0
    liquidity_score: float = 0
    fundamental_score: float = 0
    setup_confidence: float = 0

    # Final Conviction (0-10 scale)
    final_conviction: float = 0
    conviction_label: str = ""

    # Technical Data
    current_price: float = 0
    high_52w: float = 0
    low_52w: float = 0
    dma_20: float = 0
    dma_50: float = 0
    dma_200: float = 0
    from_52w_high_pct: float = 0

    # Setup Parameters
    setup_type: str = "pullback"
    entry_low: float = 0
    entry_high: float = 0
    stop_loss: float = 0
    stop_method: str = "structure"
    stop_distance_pct: float = 0
    target_1: float = 0
    target_2: float = 0
    rr_ratio_1: float = 0
    rr_ratio_2: float = 0

    # Position Sizing
    shares: int = 0
    investment_amount: float = 0
    risk_amount: float = 0
    position_pct: float = 0

    # Action Steps
    action_steps: list[str] = field(default_factory=list)

    # Gap Contingency
    gap_contingency: str = ""

    # Metadata
    generated_at: str = ""
    market_regime: str = "risk_on"
    regime_confidence: float = 0


def calculate_conviction(
    momentum: float,
    consistency: float,
    liquidity: float,
    fundamental: float,
    setup_confidence: float,
) -> tuple[float, str]:
    """
    Calculate final conviction score (0-10) from phase scores.

    Weights:
    - Momentum: 25%
    - Consistency: 20%
    - Liquidity: 15%
    - Fundamental: 20%
    - Setup Confidence: 20%

    Returns:
        Tuple of (conviction_score, label)
    """
    weighted = (
        momentum * 0.25
        + consistency * 0.20
        + liquidity * 0.15
        + fundamental * 0.20
        + setup_confidence * 0.20
    )

    # Convert to 0-10 scale
    conviction = weighted / 10

    # Generate label
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


def generate_action_steps(setup: TradeSetupTemplate) -> list[str]:
    """
    Generate actionable steps for a trade setup.

    Args:
        setup: TradeSetupTemplate instance

    Returns:
        List of action step strings.
    """
    steps = []

    # Entry steps
    steps.append(
        f"1. Place limit buy order at Rs.{setup.entry_low:.2f} - Rs.{setup.entry_high:.2f}"
    )

    # Stop loss
    steps.append(
        f"2. Set stop-loss at Rs.{setup.stop_loss:.2f} "
        f"({setup.stop_distance_pct:.1f}% below entry, {setup.stop_method} method)"
    )

    # Position size
    steps.append(
        f"3. Buy {setup.shares} shares (Rs.{setup.investment_amount:,.0f}, "
        f"{setup.position_pct:.1f}% of portfolio)"
    )

    # Targets
    steps.append(
        f"4. Target 1: Rs.{setup.target_1:.2f} ({setup.rr_ratio_1:.1f}R) - "
        f"Take 50% profit"
    )
    steps.append(
        f"5. Target 2: Rs.{setup.target_2:.2f} ({setup.rr_ratio_2:.1f}R) - "
        f"Exit remaining"
    )

    # Trailing stop
    steps.append(
        "6. At 1R profit (+3%), move stop to breakeven"
    )
    steps.append(
        "7. At 2R profit (+6%), trail stop to +2%"
    )

    # Gap contingency
    if setup.gap_contingency:
        steps.append(f"8. Gap Contingency: {setup.gap_contingency}")

    return steps


def generate_gap_contingency(
    entry_low: float,
    entry_high: float,
    stop_loss: float,
) -> str:
    """
    Generate gap contingency instructions.

    Args:
        entry_low: Lower entry zone
        entry_high: Upper entry zone
        stop_loss: Stop loss price

    Returns:
        Gap contingency string.
    """
    contingencies = []

    contingencies.append(
        f"If Monday open < Rs.{stop_loss:.2f} (stop): SKIP trade"
    )
    contingencies.append(
        f"If Monday open in Rs.{entry_low:.2f}-{entry_high:.2f}: ENTER at open"
    )
    contingencies.append(
        f"If Monday open > Rs.{entry_high * 1.02:.2f} (+2%): SKIP - don't chase"
    )
    contingencies.append(
        f"If Monday open < Rs.{entry_low:.2f} but > Rs.{stop_loss:.2f}: "
        f"ENTER at open (small gap against)"
    )

    return " | ".join(contingencies)


def generate_text_template(setup: TradeSetupTemplate) -> str:
    """
    Generate formatted text recommendation template.

    Args:
        setup: TradeSetupTemplate instance

    Returns:
        Formatted text string.
    """
    template = f"""
================================================================================
                    TRADE RECOMMENDATION CARD
                    Week of {setup.week_display}
================================================================================

SYMBOL: {setup.symbol}
Company: {setup.company_name}
Sector: {setup.sector}
Setup Type: {setup.setup_type.upper()}

--------------------------------------------------------------------------------
                         CONVICTION SCORES
--------------------------------------------------------------------------------
Final Conviction: {setup.final_conviction}/10 ({setup.conviction_label})

Phase Scores:
  - Momentum Score:    {setup.momentum_score:.0f}/100
  - Consistency Score: {setup.consistency_score:.0f}/100
  - Liquidity Score:   {setup.liquidity_score:.0f}/100
  - Fundamental Score: {setup.fundamental_score:.0f}/100
  - Setup Confidence:  {setup.setup_confidence:.0f}/100

Market Regime: {setup.market_regime.upper()} ({setup.regime_confidence:.0f}% confidence)

--------------------------------------------------------------------------------
                         TECHNICAL DATA
--------------------------------------------------------------------------------
Current Price:     Rs.{setup.current_price:,.2f}
52-Week High:      Rs.{setup.high_52w:,.2f} ({setup.from_52w_high_pct:.1f}% from high)
52-Week Low:       Rs.{setup.low_52w:,.2f}
20 DMA:            Rs.{setup.dma_20:,.2f}
50 DMA:            Rs.{setup.dma_50:,.2f}
200 DMA:           Rs.{setup.dma_200:,.2f}

--------------------------------------------------------------------------------
                         TRADE PARAMETERS
--------------------------------------------------------------------------------
Entry Zone:        Rs.{setup.entry_low:,.2f} - Rs.{setup.entry_high:,.2f}
Stop Loss:         Rs.{setup.stop_loss:,.2f} ({setup.stop_distance_pct:.1f}% risk)
Stop Method:       {setup.stop_method.upper()}

Target 1 (2R):     Rs.{setup.target_1:,.2f} (R:R {setup.rr_ratio_1:.1f})
Target 2 (3R):     Rs.{setup.target_2:,.2f} (R:R {setup.rr_ratio_2:.1f})

--------------------------------------------------------------------------------
                         POSITION SIZING
--------------------------------------------------------------------------------
Shares:            {setup.shares}
Investment:        Rs.{setup.investment_amount:,.2f}
Risk Amount:       Rs.{setup.risk_amount:,.2f}
Portfolio %:       {setup.position_pct:.1f}%

--------------------------------------------------------------------------------
                         ACTION STEPS
--------------------------------------------------------------------------------
"""
    for step in setup.action_steps:
        template += f"  {step}\n"

    template += f"""
--------------------------------------------------------------------------------
                         GAP CONTINGENCY (MONDAY)
--------------------------------------------------------------------------------
{setup.gap_contingency}

================================================================================
Generated: {setup.generated_at}
================================================================================
"""
    return template


def generate_recommendation_card(
    position: dict,
    portfolio_value: float = 1000000.0,
    market_regime: str = "risk_on",
    regime_confidence: float = 70.0,
) -> TradeSetupTemplate:
    """
    Generate a complete recommendation card from position data.

    Args:
        position: Position dict with all scores and parameters
        portfolio_value: Total portfolio value
        market_regime: Current market regime
        regime_confidence: Regime confidence percentage

    Returns:
        TradeSetupTemplate instance.
    """
    # Extract scores
    momentum = position.get("momentum_score", 0)
    consistency = position.get("consistency_score", 0)
    liquidity = position.get("liquidity_score", 0)
    fundamental = position.get("fundamental_score", 0)
    setup_conf = position.get("confidence", position.get("overall_quality", 0))

    # Calculate conviction
    conviction, label = calculate_conviction(
        momentum, consistency, liquidity, fundamental, setup_conf
    )

    # Extract prices
    entry_low = position.get("entry_low", position.get("entry_zone_low", 0))
    entry_high = position.get("entry_high", position.get("entry_zone_high", 0))
    stop_loss = position.get("stop", position.get("final_stop", 0))

    # Calculate from 52w high
    high_52w = position.get("high_52w", position.get("current_price", 0))
    current = position.get("current_price", position.get("entry_price", 0))
    from_high = ((high_52w - current) / high_52w * 100) if high_52w > 0 else 0

    # Generate week display
    today = datetime.utcnow()
    week_start = today - timedelta(days=today.weekday())
    week_display = week_start.strftime("%B %d, %Y")

    # Create template
    setup = TradeSetupTemplate(
        symbol=position.get("symbol", ""),
        company_name=position.get("company_name", position.get("symbol", "")),
        sector=position.get("sector", "Unknown"),
        week_display=week_display,
        momentum_score=momentum,
        consistency_score=consistency,
        liquidity_score=liquidity,
        fundamental_score=fundamental,
        setup_confidence=setup_conf,
        final_conviction=conviction,
        conviction_label=label,
        current_price=current,
        high_52w=high_52w,
        low_52w=position.get("low_52w", 0),
        dma_20=position.get("dma_20", position.get("sma_20", 0)),
        dma_50=position.get("dma_50", position.get("sma_50", 0)),
        dma_200=position.get("dma_200", position.get("sma_200", 0)),
        from_52w_high_pct=round(from_high, 1),
        setup_type=position.get("type", position.get("setup_type", "pullback")),
        entry_low=entry_low,
        entry_high=entry_high,
        stop_loss=stop_loss,
        stop_method=position.get("stop_method", "structure"),
        stop_distance_pct=position.get("stop_distance_pct", 0),
        target_1=position.get("target_1", 0),
        target_2=position.get("target_2", 0),
        rr_ratio_1=position.get("rr_ratio", position.get("rr_ratio_1", 2.0)),
        rr_ratio_2=position.get("rr_ratio_2", 3.0),
        shares=position.get("shares", position.get("final_shares", 0)),
        investment_amount=position.get("position_value", position.get("final_position_value", 0)),
        risk_amount=position.get("risk_amount", position.get("final_risk_amount", 0)),
        position_pct=position.get("position_pct", position.get("position_pct_of_portfolio", 0)),
        market_regime=market_regime,
        regime_confidence=regime_confidence,
        generated_at=datetime.utcnow().isoformat(),
    )

    # Generate gap contingency
    setup.gap_contingency = generate_gap_contingency(entry_low, entry_high, stop_loss)

    # Generate action steps
    setup.action_steps = generate_action_steps(setup)

    return setup


# Import timedelta for week display calculation
from datetime import timedelta

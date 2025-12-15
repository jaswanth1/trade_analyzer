"""Recommendation activities for Phase 9.

This module implements the final recommendation generation phase that packages
all analysis into user-friendly recommendation cards ready for review and execution.

Pipeline Position: Phase 9 (Final Output)
Input: 3-10 portfolio positions from Phase 7
Output: 3-7 weekly recommendation cards (typical)

The recommendation system:
- Aggregates ALL data from Phases 1-7
- Enriches with real-time context
- Generates formatted templates
- Saves with approval workflow

Recommendation Card Contents:

1. Stock Identification
    - Symbol, company name, sector
    - Week display (e.g., "Week of Dec 18, 2025")

2. Quality Scores (All Phases)
    - Momentum score (Phase 2)
    - Consistency score (Phase 3)
    - Liquidity score (Phase 4A)
    - Fundamental score (Phase 1/5)
    - Setup confidence (Phase 4B)
    - Final conviction (composite)

3. Technical Context
    - Current price
    - 52W high/low and % from high
    - 20/50/200 DMA levels
    - Recent price action

4. Trade Parameters
    - Setup type (A+/B+/C+/D)
    - Entry zone: low-high range
    - Stop loss: price and method
    - Stop distance: % from entry
    - Target 1: 2R level
    - Target 2: 3R+ level
    - R:R ratios

5. Position Sizing
    - Shares to buy
    - Investment amount (Rs)
    - Risk amount (Rs)
    - Position % of portfolio

6. Action Steps (3-5 bullet points)
    - When to enter
    - Where to set stop
    - When to take profits
    - Trailing stop guidance

7. Gap Contingency Plan
    - If gaps up >2%: Action
    - If gaps down >2%: Action
    - If in entry zone: Action

Workflow States:
    1. draft: Initial generation (requires approval)
    2. approved: User has approved (ready for execution)
    3. expired: Week ended (archived)

Expiration Logic:
    - Recommendations expire after 1 week
    - Prevents stale recommendations
    - Auto-cleanup on next run

Output Format:
    - Structured dict (for UI display)
    - Text template (for sharing/printing)
    - Saved to weekly_recommendations collection

Typical Use:
    1. System generates recommendations Saturday/Sunday
    2. User reviews and approves
    3. Monday pre-market: Gap analysis
    4. Execute approved setups
    5. Friday: Week summary
    6. Next week: New recommendations

Expected Output: 3-7 recommendation cards per week
"""

from datetime import datetime, timedelta

from temporalio import activity

from trade_analyzer.config import DEFAULT_PORTFOLIO_VALUE
from trade_analyzer.db.connection import get_database


@activity.defn
async def aggregate_phase_results() -> dict:
    """
    Aggregate results from Phases 1-7.

    Returns:
        Dict with aggregated data from all phases.
    """
    db = get_database()

    # Get latest regime assessment
    regime_doc = db["regime_assessments"].find_one(sort=[("timestamp", -1)])
    regime = {
        "state": regime_doc.get("state", "risk_on") if regime_doc else "risk_on",
        "confidence": regime_doc.get("confidence", 70) if regime_doc else 70,
        "risk_on_prob": regime_doc.get("risk_on_prob", 0.7) if regime_doc else 0.7,
    }

    # Get latest portfolio allocation
    portfolio_doc = db["portfolio_allocations"].find_one(sort=[("allocation_date", -1)])
    if not portfolio_doc:
        activity.logger.warning("No portfolio allocation found")
        return {
            "regime": regime,
            "portfolio": None,
            "positions": [],
            "stats": {},
        }

    positions = portfolio_doc.get("positions", [])

    # Enrich positions with additional data
    enriched_positions = []
    for pos in positions:
        symbol = pos.get("symbol")

        # Get stock info
        stock_doc = db["stocks"].find_one({"symbol": symbol})
        if stock_doc:
            pos["company_name"] = stock_doc.get("company_name", symbol)
            pos["sector"] = stock_doc.get("sector", "Unknown")
            pos["high_52w"] = stock_doc.get("high_52w", 0)
            pos["low_52w"] = stock_doc.get("low_52w", 0)

        # Get factor scores
        factor_doc = db["factor_scores"].find_one(
            {"symbol": symbol},
            sort=[("calculated_at", -1)]
        )
        if factor_doc:
            pos["momentum_score"] = factor_doc.get("momentum_score", 0)
            pos["consistency_score"] = factor_doc.get("consistency_score", 0)
            pos["liquidity_score"] = factor_doc.get("liquidity_score", 0)

        # Get fundamental score
        fund_doc = db["fundamental_scores"].find_one(
            {"symbol": symbol},
            sort=[("calculated_at", -1)]
        )
        if fund_doc:
            pos["fundamental_score"] = fund_doc.get("fundamental_score", 0)
            pos["roce"] = fund_doc.get("roce", 0)
            pos["roe"] = fund_doc.get("roe", 0)

        # Get technical indicators
        tech_doc = db["technical_indicators"].find_one(
            {"symbol": symbol},
            sort=[("calculated_at", -1)]
        )
        if tech_doc:
            pos["dma_20"] = tech_doc.get("sma_20", 0)
            pos["dma_50"] = tech_doc.get("sma_50", 0)
            pos["dma_200"] = tech_doc.get("sma_200", 0)

        enriched_positions.append(pos)

    # Calculate stats
    stats = {
        "total_positions": len(enriched_positions),
        "total_invested": sum(p.get("position_value", 0) for p in enriched_positions),
        "total_risk": sum(p.get("risk_amount", 0) for p in enriched_positions),
        "avg_rr_ratio": (
            sum(p.get("rr_ratio", 0) for p in enriched_positions) / len(enriched_positions)
            if enriched_positions else 0
        ),
        "sector_breakdown": portfolio_doc.get("sector_allocation", {}),
    }

    activity.logger.info(
        f"Aggregated {len(enriched_positions)} positions from Phase 7"
    )

    return {
        "regime": regime,
        "portfolio": {
            "allocation_date": portfolio_doc.get("allocation_date"),
            "total_invested_pct": portfolio_doc.get("total_invested_pct", 0),
            "total_risk_pct": portfolio_doc.get("total_risk_pct", 0),
            "cash_reserve_pct": portfolio_doc.get("cash_reserve_pct", 0),
        },
        "positions": enriched_positions,
        "stats": stats,
    }


@activity.defn
async def generate_recommendation_templates(
    positions: list[dict],
    market_regime: str = "risk_on",
    regime_confidence: float = 70.0,
    portfolio_value: float = DEFAULT_PORTFOLIO_VALUE,
) -> list[dict]:
    """
    Generate recommendation templates for all positions.

    Args:
        positions: List of enriched position dicts
        market_regime: Current market regime
        regime_confidence: Regime confidence percentage
        portfolio_value: Total portfolio value

    Returns:
        List of recommendation template dicts.
    """
    from trade_analyzer.templates.trade_setup import (
        generate_recommendation_card,
        generate_text_template,
    )

    templates = []

    for pos in positions:
        try:
            # Generate template
            card = generate_recommendation_card(
                pos,
                portfolio_value=portfolio_value,
                market_regime=market_regime,
                regime_confidence=regime_confidence,
            )

            # Generate text version
            text = generate_text_template(card)

            # Convert to dict for storage
            template_dict = {
                "symbol": card.symbol,
                "company_name": card.company_name,
                "sector": card.sector,
                "week_display": card.week_display,
                "final_conviction": card.final_conviction,
                "conviction_label": card.conviction_label,
                "scores": {
                    "momentum": card.momentum_score,
                    "consistency": card.consistency_score,
                    "liquidity": card.liquidity_score,
                    "fundamental": card.fundamental_score,
                    "setup_confidence": card.setup_confidence,
                },
                "technical": {
                    "current_price": card.current_price,
                    "high_52w": card.high_52w,
                    "low_52w": card.low_52w,
                    "dma_20": card.dma_20,
                    "dma_50": card.dma_50,
                    "dma_200": card.dma_200,
                    "from_52w_high_pct": card.from_52w_high_pct,
                },
                "trade_params": {
                    "setup_type": card.setup_type,
                    "entry_low": card.entry_low,
                    "entry_high": card.entry_high,
                    "stop_loss": card.stop_loss,
                    "stop_method": card.stop_method,
                    "stop_distance_pct": card.stop_distance_pct,
                    "target_1": card.target_1,
                    "target_2": card.target_2,
                    "rr_ratio_1": card.rr_ratio_1,
                    "rr_ratio_2": card.rr_ratio_2,
                },
                "position_sizing": {
                    "shares": card.shares,
                    "investment_amount": card.investment_amount,
                    "risk_amount": card.risk_amount,
                    "position_pct": card.position_pct,
                },
                "action_steps": card.action_steps,
                "gap_contingency": card.gap_contingency,
                "text_template": text,
                "generated_at": card.generated_at,
            }

            templates.append(template_dict)

        except Exception as e:
            activity.logger.warning(
                f"Error generating template for {pos.get('symbol')}: {e}"
            )

    activity.logger.info(f"Generated {len(templates)} recommendation templates")
    return templates


@activity.defn
async def save_weekly_recommendation(
    recommendations: list[dict],
    regime: dict,
    stats: dict,
    portfolio_value: float = DEFAULT_PORTFOLIO_VALUE,
) -> dict:
    """
    Save weekly recommendation to MongoDB.

    Args:
        recommendations: List of recommendation templates
        regime: Regime assessment dict
        stats: Aggregated stats dict
        portfolio_value: Total portfolio value

    Returns:
        Stats dict.
    """
    db = get_database()
    collection = db["weekly_recommendations"]

    # Calculate week boundaries
    today = datetime.utcnow()
    days_since_monday = today.weekday()
    week_start = today - timedelta(days=days_since_monday)
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)

    # Calculate totals
    total_investment = sum(r["position_sizing"]["investment_amount"] for r in recommendations)
    total_risk = sum(r["position_sizing"]["risk_amount"] for r in recommendations)

    # Position multiplier based on regime
    if regime["state"] == "risk_on":
        position_mult = 1.0
    elif regime["state"] == "choppy":
        position_mult = 0.5
    else:
        position_mult = 0.0

    recommendation_doc = {
        "week_start": week_start,
        "week_end": week_end,
        "market_regime": regime["state"],
        "regime_confidence": regime["confidence"],
        "risk_on_prob": regime.get("risk_on_prob", 0),
        "position_multiplier": position_mult,
        "total_setups": len(recommendations),
        "approved_setups": len(recommendations),  # All are approved from portfolio
        "setups": recommendations,
        "total_capital": portfolio_value,
        "allocated_capital": total_investment,
        "allocated_pct": round((total_investment / portfolio_value) * 100, 2),
        "total_risk": total_risk,
        "total_risk_pct": round((total_risk / portfolio_value) * 100, 2),
        "stats": stats,
        "status": "draft",  # Requires user approval
        "created_at": datetime.utcnow(),
    }

    # Check for existing recommendation for this week
    existing = collection.find_one({
        "week_start": week_start,
        "status": {"$ne": "expired"}
    })

    if existing:
        # Update existing
        collection.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                **recommendation_doc,
                "updated_at": datetime.utcnow(),
            }}
        )
        activity.logger.info(f"Updated existing recommendation for week of {week_start}")
    else:
        # Insert new
        collection.insert_one(recommendation_doc)
        activity.logger.info(f"Created new recommendation for week of {week_start}")

    # Create indexes
    collection.create_index([("week_start", -1)])
    collection.create_index("status")
    collection.create_index([("market_regime", 1), ("week_start", -1)])

    activity.logger.info(
        f"Saved weekly recommendation: {len(recommendations)} setups, "
        f"Rs.{total_investment:,.0f} allocated ({total_investment/portfolio_value*100:.1f}%)"
    )

    return {
        "saved": True,
        "week_start": week_start.isoformat(),
        "total_setups": len(recommendations),
        "allocated_capital": total_investment,
        "allocated_pct": round((total_investment / portfolio_value) * 100, 2),
        "total_risk_pct": round((total_risk / portfolio_value) * 100, 2),
    }


@activity.defn
async def get_latest_weekly_recommendation() -> dict | None:
    """
    Get the most recent weekly recommendation.

    Returns:
        Weekly recommendation dict or None.
    """
    db = get_database()
    collection = db["weekly_recommendations"]

    recommendation = collection.find_one(
        {"status": {"$ne": "expired"}},
        sort=[("week_start", -1)]
    )

    if recommendation:
        recommendation["_id"] = str(recommendation["_id"])
        activity.logger.info(
            f"Found latest recommendation: {recommendation['total_setups']} setups, "
            f"status: {recommendation['status']}"
        )
    else:
        activity.logger.info("No weekly recommendation found")

    return recommendation


@activity.defn
async def approve_weekly_recommendation(week_start: datetime) -> dict:
    """
    Approve a weekly recommendation for execution.

    Args:
        week_start: Start of the week

    Returns:
        Updated recommendation summary.
    """
    db = get_database()
    collection = db["weekly_recommendations"]

    result = collection.update_one(
        {"week_start": week_start, "status": "draft"},
        {"$set": {
            "status": "approved",
            "approved_at": datetime.utcnow(),
        }}
    )

    if result.modified_count == 0:
        activity.logger.warning(f"No draft recommendation found for {week_start}")
        return {"approved": False, "error": "No draft recommendation found"}

    activity.logger.info(f"Approved recommendation for week of {week_start}")
    return {"approved": True, "week_start": week_start.isoformat()}


@activity.defn
async def expire_old_recommendations() -> dict:
    """
    Expire recommendations older than 1 week.

    Returns:
        Count of expired recommendations.
    """
    db = get_database()
    collection = db["weekly_recommendations"]

    one_week_ago = datetime.utcnow() - timedelta(weeks=1)

    result = collection.update_many(
        {
            "week_start": {"$lt": one_week_ago},
            "status": {"$in": ["draft", "approved"]}
        },
        {"$set": {"status": "expired", "expired_at": datetime.utcnow()}}
    )

    activity.logger.info(f"Expired {result.modified_count} old recommendations")
    return {"expired_count": result.modified_count}

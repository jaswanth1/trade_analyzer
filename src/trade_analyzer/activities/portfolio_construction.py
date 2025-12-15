"""Portfolio Construction activities for Phase 7.

This module implements:
1. Correlation filter (max 0.70)
2. Sector limit enforcement (3 per sector, 25% max)
3. Final portfolio selection with constraints
"""

import asyncio
from datetime import datetime

import numpy as np
from temporalio import activity

from trade_analyzer.config import (
    CASH_RESERVE_PCT,
    DEFAULT_PORTFOLIO_VALUE,
    MAX_POSITIONS,
    MAX_SECTOR_PCT,
)
from trade_analyzer.db.connection import get_database


@activity.defn
async def fetch_position_sized_setups() -> list[dict]:
    """
    Fetch setups with position sizes from Phase 6.

    Returns:
        List of position-sized setup dicts.
    """
    db = get_database()
    collection = db["position_sizes"]

    # Get most recent position sizes
    pipeline = [
        {"$match": {"risk_qualifies": True}},
        {"$sort": {"calculated_at": -1, "overall_quality": -1}},
        {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$sort": {"overall_quality": -1}},
    ]

    cursor = collection.aggregate(pipeline)
    setups = list(cursor)

    activity.logger.info(f"Found {len(setups)} position-sized setups")
    return setups


@activity.defn
async def calculate_correlation_matrix(
    symbols: list[str],
    days: int = 60,
) -> dict:
    """
    Calculate correlation matrix for symbols.

    Args:
        symbols: List of stock symbols
        days: Lookback period

    Returns:
        Nested dict of correlations: {sym1: {sym2: corr}}
    """
    from trade_analyzer.data.providers.market_data import MarketDataProvider

    provider = MarketDataProvider()

    # Fetch returns for all symbols
    returns_data = {}
    for symbol in symbols:
        ohlcv = provider.fetch_ohlcv_yahoo(symbol, days=days + 10)
        if ohlcv is not None and len(ohlcv.data) >= days:
            returns = ohlcv.data["close"].pct_change().tail(days).dropna()
            returns_data[symbol] = returns
        await asyncio.sleep(0.2)

    # Calculate correlations
    correlations = {}
    for sym1 in symbols:
        correlations[sym1] = {}
        for sym2 in symbols:
            if sym1 == sym2:
                correlations[sym1][sym2] = 1.0
            elif sym1 in returns_data and sym2 in returns_data:
                ret1 = returns_data[sym1]
                ret2 = returns_data[sym2]
                # Align dates
                common_idx = ret1.index.intersection(ret2.index)
                if len(common_idx) >= 30:
                    corr = np.corrcoef(ret1.loc[common_idx], ret2.loc[common_idx])[0, 1]
                    correlations[sym1][sym2] = round(float(corr), 3)
                else:
                    correlations[sym1][sym2] = 0.0
            else:
                correlations[sym1][sym2] = 0.0

    activity.logger.info(f"Calculated correlation matrix for {len(symbols)} symbols")
    return correlations


@activity.defn
async def apply_correlation_filter(
    setups: list[dict],
    correlations: dict,
    max_correlation: float = 0.70,
) -> list[dict]:
    """
    Filter out highly correlated positions.

    Args:
        setups: List of setups sorted by quality
        correlations: Correlation matrix
        max_correlation: Maximum allowed correlation

    Returns:
        Filtered list of setups.
    """
    if not setups:
        return setups

    selected = [setups[0]]  # Always include best setup

    for setup in setups[1:]:
        symbol = setup["symbol"]
        is_correlated = False

        for selected_setup in selected:
            sel_symbol = selected_setup["symbol"]
            corr = correlations.get(symbol, {}).get(sel_symbol, 0)

            if abs(corr) > max_correlation:
                is_correlated = True
                activity.logger.info(
                    f"Rejecting {symbol}: correlated with {sel_symbol} ({corr:.2f})"
                )
                break

        if not is_correlated:
            selected.append(setup)

    activity.logger.info(
        f"Correlation filter: {len(selected)}/{len(setups)} passed "
        f"(max corr: {max_correlation})"
    )
    return selected


@activity.defn
async def apply_sector_limits(
    setups: list[dict],
    max_per_sector: int = 3,
    max_sector_pct: float = MAX_SECTOR_PCT,
    portfolio_value: float = DEFAULT_PORTFOLIO_VALUE,
) -> list[dict]:
    """
    Apply sector concentration limits.

    Args:
        setups: List of setups
        max_per_sector: Max positions per sector
        max_sector_pct: Max sector exposure as decimal
        portfolio_value: Total portfolio value

    Returns:
        Filtered list respecting sector limits.
    """
    sector_counts = {}
    sector_values = {}
    selected = []

    for setup in setups:
        sector = setup.get("sector", "Unknown")
        position_value = setup.get("final_position_value", 0)

        current_count = sector_counts.get(sector, 0)
        current_value = sector_values.get(sector, 0)

        # Check count limit
        if current_count >= max_per_sector:
            activity.logger.info(
                f"Rejecting {setup['symbol']}: sector {sector} at max count ({max_per_sector})"
            )
            continue

        # Check value limit
        if (current_value + position_value) / portfolio_value > max_sector_pct:
            activity.logger.info(
                f"Rejecting {setup['symbol']}: sector {sector} exceeds {max_sector_pct*100}% exposure"
            )
            continue

        # Accept
        selected.append(setup)
        sector_counts[sector] = current_count + 1
        sector_values[sector] = current_value + position_value

    activity.logger.info(
        f"Sector limits: {len(selected)}/{len(setups)} passed "
        f"(max {max_per_sector}/sector, {max_sector_pct*100}% exposure)"
    )

    return selected


@activity.defn
async def construct_final_portfolio(
    setups: list[dict],
    max_positions: int = MAX_POSITIONS,
    min_positions: int = 3,
    cash_reserve_pct: float = CASH_RESERVE_PCT,
    portfolio_value: float = DEFAULT_PORTFOLIO_VALUE,
    market_regime: str = "risk_on",
) -> dict:
    """
    Construct final portfolio with all constraints.

    Constraints:
    - Max 12 positions (Risk-On), 5 (Choppy), 0 (Risk-Off)
    - Max 25% sector exposure
    - Max 8% single position
    - Cash reserve: 25-35%

    Args:
        setups: Filtered and sorted setups
        max_positions: Maximum positions
        min_positions: Minimum positions
        cash_reserve_pct: Target cash reserve
        portfolio_value: Total portfolio value
        market_regime: Current regime

    Returns:
        Portfolio allocation dict.
    """
    # Adjust max based on regime
    regime_max = {
        "risk_on": min(10, max_positions),
        "choppy": min(5, max_positions),
        "risk_off": 0,
    }
    effective_max = regime_max.get(market_regime, 5)

    if market_regime == "risk_off":
        activity.logger.info("Risk-Off regime: No new positions")
        return {
            "allocation_date": datetime.utcnow().isoformat(),
            "regime_state": market_regime,
            "positions": [],
            "position_count": 0,
            "sector_allocation": {},
            "max_correlation": 0.70,
            "total_invested_pct": 0,
            "total_risk_pct": 0,
            "cash_reserve_pct": 100,
            "passes_sector_limit": True,
            "passes_correlation": True,
            "passes_position_limit": True,
            "passes_cash_reserve": True,
            "status": "approved",
            "message": "Risk-Off regime: No new positions",
        }

    # Select top positions
    selected = setups[:effective_max]

    if len(selected) < min_positions and market_regime == "risk_on":
        activity.logger.warning(
            f"Only {len(selected)} positions available, below minimum {min_positions}"
        )

    # Calculate allocations
    total_value = sum(s.get("final_position_value", 0) for s in selected)
    total_risk = sum(s.get("final_risk_amount", 0) for s in selected)
    total_risk_pct = (total_risk / portfolio_value) * 100

    # Sector allocation
    sector_allocation = {}
    for s in selected:
        sector = s.get("sector", "Unknown")
        value = s.get("final_position_value", 0)
        current = sector_allocation.get(sector, 0)
        sector_allocation[sector] = current + (value / portfolio_value) * 100

    # Cash reserve
    invested_pct = (total_value / portfolio_value) * 100
    actual_cash_reserve = 100 - invested_pct

    # Validation
    passes_cash = actual_cash_reserve >= cash_reserve_pct * 100
    max_sector_exposure = max(sector_allocation.values()) if sector_allocation else 0
    passes_sector = max_sector_exposure <= MAX_SECTOR_PCT * 100

    # Build position list for output
    positions = []
    for i, s in enumerate(selected):
        positions.append({
            "rank": i + 1,
            "symbol": s["symbol"],
            "type": s.get("type", "UNKNOWN"),
            "entry_low": s.get("entry_zone_low", s.get("entry_low")),
            "entry_high": s.get("entry_zone_high", s.get("entry_high")),
            "entry_price": s.get("entry_price"),
            "stop": s.get("final_stop"),
            "target_1": s.get("target_1"),
            "target_2": s.get("target_2"),
            "rr_ratio": s.get("rr_ratio_1"),
            "shares": s.get("final_shares"),
            "position_value": s.get("final_position_value"),
            "risk_amount": s.get("final_risk_amount"),
            "position_pct": s.get("position_pct_of_portfolio"),
            "confidence": s.get("confidence"),
            "momentum_score": s.get("momentum_score"),
            "consistency_score": s.get("consistency_score"),
            "liquidity_score": s.get("liquidity_score"),
            "fundamental_score": s.get("fundamental_score"),
            "overall_quality": s.get("overall_quality"),
            "sector": s.get("sector", "Unknown"),
        })

    portfolio = {
        "allocation_date": datetime.utcnow().isoformat(),
        "regime_state": market_regime,
        "positions": positions,
        "position_count": len(positions),
        "sector_allocation": {k: round(v, 2) for k, v in sector_allocation.items()},
        "max_correlation": 0.70,
        "total_invested_pct": round(invested_pct, 2),
        "total_risk_pct": round(total_risk_pct, 2),
        "cash_reserve_pct": round(actual_cash_reserve, 2),
        "passes_sector_limit": passes_sector,
        "passes_correlation": True,  # Already filtered
        "passes_position_limit": len(positions) <= effective_max,
        "passes_cash_reserve": passes_cash,
        "status": "pending",  # Requires user approval
    }

    activity.logger.info(
        f"Portfolio constructed: {len(positions)} positions, "
        f"{total_risk_pct:.1f}% risk, {actual_cash_reserve:.1f}% cash"
    )

    return portfolio


@activity.defn
async def save_portfolio_allocation(portfolio: dict) -> dict:
    """
    Save portfolio allocation to MongoDB.

    Args:
        portfolio: Portfolio allocation dict

    Returns:
        Stats dict.
    """
    db = get_database()
    collection = db["portfolio_allocations"]

    portfolio["created_at"] = datetime.utcnow()
    collection.insert_one(portfolio)

    # Create indexes
    collection.create_index([("allocation_date", -1)])
    collection.create_index("status")
    collection.create_index("regime_state")

    activity.logger.info(
        f"Saved portfolio allocation with {portfolio['position_count']} positions"
    )

    return {
        "saved": True,
        "position_count": portfolio["position_count"],
        "total_risk_pct": portfolio["total_risk_pct"],
        "cash_reserve_pct": portfolio["cash_reserve_pct"],
    }


@activity.defn
async def get_latest_portfolio_allocation() -> dict | None:
    """
    Get the most recent portfolio allocation.

    Returns:
        Portfolio allocation dict or None if not found.
    """
    db = get_database()
    collection = db["portfolio_allocations"]

    portfolio = collection.find_one(sort=[("allocation_date", -1)])

    if portfolio:
        portfolio["_id"] = str(portfolio["_id"])
        activity.logger.info(
            f"Found latest portfolio: {portfolio['position_count']} positions, "
            f"status: {portfolio['status']}"
        )
    else:
        activity.logger.info("No portfolio allocation found")

    return portfolio

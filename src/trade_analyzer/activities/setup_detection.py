"""Technical Setup Detection activities for Phase 4B.

This module implements:
1. Type A+: Enhanced Trend Pullback (Smart Support Detection)
2. Type B+: Volatility Contraction Pattern (VCP) Breakout
3. Type C+: Confirmed Breakout Retest (Role Reversal)
4. Type D: Gap-Fill Continuation

Detects 8-15 high-conviction trade setups from liquidity-qualified stocks.
"""

import asyncio
from datetime import datetime

from temporalio import activity

from trade_analyzer.data.providers.market_data import MarketDataProvider
from trade_analyzer.db.connection import get_database


@activity.defn
async def fetch_liquidity_qualified_symbols() -> list[str]:
    """
    Fetch symbols that passed liquidity filter (Phase 4A).

    Returns:
        List of symbol strings that qualified from liquidity analysis.
    """
    db = get_database()
    collection = db["liquidity_scores"]

    # Find stocks that qualified in most recent run
    pipeline = [
        {"$match": {"liq_qualifies": True}},
        {"$sort": {"calculated_at": -1, "liquidity_score": -1}},
        {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$project": {"symbol": 1}},
    ]

    cursor = collection.aggregate(pipeline)
    symbols = [doc["symbol"] async for doc in cursor]

    activity.logger.info(f"Found {len(symbols)} liquidity-qualified symbols")
    return symbols


@activity.defn
async def detect_setups_batch(
    symbols: list[str],
    fetch_delay: float = 0.3,
) -> list[dict]:
    """
    Detect technical setups for a batch of symbols.

    Args:
        symbols: List of stock symbols
        fetch_delay: Delay between API calls (rate limiting)

    Returns:
        List of detected setups with entry/stop/target levels.
    """
    provider = MarketDataProvider()
    all_setups = []

    for i, symbol in enumerate(symbols):
        try:
            # Fetch 400 days of daily data for 200-DMA calculation
            ohlcv = provider.fetch_ohlcv_yahoo(symbol, days=400)

            if ohlcv is None or ohlcv.data.empty or len(ohlcv.data) < 200:
                activity.logger.warning(f"Insufficient data for {symbol}")
                continue

            df = ohlcv.data

            # Detect all setup types
            setups = provider.detect_all_setups(df)

            for setup in setups:
                setup["symbol"] = symbol
                setup["close"] = df["close"].iloc[-1]
                setup["detected_at"] = datetime.utcnow().isoformat()
                all_setups.append(setup)

            if (i + 1) % 10 == 0:
                activity.logger.info(f"Processed {i + 1}/{len(symbols)} symbols, found {len(all_setups)} setups")

        except Exception as e:
            activity.logger.warning(f"Error processing {symbol}: {e}")

        # Rate limiting
        if fetch_delay > 0:
            await asyncio.sleep(fetch_delay)

    activity.logger.info(f"Detected {len(all_setups)} total setups from {len(symbols)} symbols")
    return all_setups


@activity.defn
async def filter_and_rank_setups(
    setups: list[dict],
    min_rr_ratio: float = 2.0,
    min_confidence: int = 70,
    max_stop_pct: float = 7.0,
) -> list[dict]:
    """
    Filter and rank setups by quality criteria.

    Args:
        setups: List of detected setups
        min_rr_ratio: Minimum reward:risk ratio
        min_confidence: Minimum confidence score (0-100)
        max_stop_pct: Maximum stop distance as percentage

    Returns:
        Filtered and ranked list of high-quality setups.
    """
    filtered = []

    for setup in setups:
        # Calculate stop distance percentage
        entry_mid = (setup.get("entry_low", 0) + setup.get("entry_high", 0)) / 2
        stop = setup.get("stop", 0)
        stop_pct = ((entry_mid - stop) / entry_mid * 100) if entry_mid > 0 else 99

        # Apply filters
        passes_rr = setup.get("rr_ratio", 0) >= min_rr_ratio
        passes_confidence = setup.get("confidence", 0) >= min_confidence
        passes_stop = stop_pct <= max_stop_pct

        # All filters must pass
        if passes_rr and passes_confidence and passes_stop:
            setup["stop_distance_pct"] = round(stop_pct, 2)
            setup["passes_rr"] = passes_rr
            setup["passes_confidence"] = passes_confidence
            setup["passes_stop"] = passes_stop
            setup["qualifies"] = True
            filtered.append(setup)

    # Rank by: confidence (40%) + R:R (30%) + conditions_met (30%)
    def setup_score(s):
        conf_score = s.get("confidence", 0) / 100
        rr_score = min(s.get("rr_ratio", 0) / 3, 1)  # Cap at 3R
        cond_score = s.get("conditions_met", 0) / 5
        return 0.4 * conf_score + 0.3 * rr_score + 0.3 * cond_score

    filtered.sort(key=setup_score, reverse=True)

    # Add rank
    for i, setup in enumerate(filtered):
        setup["rank"] = i + 1
        setup["composite_score"] = round(setup_score(setup) * 100, 1)

    activity.logger.info(
        f"Setup filter: {len(filtered)}/{len(setups)} passed "
        f"(min_rr={min_rr_ratio}, min_conf={min_confidence}, max_stop={max_stop_pct}%)"
    )

    return filtered


@activity.defn
async def enrich_setups_with_context(setups: list[dict]) -> list[dict]:
    """
    Enrich setups with additional context from database.

    Adds:
    - Momentum score from Phase 2
    - Consistency score from Phase 3
    - Liquidity score from Phase 4A

    Args:
        setups: List of setups to enrich

    Returns:
        Enriched setups with scores from previous phases.
    """
    if not setups:
        return setups

    db = get_database()

    # Get all symbols
    symbols = [s["symbol"] for s in setups]

    # Fetch momentum scores
    momentum_collection = db["momentum_scores"]
    momentum_cursor = momentum_collection.aggregate([
        {"$match": {"symbol": {"$in": symbols}}},
        {"$sort": {"calculated_at": -1}},
        {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
    ])
    momentum_map = {doc["symbol"]: doc async for doc in momentum_cursor}

    # Fetch consistency scores
    consistency_collection = db["consistency_scores"]
    consistency_cursor = consistency_collection.aggregate([
        {"$match": {"symbol": {"$in": symbols}}},
        {"$sort": {"calculated_at": -1}},
        {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
    ])
    consistency_map = {doc["symbol"]: doc async for doc in consistency_cursor}

    # Fetch liquidity scores
    liquidity_collection = db["liquidity_scores"]
    liquidity_cursor = liquidity_collection.aggregate([
        {"$match": {"symbol": {"$in": symbols}}},
        {"$sort": {"calculated_at": -1}},
        {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
    ])
    liquidity_map = {doc["symbol"]: doc async for doc in liquidity_cursor}

    # Enrich setups
    for setup in setups:
        symbol = setup["symbol"]

        # Add momentum context
        if symbol in momentum_map:
            setup["momentum_score"] = momentum_map[symbol].get("momentum_score", 0)
            setup["proximity_52w"] = momentum_map[symbol].get("proximity_52w", 0)

        # Add consistency context
        if symbol in consistency_map:
            setup["consistency_score"] = consistency_map[symbol].get("consistency_score", 0)
            setup["regime_score"] = consistency_map[symbol].get("regime_score", 0)

        # Add liquidity context
        if symbol in liquidity_map:
            setup["liquidity_score"] = liquidity_map[symbol].get("liquidity_score", 0)
            setup["turnover_20d_cr"] = liquidity_map[symbol].get("turnover_20d_cr", 0)

        # Calculate overall quality score
        mom_score = setup.get("momentum_score", 0) / 100
        cons_score = setup.get("consistency_score", 0) / 100
        liq_score = setup.get("liquidity_score", 0) / 100
        setup_conf = setup.get("confidence", 0) / 100

        # Weighted average: Setup (35%) + Momentum (25%) + Consistency (25%) + Liquidity (15%)
        overall_quality = (
            0.35 * setup_conf +
            0.25 * mom_score +
            0.25 * cons_score +
            0.15 * liq_score
        )
        setup["overall_quality"] = round(overall_quality * 100, 1)

    # Re-sort by overall quality
    setups.sort(key=lambda x: x.get("overall_quality", 0), reverse=True)

    # Update ranks
    for i, setup in enumerate(setups):
        setup["rank"] = i + 1

    activity.logger.info(f"Enriched {len(setups)} setups with context scores")
    return setups


@activity.defn
async def save_setup_results(setups: list[dict], market_regime: str = "UNKNOWN") -> dict:
    """
    Save detected setups to MongoDB.

    Args:
        setups: List of detected and filtered setups
        market_regime: Current market regime

    Returns:
        Stats dict with counts.
    """
    if not setups:
        return {"saved": 0, "by_type": {}}

    db = get_database()
    collection = db["trade_setups"]

    # Create indexes
    await collection.create_index([("symbol", 1), ("detected_at", -1)])
    await collection.create_index([("type", 1)])
    await collection.create_index([("qualifies", 1)])
    await collection.create_index([("rank", 1)])

    # Add timestamp and regime
    timestamp = datetime.utcnow()
    for setup in setups:
        setup["detected_at"] = timestamp
        setup["market_regime"] = market_regime
        setup["status"] = "active"

    # Insert all setups
    await collection.insert_many(setups)

    # Count by type
    by_type = {}
    for setup in setups:
        setup_type = setup.get("type", "UNKNOWN")
        by_type[setup_type] = by_type.get(setup_type, 0) + 1

    activity.logger.info(f"Saved {len(setups)} setups: {by_type}")

    return {
        "saved": len(setups),
        "by_type": by_type,
        "avg_confidence": sum(s.get("confidence", 0) for s in setups) / len(setups) if setups else 0,
        "avg_rr_ratio": sum(s.get("rr_ratio", 0) for s in setups) / len(setups) if setups else 0,
    }


@activity.defn
async def get_active_setups(limit: int = 15) -> list[dict]:
    """
    Get active trade setups from the most recent detection.

    Args:
        limit: Maximum number of setups to return

    Returns:
        List of active setups sorted by rank.
    """
    db = get_database()
    collection = db["trade_setups"]

    # Get most recent setups
    pipeline = [
        {"$match": {"status": "active", "qualifies": True}},
        {"$sort": {"detected_at": -1, "rank": 1}},
        {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$sort": {"rank": 1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "df": 0}},  # Exclude large fields
    ]

    cursor = collection.aggregate(pipeline)
    setups = [doc async for doc in cursor]

    activity.logger.info(f"Retrieved {len(setups)} active setups")
    return setups

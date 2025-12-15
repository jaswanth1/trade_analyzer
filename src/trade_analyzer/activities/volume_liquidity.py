"""Volume & Liquidity filter activities for Phase 4A.

This module implements:
1. Multi-dimensional liquidity scoring (0-100)
2. Smart volume expansion detection
3. Circuit & halt intelligence
4. Impact cost estimation
"""

import asyncio
from datetime import datetime

from temporalio import activity

from trade_analyzer.data.providers.market_data import MarketDataProvider
from trade_analyzer.db.connection import get_database


@activity.defn
async def fetch_consistency_qualified_symbols() -> list[str]:
    """
    Fetch symbols that passed consistency filter (Phase 3).

    Returns:
        List of symbol strings that qualified from consistency analysis.
    """
    db = get_database()
    collection = db["consistency_scores"]

    # Find stocks that qualified in most recent run
    pipeline = [
        {"$match": {"qualifies": True}},
        {"$sort": {"calculated_at": -1, "final_score": -1}},
        {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$project": {"symbol": 1}},
    ]

    cursor = collection.aggregate(pipeline)
    symbols = [doc["symbol"] async for doc in cursor]

    activity.logger.info(f"Found {len(symbols)} consistency-qualified symbols")
    return symbols


@activity.defn
async def calculate_volume_liquidity_batch(
    symbols: list[str],
    fetch_delay: float = 0.3,
) -> list[dict]:
    """
    Calculate volume & liquidity metrics for a batch of symbols.

    Args:
        symbols: List of stock symbols
        fetch_delay: Delay between API calls (rate limiting)

    Returns:
        List of dicts with volume/liquidity metrics for each symbol.
    """
    provider = MarketDataProvider()
    results = []

    for i, symbol in enumerate(symbols):
        try:
            # Fetch 90 days of daily data
            ohlcv = provider.fetch_ohlcv_yahoo(symbol, days=120)

            if ohlcv is None or ohlcv.data.empty or len(ohlcv.data) < 60:
                activity.logger.warning(f"Insufficient data for {symbol}")
                continue

            df = ohlcv.data

            # Calculate volume/liquidity metrics
            liq_metrics = provider.calculate_volume_liquidity_metrics(df)
            if liq_metrics is None:
                continue

            # Circuit analysis
            circuit_info = provider.detect_circuit_hits(df)

            # Combine results
            result = {
                "symbol": symbol,
                **liq_metrics,
                **circuit_info,
                "close": df["close"].iloc[-1],
                "calculated_at": datetime.utcnow().isoformat(),
            }

            results.append(result)

            if (i + 1) % 10 == 0:
                activity.logger.info(f"Processed {i + 1}/{len(symbols)} symbols")

        except Exception as e:
            activity.logger.warning(f"Error processing {symbol}: {e}")

        # Rate limiting
        if fetch_delay > 0:
            await asyncio.sleep(fetch_delay)

    activity.logger.info(f"Calculated liquidity metrics for {len(results)} symbols")
    return results


@activity.defn
async def filter_by_liquidity(
    liquidity_data: list[dict],
    min_liquidity_score: float = 75,
    min_turnover_20d: float = 10,
    max_circuit_hits: int = 1,
    max_gap_pct: float = 2.0,
) -> list[dict]:
    """
    Filter stocks by liquidity criteria.

    Args:
        liquidity_data: List of dicts with liquidity metrics
        min_liquidity_score: Minimum liquidity score (0-100)
        min_turnover_20d: Minimum 20D avg turnover in Crores
        max_circuit_hits: Maximum circuit hits allowed in 30D
        max_gap_pct: Maximum average gap percentage

    Returns:
        Filtered list of stocks meeting liquidity criteria.
    """
    filtered = []

    for stock in liquidity_data:
        # Apply filters
        passes_liq_score = stock.get("liquidity_score", 0) >= min_liquidity_score
        passes_turnover = stock.get("turnover_20d_cr", 0) >= min_turnover_20d
        passes_circuit = stock.get("circuit_hits_30d", 99) <= max_circuit_hits
        passes_gap = stock.get("avg_gap_pct", 99) <= max_gap_pct

        # Count filters passed
        filters_passed = sum([passes_liq_score, passes_turnover, passes_circuit, passes_gap])

        # Require at least 3/4 filters to pass
        if filters_passed >= 3:
            stock["liq_filters_passed"] = filters_passed
            stock["passes_liq_score"] = passes_liq_score
            stock["passes_turnover"] = passes_turnover
            stock["passes_circuit"] = passes_circuit
            stock["passes_gap"] = passes_gap
            stock["liq_qualifies"] = True
            filtered.append(stock)
        else:
            stock["liq_filters_passed"] = filters_passed
            stock["liq_qualifies"] = False

    # Sort by liquidity score
    filtered.sort(key=lambda x: x.get("liquidity_score", 0), reverse=True)

    activity.logger.info(
        f"Liquidity filter: {len(filtered)}/{len(liquidity_data)} passed "
        f"(min_score={min_liquidity_score}, min_turnover={min_turnover_20d}Cr)"
    )

    return filtered


@activity.defn
async def save_liquidity_results(results: list[dict]) -> dict:
    """
    Save liquidity filter results to MongoDB.

    Args:
        results: List of liquidity analysis results

    Returns:
        Stats dict with counts.
    """
    if not results:
        return {"saved": 0, "qualified": 0}

    db = get_database()
    collection = db["liquidity_scores"]

    # Create index
    await collection.create_index([("symbol", 1), ("calculated_at", -1)])
    await collection.create_index([("liq_qualifies", 1)])
    await collection.create_index([("liquidity_score", -1)])

    # Add timestamp
    timestamp = datetime.utcnow()
    for result in results:
        result["calculated_at"] = timestamp

    # Insert all results
    await collection.insert_many(results)

    qualified = sum(1 for r in results if r.get("liq_qualifies", False))

    activity.logger.info(f"Saved {len(results)} liquidity results, {qualified} qualified")

    return {
        "saved": len(results),
        "qualified": qualified,
        "avg_liquidity_score": sum(r.get("liquidity_score", 0) for r in results) / len(results) if results else 0,
    }


@activity.defn
async def get_liquidity_qualified_symbols() -> list[str]:
    """
    Get symbols that passed liquidity filter.

    Returns:
        List of symbol strings.
    """
    db = get_database()
    collection = db["liquidity_scores"]

    # Get most recent qualified stocks
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

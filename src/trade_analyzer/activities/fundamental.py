"""Fundamental Intelligence activities.

This module implements:
1. Multi-dimensional fundamental scoring (0-100)
2. Institutional ownership intelligence
3. Integration with FMP and Alpha Vantage APIs

Architecture:
- Monthly: FundamentalDataRefreshWorkflow fetches API data for universe
- Weekly: apply_fundamental_filter() uses cached data (no API calls)
- Phase 1 applies fundamental filter using cached fundamental_scores
"""

import asyncio
from datetime import datetime

from temporalio import activity

from trade_analyzer.config import FMP_API_KEY, ALPHA_VANTAGE_API_KEY
from trade_analyzer.db.connection import get_database


@activity.defn
async def fetch_setup_qualified_symbols() -> list[str]:
    """
    Fetch symbols that have active trade setups from Phase 4B.

    Returns:
        List of symbol strings from active trade setups.
    """
    db = get_database()
    collection = db["trade_setups"]

    # Get unique symbols with active setups
    pipeline = [
        {"$match": {"status": "active"}},
        {"$sort": {"detected_at": -1, "overall_quality": -1}},
        {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        {"$project": {"symbol": "$_id"}},
    ]

    cursor = collection.aggregate(pipeline)
    symbols = [doc["symbol"] for doc in cursor]

    activity.logger.info(f"Found {len(symbols)} setup-qualified symbols")
    return symbols


@activity.defn
async def fetch_fundamental_data_batch(
    symbols: list[str],
    fetch_delay: float = 1.0,
) -> list[dict]:
    """
    Fetch fundamental data for a batch of symbols from FMP API.

    Args:
        symbols: List of stock symbols
        fetch_delay: Delay between API calls (respecting rate limits)

    Returns:
        List of dicts with fundamental metrics.
    """
    from trade_analyzer.data.providers.fundamental import FundamentalDataProvider

    if not FMP_API_KEY:
        activity.logger.warning("FMP API key not configured")
        return []

    provider = FundamentalDataProvider(FMP_API_KEY, ALPHA_VANTAGE_API_KEY)
    results = []

    for i, symbol in enumerate(symbols):
        try:
            data = provider.fetch_fundamental_data(symbol)

            if data is None:
                activity.logger.warning(f"No fundamental data for {symbol}")
                continue

            # Convert dataclass to dict for storage
            result = {
                "symbol": symbol,
                "eps_current": data.eps_current,
                "eps_previous": data.eps_previous,
                "eps_qoq_growth": data.eps_qoq_growth,
                "revenue_current": data.revenue_current,
                "revenue_previous": data.revenue_previous,
                "revenue_yoy_growth": data.revenue_yoy_growth,
                "roce": data.roce,
                "roe": data.roe,
                "debt_equity": data.debt_equity,
                "opm_margin": data.opm_margin,
                "opm_trend": data.opm_trend,
                "fcf_yield": data.fcf_yield,
                "cash_eps": data.cash_eps,
                "reported_eps": data.reported_eps,
                "market_cap": data.market_cap,
                "data_source": data.data_source,
                "fetched_at": datetime.utcnow().isoformat(),
            }
            results.append(result)

            if (i + 1) % 5 == 0:
                activity.logger.info(f"Processed {i + 1}/{len(symbols)} symbols")

        except Exception as e:
            activity.logger.warning(f"Error processing {symbol}: {e}")

        if fetch_delay > 0:
            await asyncio.sleep(fetch_delay)

    activity.logger.info(f"Fetched fundamental data for {len(results)} symbols")
    return results


@activity.defn
async def calculate_fundamental_scores(
    fundamental_data: list[dict],
) -> list[dict]:
    """
    Calculate multi-dimensional fundamental scores.

    Formula:
    FUNDAMENTAL_SCORE = 30% Growth + 25% Profitability +
                        20% Leverage + 15% Cash_Flow +
                        10% Earnings_Quality

    Args:
        fundamental_data: List of fundamental data dicts

    Returns:
        List with calculated scores.
    """
    from trade_analyzer.data.providers.fundamental import (
        FundamentalData,
        FundamentalDataProvider,
    )

    # Get sector map from stocks collection
    db = get_database()
    stocks_collection = db["stocks"]
    symbols = [d["symbol"] for d in fundamental_data]

    sector_cursor = stocks_collection.find(
        {"symbol": {"$in": symbols}}, {"symbol": 1, "sector": 1}
    )
    sector_map = {doc["symbol"]: doc.get("sector", "Unknown") for doc in sector_cursor}

    provider = FundamentalDataProvider("", "")  # No API keys needed for scoring
    scored = []

    for data in fundamental_data:
        symbol = data["symbol"]
        sector = sector_map.get(symbol, "Unknown")

        # Reconstruct FundamentalData object
        fund_data = FundamentalData(
            symbol=symbol,
            eps_qoq_growth=data.get("eps_qoq_growth", 0),
            revenue_yoy_growth=data.get("revenue_yoy_growth", 0),
            roce=data.get("roce", 0),
            roe=data.get("roe", 0),
            debt_equity=data.get("debt_equity", 0),
            opm_margin=data.get("opm_margin", 0),
            opm_trend=data.get("opm_trend", "stable"),
            fcf_yield=data.get("fcf_yield", 0),
            cash_eps=data.get("cash_eps", 0),
            reported_eps=data.get("reported_eps", 0),
            market_cap=data.get("market_cap", 0),
        )

        # Calculate scores
        result = provider.calculate_fundamental_score(fund_data, sector)
        result["sector"] = sector
        scored.append(result)

    # Sort by fundamental score descending
    scored.sort(key=lambda x: x.get("fundamental_score", 0), reverse=True)

    qualified = sum(1 for s in scored if s.get("qualifies"))
    avg_score = (
        sum(s.get("fundamental_score", 0) for s in scored) / len(scored)
        if scored
        else 0
    )

    activity.logger.info(
        f"Calculated fundamental scores: {qualified}/{len(scored)} qualified, "
        f"avg score: {avg_score:.1f}"
    )

    return scored


@activity.defn
async def fetch_institutional_holdings_batch(
    symbols: list[str],
    fetch_delay: float = 0.5,
) -> list[dict]:
    """
    Fetch institutional holding data from NSE.

    Args:
        symbols: List of stock symbols
        fetch_delay: Delay between API calls

    Returns:
        List of institutional holding dicts.
    """
    from trade_analyzer.data.providers.nse_holdings import NSEHoldingsProvider

    provider = NSEHoldingsProvider()
    results = []

    for i, symbol in enumerate(symbols):
        try:
            holding = provider.fetch_shareholding_pattern(symbol)

            if holding is None:
                activity.logger.warning(f"No holding data for {symbol}")
                continue

            # Calculate scores and qualification
            result = provider.calculate_holding_score(holding)
            results.append(result)

            if (i + 1) % 10 == 0:
                activity.logger.info(f"Processed {i + 1}/{len(symbols)} holdings")

        except Exception as e:
            activity.logger.warning(f"Error fetching holdings for {symbol}: {e}")

        if fetch_delay > 0:
            await asyncio.sleep(fetch_delay)

    qualified = sum(1 for r in results if r.get("qualifies"))
    activity.logger.info(
        f"Fetched institutional holdings for {len(results)} symbols "
        f"({qualified} qualified)"
    )

    return results


@activity.defn
async def save_fundamental_results(
    fundamental_scores: list[dict],
    institutional_holdings: list[dict],
) -> dict:
    """
    Save fundamental analysis results to MongoDB.

    Args:
        fundamental_scores: List of fundamental score dicts
        institutional_holdings: List of institutional holding dicts

    Returns:
        Stats dict with counts.
    """
    db = get_database()
    timestamp = datetime.utcnow()

    # Save fundamental scores
    fund_collection = db["fundamental_scores"]
    for score in fundamental_scores:
        score["calculated_at"] = timestamp

    if fundamental_scores:
        fund_collection.insert_many(fundamental_scores)

    # Create indexes for fundamental scores
    fund_collection.create_index([("symbol", 1), ("calculated_at", -1)])
    fund_collection.create_index([("fundamental_score", -1)])
    fund_collection.create_index("qualifies")

    # Save institutional holdings
    inst_collection = db["institutional_holdings"]
    for holding in institutional_holdings:
        holding["fetched_at"] = timestamp

    if institutional_holdings:
        inst_collection.insert_many(institutional_holdings)

    # Create indexes for holdings
    inst_collection.create_index([("symbol", 1), ("fetched_at", -1)])
    inst_collection.create_index("qualifies")

    fund_qualified = sum(1 for s in fundamental_scores if s.get("qualifies"))
    inst_qualified = sum(1 for h in institutional_holdings if h.get("qualifies"))

    # Calculate combined qualification (both must qualify)
    fund_symbols = {s["symbol"] for s in fundamental_scores if s.get("qualifies")}
    inst_symbols = {h["symbol"] for h in institutional_holdings if h.get("qualifies")}
    combined_qualified = len(fund_symbols & inst_symbols)

    activity.logger.info(
        f"Saved {len(fundamental_scores)} fundamental scores ({fund_qualified} qualified), "
        f"{len(institutional_holdings)} holdings ({inst_qualified} qualified), "
        f"{combined_qualified} combined qualified"
    )

    return {
        "fundamental_saved": len(fundamental_scores),
        "fundamental_qualified": fund_qualified,
        "holdings_saved": len(institutional_holdings),
        "holdings_qualified": inst_qualified,
        "combined_qualified": combined_qualified,
        "avg_fundamental_score": (
            sum(s.get("fundamental_score", 0) for s in fundamental_scores)
            / len(fundamental_scores)
            if fundamental_scores
            else 0
        ),
    }


@activity.defn
async def get_fundamentally_qualified_symbols() -> list[str]:
    """
    Get symbols that passed fundamental filters.

    Returns both fundamental score AND institutional holding qualification.

    Returns:
        List of symbol strings.
    """
    db = get_database()

    # Get fundamentally qualified symbols
    fund_collection = db["fundamental_scores"]
    fund_pipeline = [
        {"$match": {"qualifies": True}},
        {"$sort": {"calculated_at": -1, "fundamental_score": -1}},
        {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        {"$project": {"symbol": "$_id"}},
    ]

    fund_cursor = fund_collection.aggregate(fund_pipeline)
    fund_symbols = {doc["symbol"] for doc in fund_cursor}

    # Get institutionally qualified symbols
    inst_collection = db["institutional_holdings"]
    inst_pipeline = [
        {"$match": {"qualifies": True}},
        {"$sort": {"fetched_at": -1}},
        {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        {"$project": {"symbol": "$_id"}},
    ]

    inst_cursor = inst_collection.aggregate(inst_pipeline)
    inst_symbols = {doc["symbol"] for doc in inst_cursor}

    # Combined qualification - must pass both
    qualified_symbols = list(fund_symbols & inst_symbols)

    # Sort by fundamental score
    if qualified_symbols:
        scores = fund_collection.find(
            {"symbol": {"$in": qualified_symbols}, "qualifies": True}
        ).sort("fundamental_score", -1)

        qualified_symbols = [doc["symbol"] for doc in scores]

    activity.logger.info(
        f"Found {len(qualified_symbols)} fundamentally-qualified symbols "
        f"(from {len(fund_symbols)} fundamental, {len(inst_symbols)} institutional)"
    )

    return qualified_symbols


# --- New activities for Phase 1 integration ---


@activity.defn
async def fetch_universe_for_fundamentals(min_quality_score: float = 60.0) -> list[str]:
    """
    Fetch high-quality symbols from universe for fundamental data refresh.

    This is used by the MONTHLY FundamentalDataRefreshWorkflow to fetch
    fundamental data for all quality stocks (not just trade setups).

    Args:
        min_quality_score: Minimum quality score threshold

    Returns:
        List of symbol strings from stocks collection.
    """
    db = get_database()
    collection = db["stocks"]

    # Get all active, high-quality stocks
    cursor = collection.find(
        {
            "is_active": True,
            "quality_score": {"$gte": min_quality_score},
        },
        {"symbol": 1},
    ).sort("quality_score", -1)

    symbols = [doc["symbol"] for doc in cursor]

    activity.logger.info(
        f"Found {len(symbols)} high-quality symbols for fundamental refresh"
    )
    return symbols


@activity.defn
async def apply_fundamental_filter(min_score: float = 60.0) -> dict:
    """
    Apply fundamental filter using CACHED data (no API calls).

    Called in Phase 1 after universe setup. Updates stocks collection
    with fundamentally_qualified flag based on cached fundamental_scores.

    Args:
        min_score: Minimum fundamental score to qualify

    Returns:
        Stats dict with filter results.
    """
    db = get_database()
    stocks_collection = db["stocks"]
    fund_collection = db["fundamental_scores"]
    inst_collection = db["institutional_holdings"]

    # Get latest fundamental scores for each symbol
    fund_pipeline = [
        {"$sort": {"calculated_at": -1}},
        {"$group": {
            "_id": "$symbol",
            "fundamental_score": {"$first": "$fundamental_score"},
            "qualifies": {"$first": "$qualifies"},
            "calculated_at": {"$first": "$calculated_at"},
        }},
    ]
    fund_cursor = fund_collection.aggregate(fund_pipeline)
    fund_map = {
        doc["_id"]: {
            "score": doc.get("fundamental_score", 0),
            "qualifies": doc.get("qualifies", False),
            "calculated_at": doc.get("calculated_at"),
        }
        for doc in fund_cursor
    }

    # Get latest institutional holdings for each symbol
    inst_pipeline = [
        {"$sort": {"fetched_at": -1}},
        {"$group": {
            "_id": "$symbol",
            "qualifies": {"$first": "$qualifies"},
        }},
    ]
    inst_cursor = inst_collection.aggregate(inst_pipeline)
    inst_map = {doc["_id"]: doc.get("qualifies", False) for doc in inst_cursor}

    # Get all active stocks
    active_stocks = list(stocks_collection.find({"is_active": True}, {"symbol": 1}))

    # Update each stock with fundamental qualification
    qualified_count = 0
    no_data_count = 0
    updated_count = 0

    for stock in active_stocks:
        symbol = stock["symbol"]
        fund_data = fund_map.get(symbol)
        inst_qualifies = inst_map.get(symbol, False)

        if fund_data is None:
            # No fundamental data yet - mark as not qualified but don't exclude
            # (will be fetched in next monthly refresh)
            fundamentally_qualified = False
            fundamental_score = None
            fundamental_updated_at = None
            no_data_count += 1
        else:
            # Check if passes both fundamental AND institutional filters
            fund_qualifies = fund_data["qualifies"] and fund_data["score"] >= min_score
            fundamentally_qualified = fund_qualifies and inst_qualifies
            fundamental_score = fund_data["score"]
            fundamental_updated_at = fund_data["calculated_at"]

            if fundamentally_qualified:
                qualified_count += 1

        # Update stock document
        stocks_collection.update_one(
            {"_id": stock["_id"]},
            {
                "$set": {
                    "fundamentally_qualified": fundamentally_qualified,
                    "fundamental_score": fundamental_score,
                    "fundamental_updated_at": fundamental_updated_at,
                }
            },
        )
        updated_count += 1

    activity.logger.info(
        f"Applied fundamental filter: {qualified_count}/{updated_count} qualified, "
        f"{no_data_count} stocks have no fundamental data yet"
    )

    return {
        "total_stocks": updated_count,
        "fundamentally_qualified": qualified_count,
        "no_data": no_data_count,
        "min_score": min_score,
    }


@activity.defn
async def get_fundamentally_qualified_for_momentum() -> list[str]:
    """
    Get symbols that passed Phase 1 fundamental filter.

    Used by Phase 2 momentum filter as input. Returns only stocks where
    fundamentally_qualified = True in the stocks collection.

    Returns:
        List of symbol strings ready for momentum analysis.
    """
    db = get_database()
    collection = db["stocks"]

    # Get stocks that are active AND fundamentally qualified
    cursor = collection.find(
        {
            "is_active": True,
            "fundamentally_qualified": True,
        },
        {"symbol": 1, "fundamental_score": 1},
    ).sort("fundamental_score", -1)

    symbols = [doc["symbol"] for doc in cursor]

    activity.logger.info(
        f"Found {len(symbols)} fundamentally-qualified symbols for momentum analysis"
    )
    return symbols

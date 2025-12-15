"""Risk Geometry activities for Phase 6.

This module implements:
1. Multi-method stop-loss calculation (structure, volatility, time)
2. Advanced position sizing (Kelly + Volatility adjusted)
3. Dynamic R:R optimization
"""

import asyncio
from datetime import datetime

from temporalio import activity

from trade_analyzer.config import DEFAULT_PORTFOLIO_VALUE, DEFAULT_RISK_PCT
from trade_analyzer.db.connection import get_database


@activity.defn
async def fetch_fundamentally_enriched_setups() -> list[dict]:
    """
    Fetch setups that passed Phase 5 fundamental analysis.

    Returns:
        List of setup dicts with fundamental context.
    """
    db = get_database()
    setups_collection = db["trade_setups"]
    fund_collection = db["fundamental_scores"]
    inst_collection = db["institutional_holdings"]

    # Get active setups
    setups_cursor = setups_collection.find({"status": "active"}).sort(
        [("detected_at", -1), ("overall_quality", -1)]
    )
    setups = list(setups_cursor)

    if not setups:
        activity.logger.info("No active setups found")
        return []

    # Get symbols
    symbols = list({s["symbol"] for s in setups})

    # Get fundamental scores (most recent)
    fund_cursor = fund_collection.aggregate([
        {"$match": {"symbol": {"$in": symbols}, "qualifies": True}},
        {"$sort": {"calculated_at": -1}},
        {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
    ])
    fund_map = {doc["symbol"]: doc for doc in fund_cursor}

    # Get institutional holdings (most recent)
    inst_cursor = inst_collection.aggregate([
        {"$match": {"symbol": {"$in": symbols}, "qualifies": True}},
        {"$sort": {"fetched_at": -1}},
        {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
    ])
    inst_map = {doc["symbol"]: doc for doc in inst_cursor}

    # Filter to only fundamentally qualified and enrich
    enriched = []
    for setup in setups:
        symbol = setup["symbol"]
        if symbol in fund_map and symbol in inst_map:
            setup["fundamental_score"] = fund_map[symbol].get("fundamental_score", 0)
            setup["roce"] = fund_map[symbol].get("roce", 0)
            setup["roe"] = fund_map[symbol].get("roe", 0)
            setup["debt_equity"] = fund_map[symbol].get("debt_equity", 0)
            setup["fii_holding_pct"] = inst_map[symbol].get("fii_holding_pct", 0)
            setup["total_institutional"] = inst_map[symbol].get("total_institutional", 0)
            enriched.append(setup)

    activity.logger.info(
        f"Found {len(enriched)} fundamentally-enriched setups "
        f"(from {len(setups)} active setups)"
    )
    return enriched


@activity.defn
async def calculate_risk_geometry_batch(
    setups: list[dict],
    min_rr_risk_on: float = 2.0,
    min_rr_choppy: float = 2.5,
    max_stop_pct: float = 7.0,
    market_regime: str = "risk_on",
) -> list[dict]:
    """
    Calculate multi-method stop-loss and R:R for setups.

    Methods:
    1. Structure Stop: Below swing low
    2. Volatility Stop: Entry - 2.0 * ATR(14)
    3. Time Stop: Flag for 5 days without 2% move

    FINAL_STOP = max(Method1, Method2) - tighter of two (higher value)

    Args:
        setups: List of setup dicts
        min_rr_risk_on: Minimum R:R in risk-on regime
        min_rr_choppy: Minimum R:R in choppy regime
        max_stop_pct: Maximum stop distance percentage
        market_regime: Current market regime

    Returns:
        List of setups with risk geometry.
    """
    from trade_analyzer.data.providers.market_data import MarketDataProvider

    provider = MarketDataProvider()
    min_rr = min_rr_risk_on if market_regime == "risk_on" else min_rr_choppy

    results = []

    for i, setup in enumerate(setups):
        try:
            symbol = setup["symbol"]

            # Fetch fresh data for swing low calculation
            ohlcv = provider.fetch_ohlcv_yahoo(symbol, days=60)
            if ohlcv is None or ohlcv.data.empty:
                activity.logger.warning(f"No OHLCV data for {symbol}")
                continue

            df = ohlcv.data

            # Entry price (midpoint of entry zone)
            entry_low = setup.get("entry_low", 0)
            entry_high = setup.get("entry_high", 0)
            if entry_low == 0 and entry_high == 0:
                entry = df["close"].iloc[-1]
                entry_low = entry * 0.99
                entry_high = entry * 1.01
            else:
                entry = (entry_low + entry_high) / 2

            # Method 1: Structure stop (swing low of last 10 days)
            swing_low = df["low"].tail(10).min()
            stop_structure = swing_low * 0.99  # 1% below swing low

            # Method 2: Volatility stop (ATR-based)
            # Calculate ATR manually
            high_low = df["high"] - df["low"]
            high_close = abs(df["high"] - df["close"].shift())
            low_close = abs(df["low"] - df["close"].shift())

            tr = high_low.combine(high_close, max).combine(low_close, max)
            atr_14 = tr.rolling(14).mean().iloc[-1]

            stop_volatility = entry - (2.0 * atr_14)

            # Final stop: tighter of two (higher value = less risk)
            final_stop = max(stop_structure, stop_volatility)
            stop_method = "structure" if final_stop == stop_structure else "volatility"

            # Stop distance percentage
            stop_distance_pct = ((entry - final_stop) / entry) * 100

            # Risk per share
            risk_per_share = entry - final_stop

            # Targets
            target_1 = entry + (2.0 * risk_per_share)  # 2R
            target_2 = setup.get("target_2", entry + (3.0 * risk_per_share))  # 3R or existing

            # R:R ratios
            rr_ratio_1 = 2.0  # By definition
            rr_ratio_2 = (target_2 - entry) / risk_per_share if risk_per_share > 0 else 0

            # Validation
            passes_rr = rr_ratio_1 >= min_rr
            passes_stop = stop_distance_pct <= max_stop_pct
            risk_qualifies = passes_rr and passes_stop

            result = {
                **setup,
                "entry_price": round(entry, 2),
                "entry_zone_low": round(entry_low, 2),
                "entry_zone_high": round(entry_high, 2),
                "stop_structure": round(stop_structure, 2),
                "stop_volatility": round(stop_volatility, 2),
                "final_stop": round(final_stop, 2),
                "stop_method": stop_method,
                "stop_distance_pct": round(stop_distance_pct, 2),
                "atr_14": round(atr_14, 2),
                "target_1": round(target_1, 2),
                "target_2": round(target_2, 2),
                "target_1_pct": round(((target_1 - entry) / entry) * 100, 2),
                "target_2_pct": round(((target_2 - entry) / entry) * 100, 2),
                "risk_per_share": round(risk_per_share, 2),
                "rr_ratio_1": round(rr_ratio_1, 2),
                "rr_ratio_2": round(rr_ratio_2, 2),
                "trailing_breakeven_at": 0.03,
                "trailing_plus2_at": 0.06,
                "trail_to_20dma_at": 0.10,
                "passes_rr_min": passes_rr,
                "passes_stop_max": passes_stop,
                "risk_qualifies": risk_qualifies,
                "market_regime": market_regime,
            }
            results.append(result)

            if (i + 1) % 5 == 0:
                activity.logger.info(f"Processed {i + 1}/{len(setups)} setups")

        except Exception as e:
            activity.logger.warning(f"Error processing {setup.get('symbol')}: {e}")

        await asyncio.sleep(0.3)  # Rate limiting

    qualified = sum(1 for r in results if r.get("risk_qualifies"))
    activity.logger.info(f"Risk geometry: {qualified}/{len(results)} qualified")

    return results


@activity.defn
async def calculate_position_sizes(
    risk_geometries: list[dict],
    portfolio_value: float = DEFAULT_PORTFOLIO_VALUE,
    risk_pct_per_trade: float = DEFAULT_RISK_PCT,
    max_position_pct: float = 0.08,  # 8%
    max_positions: int = 12,
    market_regime: str = "risk_on",
) -> list[dict]:
    """
    Calculate advanced position sizes with adjustments.

    Formula:
    Base_Size = (Portfolio * Risk%) / Risk_per_share
    Vol_Adjusted = Base_Size * (Nifty_ATR / Stock_ATR)
    Kelly_Fraction = (Win% * AvgWin - Loss% * AvgLoss) / AvgWin
    FINAL_SIZE = Base_Size * Vol_Adjusted * min(1.0, Kelly_Fraction) * Regime_Mult

    Args:
        risk_geometries: List of setups with risk geometry
        portfolio_value: Total portfolio value in INR
        risk_pct_per_trade: Risk per trade as decimal
        max_position_pct: Max single position as decimal
        max_positions: Maximum number of positions
        market_regime: Current market regime

    Returns:
        List of position sizes.
    """
    from trade_analyzer.data.providers.market_data import MarketDataProvider

    provider = MarketDataProvider()

    # Fetch Nifty ATR
    nifty = provider.fetch_nifty_ohlcv("NIFTY 50", days=30)
    if nifty is not None and not nifty.data.empty:
        nifty_df = nifty.data
        nifty_tr = nifty_df["high"] - nifty_df["low"]
        nifty_atr = nifty_tr.rolling(14).mean().iloc[-1]
    else:
        nifty_atr = 200  # Default

    # Regime multiplier
    regime_multipliers = {
        "risk_on": 1.0,
        "choppy": 0.5,
        "risk_off": 0.0,
    }
    regime_mult = regime_multipliers.get(market_regime, 0.5)

    # Historical performance (from trades collection)
    db = get_database()
    trades_cursor = db["trades"].find(
        {"status": {"$in": ["closed_win", "closed_loss"]}}
    )
    trades = list(trades_cursor)

    if len(trades) >= 20:
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        win_rate = len(wins) / len(trades)
        avg_win = (
            sum(t.get("r_multiple", 0) for t in wins) / len(wins) if wins else 1.2
        )
        losses = [t for t in trades if t.get("pnl", 0) <= 0]
        avg_loss = (
            abs(sum(t.get("r_multiple", 0) for t in losses) / len(losses))
            if losses
            else 1.0
        )
    else:
        # Conservative defaults
        win_rate = 0.50
        avg_win = 1.2
        avg_loss = 1.0

    # Kelly fraction
    kelly = (
        (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win if avg_win > 0 else 0.5
    )
    kelly_adjusted = min(1.0, max(0.25, kelly))  # Bound between 0.25 and 1.0

    results = []
    base_risk = portfolio_value * risk_pct_per_trade

    for geom in risk_geometries:
        if not geom.get("risk_qualifies"):
            continue

        symbol = geom["symbol"]
        entry = geom["entry_price"]
        stop = geom["final_stop"]
        risk_per_share = geom["risk_per_share"]
        stock_atr = geom.get("atr_14", entry * 0.02)

        # Base size
        if risk_per_share <= 0:
            continue
        base_shares = int(base_risk / risk_per_share)

        # Volatility adjustment
        vol_adjustment = (nifty_atr / stock_atr) if stock_atr > 0 else 1.0
        vol_adjustment = min(1.5, max(0.5, vol_adjustment))  # Bound

        # Final calculation
        adjusted_shares = int(base_shares * vol_adjustment * kelly_adjusted * regime_mult)

        # Apply max position constraint
        max_shares_by_value = int((portfolio_value * max_position_pct) / entry)
        final_shares = min(adjusted_shares, max_shares_by_value)

        if final_shares <= 0:
            continue

        final_value = final_shares * entry
        final_risk = final_shares * risk_per_share
        position_pct = (final_value / portfolio_value) * 100

        result = {
            **geom,
            "portfolio_value": portfolio_value,
            "risk_pct": risk_pct_per_trade,
            "base_risk_amount": round(base_risk, 2),
            "base_shares": base_shares,
            "base_position_value": round(base_shares * entry, 2),
            "stock_atr": round(stock_atr, 2),
            "nifty_atr": round(nifty_atr, 2),
            "vol_adjustment": round(vol_adjustment, 2),
            "historical_win_rate": round(win_rate, 2),
            "historical_avg_win": round(avg_win, 2),
            "historical_avg_loss": round(avg_loss, 2),
            "kelly_fraction": round(kelly, 4),
            "kelly_adjusted": round(kelly_adjusted, 2),
            "regime_multiplier": regime_mult,
            "final_shares": final_shares,
            "final_position_value": round(final_value, 2),
            "final_risk_amount": round(final_risk, 2),
            "position_pct_of_portfolio": round(position_pct, 2),
            "passes_max_position": position_pct <= max_position_pct * 100,
        }
        results.append(result)

    # Sort by overall quality and limit to max positions
    results.sort(key=lambda x: x.get("overall_quality", 0), reverse=True)
    results = results[:max_positions]

    total_risk = sum(r.get("final_risk_amount", 0) for r in results)
    total_value = sum(r.get("final_position_value", 0) for r in results)

    activity.logger.info(
        f"Calculated position sizes for {len(results)} positions. "
        f"Total risk: Rs.{total_risk:,.0f}, Total value: Rs.{total_value:,.0f}"
    )

    return results


@activity.defn
async def save_risk_geometry_results(results: list[dict]) -> dict:
    """
    Save risk geometry and position sizing results to MongoDB.

    Args:
        results: List of position-sized setups

    Returns:
        Stats dict.
    """
    if not results:
        return {"saved": 0, "total_positions": 0, "total_risk": 0, "total_value": 0}

    db = get_database()
    collection = db["position_sizes"]

    timestamp = datetime.utcnow()
    for r in results:
        r["calculated_at"] = timestamp
        # Remove MongoDB _id if present to allow new insert
        r.pop("_id", None)

    collection.insert_many(results)

    # Create indexes
    collection.create_index([("symbol", 1), ("calculated_at", -1)])
    collection.create_index("risk_qualifies")
    collection.create_index([("overall_quality", -1)])

    total_risk = sum(r.get("final_risk_amount", 0) for r in results)
    total_value = sum(r.get("final_position_value", 0) for r in results)

    activity.logger.info(
        f"Saved {len(results)} position sizes. "
        f"Total risk: Rs.{total_risk:,.0f}, Total value: Rs.{total_value:,.0f}"
    )

    return {
        "saved": len(results),
        "total_positions": len(results),
        "total_risk": total_risk,
        "total_value": total_value,
    }

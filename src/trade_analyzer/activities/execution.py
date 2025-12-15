"""Execution activities for Phase 8.

This module implements execution monitoring and analysis for the trading system.
It handles gap analysis, position tracking, and system health monitoring.

IMPORTANT: This is UI DISPLAY ONLY - no actual order placement or broker integration.
The system generates recommendations; execution is manual.

Pipeline Position: Phase 8 (after Portfolio Construction)
Input: 3-10 portfolio positions from Phase 7
Output: Monday gap analysis, position status, Friday summaries

Three Core Functions:

1. Monday Pre-Market Gap Analysis (8:30-9:15 AM IST)
    - Analyzes weekend gaps for all setups
    - Applies gap contingency rules
    - Recommends action: ENTER/SKIP/WAIT

Gap Contingency Rules:
    If current <= stop:
        Action: SKIP (gapped through stop)
    If current > entry_high * 1.02:
        Action: SKIP (don't chase, >2% above)
    If entry_low <= current <= entry_high:
        Action: ENTER (in entry zone)
    If current < entry_low and gap < -2%:
        Action: WAIT (large gap against)
    Else:
        Action: ENTER_AT_OPEN (small gap against)

2. Intraday Position Status (Throughout Week)
    - Tracks current prices for open positions
    - Calculates unrealized P&L and R-multiples
    - Generates alerts for key events:
        * Stop proximity (<2%)
        * Target proximity (<2%)
        * R-multiple milestones (1R, 2R, 3R)
        * Trailing stop suggestions

Position Status Values:
    - stopped_out: Hit stop loss
    - target_1_hit: Hit first target (2R)
    - target_2_hit: Hit second target (3R+)
    - in_profit: Above entry, not at target
    - in_loss: Below entry, above stop

3. Friday Close Summary (End of Week)
    - Aggregates week's performance
    - Closed trades P&L
    - Open positions status
    - System health assessment

System Health Monitoring:

Health Score (0-100) based on:
    - Win rate (12W and 52W)
    - Expectancy (recent trades)
    - Current drawdown
    - Sample size

Recommended Actions:
    Score ≥70: CONTINUE (system performing well)
    Score 50-70: REDUCE (cut sizes 50%)
    Score 30-50: PAPER_TRADE (review system)
    Score <30: STOP (full system review)

Drawdown Controls:
    - Weekly drawdown >5%: Pause new trades
    - Monthly drawdown >10%: Reduce size 50%
    - Total drawdown >20%: Stop system

Output:
    - Monday gap analysis saved to monday_premarket collection
    - Position statuses updated in real-time
    - Friday summaries saved to friday_summaries collection
    - System health tracked continuously
"""

import asyncio
from datetime import datetime, timedelta

from temporalio import activity

from trade_analyzer.db.connection import get_database


@activity.defn
async def fetch_current_prices(symbols: list[str]) -> dict:
    """
    Fetch current/pre-market prices for symbols.

    Args:
        symbols: List of stock symbols

    Returns:
        Dict mapping symbol to price data.
    """
    from trade_analyzer.data.providers.market_data import MarketDataProvider

    provider = MarketDataProvider()
    prices = {}

    for symbol in symbols:
        try:
            ohlcv = provider.fetch_ohlcv_yahoo(symbol, days=5)
            if ohlcv is not None and not ohlcv.data.empty:
                latest = ohlcv.data.iloc[-1]
                prev = ohlcv.data.iloc[-2] if len(ohlcv.data) > 1 else latest

                prices[symbol] = {
                    "current": float(latest["close"]),
                    "open": float(latest["open"]),
                    "high": float(latest["high"]),
                    "low": float(latest["low"]),
                    "prev_close": float(prev["close"]),
                    "change_pct": round(
                        ((latest["close"] - prev["close"]) / prev["close"]) * 100, 2
                    ),
                    "volume": int(latest["volume"]),
                }
            await asyncio.sleep(0.2)
        except Exception as e:
            activity.logger.warning(f"Error fetching price for {symbol}: {e}")

    activity.logger.info(f"Fetched prices for {len(prices)}/{len(symbols)} symbols")
    return prices


@activity.defn
async def analyze_monday_gaps(
    setups: list[dict],
    prices: dict,
    gap_threshold_pct: float = 2.0,
) -> list[dict]:
    """
    Analyze Monday morning gaps for trade setups.

    Gap Contingency Rules:
    - Gap through stop: SKIP
    - Small gap against (<2%): ENTER_AT_OPEN
    - Gap above entry (>2%): SKIP (don't chase)

    Args:
        setups: List of portfolio setups
        prices: Current price data
        gap_threshold_pct: Threshold for significant gap

    Returns:
        List of gap analysis dicts.
    """
    analyses = []

    for setup in setups:
        symbol = setup["symbol"]
        price_data = prices.get(symbol)

        if not price_data:
            analyses.append({
                "symbol": symbol,
                "gap_pct": 0,
                "action": "SKIP",
                "reason": "No price data available",
                "setup": setup,
            })
            continue

        current = price_data["current"]
        prev_close = price_data["prev_close"]
        gap_pct = ((current - prev_close) / prev_close) * 100

        entry_low = setup.get("entry_low", setup.get("entry_zone_low", 0))
        entry_high = setup.get("entry_high", setup.get("entry_zone_high", 0))
        stop = setup.get("stop", setup.get("final_stop", 0))

        # Determine action based on gap
        if current <= stop:
            action = "SKIP"
            reason = f"Gapped through stop (current: {current:.2f}, stop: {stop:.2f})"
        elif current > entry_high * (1 + gap_threshold_pct / 100):
            action = "SKIP"
            reason = f"Gapped too far above entry zone (+{gap_pct:.1f}%), don't chase"
        elif current < entry_low and gap_pct < -gap_threshold_pct:
            action = "WAIT"
            reason = f"Large gap against (-{abs(gap_pct):.1f}%), wait for stabilization"
        elif entry_low <= current <= entry_high:
            action = "ENTER"
            reason = f"Price in entry zone ({entry_low:.2f} - {entry_high:.2f})"
        elif current < entry_low:
            action = "ENTER_AT_OPEN"
            reason = f"Small gap against (-{abs(gap_pct):.1f}%), enter at open"
        else:
            action = "WAIT"
            reason = f"Price slightly above entry, wait for pullback"

        analyses.append({
            "symbol": symbol,
            "current_price": round(current, 2),
            "prev_close": round(prev_close, 2),
            "gap_pct": round(gap_pct, 2),
            "entry_zone": f"{entry_low:.2f} - {entry_high:.2f}",
            "stop": round(stop, 2),
            "action": action,
            "reason": reason,
            "setup": setup,
        })

    # Count actions
    enter_count = sum(1 for a in analyses if a["action"] in ["ENTER", "ENTER_AT_OPEN"])
    skip_count = sum(1 for a in analyses if a["action"] == "SKIP")
    wait_count = sum(1 for a in analyses if a["action"] == "WAIT")

    activity.logger.info(
        f"Monday gap analysis: {enter_count} ENTER, {skip_count} SKIP, {wait_count} WAIT"
    )

    return analyses


@activity.defn
async def calculate_sector_momentum() -> dict:
    """
    Calculate sector momentum for context.

    Returns:
        Dict with sector performance data.
    """
    from trade_analyzer.data.providers.market_data import MarketDataProvider

    provider = MarketDataProvider()

    # Sector proxies (using Nifty sector indices)
    sectors = {
        "NIFTY BANK": "Banking",
        "NIFTY IT": "Technology",
        "NIFTY PHARMA": "Healthcare",
        "NIFTY AUTO": "Automobiles",
        "NIFTY FMCG": "Consumer",
        "NIFTY METAL": "Metals",
        "NIFTY REALTY": "Real Estate",
        "NIFTY ENERGY": "Energy",
        "NIFTY INFRA": "Infrastructure",
        "NIFTY FIN SERVICE": "Financial Services",
    }

    momentum = {}

    for index_name, sector_name in sectors.items():
        try:
            ohlcv = provider.fetch_nifty_ohlcv(index_name, days=30)
            if ohlcv is not None and not ohlcv.data.empty:
                df = ohlcv.data
                latest = df["close"].iloc[-1]
                week_ago = df["close"].iloc[-5] if len(df) >= 5 else df["close"].iloc[0]
                month_ago = df["close"].iloc[0]

                momentum[sector_name] = {
                    "current": round(latest, 2),
                    "week_change_pct": round(((latest - week_ago) / week_ago) * 100, 2),
                    "month_change_pct": round(((latest - month_ago) / month_ago) * 100, 2),
                    "trend": "bullish" if latest > week_ago > month_ago else "bearish" if latest < week_ago < month_ago else "neutral",
                }
            await asyncio.sleep(0.3)
        except Exception as e:
            activity.logger.warning(f"Error fetching {index_name}: {e}")

    activity.logger.info(f"Calculated momentum for {len(momentum)} sectors")
    return momentum


@activity.defn
async def update_position_status(
    positions: list[dict],
    prices: dict,
) -> list[dict]:
    """
    Update current status for open positions.

    Args:
        positions: List of open position dicts
        prices: Current price data

    Returns:
        List of position status dicts.
    """
    statuses = []

    for pos in positions:
        symbol = pos["symbol"]
        price_data = prices.get(symbol)

        if not price_data:
            statuses.append({
                **pos,
                "status": "unknown",
                "current_price": 0,
                "current_pnl": 0,
                "current_r_multiple": 0,
                "alerts": ["No price data"],
            })
            continue

        current = price_data["current"]
        entry = pos.get("entry_price", 0)
        stop = pos.get("stop", pos.get("final_stop", 0))
        target_1 = pos.get("target_1", 0)
        target_2 = pos.get("target_2", 0)
        shares = pos.get("shares", pos.get("final_shares", 0))
        risk_per_share = entry - stop if entry > stop else 1

        # Calculate P&L
        pnl = (current - entry) * shares
        pnl_pct = ((current - entry) / entry) * 100 if entry > 0 else 0
        r_multiple = (current - entry) / risk_per_share if risk_per_share > 0 else 0

        # Determine status
        if current <= stop:
            status = "stopped_out"
        elif current >= target_2:
            status = "target_2_hit"
        elif current >= target_1:
            status = "target_1_hit"
        elif current > entry:
            status = "in_profit"
        else:
            status = "in_loss"

        # Generate alerts
        alerts = generate_position_alerts_sync(pos, current, entry, stop, target_1, target_2)

        statuses.append({
            **pos,
            "status": status,
            "current_price": round(current, 2),
            "current_pnl": round(pnl, 2),
            "current_pnl_pct": round(pnl_pct, 2),
            "current_r_multiple": round(r_multiple, 2),
            "alerts": alerts,
        })

    activity.logger.info(f"Updated status for {len(statuses)} positions")
    return statuses


def generate_position_alerts_sync(
    position: dict,
    current: float,
    entry: float,
    stop: float,
    target_1: float,
    target_2: float,
) -> list[str]:
    """
    Generate alerts for a position (sync helper).

    Args:
        position: Position dict
        current: Current price
        entry: Entry price
        stop: Stop loss
        target_1: First target
        target_2: Second target

    Returns:
        List of alert strings.
    """
    alerts = []
    symbol = position.get("symbol", "UNKNOWN")
    risk_per_share = entry - stop if entry > stop else 1

    # Stop proximity alert
    stop_distance_pct = ((current - stop) / current) * 100
    if 0 < stop_distance_pct < 2:
        alerts.append(f"⚠️ {symbol}: Price within 2% of stop!")

    # Target proximity alerts
    if current > entry:
        to_target_1 = ((target_1 - current) / current) * 100
        if 0 < to_target_1 < 2:
            alerts.append(f"🎯 {symbol}: Approaching Target 1 ({target_1:.2f})")

        to_target_2 = ((target_2 - current) / current) * 100
        if 0 < to_target_2 < 2:
            alerts.append(f"🎯 {symbol}: Approaching Target 2 ({target_2:.2f})")

    # R-multiple milestones
    r_multiple = (current - entry) / risk_per_share if risk_per_share > 0 else 0

    if 0.95 <= r_multiple <= 1.05:
        alerts.append(f"📈 {symbol}: At 1R - Consider moving stop to breakeven")
    elif 1.95 <= r_multiple <= 2.05:
        alerts.append(f"📈 {symbol}: At 2R (Target 1) - Consider taking partial profits")
    elif 2.95 <= r_multiple <= 3.05:
        alerts.append(f"📈 {symbol}: At 3R - Consider taking more profits")

    # Trailing stop suggestions
    if r_multiple >= 1.5:
        new_stop = entry + (0.5 * risk_per_share)
        alerts.append(f"🔒 {symbol}: Trail stop to {new_stop:.2f} (lock in 0.5R)")

    return alerts


@activity.defn
async def generate_position_alerts(position: dict) -> list[str]:
    """
    Generate alerts for a single position.

    Args:
        position: Position dict with current status

    Returns:
        List of alert strings.
    """
    return generate_position_alerts_sync(
        position,
        position.get("current_price", 0),
        position.get("entry_price", 0),
        position.get("stop", position.get("final_stop", 0)),
        position.get("target_1", 0),
        position.get("target_2", 0),
    )


@activity.defn
async def generate_friday_summary(week_start: datetime) -> dict:
    """
    Generate end-of-week summary.

    Args:
        week_start: Start of the week (Monday)

    Returns:
        Summary dict with P&L, metrics, and recommendations.
    """
    db = get_database()
    week_end = week_start + timedelta(days=6)

    # Get trades from this week
    trades_collection = db["trades"]
    trades_cursor = trades_collection.find({
        "entry_date": {"$gte": week_start, "$lte": week_end}
    })
    trades = list(trades_cursor)

    # Calculate metrics
    closed_trades = [t for t in trades if t.get("status") in ["closed_win", "closed_loss"]]
    open_trades = [t for t in trades if t.get("status") == "open"]

    realized_pnl = sum(t.get("pnl", 0) for t in closed_trades)
    unrealized_pnl = sum(t.get("unrealized_pnl", 0) for t in open_trades)

    wins = [t for t in closed_trades if t.get("pnl", 0) > 0]
    losses = [t for t in closed_trades if t.get("pnl", 0) <= 0]

    win_rate = len(wins) / len(closed_trades) if closed_trades else 0
    total_r = sum(t.get("r_multiple", 0) for t in closed_trades)

    avg_win_r = sum(t.get("r_multiple", 0) for t in wins) / len(wins) if wins else 0
    avg_loss_r = sum(t.get("r_multiple", 0) for t in losses) / len(losses) if losses else 0

    # Get system health
    system_health = await calculate_system_health()

    summary = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "total_trades": len(trades),
        "closed_trades": len(closed_trades),
        "open_trades": len(open_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate * 100, 1),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_pnl": round(realized_pnl + unrealized_pnl, 2),
        "total_r": round(total_r, 2),
        "avg_win_r": round(avg_win_r, 2),
        "avg_loss_r": round(abs(avg_loss_r), 2),
        "open_positions": [
            {
                "symbol": t.get("symbol"),
                "entry": t.get("entry_price"),
                "current_pnl": t.get("unrealized_pnl", 0),
            }
            for t in open_trades
        ],
        "closed_positions": [
            {
                "symbol": t.get("symbol"),
                "entry": t.get("entry_price"),
                "exit": t.get("exit_price"),
                "pnl": t.get("pnl", 0),
                "r_multiple": t.get("r_multiple", 0),
            }
            for t in closed_trades
        ],
        "system_health": system_health,
        "generated_at": datetime.utcnow().isoformat(),
    }

    # Save summary
    db["friday_summaries"].insert_one({**summary, "created_at": datetime.utcnow()})
    db["friday_summaries"].create_index([("week_start", -1)])

    activity.logger.info(
        f"Friday summary: {len(closed_trades)} closed ({win_rate*100:.0f}% WR), "
        f"Rs.{realized_pnl:,.0f} realized P&L"
    )

    return summary


@activity.defn
async def calculate_system_health() -> dict:
    """
    Calculate overall system health metrics.

    Returns:
        System health dict with score and recommendations.
    """
    db = get_database()

    # Get all closed trades
    trades_cursor = db["trades"].find({
        "status": {"$in": ["closed_win", "closed_loss"]}
    }).sort("exit_date", -1)
    trades = list(trades_cursor)

    if not trades:
        return {
            "health_score": 50,
            "win_rate_12w": 0,
            "win_rate_52w": 0,
            "expectancy_12w": 0,
            "current_drawdown": 0,
            "recommended_action": "PAPER_TRADE",
            "message": "Insufficient trade history. Continue paper trading.",
        }

    # 12-week metrics
    twelve_weeks_ago = datetime.utcnow() - timedelta(weeks=12)
    recent_trades = [
        t for t in trades
        if t.get("exit_date", datetime.min) > twelve_weeks_ago
    ]

    if recent_trades:
        recent_wins = [t for t in recent_trades if t.get("pnl", 0) > 0]
        win_rate_12w = len(recent_wins) / len(recent_trades)
        avg_win = sum(t.get("r_multiple", 0) for t in recent_wins) / len(recent_wins) if recent_wins else 0
        recent_losses = [t for t in recent_trades if t.get("pnl", 0) <= 0]
        avg_loss = abs(sum(t.get("r_multiple", 0) for t in recent_losses) / len(recent_losses)) if recent_losses else 1
        expectancy_12w = (win_rate_12w * avg_win) - ((1 - win_rate_12w) * avg_loss)
    else:
        win_rate_12w = 0
        expectancy_12w = 0

    # 52-week metrics
    fifty_two_weeks_ago = datetime.utcnow() - timedelta(weeks=52)
    yearly_trades = [
        t for t in trades
        if t.get("exit_date", datetime.min) > fifty_two_weeks_ago
    ]

    if yearly_trades:
        yearly_wins = [t for t in yearly_trades if t.get("pnl", 0) > 0]
        win_rate_52w = len(yearly_wins) / len(yearly_trades)
    else:
        win_rate_52w = 0

    # Calculate drawdown
    cumulative_pnl = []
    running_pnl = 0
    for t in reversed(trades):  # Oldest to newest
        running_pnl += t.get("pnl", 0)
        cumulative_pnl.append(running_pnl)

    if cumulative_pnl:
        peak = max(cumulative_pnl)
        current = cumulative_pnl[-1]
        current_drawdown = ((peak - current) / peak * 100) if peak > 0 else 0
    else:
        current_drawdown = 0

    # Calculate health score (0-100)
    score = 50  # Base score

    # Win rate contribution (up to +20)
    if win_rate_12w >= 0.55:
        score += 20
    elif win_rate_12w >= 0.50:
        score += 10
    elif win_rate_12w < 0.45:
        score -= 10

    # Expectancy contribution (up to +20)
    if expectancy_12w >= 0.3:
        score += 20
    elif expectancy_12w >= 0.1:
        score += 10
    elif expectancy_12w < 0:
        score -= 15

    # Drawdown penalty (up to -20)
    if current_drawdown > 20:
        score -= 20
    elif current_drawdown > 10:
        score -= 10
    elif current_drawdown > 5:
        score -= 5

    # Sample size bonus
    if len(recent_trades) >= 20:
        score += 10

    score = max(0, min(100, score))

    # Determine recommended action
    if score >= 70:
        action = "CONTINUE"
        message = "System performing well. Continue trading normally."
    elif score >= 50:
        action = "REDUCE"
        message = "System underperforming. Reduce position sizes by 50%."
    elif score >= 30:
        action = "PAPER_TRADE"
        message = "System struggling. Switch to paper trading for review."
    else:
        action = "STOP"
        message = "System failing. Stop trading and conduct full review."

    health = {
        "health_score": round(score),
        "win_rate_12w": round(win_rate_12w * 100, 1),
        "win_rate_52w": round(win_rate_52w * 100, 1),
        "expectancy_12w": round(expectancy_12w, 3),
        "current_drawdown": round(current_drawdown, 1),
        "total_trades": len(trades),
        "recent_trades": len(recent_trades),
        "recommended_action": action,
        "message": message,
        "calculated_at": datetime.utcnow().isoformat(),
    }

    activity.logger.info(
        f"System health: {score}/100, {action} - {win_rate_12w*100:.0f}% WR, "
        f"{expectancy_12w:.2f} expectancy"
    )

    return health


@activity.defn
async def save_monday_premarket_analysis(
    gap_analyses: list[dict],
    sector_momentum: dict,
) -> dict:
    """
    Save Monday pre-market analysis to MongoDB.

    Args:
        gap_analyses: List of gap analysis dicts
        sector_momentum: Sector momentum data

    Returns:
        Stats dict.
    """
    db = get_database()
    collection = db["monday_premarket"]

    enter_count = sum(1 for a in gap_analyses if a["action"] in ["ENTER", "ENTER_AT_OPEN"])
    skip_count = sum(1 for a in gap_analyses if a["action"] == "SKIP")
    wait_count = sum(1 for a in gap_analyses if a["action"] == "WAIT")

    # Calculate Nifty gap
    nifty_gap = 0
    if "Financial Services" in sector_momentum:
        nifty_gap = sector_momentum["Financial Services"].get("week_change_pct", 0)

    analysis = {
        "analysis_date": datetime.utcnow(),
        "nifty_gap_pct": nifty_gap,
        "setup_analyses": gap_analyses,
        "enter_count": enter_count,
        "skip_count": skip_count,
        "wait_count": wait_count,
        "sector_momentum": sector_momentum,
        "created_at": datetime.utcnow(),
    }

    collection.insert_one(analysis)
    collection.create_index([("analysis_date", -1)])

    activity.logger.info(
        f"Saved Monday pre-market: {enter_count} ENTER, {skip_count} SKIP, {wait_count} WAIT"
    )

    return {
        "saved": True,
        "enter_count": enter_count,
        "skip_count": skip_count,
        "wait_count": wait_count,
    }


@activity.defn
async def get_latest_premarket_analysis() -> dict | None:
    """
    Get the most recent Monday pre-market analysis.

    Returns:
        Pre-market analysis dict or None.
    """
    db = get_database()
    collection = db["monday_premarket"]

    analysis = collection.find_one(sort=[("analysis_date", -1)])

    if analysis:
        analysis["_id"] = str(analysis["_id"])
        activity.logger.info(
            f"Found latest pre-market: {analysis['enter_count']} ENTER, "
            f"{analysis['skip_count']} SKIP"
        )
    else:
        activity.logger.info("No pre-market analysis found")

    return analysis

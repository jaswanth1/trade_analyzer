"""Momentum filter activities for Phase 2 - Enhanced Momentum & Trend Filters.

This module implements the momentum screening phase that narrows down fundamentally-
qualified stocks to those showing strong price momentum and trend characteristics.

Pipeline Position: Phase 2 (after Fundamental Filter)
Input: ~120-320 fundamentally-qualified stocks from Phase 1
Output: ~50-100 momentum-qualified stocks

The 5-filter system ensures stocks have:
1. Price near 52-week highs (strength)
2. Perfect moving average alignment (trend)
3. Outperformance vs Nifty 50 (relative strength)
4. High composite momentum score (combined signal)
5. Controlled volatility (risk management)

Stocks must pass 4+ filters to qualify. This aggressive filtering ensures only
stocks in strong uptrends with institutional support make it to Phase 3.

Filters:
    - Filter 2A: 52-Week High Proximity - Within 10-20% of highs with volume
    - Filter 2B: MA Alignment - 5-layer confirmation (close, slopes, ordering)
    - Filter 2C: Relative Strength - Multi-timeframe outperformance vs Nifty
    - Filter 2D: Momentum Score - Composite 0-100 score (≥75 to pass)
    - Filter 2E: Volatility-Adjusted - Risk-controlled momentum (vol ≤1.5x Nifty)

Expected Pass Rate: 40-80% depending on market conditions
"""

import time
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from temporalio import activity


@dataclass
class MomentumResult:
    """Result for a single stock's momentum analysis."""

    symbol: str

    # Filter 2A: 52-Week High Proximity
    proximity_52w: float  # 0-100 (100 = at 52w high)
    high_52w: float
    close: float
    volume_surge: float  # Current vs 20D avg
    filter_2a_pass: bool

    # Filter 2B: MA Alignment (5-layer)
    close_above_sma20: bool
    close_above_sma50: bool
    close_above_sma200: bool
    sma20_above_sma50: bool
    sma50_above_sma200: bool
    slope_sma20: float
    slope_sma50: float
    slope_sma200: float
    ma_alignment_score: int  # 0-5 (how many conditions pass)
    filter_2b_pass: bool

    # Filter 2C: Relative Strength
    rs_1m: float  # vs Nifty 50, percentage points
    rs_3m: float
    rs_6m: float
    rs_horizons_pass: int  # out of 3
    filter_2c_pass: bool

    # Filter 2D: Composite Momentum Score
    momentum_score: float  # 0-100

    # Filter 2E: Volatility-Adjusted
    volatility_ratio: float  # stock vol / nifty vol
    vol_adjusted_rs: float
    filter_2e_pass: bool

    # Overall
    filters_passed: int  # out of 5
    qualifies: bool  # 4+ filters passed
    calculated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MomentumFilterInput:
    """Input for momentum filter activity."""

    symbols: list[str]
    fetch_delay: float = 0.5  # Delay between API calls to avoid rate limiting


@dataclass
class MomentumFilterResult:
    """Result of momentum filter activity."""

    total_analyzed: int
    total_passed: int
    results: list[dict]  # List of MomentumResult as dicts
    nifty_return_1m: float
    nifty_return_3m: float
    nifty_return_6m: float
    analyzed_at: datetime = field(default_factory=datetime.utcnow)


def _calculate_filter_2a(
    close: float,
    high_52w: float,
    low_52w: float,
    current_volume: float,
    avg_volume_20: float,
) -> tuple[float, float, bool]:
    """
    Filter 2A: Enhanced 52-Week High Proximity.

    Criteria:
    - Primary: Close within 0-10% of 52W High [STRICT]
    - Secondary: Close within 10-20% + Volume Surge > 1.5x 20D Avg

    Returns:
        (proximity_score, volume_surge_ratio, passes_filter)
    """
    if high_52w <= low_52w or high_52w == 0:
        return 0.0, 0.0, False

    # Proximity Score: 100 = at 52w high, 0 = at 52w low
    proximity = ((close - low_52w) / (high_52w - low_52w)) * 100

    # Distance from 52w high as percentage
    distance_from_high = ((high_52w - close) / high_52w) * 100

    # Volume surge ratio
    volume_surge = current_volume / avg_volume_20 if avg_volume_20 > 0 else 0.0

    # Primary: Within 10% of 52w high (proximity >= 90)
    if proximity >= 90 or distance_from_high <= 10:
        return proximity, volume_surge, True

    # Secondary: Within 20% + volume surge
    if (proximity >= 80 or distance_from_high <= 20) and volume_surge >= 1.5:
        return proximity, volume_surge, True

    return proximity, volume_surge, False


def _calculate_filter_2b(
    close: float,
    sma_20: float,
    sma_50: float,
    sma_200: float,
    slope_20: float,
    slope_50: float,
    slope_200: float,
) -> tuple[dict, int, bool]:
    """
    Filter 2B: Advanced Moving Average System (5-Layer Confirmation).

    Criteria (ALL must pass for full score):
    1. Close > 20-DMA
    2. Close > 50-DMA
    3. Close > 200-DMA
    4. 20-DMA > 50-DMA > 200-DMA (Perfect alignment)
    5. ALL MAs sloping UP (thresholds: 20D >= 0.1%, 50D >= 0.05%, 200D >= 0.02%)

    Returns:
        (checks_dict, alignment_score, passes_filter)
    """
    checks = {
        "close_above_sma20": close > sma_20 if sma_20 > 0 else False,
        "close_above_sma50": close > sma_50 if sma_50 > 0 else False,
        "close_above_sma200": close > sma_200 if sma_200 > 0 else False,
        "sma20_above_sma50": sma_20 > sma_50 if sma_50 > 0 else False,
        "sma50_above_sma200": sma_50 > sma_200 if sma_200 > 0 else False,
        # Slope checks (normalized daily % change)
        "slope_20_positive": slope_20 >= 0.001,  # 0.1% per day
        "slope_50_positive": slope_50 >= 0.0005,  # 0.05% per day
        "slope_200_positive": slope_200 >= 0.0002,  # 0.02% per day
    }

    # Count passing conditions
    alignment_score = sum([
        checks["close_above_sma20"],
        checks["close_above_sma50"],
        checks["close_above_sma200"],
        checks["sma20_above_sma50"] and checks["sma50_above_sma200"],  # Perfect alignment
        checks["slope_20_positive"] and checks["slope_50_positive"] and checks["slope_200_positive"],
    ])

    # Pass if 4+ conditions met (relaxed from 5)
    passes = alignment_score >= 4

    return checks, alignment_score, passes


def _calculate_filter_2c(
    rs_1m: float,
    rs_3m: float,
    rs_6m: float,
) -> tuple[int, bool]:
    """
    Filter 2C: Multi-Timeframe Relative Strength vs Nifty 50.

    Criteria:
    - 1-Month RS: Stock > Nifty50 + 5%
    - 3-Month RS: Stock > Nifty50 + 10%
    - 6-Month RS: Stock > Nifty50 + 15%

    Qualifies if: 2/3 horizons pass (relaxed from 3/4)

    Returns:
        (horizons_passed, passes_filter)
    """
    horizons_passed = 0

    if rs_1m >= 5:  # 5 percentage points outperformance
        horizons_passed += 1
    if rs_3m >= 10:  # 10 percentage points
        horizons_passed += 1
    if rs_6m >= 15:  # 15 percentage points
        horizons_passed += 1

    return horizons_passed, horizons_passed >= 2


def _calculate_filter_2d(
    proximity_52w: float,
    rs_avg: float,
    ma_alignment_score: int,
    price_acceleration: float,
) -> float:
    """
    Filter 2D: Composite Momentum Score (0-100).

    Formula:
    Momentum_Score = 25% × 52W Proximity +
                     25% × RS Score (normalized) +
                     25% × MA Strength (out of 5) +
                     25% × Price Acceleration

    Returns:
        momentum_score (0-100)
    """
    # Normalize components to 0-100 scale
    proximity_component = min(100, max(0, proximity_52w))

    # RS average (assuming max outperformance of 50% is excellent)
    rs_component = min(100, max(0, (rs_avg / 50) * 100 + 50))

    # MA alignment (0-5 -> 0-100)
    ma_component = (ma_alignment_score / 5) * 100

    # Price acceleration (-5% to +5% daily normalized to 0-100)
    accel_component = min(100, max(0, (price_acceleration + 0.05) / 0.10 * 100))

    # Weighted average
    score = (
        0.25 * proximity_component +
        0.25 * rs_component +
        0.25 * ma_component +
        0.25 * accel_component
    )

    return round(score, 2)


def _calculate_filter_2e(
    volatility_ratio: float,
    rs_avg: float,
) -> tuple[float, bool]:
    """
    Filter 2E: Volatility-Adjusted Momentum.

    Criteria:
    - Stock volatility <= 1.5x Nifty volatility (controlled risk)
    - Volatility-Adjusted RS = Raw RS / Volatility Ratio

    Returns:
        (vol_adjusted_rs, passes_filter)
    """
    if volatility_ratio <= 0:
        volatility_ratio = 1.0

    vol_adjusted_rs = rs_avg / volatility_ratio

    # Pass if volatility is controlled (<=1.5x benchmark)
    passes = volatility_ratio <= 1.5

    return vol_adjusted_rs, passes


@activity.defn
async def fetch_high_quality_symbols(min_score: int = 60) -> list[str]:
    """
    Fetch high-quality, fundamentally-qualified stock symbols from the database.

    This function returns symbols that pass BOTH quality (Phase 1) AND
    fundamental filters (Phase 1). Stocks without fundamental data yet
    are excluded until the monthly FundamentalDataRefreshWorkflow runs.

    Args:
        min_score: Minimum quality score (default 60)

    Returns:
        List of stock symbols with quality_score >= min_score AND
        fundamentally_qualified = True
    """
    from trade_analyzer.db import get_database

    activity.logger.info(
        f"Fetching symbols with quality_score >= {min_score} "
        f"AND fundamentally_qualified..."
    )

    db = get_database()
    stocks = db.stocks.find(
        {
            "is_active": True,
            "quality_score": {"$gte": min_score},
            "fundamentally_qualified": True,
        },
        {"symbol": 1, "_id": 0},
    ).sort("quality_score", -1)

    symbols = [s["symbol"] for s in stocks]
    activity.logger.info(
        f"Found {len(symbols)} high-quality, fundamentally-qualified symbols"
    )

    return symbols


@activity.defn
async def fetch_market_data_batch(
    symbols: list[str],
    fetch_delay: float = 0.3,
) -> dict:
    """
    Fetch market data for a batch of symbols.

    Args:
        symbols: List of stock symbols
        fetch_delay: Delay between API calls (default 0.3s)

    Returns:
        Dict with symbol -> OHLCV data mapping
    """
    from trade_analyzer.data.providers.market_data import MarketDataProvider

    activity.logger.info(f"Fetching market data for {len(symbols)} symbols...")

    provider = MarketDataProvider()
    results = {}

    for i, symbol in enumerate(symbols):
        try:
            ohlcv = provider.fetch_ohlcv_yahoo(symbol, days=400)  # Extra days for 200 DMA
            if ohlcv and not ohlcv.data.empty:
                results[symbol] = {
                    "data": ohlcv.data.to_dict(orient="records"),
                    "start_date": ohlcv.start_date.isoformat(),
                    "end_date": ohlcv.end_date.isoformat(),
                }
            else:
                activity.logger.warning(f"No data for {symbol}")
        except Exception as e:
            activity.logger.error(f"Error fetching {symbol}: {e}")

        # Rate limiting
        if i < len(symbols) - 1:
            time.sleep(fetch_delay)

        # Log progress every 50 symbols
        if (i + 1) % 50 == 0:
            activity.logger.info(f"Fetched {i + 1}/{len(symbols)} symbols")

    activity.logger.info(f"Successfully fetched data for {len(results)}/{len(symbols)} symbols")
    return results


@activity.defn
async def fetch_nifty_benchmark_data() -> dict:
    """
    Fetch Nifty 50 benchmark data for relative strength calculations.

    Returns:
        Dict with Nifty OHLCV data and calculated returns.
    """
    from trade_analyzer.data.providers.market_data import MarketDataProvider

    activity.logger.info("Fetching Nifty 50 benchmark data...")

    provider = MarketDataProvider()
    nifty_ohlcv = provider.fetch_nifty_ohlcv("NIFTY 50", days=400)

    if not nifty_ohlcv or nifty_ohlcv.data.empty:
        activity.logger.error("Failed to fetch Nifty 50 data")
        return {}

    df = nifty_ohlcv.data
    close = df["close"].iloc[-1]

    # Calculate returns for different periods
    returns = {}
    periods = [(21, "1m"), (63, "3m"), (126, "6m")]

    for days, label in periods:
        if len(df) >= days:
            ret = (close / df["close"].iloc[-days] - 1) * 100
            returns[f"return_{label}"] = ret
        else:
            returns[f"return_{label}"] = 0.0

    # Calculate Nifty volatility (20-day)
    nifty_vol = df["close"].pct_change().iloc[-20:].std() if len(df) >= 20 else 0.01

    activity.logger.info(
        f"Nifty 50: 1M={returns['return_1m']:.2f}%, "
        f"3M={returns['return_3m']:.2f}%, 6M={returns['return_6m']:.2f}%"
    )

    return {
        "data": df.to_dict(orient="records"),
        "returns": returns,
        "volatility_20d": nifty_vol,
        "close": close,
    }


@activity.defn
async def calculate_momentum_scores(
    market_data: dict,
    nifty_data: dict,
    symbols: list[str],
) -> list[dict]:
    """
    Calculate momentum scores for all symbols.

    Args:
        market_data: Dict with symbol -> OHLCV data
        nifty_data: Nifty 50 benchmark data
        symbols: List of symbols to analyze

    Returns:
        List of MomentumResult dicts for each symbol.
    """
    activity.logger.info(f"Calculating momentum scores for {len(symbols)} symbols...")

    nifty_returns = nifty_data.get("returns", {})
    nifty_vol = nifty_data.get("volatility_20d", 0.01)

    results = []

    for symbol in symbols:
        stock_data = market_data.get(symbol)
        if not stock_data:
            continue

        try:
            df = pd.DataFrame(stock_data["data"])
            if df.empty or len(df) < 200:
                continue

            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            # Calculate indicators
            df["sma_20"] = df["close"].rolling(20).mean()
            df["sma_50"] = df["close"].rolling(50).mean()
            df["sma_200"] = df["close"].rolling(200).mean()

            # Slopes (normalized daily percentage change)
            df["slope_20"] = df["sma_20"].diff(20) / df["sma_20"].shift(20) / 20
            df["slope_50"] = df["sma_50"].diff(50) / df["sma_50"].shift(50) / 50
            df["slope_200"] = df["sma_200"].diff(200) / df["sma_200"].shift(200) / 200

            # 52-week high/low
            high_52w = df["high"].iloc[-252:].max() if len(df) >= 252 else df["high"].max()
            low_52w = df["low"].iloc[-252:].min() if len(df) >= 252 else df["low"].min()

            # Latest values
            latest = df.iloc[-1]
            close = latest["close"]
            volume = latest["volume"]
            avg_vol_20 = df["volume"].iloc[-20:].mean() if len(df) >= 20 else volume

            # Stock returns
            stock_returns = {}
            periods = [(21, "1m"), (63, "3m"), (126, "6m")]
            for days, label in periods:
                if len(df) >= days:
                    ret = (close / df["close"].iloc[-days] - 1) * 100
                    stock_returns[label] = ret
                else:
                    stock_returns[label] = 0.0

            # Relative strength vs Nifty
            rs_1m = stock_returns.get("1m", 0) - nifty_returns.get("return_1m", 0)
            rs_3m = stock_returns.get("3m", 0) - nifty_returns.get("return_3m", 0)
            rs_6m = stock_returns.get("6m", 0) - nifty_returns.get("return_6m", 0)
            rs_avg = (rs_1m + rs_3m + rs_6m) / 3

            # Stock volatility
            stock_vol = df["close"].pct_change().iloc[-20:].std() if len(df) >= 20 else 0.01
            vol_ratio = stock_vol / nifty_vol if nifty_vol > 0 else 1.0

            # Price acceleration (10D MA slope change)
            df["sma_10"] = df["close"].rolling(10).mean()
            price_accel = (
                (df["sma_10"].iloc[-1] - df["sma_10"].iloc[-11]) / df["sma_10"].iloc[-11]
                if len(df) >= 11 and df["sma_10"].iloc[-11] > 0
                else 0.0
            )

            # Apply filters
            # Filter 2A
            proximity, volume_surge, f2a_pass = _calculate_filter_2a(
                close, high_52w, low_52w, volume, avg_vol_20
            )

            # Filter 2B
            ma_checks, ma_score, f2b_pass = _calculate_filter_2b(
                close,
                latest.get("sma_20", 0),
                latest.get("sma_50", 0),
                latest.get("sma_200", 0),
                latest.get("slope_20", 0),
                latest.get("slope_50", 0),
                latest.get("slope_200", 0),
            )

            # Filter 2C
            rs_horizons, f2c_pass = _calculate_filter_2c(rs_1m, rs_3m, rs_6m)

            # Filter 2D
            momentum_score = _calculate_filter_2d(proximity, rs_avg, ma_score, price_accel)

            # Filter 2E
            vol_adj_rs, f2e_pass = _calculate_filter_2e(vol_ratio, rs_avg)

            # Filter 2D pass (score >= 75)
            f2d_pass = momentum_score >= 75

            filters_passed = sum([f2a_pass, f2b_pass, f2c_pass, f2d_pass, f2e_pass])
            qualifies = filters_passed >= 4

            results.append({
                "symbol": symbol,
                "proximity_52w": round(proximity, 2),
                "high_52w": round(high_52w, 2),
                "close": round(close, 2),
                "volume_surge": round(volume_surge, 2),
                "filter_2a_pass": f2a_pass,
                "close_above_sma20": ma_checks["close_above_sma20"],
                "close_above_sma50": ma_checks["close_above_sma50"],
                "close_above_sma200": ma_checks["close_above_sma200"],
                "sma20_above_sma50": ma_checks["sma20_above_sma50"],
                "sma50_above_sma200": ma_checks["sma50_above_sma200"],
                "slope_sma20": round(latest.get("slope_20", 0) * 100, 4),  # As percentage
                "slope_sma50": round(latest.get("slope_50", 0) * 100, 4),
                "slope_sma200": round(latest.get("slope_200", 0) * 100, 4),
                "ma_alignment_score": ma_score,
                "filter_2b_pass": f2b_pass,
                "rs_1m": round(rs_1m, 2),
                "rs_3m": round(rs_3m, 2),
                "rs_6m": round(rs_6m, 2),
                "rs_horizons_pass": rs_horizons,
                "filter_2c_pass": f2c_pass,
                "momentum_score": momentum_score,
                "filter_2d_pass": f2d_pass,
                "volatility_ratio": round(vol_ratio, 2),
                "vol_adjusted_rs": round(vol_adj_rs, 2),
                "filter_2e_pass": f2e_pass,
                "filters_passed": filters_passed,
                "qualifies": qualifies,
                "calculated_at": datetime.utcnow().isoformat(),
            })

        except Exception as e:
            activity.logger.error(f"Error calculating momentum for {symbol}: {e}")
            continue

    # Sort by momentum score (highest first)
    results.sort(key=lambda x: x["momentum_score"], reverse=True)

    passed_count = sum(1 for r in results if r["qualifies"])
    activity.logger.info(
        f"Momentum analysis complete: {len(results)} analyzed, {passed_count} qualified"
    )

    return results


@activity.defn
async def save_momentum_results(
    results: list[dict],
    nifty_returns: dict,
) -> dict:
    """
    Save momentum filter results to MongoDB.

    Args:
        results: List of MomentumResult dicts
        nifty_returns: Nifty benchmark returns

    Returns:
        Stats about saved data.
    """
    from trade_analyzer.db import get_database

    activity.logger.info(f"Saving {len(results)} momentum results to database...")

    db = get_database()

    # Save to momentum_scores collection
    collection = db.momentum_scores

    # Clear previous results
    collection.delete_many({})

    # Insert new results
    if results:
        collection.insert_many(results)

    # Create indexes
    collection.create_index("symbol", unique=True)
    collection.create_index("momentum_score")
    collection.create_index("qualifies")
    collection.create_index("filters_passed")

    # Update stocks collection with momentum data
    stocks_collection = db.stocks
    for result in results:
        stocks_collection.update_one(
            {"symbol": result["symbol"]},
            {
                "$set": {
                    "momentum_score": result["momentum_score"],
                    "momentum_qualifies": result["qualifies"],
                    "filters_passed": result["filters_passed"],
                    "proximity_52w": result["proximity_52w"],
                    "ma_alignment_score": result["ma_alignment_score"],
                    "rs_3m": result["rs_3m"],
                    "momentum_updated": datetime.utcnow(),
                }
            },
        )

    # Stats
    qualified_count = sum(1 for r in results if r["qualifies"])
    stats = {
        "total_analyzed": len(results),
        "total_qualified": qualified_count,
        "avg_momentum_score": sum(r["momentum_score"] for r in results) / len(results) if results else 0,
        "nifty_return_1m": nifty_returns.get("return_1m", 0),
        "nifty_return_3m": nifty_returns.get("return_3m", 0),
        "nifty_return_6m": nifty_returns.get("return_6m", 0),
        "saved_at": datetime.utcnow().isoformat(),
    }

    activity.logger.info(
        f"Saved {len(results)} momentum scores. "
        f"Qualified: {qualified_count}, Avg Score: {stats['avg_momentum_score']:.1f}"
    )

    return stats

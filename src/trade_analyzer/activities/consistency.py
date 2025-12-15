"""Weekly Return Consistency filter activities for Phase 3.

This module implements the weekly consistency screening that identifies stocks with
reliable, repeatable weekly gains. This is the CRITICAL differentiator - most systems
ignore weekly behavior patterns.

Pipeline Position: Phase 3 (after Momentum Filter)
Input: ~50-100 momentum-qualified stocks from Phase 2
Output: ~30-50 consistency-qualified stocks

Why Weekly Consistency Matters:
- Weekend analysis, weekday execution model
- Reduces whipsaw and false breakouts
- Identifies stocks with institutional accumulation patterns
- Statistical validation ensures signals aren't noise

The 9-metric framework evaluates:
1. Win rate consistency (positive weeks %)
2. Magnitude consistency (+3%, +5% weeks)
3. Volatility control (weekly std dev)
4. Average performance (avg weekly return)
5. Risk-adjusted returns (Sharpe ratio)
6. Recent vs historical (regime score)

Stocks must pass 5+ filters to qualify. Regime-adaptive thresholds adjust based on
current market conditions (BULL/SIDEWAYS/BEAR).

Metrics & Thresholds (52W lookback):
    1. Positive Weeks %: ≥65% (BULL), ≥60% (SIDEWAYS), ≥55% (BEAR)
    2. +3% Weeks %: 25-35% (sweet spot - not too volatile)
    3. +5% Weeks %: 10-20% (explosive moves, but controlled)
    4. Weekly Std Dev: 3-6% (consistency, not chaos)
    5. Avg Weekly Return: ≥0.8% (compounds to 40%+ annually)
    6. Sharpe Ratio: ≥0.15 (risk-adjusted performance)
    7. Win Streak (26W): ≥62% (recent consistency)
    8. Consistency Score: ≥75 (composite metric)
    9. Regime Score: ≥1.2 (current regime outperforming)

Expected Pass Rate: ~60% of momentum-qualified stocks
"""

import time
from dataclasses import dataclass, field
from datetime import datetime

from temporalio import activity


@dataclass
class ConsistencyResult:
    """Result for a single stock's consistency analysis."""

    symbol: str

    # Core metrics (52W)
    pos_pct_52w: float
    plus3_pct_52w: float
    plus5_pct_52w: float
    neg5_pct_52w: float
    avg_return_52w: float
    std_dev_52w: float
    sharpe_52w: float
    sortino_52w: float
    best_week_52w: float
    worst_week_52w: float
    max_win_streak_52w: int
    avg_win_streak_52w: float

    # Recent metrics (26W)
    pos_pct_26w: float
    avg_return_26w: float
    sharpe_26w: float

    # Current momentum (13W)
    pos_pct_13w: float
    avg_return_13w: float

    # Composite scores
    consistency_score: float  # 0-100
    regime_score: float  # 13W/52W ratio
    final_score: float  # Weighted composite

    # Regime context
    market_regime: str  # BULL/SIDEWAYS/BEAR
    thresholds_used: dict

    # Filter results
    passes_pos_pct: bool
    passes_plus3_pct: bool
    passes_volatility: bool
    passes_sharpe: bool
    passes_consistency: bool
    passes_regime: bool
    filters_passed: int
    qualifies: bool

    calculated_at: datetime = field(default_factory=datetime.utcnow)


def _calculate_consistency_score(
    pos_pct: float,
    plus3_pct: float,
    std_dev: float,
    sharpe: float,
    win_streak_prob: float,
    universe_stats: dict,
) -> float:
    """
    Calculate composite consistency score (0-100).

    Formula:
    Consistency_Score = 25% × Pos%_norm +
                       25% × Plus3%_norm +
                       20% × (1/Volatility_norm) +
                       15% × Sharpe_norm +
                       15% × WinStreak_norm

    Where _norm = (metric - min) / (max - min) across universe
    """
    # Normalize each metric to 0-100 scale
    def normalize(val, min_val, max_val, inverse=False):
        if max_val == min_val:
            return 50.0
        norm = (val - min_val) / (max_val - min_val)
        if inverse:
            norm = 1 - norm
        return max(0, min(100, norm * 100))

    # Get universe stats for normalization
    pos_min = universe_stats.get("pos_pct_min", 40)
    pos_max = universe_stats.get("pos_pct_max", 80)
    plus3_min = universe_stats.get("plus3_pct_min", 10)
    plus3_max = universe_stats.get("plus3_pct_max", 50)
    vol_min = universe_stats.get("std_dev_min", 2)
    vol_max = universe_stats.get("std_dev_max", 10)
    sharpe_min = universe_stats.get("sharpe_min", -0.1)
    sharpe_max = universe_stats.get("sharpe_max", 0.4)
    win_min = universe_stats.get("win_streak_min", 40)
    win_max = universe_stats.get("win_streak_max", 80)

    # Calculate normalized components
    pos_norm = normalize(pos_pct, pos_min, pos_max)
    plus3_norm = normalize(plus3_pct, plus3_min, plus3_max)
    vol_norm = normalize(std_dev, vol_min, vol_max, inverse=True)  # Lower is better
    sharpe_norm = normalize(sharpe, sharpe_min, sharpe_max)
    win_norm = normalize(win_streak_prob, win_min, win_max)

    # Weighted composite
    score = (
        0.25 * pos_norm +
        0.25 * plus3_norm +
        0.20 * vol_norm +
        0.15 * sharpe_norm +
        0.15 * win_norm
    )

    return round(score, 2)


def _calculate_regime_score(avg_return_13w: float, avg_return_52w: float) -> float:
    """
    Calculate regime score (recent vs long-term performance).

    Regime_Score = Recent_13W_Performance / 52W_Performance
    Target: ≥1.2 (current regime outperforming history)
    """
    if avg_return_52w == 0 or avg_return_52w < 0:
        # Handle edge cases
        if avg_return_13w > 0:
            return 2.0  # Strong recent performance
        return 1.0

    ratio = avg_return_13w / avg_return_52w

    # Cap at reasonable bounds
    return max(0.5, min(3.0, ratio))


def _calculate_final_score(
    consistency_score: float,
    regime_score: float,
    sharpe: float,
    percentile: float,
) -> float:
    """
    Calculate final ranking score.

    FINAL_RANKING_SCORE = 40% × Consistency_Score +
                         25% × Regime_Score (normalized) +
                         20% × Percentile +
                         15% × Sharpe (normalized)
    """
    # Normalize regime score (0.5-3.0 -> 0-100)
    regime_norm = ((regime_score - 0.5) / 2.5) * 100

    # Normalize sharpe (-0.1 to 0.4 -> 0-100)
    sharpe_norm = ((sharpe + 0.1) / 0.5) * 100

    score = (
        0.40 * consistency_score +
        0.25 * regime_norm +
        0.20 * percentile +
        0.15 * sharpe_norm
    )

    return round(max(0, min(100, score)), 2)


@activity.defn
async def fetch_momentum_qualified_symbols() -> list[str]:
    """
    Fetch symbols that passed momentum filter (Phase 2).

    Returns:
        List of stock symbols with momentum_qualifies=True
    """
    from trade_analyzer.db import get_database

    activity.logger.info("Fetching momentum-qualified symbols...")

    db = get_database()
    stocks = db.momentum_scores.find(
        {"qualifies": True},
        {"symbol": 1, "_id": 0},
    ).sort("momentum_score", -1)

    symbols = [s["symbol"] for s in stocks]
    activity.logger.info(f"Found {len(symbols)} momentum-qualified symbols")

    return symbols


@activity.defn
async def fetch_weekly_data_batch(
    symbols: list[str],
    fetch_delay: float = 0.3,
) -> dict:
    """
    Fetch weekly OHLCV data for a batch of symbols.

    Args:
        symbols: List of stock symbols
        fetch_delay: Delay between API calls (default 0.3s)

    Returns:
        Dict with symbol -> weekly data mapping
    """
    from trade_analyzer.data.providers.market_data import MarketDataProvider

    activity.logger.info(f"Fetching weekly data for {len(symbols)} symbols...")

    provider = MarketDataProvider()
    results = {}

    for i, symbol in enumerate(symbols):
        try:
            weekly_df = provider.fetch_weekly_ohlcv(symbol, weeks=60)
            if weekly_df is not None and not weekly_df.empty:
                results[symbol] = weekly_df.to_dict(orient="records")
            else:
                activity.logger.warning(f"No weekly data for {symbol}")
        except Exception as e:
            activity.logger.error(f"Error fetching weekly data for {symbol}: {e}")

        # Rate limiting
        if i < len(symbols) - 1:
            time.sleep(fetch_delay)

        # Log progress every 25 symbols
        if (i + 1) % 25 == 0:
            activity.logger.info(f"Fetched {i + 1}/{len(symbols)} symbols")

    activity.logger.info(f"Successfully fetched weekly data for {len(results)}/{len(symbols)} symbols")
    return results


@activity.defn
async def detect_current_regime() -> dict:
    """
    Detect current market regime using Nifty 50.

    Returns:
        Dict with regime and thresholds.
    """
    from trade_analyzer.data.providers.market_data import MarketDataProvider

    activity.logger.info("Detecting market regime...")

    provider = MarketDataProvider()
    nifty_ohlcv = provider.fetch_nifty_ohlcv("NIFTY 50", days=400)

    if not nifty_ohlcv or nifty_ohlcv.data.empty:
        activity.logger.warning("Could not fetch Nifty data, defaulting to SIDEWAYS")
        regime = "SIDEWAYS"
    else:
        regime = provider.detect_market_regime(nifty_ohlcv.data)

    thresholds = provider.get_regime_thresholds(regime)

    activity.logger.info(f"Detected regime: {regime}, thresholds: {thresholds}")

    return {
        "regime": regime,
        "thresholds": thresholds,
    }


@activity.defn
async def calculate_consistency_scores(
    weekly_data: dict,
    regime_info: dict,
    symbols: list[str],
) -> list[dict]:
    """
    Calculate consistency scores for all symbols.

    Args:
        weekly_data: Dict with symbol -> weekly data
        regime_info: Dict with regime and thresholds
        symbols: List of symbols to analyze

    Returns:
        List of ConsistencyResult dicts for each symbol.
    """
    import pandas as pd

    from trade_analyzer.data.providers.market_data import MarketDataProvider

    activity.logger.info(f"Calculating consistency scores for {len(symbols)} symbols...")

    provider = MarketDataProvider()
    regime = regime_info.get("regime", "SIDEWAYS")
    thresholds = regime_info.get("thresholds", provider.get_regime_thresholds("SIDEWAYS"))

    # First pass: collect universe statistics for normalization
    all_metrics = []
    symbol_metrics = {}

    for symbol in symbols:
        data = weekly_data.get(symbol)
        if not data:
            continue

        try:
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            if "weekly_return" not in df.columns:
                df["weekly_return"] = df["close"].pct_change()

            metrics = provider.calculate_weekly_consistency_metrics(df, periods=[52, 26, 13])

            if metrics:
                symbol_metrics[symbol] = metrics
                all_metrics.append(metrics)
        except Exception as e:
            activity.logger.error(f"Error calculating metrics for {symbol}: {e}")

    if not all_metrics:
        activity.logger.warning("No valid metrics calculated")
        return []

    # Calculate universe statistics for normalization
    universe_stats = {
        "pos_pct_min": min(m.get("pos_pct_52w", 50) for m in all_metrics),
        "pos_pct_max": max(m.get("pos_pct_52w", 50) for m in all_metrics),
        "plus3_pct_min": min(m.get("plus3_pct_52w", 20) for m in all_metrics),
        "plus3_pct_max": max(m.get("plus3_pct_52w", 20) for m in all_metrics),
        "std_dev_min": min(m.get("std_dev_52w", 4) for m in all_metrics),
        "std_dev_max": max(m.get("std_dev_52w", 4) for m in all_metrics),
        "sharpe_min": min(m.get("sharpe_52w", 0) for m in all_metrics),
        "sharpe_max": max(m.get("sharpe_52w", 0) for m in all_metrics),
        "win_streak_min": 40,
        "win_streak_max": 80,
    }

    # Second pass: calculate scores and apply filters
    results = []
    scores_for_percentile = []

    for symbol, metrics in symbol_metrics.items():
        # Extract metrics
        pos_pct_52w = metrics.get("pos_pct_52w", 0)
        plus3_pct_52w = metrics.get("plus3_pct_52w", 0)
        plus5_pct_52w = metrics.get("plus5_pct_52w", 0)
        neg5_pct_52w = metrics.get("neg5_pct_52w", 0)
        avg_return_52w = metrics.get("avg_return_52w", 0)
        std_dev_52w = metrics.get("std_dev_52w", 0)
        sharpe_52w = metrics.get("sharpe_52w", 0)
        sortino_52w = metrics.get("sortino_52w", 0)
        best_week_52w = metrics.get("best_week_52w", 0)
        worst_week_52w = metrics.get("worst_week_52w", 0)
        max_win_streak_52w = metrics.get("max_win_streak_52w", 0)
        avg_win_streak_52w = metrics.get("avg_win_streak_52w", 0)

        pos_pct_26w = metrics.get("pos_pct_26w", 0)
        avg_return_26w = metrics.get("avg_return_26w", 0)
        sharpe_26w = metrics.get("sharpe_26w", 0)

        pos_pct_13w = metrics.get("pos_pct_13w", 0)
        avg_return_13w = metrics.get("avg_return_13w", 0)

        # Win streak probability (26W)
        win_streak_prob = pos_pct_26w

        # Calculate composite scores
        consistency_score = _calculate_consistency_score(
            pos_pct_52w, plus3_pct_52w, std_dev_52w, sharpe_52w,
            win_streak_prob, universe_stats
        )

        regime_score = _calculate_regime_score(avg_return_13w, avg_return_52w)

        scores_for_percentile.append((symbol, consistency_score))

    # Calculate percentiles
    sorted_scores = sorted(scores_for_percentile, key=lambda x: x[1], reverse=True)
    percentiles = {}
    n = len(sorted_scores)
    for i, (sym, _) in enumerate(sorted_scores):
        percentiles[sym] = ((n - i) / n) * 100

    # Final pass: calculate final scores and filter
    for symbol, metrics in symbol_metrics.items():
        pos_pct_52w = metrics.get("pos_pct_52w", 0)
        plus3_pct_52w = metrics.get("plus3_pct_52w", 0)
        plus5_pct_52w = metrics.get("plus5_pct_52w", 0)
        neg5_pct_52w = metrics.get("neg5_pct_52w", 0)
        avg_return_52w = metrics.get("avg_return_52w", 0)
        std_dev_52w = metrics.get("std_dev_52w", 0)
        sharpe_52w = metrics.get("sharpe_52w", 0)
        sortino_52w = metrics.get("sortino_52w", 0)
        best_week_52w = metrics.get("best_week_52w", 0)
        worst_week_52w = metrics.get("worst_week_52w", 0)
        max_win_streak_52w = metrics.get("max_win_streak_52w", 0)
        avg_win_streak_52w = metrics.get("avg_win_streak_52w", 0)

        pos_pct_26w = metrics.get("pos_pct_26w", 0)
        avg_return_26w = metrics.get("avg_return_26w", 0)
        sharpe_26w = metrics.get("sharpe_26w", 0)

        pos_pct_13w = metrics.get("pos_pct_13w", 0)
        avg_return_13w = metrics.get("avg_return_13w", 0)

        win_streak_prob = pos_pct_26w

        consistency_score = _calculate_consistency_score(
            pos_pct_52w, plus3_pct_52w, std_dev_52w, sharpe_52w,
            win_streak_prob, universe_stats
        )

        regime_score = _calculate_regime_score(avg_return_13w, avg_return_52w)

        final_score = _calculate_final_score(
            consistency_score, regime_score, sharpe_52w, percentiles.get(symbol, 50)
        )

        # Apply regime-adaptive filters
        passes_pos_pct = pos_pct_52w >= thresholds["pos_pct_min"]
        passes_plus3_pct = (
            thresholds["plus3_pct_min"] <= plus3_pct_52w <= thresholds["plus3_pct_max"]
        )
        passes_volatility = std_dev_52w <= thresholds["vol_max"]
        passes_sharpe = sharpe_52w >= thresholds["sharpe_min"]
        passes_consistency = consistency_score >= 65  # Composite score threshold
        passes_regime = regime_score >= 1.0  # At least matching historical

        filters_passed = sum([
            passes_pos_pct,
            passes_plus3_pct,
            passes_volatility,
            passes_sharpe,
            passes_consistency,
            passes_regime,
        ])

        # Qualify if 5+ filters pass
        qualifies = filters_passed >= 5

        results.append({
            "symbol": symbol,
            "pos_pct_52w": pos_pct_52w,
            "plus3_pct_52w": plus3_pct_52w,
            "plus5_pct_52w": plus5_pct_52w,
            "neg5_pct_52w": neg5_pct_52w,
            "avg_return_52w": avg_return_52w,
            "std_dev_52w": std_dev_52w,
            "sharpe_52w": round(sharpe_52w, 4),
            "sortino_52w": round(sortino_52w, 4),
            "best_week_52w": best_week_52w,
            "worst_week_52w": worst_week_52w,
            "max_win_streak_52w": max_win_streak_52w,
            "avg_win_streak_52w": avg_win_streak_52w,
            "pos_pct_26w": pos_pct_26w,
            "avg_return_26w": avg_return_26w,
            "sharpe_26w": round(sharpe_26w, 4),
            "pos_pct_13w": pos_pct_13w,
            "avg_return_13w": avg_return_13w,
            "consistency_score": consistency_score,
            "regime_score": round(regime_score, 2),
            "final_score": final_score,
            "market_regime": regime,
            "passes_pos_pct": passes_pos_pct,
            "passes_plus3_pct": passes_plus3_pct,
            "passes_volatility": passes_volatility,
            "passes_sharpe": passes_sharpe,
            "passes_consistency": passes_consistency,
            "passes_regime": passes_regime,
            "filters_passed": filters_passed,
            "qualifies": qualifies,
            "calculated_at": datetime.utcnow().isoformat(),
        })

    # Sort by final score (highest first)
    results.sort(key=lambda x: x["final_score"], reverse=True)

    passed_count = sum(1 for r in results if r["qualifies"])
    activity.logger.info(
        f"Consistency analysis complete: {len(results)} analyzed, {passed_count} qualified"
    )

    return results


@activity.defn
async def save_consistency_results(
    results: list[dict],
    regime_info: dict,
) -> dict:
    """
    Save consistency filter results to MongoDB.

    Args:
        results: List of ConsistencyResult dicts
        regime_info: Regime information

    Returns:
        Stats about saved data.
    """
    from trade_analyzer.db import get_database

    activity.logger.info(f"Saving {len(results)} consistency results to database...")

    db = get_database()

    # Save to consistency_scores collection
    collection = db.consistency_scores

    # Clear previous results
    collection.delete_many({})

    # Insert new results
    if results:
        collection.insert_many(results)

    # Create indexes
    collection.create_index("symbol", unique=True)
    collection.create_index("final_score")
    collection.create_index("consistency_score")
    collection.create_index("qualifies")
    collection.create_index("filters_passed")

    # Update stocks collection with consistency data
    stocks_collection = db.stocks
    for result in results:
        stocks_collection.update_one(
            {"symbol": result["symbol"]},
            {
                "$set": {
                    "consistency_score": result["consistency_score"],
                    "consistency_qualifies": result["qualifies"],
                    "consistency_filters_passed": result["filters_passed"],
                    "final_score": result["final_score"],
                    "regime_score": result["regime_score"],
                    "pos_pct_52w": result["pos_pct_52w"],
                    "sharpe_52w": result["sharpe_52w"],
                    "consistency_updated": datetime.utcnow(),
                }
            },
        )

    # Stats
    qualified_count = sum(1 for r in results if r["qualifies"])
    stats = {
        "total_analyzed": len(results),
        "total_qualified": qualified_count,
        "avg_final_score": round(
            sum(r["final_score"] for r in results) / len(results), 2
        ) if results else 0,
        "avg_consistency_score": round(
            sum(r["consistency_score"] for r in results) / len(results), 2
        ) if results else 0,
        "market_regime": regime_info.get("regime", "UNKNOWN"),
        "saved_at": datetime.utcnow().isoformat(),
    }

    activity.logger.info(
        f"Saved {len(results)} consistency scores. "
        f"Qualified: {qualified_count}, Avg Final Score: {stats['avg_final_score']:.1f}"
    )

    return stats

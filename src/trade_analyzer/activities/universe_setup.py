"""Universe setup activities for high-quality trading universe."""

import gzip
import json
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

import requests
from temporalio import activity

# Upstox URLs (from existing upstox.py)
NSE_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
MTF_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/MTF.json.gz"


@dataclass
class BaseUniverseData:
    """Base universe from Upstox."""

    nse_eq_instruments: list[dict]
    mtf_symbols: set[str]
    nse_eq_count: int
    mtf_count: int
    fetched_at: str


@dataclass
class NiftyData:
    """Nifty indices data."""

    nifty_50: list[str]
    nifty_100: list[str]
    nifty_200: list[str]
    nifty_500: list[str]
    fetched_at: str


@dataclass
class EnrichedStock:
    """Enriched stock with quality scores."""

    symbol: str
    name: str
    isin: str
    instrument_key: str

    # Quality flags
    is_mtf: bool  # MTF eligible (highest priority)
    in_nifty_50: bool
    in_nifty_100: bool
    in_nifty_200: bool
    in_nifty_500: bool

    # Scores
    quality_score: float  # 0-100
    liquidity_tier: str  # "A", "B", "C"

    # Metadata
    lot_size: int
    tick_size: float
    security_type: str


@dataclass
class UniverseSetupResult:
    """Result of universe setup workflow."""

    success: bool
    total_nse_eq: int
    total_mtf: int
    high_quality_count: int  # Final filtered universe
    tier_a_count: int  # Highest liquidity
    tier_b_count: int
    tier_c_count: int
    error: str | None = None


def _fetch_gzip_json(url: str) -> list[dict]:
    """Fetch and decompress gzipped JSON."""
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    with gzip.GzipFile(fileobj=BytesIO(response.content)) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _filter_nse_equity(instruments: list[dict]) -> list[dict]:
    """Filter for NSE equity only."""
    return [
        inst for inst in instruments
        if inst.get("segment") == "NSE_EQ" and inst.get("instrument_type") == "EQ"
    ]


@activity.defn
async def fetch_base_universe() -> BaseUniverseData:
    """
    Fetch base universe: NSE EQ + MTF from Upstox.

    Returns:
        BaseUniverseData with all NSE EQ instruments and MTF symbols.
    """
    activity.logger.info("Fetching base universe from Upstox...")

    # Fetch NSE instruments
    nse_instruments = _fetch_gzip_json(NSE_INSTRUMENTS_URL)
    nse_eq = _filter_nse_equity(nse_instruments)
    activity.logger.info(f"Fetched {len(nse_eq)} NSE EQ instruments")

    # Fetch MTF instruments
    mtf_instruments = _fetch_gzip_json(MTF_INSTRUMENTS_URL)
    mtf_symbols = {inst.get("trading_symbol", "") for inst in mtf_instruments}
    mtf_symbols.discard("")
    activity.logger.info(f"Fetched {len(mtf_symbols)} MTF symbols")

    return BaseUniverseData(
        nse_eq_instruments=nse_eq,
        mtf_symbols=mtf_symbols,
        nse_eq_count=len(nse_eq),
        mtf_count=len(mtf_symbols),
        fetched_at=datetime.utcnow().isoformat(),
    )


@activity.defn
async def fetch_nifty_indices() -> NiftyData:
    """
    Fetch Nifty indices constituents from NSE.

    Returns:
        NiftyData with all index constituents.
    """
    import time

    activity.logger.info("Fetching Nifty indices from NSE...")

    from trade_analyzer.data.providers.nse import fetch_nifty_constituents

    nifty_50 = list(fetch_nifty_constituents("NIFTY 50"))
    time.sleep(0.3)
    nifty_100 = list(fetch_nifty_constituents("NIFTY 100"))
    time.sleep(0.3)
    nifty_200 = list(fetch_nifty_constituents("NIFTY 200"))
    time.sleep(0.3)
    nifty_500 = list(fetch_nifty_constituents("NIFTY 500"))

    activity.logger.info(
        f"Nifty constituents: 50={len(nifty_50)}, 100={len(nifty_100)}, "
        f"200={len(nifty_200)}, 500={len(nifty_500)}"
    )

    return NiftyData(
        nifty_50=nifty_50,
        nifty_100=nifty_100,
        nifty_200=nifty_200,
        nifty_500=nifty_500,
        fetched_at=datetime.utcnow().isoformat(),
    )


@activity.defn
async def enrich_and_score_universe(
    nse_eq_instruments: list[dict],
    mtf_symbols: list[str],  # Changed to list for serialization
    nifty_50: list[str],
    nifty_100: list[str],
    nifty_200: list[str],
    nifty_500: list[str],
) -> list[dict]:
    """
    Enrich stocks with quality scores.

    Priority order (MTF first):
    1. MTF + Nifty 50 = Tier A (score 90-100)
    2. MTF + Nifty 100/200 = Tier A (score 80-90)
    3. MTF + Nifty 500 = Tier B (score 70-80)
    4. MTF only = Tier B (score 60-70)
    5. Nifty 500 (non-MTF) = Tier C (score 40-60)
    6. Other NSE EQ = Excluded or Tier C (score < 40)

    Returns:
        List of enriched stock dicts.
    """
    activity.logger.info("Enriching and scoring universe...")

    # Convert to sets for fast lookup
    mtf_set = set(mtf_symbols)
    nifty_50_set = set(nifty_50)
    nifty_100_set = set(nifty_100)
    nifty_200_set = set(nifty_200)
    nifty_500_set = set(nifty_500)

    enriched = []

    for inst in nse_eq_instruments:
        symbol = inst.get("trading_symbol", "")
        if not symbol:
            continue

        # Quality flags
        is_mtf = symbol in mtf_set
        in_nifty_50 = symbol in nifty_50_set
        in_nifty_100 = symbol in nifty_100_set
        in_nifty_200 = symbol in nifty_200_set
        in_nifty_500 = symbol in nifty_500_set

        # Calculate quality score (MTF gets highest priority)
        score = 0
        tier = "C"

        if is_mtf:
            # MTF eligible - start with base score of 60
            score = 60
            tier = "B"

            if in_nifty_50:
                score = 95
                tier = "A"
            elif in_nifty_100:
                score = 85
                tier = "A"
            elif in_nifty_200:
                score = 75
                tier = "B"
            elif in_nifty_500:
                score = 70
                tier = "B"
        else:
            # Non-MTF - lower priority
            if in_nifty_50:
                score = 55
                tier = "C"
            elif in_nifty_100:
                score = 50
                tier = "C"
            elif in_nifty_200:
                score = 45
                tier = "C"
            elif in_nifty_500:
                score = 40
                tier = "C"
            else:
                # Not in any index and not MTF - exclude
                score = 10
                tier = "D"

        enriched.append({
            "symbol": symbol,
            "name": inst.get("name", ""),
            "isin": inst.get("isin", ""),
            "instrument_key": inst.get("instrument_key", ""),
            "exchange_token": inst.get("exchange_token", ""),
            "segment": inst.get("segment", ""),
            "instrument_type": inst.get("instrument_type", ""),
            "lot_size": inst.get("lot_size", 1),
            "tick_size": inst.get("tick_size", 0.05),
            "security_type": inst.get("security_type", ""),
            "short_name": inst.get("short_name", ""),
            # Quality enrichment
            "is_mtf": is_mtf,
            "in_nifty_50": in_nifty_50,
            "in_nifty_100": in_nifty_100,
            "in_nifty_200": in_nifty_200,
            "in_nifty_500": in_nifty_500,
            "quality_score": score,
            "liquidity_tier": tier,
            "is_active": True,
            "last_updated": datetime.utcnow().isoformat(),
        })

    # Sort by quality score (highest first)
    enriched.sort(key=lambda x: x["quality_score"], reverse=True)

    tier_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for stock in enriched:
        tier_counts[stock["liquidity_tier"]] += 1

    activity.logger.info(
        f"Enriched {len(enriched)} stocks: "
        f"Tier A={tier_counts['A']}, B={tier_counts['B']}, "
        f"C={tier_counts['C']}, D={tier_counts['D']}"
    )

    return enriched


@activity.defn
async def save_enriched_universe(enriched_stocks: list[dict]) -> dict:
    """
    Save enriched universe to MongoDB.

    Args:
        enriched_stocks: List of enriched stock dicts.

    Returns:
        Stats about saved data.
    """
    from trade_analyzer.db import get_database

    activity.logger.info(f"Saving {len(enriched_stocks)} enriched stocks to database...")

    db = get_database()
    collection = db.stocks

    # Mark all existing as inactive
    collection.update_many({}, {"$set": {"is_active": False}})

    # Upsert all stocks
    saved = 0
    for stock in enriched_stocks:
        collection.update_one(
            {"symbol": stock["symbol"]},
            {"$set": stock},
            upsert=True,
        )
        saved += 1

    # Create indexes
    collection.create_index("symbol", unique=True)
    collection.create_index("is_mtf")
    collection.create_index("quality_score")
    collection.create_index("liquidity_tier")
    collection.create_index("is_active")
    collection.create_index([("quality_score", -1), ("is_mtf", -1)])

    # Count stats
    stats = {
        "total_saved": saved,
        "tier_a": collection.count_documents({"liquidity_tier": "A", "is_active": True}),
        "tier_b": collection.count_documents({"liquidity_tier": "B", "is_active": True}),
        "tier_c": collection.count_documents({"liquidity_tier": "C", "is_active": True}),
        "mtf_count": collection.count_documents({"is_mtf": True, "is_active": True}),
        "high_quality": collection.count_documents({"quality_score": {"$gte": 60}, "is_active": True}),
    }

    activity.logger.info(
        f"Saved {stats['total_saved']} stocks. "
        f"High quality (score>=60): {stats['high_quality']}, MTF: {stats['mtf_count']}"
    )

    return stats

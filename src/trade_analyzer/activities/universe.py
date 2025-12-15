"""Universe refresh activities for Temporal workflows."""

import gzip
import json
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

import requests
from temporalio import activity

NSE_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
MTF_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/MTF.json.gz"


@dataclass
class InstrumentData:
    """Data class for instrument fetch results."""

    instruments: list[dict]
    count: int
    source: str
    fetched_at: str


@dataclass
class UniverseStats:
    """Statistics about the trading universe."""

    total_nse_eq: int
    mtf_eligible: int
    last_updated: str | None


def _fetch_gzip_json(url: str) -> list[dict]:
    """Fetch and decompress gzipped JSON from URL."""
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    with gzip.GzipFile(fileobj=BytesIO(response.content)) as f:
        data = json.load(f)

    return data if isinstance(data, list) else []


def _filter_nse_equity(instruments: list[dict]) -> list[dict]:
    """Filter for NSE equity instruments only (no futures/options)."""
    return [
        inst
        for inst in instruments
        if inst.get("segment") == "NSE_EQ" and inst.get("instrument_type") == "EQ"
    ]


def _transform_instrument(instrument: dict, is_mtf: bool = False) -> dict:
    """Transform Upstox instrument to stock document format."""
    return {
        "symbol": instrument.get("trading_symbol", ""),
        "name": instrument.get("name", ""),
        "isin": instrument.get("isin", ""),
        "instrument_key": instrument.get("instrument_key", ""),
        "exchange_token": instrument.get("exchange_token", ""),
        "segment": instrument.get("segment", ""),
        "instrument_type": instrument.get("instrument_type", ""),
        "lot_size": instrument.get("lot_size", 1),
        "tick_size": instrument.get("tick_size", 0.05),
        "security_type": instrument.get("security_type", ""),
        "short_name": instrument.get("short_name", ""),
        "is_mtf": is_mtf,
        "is_active": True,
        "sector": "Unknown",
        "industry": "Unknown",
        "market_cap": 0.0,
        "avg_daily_turnover": 0.0,
        "last_updated": datetime.utcnow().isoformat(),
    }


@activity.defn
async def refresh_nse_instruments() -> InstrumentData:
    """
    Fetch NSE equity instruments from Upstox.

    Returns:
        InstrumentData with list of NSE EQ instruments.
    """
    activity.logger.info("Fetching NSE instruments from Upstox...")

    instruments = _fetch_gzip_json(NSE_INSTRUMENTS_URL)
    nse_eq = _filter_nse_equity(instruments)

    activity.logger.info(f"Fetched {len(nse_eq)} NSE EQ instruments")

    return InstrumentData(
        instruments=nse_eq,
        count=len(nse_eq),
        source="NSE",
        fetched_at=datetime.utcnow().isoformat(),
    )


@activity.defn
async def refresh_mtf_instruments() -> InstrumentData:
    """
    Fetch MTF instruments from Upstox.

    Returns:
        InstrumentData with list of MTF instruments.
    """
    activity.logger.info("Fetching MTF instruments from Upstox...")

    instruments = _fetch_gzip_json(MTF_INSTRUMENTS_URL)

    activity.logger.info(f"Fetched {len(instruments)} MTF instruments")

    return InstrumentData(
        instruments=instruments,
        count=len(instruments),
        source="MTF",
        fetched_at=datetime.utcnow().isoformat(),
    )


@activity.defn
async def save_instruments_to_db(
    nse_instruments: list[dict],
    mtf_symbols: set[str],
) -> dict:
    """
    Save instruments to MongoDB.

    Args:
        nse_instruments: List of NSE EQ instruments.
        mtf_symbols: Set of MTF-eligible symbols.

    Returns:
        Dict with save statistics.
    """
    from trade_analyzer.db import get_database

    activity.logger.info("Saving instruments to database...")

    db = get_database()
    collection = db.stocks

    # Mark all existing stocks as inactive
    collection.update_many({}, {"$set": {"is_active": False}})

    # Upsert instruments
    saved_count = 0
    mtf_count = 0

    for inst in nse_instruments:
        symbol = inst.get("trading_symbol")
        if not symbol:
            continue

        is_mtf = symbol in mtf_symbols
        if is_mtf:
            mtf_count += 1

        doc = _transform_instrument(inst, is_mtf=is_mtf)
        collection.update_one({"symbol": symbol}, {"$set": doc}, upsert=True)
        saved_count += 1

    # Ensure indexes
    collection.create_index("symbol", unique=True)
    collection.create_index("is_mtf")
    collection.create_index("is_active")
    collection.create_index("instrument_key")

    activity.logger.info(
        f"Saved {saved_count} instruments ({mtf_count} MTF eligible)"
    )

    return {
        "saved_count": saved_count,
        "mtf_count": mtf_count,
        "timestamp": datetime.utcnow().isoformat(),
    }


@activity.defn
async def get_universe_stats() -> UniverseStats:
    """
    Get statistics about the current trading universe.

    Returns:
        UniverseStats with counts and last update time.
    """
    from trade_analyzer.db import get_database

    db = get_database()
    collection = db.stocks

    total = collection.count_documents({"is_active": True})
    mtf = collection.count_documents({"is_active": True, "is_mtf": True})

    latest = collection.find_one(
        {"is_active": True},
        {"last_updated": 1},
        sort=[("last_updated", -1)],
    )
    last_updated = latest.get("last_updated") if latest else None

    return UniverseStats(
        total_nse_eq=total,
        mtf_eligible=mtf,
        last_updated=last_updated,
    )

"""Universe refresh activities for Temporal workflows.

This module implements basic universe data fetching and storage activities.
It's part of the initial universe setup phase that runs periodically to maintain
the trading universe with current market data.

Pipeline Position: Phase 0 (Initial Setup)
- Fetches NSE EQ instruments from Upstox API
- Fetches MTF (Margin Trading Facility) instruments
- Transforms and stores in MongoDB stocks collection

Activities:
    - refresh_nse_instruments: Fetch all NSE equity instruments
    - refresh_mtf_instruments: Fetch MTF-eligible symbols
    - save_instruments_to_db: Save transformed data to MongoDB
    - get_universe_stats: Get current universe statistics

Note: This is the basic version. For full quality-scored universe setup,
see universe_setup.py which implements the UniverseSetupWorkflow.
"""

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
    """Fetch and decompress gzipped JSON from URL.

    Args:
        url: URL to fetch gzipped JSON from

    Returns:
        List of dictionaries from decompressed JSON data

    Raises:
        requests.HTTPError: If HTTP request fails
        json.JSONDecodeError: If JSON parsing fails
    """
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    with gzip.GzipFile(fileobj=BytesIO(response.content)) as f:
        data = json.load(f)

    return data if isinstance(data, list) else []


def _filter_nse_equity(instruments: list[dict]) -> list[dict]:
    """Filter for NSE equity instruments only (no futures/options).

    Filters instrument list to include only:
    - segment == "NSE_EQ" (equity segment)
    - instrument_type == "EQ" (equity type)

    This excludes derivatives, futures, options, and other non-equity instruments.

    Args:
        instruments: List of all instruments from Upstox API

    Returns:
        Filtered list containing only NSE equity instruments
    """
    return [
        inst
        for inst in instruments
        if inst.get("segment") == "NSE_EQ" and inst.get("instrument_type") == "EQ"
    ]


def _transform_instrument(instrument: dict, is_mtf: bool = False) -> dict:
    """Transform Upstox instrument to stock document format.

    Converts Upstox API format to our internal stock document schema.
    Sets default values for fields that will be enriched later:
    - sector/industry: Set to "Unknown", enriched by fundamentals
    - market_cap: Set to 0.0, enriched by fundamentals
    - avg_daily_turnover: Set to 0.0, enriched by market data

    Args:
        instrument: Raw instrument dict from Upstox API
        is_mtf: Whether this instrument is MTF-eligible

    Returns:
        Transformed stock document ready for MongoDB insertion
    """
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
    """Fetch NSE equity instruments from Upstox.

    Fetches the complete list of NSE equity instruments from Upstox's
    public instruments API. The data is compressed (gzip) and contains
    all tradable instruments on NSE.

    This activity filters to include only equity instruments (NSE_EQ segment)
    and excludes derivatives, futures, and options.

    Returns:
        InstrumentData: Contains:
            - instruments: List of NSE EQ instrument dicts
            - count: Number of instruments
            - source: "NSE"
            - fetched_at: ISO timestamp

    Raises:
        requests.HTTPError: If API request fails
        json.JSONDecodeError: If response parsing fails
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
    """Fetch MTF (Margin Trading Facility) instruments from Upstox.

    MTF instruments are stocks eligible for margin trading, which indicates:
    - Higher liquidity standards
    - Lower volatility requirements
    - Exchange-approved quality criteria

    MTF eligibility is a strong quality signal and receives the highest
    priority in our quality scoring system (Phase 1).

    Returns:
        InstrumentData: Contains:
            - instruments: List of MTF instrument dicts
            - count: Number of MTF-eligible instruments
            - source: "MTF"
            - fetched_at: ISO timestamp

    Raises:
        requests.HTTPError: If API request fails
        json.JSONDecodeError: If response parsing fails
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
    """Save instruments to MongoDB stocks collection.

    Performs upsert operation for all instruments:
    1. Marks all existing stocks as inactive
    2. Upserts each NSE instrument with is_mtf flag
    3. Creates necessary indexes for efficient querying

    The is_mtf flag is critical for quality scoring in Phase 1.

    Args:
        nse_instruments: List of NSE EQ instrument dicts from Upstox
        mtf_symbols: Set of symbols that are MTF-eligible

    Returns:
        Dict with statistics:
            - saved_count: Total instruments saved
            - mtf_count: Number marked as MTF-eligible
            - timestamp: When save completed

    Side Effects:
        - Updates MongoDB stocks collection
        - Creates indexes: symbol (unique), is_mtf, is_active, instrument_key
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
    """Get statistics about the current trading universe.

    Queries MongoDB to provide counts of active instruments and
    last update timestamp. Used for monitoring and UI display.

    Returns:
        UniverseStats: Contains:
            - total_nse_eq: Count of active NSE equity instruments (~2000)
            - mtf_eligible: Count of MTF-eligible instruments (~200-300)
            - last_updated: ISO timestamp of most recent update

    Note: Only counts instruments where is_active=True
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

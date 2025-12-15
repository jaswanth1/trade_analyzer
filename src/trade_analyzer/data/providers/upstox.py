"""Upstox Instruments Data Provider.

This module provides functionality to fetch and manage trading instruments from Upstox API.
Upstox provides comprehensive lists of NSE equity instruments and MTF (Margin Trading Facility)
eligible stocks through gzipped JSON endpoints.

Data Sources:
    - NSE Equity: https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz
    - MTF Instruments: https://assets.upstox.com/market-quote/instruments/exchange/MTF.json.gz

Rate Limits:
    - Public endpoints (no API key required)
    - No explicit rate limits documented
    - Recommended: 1 request per minute for universe refresh

Data Update Frequency:
    - NSE equity list: Updated daily after market close
    - MTF list: Updated when eligibility changes (weekly/monthly)

Usage:
    Basic usage for refreshing trading universe:

    >>> from pymongo import MongoClient
    >>> from trade_analyzer.data.providers.upstox import UpstoxInstrumentProvider
    >>>
    >>> client = MongoClient("mongodb://localhost:27017")
    >>> db = client["trade_analysis"]
    >>> provider = UpstoxInstrumentProvider(db)
    >>>
    >>> # Refresh the entire trading universe
    >>> result = provider.refresh_trading_universe()
    >>> print(f"Success: {result.success}")
    >>> print(f"NSE EQ: {result.nse_eq_count}, MTF: {result.mtf_count}")
    >>>
    >>> # Get MTF-eligible stocks only
    >>> mtf_stocks = provider.get_mtf_universe()
    >>> print(f"Found {len(mtf_stocks)} MTF-eligible stocks")
    >>>
    >>> # Get universe statistics
    >>> stats = provider.get_universe_stats()
    >>> print(f"Total active: {stats['total_nse_eq']}")
    >>> print(f"MTF eligible: {stats['mtf_eligible']}")

Notes:
    - This provider focuses on liquid, margin-tradeable stocks (MTF-eligible)
    - MTF eligibility is a proxy for liquidity and institutional interest
    - The trading universe is the intersection of NSE EQ and MTF lists
    - Instruments are marked as inactive during refresh before re-activation
"""

import gzip
import json
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Optional

import requests
from pymongo.database import Database

NSE_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
MTF_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/MTF.json.gz"


@dataclass
class InstrumentFetchResult:
    """Result of instrument fetch operation.

    Encapsulates the outcome of fetching instruments from Upstox API,
    including success status, counts, and any errors encountered.

    Attributes:
        success: Whether the fetch operation succeeded
        nse_eq_count: Number of NSE equity instruments fetched
        mtf_count: Number of MTF-eligible instruments
        total_universe: Number of stocks in the intersection (NSE EQ & MTF)
        error: Error message if fetch failed, None otherwise
        timestamp: UTC timestamp when the fetch was performed
    """

    success: bool
    nse_eq_count: int = 0
    mtf_count: int = 0
    total_universe: int = 0
    error: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


class UpstoxInstrumentProvider:
    """Provider to fetch and store Upstox instruments.

    This provider fetches NSE equity and MTF instruments from Upstox's public
    endpoints and stores them in MongoDB. It maintains a trading universe that
    consists of liquid, margin-tradeable stocks.

    The provider performs three main operations:
    1. Fetches and filters NSE equity instruments (segment=NSE_EQ, type=EQ)
    2. Fetches MTF-eligible instruments
    3. Creates a trading universe from their intersection

    Attributes:
        db: MongoDB database instance
        collection: MongoDB collection for storing stock instruments

    Example:
        >>> provider = UpstoxInstrumentProvider(db)
        >>> result = provider.refresh_trading_universe()
        >>> if result.success:
        ...     print(f"Universe refreshed: {result.total_universe} stocks")
    """

    def __init__(self, db: Database):
        self.db = db
        self.collection = db["stocks"]

    def _fetch_gzip_json(self, url: str) -> list[dict]:
        """Fetch and decompress gzipped JSON from URL.

        Args:
            url: URL of the gzipped JSON file

        Returns:
            List of instrument dictionaries, empty list if not a list

        Raises:
            requests.RequestException: If network request fails
            json.JSONDecodeError: If JSON parsing fails
            gzip.BadGzipFile: If gzip decompression fails
        """
        response = requests.get(url, timeout=60)
        response.raise_for_status()

        with gzip.GzipFile(fileobj=BytesIO(response.content)) as f:
            data = json.load(f)

        return data if isinstance(data, list) else []

    def _filter_nse_equity(self, instruments: list[dict]) -> list[dict]:
        """Filter for NSE equity instruments only (no futures/options).

        Args:
            instruments: List of all NSE instruments from Upstox

        Returns:
            List of equity instruments (segment=NSE_EQ, instrument_type=EQ)

        Example:
            >>> instruments = [
            ...     {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "RELIANCE"},
            ...     {"segment": "NSE_FO", "instrument_type": "FUT", "trading_symbol": "RELIANCE25FEB"}
            ... ]
            >>> equity = provider._filter_nse_equity(instruments)
            >>> len(equity)
            1
        """
        return [
            inst
            for inst in instruments
            if inst.get("segment") == "NSE_EQ"
            and inst.get("instrument_type") == "EQ"
        ]

    def _transform_to_stock_doc(
        self, instrument: dict, is_mtf: bool = False
    ) -> dict:
        """Transform Upstox instrument to stock document format.

        Converts Upstox API format to our internal MongoDB document schema.
        Adds default values for fields that will be enriched later (sector,
        market cap, turnover, etc.).

        Args:
            instrument: Raw instrument dict from Upstox API
            is_mtf: Whether this instrument is MTF-eligible

        Returns:
            Stock document dict ready for MongoDB upsert

        Example:
            >>> upstox_inst = {
            ...     "trading_symbol": "RELIANCE",
            ...     "name": "Reliance Industries Limited",
            ...     "isin": "INE002A01018",
            ...     "instrument_key": "NSE_EQ|INE002A01018",
            ...     "segment": "NSE_EQ",
            ...     "instrument_type": "EQ"
            ... }
            >>> doc = provider._transform_to_stock_doc(upstox_inst, is_mtf=True)
            >>> doc["symbol"]
            'RELIANCE'
            >>> doc["is_mtf"]
            True
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
            "last_updated": datetime.utcnow(),
        }

    def fetch_nse_equity(self) -> list[dict]:
        """Fetch NSE equity instruments.

        Fetches all NSE instruments and filters for equity only (no F&O).

        Returns:
            List of NSE equity instrument dicts

        Raises:
            requests.RequestException: If download fails
            json.JSONDecodeError: If JSON parsing fails

        Example:
            >>> nse_eq = provider.fetch_nse_equity()
            >>> len(nse_eq) > 2000  # Typically 2000+ equity instruments
            True
        """
        instruments = self._fetch_gzip_json(NSE_INSTRUMENTS_URL)
        return self._filter_nse_equity(instruments)

    def fetch_mtf_instruments(self) -> list[dict]:
        """Fetch MTF instruments (already equity only).

        MTF (Margin Trading Facility) list contains stocks approved for
        margin trading by brokers. These are typically liquid, high-quality
        stocks with institutional interest.

        Returns:
            List of MTF instrument dicts (all equity)

        Raises:
            requests.RequestException: If download fails
            json.JSONDecodeError: If JSON parsing fails

        Example:
            >>> mtf = provider.fetch_mtf_instruments()
            >>> len(mtf)  # Typically 300-500 MTF-eligible stocks
            450
        """
        instruments = self._fetch_gzip_json(MTF_INSTRUMENTS_URL)
        # MTF list contains only equity instruments eligible for margin trading
        return instruments

    def refresh_trading_universe(self) -> InstrumentFetchResult:
        """
        Refresh the trading universe with NSE EQ and MTF instruments.

        Returns:
            InstrumentFetchResult with counts and status.
        """
        try:
            # Fetch NSE equity instruments
            nse_eq = self.fetch_nse_equity()
            nse_eq_symbols = {inst.get("trading_symbol") for inst in nse_eq}

            # Fetch MTF instruments
            mtf_instruments = self.fetch_mtf_instruments()
            mtf_symbols = {inst.get("trading_symbol") for inst in mtf_instruments}

            # Build universe: NSE EQ instruments that are also MTF eligible
            # This gives us liquid, margin-tradeable stocks
            universe_symbols = nse_eq_symbols & mtf_symbols

            # Mark all existing stocks as inactive first
            self.collection.update_many({}, {"$set": {"is_active": False}})

            # Upsert NSE EQ instruments
            nse_eq_count = 0
            for inst in nse_eq:
                symbol = inst.get("trading_symbol")
                if not symbol:
                    continue

                is_mtf = symbol in mtf_symbols
                doc = self._transform_to_stock_doc(inst, is_mtf=is_mtf)

                self.collection.update_one(
                    {"symbol": symbol},
                    {"$set": doc},
                    upsert=True,
                )
                nse_eq_count += 1

            # Ensure indexes
            self.collection.create_index("symbol", unique=True)
            self.collection.create_index("is_mtf")
            self.collection.create_index("is_active")
            self.collection.create_index("instrument_key")

            return InstrumentFetchResult(
                success=True,
                nse_eq_count=nse_eq_count,
                mtf_count=len(mtf_symbols),
                total_universe=len(universe_symbols),
            )

        except requests.RequestException as e:
            return InstrumentFetchResult(
                success=False,
                error=f"Network error: {e}",
            )
        except json.JSONDecodeError as e:
            return InstrumentFetchResult(
                success=False,
                error=f"JSON parse error: {e}",
            )
        except Exception as e:
            return InstrumentFetchResult(
                success=False,
                error=f"Unexpected error: {e}",
            )

    def get_mtf_universe(self) -> list[dict]:
        """Get all active MTF-eligible stocks.

        Returns:
            List of stock documents with is_mtf=True, sorted by symbol

        Example:
            >>> mtf_stocks = provider.get_mtf_universe()
            >>> all(stock["is_mtf"] for stock in mtf_stocks)
            True
            >>> mtf_stocks[0]["symbol"] < mtf_stocks[1]["symbol"]  # Sorted
            True
        """
        return list(
            self.collection.find(
                {"is_active": True, "is_mtf": True},
                {"_id": 0},
            ).sort("symbol", 1)
        )

    def get_universe_stats(self) -> dict:
        """Get statistics about the current universe.

        Returns:
            Dict with keys:
                - total_nse_eq: Total active NSE equity instruments
                - mtf_eligible: Number of MTF-eligible instruments
                - last_updated: Most recent update timestamp

        Example:
            >>> stats = provider.get_universe_stats()
            >>> stats.keys()
            dict_keys(['total_nse_eq', 'mtf_eligible', 'last_updated'])
            >>> stats['mtf_eligible'] <= stats['total_nse_eq']
            True
        """
        total = self.collection.count_documents({"is_active": True})
        mtf = self.collection.count_documents({"is_active": True, "is_mtf": True})

        # Get last update time
        latest = self.collection.find_one(
            {"is_active": True},
            {"last_updated": 1},
            sort=[("last_updated", -1)],
        )
        last_updated = latest.get("last_updated") if latest else None

        return {
            "total_nse_eq": total,
            "mtf_eligible": mtf,
            "last_updated": last_updated,
        }

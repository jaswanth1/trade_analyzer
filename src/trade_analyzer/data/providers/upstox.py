"""Upstox instruments data provider."""

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
    """Result of instrument fetch operation."""

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
    """Provider to fetch and store Upstox instruments."""

    def __init__(self, db: Database):
        self.db = db
        self.collection = db["stocks"]

    def _fetch_gzip_json(self, url: str) -> list[dict]:
        """Fetch and decompress gzipped JSON from URL."""
        response = requests.get(url, timeout=60)
        response.raise_for_status()

        with gzip.GzipFile(fileobj=BytesIO(response.content)) as f:
            data = json.load(f)

        return data if isinstance(data, list) else []

    def _filter_nse_equity(self, instruments: list[dict]) -> list[dict]:
        """Filter for NSE equity instruments only (no futures/options)."""
        return [
            inst
            for inst in instruments
            if inst.get("segment") == "NSE_EQ"
            and inst.get("instrument_type") == "EQ"
        ]

    def _transform_to_stock_doc(
        self, instrument: dict, is_mtf: bool = False
    ) -> dict:
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
            "last_updated": datetime.utcnow(),
        }

    def fetch_nse_equity(self) -> list[dict]:
        """Fetch NSE equity instruments."""
        instruments = self._fetch_gzip_json(NSE_INSTRUMENTS_URL)
        return self._filter_nse_equity(instruments)

    def fetch_mtf_instruments(self) -> list[dict]:
        """Fetch MTF instruments (already equity only)."""
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
        """Get all active MTF-eligible stocks."""
        return list(
            self.collection.find(
                {"is_active": True, "is_mtf": True},
                {"_id": 0},
            ).sort("symbol", 1)
        )

    def get_universe_stats(self) -> dict:
        """Get statistics about the current universe."""
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

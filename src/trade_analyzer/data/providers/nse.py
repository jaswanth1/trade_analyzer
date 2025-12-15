"""NSE data provider for Nifty indices constituents."""

import time
from dataclasses import dataclass
from datetime import datetime

import requests

# NSE requires browser-like headers
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

NSE_BASE_URL = "https://www.nseindia.com"


class NSESession:
    """Manages NSE session with cookies."""

    _session: requests.Session = None

    @classmethod
    def get(cls) -> requests.Session:
        if cls._session is None:
            cls._session = requests.Session()
            cls._session.headers.update(NSE_HEADERS)
            try:
                cls._session.get(NSE_BASE_URL, timeout=10)
            except Exception:
                pass
        return cls._session


def fetch_nifty_constituents(index_name: str = "NIFTY 500") -> set[str]:
    """
    Fetch constituents of a Nifty index.

    Args:
        index_name: "NIFTY 50", "NIFTY 100", "NIFTY 200", "NIFTY 500"

    Returns:
        Set of symbols in the index.
    """
    session = NSESession.get()
    symbols = set()

    try:
        url = f"{NSE_BASE_URL}/api/equity-stockIndices?index={index_name.replace(' ', '%20')}"
        response = session.get(url, timeout=15)

        if response.status_code == 200:
            data = response.json()
            for item in data.get("data", []):
                symbol = item.get("symbol", "")
                if symbol and symbol != index_name:
                    symbols.add(symbol)
    except Exception as e:
        print(f"Error fetching {index_name}: {e}")

    return symbols


@dataclass
class NiftyIndicesData:
    """Nifty indices constituents."""

    nifty_50: set[str]
    nifty_100: set[str]
    nifty_200: set[str]
    nifty_500: set[str]
    fetched_at: str

    @property
    def all_symbols(self) -> set[str]:
        return self.nifty_50 | self.nifty_100 | self.nifty_200 | self.nifty_500


def fetch_all_nifty_indices() -> NiftyIndicesData:
    """Fetch all Nifty indices constituents."""
    nifty_50 = fetch_nifty_constituents("NIFTY 50")
    time.sleep(0.3)
    nifty_100 = fetch_nifty_constituents("NIFTY 100")
    time.sleep(0.3)
    nifty_200 = fetch_nifty_constituents("NIFTY 200")
    time.sleep(0.3)
    nifty_500 = fetch_nifty_constituents("NIFTY 500")

    return NiftyIndicesData(
        nifty_50=nifty_50,
        nifty_100=nifty_100,
        nifty_200=nifty_200,
        nifty_500=nifty_500,
        fetched_at=datetime.utcnow().isoformat(),
    )

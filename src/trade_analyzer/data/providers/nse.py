"""NSE India Data Provider for Nifty Indices.

This module provides functionality to fetch constituent lists for major Nifty indices
directly from the NSE India website. The data is used to classify stocks by liquidity
tier and assign quality scores.

Data Source:
    - NSE India API: https://www.nseindia.com/api/equity-stockIndices

Rate Limits:
    - No official rate limits documented
    - NSE requires cookies from homepage visit before API access
    - Recommended: 0.3-0.5 second delay between requests
    - Max 10 requests per minute recommended

Available Indices:
    - NIFTY 50: Top 50 companies by market cap
    - NIFTY 100: Includes NIFTY 50 + Next 50
    - NIFTY 200: Top 200 companies
    - NIFTY 500: Top 500 companies (broad market)

Usage:
    Fetch constituents of a single index:

    >>> from trade_analyzer.data.providers.nse import fetch_nifty_constituents
    >>>
    >>> # Fetch Nifty 50 constituents
    >>> nifty50 = fetch_nifty_constituents("NIFTY 50")
    >>> print(f"Nifty 50 has {len(nifty50)} stocks")
    >>> "RELIANCE" in nifty50
    True

    Fetch all indices at once:

    >>> from trade_analyzer.data.providers.nse import fetch_all_nifty_indices
    >>>
    >>> indices = fetch_all_nifty_indices()
    >>> print(f"Nifty 50: {len(indices.nifty_50)} stocks")
    >>> print(f"Nifty 500: {len(indices.nifty_500)} stocks")
    >>> print(f"Total unique: {len(indices.all_symbols)} stocks")

Notes:
    - NSE blocks requests without proper headers and cookies
    - Session management is handled automatically via NSESession class
    - Returns empty set on failure to allow graceful degradation
    - Index names must match NSE's naming convention exactly
"""

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
    """Manages NSE session with cookies.

    NSE India requires an active session with cookies obtained from the homepage
    before allowing API access. This singleton class manages that session.

    Attributes:
        _session: Shared session instance with NSE cookies

    Example:
        >>> from trade_analyzer.data.providers.nse import NSESession
        >>> session = NSESession.get()
        >>> response = session.get("https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050")
        >>> response.status_code
        200
    """

    _session: requests.Session = None

    @classmethod
    def get(cls) -> requests.Session:
        """Get or create the shared NSE session.

        Returns:
            requests.Session with valid NSE cookies

        Example:
            >>> session = NSESession.get()
            >>> "nsit" in session.cookies  # NSE sets 'nsit' cookie
            True
        """
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
    """Nifty indices constituents.

    Container for constituent lists of all major Nifty indices.

    Attributes:
        nifty_50: Set of symbols in Nifty 50
        nifty_100: Set of symbols in Nifty 100
        nifty_200: Set of symbols in Nifty 200
        nifty_500: Set of symbols in Nifty 500
        fetched_at: ISO format timestamp of when data was fetched

    Example:
        >>> indices = NiftyIndicesData(
        ...     nifty_50={"RELIANCE", "TCS", "INFY"},
        ...     nifty_100={"RELIANCE", "TCS", "INFY", "WIPRO"},
        ...     nifty_200=set(),
        ...     nifty_500=set(),
        ...     fetched_at="2025-12-15T10:30:00"
        ... )
        >>> len(indices.nifty_50)
        3
        >>> "RELIANCE" in indices.all_symbols
        True
    """

    nifty_50: set[str]
    nifty_100: set[str]
    nifty_200: set[str]
    nifty_500: set[str]
    fetched_at: str

    @property
    def all_symbols(self) -> set[str]:
        """Get union of all symbols across all indices.

        Returns:
            Set of all unique symbols present in any index

        Example:
            >>> indices.all_symbols == indices.nifty_500  # Usually true
            True
        """
        return self.nifty_50 | self.nifty_100 | self.nifty_200 | self.nifty_500


def fetch_all_nifty_indices() -> NiftyIndicesData:
    """Fetch all Nifty indices constituents.

    Fetches Nifty 50, 100, 200, and 500 constituents with appropriate delays
    between requests to respect NSE rate limits.

    Returns:
        NiftyIndicesData with all index constituents

    Example:
        >>> indices = fetch_all_nifty_indices()
        >>> len(indices.nifty_50)
        50
        >>> len(indices.nifty_100)
        100
        >>> indices.nifty_50.issubset(indices.nifty_100)  # 50 is subset of 100
        True
        >>> indices.nifty_100.issubset(indices.nifty_500)  # 100 is subset of 500
        True
    """
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

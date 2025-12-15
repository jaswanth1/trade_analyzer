"""NSE Shareholding Pattern Provider for Phase 5.

Fetches institutional ownership data (FII/DII/Promoter) from NSE India.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class InstitutionalHolding:
    """Institutional holding data for a stock."""

    symbol: str
    # FII holdings
    fii_holding_pct: float = 0.0
    fii_net_30d: float = 0.0  # Net buying/selling in crores
    fii_trend: str = "neutral"  # "buying", "neutral", "selling"
    # DII holdings
    dii_holding_pct: float = 0.0
    # Combined
    total_institutional: float = 0.0
    # Promoter
    promoter_holding_pct: float = 0.0
    promoter_pledge_pct: float = 0.0
    # Public
    public_holding_pct: float = 0.0
    # Metadata
    fetched_at: datetime = None

    def __post_init__(self):
        if self.fetched_at is None:
            self.fetched_at = datetime.utcnow()


class NSEHoldingsProvider:
    """Provider for NSE shareholding pattern data."""

    NSE_BASE_URL = "https://www.nseindia.com"

    NSE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.nseindia.com/",
        "X-Requested-With": "XMLHttpRequest",
        "Connection": "keep-alive",
    }

    def __init__(self):
        """Initialize the NSE holdings provider."""
        self._session: Optional[requests.Session] = None
        self._cookies_set = False

    def _get_session(self) -> requests.Session:
        """Get or create a session with NSE cookies."""
        if self._session is None or not self._cookies_set:
            self._session = requests.Session()
            self._session.headers.update(self.NSE_HEADERS)

            # First request to get cookies
            try:
                self._session.get(
                    f"{self.NSE_BASE_URL}/get-quotes/equity",
                    timeout=10,
                )
                self._cookies_set = True
                time.sleep(0.5)  # Respect rate limits
            except requests.RequestException as e:
                logger.warning(f"Error initializing NSE session: {e}")

        return self._session

    def fetch_shareholding_pattern(self, symbol: str) -> Optional[InstitutionalHolding]:
        """
        Fetch shareholding pattern for a stock from NSE.

        Args:
            symbol: NSE stock symbol (e.g., "RELIANCE")

        Returns:
            InstitutionalHolding object or None on failure.
        """
        session = self._get_session()

        # URL for shareholding pattern
        url = f"{self.NSE_BASE_URL}/api/corporate-shareholding?index=equities&symbol={symbol}"

        try:
            response = session.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()

            if not data or "shareholding" not in data:
                logger.warning(f"No shareholding data for {symbol}")
                return None

            shareholding = data.get("shareholding", {})

            # Parse the shareholding data
            # NSE returns data in different formats, handle both
            promoter_pct = 0.0
            promoter_pledge = 0.0
            fii_pct = 0.0
            dii_pct = 0.0
            public_pct = 0.0

            # Try to extract from the nested structure
            if isinstance(shareholding, list):
                for category in shareholding:
                    category_name = category.get("category", "").lower()
                    pct = float(category.get("percentage", 0) or 0)

                    if "promoter" in category_name:
                        promoter_pct = pct
                        # Check for pledged shares
                        pledged = category.get("pledgedOrEncumbered", 0)
                        if pledged and promoter_pct > 0:
                            promoter_pledge = (float(pledged) / promoter_pct) * 100

                    elif "fii" in category_name or "foreign" in category_name:
                        fii_pct = pct

                    elif "dii" in category_name or "domestic" in category_name or "mutual" in category_name:
                        dii_pct = pct

                    elif "public" in category_name:
                        public_pct = pct

            elif isinstance(shareholding, dict):
                promoter_pct = float(shareholding.get("promoterHolding", 0) or 0)
                fii_pct = float(shareholding.get("fiiHolding", 0) or 0)
                dii_pct = float(shareholding.get("diiHolding", 0) or 0)
                public_pct = float(shareholding.get("publicHolding", 0) or 0)
                promoter_pledge = float(shareholding.get("promoterPledge", 0) or 0)

            total_institutional = fii_pct + dii_pct

            # Determine FII trend (simplified - ideally compare with previous quarter)
            # For now, we'll use neutral as default
            fii_trend = "neutral"

            return InstitutionalHolding(
                symbol=symbol,
                fii_holding_pct=round(fii_pct, 2),
                fii_net_30d=0.0,  # Would need historical data
                fii_trend=fii_trend,
                dii_holding_pct=round(dii_pct, 2),
                total_institutional=round(total_institutional, 2),
                promoter_holding_pct=round(promoter_pct, 2),
                promoter_pledge_pct=round(promoter_pledge, 2),
                public_holding_pct=round(public_pct, 2),
            )

        except requests.RequestException as e:
            logger.warning(f"Error fetching shareholding for {symbol}: {e}")
            return None
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Error parsing shareholding for {symbol}: {e}")
            return None

    def fetch_bulk_deals(self, symbol: str, days: int = 30) -> Optional[dict]:
        """
        Fetch recent bulk/block deals to estimate FII activity.

        Args:
            symbol: NSE stock symbol
            days: Lookback period in days

        Returns:
            Dict with deal summary or None.
        """
        session = self._get_session()

        url = f"{self.NSE_BASE_URL}/api/historical/bulk-deals?symbol={symbol}"

        try:
            response = session.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()

            if not data or "data" not in data:
                return None

            deals = data.get("data", [])

            # Summarize FII/FPI activity
            fii_buy = 0.0
            fii_sell = 0.0

            for deal in deals:
                client_name = deal.get("clientName", "").upper()
                deal_type = deal.get("buySell", "").upper()
                quantity = float(deal.get("quantity", 0) or 0)
                price = float(deal.get("price", 0) or 0)
                value = quantity * price / 10000000  # Convert to crores

                # Check if FII/FPI
                if any(
                    term in client_name
                    for term in ["FII", "FPI", "FOREIGN", "GOLDMAN", "MORGAN", "CITI"]
                ):
                    if deal_type == "BUY":
                        fii_buy += value
                    else:
                        fii_sell += value

            fii_net = fii_buy - fii_sell

            return {
                "fii_buy_cr": round(fii_buy, 2),
                "fii_sell_cr": round(fii_sell, 2),
                "fii_net_cr": round(fii_net, 2),
                "fii_trend": "buying" if fii_net > 0 else ("selling" if fii_net < 0 else "neutral"),
            }

        except requests.RequestException as e:
            logger.warning(f"Error fetching bulk deals for {symbol}: {e}")
            return None

    def calculate_holding_score(
        self, holding: InstitutionalHolding
    ) -> dict:
        """
        Calculate institutional holding score and qualification.

        Criteria:
        - FII + DII >= 35%
        - FII net buying >= 0 (not selling)
        - Promoter pledge <= 20%

        Args:
            holding: InstitutionalHolding object

        Returns:
            Dict with scores and qualification status.
        """
        # Institutional threshold: >= 35%
        passes_institutional_min = holding.total_institutional >= 35

        # FII trend: not selling (neutral or buying is OK)
        passes_fii_trend = holding.fii_trend != "selling"

        # Promoter pledge: <= 20%
        passes_pledge = holding.promoter_pledge_pct <= 20

        # Overall qualification
        qualifies = passes_institutional_min and passes_fii_trend and passes_pledge

        # Calculate a score (0-100)
        inst_score = min(100, (holding.total_institutional / 0.50) * 100)  # 50% = 100 score
        pledge_score = max(0, 100 - (holding.promoter_pledge_pct / 0.30) * 100)  # 30% = 0 score

        holding_score = inst_score * 0.7 + pledge_score * 0.3

        return {
            "symbol": holding.symbol,
            "fii_holding_pct": holding.fii_holding_pct,
            "dii_holding_pct": holding.dii_holding_pct,
            "total_institutional": holding.total_institutional,
            "fii_net_30d": holding.fii_net_30d,
            "fii_trend": holding.fii_trend,
            "promoter_holding_pct": holding.promoter_holding_pct,
            "promoter_pledge_pct": holding.promoter_pledge_pct,
            "public_holding_pct": holding.public_holding_pct,
            "passes_institutional_min": passes_institutional_min,
            "passes_fii_trend": passes_fii_trend,
            "passes_pledge": passes_pledge,
            "holding_score": round(holding_score, 2),
            "qualifies": qualifies,
            "fetched_at": holding.fetched_at.isoformat(),
        }

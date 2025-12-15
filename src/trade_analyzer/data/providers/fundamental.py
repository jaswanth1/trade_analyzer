"""Fundamental Data Provider for Phase 5.

This module provides fundamental analysis capabilities by integrating with
Financial Modeling Prep (FMP) API for comprehensive financial statements,
metrics, and valuation data.

Data Sources:
    - Financial Modeling Prep (FMP): https://financialmodelingprep.com/api/v3
      - Income statements (quarterly)
      - Balance sheets (quarterly)
      - Cash flow statements (quarterly)
      - Key financial metrics (ROE, ROCE, etc.)

    - Alpha Vantage (optional): https://www.alphavantage.co/query
      - Company overview data

Rate Limits:
    - FMP Free Tier: 250 requests/day
    - FMP Premium: 300 requests/minute
    - Alpha Vantage Free: 5 requests/minute, 500/day
    - Recommended: Cache results, batch requests

Symbol Format:
    - NSE stocks use .NS suffix (e.g., "RELIANCE.NS")
    - Automatic conversion handled by provider

Usage:
    Basic fundamental data fetching:

    >>> from trade_analyzer.data.providers.fundamental import FundamentalDataProvider
    >>>
    >>> # Initialize with API keys
    >>> provider = FundamentalDataProvider(
    ...     fmp_api_key="your_fmp_key",
    ...     av_api_key="your_av_key"
    ... )
    >>>
    >>> # Fetch comprehensive fundamental data
    >>> fund_data = provider.fetch_fundamental_data("RELIANCE")
    >>> if fund_data:
    ...     print(f"EPS QoQ Growth: {fund_data.eps_qoq_growth:.1f}%")
    ...     print(f"Revenue YoY Growth: {fund_data.revenue_yoy_growth:.1f}%")
    ...     print(f"ROCE: {fund_data.roce:.1f}%")
    ...     print(f"ROE: {fund_data.roe:.1f}%")
    ...     print(f"D/E: {fund_data.debt_equity:.2f}")
    >>>
    >>> # Calculate fundamental score
    >>> score = provider.calculate_fundamental_score(fund_data, sector="Energy")
    >>> print(f"Fundamental Score: {score['fundamental_score']:.1f}/100")
    >>> print(f"Passes {score['filters_passed']}/5 filters")
    >>> print(f"Qualifies: {score['qualifies']}")

    Individual statements:

    >>> # Fetch specific statements
    >>> income = provider.fetch_income_statement("TCS", limit=4)  # 4 quarters
    >>> balance = provider.fetch_balance_sheet("TCS", limit=2)
    >>> cash_flow = provider.fetch_cash_flow("TCS", limit=2)
    >>> metrics = provider.fetch_key_metrics("TCS", limit=2)

Scoring System:
    The fundamental score (0-100) is calculated as:
    - 30% Growth (EPS QoQ + Revenue YoY)
    - 25% Profitability (ROCE + ROE)
    - 20% Leverage (Debt/Equity ratio)
    - 15% Cash Flow (FCF Yield)
    - 10% Earnings Quality (Cash EPS vs Reported EPS)

    A stock qualifies if it passes at least 3 of 5 fundamental filters.

Notes:
    - Returns None gracefully on API failures
    - Handles different sector thresholds (financials vs non-financials)
    - All growth rates as percentages, returns as decimals
    - Requires at least 2 quarters of data for meaningful analysis
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class FundamentalData:
    """Fundamental data for a stock.

    Comprehensive fundamental metrics extracted from financial statements.

    Attributes:
        symbol: Stock symbol
        eps_current: Current quarter EPS
        eps_previous: Previous quarter EPS
        eps_qoq_growth: EPS quarter-over-quarter growth (%)
        revenue_current: Current quarter revenue
        revenue_previous: Previous year same quarter revenue
        revenue_yoy_growth: Revenue year-over-year growth (%)
        roce: Return on Capital Employed (%)
        roe: Return on Equity (%)
        debt_equity: Debt to Equity ratio
        total_debt: Total debt amount
        total_equity: Total shareholder equity
        opm_margin: Operating Profit Margin (%)
        opm_previous: Previous quarter OPM (%)
        opm_trend: Margin trend ("improving", "stable", "declining")
        operating_cash_flow: Operating cash flow
        capex: Capital expenditure
        free_cash_flow: Free cash flow (OCF - CapEx)
        fcf_yield: FCF Yield (FCF/Market Cap) (%)
        market_cap: Market capitalization
        cash_eps: Cash EPS (OCF per share)
        reported_eps: Reported EPS
        earnings_quality_score: Ratio of cash EPS to reported EPS
        fetched_at: Timestamp of fetch
        data_source: Data source identifier
    """

    symbol: str
    # Growth metrics
    eps_current: float = 0.0
    eps_previous: float = 0.0
    eps_qoq_growth: float = 0.0
    revenue_current: float = 0.0
    revenue_previous: float = 0.0
    revenue_yoy_growth: float = 0.0
    # Profitability metrics
    roce: float = 0.0
    roe: float = 0.0
    # Leverage
    debt_equity: float = 0.0
    total_debt: float = 0.0
    total_equity: float = 0.0
    # Margins
    opm_margin: float = 0.0
    opm_previous: float = 0.0
    opm_trend: str = "stable"  # "improving", "stable", "declining"
    # Cash flow
    operating_cash_flow: float = 0.0
    capex: float = 0.0
    free_cash_flow: float = 0.0
    fcf_yield: float = 0.0
    market_cap: float = 0.0
    # Earnings quality
    cash_eps: float = 0.0
    reported_eps: float = 0.0
    earnings_quality_score: float = 0.0
    # Metadata
    fetched_at: datetime = None
    data_source: str = "FMP"

    def __post_init__(self):
        if self.fetched_at is None:
            self.fetched_at = datetime.utcnow()


class FundamentalDataProvider:
    """Provider for fundamental data from FMP and Alpha Vantage APIs.

    Main provider for fetching and analyzing fundamental financial data.
    Integrates with FMP API for comprehensive financial statements and
    calculates multi-dimensional fundamental scores.

    Attributes:
        fmp_api_key: Financial Modeling Prep API key
        av_api_key: Alpha Vantage API key
        session: Requests session for API calls

    Example:
        >>> provider = FundamentalDataProvider("fmp_key", "av_key")
        >>> data = provider.fetch_fundamental_data("RELIANCE")
        >>> score = provider.calculate_fundamental_score(data, "Energy")
    """

    FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
    AV_BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, fmp_api_key: str, av_api_key: str):
        """
        Initialize the provider with API keys.

        Args:
            fmp_api_key: Financial Modeling Prep API key
            av_api_key: Alpha Vantage API key
        """
        self.fmp_api_key = fmp_api_key
        self.av_api_key = av_api_key
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

    def _convert_to_nse_symbol(self, symbol: str) -> str:
        """Convert internal symbol to NSE format for API calls.

        Args:
            symbol: Internal stock symbol (e.g., "RELIANCE")

        Returns:
            NSE format symbol with .NS suffix (e.g., "RELIANCE.NS")

        Example:
            >>> provider._convert_to_nse_symbol("RELIANCE")
            'RELIANCE.NS'
            >>> provider._convert_to_nse_symbol("TCS.NS")
            'TCS.NS'
        """
        # FMP uses .NS suffix for NSE stocks
        if not symbol.endswith(".NS"):
            return f"{symbol}.NS"
        return symbol

    def fetch_income_statement(self, symbol: str, limit: int = 4) -> Optional[list]:
        """
        Fetch quarterly income statements from FMP.

        Args:
            symbol: Stock symbol
            limit: Number of quarters to fetch

        Returns:
            List of income statement data or None on failure.
        """
        nse_symbol = self._convert_to_nse_symbol(symbol)
        url = f"{self.FMP_BASE_URL}/income-statement/{nse_symbol}"
        params = {"period": "quarter", "limit": limit, "apikey": self.fmp_api_key}

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, list) and len(data) > 0:
                return data
            return None

        except requests.RequestException as e:
            logger.warning(f"FMP income statement error for {symbol}: {e}")
            return None

    def fetch_balance_sheet(self, symbol: str, limit: int = 4) -> Optional[list]:
        """
        Fetch quarterly balance sheets from FMP.

        Args:
            symbol: Stock symbol
            limit: Number of quarters to fetch

        Returns:
            List of balance sheet data or None on failure.
        """
        nse_symbol = self._convert_to_nse_symbol(symbol)
        url = f"{self.FMP_BASE_URL}/balance-sheet-statement/{nse_symbol}"
        params = {"period": "quarter", "limit": limit, "apikey": self.fmp_api_key}

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, list) and len(data) > 0:
                return data
            return None

        except requests.RequestException as e:
            logger.warning(f"FMP balance sheet error for {symbol}: {e}")
            return None

    def fetch_cash_flow(self, symbol: str, limit: int = 4) -> Optional[list]:
        """
        Fetch quarterly cash flow statements from FMP.

        Args:
            symbol: Stock symbol
            limit: Number of quarters to fetch

        Returns:
            List of cash flow data or None on failure.
        """
        nse_symbol = self._convert_to_nse_symbol(symbol)
        url = f"{self.FMP_BASE_URL}/cash-flow-statement/{nse_symbol}"
        params = {"period": "quarter", "limit": limit, "apikey": self.fmp_api_key}

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, list) and len(data) > 0:
                return data
            return None

        except requests.RequestException as e:
            logger.warning(f"FMP cash flow error for {symbol}: {e}")
            return None

    def fetch_key_metrics(self, symbol: str, limit: int = 4) -> Optional[list]:
        """
        Fetch key financial metrics from FMP.

        Args:
            symbol: Stock symbol
            limit: Number of quarters to fetch

        Returns:
            List of key metrics or None on failure.
        """
        nse_symbol = self._convert_to_nse_symbol(symbol)
        url = f"{self.FMP_BASE_URL}/key-metrics/{nse_symbol}"
        params = {"period": "quarter", "limit": limit, "apikey": self.fmp_api_key}

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, list) and len(data) > 0:
                return data
            return None

        except requests.RequestException as e:
            logger.warning(f"FMP key metrics error for {symbol}: {e}")
            return None

    def fetch_alpha_vantage_overview(self, symbol: str) -> Optional[dict]:
        """
        Fetch company overview from Alpha Vantage.

        Args:
            symbol: Stock symbol

        Returns:
            Company overview dict or None on failure.
        """
        nse_symbol = self._convert_to_nse_symbol(symbol)
        params = {
            "function": "OVERVIEW",
            "symbol": nse_symbol,
            "apikey": self.av_api_key,
        }

        try:
            response = self.session.get(self.AV_BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Check for valid response (has Symbol field)
            if data.get("Symbol"):
                return data
            return None

        except requests.RequestException as e:
            logger.warning(f"Alpha Vantage overview error for {symbol}: {e}")
            return None

    def fetch_fundamental_data(self, symbol: str) -> Optional[FundamentalData]:
        """
        Fetch comprehensive fundamental data for a stock.

        Combines data from FMP income statement, balance sheet, cash flow,
        and key metrics to build a complete fundamental picture.

        Args:
            symbol: Stock symbol

        Returns:
            FundamentalData object or None if insufficient data.
        """
        # Fetch all data sources
        income = self.fetch_income_statement(symbol, limit=4)
        balance = self.fetch_balance_sheet(symbol, limit=2)
        cash_flow = self.fetch_cash_flow(symbol, limit=2)
        metrics = self.fetch_key_metrics(symbol, limit=2)

        # Need at least income statement
        if not income or len(income) < 2:
            logger.warning(f"Insufficient data for {symbol}")
            return None

        try:
            # Current and previous quarter income
            current_q = income[0]
            previous_q = income[1]

            # EPS growth (QoQ)
            eps_current = float(current_q.get("eps", 0) or 0)
            eps_previous = float(previous_q.get("eps", 0) or 0)
            eps_qoq_growth = (
                ((eps_current - eps_previous) / abs(eps_previous)) * 100
                if eps_previous != 0
                else 0
            )

            # Revenue growth (YoY - compare to same quarter last year)
            revenue_current = float(current_q.get("revenue", 0) or 0)
            # For YoY, we need Q4 (index 3) if available
            revenue_yoy = 0
            if len(income) >= 4:
                revenue_lastyear = float(income[3].get("revenue", 0) or 0)
                if revenue_lastyear > 0:
                    revenue_yoy = (
                        (revenue_current - revenue_lastyear) / revenue_lastyear
                    ) * 100
            else:
                # Fall back to QoQ
                revenue_previous = float(previous_q.get("revenue", 0) or 0)
                if revenue_previous > 0:
                    revenue_yoy = (
                        (revenue_current - revenue_previous) / revenue_previous
                    ) * 100

            # Operating profit margin
            operating_income = float(current_q.get("operatingIncome", 0) or 0)
            opm_current = (
                (operating_income / revenue_current) * 100 if revenue_current > 0 else 0
            )

            prev_operating_income = float(previous_q.get("operatingIncome", 0) or 0)
            prev_revenue = float(previous_q.get("revenue", 0) or 0)
            opm_previous = (
                (prev_operating_income / prev_revenue) * 100 if prev_revenue > 0 else 0
            )

            # OPM trend
            opm_change = opm_current - opm_previous
            if opm_change > 2:
                opm_trend = "improving"
            elif opm_change < -2:
                opm_trend = "declining"
            else:
                opm_trend = "stable"

            # Balance sheet metrics
            total_debt = 0
            total_equity = 0
            if balance and len(balance) > 0:
                current_bs = balance[0]
                total_debt = float(current_bs.get("totalDebt", 0) or 0)
                total_equity = float(
                    current_bs.get("totalStockholdersEquity", 0) or 0
                )

            debt_equity = total_debt / total_equity if total_equity > 0 else 0

            # Cash flow metrics
            operating_cf = 0
            capex = 0
            free_cf = 0
            if cash_flow and len(cash_flow) > 0:
                current_cf = cash_flow[0]
                operating_cf = float(
                    current_cf.get("operatingCashFlow", 0) or 0
                )
                capex = abs(float(current_cf.get("capitalExpenditure", 0) or 0))
                free_cf = float(current_cf.get("freeCashFlow", 0) or 0)

            # Key metrics (ROE, ROCE)
            roe = 0
            roce = 0
            market_cap = 0
            if metrics and len(metrics) > 0:
                current_metrics = metrics[0]
                roe = float(current_metrics.get("returnOnEquity", 0) or 0) * 100
                roce = (
                    float(current_metrics.get("returnOnCapitalEmployed", 0) or 0) * 100
                )
                market_cap = float(current_metrics.get("marketCap", 0) or 0)

            # FCF Yield
            fcf_yield = (free_cf / market_cap) * 100 if market_cap > 0 else 0

            # Cash EPS (Operating CF / Shares)
            shares = float(current_q.get("weightedAverageShsOut", 0) or 0)
            cash_eps = operating_cf / shares if shares > 0 else 0

            # Earnings quality score (cash_eps > reported_eps is good)
            if eps_current > 0:
                earnings_quality = min(100, (cash_eps / eps_current) * 100)
            else:
                earnings_quality = 50  # Neutral if no earnings

            return FundamentalData(
                symbol=symbol,
                eps_current=eps_current,
                eps_previous=eps_previous,
                eps_qoq_growth=eps_qoq_growth,
                revenue_current=revenue_current,
                revenue_previous=revenue_previous if len(income) < 4 else float(income[3].get("revenue", 0) or 0),
                revenue_yoy_growth=revenue_yoy,
                roce=roce,
                roe=roe,
                debt_equity=debt_equity,
                total_debt=total_debt,
                total_equity=total_equity,
                opm_margin=opm_current,
                opm_previous=opm_previous,
                opm_trend=opm_trend,
                operating_cash_flow=operating_cf,
                capex=capex,
                free_cash_flow=free_cf,
                fcf_yield=fcf_yield,
                market_cap=market_cap,
                cash_eps=cash_eps,
                reported_eps=eps_current,
                earnings_quality_score=earnings_quality,
                data_source="FMP",
            )

        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Error parsing fundamental data for {symbol}: {e}")
            return None

    def calculate_fundamental_score(
        self, data: FundamentalData, sector: str = "Unknown"
    ) -> dict:
        """
        Calculate multi-dimensional fundamental score (0-100).

        Formula:
        FUNDAMENTAL_SCORE = 30% × Growth + 25% × Profitability +
                           20% × Leverage + 15% × Cash_Flow +
                           10% × Earnings_Quality

        Args:
            data: FundamentalData object
            sector: Stock sector for industry-specific thresholds

        Returns:
            Dict with component scores and final score.
        """
        is_financial = sector in [
            "Banks",
            "NBFC",
            "Insurance",
            "Financial Services",
            "Finance",
        ]

        # === Growth Score (30%) ===
        # EPS QoQ growth: >= 5% is good
        eps_score = min(100, max(0, (data.eps_qoq_growth / 0.10) * 100))

        # Revenue YoY growth: >= 8% is good
        rev_score = min(100, max(0, (data.revenue_yoy_growth / 0.15) * 100))

        growth_score = (eps_score * 0.6 + rev_score * 0.4)

        passes_growth = data.eps_qoq_growth >= 5 and data.revenue_yoy_growth >= 8

        # === Profitability Score (25%) ===
        # ROCE: >= 18% is good (12% for financials)
        roce_threshold = 12 if is_financial else 18
        roce_score = min(100, max(0, (data.roce / (roce_threshold * 1.5)) * 100))

        # ROE: >= 20% is good
        roe_score = min(100, max(0, (data.roe / 0.30) * 100))

        profitability_score = (roce_score * 0.5 + roe_score * 0.5)

        passes_profitability = data.roce >= roce_threshold and data.roe >= 20

        # === Leverage Score (20%) ===
        # D/E: < 0.8 for non-financial, < 4.0 for financial
        de_threshold = 4.0 if is_financial else 0.8

        if data.debt_equity <= 0:
            leverage_score = 100  # No debt is great
        elif data.debt_equity < de_threshold:
            leverage_score = max(0, 100 - (data.debt_equity / de_threshold) * 100)
        else:
            leverage_score = max(0, 50 - ((data.debt_equity - de_threshold) / de_threshold) * 50)

        passes_leverage = data.debt_equity < de_threshold

        # === Cash Flow Score (15%) ===
        # FCF Yield: >= 4% is good
        if data.fcf_yield > 0:
            cash_flow_score = min(100, (data.fcf_yield / 0.08) * 100)
        else:
            cash_flow_score = max(0, 50 + data.fcf_yield * 10)  # Penalize negative

        passes_cash_flow = data.fcf_yield >= 4

        # === Earnings Quality Score (10%) ===
        # Cash EPS > Reported EPS indicates quality earnings
        quality_score = min(100, max(0, data.earnings_quality_score))

        passes_quality = data.cash_eps > data.reported_eps

        # === Composite Score ===
        fundamental_score = (
            0.30 * growth_score
            + 0.25 * profitability_score
            + 0.20 * leverage_score
            + 0.15 * cash_flow_score
            + 0.10 * quality_score
        )

        # Count filters passed
        filters_passed = sum(
            [
                passes_growth,
                passes_profitability,
                passes_leverage,
                passes_cash_flow,
                passes_quality,
            ]
        )

        # Qualify if at least 3/5 filters pass
        qualifies = filters_passed >= 3

        return {
            "symbol": data.symbol,
            "eps_qoq_growth": round(data.eps_qoq_growth, 2),
            "revenue_yoy_growth": round(data.revenue_yoy_growth, 2),
            "roce": round(data.roce, 2),
            "roe": round(data.roe, 2),
            "debt_equity": round(data.debt_equity, 2),
            "opm_margin": round(data.opm_margin, 2),
            "opm_trend": data.opm_trend,
            "fcf_yield": round(data.fcf_yield, 2),
            "cash_eps": round(data.cash_eps, 2),
            "reported_eps": round(data.reported_eps, 2),
            "market_cap": data.market_cap,
            "is_financial": is_financial,
            "growth_score": round(growth_score, 2),
            "profitability_score": round(profitability_score, 2),
            "leverage_score": round(leverage_score, 2),
            "cash_flow_score": round(cash_flow_score, 2),
            "earnings_quality_score": round(quality_score, 2),
            "fundamental_score": round(fundamental_score, 2),
            "passes_growth": passes_growth,
            "passes_profitability": passes_profitability,
            "passes_leverage": passes_leverage,
            "passes_cash_flow": passes_cash_flow,
            "passes_quality": passes_quality,
            "filters_passed": filters_passed,
            "qualifies": qualifies,
            "data_source": data.data_source,
        }

"""Market Data Provider for Historical OHLCV and Technical Indicators.

This module provides comprehensive market data functionality using free APIs,
primarily Yahoo Finance. It handles:
- Historical OHLCV (Open, High, Low, Close, Volume) data
- Technical indicator calculations (SMA, ATR, RSI, MACD, Bollinger Bands)
- Relative strength analysis vs benchmarks
- Weekly consistency metrics
- Volume and liquidity analysis
- Technical setup detection (Pullback, VCP, Retest, Gap-Fill)

Data Source:
    - Yahoo Finance API: https://query1.finance.yahoo.com/v8/finance/chart

Rate Limits:
    - Free API, no authentication required
    - Recommended: 1 request per second
    - Max 2000 requests per hour recommended
    - Failures handled gracefully with None returns

NSE Symbol Format:
    - Indian stocks: {SYMBOL}.NS (e.g., "RELIANCE.NS")
    - Nifty indices: ^NSEI (Nifty 50), ^CNX100 (Nifty 100), etc.

Usage:
    Basic OHLCV fetching:

    >>> from trade_analyzer.data.providers.market_data import MarketDataProvider
    >>>
    >>> provider = MarketDataProvider()
    >>>
    >>> # Fetch daily OHLCV for a stock
    >>> ohlcv = provider.fetch_ohlcv_yahoo("RELIANCE", days=365)
    >>> if ohlcv:
    ...     print(f"Fetched {len(ohlcv.data)} days of data")
    ...     print(f"Latest close: {ohlcv.data['close'].iloc[-1]}")
    >>>
    >>> # Calculate technical indicators
    >>> indicators = provider.calculate_indicators(ohlcv)
    >>> if indicators:
    ...     print(f"SMA 50: {indicators.sma_50}")
    ...     print(f"RSI 14: {indicators.rsi_14}")
    >>>
    >>> # Fetch Nifty 50 data
    >>> nifty = provider.fetch_nifty_ohlcv("NIFTY 50", days=365)

    Weekly consistency analysis:

    >>> # Fetch weekly data
    >>> weekly = provider.fetch_weekly_ohlcv("RELIANCE", weeks=60)
    >>> metrics = provider.calculate_weekly_consistency_metrics(weekly)
    >>> if metrics:
    ...     print(f"Positive weeks: {metrics['pos_pct_52w']}%")
    ...     print(f"Sharpe ratio: {metrics['sharpe_52w']}")

    Setup detection:

    >>> # Detect all technical setups
    >>> ohlcv = provider.fetch_ohlcv_yahoo("TCS", days=365)
    >>> setups = provider.detect_all_setups(ohlcv.data)
    >>> for setup in setups:
    ...     print(f"{setup['type']}: Confidence {setup['confidence']}%")

Notes:
    - All calculations require minimum data (typically 200 days for indicators)
    - Returns None gracefully on failures to allow pipeline continuation
    - Handles missing/invalid data with dropna()
    - All prices in INR for NSE stocks
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import requests

# Yahoo Finance for free historical data
YAHOO_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"


@dataclass
class OHLCVData:
    """Historical OHLCV data for a symbol.

    Container for historical price and volume data.

    Attributes:
        symbol: Stock symbol (without .NS suffix)
        data: DataFrame with columns: date, open, high, low, close, volume
        start_date: First date in the dataset
        end_date: Last date in the dataset
        fetched_at: Timestamp when data was fetched
    """

    symbol: str
    data: pd.DataFrame  # columns: date, open, high, low, close, volume
    start_date: datetime
    end_date: datetime
    fetched_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if self.data is not None and not self.data.empty:
            self.data = self.data.sort_values("date").reset_index(drop=True)


@dataclass
class TechnicalIndicators:
    """Technical indicators for a symbol.

    Calculated technical indicators from OHLCV data.

    Attributes:
        symbol: Stock symbol
        sma_20: 20-day simple moving average
        sma_50: 50-day simple moving average
        sma_200: 200-day simple moving average
        slope_sma_20: Normalized slope of 20-DMA (daily change %)
        slope_sma_50: Normalized slope of 50-DMA
        slope_sma_200: Normalized slope of 200-DMA
        atr_14: 14-day Average True Range
        rsi_14: 14-day Relative Strength Index
        avg_volume_20: 20-day average volume
        high_52w: 52-week high
        low_52w: 52-week low
        close: Current close price
        proximity_52w_high: Distance from 52w high (0-100, 100=at high)
        calculated_at: Timestamp of calculation
    """

    symbol: str
    sma_20: float
    sma_50: float
    sma_200: float
    slope_sma_20: float  # Normalized slope
    slope_sma_50: float
    slope_sma_200: float
    atr_14: float
    rsi_14: float
    avg_volume_20: float
    high_52w: float
    low_52w: float
    close: float
    proximity_52w_high: float  # 0-100 (100 = at 52w high)
    calculated_at: datetime = field(default_factory=datetime.utcnow)


class MarketDataProvider:
    """Provider for market data using free APIs.

    Main provider for fetching historical price data and calculating
    technical indicators and trading setups.

    This provider is stateless except for the requests session.
    All methods are safe to call concurrently.

    Example:
        >>> provider = MarketDataProvider()
        >>> ohlcv = provider.fetch_ohlcv_yahoo("RELIANCE")
        >>> indicators = provider.calculate_indicators(ohlcv)
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def fetch_ohlcv_yahoo(
        self,
        symbol: str,
        days: int = 365,
        exchange_suffix: str = ".NS",
    ) -> Optional[OHLCVData]:
        """
        Fetch historical OHLCV data from Yahoo Finance.

        Args:
            symbol: Stock symbol (e.g., "RELIANCE")
            days: Number of days of history (default 365 for 52 weeks)
            exchange_suffix: Exchange suffix (default ".NS" for NSE)

        Returns:
            OHLCVData with historical prices or None on failure.
        """
        yahoo_symbol = f"{symbol}{exchange_suffix}"
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # Yahoo Finance API parameters
        params = {
            "period1": int(start_date.timestamp()),
            "period2": int(end_date.timestamp()),
            "interval": "1d",
            "includeAdjustedClose": "true",
        }

        try:
            url = f"{YAHOO_BASE_URL}/{yahoo_symbol}"
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            chart = data.get("chart", {})
            result = chart.get("result", [])

            if not result:
                return None

            result = result[0]
            timestamps = result.get("timestamp", [])
            quotes = result.get("indicators", {}).get("quote", [{}])[0]

            if not timestamps or not quotes:
                return None

            df = pd.DataFrame({
                "date": pd.to_datetime(timestamps, unit="s"),
                "open": quotes.get("open", []),
                "high": quotes.get("high", []),
                "low": quotes.get("low", []),
                "close": quotes.get("close", []),
                "volume": quotes.get("volume", []),
            })

            # Remove rows with NaN values
            df = df.dropna()

            return OHLCVData(
                symbol=symbol,
                data=df,
                start_date=df["date"].min().to_pydatetime() if not df.empty else start_date,
                end_date=df["date"].max().to_pydatetime() if not df.empty else end_date,
            )

        except Exception:
            return None

    def fetch_nifty_ohlcv(self, index: str = "NIFTY 50", days: int = 365) -> Optional[OHLCVData]:
        """
        Fetch Nifty index OHLCV data.

        Args:
            index: Index name (e.g., "NIFTY 50", "NIFTY BANK")
            days: Number of days

        Returns:
            OHLCVData for the index.
        """
        # Yahoo Finance symbols for Indian indices
        index_symbols = {
            "NIFTY 50": "^NSEI",
            "NIFTY 100": "^CNX100",
            "NIFTY 500": "^CRSLDX",
            "NIFTY BANK": "^NSEBANK",
            "INDIA VIX": "^INDIAVIX",
        }

        yahoo_symbol = index_symbols.get(index, "^NSEI")

        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            params = {
                "period1": int(start_date.timestamp()),
                "period2": int(end_date.timestamp()),
                "interval": "1d",
                "includeAdjustedClose": "true",
            }

            url = f"{YAHOO_BASE_URL}/{yahoo_symbol}"
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            chart = data.get("chart", {})
            result = chart.get("result", [])

            if not result:
                return None

            result = result[0]
            timestamps = result.get("timestamp", [])
            quotes = result.get("indicators", {}).get("quote", [{}])[0]

            if not timestamps or not quotes:
                return None

            df = pd.DataFrame({
                "date": pd.to_datetime(timestamps, unit="s"),
                "open": quotes.get("open", []),
                "high": quotes.get("high", []),
                "low": quotes.get("low", []),
                "close": quotes.get("close", []),
                "volume": quotes.get("volume", []),
            })

            df = df.dropna()

            return OHLCVData(
                symbol=index,
                data=df,
                start_date=df["date"].min().to_pydatetime() if not df.empty else start_date,
                end_date=df["date"].max().to_pydatetime() if not df.empty else end_date,
            )

        except Exception:
            return None

    def calculate_indicators(self, ohlcv: OHLCVData) -> Optional[TechnicalIndicators]:
        """Calculate technical indicators from OHLCV data.

        Calculates all standard technical indicators used in the trading system.
        Requires at least 200 days of data for accurate calculations.

        Args:
            ohlcv: OHLCVData with historical prices

        Returns:
            TechnicalIndicators with calculated values, None if insufficient data

        Raises:
            None (returns None on failure for graceful degradation)

        Example:
            >>> ohlcv = provider.fetch_ohlcv_yahoo("TCS", days=365)
            >>> indicators = provider.calculate_indicators(ohlcv)
            >>> if indicators:
            ...     print(f"RSI: {indicators.rsi_14:.2f}")
            ...     print(f"52w high proximity: {indicators.proximity_52w_high:.1f}%")
        """
        df = ohlcv.data.copy()

        if df.empty or len(df) < 200:
            return None

        # Simple Moving Averages
        df["sma_20"] = df["close"].rolling(window=20).mean()
        df["sma_50"] = df["close"].rolling(window=50).mean()
        df["sma_200"] = df["close"].rolling(window=200).mean()

        # SMA Slopes (normalized: change per day as percentage)
        df["slope_sma_20"] = df["sma_20"].diff(20) / df["sma_20"].shift(20) / 20
        df["slope_sma_50"] = df["sma_50"].diff(50) / df["sma_50"].shift(50) / 50
        df["slope_sma_200"] = df["sma_200"].diff(200) / df["sma_200"].shift(200) / 200

        # ATR (Average True Range)
        df["tr"] = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        df["atr_14"] = df["tr"].rolling(window=14).mean()

        # RSI
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, float("inf"))
        df["rsi_14"] = 100 - (100 / (1 + rs))

        # Average Volume
        df["avg_volume_20"] = df["volume"].rolling(window=20).mean()

        # 52-week High/Low
        high_52w = df["high"].rolling(window=252).max().iloc[-1]
        low_52w = df["low"].rolling(window=252).min().iloc[-1]
        close = df["close"].iloc[-1]

        # Proximity to 52-week high (0-100 scale, 100 = at high)
        if high_52w > low_52w:
            proximity = ((close - low_52w) / (high_52w - low_52w)) * 100
        else:
            proximity = 50.0

        latest = df.iloc[-1]

        return TechnicalIndicators(
            symbol=ohlcv.symbol,
            sma_20=latest["sma_20"],
            sma_50=latest["sma_50"],
            sma_200=latest["sma_200"],
            slope_sma_20=latest["slope_sma_20"],
            slope_sma_50=latest["slope_sma_50"],
            slope_sma_200=latest["slope_sma_200"],
            atr_14=latest["atr_14"],
            rsi_14=latest["rsi_14"],
            avg_volume_20=latest["avg_volume_20"],
            high_52w=high_52w,
            low_52w=low_52w,
            close=close,
            proximity_52w_high=proximity,
        )

    def calculate_relative_strength(
        self,
        stock_df: pd.DataFrame,
        benchmark_df: pd.DataFrame,
        periods: list[int] = None,
    ) -> dict[str, float]:
        """
        Calculate relative strength vs benchmark.

        Args:
            stock_df: Stock OHLCV DataFrame
            benchmark_df: Benchmark (e.g., Nifty 50) OHLCV DataFrame
            periods: List of periods in trading days (default: [21, 63, 126] = 1M, 3M, 6M)

        Returns:
            Dict with RS values for each period.
        """
        if periods is None:
            periods = [21, 63, 126]  # 1M, 3M, 6M in trading days

        rs = {}

        for period in periods:
            if len(stock_df) < period or len(benchmark_df) < period:
                rs[f"rs_{period}d"] = 0.0
                continue

            stock_return = (stock_df["close"].iloc[-1] / stock_df["close"].iloc[-period]) - 1
            bench_return = (benchmark_df["close"].iloc[-1] / benchmark_df["close"].iloc[-period]) - 1

            rs[f"rs_{period}d"] = (stock_return - bench_return) * 100  # As percentage points

        return rs

    def calculate_volatility_ratio(
        self,
        stock_df: pd.DataFrame,
        benchmark_df: pd.DataFrame,
        period: int = 20,
    ) -> float:
        """
        Calculate volatility ratio (stock vol / benchmark vol).

        Args:
            stock_df: Stock OHLCV DataFrame
            benchmark_df: Benchmark OHLCV DataFrame
            period: Period for volatility calculation (default 20 days)

        Returns:
            Volatility ratio (1.0 = same as benchmark)
        """
        if len(stock_df) < period or len(benchmark_df) < period:
            return 1.0

        stock_returns = stock_df["close"].pct_change().iloc[-period:]
        bench_returns = benchmark_df["close"].pct_change().iloc[-period:]

        stock_vol = stock_returns.std()
        bench_vol = bench_returns.std()

        if bench_vol == 0:
            return 1.0

        return stock_vol / bench_vol

    def fetch_weekly_ohlcv(
        self,
        symbol: str,
        weeks: int = 60,
        exchange_suffix: str = ".NS",
    ) -> Optional[pd.DataFrame]:
        """
        Fetch weekly OHLCV data from Yahoo Finance.

        Args:
            symbol: Stock symbol (e.g., "RELIANCE")
            weeks: Number of weeks of history (default 60 for 52+buffer)
            exchange_suffix: Exchange suffix (default ".NS" for NSE)

        Returns:
            DataFrame with weekly OHLCV and returns or None on failure.
        """
        yahoo_symbol = f"{symbol}{exchange_suffix}"
        end_date = datetime.now()
        start_date = end_date - timedelta(weeks=weeks + 2)  # Extra buffer

        params = {
            "period1": int(start_date.timestamp()),
            "period2": int(end_date.timestamp()),
            "interval": "1wk",
            "includeAdjustedClose": "true",
        }

        try:
            url = f"{YAHOO_BASE_URL}/{yahoo_symbol}"
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            chart = data.get("chart", {})
            result = chart.get("result", [])

            if not result:
                return None

            result = result[0]
            timestamps = result.get("timestamp", [])
            quotes = result.get("indicators", {}).get("quote", [{}])[0]

            if not timestamps or not quotes:
                return None

            df = pd.DataFrame({
                "date": pd.to_datetime(timestamps, unit="s"),
                "open": quotes.get("open", []),
                "high": quotes.get("high", []),
                "low": quotes.get("low", []),
                "close": quotes.get("close", []),
                "volume": quotes.get("volume", []),
            })

            # Remove rows with NaN values
            df = df.dropna()
            df = df.sort_values("date").reset_index(drop=True)

            # Calculate weekly returns
            df["weekly_return"] = df["close"].pct_change()

            return df

        except Exception:
            return None

    def calculate_weekly_consistency_metrics(
        self,
        weekly_df: pd.DataFrame,
        periods: list[int] = None,
    ) -> Optional[dict]:
        """
        Calculate weekly consistency metrics for multiple periods.

        Args:
            weekly_df: DataFrame with weekly OHLCV and weekly_return column
            periods: List of periods in weeks (default: [52, 26, 13])

        Returns:
            Dict with all consistency metrics or None on failure.
        """
        if periods is None:
            periods = [52, 26, 13]

        if weekly_df is None or weekly_df.empty:
            return None

        returns = weekly_df["weekly_return"].dropna()

        if len(returns) < max(periods):
            return None

        metrics = {}
        risk_free_weekly = 0.06 / 52  # 6% annual -> weekly

        for period in periods:
            recent = returns.tail(period)

            if len(recent) < period * 0.8:  # Need at least 80% of data
                continue

            # Core metrics
            pos_pct = (recent > 0).mean() * 100
            plus3_pct = (recent >= 0.03).mean() * 100
            plus5_pct = (recent >= 0.05).mean() * 100
            neg5_pct = (recent <= -0.05).mean() * 100
            avg_return = recent.mean()
            std_dev = recent.std()

            # Sharpe ratio (weekly)
            sharpe = (avg_return - risk_free_weekly) / std_dev if std_dev > 0 else 0

            # Best and worst weeks
            best_week = recent.max()
            worst_week = recent.min()

            # Win streak analysis
            positive_weeks = (recent > 0).astype(int)
            streaks = []
            current_streak = 0
            for val in positive_weeks:
                if val == 1:
                    current_streak += 1
                else:
                    if current_streak > 0:
                        streaks.append(current_streak)
                    current_streak = 0
            if current_streak > 0:
                streaks.append(current_streak)
            max_win_streak = max(streaks) if streaks else 0
            avg_win_streak = np.mean(streaks) if streaks else 0

            # Downside deviation (semi-deviation)
            negative_returns = recent[recent < 0]
            downside_dev = negative_returns.std() if len(negative_returns) > 0 else 0

            # Sortino ratio
            sortino = (avg_return - risk_free_weekly) / downside_dev if downside_dev > 0 else 0

            suffix = f"_{period}w"
            metrics.update({
                f"pos_pct{suffix}": round(pos_pct, 2),
                f"plus3_pct{suffix}": round(plus3_pct, 2),
                f"plus5_pct{suffix}": round(plus5_pct, 2),
                f"neg5_pct{suffix}": round(neg5_pct, 2),
                f"avg_return{suffix}": round(avg_return * 100, 4),  # As percentage
                f"std_dev{suffix}": round(std_dev * 100, 4),  # As percentage
                f"sharpe{suffix}": round(sharpe, 4),
                f"sortino{suffix}": round(sortino, 4),
                f"best_week{suffix}": round(best_week * 100, 2),
                f"worst_week{suffix}": round(worst_week * 100, 2),
                f"max_win_streak{suffix}": max_win_streak,
                f"avg_win_streak{suffix}": round(avg_win_streak, 2),
                f"downside_dev{suffix}": round(downside_dev * 100, 4),
            })

        return metrics if metrics else None

    def detect_market_regime(self, nifty_df: pd.DataFrame) -> str:
        """Detect market regime based on Nifty 50 position vs moving averages.

        Simplified regime detection using price vs moving averages.
        For production use, see the full regime module with breadth/VIX analysis.

        Args:
            nifty_df: Nifty 50 daily OHLCV DataFrame

        Returns:
            'BULL' if price > 50 DMA by 5%
            'BEAR' if price < 200 DMA
            'SIDEWAYS' otherwise

        Example:
            >>> nifty_data = provider.fetch_nifty_ohlcv("NIFTY 50")
            >>> regime = provider.detect_market_regime(nifty_data.data)
            >>> print(f"Current regime: {regime}")
        """
        if nifty_df is None or len(nifty_df) < 200:
            return "SIDEWAYS"

        close = nifty_df["close"].iloc[-1]
        sma_50 = nifty_df["close"].rolling(50).mean().iloc[-1]
        sma_200 = nifty_df["close"].rolling(200).mean().iloc[-1]

        # Bull: Above 50 DMA by more than 5%
        if close > sma_50 * 1.05:
            return "BULL"
        # Bear: Below 200 DMA
        elif close < sma_200:
            return "BEAR"
        # Sideways: Between
        else:
            return "SIDEWAYS"

    def get_regime_thresholds(self, regime: str) -> dict:
        """
        Get dynamic thresholds based on market regime.

        Args:
            regime: 'BULL', 'SIDEWAYS', or 'BEAR'

        Returns:
            Dict with threshold values
        """
        thresholds = {
            "BULL": {
                "pos_pct_min": 60,
                "plus3_pct_min": 22,
                "plus3_pct_max": 40,
                "vol_max": 6.5,
                "sharpe_min": 0.12,
            },
            "SIDEWAYS": {
                "pos_pct_min": 65,
                "plus3_pct_min": 25,
                "plus3_pct_max": 35,
                "vol_max": 6.0,
                "sharpe_min": 0.15,
            },
            "BEAR": {
                "pos_pct_min": 70,
                "plus3_pct_min": 20,
                "plus3_pct_max": 30,
                "vol_max": 4.5,
                "sharpe_min": 0.18,
            },
        }
        return thresholds.get(regime, thresholds["SIDEWAYS"])

    # ========== Phase 4A: Volume & Liquidity Analysis ==========

    def calculate_volume_liquidity_metrics(
        self,
        df: pd.DataFrame,
        close_price: float = None,
    ) -> Optional[dict]:
        """
        Calculate comprehensive volume and liquidity metrics for Phase 4A.

        Args:
            df: OHLCV DataFrame with at least 90 days of data
            close_price: Current close price (if not in df)

        Returns:
            Dict with liquidity metrics or None on failure.
        """
        if df is None or len(df) < 60:
            return None

        # Turnover calculation (volume * close price in Crores)
        df["turnover"] = df["volume"] * df["close"] / 1e7  # In Crores

        # Multi-horizon turnover
        turnover_20d = df["turnover"].tail(20).mean()
        turnover_60d = df["turnover"].tail(60).mean()
        peak_turnover_30d = df["turnover"].tail(30).max()

        # Volume analysis
        avg_vol_20d = df["volume"].tail(20).mean()
        avg_vol_60d = df["volume"].tail(60).mean()
        recent_peak_vol_5d = df["volume"].tail(5).max()
        recent_peak_vol_10d = df["volume"].tail(10).max()

        # Volume ratios
        vol_ratio_5d = recent_peak_vol_5d / avg_vol_20d if avg_vol_20d > 0 else 0
        vol_ratio_10d = recent_peak_vol_10d / avg_vol_20d if avg_vol_20d > 0 else 0

        # Volume stability (coefficient of variation)
        vol_cv = df["volume"].tail(60).std() / avg_vol_60d if avg_vol_60d > 0 else 1
        vol_stability = max(0, 100 * (1 - min(vol_cv, 2) / 2))  # 0-100 scale

        # Pullback volume analysis (last 3 days vs 20d avg)
        recent_vol_3d = df["volume"].tail(3).mean()
        pullback_vol_ratio = recent_vol_3d / avg_vol_20d if avg_vol_20d > 0 else 1

        # Price change analysis for context
        returns_5d = (df["close"].iloc[-1] / df["close"].iloc[-5] - 1) * 100
        is_pullback = returns_5d < -2  # Price down >2%

        # Gap analysis (average gap %)
        df["gap_pct"] = ((df["open"] - df["close"].shift(1)) / df["close"].shift(1)).abs() * 100
        avg_gap = df["gap_pct"].tail(30).mean()
        max_gap_30d = df["gap_pct"].tail(30).max()

        # Calculate liquidity score (0-100)
        # 40% × Turnover_20D_norm + 30% × Turnover_60D_norm + 20% × Peak_norm + 10% × Stability
        turnover_20d_norm = min(100, turnover_20d / 10 * 100)  # 10 Cr = 100
        turnover_60d_norm = min(100, turnover_60d / 8 * 100)   # 8 Cr = 100
        peak_turnover_norm = min(100, peak_turnover_30d / 50 * 100)  # 50 Cr = 100

        liquidity_score = (
            0.40 * turnover_20d_norm +
            0.30 * turnover_60d_norm +
            0.20 * peak_turnover_norm +
            0.10 * vol_stability
        )

        return {
            "turnover_20d_cr": round(turnover_20d, 2),
            "turnover_60d_cr": round(turnover_60d, 2),
            "peak_turnover_30d_cr": round(peak_turnover_30d, 2),
            "avg_volume_20d": round(avg_vol_20d, 0),
            "avg_volume_60d": round(avg_vol_60d, 0),
            "vol_ratio_5d": round(vol_ratio_5d, 2),
            "vol_ratio_10d": round(vol_ratio_10d, 2),
            "vol_stability": round(vol_stability, 2),
            "pullback_vol_ratio": round(pullback_vol_ratio, 2),
            "is_pullback_day": is_pullback and pullback_vol_ratio <= 0.8,
            "avg_gap_pct": round(avg_gap, 2),
            "max_gap_30d_pct": round(max_gap_30d, 2),
            "liquidity_score": round(liquidity_score, 2),
        }

    def detect_circuit_hits(
        self,
        df: pd.DataFrame,
        circuit_limit: float = 0.05,
        lookback_days: int = 30,
    ) -> dict:
        """
        Detect circuit hits (5% limit hits) in recent history.

        Args:
            df: OHLCV DataFrame
            circuit_limit: Circuit limit threshold (default 5%)
            lookback_days: Number of days to look back

        Returns:
            Dict with circuit analysis.
        """
        if df is None or len(df) < lookback_days:
            return {"circuit_hits_30d": 0, "has_5pct_circuits": False, "max_daily_move": 0}

        recent = df.tail(lookback_days).copy()
        recent["daily_return"] = recent["close"].pct_change().abs()

        # Count days with moves >= circuit limit
        circuit_hits = (recent["daily_return"] >= circuit_limit).sum()
        max_daily_move = recent["daily_return"].max() * 100

        return {
            "circuit_hits_30d": int(circuit_hits),
            "has_5pct_circuits": circuit_hits > 0,
            "max_daily_move_pct": round(max_daily_move, 2),
        }

    # ========== Phase 4B: Technical Setup Detection ==========

    def calculate_setup_indicators(self, df: pd.DataFrame) -> Optional[dict]:
        """
        Calculate all indicators needed for setup detection.

        Args:
            df: OHLCV DataFrame with at least 200 days of data

        Returns:
            Dict with indicator values or None on failure.
        """
        if df is None or len(df) < 200:
            return None

        df = df.copy()

        # Moving averages
        df["sma_20"] = df["close"].rolling(20).mean()
        df["sma_50"] = df["close"].rolling(50).mean()
        df["sma_200"] = df["close"].rolling(200).mean()

        # EMA for MACD
        df["ema_12"] = df["close"].ewm(span=12, adjust=False).mean()
        df["ema_26"] = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"] = df["ema_12"] - df["ema_26"]
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        # RSI
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, float("inf"))
        df["rsi_14"] = 100 - (100 / (1 + rs))

        # ATR
        df["tr"] = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        df["atr_14"] = df["tr"].rolling(14).mean()
        df["atr_20"] = df["tr"].rolling(20).mean()

        # Bollinger Bands
        df["bb_mid"] = df["close"].rolling(20).mean()
        df["bb_std"] = df["close"].rolling(20).std()
        df["bb_upper"] = df["bb_mid"] + 2 * df["bb_std"]
        df["bb_lower"] = df["bb_mid"] - 2 * df["bb_std"]

        # Volume analysis
        df["vol_sma_20"] = df["volume"].rolling(20).mean()
        df["vol_ratio"] = df["volume"] / df["vol_sma_20"]

        # Swing highs/lows (5-bar)
        df["swing_high"] = df["high"].rolling(5, center=True).max()
        df["swing_low"] = df["low"].rolling(5, center=True).min()

        # 52-week high/low
        high_52w = df["high"].rolling(252).max().iloc[-1]
        low_52w = df["low"].rolling(252).min().iloc[-1]

        # Recent range analysis
        recent_20 = df.tail(20)
        recent_high = recent_20["high"].max()
        recent_low = recent_20["low"].min()
        recent_range_pct = (recent_high - recent_low) / recent_low * 100 if recent_low > 0 else 0

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        return {
            "close": latest["close"],
            "open": latest["open"],
            "high": latest["high"],
            "low": latest["low"],
            "volume": latest["volume"],
            "sma_20": latest["sma_20"],
            "sma_50": latest["sma_50"],
            "sma_200": latest["sma_200"],
            "macd": latest["macd"],
            "macd_signal": latest["macd_signal"],
            "macd_hist": latest["macd_hist"],
            "macd_hist_prev": prev["macd_hist"],
            "rsi_14": latest["rsi_14"],
            "atr_14": latest["atr_14"],
            "atr_20": latest["atr_20"],
            "bb_upper": latest["bb_upper"],
            "bb_lower": latest["bb_lower"],
            "vol_ratio": latest["vol_ratio"],
            "vol_sma_20": latest["vol_sma_20"],
            "high_52w": high_52w,
            "low_52w": low_52w,
            "recent_high_20d": recent_high,
            "recent_low_20d": recent_low,
            "recent_range_pct": recent_range_pct,
            "df": df,  # Keep for further analysis
        }

    def detect_pullback_setup(self, indicators: dict) -> Optional[dict]:
        """Detect Type A: Enhanced Trend Pullback setup.

        This is the primary setup type for the trading system. It identifies
        stocks pulling back to support in a confirmed uptrend with volume
        contraction.

        Criteria:
        1. Price >= 95% of 20/50-DMA (Dynamic support)
        2. Volume contraction: Last 3 days <= 70% of 20D avg
        3. RSI(14) 35-55 (oversold recovery zone)
        4. MACD histogram turning positive
        5. In uptrend (price > 50-DMA > 200-DMA)

        Args:
            indicators: Dict from calculate_setup_indicators()

        Returns:
            Setup dict with entry/stop/target levels, None if not detected

        Example:
            >>> indicators = provider.calculate_setup_indicators(df)
            >>> setup = provider.detect_pullback_setup(indicators)
            >>> if setup:
            ...     print(f"Entry: {setup['entry_low']}-{setup['entry_high']}")
            ...     print(f"Stop: {setup['stop']}, Target: {setup['target_1']}")
            ...     print(f"R:R = {setup['rr_ratio']:.2f}")
        """
        df = indicators.get("df")
        if df is None or len(df) < 50:
            return None

        close = indicators["close"]
        sma_20 = indicators["sma_20"]
        sma_50 = indicators["sma_50"]
        sma_200 = indicators["sma_200"]
        rsi = indicators["rsi_14"]
        atr = indicators["atr_14"]
        macd_hist = indicators["macd_hist"]
        macd_hist_prev = indicators["macd_hist_prev"]

        # Condition 1: Price near support (95-103% of 20-DMA or 50-DMA)
        near_20dma = 0.95 * sma_20 <= close <= 1.03 * sma_20
        near_50dma = 0.95 * sma_50 <= close <= 1.03 * sma_50
        near_support = near_20dma or near_50dma

        # Condition 2: Volume contraction
        recent_vol_3d = df["volume"].tail(3).mean()
        avg_vol_20d = df["volume"].tail(20).mean()
        vol_contraction = recent_vol_3d <= 0.70 * avg_vol_20d

        # Condition 3: RSI in oversold recovery zone
        rsi_in_zone = 35 <= rsi <= 55

        # Condition 4: MACD histogram turning positive
        macd_turning = macd_hist > macd_hist_prev and macd_hist > -0.5

        # Condition 5: Uptrend
        in_uptrend = close > sma_50 > sma_200

        # Check candlestick patterns (simplified hammer detection)
        latest = df.iloc[-1]
        body = abs(latest["close"] - latest["open"])
        total_range = latest["high"] - latest["low"]
        lower_shadow = min(latest["open"], latest["close"]) - latest["low"]
        is_hammer = total_range > 0 and body <= 0.3 * total_range and lower_shadow >= 2 * body

        # Score conditions
        conditions_met = sum([near_support, vol_contraction, rsi_in_zone, macd_turning, in_uptrend])

        if conditions_met >= 3 and (near_support or in_uptrend):
            # Calculate entry/stop/target
            support_level = min(sma_20, sma_50) if near_50dma else sma_20
            swing_low = df["low"].tail(10).min()
            entry = support_level
            stop = min(swing_low * 0.99, entry - 2 * atr)
            target_1 = entry + 2 * (entry - stop)  # 2R target
            target_2 = entry + 3 * (entry - stop)  # 3R target

            risk = entry - stop
            reward = target_1 - entry
            rr_ratio = reward / risk if risk > 0 else 0

            confidence = min(95, 60 + conditions_met * 7 + (10 if is_hammer else 0))

            return {
                "type": "PULLBACK",
                "entry_low": round(entry - 0.5 * atr, 2),
                "entry_high": round(entry + 0.5 * atr, 2),
                "stop": round(stop, 2),
                "target_1": round(target_1, 2),
                "target_2": round(target_2, 2),
                "rr_ratio": round(rr_ratio, 2),
                "confidence": confidence,
                "conditions_met": conditions_met,
                "near_support": near_support,
                "vol_contraction": vol_contraction,
                "rsi_in_zone": rsi_in_zone,
                "macd_turning": macd_turning,
                "in_uptrend": in_uptrend,
                "is_hammer": is_hammer,
            }

        return None

    def detect_vcp_breakout_setup(self, indicators: dict) -> Optional[dict]:
        """Detect Type B: Volatility Contraction Pattern (VCP) Breakout.

        Identifies consolidation patterns with contracting volatility that
        typically precede strong directional moves.

        Criteria:
        1. Range contraction: Recent range <= 12%
        2. Time consolidation: 21-40 days
        3. Declining volatility: ATR14 today < ATR14 21 days ago
        4. Breakout potential: Price near upper range

        Args:
            indicators: Dict from calculate_setup_indicators()

        Returns:
            Setup dict with entry/stop/target levels, None if not detected

        Example:
            >>> setup = provider.detect_vcp_breakout_setup(indicators)
            >>> if setup:
            ...     print(f"VCP detected: Range {setup['range_pct']:.1f}%")
            ...     print(f"Entry above: {setup['entry_high']}")
        """
        df = indicators.get("df")
        if df is None or len(df) < 60:
            return None

        close = indicators["close"]
        atr_14 = indicators["atr_14"]
        recent_range_pct = indicators["recent_range_pct"]
        recent_high = indicators["recent_high_20d"]
        recent_low = indicators["recent_low_20d"]
        high_52w = indicators["high_52w"]

        # Condition 1: Range contraction
        tight_range = recent_range_pct <= 12

        # Condition 2: Check for consolidation (price within 5% of 20-day range)
        range_mid = (recent_high + recent_low) / 2
        in_consolidation = abs(close - range_mid) / range_mid <= 0.05

        # Condition 3: Declining volatility
        atr_21d_ago = df["atr_14"].iloc[-21] if len(df) >= 21 else atr_14
        declining_vol = atr_14 < atr_21d_ago * 0.95

        # Condition 4: Near breakout (upper 30% of range)
        range_position = (close - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5
        near_breakout = range_position >= 0.70

        # Weekly range tightening (check last 4 weeks)
        weekly_ranges = []
        for i in range(4):
            week_start = -5 * (i + 1)
            week_end = -5 * i if i > 0 else None
            week_data = df.iloc[week_start:week_end] if week_end else df.iloc[week_start:]
            if len(week_data) > 0:
                w_range = (week_data["high"].max() - week_data["low"].min()) / week_data["low"].min() * 100
                weekly_ranges.append(w_range)

        tightening_range = len(weekly_ranges) >= 3 and weekly_ranges[0] <= weekly_ranges[2]

        conditions_met = sum([tight_range, in_consolidation, declining_vol, near_breakout, tightening_range])

        if conditions_met >= 3:
            # Calculate entry/stop/target
            entry = recent_high * 1.005  # Breakout entry
            stop = recent_low * 0.99
            target_1 = entry + 2 * (entry - stop)
            target_2 = min(high_52w, entry + 3 * (entry - stop))

            risk = entry - stop
            reward = target_1 - entry
            rr_ratio = reward / risk if risk > 0 else 0

            confidence = min(95, 55 + conditions_met * 8)

            return {
                "type": "VCP_BREAKOUT",
                "entry_low": round(recent_high, 2),
                "entry_high": round(entry, 2),
                "stop": round(stop, 2),
                "target_1": round(target_1, 2),
                "target_2": round(target_2, 2),
                "rr_ratio": round(rr_ratio, 2),
                "confidence": confidence,
                "conditions_met": conditions_met,
                "tight_range": tight_range,
                "range_pct": round(recent_range_pct, 2),
                "in_consolidation": in_consolidation,
                "declining_vol": declining_vol,
                "near_breakout": near_breakout,
                "tightening_range": tightening_range,
            }

        return None

    def detect_retest_setup(self, indicators: dict) -> Optional[dict]:
        """
        Detect Type C: Confirmed Breakout Retest (Role Reversal).

        Criteria:
        1. Recent breakout (last 2-3 weeks) with high volume
        2. Retest holding above breakout level
        3. Volume dry-up on retest
        4. Higher low formation

        Returns:
            Setup dict or None if not detected.
        """
        df = indicators.get("df")
        if df is None or len(df) < 30:
            return None

        close = indicators["close"]
        high_52w = indicators["high_52w"]

        # Look for breakout in last 15 days
        lookback_start = -20
        lookback_end = -5
        lookback_data = df.iloc[lookback_start:lookback_end]
        recent_data = df.tail(5)

        if len(lookback_data) < 10:
            return None

        # Find potential breakout level (high volume up day in lookback)
        lookback_data = lookback_data.copy()
        lookback_data["return"] = lookback_data["close"].pct_change()
        lookback_data["vol_spike"] = lookback_data["volume"] / df["volume"].rolling(20).mean()

        # Breakout day: >2% gain with >2x volume
        breakout_days = lookback_data[
            (lookback_data["return"] > 0.02) &
            (lookback_data["vol_spike"] > 2.0)
        ]

        if len(breakout_days) == 0:
            return None

        # Use the highest breakout day as reference
        breakout_day = breakout_days.iloc[-1]
        breakout_level = breakout_day["close"]

        # Condition 1: Breakout volume was high
        breakout_vol_high = breakout_day["vol_spike"] >= 2.5

        # Condition 2: Current price holding above breakout (within 3%)
        holding_above = close >= breakout_level * 0.97

        # Condition 3: Volume dry-up on retest
        recent_vol = recent_data["volume"].mean()
        breakout_vol = breakout_day["volume"]
        vol_dryup = recent_vol <= 0.6 * breakout_vol

        # Condition 4: Higher low formation
        recent_low = recent_data["low"].min()
        prior_low = df.iloc[-20:-10]["low"].min()
        higher_low = recent_low > prior_low

        conditions_met = sum([breakout_vol_high, holding_above, vol_dryup, higher_low])

        if conditions_met >= 3 and holding_above:
            entry = breakout_level * 1.01
            stop = recent_low * 0.99
            target_1 = entry + 2 * (entry - stop)
            target_2 = min(high_52w, entry + 3 * (entry - stop))

            risk = entry - stop
            reward = target_1 - entry
            rr_ratio = reward / risk if risk > 0 else 0

            confidence = min(95, 60 + conditions_met * 9)

            return {
                "type": "RETEST",
                "entry_low": round(breakout_level, 2),
                "entry_high": round(entry, 2),
                "stop": round(stop, 2),
                "target_1": round(target_1, 2),
                "target_2": round(target_2, 2),
                "rr_ratio": round(rr_ratio, 2),
                "confidence": confidence,
                "conditions_met": conditions_met,
                "breakout_level": round(breakout_level, 2),
                "breakout_vol_high": breakout_vol_high,
                "holding_above": holding_above,
                "vol_dryup": vol_dryup,
                "higher_low": higher_low,
            }

        return None

    def detect_gap_fill_setup(self, indicators: dict) -> Optional[dict]:
        """
        Detect Type D: Gap-Fill Continuation setup.

        Criteria:
        1. Recent gap up (0.5-2%) in uptrend
        2. Gap partially filled (50-75%)
        3. Volume expansion on gap day
        4. Gap above rising 20-DMA

        Returns:
            Setup dict or None if not detected.
        """
        df = indicators.get("df")
        if df is None or len(df) < 30:
            return None

        close = indicators["close"]
        sma_20 = indicators["sma_20"]
        sma_50 = indicators["sma_50"]

        # Look for gaps in last 10 days
        recent = df.tail(10).copy()
        recent["gap_pct"] = (recent["open"] - recent["close"].shift(1)) / recent["close"].shift(1) * 100

        # Find gap-up days (0.5-2%)
        gap_days = recent[(recent["gap_pct"] >= 0.5) & (recent["gap_pct"] <= 2.0)]

        if len(gap_days) == 0:
            return None

        gap_day = gap_days.iloc[-1]
        gap_idx = df.index.get_loc(gap_day.name)
        gap_open = gap_day["open"]
        gap_prev_close = df.iloc[gap_idx - 1]["close"]
        gap_size = gap_open - gap_prev_close

        # Gap fill analysis
        days_after_gap = df.iloc[gap_idx:]
        lowest_after_gap = days_after_gap["low"].min()
        gap_filled_pct = (gap_open - lowest_after_gap) / gap_size * 100 if gap_size > 0 else 0

        # Condition 1: Gap in uptrend
        gap_above_20dma = gap_open > df["close"].rolling(20).mean().iloc[gap_idx]

        # Condition 2: Gap partially filled (50-75%)
        partial_fill = 50 <= gap_filled_pct <= 75

        # Condition 3: Volume expansion on gap day
        avg_vol = df["volume"].rolling(20).mean().iloc[gap_idx]
        vol_expansion = gap_day["volume"] >= 1.8 * avg_vol

        # Condition 4: Currently above gap low
        holding_gap = close >= gap_prev_close

        # Condition 5: Uptrend
        in_uptrend = close > sma_20 > sma_50

        conditions_met = sum([gap_above_20dma, partial_fill, vol_expansion, holding_gap, in_uptrend])

        if conditions_met >= 3 and holding_gap:
            entry = gap_prev_close * 1.005
            stop = gap_prev_close * 0.98
            target_1 = gap_open + gap_size  # Gap extension
            target_2 = entry + 3 * (entry - stop)

            risk = entry - stop
            reward = target_1 - entry
            rr_ratio = reward / risk if risk > 0 else 0

            confidence = min(95, 55 + conditions_met * 8)

            return {
                "type": "GAP_FILL",
                "entry_low": round(gap_prev_close, 2),
                "entry_high": round(entry, 2),
                "stop": round(stop, 2),
                "target_1": round(target_1, 2),
                "target_2": round(target_2, 2),
                "rr_ratio": round(rr_ratio, 2),
                "confidence": confidence,
                "conditions_met": conditions_met,
                "gap_pct": round(gap_day["gap_pct"], 2),
                "gap_filled_pct": round(gap_filled_pct, 2),
                "gap_above_20dma": gap_above_20dma,
                "vol_expansion": vol_expansion,
                "holding_gap": holding_gap,
                "in_uptrend": in_uptrend,
            }

        return None

    def detect_all_setups(self, df: pd.DataFrame) -> list[dict]:
        """Detect all setup types for a stock.

        Runs all setup detection algorithms and returns any that qualify.
        A stock can have multiple setups simultaneously.

        Args:
            df: OHLCV DataFrame with at least 200 days

        Returns:
            List of setup dicts (can be empty if none detected)

        Example:
            >>> ohlcv = provider.fetch_ohlcv_yahoo("INFY", days=365)
            >>> setups = provider.detect_all_setups(ohlcv.data)
            >>> for setup in setups:
            ...     print(f"{setup['type']}: {setup['confidence']}% confidence")
            ...     print(f"  Entry: {setup['entry_low']}-{setup['entry_high']}")
            ...     print(f"  R:R: {setup['rr_ratio']:.2f}")
        """
        indicators = self.calculate_setup_indicators(df)
        if indicators is None:
            return []

        setups = []

        # Check each setup type
        pullback = self.detect_pullback_setup(indicators)
        if pullback:
            setups.append(pullback)

        vcp = self.detect_vcp_breakout_setup(indicators)
        if vcp:
            setups.append(vcp)

        retest = self.detect_retest_setup(indicators)
        if retest:
            setups.append(retest)

        gap_fill = self.detect_gap_fill_setup(indicators)
        if gap_fill:
            setups.append(gap_fill)

        return setups

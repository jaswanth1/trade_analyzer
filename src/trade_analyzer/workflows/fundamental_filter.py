"""Fundamental Data Refresh workflow.

This workflow runs MONTHLY to fetch and cache fundamental data for the universe.
It is NOT part of the weekly pipeline - fundamentals are applied in Phase 1
using cached data (no API calls).

Steps:
1. Fetches high-quality symbols from stocks collection
2. Fetches fundamental data from FMP/Alpha Vantage (with rate limiting)
3. Calculates multi-dimensional fundamental scores
4. Fetches institutional holdings from NSE
5. Saves results to MongoDB (fundamental_scores, institutional_holdings)

The weekly Phase 1 (UniverseSetupWorkflow) then applies fundamental filter
using this cached data.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from trade_analyzer.activities.fundamental import (
        calculate_fundamental_scores,
        fetch_fundamental_data_batch,
        fetch_institutional_holdings_batch,
        fetch_universe_for_fundamentals,
        save_fundamental_results,
    )


@dataclass
class FundamentalDataRefreshResult:
    """Result of fundamental data refresh workflow.

    This result contains statistics from the MONTHLY fundamental data refresh,
    NOT the weekly pipeline. The data refreshed here is cached and used by
    Phase 1 (UniverseSetupWorkflow) during weekly runs.

    Attributes:
        success: True if workflow completed without errors
        symbols_analyzed: Total stocks analyzed for fundamentals
        fundamental_saved: Fundamental scores saved to database
        fundamental_qualified: Stocks passing fundamental filters (>=60 score)
        holdings_saved: Institutional holdings data saved
        holdings_qualified: Stocks with sufficient institutional holding (>=35%)
        combined_qualified: Stocks passing both fundamental and institutional
        avg_fundamental_score: Average fundamental score (0-100)
        top_10: Top 10 stocks by fundamental score
        error: Error message if workflow failed, None otherwise
    """

    success: bool
    symbols_analyzed: int
    fundamental_saved: int
    fundamental_qualified: int
    holdings_saved: int
    holdings_qualified: int
    combined_qualified: int
    avg_fundamental_score: float
    top_10: list[dict]
    error: str | None = None


@workflow.defn
class FundamentalDataRefreshWorkflow:
    """
    MONTHLY workflow to refresh fundamental data for universe.

    This workflow fetches fundamental data from external APIs and caches it
    in MongoDB. It runs independently of the weekly pipeline (typically once
    a month after quarterly results).

    The weekly UniverseSetupWorkflow (Phase 1) applies fundamental filter
    using this cached data - no API calls during weekly runs.

    Scoring Formula:
    FUNDAMENTAL_SCORE = 30% × Growth + 25% × Profitability +
                        20% × Leverage + 15% × Cash_Flow +
                        10% × Earnings_Quality

    Qualification:
    - At least 3/5 fundamental filters must pass
    - Institutional holding >= 35%
    - Promoter pledge <= 20%
    """

    @workflow.run
    async def run(
        self,
        min_quality_score: float = 60.0,
        fetch_delay: float = 1.0,
    ) -> FundamentalDataRefreshResult:
        """
        Execute the fundamental data refresh workflow.

        Args:
            min_quality_score: Minimum quality score for stocks to analyze
            fetch_delay: Delay between API calls (respecting rate limits)
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info(
            "Starting Fundamental Data Refresh Workflow (Monthly)"
        )

        try:
            # Step 1: Get high-quality symbols from universe
            workflow.logger.info(
                f"Step 1: Fetching high-quality symbols (min_score={min_quality_score})..."
            )
            symbols = await workflow.execute_activity(
                fetch_universe_for_fundamentals,
                args=[min_quality_score],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Found {len(symbols)} high-quality symbols")

            if not symbols:
                return FundamentalDataRefreshResult(
                    success=True,
                    symbols_analyzed=0,
                    fundamental_saved=0,
                    fundamental_qualified=0,
                    holdings_saved=0,
                    holdings_qualified=0,
                    combined_qualified=0,
                    avg_fundamental_score=0,
                    top_10=[],
                    error="No high-quality symbols found. Run Universe Setup first.",
                )

            # Step 2: Fetch fundamental data from FMP
            # Longer timeout due to API rate limits (could take 30+ mins for 500+ stocks)
            workflow.logger.info("Step 2: Fetching fundamental data from FMP...")
            fundamental_data = await workflow.execute_activity(
                fetch_fundamental_data_batch,
                args=[symbols, fetch_delay],
                start_to_close_timeout=timedelta(minutes=60),
                retry_policy=retry_policy,
            )
            workflow.logger.info(
                f"Fetched fundamental data for {len(fundamental_data)} symbols"
            )

            if not fundamental_data:
                return FundamentalDataRefreshResult(
                    success=False,
                    symbols_analyzed=len(symbols),
                    fundamental_saved=0,
                    fundamental_qualified=0,
                    holdings_saved=0,
                    holdings_qualified=0,
                    combined_qualified=0,
                    avg_fundamental_score=0,
                    top_10=[],
                    error="Failed to fetch fundamental data. Check FMP API key.",
                )

            # Step 3: Calculate fundamental scores
            workflow.logger.info("Step 3: Calculating fundamental scores...")
            fundamental_scores = await workflow.execute_activity(
                calculate_fundamental_scores,
                args=[fundamental_data],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )

            # Step 4: Fetch institutional holdings from NSE
            workflow.logger.info("Step 4: Fetching institutional holdings...")
            holdings = await workflow.execute_activity(
                fetch_institutional_holdings_batch,
                args=[symbols, 0.5],  # Faster delay for holdings
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=retry_policy,
            )

            # Step 5: Save results to MongoDB
            workflow.logger.info("Step 5: Saving results to database...")
            stats = await workflow.execute_activity(
                save_fundamental_results,
                args=[fundamental_scores, holdings],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Prepare top 10 for display
            top_10 = [
                {
                    "symbol": s["symbol"],
                    "fundamental_score": s.get("fundamental_score", 0),
                    "eps_growth": f"{s.get('eps_qoq_growth', 0):.1f}%",
                    "roce": f"{s.get('roce', 0):.1f}%",
                    "roe": f"{s.get('roe', 0):.1f}%",
                    "debt_equity": f"{s.get('debt_equity', 0):.2f}",
                    "filters_passed": s.get("filters_passed", 0),
                    "qualifies": s.get("qualifies", False),
                }
                for s in fundamental_scores[:10]
            ]

            workflow.logger.info(
                f"Fundamental Data Refresh complete: "
                f"{stats['fundamental_qualified']} fundamental, "
                f"{stats['holdings_qualified']} institutional, "
                f"{stats['combined_qualified']} combined qualified"
            )

            return FundamentalDataRefreshResult(
                success=True,
                symbols_analyzed=len(symbols),
                fundamental_saved=stats["fundamental_saved"],
                fundamental_qualified=stats["fundamental_qualified"],
                holdings_saved=stats["holdings_saved"],
                holdings_qualified=stats["holdings_qualified"],
                combined_qualified=stats["combined_qualified"],
                avg_fundamental_score=round(stats["avg_fundamental_score"], 1),
                top_10=top_10,
            )

        except Exception as e:
            workflow.logger.error(f"Fundamental Data Refresh failed: {e}")
            return FundamentalDataRefreshResult(
                success=False,
                symbols_analyzed=0,
                fundamental_saved=0,
                fundamental_qualified=0,
                holdings_saved=0,
                holdings_qualified=0,
                combined_qualified=0,
                avg_fundamental_score=0,
                top_10=[],
                error=str(e),
            )


# Keep old names as aliases for backward compatibility during transition
FundamentalFilterWorkflow = FundamentalDataRefreshWorkflow
FundamentalFilterResult = FundamentalDataRefreshResult

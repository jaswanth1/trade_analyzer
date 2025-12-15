"""Momentum filter workflow for Phase 2 - Enhanced Momentum & Trend Filters.

This module implements Phase 2 of the trading pipeline, which applies momentum
and trend filters to reduce the high-quality universe to momentum leaders.

Pipeline Position: Phase 2 - Momentum Filter
--------------------------------------------
Input: High-quality stocks (score >= 60) from Phase 1 (~450 stocks)
Output: Momentum-qualified stocks (~50-100 stocks)

This is the SECOND filter in the weekend pipeline, focusing on stocks
showing strong upward momentum and trend alignment.

Workflow Flow:
1. Fetch high-quality symbols from Phase 1 (quality_score >= 60)
2. Fetch Nifty 50 benchmark data for relative strength calculations
3. Fetch historical OHLCV data (batched with rate limiting)
4. Calculate momentum scores using 5 filters:
   - Filter 2A: 52-Week High Proximity (within 10%)
   - Filter 2B: Advanced MA System (5-layer: 10/20/50/100/200)
   - Filter 2C: Multi-Timeframe Relative Strength vs Nifty
   - Filter 2D: Composite Momentum Score
   - Filter 2E: Volatility-Adjusted Momentum
5. Save results to MongoDB momentum_scores collection

5-Filter System:
- Each filter is binary (pass/fail)
- Must pass ALL 5 filters to qualify
- Filters are designed to identify clean uptrends
- Stocks are ranked by momentum_score (0-100)

Typical Funnel:
~450 high-quality -> ~300 analyzed -> ~50-100 momentum-qualified

Inputs:
- batch_size: Number of stocks to fetch per API batch (default 100)

Outputs:
- MomentumFilterResult containing:
  - total_analyzed: Stocks analyzed
  - total_qualified: Stocks passing all 5 filters
  - avg_momentum_score: Average momentum score
  - top_10: Top 10 stocks by momentum score
  - nifty_return_3m: Nifty 50 3-month return for reference

Retry Policy:
- Initial interval: 2 seconds
- Maximum interval: 60 seconds
- Maximum attempts: 3
- Backoff coefficient: 2.0

Typical Runtime: 15-25 minutes (depends on batch size and API rate limits)

Related Workflows:
- UniverseSetupWorkflow (Phase 1): Provides input
- ConsistencyFilterWorkflow (Phase 3): Uses output
- UniverseAndMomentumWorkflow: Combined Phase 1+2 workflow
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from trade_analyzer.activities.momentum import (
        calculate_momentum_scores,
        fetch_market_data_batch,
        fetch_nifty_benchmark_data,
        save_momentum_results,
    )


@dataclass
class MomentumFilterResult:
    """Result of momentum filter workflow.

    Attributes:
        success: True if workflow completed without errors
        total_analyzed: Total stocks analyzed with market data
        total_qualified: Stocks passing all 5 momentum filters
        avg_momentum_score: Average momentum score across all analyzed stocks
        top_10: Top 10 stocks by momentum_score with key metrics
        nifty_return_3m: Nifty 50 3-month return for benchmark comparison
        error: Error message if workflow failed, None otherwise
    """

    success: bool
    total_analyzed: int
    total_qualified: int
    avg_momentum_score: float
    top_10: list[dict]  # Top 10 stocks by momentum score
    nifty_return_3m: float
    error: str | None = None


@workflow.defn
class MomentumFilterWorkflow:
    """Workflow to apply enhanced momentum filters (Phase 2).

    This workflow orchestrates momentum analysis by fetching market data
    in batches and applying 5 strict momentum filters to identify stocks
    in strong uptrends with institutional-grade momentum.

    Activities Orchestrated:
    1. fetch_high_quality_symbols: Gets stocks from Phase 1
    2. fetch_nifty_benchmark_data: Gets Nifty 50 data for RS calculations
    3. fetch_market_data_batch: Fetches OHLCV in batches with rate limiting
    4. calculate_momentum_scores: Applies 5 filters and scores stocks
    5. save_momentum_results: Saves to MongoDB momentum_scores collection

    5-Filter System:
    - Filter 2A: 52-Week High Proximity (close within 10% of 52W high)
    - Filter 2B: Advanced MA System (5/10/20/50/200 alignment + rising slopes)
    - Filter 2C: Multi-Timeframe RS (outperformance vs Nifty on 1M/3M/6M)
    - Filter 2D: Composite Momentum Score (>=70 combined score)
    - Filter 2E: Volatility-Adjusted Momentum (high return, low volatility)

    All 5 filters must pass for qualification. Stocks are then ranked by
    momentum_score (0-100) for priority in next phases.

    Error Handling:
    - Batched fetching with retries for API resilience
    - Continues processing even if some stocks fail
    - Returns partial results with error flag

    Returns:
        MomentumFilterResult with qualified stocks and statistics
    """

    @workflow.run
    async def run(self, batch_size: int = 100) -> MomentumFilterResult:
        """
        Execute the momentum filter workflow.

        Args:
            batch_size: Number of stocks to fetch per batch (default 100)
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting Momentum Filter Workflow (Phase 2)")

        try:
            # Step 1: Get high-quality stocks from universe
            workflow.logger.info("Step 1: Fetching high-quality universe...")
            symbols = await workflow.execute_activity(
                "fetch_high_quality_symbols",
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Found {len(symbols)} high-quality stocks to analyze")

            if not symbols:
                return MomentumFilterResult(
                    success=False,
                    total_analyzed=0,
                    total_qualified=0,
                    avg_momentum_score=0,
                    top_10=[],
                    nifty_return_3m=0,
                    error="No high-quality stocks found. Run Universe Setup first.",
                )

            # Step 2: Fetch Nifty benchmark data
            workflow.logger.info("Step 2: Fetching Nifty 50 benchmark data...")
            nifty_data = await workflow.execute_activity(
                fetch_nifty_benchmark_data,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            if not nifty_data:
                return MomentumFilterResult(
                    success=False,
                    total_analyzed=0,
                    total_qualified=0,
                    avg_momentum_score=0,
                    top_10=[],
                    nifty_return_3m=0,
                    error="Failed to fetch Nifty benchmark data",
                )

            # Step 3: Fetch market data in batches
            workflow.logger.info("Step 3: Fetching historical OHLCV data...")
            all_market_data = {}

            for i in range(0, len(symbols), batch_size):
                batch = symbols[i : i + batch_size]
                workflow.logger.info(
                    f"Fetching batch {i // batch_size + 1} ({len(batch)} symbols)..."
                )

                batch_data = await workflow.execute_activity(
                    fetch_market_data_batch,
                    args=[batch, 0.3],  # 0.3s delay between API calls
                    start_to_close_timeout=timedelta(minutes=15),
                    retry_policy=retry_policy,
                )

                all_market_data.update(batch_data)
                workflow.logger.info(
                    f"Fetched {len(all_market_data)}/{len(symbols)} symbols"
                )

            workflow.logger.info(f"Fetched market data for {len(all_market_data)} stocks")

            # Step 4: Calculate momentum scores
            workflow.logger.info("Step 4: Calculating momentum scores and applying filters...")
            results = await workflow.execute_activity(
                calculate_momentum_scores,
                args=[all_market_data, nifty_data, symbols],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )

            workflow.logger.info(f"Calculated momentum for {len(results)} stocks")

            # Step 5: Save results
            workflow.logger.info("Step 5: Saving momentum results to database...")
            await workflow.execute_activity(
                save_momentum_results,
                args=[results, nifty_data.get("returns", {})],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Get top 10 for display
            top_10 = [
                {
                    "symbol": r["symbol"],
                    "momentum_score": r["momentum_score"],
                    "filters_passed": r["filters_passed"],
                    "proximity_52w": r["proximity_52w"],
                    "rs_3m": r["rs_3m"],
                    "qualifies": r["qualifies"],
                }
                for r in results[:10]
            ]

            qualified_count = sum(1 for r in results if r["qualifies"])
            avg_score = sum(r["momentum_score"] for r in results) / len(results) if results else 0

            workflow.logger.info(
                f"Momentum Filter complete: {len(results)} analyzed, "
                f"{qualified_count} qualified, avg score {avg_score:.1f}"
            )

            return MomentumFilterResult(
                success=True,
                total_analyzed=len(results),
                total_qualified=qualified_count,
                avg_momentum_score=round(avg_score, 2),
                top_10=top_10,
                nifty_return_3m=nifty_data.get("returns", {}).get("return_3m", 0),
            )

        except Exception as e:
            workflow.logger.error(f"Momentum Filter failed: {e}")
            return MomentumFilterResult(
                success=False,
                total_analyzed=0,
                total_qualified=0,
                avg_momentum_score=0,
                top_10=[],
                nifty_return_3m=0,
                error=str(e),
            )


@dataclass
class CombinedUniverseFilterResult:
    """Result of combined universe + momentum filter workflow.

    This result combines Phase 1 and Phase 2 statistics for the
    UniverseAndMomentumWorkflow, which runs both phases sequentially.

    Attributes:
        success: True if both phases completed without errors
        total_nse_eq: Total NSE EQ instruments from Phase 1
        total_mtf: Total MTF instruments from Phase 1
        high_quality_count: High-quality stocks from Phase 1 (score >= 60)
        momentum_analyzed: Stocks analyzed in Phase 2
        momentum_qualified: Stocks passing all 5 momentum filters
        avg_momentum_score: Average momentum score from Phase 2
        top_10: Top 10 stocks by momentum score
        nifty_return_3m: Nifty 50 3-month return
        error: Error message if either phase failed, None otherwise
    """

    success: bool
    # Universe stats
    total_nse_eq: int
    total_mtf: int
    high_quality_count: int
    # Momentum stats
    momentum_analyzed: int
    momentum_qualified: int
    avg_momentum_score: float
    top_10: list[dict]
    nifty_return_3m: float
    error: str | None = None


@workflow.defn
class UniverseAndMomentumWorkflow:
    """Combined workflow that runs Universe Setup + Momentum Filter (Phase 1-2).

    This workflow orchestrates the first two phases of the weekend pipeline
    as child workflows, producing momentum-qualified stocks ready for
    consistency filtering.

    Child Workflows:
    1. UniverseSetupWorkflow (Phase 1): Creates high-quality universe
    2. MomentumFilterWorkflow (Phase 2): Applies momentum filters

    The workflow runs Phase 1 first and only proceeds to Phase 2 if Phase 1
    succeeds. This ensures data dependencies are satisfied.

    Typical Funnel:
    ~2,400 NSE EQ -> ~450 high-quality -> ~50-100 momentum-qualified

    Error Handling:
    - If Phase 1 fails, Phase 2 is not executed
    - Returns combined result with error from failed phase
    - Successful phases still return their statistics

    Returns:
        CombinedUniverseFilterResult with statistics from both phases
    """

    @workflow.run
    async def run(self) -> CombinedUniverseFilterResult:
        """Execute combined universe + momentum workflow."""
        workflow.logger.info("Starting Combined Universe + Momentum Workflow")

        try:
            # Step 1: Run Universe Setup as child workflow
            workflow.logger.info("Phase 1: Running Universe Setup...")

            from trade_analyzer.workflows.universe_setup import UniverseSetupWorkflow

            universe_result = await workflow.execute_child_workflow(
                UniverseSetupWorkflow.run,
                id=f"universe-setup-{workflow.info().workflow_id}",
            )

            if not universe_result.success:
                return CombinedUniverseFilterResult(
                    success=False,
                    total_nse_eq=0,
                    total_mtf=0,
                    high_quality_count=0,
                    momentum_analyzed=0,
                    momentum_qualified=0,
                    avg_momentum_score=0,
                    top_10=[],
                    nifty_return_3m=0,
                    error=f"Universe Setup failed: {universe_result.error}",
                )

            workflow.logger.info(
                f"Universe Setup complete: {universe_result.high_quality_count} high-quality stocks"
            )

            # Step 2: Run Momentum Filter as child workflow
            workflow.logger.info("Phase 2: Running Momentum Filter...")

            momentum_result = await workflow.execute_child_workflow(
                MomentumFilterWorkflow.run,
                args=[100],  # batch_size
                id=f"momentum-filter-{workflow.info().workflow_id}",
            )

            if not momentum_result.success:
                return CombinedUniverseFilterResult(
                    success=False,
                    total_nse_eq=universe_result.total_nse_eq,
                    total_mtf=universe_result.total_mtf,
                    high_quality_count=universe_result.high_quality_count,
                    momentum_analyzed=0,
                    momentum_qualified=0,
                    avg_momentum_score=0,
                    top_10=[],
                    nifty_return_3m=0,
                    error=f"Momentum Filter failed: {momentum_result.error}",
                )

            workflow.logger.info(
                f"Momentum Filter complete: {momentum_result.total_qualified} stocks qualified"
            )

            return CombinedUniverseFilterResult(
                success=True,
                total_nse_eq=universe_result.total_nse_eq,
                total_mtf=universe_result.total_mtf,
                high_quality_count=universe_result.high_quality_count,
                momentum_analyzed=momentum_result.total_analyzed,
                momentum_qualified=momentum_result.total_qualified,
                avg_momentum_score=momentum_result.avg_momentum_score,
                top_10=momentum_result.top_10,
                nifty_return_3m=momentum_result.nifty_return_3m,
            )

        except Exception as e:
            workflow.logger.error(f"Combined workflow failed: {e}")
            return CombinedUniverseFilterResult(
                success=False,
                total_nse_eq=0,
                total_mtf=0,
                high_quality_count=0,
                momentum_analyzed=0,
                momentum_qualified=0,
                avg_momentum_score=0,
                top_10=[],
                nifty_return_3m=0,
                error=str(e),
            )

"""Momentum filter workflow for Phase 2 - Enhanced Momentum & Trend Filters.

This workflow:
1. Fetches high-quality stocks from universe (score >= 60)
2. Fetches Nifty 50 benchmark data
3. Fetches historical OHLCV for all stocks (batched)
4. Calculates momentum scores and applies 5 filters
5. Saves results to MongoDB
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
    """Result of momentum filter workflow."""

    success: bool
    total_analyzed: int
    total_qualified: int
    avg_momentum_score: float
    top_10: list[dict]  # Top 10 stocks by momentum score
    nifty_return_3m: float
    error: str | None = None


@workflow.defn
class MomentumFilterWorkflow:
    """
    Workflow to apply enhanced momentum filters to the trading universe.

    Phase 2 Implementation:
    - Filter 2A: 52-Week High Proximity
    - Filter 2B: Advanced MA System (5-layer)
    - Filter 2C: Multi-Timeframe Relative Strength
    - Filter 2D: Composite Momentum Score
    - Filter 2E: Volatility-Adjusted Momentum

    Reduces ~300-500 stocks to 50-100 high-momentum candidates.
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
    """Result of combined universe + momentum filter workflow."""

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
    """
    Combined workflow that runs Universe Setup followed by Momentum Filter.

    This is the main weekend workflow for Phase 2:
    1. Refreshes universe (NSE EQ + MTF + Nifty indices)
    2. Enriches with quality scores
    3. Applies momentum filters to high-quality stocks
    4. Produces 50-100 high-momentum candidates
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

"""Consistency filter workflow for Phase 3 - Weekly Return Consistency Engine.

This module implements Phase 3 of the trading pipeline, which applies weekly
return consistency filters to identify stocks with sustainable, predictable
performance patterns.

Pipeline Position: Phase 3 - Consistency Filter
-----------------------------------------------
Input: Momentum-qualified stocks from Phase 2 (~50-100 stocks)
Output: Consistency-qualified stocks (~30-50 stocks)

This is the THIRD filter focusing on weekly return patterns with regime-aware
thresholds to ensure stocks perform consistently across market conditions.

Workflow Flow:
1. Fetch momentum-qualified symbols from Phase 2
2. Detect current market regime (BULL/SIDEWAYS/BEAR) using Nifty data
3. Fetch weekly OHLCV data (batched with rate limiting)
4. Calculate 9-metric consistency framework with regime-adjusted thresholds
5. Save results to MongoDB consistency_scores collection

9-Metric Consistency Framework:
- M1: Positive Weeks % (52W): >=65% in BULL, >=60% in SIDEWAYS, >=55% in BEAR
- M2: +3% Weeks % (52W): 25-35% (strong weeks)
- M3: Weekly Std Dev: <=6% in BULL, <=7% in SIDEWAYS/BEAR
- M4: Sharpe Ratio (52W): >=0.15 in BULL, >=0.10 in SIDEWAYS/BEAR
- M5: Consistency Score: >=65 (composite metric)
- M6: Regime Score: >=1.0 (13W vs 52W performance)
- M7: Max Drawdown: <=20%
- M8: Consecutive Loss Weeks: <=3
- M9: Recovery Speed: <5 weeks average

Regime Detection:
- BULL: Nifty above 200 DMA, upward trend, VIX < 20
- SIDEWAYS: Nifty choppy around 200 DMA, VIX 15-25
- BEAR: Nifty below 200 DMA, downward trend, VIX > 25

Typical Funnel:
~50-100 momentum -> ~70-90 analyzed -> ~30-50 consistency-qualified

Inputs:
- batch_size: Number of stocks to fetch per API batch (default 50)

Outputs:
- ConsistencyFilterResult containing:
  - total_analyzed: Stocks analyzed with weekly data
  - total_qualified: Stocks passing consistency filters
  - avg_final_score: Average final composite score
  - avg_consistency_score: Average consistency metric
  - market_regime: Detected regime (BULL/SIDEWAYS/BEAR)
  - top_10: Top 10 stocks by final score

Retry Policy:
- Initial interval: 2 seconds
- Maximum interval: 60 seconds
- Maximum attempts: 3
- Backoff coefficient: 2.0

Typical Runtime: 10-15 minutes

Related Workflows:
- MomentumFilterWorkflow (Phase 2): Provides input
- VolumeFilterWorkflow (Phase 4A): Uses output
- FullPipelineWorkflow: Orchestrates Phase 1-3
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from trade_analyzer.activities.consistency import (
        calculate_consistency_scores,
        detect_current_regime,
        fetch_momentum_qualified_symbols,
        fetch_weekly_data_batch,
        save_consistency_results,
    )


@dataclass
class ConsistencyFilterResult:
    """Result of consistency filter workflow.

    Attributes:
        success: True if workflow completed without errors
        total_analyzed: Total stocks analyzed with weekly data
        total_qualified: Stocks passing all consistency filters
        avg_final_score: Average final score (momentum × consistency)
        avg_consistency_score: Average consistency metric (0-100)
        market_regime: Detected regime (BULL/SIDEWAYS/BEAR)
        top_10: Top 10 stocks by final score with key metrics
        error: Error message if workflow failed, None otherwise
    """

    success: bool
    total_analyzed: int
    total_qualified: int
    avg_final_score: float
    avg_consistency_score: float
    market_regime: str
    top_10: list[dict]  # Top 10 stocks by final score
    error: str | None = None


@workflow.defn
class ConsistencyFilterWorkflow:
    """Workflow to apply weekly return consistency filters (Phase 3).

    This workflow orchestrates consistency analysis using regime-aware
    thresholds to identify stocks with predictable, sustainable performance
    patterns across different market conditions.

    Activities Orchestrated:
    1. fetch_momentum_qualified_symbols: Gets stocks from Phase 2
    2. detect_current_regime: Detects market regime for threshold adjustment
    3. fetch_weekly_data_batch: Fetches weekly OHLCV in batches
    4. calculate_consistency_scores: Applies 9-metric framework
    5. save_consistency_results: Saves to MongoDB consistency_scores collection

    9-Metric Consistency Framework:
    - M1: Positive Weeks % (52W): >=65% (regime-adjusted)
    - M2: +3% Weeks % (52W): 25-35% (strong weeks)
    - M3: Weekly Std Dev: <=6% (regime-adjusted)
    - M4: Sharpe Ratio: >=0.15 (regime-adjusted)
    - M5: Consistency Score: >=65 (composite metric)
    - M6: Regime Score: >=1.0 (13W vs 52W performance comparison)
    - M7: Max Drawdown: <=20%
    - M8: Consecutive Loss Weeks: <=3
    - M9: Recovery Speed: <5 weeks average

    Regime-Adaptive Thresholds:
    - BULL: Stricter thresholds (expect consistent gains)
    - SIDEWAYS: Moderate thresholds (accept choppiness)
    - BEAR: Relaxed thresholds (relative outperformance focus)

    Error Handling:
    - Batched fetching with retries for API resilience
    - Continues processing even if some stocks fail
    - Returns partial results with error flag

    Returns:
        ConsistencyFilterResult with qualified stocks and regime info
    """

    @workflow.run
    async def run(self, batch_size: int = 50) -> ConsistencyFilterResult:
        """
        Execute the consistency filter workflow.

        Args:
            batch_size: Number of stocks to fetch per batch (default 50)
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting Consistency Filter Workflow (Phase 3)")

        try:
            # Step 1: Get momentum-qualified symbols from Phase 2
            workflow.logger.info("Step 1: Fetching momentum-qualified symbols...")
            symbols = await workflow.execute_activity(
                fetch_momentum_qualified_symbols,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Found {len(symbols)} momentum-qualified stocks")

            if not symbols:
                return ConsistencyFilterResult(
                    success=False,
                    total_analyzed=0,
                    total_qualified=0,
                    avg_final_score=0,
                    avg_consistency_score=0,
                    market_regime="UNKNOWN",
                    top_10=[],
                    error="No momentum-qualified stocks found. Run Momentum Filter first.",
                )

            # Step 2: Detect current market regime
            workflow.logger.info("Step 2: Detecting market regime...")
            regime_info = await workflow.execute_activity(
                detect_current_regime,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Market regime: {regime_info.get('regime', 'UNKNOWN')}")

            # Step 3: Fetch weekly data in batches
            workflow.logger.info("Step 3: Fetching weekly OHLCV data...")
            all_weekly_data = {}

            for i in range(0, len(symbols), batch_size):
                batch = symbols[i : i + batch_size]
                workflow.logger.info(
                    f"Fetching batch {i // batch_size + 1} ({len(batch)} symbols)..."
                )

                batch_data = await workflow.execute_activity(
                    fetch_weekly_data_batch,
                    args=[batch, 0.3],  # 0.3s delay between API calls
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=retry_policy,
                )

                all_weekly_data.update(batch_data)
                workflow.logger.info(
                    f"Fetched {len(all_weekly_data)}/{len(symbols)} symbols"
                )

            workflow.logger.info(f"Fetched weekly data for {len(all_weekly_data)} stocks")

            # Step 4: Calculate consistency scores
            workflow.logger.info("Step 4: Calculating consistency scores...")
            results = await workflow.execute_activity(
                calculate_consistency_scores,
                args=[all_weekly_data, regime_info, symbols],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )

            workflow.logger.info(f"Calculated consistency for {len(results)} stocks")

            # Step 5: Save results
            workflow.logger.info("Step 5: Saving consistency results to database...")
            await workflow.execute_activity(
                save_consistency_results,
                args=[results, regime_info],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Get top 10 for display
            top_10 = [
                {
                    "symbol": r["symbol"],
                    "final_score": r["final_score"],
                    "consistency_score": r["consistency_score"],
                    "regime_score": r["regime_score"],
                    "pos_pct_52w": r["pos_pct_52w"],
                    "sharpe_52w": r["sharpe_52w"],
                    "filters_passed": r["filters_passed"],
                    "qualifies": r["qualifies"],
                }
                for r in results[:10]
            ]

            qualified_count = sum(1 for r in results if r["qualifies"])
            avg_final = sum(r["final_score"] for r in results) / len(results) if results else 0
            avg_cons = sum(r["consistency_score"] for r in results) / len(results) if results else 0

            workflow.logger.info(
                f"Consistency Filter complete: {len(results)} analyzed, "
                f"{qualified_count} qualified, avg final score {avg_final:.1f}"
            )

            return ConsistencyFilterResult(
                success=True,
                total_analyzed=len(results),
                total_qualified=qualified_count,
                avg_final_score=round(avg_final, 2),
                avg_consistency_score=round(avg_cons, 2),
                market_regime=regime_info.get("regime", "UNKNOWN"),
                top_10=top_10,
            )

        except Exception as e:
            workflow.logger.error(f"Consistency Filter failed: {e}")
            return ConsistencyFilterResult(
                success=False,
                total_analyzed=0,
                total_qualified=0,
                avg_final_score=0,
                avg_consistency_score=0,
                market_regime="UNKNOWN",
                top_10=[],
                error=str(e),
            )


@dataclass
class FullPipelineResult:
    """Result of full pipeline workflow (Universe + Momentum + Consistency)."""

    success: bool
    # Universe stats
    total_nse_eq: int
    high_quality_count: int
    # Momentum stats
    momentum_qualified: int
    # Consistency stats
    consistency_qualified: int
    avg_final_score: float
    market_regime: str
    top_10: list[dict]
    error: str | None = None


@workflow.defn
class FullPipelineWorkflow:
    """
    Full weekend pipeline: Universe + Momentum + Consistency.

    This is the complete Phase 1-3 workflow:
    1. UniverseSetupWorkflow: ~2400 NSE EQ -> ~1400 high-quality
    2. MomentumFilterWorkflow: ~1400 -> ~50-100 momentum-qualified
    3. ConsistencyFilterWorkflow: ~50-100 -> ~30-50 ultra-consistent
    """

    @workflow.run
    async def run(self) -> FullPipelineResult:
        """Execute full pipeline workflow."""
        workflow.logger.info("Starting Full Pipeline Workflow (Phase 1-3)")

        try:
            # Phase 1: Universe Setup
            workflow.logger.info("=== Phase 1: Universe Setup ===")

            from trade_analyzer.workflows.universe_setup import UniverseSetupWorkflow

            universe_result = await workflow.execute_child_workflow(
                UniverseSetupWorkflow.run,
                id=f"universe-setup-{workflow.info().workflow_id}",
            )

            if not universe_result.success:
                return FullPipelineResult(
                    success=False,
                    total_nse_eq=0,
                    high_quality_count=0,
                    momentum_qualified=0,
                    consistency_qualified=0,
                    avg_final_score=0,
                    market_regime="UNKNOWN",
                    top_10=[],
                    error=f"Universe Setup failed: {universe_result.error}",
                )

            workflow.logger.info(
                f"Universe Setup complete: {universe_result.high_quality_count} high-quality"
            )

            # Phase 2: Momentum Filter
            workflow.logger.info("=== Phase 2: Momentum Filter ===")

            from trade_analyzer.workflows.momentum_filter import MomentumFilterWorkflow

            momentum_result = await workflow.execute_child_workflow(
                MomentumFilterWorkflow.run,
                args=[100],
                id=f"momentum-filter-{workflow.info().workflow_id}",
            )

            if not momentum_result.success:
                return FullPipelineResult(
                    success=False,
                    total_nse_eq=universe_result.total_nse_eq,
                    high_quality_count=universe_result.high_quality_count,
                    momentum_qualified=0,
                    consistency_qualified=0,
                    avg_final_score=0,
                    market_regime="UNKNOWN",
                    top_10=[],
                    error=f"Momentum Filter failed: {momentum_result.error}",
                )

            workflow.logger.info(
                f"Momentum Filter complete: {momentum_result.total_qualified} qualified"
            )

            # Phase 3: Consistency Filter
            workflow.logger.info("=== Phase 3: Consistency Filter ===")

            consistency_result = await workflow.execute_child_workflow(
                ConsistencyFilterWorkflow.run,
                args=[50],
                id=f"consistency-filter-{workflow.info().workflow_id}",
            )

            if not consistency_result.success:
                return FullPipelineResult(
                    success=False,
                    total_nse_eq=universe_result.total_nse_eq,
                    high_quality_count=universe_result.high_quality_count,
                    momentum_qualified=momentum_result.total_qualified,
                    consistency_qualified=0,
                    avg_final_score=0,
                    market_regime="UNKNOWN",
                    top_10=[],
                    error=f"Consistency Filter failed: {consistency_result.error}",
                )

            workflow.logger.info(
                f"Consistency Filter complete: {consistency_result.total_qualified} qualified"
            )

            return FullPipelineResult(
                success=True,
                total_nse_eq=universe_result.total_nse_eq,
                high_quality_count=universe_result.high_quality_count,
                momentum_qualified=momentum_result.total_qualified,
                consistency_qualified=consistency_result.total_qualified,
                avg_final_score=consistency_result.avg_final_score,
                market_regime=consistency_result.market_regime,
                top_10=consistency_result.top_10,
            )

        except Exception as e:
            workflow.logger.error(f"Full Pipeline failed: {e}")
            return FullPipelineResult(
                success=False,
                total_nse_eq=0,
                high_quality_count=0,
                momentum_qualified=0,
                consistency_qualified=0,
                avg_final_score=0,
                market_regime="UNKNOWN",
                top_10=[],
                error=str(e),
            )

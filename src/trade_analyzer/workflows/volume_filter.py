"""Volume & Liquidity filter workflow for Phase 4A.

This workflow:
1. Fetches consistency-qualified stocks from Phase 3
2. Calculates volume & liquidity metrics
3. Filters by liquidity score, turnover, circuit hits
4. Saves results to MongoDB
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from trade_analyzer.activities.volume_liquidity import (
        calculate_volume_liquidity_batch,
        fetch_consistency_qualified_symbols,
        filter_by_liquidity,
        save_liquidity_results,
    )


@dataclass
class VolumeFilterResult:
    """Result of volume & liquidity filter workflow."""

    success: bool
    total_analyzed: int
    total_qualified: int
    avg_liquidity_score: float
    avg_turnover_20d: float
    top_10: list[dict]
    error: str | None = None


@workflow.defn
class VolumeFilterWorkflow:
    """
    Workflow to apply volume & liquidity filters (Phase 4A).

    Filters:
    1. Liquidity Score >= 75
    2. 20D Avg Turnover >= 10 Cr
    3. Circuit Hits (30D) <= 1
    4. Avg Gap <= 2%

    Reduces ~30-50 consistency stocks to 15-25 liquid candidates.
    """

    @workflow.run
    async def run(self, batch_size: int = 50) -> VolumeFilterResult:
        """
        Execute the volume & liquidity filter workflow.

        Args:
            batch_size: Number of stocks to fetch per batch
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting Volume & Liquidity Filter Workflow (Phase 4A)")

        try:
            # Step 1: Get consistency-qualified symbols from Phase 3
            workflow.logger.info("Step 1: Fetching consistency-qualified symbols...")
            symbols = await workflow.execute_activity(
                fetch_consistency_qualified_symbols,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Found {len(symbols)} consistency-qualified stocks")

            if not symbols:
                return VolumeFilterResult(
                    success=False,
                    total_analyzed=0,
                    total_qualified=0,
                    avg_liquidity_score=0,
                    avg_turnover_20d=0,
                    top_10=[],
                    error="No consistency-qualified stocks found. Run Consistency Filter first.",
                )

            # Step 2: Calculate volume/liquidity metrics in batches
            workflow.logger.info("Step 2: Calculating volume & liquidity metrics...")
            all_results = []

            for i in range(0, len(symbols), batch_size):
                batch = symbols[i : i + batch_size]
                workflow.logger.info(
                    f"Processing batch {i // batch_size + 1} ({len(batch)} symbols)..."
                )

                batch_results = await workflow.execute_activity(
                    calculate_volume_liquidity_batch,
                    args=[batch, 0.3],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=retry_policy,
                )

                all_results.extend(batch_results)
                workflow.logger.info(
                    f"Processed {len(all_results)}/{len(symbols)} symbols"
                )

            workflow.logger.info(f"Calculated metrics for {len(all_results)} stocks")

            # Step 3: Filter by liquidity criteria
            workflow.logger.info("Step 3: Filtering by liquidity criteria...")
            filtered_results = await workflow.execute_activity(
                filter_by_liquidity,
                args=[all_results, 75, 10, 1, 2.0],  # min_score, min_turnover, max_circuits, max_gap
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            workflow.logger.info(f"Filtered to {len(filtered_results)} liquid stocks")

            # Step 4: Save results
            workflow.logger.info("Step 4: Saving liquidity results to database...")
            await workflow.execute_activity(
                save_liquidity_results,
                args=[all_results],  # Save all results, not just filtered
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Get top 10 for display
            top_10 = [
                {
                    "symbol": r["symbol"],
                    "liquidity_score": r["liquidity_score"],
                    "turnover_20d_cr": r["turnover_20d_cr"],
                    "vol_ratio_5d": r.get("vol_ratio_5d", 0),
                    "circuit_hits_30d": r.get("circuit_hits_30d", 0),
                    "avg_gap_pct": r.get("avg_gap_pct", 0),
                    "liq_qualifies": r.get("liq_qualifies", False),
                }
                for r in filtered_results[:10]
            ]

            avg_liq = sum(r.get("liquidity_score", 0) for r in filtered_results) / len(filtered_results) if filtered_results else 0
            avg_turnover = sum(r.get("turnover_20d_cr", 0) for r in filtered_results) / len(filtered_results) if filtered_results else 0

            workflow.logger.info(
                f"Volume Filter complete: {len(all_results)} analyzed, "
                f"{len(filtered_results)} qualified, avg liquidity {avg_liq:.1f}"
            )

            return VolumeFilterResult(
                success=True,
                total_analyzed=len(all_results),
                total_qualified=len(filtered_results),
                avg_liquidity_score=round(avg_liq, 2),
                avg_turnover_20d=round(avg_turnover, 2),
                top_10=top_10,
            )

        except Exception as e:
            workflow.logger.error(f"Volume Filter failed: {e}")
            return VolumeFilterResult(
                success=False,
                total_analyzed=0,
                total_qualified=0,
                avg_liquidity_score=0,
                avg_turnover_20d=0,
                top_10=[],
                error=str(e),
            )

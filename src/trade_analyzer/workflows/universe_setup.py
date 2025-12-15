"""Universe setup workflow for high-quality trading universe."""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from trade_analyzer.activities.universe_setup import (
        BaseUniverseData,
        NiftyData,
        enrich_and_score_universe,
        fetch_base_universe,
        fetch_nifty_indices,
        save_enriched_universe,
    )


@dataclass
class UniverseSetupResult:
    """Result of universe setup workflow."""

    success: bool
    total_nse_eq: int
    total_mtf: int
    high_quality_count: int
    tier_a_count: int
    tier_b_count: int
    tier_c_count: int
    error: str | None = None


@workflow.defn
class UniverseSetupWorkflow:
    """
    Workflow to set up high-quality trading universe.

    This workflow:
    1. Fetches NSE EQ + MTF instruments from Upstox
    2. Fetches Nifty indices constituents from NSE
    3. Enriches and scores stocks (MTF priority)
    4. Saves enriched universe to MongoDB
    """

    @workflow.run
    async def run(self) -> UniverseSetupResult:
        """Execute the universe setup workflow."""
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=30),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting universe setup workflow")

        try:
            # Step 1: Fetch base universe (NSE EQ + MTF)
            workflow.logger.info("Step 1: Fetching base universe from Upstox...")
            base_data: BaseUniverseData = await workflow.execute_activity(
                fetch_base_universe,
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=retry_policy,
            )
            workflow.logger.info(
                f"Base universe: {base_data.nse_eq_count} NSE EQ, "
                f"{base_data.mtf_count} MTF symbols"
            )

            # Step 2: Fetch Nifty indices
            workflow.logger.info("Step 2: Fetching Nifty indices from NSE...")
            nifty_data: NiftyData = await workflow.execute_activity(
                fetch_nifty_indices,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )
            workflow.logger.info(
                f"Nifty indices: 50={len(nifty_data.nifty_50)}, "
                f"100={len(nifty_data.nifty_100)}, "
                f"200={len(nifty_data.nifty_200)}, "
                f"500={len(nifty_data.nifty_500)}"
            )

            # Step 3: Enrich and score universe
            workflow.logger.info("Step 3: Enriching and scoring universe...")
            enriched_stocks: list[dict] = await workflow.execute_activity(
                enrich_and_score_universe,
                args=[
                    base_data.nse_eq_instruments,
                    list(base_data.mtf_symbols),  # Convert set to list for serialization
                    nifty_data.nifty_50,
                    nifty_data.nifty_100,
                    nifty_data.nifty_200,
                    nifty_data.nifty_500,
                ],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Enriched {len(enriched_stocks)} stocks")

            # Step 4: Save to database
            workflow.logger.info("Step 4: Saving enriched universe to database...")
            stats: dict = await workflow.execute_activity(
                save_enriched_universe,
                args=[enriched_stocks],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )
            workflow.logger.info(
                f"Saved {stats['total_saved']} stocks. "
                f"Tier A: {stats['tier_a']}, B: {stats['tier_b']}, C: {stats['tier_c']}"
            )

            return UniverseSetupResult(
                success=True,
                total_nse_eq=base_data.nse_eq_count,
                total_mtf=base_data.mtf_count,
                high_quality_count=stats["high_quality"],
                tier_a_count=stats["tier_a"],
                tier_b_count=stats["tier_b"],
                tier_c_count=stats["tier_c"],
            )

        except Exception as e:
            workflow.logger.error(f"Universe setup failed: {e}")
            return UniverseSetupResult(
                success=False,
                total_nse_eq=0,
                total_mtf=0,
                high_quality_count=0,
                tier_a_count=0,
                tier_b_count=0,
                tier_c_count=0,
                error=str(e),
            )

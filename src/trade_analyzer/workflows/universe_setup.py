"""Universe setup workflow for high-quality trading universe.

This module implements Phase 1 of the trading pipeline, which creates a
high-quality trading universe by enriching stocks with quality scores and
applying fundamental filters.

Pipeline Position: Phase 1 - Universe Setup
-------------------------------------------
Input: Raw NSE EQ + MTF instruments from stocks collection
Output: High-quality stocks (score >= 60) with tier classifications

This is the FIRST filter in the weekend pipeline and includes fundamental
qualification using cached data (no API calls).

Workflow Flow:
1. Fetch base universe (NSE EQ + MTF) from Upstox
2. Fetch Nifty indices constituents (50, 100, 200, 500) from NSE
3. Enrich stocks with quality scores based on:
   - MTF eligibility (highest priority)
   - Nifty index membership (50 > 100 > 200 > 500)
   - Tier classification: A (MTF+N50), B (MTF+N100), C (MTF+N500), D (MTF only)
4. Save enriched universe to MongoDB
5. Apply fundamental filter using CACHED scores (from monthly refresh)

Tier System:
- Tier A (90-100): MTF + Nifty 50 (highest quality, ~30-40 stocks)
- Tier B (75-89): MTF + Nifty 100 (~50-70 stocks)
- Tier C (60-74): MTF + Nifty 500 (~200-300 stocks)
- Tier D (40-59): MTF only (~100-150 stocks)
- Below 40: Low quality, excluded from pipeline

Inputs:
- None (fetches fresh data from APIs)

Outputs:
- UniverseSetupResult containing:
  - total_nse_eq: Total NSE EQ instruments
  - total_mtf: Total MTF instruments
  - high_quality_count: Stocks with score >= 60
  - tier_a/b/c_count: Count per tier
  - fundamentally_qualified: Stocks passing fundamental filter
  - no_fundamental_data: Stocks without cached fundamental scores

Typical Funnel:
~2,400 NSE EQ -> ~600 MTF -> ~450 high-quality (score >= 60) ->
~300 fundamentally qualified

Retry Policy:
- Initial interval: 1 second
- Maximum interval: 30 seconds
- Maximum attempts: 3
- Backoff coefficient: 2.0

Typical Runtime: 5-8 minutes

Related Workflows:
- UniverseRefreshWorkflow: Should be run before this to ensure fresh data
- MomentumFilterWorkflow (Phase 2): Uses output from this workflow
- FundamentalDataRefreshWorkflow: MONTHLY workflow that caches fundamental data
"""

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
    from trade_analyzer.activities.fundamental import apply_fundamental_filter


@dataclass
class UniverseSetupResult:
    """Result of universe setup workflow.

    Attributes:
        success: True if workflow completed without errors
        total_nse_eq: Total NSE equity instruments fetched
        total_mtf: Total MTF-eligible instruments
        high_quality_count: Stocks with quality_score >= 60
        tier_a_count: Tier A stocks (MTF + Nifty 50, score 90-100)
        tier_b_count: Tier B stocks (MTF + Nifty 100, score 75-89)
        tier_c_count: Tier C stocks (MTF + Nifty 500, score 60-74)
        fundamentally_qualified: Stocks passing fundamental filter (score >= 60)
        no_fundamental_data: Stocks without cached fundamental data
        error: Error message if workflow failed, None otherwise
    """

    success: bool
    total_nse_eq: int
    total_mtf: int
    high_quality_count: int
    tier_a_count: int
    tier_b_count: int
    tier_c_count: int
    # Fundamental filter results (Phase 1)
    fundamentally_qualified: int = 0
    no_fundamental_data: int = 0
    error: str | None = None


@workflow.defn
class UniverseSetupWorkflow:
    """Workflow to set up high-quality trading universe (Phase 1).

    This workflow orchestrates the creation of a high-quality trading universe
    by combining multiple data sources and applying quality scoring. It is the
    FIRST phase in the weekend pipeline.

    Activities Orchestrated:
    1. fetch_base_universe: Fetches NSE EQ + MTF from Upstox
    2. fetch_nifty_indices: Fetches Nifty 50/100/200/500 constituents
    3. enrich_and_score_universe: Calculates quality scores
    4. save_enriched_universe: Saves to MongoDB stocks collection
    5. apply_fundamental_filter: Applies cached fundamental scores

    Quality Scoring Logic:
    - Base score: 40 (MTF eligibility)
    - Nifty 50: +50 points (total 90-100)
    - Nifty 100: +35 points (total 75-89)
    - Nifty 200: +25 points (total 65-74)
    - Nifty 500: +20 points (total 60-64)

    The workflow marks stocks as:
    - quality_score: 0-100 numerical score
    - quality_tier: A/B/C/D tier classification
    - fundamentally_qualified: True if fundamental_score >= 60

    Error Handling:
    - Each activity has independent retry policy (3 attempts)
    - Workflow catches all exceptions and returns error result
    - Partial failures (e.g., no fundamental data) still succeed

    Returns:
        UniverseSetupResult with detailed statistics
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

            # Step 5: Apply fundamental filter using cached data
            workflow.logger.info(
                "Step 5: Applying fundamental filter (using cached data)..."
            )
            fund_stats: dict = await workflow.execute_activity(
                apply_fundamental_filter,
                args=[60.0],  # min_score threshold
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )
            workflow.logger.info(
                f"Fundamental filter: {fund_stats['fundamentally_qualified']}/"
                f"{fund_stats['total_stocks']} qualified, "
                f"{fund_stats['no_data']} without data yet"
            )

            return UniverseSetupResult(
                success=True,
                total_nse_eq=base_data.nse_eq_count,
                total_mtf=base_data.mtf_count,
                high_quality_count=stats["high_quality"],
                tier_a_count=stats["tier_a"],
                tier_b_count=stats["tier_b"],
                tier_c_count=stats["tier_c"],
                fundamentally_qualified=fund_stats["fundamentally_qualified"],
                no_fundamental_data=fund_stats["no_data"],
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

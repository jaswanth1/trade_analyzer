"""Fundamental Intelligence workflow for Phase 5.

This workflow:
1. Fetches symbols from Phase 4B trade setups
2. Fetches fundamental data from FMP/Alpha Vantage
3. Calculates multi-dimensional fundamental scores
4. Fetches institutional holdings from NSE
5. Saves results to MongoDB

Reduces ~15-25 liquid stocks to 8-12 fundamentally qualified.
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
        fetch_setup_qualified_symbols,
        save_fundamental_results,
    )


@dataclass
class FundamentalFilterResult:
    """Result of fundamental filter workflow."""

    success: bool
    symbols_analyzed: int
    fundamental_qualified: int
    institutional_qualified: int
    combined_qualified: int
    avg_fundamental_score: float
    top_10: list[dict]
    error: str | None = None


@workflow.defn
class FundamentalFilterWorkflow:
    """
    Workflow for Phase 5: Fundamental Intelligence.

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
        fetch_delay: float = 1.0,
    ) -> FundamentalFilterResult:
        """
        Execute the fundamental filter workflow.

        Args:
            fetch_delay: Delay between API calls (respecting rate limits)
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting Fundamental Filter Workflow (Phase 5)")

        try:
            # Step 1: Get setup-qualified symbols from Phase 4B
            workflow.logger.info("Step 1: Fetching setup-qualified symbols...")
            symbols = await workflow.execute_activity(
                fetch_setup_qualified_symbols,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Found {len(symbols)} setup-qualified symbols")

            if not symbols:
                return FundamentalFilterResult(
                    success=True,
                    symbols_analyzed=0,
                    fundamental_qualified=0,
                    institutional_qualified=0,
                    combined_qualified=0,
                    avg_fundamental_score=0,
                    top_10=[],
                    error="No setup-qualified symbols found. Run Setup Detection first.",
                )

            # Step 2: Fetch fundamental data from FMP
            # Longer timeout due to API rate limits
            workflow.logger.info("Step 2: Fetching fundamental data from FMP...")
            fundamental_data = await workflow.execute_activity(
                fetch_fundamental_data_batch,
                args=[symbols, fetch_delay],
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=retry_policy,
            )
            workflow.logger.info(
                f"Fetched fundamental data for {len(fundamental_data)} symbols"
            )

            if not fundamental_data:
                return FundamentalFilterResult(
                    success=False,
                    symbols_analyzed=len(symbols),
                    fundamental_qualified=0,
                    institutional_qualified=0,
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
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Step 4: Fetch institutional holdings from NSE
            workflow.logger.info("Step 4: Fetching institutional holdings...")
            holdings = await workflow.execute_activity(
                fetch_institutional_holdings_batch,
                args=[symbols, 0.5],
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=retry_policy,
            )

            # Step 5: Save results to MongoDB
            workflow.logger.info("Step 5: Saving results...")
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
                f"Fundamental Filter complete: {stats['fundamental_qualified']} fundamental, "
                f"{stats['holdings_qualified']} institutional, "
                f"{stats['combined_qualified']} combined qualified"
            )

            return FundamentalFilterResult(
                success=True,
                symbols_analyzed=len(symbols),
                fundamental_qualified=stats["fundamental_qualified"],
                institutional_qualified=stats["holdings_qualified"],
                combined_qualified=stats["combined_qualified"],
                avg_fundamental_score=round(stats["avg_fundamental_score"], 1),
                top_10=top_10,
            )

        except Exception as e:
            workflow.logger.error(f"Fundamental Filter failed: {e}")
            return FundamentalFilterResult(
                success=False,
                symbols_analyzed=0,
                fundamental_qualified=0,
                institutional_qualified=0,
                combined_qualified=0,
                avg_fundamental_score=0,
                top_10=[],
                error=str(e),
            )


@dataclass
class Phase5PipelineResult:
    """Result of Phase 4B + Phase 5 pipeline."""

    success: bool
    # Phase 4B stats
    setups_analyzed: int
    setups_found: int
    # Phase 5 stats
    fundamental_qualified: int
    institutional_qualified: int
    combined_qualified: int
    avg_fundamental_score: float
    top_setups: list[dict]
    error: str | None = None


@workflow.defn
class Phase5PipelineWorkflow:
    """
    Complete Phase 5 Pipeline: Setup Detection + Fundamental Filter.

    Phase 4B: ~15-25 → ~8-15 (Setup Detection)
    Phase 5: ~8-15 → ~8-12 (Fundamental Filter)
    """

    @workflow.run
    async def run(self) -> Phase5PipelineResult:
        """Execute Phase 4B + 5 pipeline."""
        workflow.logger.info("Starting Phase 5 Pipeline (Setup + Fundamental)")

        try:
            # Import here to avoid circular imports
            from trade_analyzer.workflows.setup_detection import SetupDetectionWorkflow

            # Phase 4B: Setup Detection
            workflow.logger.info("=== Phase 4B: Setup Detection ===")

            setup_result = await workflow.execute_child_workflow(
                SetupDetectionWorkflow.run,
                args=[30, 2.0, 70],  # batch_size, min_rr, min_confidence
                id=f"setup-detection-{workflow.info().workflow_id}",
            )

            if not setup_result.success:
                return Phase5PipelineResult(
                    success=False,
                    setups_analyzed=0,
                    setups_found=0,
                    fundamental_qualified=0,
                    institutional_qualified=0,
                    combined_qualified=0,
                    avg_fundamental_score=0,
                    top_setups=[],
                    error=f"Setup Detection failed: {setup_result.error}",
                )

            workflow.logger.info(
                f"Setup Detection complete: {setup_result.total_qualified} qualified"
            )

            # Phase 5: Fundamental Filter
            workflow.logger.info("=== Phase 5: Fundamental Filter ===")

            fund_result = await workflow.execute_child_workflow(
                FundamentalFilterWorkflow.run,
                args=[1.0],  # fetch_delay
                id=f"fundamental-filter-{workflow.info().workflow_id}",
            )

            if not fund_result.success:
                return Phase5PipelineResult(
                    success=False,
                    setups_analyzed=setup_result.total_analyzed,
                    setups_found=setup_result.total_setups_found,
                    fundamental_qualified=0,
                    institutional_qualified=0,
                    combined_qualified=0,
                    avg_fundamental_score=0,
                    top_setups=setup_result.top_setups,
                    error=f"Fundamental Filter failed: {fund_result.error}",
                )

            workflow.logger.info(
                f"Fundamental Filter complete: {fund_result.combined_qualified} combined qualified"
            )

            return Phase5PipelineResult(
                success=True,
                setups_analyzed=setup_result.total_analyzed,
                setups_found=setup_result.total_setups_found,
                fundamental_qualified=fund_result.fundamental_qualified,
                institutional_qualified=fund_result.institutional_qualified,
                combined_qualified=fund_result.combined_qualified,
                avg_fundamental_score=fund_result.avg_fundamental_score,
                top_setups=fund_result.top_10,
            )

        except Exception as e:
            workflow.logger.error(f"Phase 5 Pipeline failed: {e}")
            return Phase5PipelineResult(
                success=False,
                setups_analyzed=0,
                setups_found=0,
                fundamental_qualified=0,
                institutional_qualified=0,
                combined_qualified=0,
                avg_fundamental_score=0,
                top_setups=[],
                error=str(e),
            )

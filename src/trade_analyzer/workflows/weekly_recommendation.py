"""Weekly Recommendation workflow for Phase 8 (was Phase 9).

This module implements the final phase that produces human-readable trade
recommendation templates from the portfolio allocation.

Pipeline Position: Phase 8 - Weekly Recommendations
---------------------------------------------------
Input: Final portfolio from Phase 7 (3-7 positions)
Output: Formatted recommendation templates for each trade

This is the FINAL OUTPUT of the weekend pipeline, producing actionable
trade recommendations in template format for manual execution.

NEW Pipeline (fundamentals moved to Phase 1):
Phase 1 (Universe + Fundamentals) → Phase 2 (Momentum) → Phase 3 (Consistency) →
Phase 4A (Volume) → Phase 4B (Setups) → Phase 6 (Risk) → Phase 7 (Portfolio) →
Phase 8 (Recommendations)

Note: Phase 5 (Fundamentals) was consolidated into Phase 1 for efficiency.

Workflow Flow:
1. Optionally run full Phase 5-7 pipeline (if run_full_pipeline=True)
2. Aggregate results from all phases (from MongoDB)
3. Generate recommendation templates with entry/stop/target/thesis
4. Save weekly recommendations to MongoDB
5. Expire old recommendations (>7 days)

Recommendation Template Structure:
- Week Display: "Week of Jan 15-19, 2024"
- Symbol: Stock symbol and name
- Setup Type: PULLBACK/VCP_BREAKOUT/RETEST/GAP_FILL
- Entry Zone: Price range for entry
- Stop Loss: Exact stop price and distance
- Targets: T1 and T2 with R:R ratios
- Position Size: Shares and capital required
- Trade Thesis: Why this setup (1-2 sentences)
- Gap Contingency: What to do if gaps on Monday
- Invalidation: Conditions that invalidate setup

Market Regime Context:
- BULL: Full position sizes, aggressive targets
- SIDEWAYS: 70% sizes, conservative targets
- BEAR: No new positions OR small pullback-only

Typical Output:
3-7 recommendation templates ready for manual execution

Inputs:
- portfolio_value: Total portfolio value (default 10L INR)
- run_full_pipeline: If True, runs Phase 5-7 first (default False)
- market_regime: Override regime (default None, uses DB)

Outputs:
- WeeklyRecommendationResult containing:
  - week_display: Week display string
  - market_regime: Current regime
  - regime_confidence: Regime confidence (0-1)
  - total_setups: Number of recommendations
  - allocated_capital: Capital to deploy (INR)
  - allocated_pct: Capital deployed (%)
  - total_risk_pct: Portfolio risk (%)
  - recommendations: Full recommendation templates

Retry Policy:
- Initial interval: 2 seconds
- Maximum interval: 60 seconds
- Maximum attempts: 3
- Backoff coefficient: 2.0

Typical Runtime:
- Standalone: 2-3 minutes
- With full pipeline: 30-45 minutes

Related Workflows:
- PortfolioConstructionWorkflow (Phase 7): Provides input
- FullPipelineWorkflow: Complete end-to-end pipeline
- ExecutionDisplayWorkflow (Phase 8): Parallel execution workflow
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from trade_analyzer.activities.recommendation import (
        aggregate_phase_results,
        expire_old_recommendations,
        generate_recommendation_templates,
        save_weekly_recommendation,
    )
    from trade_analyzer.config import DEFAULT_PORTFOLIO_VALUE


@dataclass
class WeeklyRecommendationResult:
    """Result of weekly recommendation workflow.

    Attributes:
        success: True if workflow completed without errors
        week_display: Week display string (e.g. "Week of Jan 15-19, 2024")
        market_regime: Current regime (BULL/SIDEWAYS/BEAR)
        regime_confidence: Regime confidence score (0-1)
        total_setups: Number of recommendation templates generated
        allocated_capital: Total capital to deploy in INR
        allocated_pct: Percentage of portfolio to deploy
        total_risk_pct: Total portfolio risk percentage
        recommendations: Full recommendation templates (entry/stop/target/thesis)
        error: Error message if workflow failed, None otherwise
    """

    success: bool
    week_display: str
    market_regime: str
    regime_confidence: float
    total_setups: int
    allocated_capital: float
    allocated_pct: float
    total_risk_pct: float
    recommendations: list[dict]
    error: str | None = None


@workflow.defn
class WeeklyRecommendationWorkflow:
    """Master Weekly Recommendation Workflow (Phase 8).

    This workflow orchestrates the final phase of the weekend pipeline,
    producing human-readable trade recommendations ready for manual execution.

    Activities Orchestrated:
    1. (Optional) Phase7PipelineWorkflow: Runs Phase 5-7 if requested
    2. aggregate_phase_results: Aggregates data from all phases
    3. generate_recommendation_templates: Creates formatted recommendations
    4. save_weekly_recommendation: Saves to MongoDB recommendations collection
    5. expire_old_recommendations: Marks old (>7 days) recommendations expired

    Recommendation Template Contents:
    - Trade identification (symbol, setup type)
    - Entry parameters (zone, timing)
    - Risk parameters (stop, distance %)
    - Reward parameters (T1, T2, R:R ratios)
    - Position sizing (shares, capital)
    - Trade thesis (why this setup)
    - Gap contingency (Monday plan)
    - Invalidation rules (when to abort)

    Can Run In Two Modes:
    1. Standalone: Uses existing Phase 7 portfolio (fast, 2-3 min)
    2. Full Pipeline: Runs Phase 5-7 first (slow, 30-45 min)

    Error Handling:
    - Returns empty result if no portfolio found
    - Saves partial recommendations if some fail
    - Expires old recommendations even on error

    Returns:
        WeeklyRecommendationResult with formatted recommendations
    """

    @workflow.run
    async def run(
        self,
        portfolio_value: float = DEFAULT_PORTFOLIO_VALUE,
        run_full_pipeline: bool = False,
        market_regime: str | None = None,
    ) -> WeeklyRecommendationResult:
        """
        Execute weekly recommendation workflow.

        Args:
            portfolio_value: Total portfolio value
            run_full_pipeline: If True, runs Phases 5-7 first
            market_regime: Override regime (if None, uses latest from DB)
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting Weekly Recommendation Workflow (Phase 9)")

        try:
            # Optionally run full pipeline
            if run_full_pipeline:
                workflow.logger.info("Running full Phase 5-7 pipeline...")
                from trade_analyzer.workflows.portfolio_construction import (
                    Phase7PipelineWorkflow,
                )

                pipeline_result = await workflow.execute_child_workflow(
                    Phase7PipelineWorkflow.run,
                    args=[portfolio_value, market_regime or "risk_on"],
                    id=f"phase7-pipeline-{workflow.info().workflow_id}",
                )

                if not pipeline_result.success:
                    return WeeklyRecommendationResult(
                        success=False,
                        week_display="",
                        market_regime="unknown",
                        regime_confidence=0,
                        total_setups=0,
                        allocated_capital=0,
                        allocated_pct=0,
                        total_risk_pct=0,
                        recommendations=[],
                        error=f"Pipeline failed: {pipeline_result.error}",
                    )

            # Step 1: Aggregate results from all phases
            workflow.logger.info("Step 1: Aggregating phase results...")
            aggregated = await workflow.execute_activity(
                aggregate_phase_results,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            regime = aggregated["regime"]
            positions = aggregated["positions"]
            stats = aggregated["stats"]

            # Use provided regime or aggregated
            if market_regime:
                regime["state"] = market_regime

            if not positions:
                return WeeklyRecommendationResult(
                    success=True,
                    week_display="",
                    market_regime=regime["state"],
                    regime_confidence=regime["confidence"],
                    total_setups=0,
                    allocated_capital=0,
                    allocated_pct=0,
                    total_risk_pct=0,
                    recommendations=[],
                    error="No positions found. Run Phase 7 pipeline first.",
                )

            workflow.logger.info(
                f"Aggregated {len(positions)} positions, regime: {regime['state']}"
            )

            # Step 2: Generate recommendation templates
            workflow.logger.info("Step 2: Generating recommendation templates...")
            templates = await workflow.execute_activity(
                generate_recommendation_templates,
                args=[positions, regime["state"], regime["confidence"], portfolio_value],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )

            workflow.logger.info(f"Generated {len(templates)} recommendation templates")

            # Step 3: Save weekly recommendation
            workflow.logger.info("Step 3: Saving weekly recommendation...")
            save_result = await workflow.execute_activity(
                save_weekly_recommendation,
                args=[templates, regime, stats, portfolio_value],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Step 4: Expire old recommendations
            workflow.logger.info("Step 4: Expiring old recommendations...")
            await workflow.execute_activity(
                expire_old_recommendations,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            # Get week display from first template
            week_display = templates[0]["week_display"] if templates else ""

            workflow.logger.info(
                f"Weekly Recommendation complete: {len(templates)} setups, "
                f"Rs.{save_result['allocated_capital']:,.0f} allocated "
                f"({save_result['allocated_pct']:.1f}%)"
            )

            return WeeklyRecommendationResult(
                success=True,
                week_display=week_display,
                market_regime=regime["state"],
                regime_confidence=regime["confidence"],
                total_setups=len(templates),
                allocated_capital=save_result["allocated_capital"],
                allocated_pct=save_result["allocated_pct"],
                total_risk_pct=save_result["total_risk_pct"],
                recommendations=templates,
            )

        except Exception as e:
            workflow.logger.error(f"Weekly Recommendation workflow failed: {e}")
            return WeeklyRecommendationResult(
                success=False,
                week_display="",
                market_regime="unknown",
                regime_confidence=0,
                total_setups=0,
                allocated_capital=0,
                allocated_pct=0,
                total_risk_pct=0,
                recommendations=[],
                error=str(e),
            )


@dataclass
class FullPipelineResult:
    """Result of full end-to-end pipeline workflow.

    This result combines statistics from ALL phases of the weekend pipeline,
    from setup detection through final recommendations.

    Attributes:
        success: True if all phases completed without errors
        phase_4_setups: Setups detected in Phase 4B (8-15 typical)
        phase_5_fundamental: Fundamentals (kept for backward compat, now in Phase 1)
        phase_6_risk_qualified: Positions passing risk filters (8-10 typical)
        phase_7_final_positions: Final portfolio positions (3-7 typical)
        week_display: Week display string for recommendations
        market_regime: Current market regime (BULL/SIDEWAYS/BEAR)
        regime_confidence: Regime confidence score (0-1)
        total_setups: Final recommendation count
        allocated_capital: Capital to deploy (INR)
        allocated_pct: Capital deployment percentage
        total_risk_pct: Portfolio risk percentage
        recommendations: Complete recommendation templates
        error: Error message if any phase failed, None otherwise
    """

    success: bool
    # Phase summaries
    phase_4_setups: int
    phase_5_fundamental: int
    phase_6_risk_qualified: int
    phase_7_final_positions: int
    # Final output
    week_display: str
    market_regime: str
    regime_confidence: float
    total_setups: int
    allocated_capital: float
    allocated_pct: float
    total_risk_pct: float
    recommendations: list[dict]
    error: str | None = None


@workflow.defn
class FullPipelineWorkflow:
    """Complete End-to-End Pipeline Workflow (Phase 4B → 8).

    This is the MASTER WORKFLOW for weekend analysis, orchestrating the final
    stages of the pipeline from setup detection through recommendations.

    Child Workflows Orchestrated:
    1. SetupDetectionWorkflow (Phase 4B): Detects technical setups
    2. RiskGeometryWorkflow (Phase 6): Calculates risk parameters
    3. PortfolioConstructionWorkflow (Phase 7): Builds final portfolio
    4. WeeklyRecommendationWorkflow (Phase 8): Generates recommendations

    NOTE: Fundamentals are now applied in Phase 1 (UniverseSetupWorkflow).
    The old Phase 5 (Fundamentals) has been removed from this pipeline for
    efficiency. This workflow assumes Phase 1-4A have already run.

    Complete Weekend Pipeline Flow:
    1. Phase 1: UniverseSetupWorkflow (Universe + Fundamentals)
    2. Phase 2: MomentumFilterWorkflow (Momentum filters)
    3. Phase 3: ConsistencyFilterWorkflow (Weekly consistency)
    4. Phase 4A: VolumeFilterWorkflow (Liquidity)
    5. Phase 4B: SetupDetectionWorkflow (Technical setups) <- This workflow starts here
    6. Phase 6: RiskGeometryWorkflow (Risk parameters)
    7. Phase 7: PortfolioConstructionWorkflow (Final portfolio)
    8. Phase 8: WeeklyRecommendationWorkflow (Recommendations)

    Typical Full Pipeline Funnel:
    ~2,400 NSE EQ -> ~450 high-quality -> ~50-100 momentum -> ~30-50 consistency ->
    ~15-25 liquid -> ~8-15 setups -> ~8-10 risk-qualified -> ~5-7 portfolio ->
    3-7 final recommendations

    This workflow is the master orchestrator for weekend analysis, producing
    the final trade recommendations for the upcoming week.

    Error Handling:
    - Each phase failure stops pipeline
    - Returns results from successful phases
    - Detailed error reporting per phase

    Returns:
        FullPipelineResult with complete pipeline statistics
    """

    @workflow.run
    async def run(
        self,
        portfolio_value: float = DEFAULT_PORTFOLIO_VALUE,
        market_regime: str = "risk_on",
    ) -> FullPipelineResult:
        """
        Execute complete end-to-end pipeline.

        Args:
            portfolio_value: Total portfolio value
            market_regime: Current market regime
        """
        workflow.logger.info(
            "Starting Full Pipeline Workflow (Phases 4B → 5 → 6 → 8)"
        )
        workflow.logger.info(
            "NOTE: Fundamentals are now applied in Phase 1 (UniverseSetupWorkflow)"
        )

        try:
            # Import workflows
            from trade_analyzer.workflows.setup_detection import SetupDetectionWorkflow
            from trade_analyzer.workflows.risk_geometry import RiskGeometryWorkflow
            from trade_analyzer.workflows.portfolio_construction import PortfolioConstructionWorkflow

            # Phase 4B: Setup Detection
            workflow.logger.info("=== Phase 4B: Setup Detection ===")
            setup_result = await workflow.execute_child_workflow(
                SetupDetectionWorkflow.run,
                args=[30, 2.0, 70],  # batch_size, min_rr, min_confidence
                id=f"setup-detection-{workflow.info().workflow_id}",
            )

            if not setup_result.success:
                return FullPipelineResult(
                    success=False,
                    phase_4_setups=0,
                    phase_5_fundamental=0,  # Kept for backward compat
                    phase_6_risk_qualified=0,
                    phase_7_final_positions=0,
                    week_display="",
                    market_regime=market_regime,
                    regime_confidence=0,
                    total_setups=0,
                    allocated_capital=0,
                    allocated_pct=0,
                    total_risk_pct=0,
                    recommendations=[],
                    error=f"Phase 4B failed: {setup_result.error}",
                )

            phase_4_count = setup_result.total_qualified
            workflow.logger.info(f"Phase 4B: {phase_4_count} setups qualified")

            # NOTE: Old Phase 5 (Fundamentals) removed - now in Phase 1
            # Setups already have fundamentally_qualified stocks from Phase 1
            workflow.logger.info(
                "=== Skipping old Phase 5 (Fundamentals now in Phase 1) ==="
            )

            # Phase 5: Risk Geometry (was Phase 6)
            workflow.logger.info("=== Phase 5: Risk Geometry ===")
            risk_result = await workflow.execute_child_workflow(
                RiskGeometryWorkflow.run,
                args=[portfolio_value, 0.015, 0.08, 12, 2.0, 2.5, 7.0, market_regime],
                id=f"risk-geometry-{workflow.info().workflow_id}",
            )

            if not risk_result.success:
                return FullPipelineResult(
                    success=False,
                    phase_4_setups=phase_4_count,
                    phase_5_fundamental=phase_4_count,  # Same as 4B (no separate filter)
                    phase_6_risk_qualified=0,
                    phase_7_final_positions=0,
                    week_display="",
                    market_regime=market_regime,
                    regime_confidence=0,
                    total_setups=0,
                    allocated_capital=0,
                    allocated_pct=0,
                    total_risk_pct=0,
                    recommendations=[],
                    error=f"Phase 5 (Risk) failed: {risk_result.error}",
                )

            phase_5_risk_count = risk_result.risk_qualified
            workflow.logger.info(f"Phase 5 (Risk): {phase_5_risk_count} risk qualified")

            # Phase 6: Portfolio Construction (was Phase 7)
            workflow.logger.info("=== Phase 6: Portfolio Construction ===")
            portfolio_result = await workflow.execute_child_workflow(
                PortfolioConstructionWorkflow.run,
                args=[portfolio_value, 0.70, 3, 0.25, 12, 3, 0.30, market_regime],
                id=f"portfolio-{workflow.info().workflow_id}",
            )

            if not portfolio_result.success:
                return FullPipelineResult(
                    success=False,
                    phase_4_setups=phase_4_count,
                    phase_5_fundamental=phase_4_count,
                    phase_6_risk_qualified=phase_5_risk_count,
                    phase_7_final_positions=0,
                    week_display="",
                    market_regime=market_regime,
                    regime_confidence=0,
                    total_setups=0,
                    allocated_capital=0,
                    allocated_pct=0,
                    total_risk_pct=0,
                    recommendations=[],
                    error=f"Phase 6 (Portfolio) failed: {portfolio_result.error}",
                )

            phase_6_count = portfolio_result.final_positions
            workflow.logger.info(f"Phase 6 (Portfolio): {phase_6_count} final positions")

            # Phase 8: Weekly Recommendations (was Phase 9)
            workflow.logger.info("=== Phase 8: Weekly Recommendations ===")
            rec_result = await workflow.execute_child_workflow(
                WeeklyRecommendationWorkflow.run,
                args=[portfolio_value, False, market_regime],  # Don't re-run pipeline
                id=f"recommendation-{workflow.info().workflow_id}",
            )

            if not rec_result.success:
                return FullPipelineResult(
                    success=False,
                    phase_4_setups=phase_4_count,
                    phase_5_fundamental=phase_4_count,
                    phase_6_risk_qualified=phase_5_risk_count,
                    phase_7_final_positions=phase_6_count,
                    week_display="",
                    market_regime=market_regime,
                    regime_confidence=0,
                    total_setups=0,
                    allocated_capital=0,
                    allocated_pct=0,
                    total_risk_pct=0,
                    recommendations=[],
                    error=f"Phase 8 (Recommendations) failed: {rec_result.error}",
                )

            workflow.logger.info(
                f"Full Pipeline complete: {phase_4_count} setups → "
                f"{phase_5_risk_count} risk → {phase_6_count} portfolio → "
                f"{rec_result.total_setups} recommendations"
            )

            return FullPipelineResult(
                success=True,
                phase_4_setups=phase_4_count,
                phase_5_fundamental=phase_4_count,  # Backward compat: same as 4B
                phase_6_risk_qualified=phase_5_risk_count,
                phase_7_final_positions=phase_6_count,
                week_display=rec_result.week_display,
                market_regime=rec_result.market_regime,
                regime_confidence=rec_result.regime_confidence,
                total_setups=rec_result.total_setups,
                allocated_capital=rec_result.allocated_capital,
                allocated_pct=rec_result.allocated_pct,
                total_risk_pct=rec_result.total_risk_pct,
                recommendations=rec_result.recommendations,
            )

        except Exception as e:
            workflow.logger.error(f"Full Pipeline failed: {e}")
            return FullPipelineResult(
                success=False,
                phase_4_setups=0,
                phase_5_fundamental=0,
                phase_6_risk_qualified=0,
                phase_7_final_positions=0,
                week_display="",
                market_regime="unknown",
                regime_confidence=0,
                total_setups=0,
                allocated_capital=0,
                allocated_pct=0,
                total_risk_pct=0,
                recommendations=[],
                error=str(e),
            )

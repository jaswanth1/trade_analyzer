"""Weekly Recommendation workflow for Phase 9.

This is the master workflow that orchestrates all phases
and produces final trade recommendation templates.

Pipeline: Phase 1-4 → Phase 5 → Phase 6 → Phase 7 → Phase 8-9
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
    """Result of weekly recommendation workflow."""

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
    """
    Master Weekly Recommendation Workflow.

    This workflow:
    1. Optionally runs Phase 5-7 pipeline
    2. Aggregates results from all phases
    3. Generates recommendation templates
    4. Saves weekly recommendations
    5. Expires old recommendations

    Can be run standalone (after Phase 7) or as part of full pipeline.
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
    """Result of full end-to-end pipeline."""

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
    """
    Complete End-to-End Pipeline Workflow.

    Runs all phases from setup detection to final recommendations:
    Phase 4B → Phase 5 → Phase 6 → Phase 7 → Phase 9

    This is the master workflow for weekend analysis.
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
        workflow.logger.info("Starting Full Pipeline Workflow (Phases 4B-9)")

        try:
            # Import workflows
            from trade_analyzer.workflows.setup_detection import SetupDetectionWorkflow
            from trade_analyzer.workflows.fundamental_filter import FundamentalFilterWorkflow
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
                    phase_5_fundamental=0,
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

            # Phase 5: Fundamental Filter
            workflow.logger.info("=== Phase 5: Fundamental Filter ===")
            fund_result = await workflow.execute_child_workflow(
                FundamentalFilterWorkflow.run,
                args=[1.0],  # fetch_delay
                id=f"fundamental-{workflow.info().workflow_id}",
            )

            if not fund_result.success:
                return FullPipelineResult(
                    success=False,
                    phase_4_setups=phase_4_count,
                    phase_5_fundamental=0,
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
                    error=f"Phase 5 failed: {fund_result.error}",
                )

            phase_5_count = fund_result.combined_qualified
            workflow.logger.info(f"Phase 5: {phase_5_count} fundamentally qualified")

            # Phase 6: Risk Geometry
            workflow.logger.info("=== Phase 6: Risk Geometry ===")
            risk_result = await workflow.execute_child_workflow(
                RiskGeometryWorkflow.run,
                args=[portfolio_value, 0.015, 0.08, 12, 2.0, 2.5, 7.0, market_regime],
                id=f"risk-geometry-{workflow.info().workflow_id}",
            )

            if not risk_result.success:
                return FullPipelineResult(
                    success=False,
                    phase_4_setups=phase_4_count,
                    phase_5_fundamental=phase_5_count,
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
                    error=f"Phase 6 failed: {risk_result.error}",
                )

            phase_6_count = risk_result.risk_qualified
            workflow.logger.info(f"Phase 6: {phase_6_count} risk qualified")

            # Phase 7: Portfolio Construction
            workflow.logger.info("=== Phase 7: Portfolio Construction ===")
            portfolio_result = await workflow.execute_child_workflow(
                PortfolioConstructionWorkflow.run,
                args=[portfolio_value, 0.70, 3, 0.25, 12, 3, 0.30, market_regime],
                id=f"portfolio-{workflow.info().workflow_id}",
            )

            if not portfolio_result.success:
                return FullPipelineResult(
                    success=False,
                    phase_4_setups=phase_4_count,
                    phase_5_fundamental=phase_5_count,
                    phase_6_risk_qualified=phase_6_count,
                    phase_7_final_positions=0,
                    week_display="",
                    market_regime=market_regime,
                    regime_confidence=0,
                    total_setups=0,
                    allocated_capital=0,
                    allocated_pct=0,
                    total_risk_pct=0,
                    recommendations=[],
                    error=f"Phase 7 failed: {portfolio_result.error}",
                )

            phase_7_count = portfolio_result.final_positions
            workflow.logger.info(f"Phase 7: {phase_7_count} final positions")

            # Phase 9: Weekly Recommendations
            workflow.logger.info("=== Phase 9: Weekly Recommendations ===")
            rec_result = await workflow.execute_child_workflow(
                WeeklyRecommendationWorkflow.run,
                args=[portfolio_value, False, market_regime],  # Don't re-run pipeline
                id=f"recommendation-{workflow.info().workflow_id}",
            )

            if not rec_result.success:
                return FullPipelineResult(
                    success=False,
                    phase_4_setups=phase_4_count,
                    phase_5_fundamental=phase_5_count,
                    phase_6_risk_qualified=phase_6_count,
                    phase_7_final_positions=phase_7_count,
                    week_display="",
                    market_regime=market_regime,
                    regime_confidence=0,
                    total_setups=0,
                    allocated_capital=0,
                    allocated_pct=0,
                    total_risk_pct=0,
                    recommendations=[],
                    error=f"Phase 9 failed: {rec_result.error}",
                )

            workflow.logger.info(
                f"Full Pipeline complete: {phase_4_count} → {phase_5_count} → "
                f"{phase_6_count} → {phase_7_count} → {rec_result.total_setups} recommendations"
            )

            return FullPipelineResult(
                success=True,
                phase_4_setups=phase_4_count,
                phase_5_fundamental=phase_5_count,
                phase_6_risk_qualified=phase_6_count,
                phase_7_final_positions=phase_7_count,
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

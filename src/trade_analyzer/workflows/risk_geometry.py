"""Risk Geometry workflow for Phase 6.

This workflow:
1. Fetches fundamentally-enriched setups from Phase 5
2. Calculates multi-method stop-loss (structure, volatility)
3. Calculates position sizes with Kelly + Volatility adjustments
4. Saves results to MongoDB

Reduces ~8-12 fundamental stocks to ~8-10 risk-qualified.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from trade_analyzer.activities.risk_geometry import (
        calculate_position_sizes,
        calculate_risk_geometry_batch,
        fetch_fundamentally_enriched_setups,
        save_risk_geometry_results,
    )


@dataclass
class RiskGeometryResult:
    """Result of risk geometry workflow."""

    success: bool
    setups_analyzed: int
    risk_qualified: int
    total_risk: float
    total_value: float
    avg_rr_ratio: float
    top_positions: list[dict]
    error: str | None = None


@workflow.defn
class RiskGeometryWorkflow:
    """
    Workflow for Phase 6: Risk Geometry.

    Stop-Loss Methods:
    1. Structure Stop: Below swing low * 0.99
    2. Volatility Stop: Entry - 2.0 × ATR(14)
    Final Stop = max(structure, volatility) (tighter)

    Position Sizing:
    Base = (Portfolio × Risk%) / Risk_per_share
    Vol_Adjusted = Base × (Nifty_ATR / Stock_ATR)
    Kelly = (Win% × AvgWin - Loss% × AvgLoss) / AvgWin
    Final = Base × Vol_Adj × min(1.0, Kelly) × Regime_Mult
    """

    @workflow.run
    async def run(
        self,
        portfolio_value: float = 1000000.0,
        risk_pct_per_trade: float = 0.015,
        max_position_pct: float = 0.08,
        max_positions: int = 12,
        min_rr_risk_on: float = 2.0,
        min_rr_choppy: float = 2.5,
        max_stop_pct: float = 7.0,
        market_regime: str = "risk_on",
    ) -> RiskGeometryResult:
        """
        Execute the risk geometry workflow.

        Args:
            portfolio_value: Total portfolio value in INR
            risk_pct_per_trade: Risk per trade as decimal
            max_position_pct: Max single position as decimal
            max_positions: Maximum number of positions
            min_rr_risk_on: Minimum R:R in risk-on regime
            min_rr_choppy: Minimum R:R in choppy regime
            max_stop_pct: Maximum stop distance percentage
            market_regime: Current market regime
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting Risk Geometry Workflow (Phase 6)")

        try:
            # Step 1: Fetch fundamentally-enriched setups
            workflow.logger.info("Step 1: Fetching fundamentally-enriched setups...")
            setups = await workflow.execute_activity(
                fetch_fundamentally_enriched_setups,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Found {len(setups)} fundamentally-enriched setups")

            if not setups:
                return RiskGeometryResult(
                    success=True,
                    setups_analyzed=0,
                    risk_qualified=0,
                    total_risk=0,
                    total_value=0,
                    avg_rr_ratio=0,
                    top_positions=[],
                    error="No fundamentally-enriched setups found. Run Fundamental Filter first.",
                )

            # Step 2: Calculate risk geometry (stops, targets, R:R)
            workflow.logger.info("Step 2: Calculating risk geometry...")
            risk_geometries = await workflow.execute_activity(
                calculate_risk_geometry_batch,
                args=[setups, min_rr_risk_on, min_rr_choppy, max_stop_pct, market_regime],
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=retry_policy,
            )

            qualified_geometries = [g for g in risk_geometries if g.get("risk_qualifies")]
            workflow.logger.info(
                f"Risk geometry: {len(qualified_geometries)}/{len(risk_geometries)} qualified"
            )

            if not qualified_geometries:
                return RiskGeometryResult(
                    success=True,
                    setups_analyzed=len(setups),
                    risk_qualified=0,
                    total_risk=0,
                    total_value=0,
                    avg_rr_ratio=0,
                    top_positions=[],
                    error="No setups passed risk geometry filters.",
                )

            # Step 3: Calculate position sizes
            workflow.logger.info("Step 3: Calculating position sizes...")
            position_sizes = await workflow.execute_activity(
                calculate_position_sizes,
                args=[
                    risk_geometries,
                    portfolio_value,
                    risk_pct_per_trade,
                    max_position_pct,
                    max_positions,
                    market_regime,
                ],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Calculated sizes for {len(position_sizes)} positions")

            # Step 4: Save results
            workflow.logger.info("Step 4: Saving results...")
            stats = await workflow.execute_activity(
                save_risk_geometry_results,
                args=[position_sizes],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Calculate average R:R
            rr_ratios = [p.get("rr_ratio_1", 0) for p in position_sizes]
            avg_rr = sum(rr_ratios) / len(rr_ratios) if rr_ratios else 0

            # Prepare top positions for display
            top_positions = [
                {
                    "symbol": p["symbol"],
                    "entry": p.get("entry_price", 0),
                    "stop": p.get("final_stop", 0),
                    "stop_method": p.get("stop_method", ""),
                    "target_1": p.get("target_1", 0),
                    "rr_ratio": p.get("rr_ratio_1", 0),
                    "shares": p.get("final_shares", 0),
                    "position_value": p.get("final_position_value", 0),
                    "risk_amount": p.get("final_risk_amount", 0),
                    "position_pct": p.get("position_pct_of_portfolio", 0),
                }
                for p in position_sizes[:10]
            ]

            workflow.logger.info(
                f"Risk Geometry complete: {len(position_sizes)} positions, "
                f"Rs.{stats['total_risk']:,.0f} risk, Rs.{stats['total_value']:,.0f} value"
            )

            return RiskGeometryResult(
                success=True,
                setups_analyzed=len(setups),
                risk_qualified=len(position_sizes),
                total_risk=stats["total_risk"],
                total_value=stats["total_value"],
                avg_rr_ratio=round(avg_rr, 2),
                top_positions=top_positions,
            )

        except Exception as e:
            workflow.logger.error(f"Risk Geometry workflow failed: {e}")
            return RiskGeometryResult(
                success=False,
                setups_analyzed=0,
                risk_qualified=0,
                total_risk=0,
                total_value=0,
                avg_rr_ratio=0,
                top_positions=[],
                error=str(e),
            )


@dataclass
class Phase6PipelineResult:
    """Result of Phase 5 + Phase 6 pipeline."""

    success: bool
    # Phase 5 stats
    fundamental_qualified: int
    institutional_qualified: int
    # Phase 6 stats
    risk_qualified: int
    total_risk: float
    total_value: float
    avg_rr_ratio: float
    top_positions: list[dict]
    error: str | None = None


@workflow.defn
class Phase6PipelineWorkflow:
    """
    Complete Phase 6 Pipeline: Fundamental Filter + Risk Geometry.

    Phase 5: ~15-25 → ~8-12 (Fundamental Filter)
    Phase 6: ~8-12 → ~8-10 (Risk Geometry)
    """

    @workflow.run
    async def run(
        self,
        portfolio_value: float = 1000000.0,
        market_regime: str = "risk_on",
    ) -> Phase6PipelineResult:
        """Execute Phase 5 + 6 pipeline."""
        workflow.logger.info("Starting Phase 6 Pipeline (Fundamental + Risk)")

        try:
            # Import here to avoid circular imports
            from trade_analyzer.workflows.fundamental_filter import (
                FundamentalFilterWorkflow,
            )

            # Phase 5: Fundamental Filter
            workflow.logger.info("=== Phase 5: Fundamental Filter ===")

            fund_result = await workflow.execute_child_workflow(
                FundamentalFilterWorkflow.run,
                args=[1.0],  # fetch_delay
                id=f"fundamental-filter-{workflow.info().workflow_id}",
            )

            if not fund_result.success:
                return Phase6PipelineResult(
                    success=False,
                    fundamental_qualified=0,
                    institutional_qualified=0,
                    risk_qualified=0,
                    total_risk=0,
                    total_value=0,
                    avg_rr_ratio=0,
                    top_positions=[],
                    error=f"Fundamental Filter failed: {fund_result.error}",
                )

            workflow.logger.info(
                f"Fundamental Filter complete: {fund_result.combined_qualified} combined qualified"
            )

            # Phase 6: Risk Geometry
            workflow.logger.info("=== Phase 6: Risk Geometry ===")

            risk_result = await workflow.execute_child_workflow(
                RiskGeometryWorkflow.run,
                args=[portfolio_value, 0.015, 0.08, 12, 2.0, 2.5, 7.0, market_regime],
                id=f"risk-geometry-{workflow.info().workflow_id}",
            )

            if not risk_result.success:
                return Phase6PipelineResult(
                    success=False,
                    fundamental_qualified=fund_result.fundamental_qualified,
                    institutional_qualified=fund_result.institutional_qualified,
                    risk_qualified=0,
                    total_risk=0,
                    total_value=0,
                    avg_rr_ratio=0,
                    top_positions=[],
                    error=f"Risk Geometry failed: {risk_result.error}",
                )

            workflow.logger.info(
                f"Risk Geometry complete: {risk_result.risk_qualified} risk-qualified"
            )

            return Phase6PipelineResult(
                success=True,
                fundamental_qualified=fund_result.fundamental_qualified,
                institutional_qualified=fund_result.institutional_qualified,
                risk_qualified=risk_result.risk_qualified,
                total_risk=risk_result.total_risk,
                total_value=risk_result.total_value,
                avg_rr_ratio=risk_result.avg_rr_ratio,
                top_positions=risk_result.top_positions,
            )

        except Exception as e:
            workflow.logger.error(f"Phase 6 Pipeline failed: {e}")
            return Phase6PipelineResult(
                success=False,
                fundamental_qualified=0,
                institutional_qualified=0,
                risk_qualified=0,
                total_risk=0,
                total_value=0,
                avg_rr_ratio=0,
                top_positions=[],
                error=str(e),
            )

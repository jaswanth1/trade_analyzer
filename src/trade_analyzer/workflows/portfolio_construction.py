"""Portfolio Construction workflow for Phase 7.

This workflow:
1. Fetches position-sized setups from Phase 6
2. Calculates correlation matrix
3. Applies correlation filter (max 0.70)
4. Applies sector limits (3 per sector, 25% max)
5. Constructs final portfolio with constraints
6. Saves portfolio allocation

Produces final 3-7 position portfolio.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from trade_analyzer.activities.portfolio_construction import (
        apply_correlation_filter,
        apply_sector_limits,
        calculate_correlation_matrix,
        construct_final_portfolio,
        fetch_position_sized_setups,
        save_portfolio_allocation,
    )
    from trade_analyzer.config import (
        CASH_RESERVE_PCT,
        DEFAULT_PORTFOLIO_VALUE,
        MAX_POSITIONS,
        MAX_SECTOR_PCT,
    )


@dataclass
class PortfolioConstructionResult:
    """Result of portfolio construction workflow."""

    success: bool
    setups_input: int
    after_correlation_filter: int
    after_sector_limits: int
    final_positions: int
    total_invested_pct: float
    total_risk_pct: float
    cash_reserve_pct: float
    sector_allocation: dict
    positions: list[dict]
    status: str
    error: str | None = None


@workflow.defn
class PortfolioConstructionWorkflow:
    """
    Workflow for Phase 7: Portfolio Construction.

    Constraints Applied:
    1. Correlation filter: Max 0.70 between any two positions
    2. Sector limits: Max 3 per sector, 25% max exposure
    3. Position limits: Max 12 (Risk-On), 5 (Choppy), 0 (Risk-Off)
    4. Single position: Max 8% of portfolio
    5. Cash reserve: 25-35%
    """

    @workflow.run
    async def run(
        self,
        portfolio_value: float = DEFAULT_PORTFOLIO_VALUE,
        max_correlation: float = 0.70,
        max_per_sector: int = 3,
        max_sector_pct: float = MAX_SECTOR_PCT,
        max_positions: int = MAX_POSITIONS,
        min_positions: int = 3,
        cash_reserve_pct: float = CASH_RESERVE_PCT,
        market_regime: str = "risk_on",
    ) -> PortfolioConstructionResult:
        """
        Execute the portfolio construction workflow.

        Args:
            portfolio_value: Total portfolio value
            max_correlation: Maximum allowed correlation
            max_per_sector: Max positions per sector
            max_sector_pct: Max sector exposure as decimal
            max_positions: Maximum total positions
            min_positions: Minimum positions for valid portfolio
            cash_reserve_pct: Target cash reserve percentage
            market_regime: Current market regime
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting Portfolio Construction Workflow (Phase 7)")

        try:
            # Step 1: Fetch position-sized setups from Phase 6
            workflow.logger.info("Step 1: Fetching position-sized setups...")
            setups = await workflow.execute_activity(
                fetch_position_sized_setups,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Found {len(setups)} position-sized setups")

            if not setups:
                return PortfolioConstructionResult(
                    success=True,
                    setups_input=0,
                    after_correlation_filter=0,
                    after_sector_limits=0,
                    final_positions=0,
                    total_invested_pct=0,
                    total_risk_pct=0,
                    cash_reserve_pct=100,
                    sector_allocation={},
                    positions=[],
                    status="no_setups",
                    error="No position-sized setups found. Run Risk Geometry first.",
                )

            # Step 2: Calculate correlation matrix
            workflow.logger.info("Step 2: Calculating correlation matrix...")
            symbols = [s["symbol"] for s in setups]
            correlations = await workflow.execute_activity(
                calculate_correlation_matrix,
                args=[symbols, 60],  # 60 day lookback
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Calculated correlations for {len(symbols)} symbols")

            # Step 3: Apply correlation filter
            workflow.logger.info("Step 3: Applying correlation filter...")
            after_corr = await workflow.execute_activity(
                apply_correlation_filter,
                args=[setups, correlations, max_correlation],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )
            workflow.logger.info(
                f"Correlation filter: {len(after_corr)}/{len(setups)} passed"
            )

            # Step 4: Apply sector limits
            workflow.logger.info("Step 4: Applying sector limits...")
            after_sector = await workflow.execute_activity(
                apply_sector_limits,
                args=[after_corr, max_per_sector, max_sector_pct, portfolio_value],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )
            workflow.logger.info(
                f"Sector limits: {len(after_sector)}/{len(after_corr)} passed"
            )

            # Step 5: Construct final portfolio
            workflow.logger.info("Step 5: Constructing final portfolio...")
            portfolio = await workflow.execute_activity(
                construct_final_portfolio,
                args=[
                    after_sector,
                    max_positions,
                    min_positions,
                    cash_reserve_pct,
                    portfolio_value,
                    market_regime,
                ],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Step 6: Save portfolio allocation
            workflow.logger.info("Step 6: Saving portfolio allocation...")
            await workflow.execute_activity(
                save_portfolio_allocation,
                args=[portfolio],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            workflow.logger.info(
                f"Portfolio Construction complete: {portfolio['position_count']} positions, "
                f"{portfolio['total_risk_pct']:.1f}% risk, "
                f"{portfolio['cash_reserve_pct']:.1f}% cash"
            )

            return PortfolioConstructionResult(
                success=True,
                setups_input=len(setups),
                after_correlation_filter=len(after_corr),
                after_sector_limits=len(after_sector),
                final_positions=portfolio["position_count"],
                total_invested_pct=portfolio["total_invested_pct"],
                total_risk_pct=portfolio["total_risk_pct"],
                cash_reserve_pct=portfolio["cash_reserve_pct"],
                sector_allocation=portfolio["sector_allocation"],
                positions=portfolio["positions"],
                status=portfolio["status"],
            )

        except Exception as e:
            workflow.logger.error(f"Portfolio Construction workflow failed: {e}")
            return PortfolioConstructionResult(
                success=False,
                setups_input=0,
                after_correlation_filter=0,
                after_sector_limits=0,
                final_positions=0,
                total_invested_pct=0,
                total_risk_pct=0,
                cash_reserve_pct=0,
                sector_allocation={},
                positions=[],
                status="error",
                error=str(e),
            )


@dataclass
class Phase7PipelineResult:
    """Result of full Phase 5-7 pipeline."""

    success: bool
    # Phase 5 stats
    fundamental_qualified: int
    institutional_qualified: int
    # Phase 6 stats
    risk_qualified: int
    # Phase 7 stats
    final_positions: int
    total_invested_pct: float
    total_risk_pct: float
    cash_reserve_pct: float
    sector_allocation: dict
    positions: list[dict]
    error: str | None = None


@workflow.defn
class Phase7PipelineWorkflow:
    """
    Complete Phase 7 Pipeline: Fundamental + Risk + Portfolio.

    Phase 5: ~15-25 → ~8-12 (Fundamental Filter)
    Phase 6: ~8-12 → ~8-10 (Risk Geometry)
    Phase 7: ~8-10 → ~3-7 (Portfolio Construction)
    """

    @workflow.run
    async def run(
        self,
        portfolio_value: float = DEFAULT_PORTFOLIO_VALUE,
        market_regime: str = "risk_on",
    ) -> Phase7PipelineResult:
        """Execute Phase 5 + 6 + 7 pipeline."""
        workflow.logger.info("Starting Phase 7 Pipeline (Full Risk Management)")

        try:
            # Import here to avoid circular imports
            from trade_analyzer.workflows.risk_geometry import RiskGeometryWorkflow
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
                return Phase7PipelineResult(
                    success=False,
                    fundamental_qualified=0,
                    institutional_qualified=0,
                    risk_qualified=0,
                    final_positions=0,
                    total_invested_pct=0,
                    total_risk_pct=0,
                    cash_reserve_pct=0,
                    sector_allocation={},
                    positions=[],
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
                return Phase7PipelineResult(
                    success=False,
                    fundamental_qualified=fund_result.fundamental_qualified,
                    institutional_qualified=fund_result.institutional_qualified,
                    risk_qualified=0,
                    final_positions=0,
                    total_invested_pct=0,
                    total_risk_pct=0,
                    cash_reserve_pct=0,
                    sector_allocation={},
                    positions=[],
                    error=f"Risk Geometry failed: {risk_result.error}",
                )

            workflow.logger.info(
                f"Risk Geometry complete: {risk_result.risk_qualified} risk-qualified"
            )

            # Phase 7: Portfolio Construction
            workflow.logger.info("=== Phase 7: Portfolio Construction ===")

            portfolio_result = await workflow.execute_child_workflow(
                PortfolioConstructionWorkflow.run,
                args=[
                    portfolio_value,
                    0.70,  # max_correlation
                    3,  # max_per_sector
                    MAX_SECTOR_PCT,
                    MAX_POSITIONS,
                    3,  # min_positions
                    CASH_RESERVE_PCT,
                    market_regime,
                ],
                id=f"portfolio-construction-{workflow.info().workflow_id}",
            )

            if not portfolio_result.success:
                return Phase7PipelineResult(
                    success=False,
                    fundamental_qualified=fund_result.fundamental_qualified,
                    institutional_qualified=fund_result.institutional_qualified,
                    risk_qualified=risk_result.risk_qualified,
                    final_positions=0,
                    total_invested_pct=0,
                    total_risk_pct=0,
                    cash_reserve_pct=0,
                    sector_allocation={},
                    positions=[],
                    error=f"Portfolio Construction failed: {portfolio_result.error}",
                )

            workflow.logger.info(
                f"Portfolio Construction complete: {portfolio_result.final_positions} final positions"
            )

            return Phase7PipelineResult(
                success=True,
                fundamental_qualified=fund_result.fundamental_qualified,
                institutional_qualified=fund_result.institutional_qualified,
                risk_qualified=risk_result.risk_qualified,
                final_positions=portfolio_result.final_positions,
                total_invested_pct=portfolio_result.total_invested_pct,
                total_risk_pct=portfolio_result.total_risk_pct,
                cash_reserve_pct=portfolio_result.cash_reserve_pct,
                sector_allocation=portfolio_result.sector_allocation,
                positions=portfolio_result.positions,
            )

        except Exception as e:
            workflow.logger.error(f"Phase 7 Pipeline failed: {e}")
            return Phase7PipelineResult(
                success=False,
                fundamental_qualified=0,
                institutional_qualified=0,
                risk_qualified=0,
                final_positions=0,
                total_invested_pct=0,
                total_risk_pct=0,
                cash_reserve_pct=0,
                sector_allocation={},
                positions=[],
                error=str(e),
            )

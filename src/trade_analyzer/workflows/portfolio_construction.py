"""Portfolio Construction workflow for Phase 7.

This module implements Phase 7 of the trading pipeline (now Phase 6 after
fundamental consolidation), which constructs the final portfolio by applying
correlation and sector diversification constraints.

Pipeline Position: Phase 7 (now Phase 6) - Portfolio Construction
-----------------------------------------------------------------
Input: Position-sized setups from Phase 6 (~8-10 positions)
Output: Final portfolio allocation (3-7 positions)

This is the FINAL filter that produces the actual trading portfolio by ensuring
proper diversification and risk distribution across sectors and correlations.

Workflow Flow:
1. Fetch position-sized setups from Phase 6 risk_geometry collection
2. Calculate 60-day correlation matrix for all symbols
3. Apply correlation filter (remove highly correlated pairs)
4. Apply sector limits (max 3 per sector, 25% max exposure)
5. Construct final portfolio with position limits and cash reserve
6. Save to MongoDB portfolio_allocations collection

5 Portfolio Constraints:
1. Correlation Filter: Max 0.70 between any two positions
2. Sector Limits: Max 3 positions per sector
3. Sector Exposure: Max 25% of portfolio in single sector
4. Position Limits: Max 12 (Risk-On), 5 (Choppy), 0 (Risk-Off)
5. Cash Reserve: Maintain 25-35% cash buffer

Correlation Filter Logic:
- Calculate 60-day rolling correlation for all pairs
- If correlation > 0.70, remove lower-scored position
- Ensures portfolio isn't overexposed to single market factor

Sector Diversification:
- Max 3 positions per sector (prevents sector concentration)
- Max 25% exposure per sector (by capital allocation)
- Prioritizes high-quality setups across diverse sectors

Cash Reserve Management:
- Target: 30% cash reserve
- Min: 25% (aggressive deployment)
- Max: 35% (conservative, few opportunities)
- Never fully deploy capital (risk management buffer)

Typical Funnel:
~8-10 risk-qualified -> ~6-8 after correlation -> ~5-7 after sector -> 3-7 final

Inputs:
- portfolio_value: Total portfolio value (default 10L INR)
- max_correlation: Max allowed correlation (default 0.70)
- max_per_sector: Max positions per sector (default 3)
- max_sector_pct: Max sector exposure (default 0.25)
- max_positions: Max total positions (default 12)
- min_positions: Min for valid portfolio (default 3)
- cash_reserve_pct: Target cash reserve (default 0.30)
- market_regime: Current regime (default risk_on)

Outputs:
- PortfolioConstructionResult containing:
  - setups_input: Input positions from Phase 6
  - after_correlation_filter: Positions after correlation filter
  - after_sector_limits: Positions after sector limits
  - final_positions: Final portfolio positions (3-7)
  - total_invested_pct: Capital deployed (%)
  - total_risk_pct: Portfolio risk (%)
  - cash_reserve_pct: Cash reserve (%)
  - sector_allocation: Breakdown by sector
  - positions: Full position details
  - status: Portfolio status (valid/no_setups/insufficient)

Retry Policy:
- Initial interval: 2 seconds
- Maximum interval: 60 seconds
- Maximum attempts: 3
- Backoff coefficient: 2.0

Typical Runtime: 5-8 minutes

Related Workflows:
- RiskGeometryWorkflow (Phase 6): Provides input
- WeeklyRecommendationWorkflow (Phase 8): Uses output
- Phase7PipelineWorkflow: Orchestrates Phase 5+6+7
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
    """Result of portfolio construction workflow.

    Attributes:
        success: True if workflow completed without errors
        setups_input: Input positions from Phase 6
        after_correlation_filter: Positions after correlation filter
        after_sector_limits: Positions after sector limits
        final_positions: Final portfolio positions (3-7 target)
        total_invested_pct: Percentage of capital deployed
        total_risk_pct: Total portfolio risk as % of capital
        cash_reserve_pct: Cash reserve percentage (target 25-35%)
        sector_allocation: Breakdown by sector {sector: {count, pct}}
        positions: Full position details with entry/stop/target/size
        status: Portfolio status (valid/no_setups/insufficient/error)
        error: Error message if workflow failed, None otherwise
    """

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
    """Workflow for Phase 7 (now Phase 6): Portfolio Construction.

    This workflow orchestrates final portfolio construction by applying
    correlation and sector diversification filters to create a balanced,
    risk-managed portfolio.

    Activities Orchestrated:
    1. fetch_position_sized_setups: Gets positions from Phase 6
    2. calculate_correlation_matrix: Calculates 60-day correlations
    3. apply_correlation_filter: Removes highly correlated pairs
    4. apply_sector_limits: Enforces sector concentration limits
    5. construct_final_portfolio: Builds final portfolio with constraints
    6. save_portfolio_allocation: Saves to MongoDB portfolio_allocations

    5 Portfolio Constraints Applied:
    1. Correlation: Max 0.70 between any two positions
    2. Sector Count: Max 3 positions per sector
    3. Sector Exposure: Max 25% of portfolio in single sector
    4. Position Limits: Max 12 (Risk-On), 5 (Choppy), 0 (Risk-Off)
    5. Cash Reserve: Maintain 25-35% buffer

    Diversification Logic:
    - Prioritizes uncorrelated positions (correlation < 0.70)
    - Distributes across sectors (no concentration)
    - Balances position sizes (no single oversized position)
    - Maintains cash buffer (risk management)

    Error Handling:
    - Returns no_setups status if no input positions
    - Returns insufficient status if < min_positions
    - Continues processing even if some calculations fail
    - Partial results with error flag

    Returns:
        PortfolioConstructionResult with final portfolio allocation
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

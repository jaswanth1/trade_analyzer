"""Execution workflows for Phase 8.

This module implements Phase 8 execution workflows that provide real-time
trade monitoring and gap analysis. These are DISPLAY ONLY workflows - no
actual order placement or broker integration.

Pipeline Position: Phase 8 - Execution Display & Monitoring
-----------------------------------------------------------
Input: Final portfolio from Phase 7 (3-7 positions)
Output: Trade execution guidance and position monitoring

This module provides THREE workflow types for different weekday activities:
1. PreMarketAnalysisWorkflow: Monday 8:30-9:15 AM gap analysis
2. PositionStatusWorkflow: Intraday position status updates
3. FridayCloseWorkflow: End-of-week summary and system health

IMPORTANT: This is UI display only - no actual order placement or broker API
integration. User must manually execute trades based on recommendations.

Workflow 1: PreMarketAnalysisWorkflow (Monday 8:30-9:15 AM)
-----------------------------------------------------------
Analyzes Monday opening gaps and determines entry actions for each setup.

Gap Contingency Rules:
- Gap through stop (< stop_loss): SKIP (invalidated)
- Small gap against (<2% below entry): ENTER_AT_OPEN (acceptable)
- Gap above entry (>2% above): SKIP (don't chase)
- Within entry zone: ENTER (normal entry)

Outputs:
- Gap analysis for each position
- Sector momentum assessment
- Entry/Skip/Wait recommendations

Workflow 2: PositionStatusWorkflow (Intraday)
---------------------------------------------
Updates current position status, P&L, and alerts throughout trading day.

Monitors:
- Current price vs entry/stop/targets
- Unrealized P&L (INR and R-multiples)
- Stop-loss proximity alerts
- Target achievement notifications

Outputs:
- Position status (in_profit/in_loss/stopped_out/target_hit)
- Current P&L and R-multiples
- Real-time alerts

Workflow 3: FridayCloseWorkflow (Friday Close)
----------------------------------------------
Generates end-of-week summary with system health assessment.

Calculates:
- Weekly P&L (realized + unrealized)
- Win rate and R-multiple statistics
- System health score (0-100)
- Recommended action (CONTINUE/REDUCE/PAUSE/STOP)

System Health Scoring:
- Score >= 70: CONTINUE normally
- Score 50-70: REDUCE sizes, review parameters
- Score 30-50: PAUSE new trades, paper trade only
- Score < 30: STOP trading, full system review

Health Metrics:
- Win rate (12W and 52W)
- Expectancy (12W)
- Average slippage
- Current drawdown
- Consistency vs backtest

Outputs:
- Weekly performance summary
- Open/closed positions
- System health score
- Recommended action

Retry Policy (All Workflows):
- Initial interval: 2 seconds
- Maximum interval: 30 seconds
- Maximum attempts: 3
- Backoff coefficient: 2.0

Typical Runtimes:
- PreMarket: 2-3 minutes
- Position Status: 1-2 minutes
- Friday Close: 3-5 minutes

Related Workflows:
- PortfolioConstructionWorkflow (Phase 7): Provides input
- WeeklyRecommendationWorkflow (Phase 8): Parallel workflow
- ExecutionDisplayWorkflow: Master execution coordinator
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from trade_analyzer.activities.execution import (
        analyze_monday_gaps,
        calculate_sector_momentum,
        calculate_system_health,
        fetch_current_prices,
        generate_friday_summary,
        save_monday_premarket_analysis,
        update_position_status,
    )
    from trade_analyzer.activities.portfolio_construction import (
        get_latest_portfolio_allocation,
    )


@dataclass
class PreMarketAnalysisResult:
    """Result of pre-market analysis workflow.

    Attributes:
        success: True if workflow completed without errors
        analysis_date: ISO format date of analysis
        nifty_gap_pct: Nifty 50 gap percentage vs previous close
        total_setups: Total setups analyzed
        enter_count: Setups recommended to ENTER
        skip_count: Setups recommended to SKIP
        wait_count: Setups recommended to WAIT
        gap_analyses: Detailed gap analysis per setup
        sector_momentum: Sector-wise momentum assessment
        error: Error message if workflow failed, None otherwise
    """

    success: bool
    analysis_date: str
    nifty_gap_pct: float
    total_setups: int
    enter_count: int
    skip_count: int
    wait_count: int
    gap_analyses: list[dict]
    sector_momentum: dict
    error: str | None = None


@workflow.defn
class PreMarketAnalysisWorkflow:
    """Monday Pre-Market Analysis Workflow.

    This workflow analyzes Monday opening gaps for all weekend recommendations
    and determines entry/skip/wait actions based on gap contingency rules.

    Activities Orchestrated:
    1. get_latest_portfolio_allocation: Gets weekend recommendations
    2. fetch_current_prices: Gets pre-market/opening prices
    3. analyze_monday_gaps: Applies gap contingency logic
    4. calculate_sector_momentum: Assesses sector strength
    5. save_monday_premarket_analysis: Saves to MongoDB

    Gap Contingency Rules:
    - Gap through stop (< stop_loss): SKIP (setup invalidated)
    - Small gap against (<2% below entry): ENTER_AT_OPEN (acceptable)
    - Gap above entry (>2% above): SKIP (don't chase, wait for pullback)
    - Within entry zone: ENTER (normal entry as planned)

    Timing: Should be run Monday 8:30-9:15 AM IST (pre-market window)

    Error Handling:
    - Returns empty result if no portfolio found
    - Continues even if some prices unavailable
    - Partial results with error flag

    Returns:
        PreMarketAnalysisResult with gap analysis and recommendations
    """

    @workflow.run
    async def run(
        self,
        gap_threshold_pct: float = 2.0,
    ) -> PreMarketAnalysisResult:
        """
        Execute pre-market analysis workflow.

        Args:
            gap_threshold_pct: Threshold for significant gap
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=30),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting Pre-Market Analysis Workflow (Monday)")

        try:
            # Step 1: Get latest portfolio allocation
            workflow.logger.info("Step 1: Fetching portfolio allocation...")
            portfolio = await workflow.execute_activity(
                get_latest_portfolio_allocation,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            if not portfolio or not portfolio.get("positions"):
                return PreMarketAnalysisResult(
                    success=True,
                    analysis_date=datetime.utcnow().isoformat(),
                    nifty_gap_pct=0,
                    total_setups=0,
                    enter_count=0,
                    skip_count=0,
                    wait_count=0,
                    gap_analyses=[],
                    sector_momentum={},
                    error="No portfolio allocation found. Run Portfolio Construction first.",
                )

            positions = portfolio["positions"]
            symbols = [p["symbol"] for p in positions]
            workflow.logger.info(f"Found {len(positions)} positions to analyze")

            # Step 2: Fetch current prices
            workflow.logger.info("Step 2: Fetching current prices...")
            prices = await workflow.execute_activity(
                fetch_current_prices,
                args=[symbols],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Step 3: Analyze gaps
            workflow.logger.info("Step 3: Analyzing Monday gaps...")
            gap_analyses = await workflow.execute_activity(
                analyze_monday_gaps,
                args=[positions, prices, gap_threshold_pct],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Step 4: Calculate sector momentum
            workflow.logger.info("Step 4: Calculating sector momentum...")
            sector_momentum = await workflow.execute_activity(
                calculate_sector_momentum,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )

            # Step 5: Save analysis
            workflow.logger.info("Step 5: Saving pre-market analysis...")
            await workflow.execute_activity(
                save_monday_premarket_analysis,
                args=[gap_analyses, sector_momentum],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            # Calculate counts
            enter_count = sum(1 for a in gap_analyses if a["action"] in ["ENTER", "ENTER_AT_OPEN"])
            skip_count = sum(1 for a in gap_analyses if a["action"] == "SKIP")
            wait_count = sum(1 for a in gap_analyses if a["action"] == "WAIT")

            # Estimate Nifty gap
            nifty_gap = 0
            if "Financial Services" in sector_momentum:
                nifty_gap = sector_momentum["Financial Services"].get("week_change_pct", 0)

            workflow.logger.info(
                f"Pre-market analysis complete: {enter_count} ENTER, "
                f"{skip_count} SKIP, {wait_count} WAIT"
            )

            return PreMarketAnalysisResult(
                success=True,
                analysis_date=datetime.utcnow().isoformat(),
                nifty_gap_pct=nifty_gap,
                total_setups=len(positions),
                enter_count=enter_count,
                skip_count=skip_count,
                wait_count=wait_count,
                gap_analyses=gap_analyses,
                sector_momentum=sector_momentum,
            )

        except Exception as e:
            workflow.logger.error(f"Pre-market analysis failed: {e}")
            return PreMarketAnalysisResult(
                success=False,
                analysis_date=datetime.utcnow().isoformat(),
                nifty_gap_pct=0,
                total_setups=0,
                enter_count=0,
                skip_count=0,
                wait_count=0,
                gap_analyses=[],
                sector_momentum={},
                error=str(e),
            )


@dataclass
class PositionStatusResult:
    """Result of position status workflow."""

    success: bool
    total_positions: int
    in_profit: int
    in_loss: int
    stopped_out: int
    target_hit: int
    total_pnl: float
    total_r_multiple: float
    positions: list[dict]
    alerts: list[str]
    error: str | None = None


@workflow.defn
class PositionStatusWorkflow:
    """
    Intraday Position Status Workflow.

    Updates current status of all open positions,
    calculates P&L, and generates alerts.
    """

    @workflow.run
    async def run(self) -> PositionStatusResult:
        """Execute position status update workflow."""
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=30),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting Position Status Workflow")

        try:
            # Step 1: Get open positions from trades collection
            from trade_analyzer.db.connection import get_database

            db = get_database()
            trades_cursor = db["trades"].find({"status": "open"})
            open_trades = list(trades_cursor)

            if not open_trades:
                # Fall back to latest portfolio allocation
                portfolio = await workflow.execute_activity(
                    get_latest_portfolio_allocation,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=retry_policy,
                )

                if portfolio and portfolio.get("positions"):
                    open_trades = portfolio["positions"]
                else:
                    return PositionStatusResult(
                        success=True,
                        total_positions=0,
                        in_profit=0,
                        in_loss=0,
                        stopped_out=0,
                        target_hit=0,
                        total_pnl=0,
                        total_r_multiple=0,
                        positions=[],
                        alerts=["No open positions"],
                    )

            symbols = [t.get("symbol") for t in open_trades if t.get("symbol")]
            workflow.logger.info(f"Found {len(symbols)} open positions")

            # Step 2: Fetch current prices
            workflow.logger.info("Step 2: Fetching current prices...")
            prices = await workflow.execute_activity(
                fetch_current_prices,
                args=[symbols],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Step 3: Update position statuses
            workflow.logger.info("Step 3: Updating position statuses...")
            statuses = await workflow.execute_activity(
                update_position_status,
                args=[open_trades, prices],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Calculate aggregates
            in_profit = sum(1 for s in statuses if s.get("status") == "in_profit")
            in_loss = sum(1 for s in statuses if s.get("status") == "in_loss")
            stopped_out = sum(1 for s in statuses if s.get("status") == "stopped_out")
            target_hit = sum(1 for s in statuses if "target" in s.get("status", ""))

            total_pnl = sum(s.get("current_pnl", 0) for s in statuses)
            total_r = sum(s.get("current_r_multiple", 0) for s in statuses)

            # Collect all alerts
            all_alerts = []
            for s in statuses:
                all_alerts.extend(s.get("alerts", []))

            workflow.logger.info(
                f"Position status: {in_profit} profit, {in_loss} loss, "
                f"Rs.{total_pnl:,.0f} P&L, {len(all_alerts)} alerts"
            )

            return PositionStatusResult(
                success=True,
                total_positions=len(statuses),
                in_profit=in_profit,
                in_loss=in_loss,
                stopped_out=stopped_out,
                target_hit=target_hit,
                total_pnl=round(total_pnl, 2),
                total_r_multiple=round(total_r, 2),
                positions=statuses,
                alerts=all_alerts,
            )

        except Exception as e:
            workflow.logger.error(f"Position status update failed: {e}")
            return PositionStatusResult(
                success=False,
                total_positions=0,
                in_profit=0,
                in_loss=0,
                stopped_out=0,
                target_hit=0,
                total_pnl=0,
                total_r_multiple=0,
                positions=[],
                alerts=[],
                error=str(e),
            )


@dataclass
class FridayCloseResult:
    """Result of Friday close workflow."""

    success: bool
    week_start: str
    week_end: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    total_r: float
    system_health_score: int
    recommended_action: str
    open_positions: list[dict]
    closed_positions: list[dict]
    error: str | None = None


@workflow.defn
class FridayCloseWorkflow:
    """
    Friday Close Summary Workflow.

    Generates end-of-week summary including:
    - P&L for the week
    - Win rate and R-multiples
    - System health assessment
    - Recommendations for next week
    """

    @workflow.run
    async def run(
        self,
        week_start: datetime | None = None,
    ) -> FridayCloseResult:
        """
        Execute Friday close summary workflow.

        Args:
            week_start: Start of the week (Monday). Defaults to this week.
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=30),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting Friday Close Workflow")

        try:
            # Calculate week start if not provided
            if week_start is None:
                today = datetime.utcnow()
                days_since_monday = today.weekday()
                week_start = today - timedelta(days=days_since_monday)
                week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

            workflow.logger.info(f"Generating summary for week starting {week_start}")

            # Step 1: Generate Friday summary
            summary = await workflow.execute_activity(
                generate_friday_summary,
                args=[week_start],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Step 2: Calculate system health (if not in summary)
            system_health = summary.get("system_health", {})
            if not system_health:
                system_health = await workflow.execute_activity(
                    calculate_system_health,
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=retry_policy,
                )

            workflow.logger.info(
                f"Friday summary: {summary['win_rate']:.0f}% WR, "
                f"Rs.{summary['total_pnl']:,.0f} P&L, "
                f"Health: {system_health.get('health_score', 0)}/100"
            )

            return FridayCloseResult(
                success=True,
                week_start=summary["week_start"],
                week_end=summary["week_end"],
                total_trades=summary["total_trades"],
                wins=summary["wins"],
                losses=summary["losses"],
                win_rate=summary["win_rate"],
                realized_pnl=summary["realized_pnl"],
                unrealized_pnl=summary["unrealized_pnl"],
                total_pnl=summary["total_pnl"],
                total_r=summary["total_r"],
                system_health_score=system_health.get("health_score", 0),
                recommended_action=system_health.get("recommended_action", "CONTINUE"),
                open_positions=summary["open_positions"],
                closed_positions=summary["closed_positions"],
            )

        except Exception as e:
            workflow.logger.error(f"Friday close workflow failed: {e}")
            return FridayCloseResult(
                success=False,
                week_start="",
                week_end="",
                total_trades=0,
                wins=0,
                losses=0,
                win_rate=0,
                realized_pnl=0,
                unrealized_pnl=0,
                total_pnl=0,
                total_r=0,
                system_health_score=0,
                recommended_action="STOP",
                open_positions=[],
                closed_positions=[],
                error=str(e),
            )


@dataclass
class ExecutionDisplayResult:
    """Result of full execution display workflow."""

    success: bool
    premarket: PreMarketAnalysisResult | None
    position_status: PositionStatusResult | None
    friday_summary: FridayCloseResult | None
    error: str | None = None


@workflow.defn
class ExecutionDisplayWorkflow:
    """
    Combined Execution Display Workflow.

    Runs appropriate analysis based on day of week:
    - Monday: Pre-market gap analysis
    - Weekdays: Position status updates
    - Friday: Week summary
    """

    @workflow.run
    async def run(
        self,
        force_premarket: bool = False,
        force_friday: bool = False,
    ) -> ExecutionDisplayResult:
        """
        Execute appropriate analysis based on day.

        Args:
            force_premarket: Force pre-market analysis regardless of day
            force_friday: Force Friday summary regardless of day
        """
        workflow.logger.info("Starting Execution Display Workflow")

        try:
            today = datetime.utcnow()
            day_of_week = today.weekday()  # 0=Monday, 4=Friday

            premarket_result = None
            position_result = None
            friday_result = None

            # Monday or forced pre-market
            if day_of_week == 0 or force_premarket:
                workflow.logger.info("Running pre-market analysis...")
                premarket_result = await workflow.execute_child_workflow(
                    PreMarketAnalysisWorkflow.run,
                    args=[2.0],  # gap_threshold_pct
                    id=f"premarket-{workflow.info().workflow_id}",
                )

            # Always run position status (weekdays)
            if day_of_week < 5:
                workflow.logger.info("Running position status update...")
                position_result = await workflow.execute_child_workflow(
                    PositionStatusWorkflow.run,
                    id=f"position-status-{workflow.info().workflow_id}",
                )

            # Friday or forced summary
            if day_of_week == 4 or force_friday:
                workflow.logger.info("Running Friday close summary...")
                friday_result = await workflow.execute_child_workflow(
                    FridayCloseWorkflow.run,
                    id=f"friday-close-{workflow.info().workflow_id}",
                )

            return ExecutionDisplayResult(
                success=True,
                premarket=premarket_result,
                position_status=position_result,
                friday_summary=friday_result,
            )

        except Exception as e:
            workflow.logger.error(f"Execution display workflow failed: {e}")
            return ExecutionDisplayResult(
                success=False,
                premarket=None,
                position_status=None,
                friday_summary=None,
                error=str(e),
            )

"""
Universe refresh worker for Trade Analyzer.

This is the main Temporal worker process that handles all workflow and activity
execution for the trade analysis pipeline. It registers all workflows and activities
across all 8 phases of the system.

Worker Role:
    - Polls Temporal task queue for workflow/activity tasks
    - Executes all phases: Universe Setup, Momentum, Consistency, Volume,
      Setup Detection, Fundamental, Risk Geometry, Portfolio Construction,
      Execution Display, and Weekly Recommendations
    - Handles retry policies, timeouts, and error recovery
    - Runs continuously until interrupted

Workflows Handled:
    - Phase 1: UniverseRefreshWorkflow, UniverseSetupWorkflow, FundamentalDataRefreshWorkflow
    - Phase 2: MomentumFilterWorkflow, UniverseAndMomentumWorkflow
    - Phase 3: ConsistencyFilterWorkflow, FullPipelineWorkflow
    - Phase 4: VolumeFilterWorkflow, SetupDetectionWorkflow, Phase4PipelineWorkflow
    - Phase 5: RiskGeometryWorkflow (was Phase 6)
    - Phase 6: PortfolioConstructionWorkflow (was Phase 7)
    - Phase 7: PreMarketAnalysisWorkflow, PositionStatusWorkflow, FridayCloseWorkflow (was Phase 8)
    - Phase 8: WeeklyRecommendationWorkflow (was Phase 9)

Activities Registered:
    - Universe setup: fetch NSE instruments, MTF data, Nifty indices
    - Momentum: fetch market data, calculate momentum scores
    - Consistency: fetch weekly data, detect regime, calculate consistency scores
    - Volume: calculate liquidity metrics
    - Setup detection: detect technical patterns, rank setups
    - Fundamental: fetch fundamental data, institutional holdings
    - Risk geometry: calculate position sizes, risk metrics
    - Portfolio: correlation analysis, sector limits, portfolio construction
    - Execution: gap analysis, position status, system health
    - Recommendations: aggregate results, generate recommendations

Task Queue:
    - TASK_QUEUE_UNIVERSE_REFRESH (configurable)
    - Default: "trade-analyzer-queue"

Usage:
    Run via CLI:
        $ python -m trade_analyzer.workers.universe_worker

    Or via Make:
        $ make worker

Architecture Notes:
    - Long-running process (runs until interrupted)
    - Auto-reconnects to Temporal on connection loss
    - All activities are idempotent (safe to retry)
    - Workflows use retry policies for transient failures
"""

import asyncio
import logging

from temporalio.worker import Worker

from trade_analyzer.activities.universe import (
    get_universe_stats,
    refresh_mtf_instruments,
    refresh_nse_instruments,
    save_instruments_to_db,
)
from trade_analyzer.activities.universe_setup import (
    enrich_and_score_universe,
    fetch_base_universe,
    fetch_nifty_indices,
    save_enriched_universe,
)
from trade_analyzer.activities.momentum import (
    calculate_momentum_scores,
    fetch_high_quality_symbols,
    fetch_market_data_batch,
    fetch_nifty_benchmark_data,
    save_momentum_results,
)
from trade_analyzer.activities.consistency import (
    calculate_consistency_scores,
    detect_current_regime,
    fetch_momentum_qualified_symbols,
    fetch_weekly_data_batch,
    save_consistency_results,
)
from trade_analyzer.activities.volume_liquidity import (
    calculate_volume_liquidity_batch,
    fetch_consistency_qualified_symbols,
    filter_by_liquidity,
    get_liquidity_qualified_symbols,
    save_liquidity_results,
)
from trade_analyzer.activities.setup_detection import (
    detect_setups_batch,
    enrich_setups_with_context,
    fetch_liquidity_qualified_symbols,
    filter_and_rank_setups,
    get_active_setups,
    save_setup_results,
)
# Fundamental activities (monthly refresh + Phase 1 filter)
from trade_analyzer.activities.fundamental import (
    apply_fundamental_filter,
    calculate_fundamental_scores,
    fetch_fundamental_data_batch,
    fetch_institutional_holdings_batch,
    fetch_setup_qualified_symbols,
    fetch_universe_for_fundamentals,
    get_fundamentally_qualified_for_momentum,
    get_fundamentally_qualified_symbols,
    save_fundamental_results,
)
# Phase 6: Risk Geometry
from trade_analyzer.activities.risk_geometry import (
    calculate_position_sizes,
    calculate_risk_geometry_batch,
    fetch_fundamentally_enriched_setups,
    save_risk_geometry_results,
)
# Phase 7: Portfolio Construction
from trade_analyzer.activities.portfolio_construction import (
    apply_correlation_filter,
    apply_sector_limits,
    calculate_correlation_matrix,
    construct_final_portfolio,
    fetch_position_sized_setups,
    get_latest_portfolio_allocation,
    save_portfolio_allocation,
)
# Phase 8: Execution
from trade_analyzer.activities.execution import (
    analyze_monday_gaps,
    calculate_sector_momentum,
    calculate_system_health,
    fetch_current_prices,
    generate_friday_summary,
    generate_position_alerts,
    get_latest_premarket_analysis,
    save_monday_premarket_analysis,
    update_position_status,
)
# Phase 9: Recommendations
from trade_analyzer.activities.recommendation import (
    aggregate_phase_results,
    approve_weekly_recommendation,
    expire_old_recommendations,
    generate_recommendation_templates,
    get_latest_weekly_recommendation,
    save_weekly_recommendation,
)
from trade_analyzer.config import TASK_QUEUE_UNIVERSE_REFRESH
from trade_analyzer.workers.client import get_temporal_client
from trade_analyzer.workflows.universe import UniverseRefreshWorkflow
from trade_analyzer.workflows.universe_setup import UniverseSetupWorkflow
from trade_analyzer.workflows.momentum_filter import (
    MomentumFilterWorkflow,
    UniverseAndMomentumWorkflow,
)
from trade_analyzer.workflows.consistency_filter import (
    ConsistencyFilterWorkflow,
    FullPipelineWorkflow,
)
from trade_analyzer.workflows.volume_filter import VolumeFilterWorkflow
from trade_analyzer.workflows.setup_detection import (
    SetupDetectionWorkflow,
    Phase4PipelineWorkflow,
    FullAnalysisPipelineWorkflow,
)
# Fundamental Data Refresh (monthly - runs independently)
from trade_analyzer.workflows.fundamental_filter import (
    FundamentalDataRefreshWorkflow,
    FundamentalFilterWorkflow,  # Backward compat alias
)
# Phase 6: Risk Geometry
from trade_analyzer.workflows.risk_geometry import (
    RiskGeometryWorkflow,
    Phase6PipelineWorkflow,
)
# Phase 7: Portfolio Construction
from trade_analyzer.workflows.portfolio_construction import (
    PortfolioConstructionWorkflow,
    Phase7PipelineWorkflow,
)
# Phase 8: Execution
from trade_analyzer.workflows.execution import (
    PreMarketAnalysisWorkflow,
    PositionStatusWorkflow,
    FridayCloseWorkflow,
    ExecutionDisplayWorkflow,
)
# Phase 9: Weekly Recommendations
from trade_analyzer.workflows.weekly_recommendation import (
    WeeklyRecommendationWorkflow,
    FullPipelineWorkflow as WeeklyFullPipelineWorkflow,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_universe_worker() -> None:
    """
    Run the universe refresh worker.

    This is the main worker function that:
    1. Connects to Temporal (Cloud or local)
    2. Registers all workflows and activities
    3. Starts polling the task queue for work
    4. Runs indefinitely until interrupted (Ctrl+C)

    The worker handles all 8 phases of the trading pipeline:
    - Phase 1: Universe setup + fundamental filter (weekly)
    - Phase 2: Momentum filter
    - Phase 3: Consistency filter + regime detection
    - Phase 4: Volume/liquidity + setup detection
    - Phase 5: Risk geometry
    - Phase 6: Portfolio construction
    - Phase 7: Execution display (pre-market, position status, Friday close)
    - Phase 8: Weekly recommendations

    Note:
        This is a long-running process. Use Ctrl+C to gracefully shutdown.
        All in-flight activities will complete before shutdown.

    Raises:
        Exception: If worker fails to connect to Temporal or encounters
                   fatal errors during execution.
    """
    logger.info("Starting Trade Analyzer Worker...")

    client = await get_temporal_client()
    logger.info(f"Connected to Temporal at {client.service_client.config.target_host}")

    worker = Worker(
        client,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
        workflows=[
            # Phase 1: Universe + Fundamentals (weekly filter uses cached data)
            UniverseRefreshWorkflow,
            UniverseSetupWorkflow,  # Now includes fundamental filter step
            FundamentalDataRefreshWorkflow,  # Monthly API refresh
            FundamentalFilterWorkflow,  # Backward compat alias
            # Phase 2: Momentum Filter
            MomentumFilterWorkflow,
            UniverseAndMomentumWorkflow,
            # Phase 3: Consistency Filter
            ConsistencyFilterWorkflow,
            FullPipelineWorkflow,
            # Phase 4: Volume/Liquidity + Setup Detection
            VolumeFilterWorkflow,
            SetupDetectionWorkflow,
            Phase4PipelineWorkflow,
            FullAnalysisPipelineWorkflow,
            # Phase 5: Risk Geometry (was Phase 6)
            RiskGeometryWorkflow,
            Phase6PipelineWorkflow,
            # Phase 6: Portfolio Construction (was Phase 7)
            PortfolioConstructionWorkflow,
            Phase7PipelineWorkflow,
            # Phase 7: Execution Display (was Phase 8)
            PreMarketAnalysisWorkflow,
            PositionStatusWorkflow,
            FridayCloseWorkflow,
            ExecutionDisplayWorkflow,
            # Phase 8: Weekly Recommendations (was Phase 9)
            WeeklyRecommendationWorkflow,
            WeeklyFullPipelineWorkflow,
        ],
        activities=[
            # Basic universe activities
            refresh_nse_instruments,
            refresh_mtf_instruments,
            save_instruments_to_db,
            get_universe_stats,
            # Universe setup activities
            fetch_base_universe,
            fetch_nifty_indices,
            enrich_and_score_universe,
            save_enriched_universe,
            # Momentum filter activities (Phase 2)
            fetch_high_quality_symbols,
            fetch_market_data_batch,
            fetch_nifty_benchmark_data,
            calculate_momentum_scores,
            save_momentum_results,
            # Consistency filter activities (Phase 3)
            fetch_momentum_qualified_symbols,
            fetch_weekly_data_batch,
            detect_current_regime,
            calculate_consistency_scores,
            save_consistency_results,
            # Volume & Liquidity filter activities (Phase 4A)
            fetch_consistency_qualified_symbols,
            calculate_volume_liquidity_batch,
            filter_by_liquidity,
            save_liquidity_results,
            get_liquidity_qualified_symbols,
            # Setup detection activities (Phase 4B)
            fetch_liquidity_qualified_symbols,
            detect_setups_batch,
            filter_and_rank_setups,
            enrich_setups_with_context,
            save_setup_results,
            get_active_setups,
            # Fundamental activities (Phase 1 filter + monthly refresh)
            apply_fundamental_filter,  # Phase 1: weekly filter using cached data
            fetch_universe_for_fundamentals,  # Monthly: get symbols to refresh
            get_fundamentally_qualified_for_momentum,  # Phase 2 input
            fetch_setup_qualified_symbols,  # Legacy
            fetch_fundamental_data_batch,
            calculate_fundamental_scores,
            fetch_institutional_holdings_batch,
            save_fundamental_results,
            get_fundamentally_qualified_symbols,
            # Risk geometry activities (Phase 5, was Phase 6)
            fetch_fundamentally_enriched_setups,
            calculate_risk_geometry_batch,
            calculate_position_sizes,
            save_risk_geometry_results,
            # Portfolio construction activities (Phase 6, was Phase 7)
            fetch_position_sized_setups,
            calculate_correlation_matrix,
            apply_correlation_filter,
            apply_sector_limits,
            construct_final_portfolio,
            save_portfolio_allocation,
            get_latest_portfolio_allocation,
            # Execution activities (Phase 7, was Phase 8)
            fetch_current_prices,
            analyze_monday_gaps,
            calculate_sector_momentum,
            update_position_status,
            generate_position_alerts,
            generate_friday_summary,
            calculate_system_health,
            save_monday_premarket_analysis,
            get_latest_premarket_analysis,
            # Recommendation activities (Phase 8, was Phase 9)
            aggregate_phase_results,
            generate_recommendation_templates,
            save_weekly_recommendation,
            get_latest_weekly_recommendation,
            approve_weekly_recommendation,
            expire_old_recommendations,
        ],
    )

    logger.info(f"Worker listening on task queue: {TASK_QUEUE_UNIVERSE_REFRESH}")
    await worker.run()


def main() -> None:
    """
    Entry point for the worker.

    This function is called when running the worker as a script or module.
    It starts the async event loop and runs the worker until interrupted.

    Usage:
        $ python -m trade_analyzer.workers.universe_worker
        $ make worker
    """
    asyncio.run(run_universe_worker())


if __name__ == "__main__":
    main()

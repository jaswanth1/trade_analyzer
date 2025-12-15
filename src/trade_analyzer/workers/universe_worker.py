"""Universe refresh worker for Trade Analyzer."""

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
# Phase 5: Fundamental Intelligence
from trade_analyzer.activities.fundamental import (
    calculate_fundamental_scores,
    fetch_fundamental_data_batch,
    fetch_institutional_holdings_batch,
    fetch_setup_qualified_symbols,
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
# Phase 5: Fundamental Intelligence
from trade_analyzer.workflows.fundamental_filter import (
    FundamentalFilterWorkflow,
    Phase5PipelineWorkflow,
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
    """Run the universe refresh worker."""
    logger.info("Starting Trade Analyzer Worker...")

    client = await get_temporal_client()
    logger.info(f"Connected to Temporal at {client.service_client.config.target_host}")

    worker = Worker(
        client,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
        workflows=[
            UniverseRefreshWorkflow,
            UniverseSetupWorkflow,
            MomentumFilterWorkflow,
            UniverseAndMomentumWorkflow,
            ConsistencyFilterWorkflow,
            FullPipelineWorkflow,
            # Phase 4 workflows
            VolumeFilterWorkflow,
            SetupDetectionWorkflow,
            Phase4PipelineWorkflow,
            FullAnalysisPipelineWorkflow,
            # Phase 5 workflows
            FundamentalFilterWorkflow,
            Phase5PipelineWorkflow,
            # Phase 6 workflows
            RiskGeometryWorkflow,
            Phase6PipelineWorkflow,
            # Phase 7 workflows
            PortfolioConstructionWorkflow,
            Phase7PipelineWorkflow,
            # Phase 8 workflows
            PreMarketAnalysisWorkflow,
            PositionStatusWorkflow,
            FridayCloseWorkflow,
            ExecutionDisplayWorkflow,
            # Phase 9 workflows
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
            # Fundamental activities (Phase 5)
            fetch_setup_qualified_symbols,
            fetch_fundamental_data_batch,
            calculate_fundamental_scores,
            fetch_institutional_holdings_batch,
            save_fundamental_results,
            get_fundamentally_qualified_symbols,
            # Risk geometry activities (Phase 6)
            fetch_fundamentally_enriched_setups,
            calculate_risk_geometry_batch,
            calculate_position_sizes,
            save_risk_geometry_results,
            # Portfolio construction activities (Phase 7)
            fetch_position_sized_setups,
            calculate_correlation_matrix,
            apply_correlation_filter,
            apply_sector_limits,
            construct_final_portfolio,
            save_portfolio_allocation,
            get_latest_portfolio_allocation,
            # Execution activities (Phase 8)
            fetch_current_prices,
            analyze_monday_gaps,
            calculate_sector_momentum,
            update_position_status,
            generate_position_alerts,
            generate_friday_summary,
            calculate_system_health,
            save_monday_premarket_analysis,
            get_latest_premarket_analysis,
            # Recommendation activities (Phase 9)
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
    """Entry point for the worker."""
    asyncio.run(run_universe_worker())


if __name__ == "__main__":
    main()

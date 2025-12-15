"""Script to start Temporal workflows."""

import asyncio
import logging
import uuid

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
# Phase 5-9 workflows
from trade_analyzer.workflows.fundamental_filter import (
    FundamentalFilterWorkflow,
    Phase5PipelineWorkflow,
)
from trade_analyzer.workflows.risk_geometry import (
    RiskGeometryWorkflow,
    Phase6PipelineWorkflow,
)
from trade_analyzer.workflows.portfolio_construction import (
    PortfolioConstructionWorkflow,
    Phase7PipelineWorkflow,
)
from trade_analyzer.workflows.execution import (
    PreMarketAnalysisWorkflow,
    PositionStatusWorkflow,
    FridayCloseWorkflow,
    ExecutionDisplayWorkflow,
)
from trade_analyzer.workflows.weekly_recommendation import (
    WeeklyRecommendationWorkflow,
    FullPipelineWorkflow as WeeklyFullPipelineWorkflow,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def start_universe_setup() -> dict:
    """
    Start the universe setup workflow (full pipeline with enrichment).

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"universe-setup-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        UniverseSetupWorkflow.run,
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "total_nse_eq": result.total_nse_eq,
        "total_mtf": result.total_mtf,
        "high_quality_count": result.high_quality_count,
        "tier_a_count": result.tier_a_count,
        "tier_b_count": result.tier_b_count,
        "tier_c_count": result.tier_c_count,
        "error": result.error,
    }


async def start_universe_setup_async() -> str:
    """
    Start the universe setup workflow without waiting for completion.

    Returns:
        Workflow ID of the started workflow.
    """
    client = await get_temporal_client()

    workflow_id = f"universe-setup-{uuid.uuid4().hex[:8]}"

    handle = await client.start_workflow(
        UniverseSetupWorkflow.run,
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Started workflow {workflow_id}")
    return handle.id


async def start_universe_refresh() -> str:
    """
    Start the basic universe refresh workflow (deprecated - use setup).

    Returns:
        Workflow ID of the started workflow.
    """
    client = await get_temporal_client()

    workflow_id = f"universe-refresh-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        UniverseRefreshWorkflow.run,
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return workflow_id


async def start_momentum_filter() -> dict:
    """
    Start the momentum filter workflow.

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"momentum-filter-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        MomentumFilterWorkflow.run,
        args=[100],  # batch_size
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "total_analyzed": result.total_analyzed,
        "total_qualified": result.total_qualified,
        "avg_momentum_score": result.avg_momentum_score,
        "top_10": result.top_10,
        "nifty_return_3m": result.nifty_return_3m,
        "error": result.error,
    }


async def start_universe_and_momentum() -> dict:
    """
    Start the combined universe + momentum workflow.

    This is the main weekend workflow for Phase 2.

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"universe-momentum-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        UniverseAndMomentumWorkflow.run,
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "total_nse_eq": result.total_nse_eq,
        "total_mtf": result.total_mtf,
        "high_quality_count": result.high_quality_count,
        "momentum_analyzed": result.momentum_analyzed,
        "momentum_qualified": result.momentum_qualified,
        "avg_momentum_score": result.avg_momentum_score,
        "top_10": result.top_10,
        "nifty_return_3m": result.nifty_return_3m,
        "error": result.error,
    }


async def start_consistency_filter() -> dict:
    """
    Start the consistency filter workflow.

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"consistency-filter-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        ConsistencyFilterWorkflow.run,
        args=[50],  # batch_size
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "total_analyzed": result.total_analyzed,
        "total_qualified": result.total_qualified,
        "avg_final_score": result.avg_final_score,
        "avg_consistency_score": result.avg_consistency_score,
        "market_regime": result.market_regime,
        "top_10": result.top_10,
        "error": result.error,
    }


async def start_full_pipeline() -> dict:
    """
    Start the full pipeline workflow (Universe + Momentum + Consistency).

    This is the complete Phase 1-3 weekend workflow.

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"full-pipeline-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        FullPipelineWorkflow.run,
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "total_nse_eq": result.total_nse_eq,
        "high_quality_count": result.high_quality_count,
        "momentum_qualified": result.momentum_qualified,
        "consistency_qualified": result.consistency_qualified,
        "avg_final_score": result.avg_final_score,
        "market_regime": result.market_regime,
        "top_10": result.top_10,
        "error": result.error,
    }


async def start_volume_filter() -> dict:
    """
    Start the volume & liquidity filter workflow.

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"volume-filter-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        VolumeFilterWorkflow.run,
        args=[50],  # batch_size
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "total_analyzed": result.total_analyzed,
        "total_qualified": result.total_qualified,
        "avg_liquidity_score": result.avg_liquidity_score,
        "avg_turnover_20d": result.avg_turnover_20d,
        "top_10": result.top_10,
        "error": result.error,
    }


async def start_setup_detection() -> dict:
    """
    Start the setup detection workflow.

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"setup-detection-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        SetupDetectionWorkflow.run,
        args=[30, 2.0, 70],  # batch_size, min_rr, min_confidence
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "total_analyzed": result.total_analyzed,
        "total_setups_found": result.total_setups_found,
        "total_qualified": result.total_qualified,
        "setups_by_type": result.setups_by_type,
        "avg_confidence": result.avg_confidence,
        "avg_rr_ratio": result.avg_rr_ratio,
        "market_regime": result.market_regime,
        "top_setups": result.top_setups,
        "error": result.error,
    }


async def start_phase4_pipeline() -> dict:
    """
    Start the Phase 4 pipeline (Volume Filter + Setup Detection).

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"phase4-pipeline-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        Phase4PipelineWorkflow.run,
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "volume_analyzed": result.volume_analyzed,
        "volume_qualified": result.volume_qualified,
        "avg_liquidity_score": result.avg_liquidity_score,
        "setups_found": result.setups_found,
        "setups_qualified": result.setups_qualified,
        "setups_by_type": result.setups_by_type,
        "avg_confidence": result.avg_confidence,
        "avg_rr_ratio": result.avg_rr_ratio,
        "market_regime": result.market_regime,
        "top_setups": result.top_setups,
        "error": result.error,
    }


async def start_full_analysis_pipeline() -> dict:
    """
    Start the full analysis pipeline (Phase 1-4).

    This is the complete weekend workflow producing trade setups.

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"full-analysis-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        FullAnalysisPipelineWorkflow.run,
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "total_nse_eq": result.total_nse_eq,
        "high_quality_count": result.high_quality_count,
        "momentum_qualified": result.momentum_qualified,
        "consistency_qualified": result.consistency_qualified,
        "liquidity_qualified": result.liquidity_qualified,
        "setups_qualified": result.setups_qualified,
        "setups_by_type": result.setups_by_type,
        "market_regime": result.market_regime,
        "top_setups": result.top_setups,
        "error": result.error,
    }


# ============================================================================
# Phase 5: Fundamental Intelligence
# ============================================================================


async def start_fundamental_filter() -> dict:
    """
    Start the fundamental filter workflow.

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"fundamental-filter-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        FundamentalFilterWorkflow.run,
        args=[1.0],  # fetch_delay
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "symbols_analyzed": result.symbols_analyzed,
        "fundamental_qualified": result.fundamental_qualified,
        "institutional_qualified": result.institutional_qualified,
        "combined_qualified": result.combined_qualified,
        "avg_fundamental_score": result.avg_fundamental_score,
        "top_10": result.top_10,
        "error": result.error,
    }


# ============================================================================
# Phase 6: Risk Geometry
# ============================================================================


async def start_risk_geometry(
    portfolio_value: float = 1000000.0,
    market_regime: str = "risk_on",
) -> dict:
    """
    Start the risk geometry workflow.

    Args:
        portfolio_value: Total portfolio value
        market_regime: Current market regime

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"risk-geometry-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        RiskGeometryWorkflow.run,
        args=[portfolio_value, 0.015, 0.08, 12, 2.0, 2.5, 7.0, market_regime],
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "setups_analyzed": result.setups_analyzed,
        "risk_qualified": result.risk_qualified,
        "total_risk": result.total_risk,
        "total_value": result.total_value,
        "avg_rr_ratio": result.avg_rr_ratio,
        "top_positions": result.top_positions,
        "error": result.error,
    }


# ============================================================================
# Phase 7: Portfolio Construction
# ============================================================================


async def start_portfolio_construction(
    portfolio_value: float = 1000000.0,
    market_regime: str = "risk_on",
) -> dict:
    """
    Start the portfolio construction workflow.

    Args:
        portfolio_value: Total portfolio value
        market_regime: Current market regime

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"portfolio-construction-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        PortfolioConstructionWorkflow.run,
        args=[portfolio_value, 0.70, 3, 0.25, 12, 3, 0.30, market_regime],
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "setups_input": result.setups_input,
        "after_correlation_filter": result.after_correlation_filter,
        "after_sector_limits": result.after_sector_limits,
        "final_positions": result.final_positions,
        "total_invested_pct": result.total_invested_pct,
        "total_risk_pct": result.total_risk_pct,
        "cash_reserve_pct": result.cash_reserve_pct,
        "sector_allocation": result.sector_allocation,
        "positions": result.positions,
        "status": result.status,
        "error": result.error,
    }


async def start_phase7_pipeline(
    portfolio_value: float = 1000000.0,
    market_regime: str = "risk_on",
) -> dict:
    """
    Start the Phase 5-7 pipeline (Fundamental + Risk + Portfolio).

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"phase7-pipeline-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        Phase7PipelineWorkflow.run,
        args=[portfolio_value, market_regime],
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "fundamental_qualified": result.fundamental_qualified,
        "institutional_qualified": result.institutional_qualified,
        "risk_qualified": result.risk_qualified,
        "final_positions": result.final_positions,
        "total_invested_pct": result.total_invested_pct,
        "total_risk_pct": result.total_risk_pct,
        "cash_reserve_pct": result.cash_reserve_pct,
        "sector_allocation": result.sector_allocation,
        "positions": result.positions,
        "error": result.error,
    }


# ============================================================================
# Phase 8: Execution Display
# ============================================================================


async def start_premarket_analysis() -> dict:
    """
    Start the Monday pre-market analysis workflow.

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"premarket-analysis-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        PreMarketAnalysisWorkflow.run,
        args=[2.0],  # gap_threshold_pct
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "analysis_date": result.analysis_date,
        "total_setups": result.total_setups,
        "enter_count": result.enter_count,
        "skip_count": result.skip_count,
        "wait_count": result.wait_count,
        "gap_analyses": result.gap_analyses,
        "sector_momentum": result.sector_momentum,
        "error": result.error,
    }


async def start_position_status() -> dict:
    """
    Start the position status update workflow.

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"position-status-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        PositionStatusWorkflow.run,
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "total_positions": result.total_positions,
        "in_profit": result.in_profit,
        "in_loss": result.in_loss,
        "stopped_out": result.stopped_out,
        "target_hit": result.target_hit,
        "total_pnl": result.total_pnl,
        "total_r_multiple": result.total_r_multiple,
        "positions": result.positions,
        "alerts": result.alerts,
        "error": result.error,
    }


async def start_friday_close() -> dict:
    """
    Start the Friday close summary workflow.

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"friday-close-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        FridayCloseWorkflow.run,
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "week_start": result.week_start,
        "week_end": result.week_end,
        "total_trades": result.total_trades,
        "wins": result.wins,
        "losses": result.losses,
        "win_rate": result.win_rate,
        "realized_pnl": result.realized_pnl,
        "unrealized_pnl": result.unrealized_pnl,
        "total_pnl": result.total_pnl,
        "total_r": result.total_r,
        "system_health_score": result.system_health_score,
        "recommended_action": result.recommended_action,
        "error": result.error,
    }


# ============================================================================
# Phase 9: Weekly Recommendations
# ============================================================================


async def start_weekly_recommendation(
    portfolio_value: float = 1000000.0,
    run_full_pipeline: bool = False,
    market_regime: str | None = None,
) -> dict:
    """
    Start the weekly recommendation workflow.

    Args:
        portfolio_value: Total portfolio value
        run_full_pipeline: Whether to run Phase 5-7 first
        market_regime: Override regime (optional)

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"weekly-recommendation-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        WeeklyRecommendationWorkflow.run,
        args=[portfolio_value, run_full_pipeline, market_regime],
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed with result: {result}")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "week_display": result.week_display,
        "market_regime": result.market_regime,
        "regime_confidence": result.regime_confidence,
        "total_setups": result.total_setups,
        "allocated_capital": result.allocated_capital,
        "allocated_pct": result.allocated_pct,
        "total_risk_pct": result.total_risk_pct,
        "recommendations": result.recommendations,
        "error": result.error,
    }


async def start_complete_weekly_pipeline(
    portfolio_value: float = 1000000.0,
    market_regime: str = "risk_on",
) -> dict:
    """
    Start the complete end-to-end weekly pipeline (Phase 4B-9).

    This is the master weekend workflow producing final trade recommendations.

    Args:
        portfolio_value: Total portfolio value
        market_regime: Current market regime

    Returns:
        Result dict with workflow outcome.
    """
    client = await get_temporal_client()

    workflow_id = f"complete-weekly-{uuid.uuid4().hex[:8]}"

    result = await client.execute_workflow(
        WeeklyFullPipelineWorkflow.run,
        args=[portfolio_value, market_regime],
        id=workflow_id,
        task_queue=TASK_QUEUE_UNIVERSE_REFRESH,
    )

    logger.info(f"Workflow {workflow_id} completed")
    return {
        "workflow_id": workflow_id,
        "success": result.success,
        "phase_4_setups": result.phase_4_setups,
        "phase_5_fundamental": result.phase_5_fundamental,
        "phase_6_risk_qualified": result.phase_6_risk_qualified,
        "phase_7_final_positions": result.phase_7_final_positions,
        "week_display": result.week_display,
        "market_regime": result.market_regime,
        "regime_confidence": result.regime_confidence,
        "total_setups": result.total_setups,
        "allocated_capital": result.allocated_capital,
        "allocated_pct": result.allocated_pct,
        "total_risk_pct": result.total_risk_pct,
        "recommendations": result.recommendations,
        "error": result.error,
    }


def main() -> None:
    """Entry point to start universe setup workflow."""
    asyncio.run(start_universe_setup())


if __name__ == "__main__":
    main()

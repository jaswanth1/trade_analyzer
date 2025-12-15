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


def main() -> None:
    """Entry point to start universe setup workflow."""
    asyncio.run(start_universe_setup())


if __name__ == "__main__":
    main()

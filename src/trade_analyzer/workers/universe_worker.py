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
        ],
    )

    logger.info(f"Worker listening on task queue: {TASK_QUEUE_UNIVERSE_REFRESH}")
    await worker.run()


def main() -> None:
    """Entry point for the worker."""
    asyncio.run(run_universe_worker())


if __name__ == "__main__":
    main()

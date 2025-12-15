"""Universe refresh workflow for Trade Analyzer."""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from trade_analyzer.activities.universe import (
        InstrumentData,
        refresh_mtf_instruments,
        refresh_nse_instruments,
        save_instruments_to_db,
    )


@dataclass
class UniverseRefreshResult:
    """Result of universe refresh workflow."""

    success: bool
    nse_eq_count: int
    mtf_count: int
    saved_count: int
    error: str | None = None


@workflow.defn
class UniverseRefreshWorkflow:
    """
    Workflow to refresh the trading universe from Upstox.

    This workflow:
    1. Fetches NSE equity instruments
    2. Fetches MTF instruments
    3. Merges and saves to MongoDB
    """

    @workflow.run
    async def run(self) -> UniverseRefreshResult:
        """Execute the universe refresh workflow."""
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=30),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting universe refresh workflow")

        try:
            # Fetch NSE instruments
            nse_data: InstrumentData = await workflow.execute_activity(
                refresh_nse_instruments,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Fetched {nse_data.count} NSE EQ instruments")

            # Fetch MTF instruments
            mtf_data: InstrumentData = await workflow.execute_activity(
                refresh_mtf_instruments,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Fetched {mtf_data.count} MTF instruments")

            # Extract MTF symbols
            mtf_symbols = {
                inst.get("trading_symbol") for inst in mtf_data.instruments
            }

            # Save to database
            save_result = await workflow.execute_activity(
                save_instruments_to_db,
                args=[nse_data.instruments, mtf_symbols],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            workflow.logger.info(
                f"Universe refresh complete: {save_result['saved_count']} saved"
            )

            return UniverseRefreshResult(
                success=True,
                nse_eq_count=nse_data.count,
                mtf_count=mtf_data.count,
                saved_count=save_result["saved_count"],
            )

        except Exception as e:
            workflow.logger.error(f"Universe refresh failed: {e}")
            return UniverseRefreshResult(
                success=False,
                nse_eq_count=0,
                mtf_count=0,
                saved_count=0,
                error=str(e),
            )

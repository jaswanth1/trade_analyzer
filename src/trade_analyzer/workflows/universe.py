"""Universe refresh workflow for Trade Analyzer.

This module implements the basic universe refresh workflow that fetches
trading instruments from Upstox API and stores them in MongoDB.

Pipeline Position: Initial Data Setup (Pre-Phase 1)
---------------------------------------------------
This workflow is a prerequisite for the main pipeline. It should be run
before UniverseSetupWorkflow to ensure the database has fresh instrument data.

Workflow Flow:
1. Fetch NSE equity instruments from Upstox API
2. Fetch MTF (Margin Trading Facility) instruments from Upstox API
3. Merge NSE EQ and MTF data
4. Save instruments to MongoDB stocks collection

Inputs:
- None (fetches fresh data from Upstox API)

Outputs:
- UniverseRefreshResult containing:
  - success: Whether the workflow completed successfully
  - nse_eq_count: Number of NSE equity instruments fetched
  - mtf_count: Number of MTF instruments fetched
  - saved_count: Number of instruments saved to database
  - error: Error message if workflow failed

Retry Policy:
- Initial interval: 1 second
- Maximum interval: 30 seconds
- Maximum attempts: 3
- Backoff coefficient: 2.0

Typical Runtime: 1-2 minutes

Usage:
    This workflow should be run:
    - Once per week before weekend analysis (Saturday/Sunday)
    - After Upstox instrument master updates
    - When setting up a fresh database

Related Workflows:
- UniverseSetupWorkflow: Uses output from this workflow to create
  high-quality universe with scoring
"""

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
    """Result of universe refresh workflow.

    Attributes:
        success: True if workflow completed without errors
        nse_eq_count: Total NSE equity instruments fetched from Upstox
        mtf_count: Total MTF instruments fetched from Upstox
        saved_count: Total instruments saved to MongoDB stocks collection
        error: Error message if workflow failed, None otherwise
    """

    success: bool
    nse_eq_count: int
    mtf_count: int
    saved_count: int
    error: str | None = None


@workflow.defn
class UniverseRefreshWorkflow:
    """Workflow to refresh the trading universe from Upstox.

    This workflow orchestrates the fetching and storage of trading instruments
    from Upstox API. It runs three sequential activities with retry policies
    to ensure reliable data acquisition.

    Activities Orchestrated:
    1. refresh_nse_instruments: Fetches NSE equity instruments (NSE_EQ segment)
    2. refresh_mtf_instruments: Fetches MTF-eligible instruments
    3. save_instruments_to_db: Merges data and saves to MongoDB

    The workflow marks MTF stocks with is_mtf=True flag for prioritization
    in subsequent universe setup workflows.

    Error Handling:
    - Each activity has independent retry policy (3 attempts)
    - Workflow catches all exceptions and returns error result
    - Failed workflow does not modify existing database

    Returns:
        UniverseRefreshResult with counts and status
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

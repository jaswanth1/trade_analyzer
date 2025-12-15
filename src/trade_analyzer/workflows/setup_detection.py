"""Technical Setup Detection workflow for Phase 4B.

This module implements Phase 4B of the trading pipeline, which detects specific
technical setups with clear entry, stop, and target levels.

Pipeline Position: Phase 4B - Setup Detection
---------------------------------------------
Input: Liquidity-qualified stocks from Phase 4A (~15-25 stocks)
Output: Trade setups with risk geometry (~8-15 setups)

This is the FIFTH filter (Phase 4B) focusing on identifying actionable trade
setups with defined risk-reward profiles.

Workflow Flow:
1. Fetch liquidity-qualified symbols from Phase 4A
2. Detect current market regime for R:R adjustment
3. Detect technical setups (batched with rate limiting)
4. Filter by R:R ratio, confidence, stop distance
5. Enrich with context from previous phases
6. Save to MongoDB trade_setups collection

4 Setup Types Detected:
- A. PULLBACK: Trend pullback to rising moving averages (most common)
- B. VCP_BREAKOUT: Volatility contraction pattern breakout (high win rate)
- C. RETEST: Breakout retest / role reversal (lower risk)
- D. GAP_FILL: Gap-fill continuation play (rare but powerful)

Setup Requirements (all must pass):
- R:R Ratio >= 2.0 (Risk-On) or >= 2.5 (Choppy/Bear)
- Confidence >= 70 (pattern quality score)
- Stop Distance <= 7% from entry
- Clear entry zone defined
- Multiple exit targets (T1, T2)

Typical Funnel:
~15-25 liquid -> ~12-20 analyzed -> ~8-15 setups qualified

Inputs:
- batch_size: Stocks to process per batch (default 30)
- min_rr_ratio: Minimum R:R (default 2.0, adjusted by regime)
- min_confidence: Minimum setup confidence (default 70)

Outputs:
- SetupDetectionResult containing:
  - total_analyzed: Stocks analyzed
  - total_setups_found: Raw setups detected
  - total_qualified: Setups passing filters
  - setups_by_type: Count per setup type
  - avg_confidence: Average setup confidence
  - avg_rr_ratio: Average reward:risk ratio
  - market_regime: Current regime
  - top_setups: Top setups by composite score

Retry Policy:
- Initial interval: 2 seconds
- Maximum interval: 60 seconds
- Maximum attempts: 3
- Backoff coefficient: 2.0

Typical Runtime: 10-15 minutes

Related Workflows:
- VolumeFilterWorkflow (Phase 4A): Provides input
- RiskGeometryWorkflow (Phase 6): Uses output
- Phase4PipelineWorkflow: Orchestrates Phase 4A+4B
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from trade_analyzer.activities.consistency import detect_current_regime
    from trade_analyzer.activities.setup_detection import (
        detect_setups_batch,
        enrich_setups_with_context,
        fetch_liquidity_qualified_symbols,
        filter_and_rank_setups,
        save_setup_results,
    )
    from trade_analyzer.workflows.volume_filter import VolumeFilterWorkflow


@dataclass
class SetupDetectionResult:
    """Result of setup detection workflow.

    Attributes:
        success: True if workflow completed without errors
        total_analyzed: Total stocks analyzed for setups
        total_setups_found: Raw setups detected (before filtering)
        total_qualified: Setups passing R:R, confidence, stop filters
        setups_by_type: Count breakdown (PULLBACK, VCP_BREAKOUT, RETEST, GAP_FILL)
        avg_confidence: Average setup confidence score (0-100)
        avg_rr_ratio: Average reward:risk ratio across qualified setups
        market_regime: Current market regime (BULL/SIDEWAYS/BEAR)
        top_setups: Top setups by composite score (max 10)
        error: Error message if workflow failed, None otherwise
    """

    success: bool
    total_analyzed: int
    total_setups_found: int
    total_qualified: int
    setups_by_type: dict
    avg_confidence: float
    avg_rr_ratio: float
    market_regime: str
    top_setups: list[dict]
    error: str | None = None


@workflow.defn
class SetupDetectionWorkflow:
    """Workflow to detect technical trade setups (Phase 4B).

    This workflow orchestrates setup detection by analyzing price action
    patterns and calculating risk-reward geometry for each potential trade.

    Activities Orchestrated:
    1. fetch_liquidity_qualified_symbols: Gets stocks from Phase 4A
    2. detect_current_regime: Gets regime for R:R adjustment
    3. detect_setups_batch: Scans for 4 setup types with pattern matching
    4. filter_and_rank_setups: Applies R:R, confidence, stop filters
    5. enrich_setups_with_context: Adds scores from previous phases
    6. save_setup_results: Saves to MongoDB trade_setups collection

    4 Setup Types:
    - A. PULLBACK: Trend pullback to rising MA (most common, 50-60% of setups)
    - B. VCP_BREAKOUT: Volatility contraction breakout (highest win rate)
    - C. RETEST: Breakout retest/role reversal (cleanest entries)
    - D. GAP_FILL: Gap-fill continuation (rare but powerful)

    Setup Quality Scoring:
    - Pattern Clarity: 30% (clean vs messy)
    - Volume Confirmation: 25% (volume surge on setup day)
    - Trend Strength: 20% (MA alignment)
    - Support/Resistance: 15% (clear levels)
    - Risk-Reward: 10% (favorable R:R)

    Regime Adjustment:
    - Risk-On: min_rr = 2.0
    - Choppy/Bear: min_rr = 2.5 (higher bar)

    Error Handling:
    - Batched processing with retries
    - Returns setups even if some stocks fail
    - Partial results with error flag

    Returns:
        SetupDetectionResult with qualified setups and statistics
    """

    @workflow.run
    async def run(
        self,
        batch_size: int = 30,
        min_rr_ratio: float = 2.0,
        min_confidence: int = 70,
    ) -> SetupDetectionResult:
        """
        Execute the setup detection workflow.

        Args:
            batch_size: Number of stocks to process per batch
            min_rr_ratio: Minimum reward:risk ratio
            min_confidence: Minimum confidence score
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info("Starting Setup Detection Workflow (Phase 4B)")

        try:
            # Step 1: Get liquidity-qualified symbols from Phase 4A
            workflow.logger.info("Step 1: Fetching liquidity-qualified symbols...")
            symbols = await workflow.execute_activity(
                fetch_liquidity_qualified_symbols,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=retry_policy,
            )
            workflow.logger.info(f"Found {len(symbols)} liquidity-qualified stocks")

            if not symbols:
                return SetupDetectionResult(
                    success=False,
                    total_analyzed=0,
                    total_setups_found=0,
                    total_qualified=0,
                    setups_by_type={},
                    avg_confidence=0,
                    avg_rr_ratio=0,
                    market_regime="UNKNOWN",
                    top_setups=[],
                    error="No liquidity-qualified stocks found. Run Volume Filter first.",
                )

            # Step 2: Detect current market regime
            workflow.logger.info("Step 2: Detecting market regime...")
            regime_info = await workflow.execute_activity(
                detect_current_regime,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )
            market_regime = regime_info.get("regime", "UNKNOWN")
            workflow.logger.info(f"Market regime: {market_regime}")

            # Adjust min_rr for Choppy regime
            if market_regime == "BEAR" or market_regime == "CHOPPY":
                min_rr_ratio = 2.5
                workflow.logger.info(f"Adjusted min R:R to {min_rr_ratio} for {market_regime} regime")

            # Step 3: Detect setups in batches
            workflow.logger.info("Step 3: Detecting technical setups...")
            all_setups = []

            for i in range(0, len(symbols), batch_size):
                batch = symbols[i : i + batch_size]
                workflow.logger.info(
                    f"Processing batch {i // batch_size + 1} ({len(batch)} symbols)..."
                )

                batch_setups = await workflow.execute_activity(
                    detect_setups_batch,
                    args=[batch, 0.3],
                    start_to_close_timeout=timedelta(minutes=15),
                    retry_policy=retry_policy,
                )

                all_setups.extend(batch_setups)
                workflow.logger.info(
                    f"Found {len(all_setups)} setups from {min(i + batch_size, len(symbols))} symbols"
                )

            workflow.logger.info(f"Detected {len(all_setups)} raw setups")

            if not all_setups:
                return SetupDetectionResult(
                    success=True,
                    total_analyzed=len(symbols),
                    total_setups_found=0,
                    total_qualified=0,
                    setups_by_type={},
                    avg_confidence=0,
                    avg_rr_ratio=0,
                    market_regime=market_regime,
                    top_setups=[],
                    error="No setups detected. Market may not be favorable.",
                )

            # Step 4: Filter and rank setups
            workflow.logger.info("Step 4: Filtering and ranking setups...")
            filtered_setups = await workflow.execute_activity(
                filter_and_rank_setups,
                args=[all_setups, min_rr_ratio, min_confidence, 7.0],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            workflow.logger.info(f"Filtered to {len(filtered_setups)} qualified setups")

            # Step 5: Enrich with context from previous phases
            workflow.logger.info("Step 5: Enriching setups with context...")
            enriched_setups = await workflow.execute_activity(
                enrich_setups_with_context,
                args=[filtered_setups],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            # Step 6: Save results
            workflow.logger.info("Step 6: Saving setup results to database...")
            save_stats = await workflow.execute_activity(
                save_setup_results,
                args=[enriched_setups, market_regime],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Prepare top setups for display (exclude df field)
            top_setups = [
                {k: v for k, v in s.items() if k != "df"}
                for s in enriched_setups[:10]
            ]

            avg_conf = sum(s.get("confidence", 0) for s in enriched_setups) / len(enriched_setups) if enriched_setups else 0
            avg_rr = sum(s.get("rr_ratio", 0) for s in enriched_setups) / len(enriched_setups) if enriched_setups else 0

            workflow.logger.info(
                f"Setup Detection complete: {len(symbols)} analyzed, "
                f"{len(all_setups)} found, {len(enriched_setups)} qualified"
            )

            return SetupDetectionResult(
                success=True,
                total_analyzed=len(symbols),
                total_setups_found=len(all_setups),
                total_qualified=len(enriched_setups),
                setups_by_type=save_stats.get("by_type", {}),
                avg_confidence=round(avg_conf, 1),
                avg_rr_ratio=round(avg_rr, 2),
                market_regime=market_regime,
                top_setups=top_setups,
            )

        except Exception as e:
            workflow.logger.error(f"Setup Detection failed: {e}")
            return SetupDetectionResult(
                success=False,
                total_analyzed=0,
                total_setups_found=0,
                total_qualified=0,
                setups_by_type={},
                avg_confidence=0,
                avg_rr_ratio=0,
                market_regime="UNKNOWN",
                top_setups=[],
                error=str(e),
            )


@dataclass
class Phase4PipelineResult:
    """Result of complete Phase 4 pipeline (Volume + Setup Detection)."""

    success: bool
    # Volume filter stats
    volume_analyzed: int
    volume_qualified: int
    avg_liquidity_score: float
    # Setup detection stats
    setups_found: int
    setups_qualified: int
    setups_by_type: dict
    avg_confidence: float
    avg_rr_ratio: float
    market_regime: str
    top_setups: list[dict]
    error: str | None = None


@workflow.defn
class Phase4PipelineWorkflow:
    """
    Complete Phase 4 Pipeline: Volume Filter + Setup Detection.

    Phase 4A: ~30-50 → ~15-25 (Liquidity Filter)
    Phase 4B: ~15-25 → ~8-15 (Setup Detection)
    """

    @workflow.run
    async def run(self) -> Phase4PipelineResult:
        """Execute full Phase 4 pipeline."""
        workflow.logger.info("Starting Phase 4 Pipeline (Volume + Setup Detection)")

        try:
            # Phase 4A: Volume Filter
            workflow.logger.info("=== Phase 4A: Volume & Liquidity Filter ===")

            volume_result = await workflow.execute_child_workflow(
                VolumeFilterWorkflow.run,
                args=[50],
                id=f"volume-filter-{workflow.info().workflow_id}",
            )

            if not volume_result.success:
                return Phase4PipelineResult(
                    success=False,
                    volume_analyzed=0,
                    volume_qualified=0,
                    avg_liquidity_score=0,
                    setups_found=0,
                    setups_qualified=0,
                    setups_by_type={},
                    avg_confidence=0,
                    avg_rr_ratio=0,
                    market_regime="UNKNOWN",
                    top_setups=[],
                    error=f"Volume Filter failed: {volume_result.error}",
                )

            workflow.logger.info(
                f"Volume Filter complete: {volume_result.total_qualified} qualified"
            )

            # Phase 4B: Setup Detection
            workflow.logger.info("=== Phase 4B: Setup Detection ===")

            setup_result = await workflow.execute_child_workflow(
                SetupDetectionWorkflow.run,
                args=[30, 2.0, 70],
                id=f"setup-detection-{workflow.info().workflow_id}",
            )

            if not setup_result.success:
                return Phase4PipelineResult(
                    success=False,
                    volume_analyzed=volume_result.total_analyzed,
                    volume_qualified=volume_result.total_qualified,
                    avg_liquidity_score=volume_result.avg_liquidity_score,
                    setups_found=0,
                    setups_qualified=0,
                    setups_by_type={},
                    avg_confidence=0,
                    avg_rr_ratio=0,
                    market_regime="UNKNOWN",
                    top_setups=[],
                    error=f"Setup Detection failed: {setup_result.error}",
                )

            workflow.logger.info(
                f"Setup Detection complete: {setup_result.total_qualified} qualified"
            )

            return Phase4PipelineResult(
                success=True,
                volume_analyzed=volume_result.total_analyzed,
                volume_qualified=volume_result.total_qualified,
                avg_liquidity_score=volume_result.avg_liquidity_score,
                setups_found=setup_result.total_setups_found,
                setups_qualified=setup_result.total_qualified,
                setups_by_type=setup_result.setups_by_type,
                avg_confidence=setup_result.avg_confidence,
                avg_rr_ratio=setup_result.avg_rr_ratio,
                market_regime=setup_result.market_regime,
                top_setups=setup_result.top_setups,
            )

        except Exception as e:
            workflow.logger.error(f"Phase 4 Pipeline failed: {e}")
            return Phase4PipelineResult(
                success=False,
                volume_analyzed=0,
                volume_qualified=0,
                avg_liquidity_score=0,
                setups_found=0,
                setups_qualified=0,
                setups_by_type={},
                avg_confidence=0,
                avg_rr_ratio=0,
                market_regime="UNKNOWN",
                top_setups=[],
                error=str(e),
            )


@dataclass
class FullAnalysisPipelineResult:
    """Result of complete analysis pipeline (Phase 1-4)."""

    success: bool
    # Phase 1
    total_nse_eq: int
    high_quality_count: int
    # Phase 2
    momentum_qualified: int
    # Phase 3
    consistency_qualified: int
    # Phase 4
    liquidity_qualified: int
    setups_qualified: int
    setups_by_type: dict
    market_regime: str
    top_setups: list[dict]
    error: str | None = None


@workflow.defn
class FullAnalysisPipelineWorkflow:
    """
    Complete Analysis Pipeline: Phase 1-4.

    Phase 1: ~2400 NSE EQ → ~1400 High Quality
    Phase 2: ~1400 → ~50-100 Momentum Qualified
    Phase 3: ~50-100 → ~30-50 Consistency Qualified
    Phase 4A: ~30-50 → ~15-25 Liquidity Qualified
    Phase 4B: ~15-25 → ~8-15 Trade Setups
    """

    @workflow.run
    async def run(self) -> FullAnalysisPipelineResult:
        """Execute full analysis pipeline (Phase 1-4)."""
        workflow.logger.info("Starting Full Analysis Pipeline (Phase 1-4)")

        try:
            # Import here to avoid circular imports
            from trade_analyzer.workflows.consistency_filter import FullPipelineWorkflow

            # Phase 1-3: Universe + Momentum + Consistency
            workflow.logger.info("=== Phase 1-3: Universe + Momentum + Consistency ===")

            phase3_result = await workflow.execute_child_workflow(
                FullPipelineWorkflow.run,
                id=f"phase1-3-{workflow.info().workflow_id}",
            )

            if not phase3_result.success:
                return FullAnalysisPipelineResult(
                    success=False,
                    total_nse_eq=0,
                    high_quality_count=0,
                    momentum_qualified=0,
                    consistency_qualified=0,
                    liquidity_qualified=0,
                    setups_qualified=0,
                    setups_by_type={},
                    market_regime="UNKNOWN",
                    top_setups=[],
                    error=f"Phase 1-3 failed: {phase3_result.error}",
                )

            workflow.logger.info(
                f"Phase 1-3 complete: {phase3_result.consistency_qualified} consistency-qualified"
            )

            # Phase 4: Volume + Setup Detection
            workflow.logger.info("=== Phase 4: Volume + Setup Detection ===")

            phase4_result = await workflow.execute_child_workflow(
                Phase4PipelineWorkflow.run,
                id=f"phase4-{workflow.info().workflow_id}",
            )

            if not phase4_result.success:
                return FullAnalysisPipelineResult(
                    success=False,
                    total_nse_eq=phase3_result.total_nse_eq,
                    high_quality_count=phase3_result.high_quality_count,
                    momentum_qualified=phase3_result.momentum_qualified,
                    consistency_qualified=phase3_result.consistency_qualified,
                    liquidity_qualified=0,
                    setups_qualified=0,
                    setups_by_type={},
                    market_regime=phase3_result.market_regime,
                    top_setups=[],
                    error=f"Phase 4 failed: {phase4_result.error}",
                )

            workflow.logger.info(
                f"Phase 4 complete: {phase4_result.setups_qualified} trade setups"
            )

            return FullAnalysisPipelineResult(
                success=True,
                total_nse_eq=phase3_result.total_nse_eq,
                high_quality_count=phase3_result.high_quality_count,
                momentum_qualified=phase3_result.momentum_qualified,
                consistency_qualified=phase3_result.consistency_qualified,
                liquidity_qualified=phase4_result.volume_qualified,
                setups_qualified=phase4_result.setups_qualified,
                setups_by_type=phase4_result.setups_by_type,
                market_regime=phase4_result.market_regime,
                top_setups=phase4_result.top_setups,
            )

        except Exception as e:
            workflow.logger.error(f"Full Analysis Pipeline failed: {e}")
            return FullAnalysisPipelineResult(
                success=False,
                total_nse_eq=0,
                high_quality_count=0,
                momentum_qualified=0,
                consistency_qualified=0,
                liquidity_qualified=0,
                setups_qualified=0,
                setups_by_type={},
                market_regime="UNKNOWN",
                top_setups=[],
                error=str(e),
            )

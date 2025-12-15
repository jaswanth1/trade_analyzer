"""Temporal Workflows for Trade Analyzer."""

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

__all__ = [
    "UniverseRefreshWorkflow",
    "UniverseSetupWorkflow",
    "MomentumFilterWorkflow",
    "UniverseAndMomentumWorkflow",
    "ConsistencyFilterWorkflow",
    "FullPipelineWorkflow",
    # Phase 4 workflows
    "VolumeFilterWorkflow",
    "SetupDetectionWorkflow",
    "Phase4PipelineWorkflow",
    "FullAnalysisPipelineWorkflow",
]

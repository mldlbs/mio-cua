"""Evaluation package for Agent Runtime v2 (milestone 1: measuring stick)."""

from mio_cua.evaluation.dataset import BenchmarkTask, TaskDataset
from mio_cua.evaluation.harness import Harness, RunResult
from mio_cua.evaluation.metrics import compute_metrics, render_report

# --- Phase 3: real trace recording, replay, attribution, benchmark (spec §5-§30) ---
from mio_cua.evaluation.schema import (
    SCHEMA_VERSION,
    EventType,
    FailureAttribution,
    FailureCategory,
    Trace,
    TraceEvent,
    TraceRedactor,
)
from mio_cua.evaluation.attribution import FailureAttributor
from mio_cua.evaluation.recorder import JSONLTraceStore, Recorder, RuntimeEventSink
from mio_cua.evaluation.replay import ReplayEngine, ReplayOutcome, compare_plans
from mio_cua.evaluation.benchmark import benchmark

__all__ = [
    "BenchmarkTask",
    "TaskDataset",
    "Harness",
    "RunResult",
    "compute_metrics",
    "render_report",
    # Phase 3
    "SCHEMA_VERSION",
    "EventType",
    "FailureAttribution",
    "FailureCategory",
    "Trace",
    "TraceEvent",
    "TraceRedactor",
    "FailureAttributor",
    "JSONLTraceStore",
    "Recorder",
    "RuntimeEventSink",
    "ReplayEngine",
    "ReplayOutcome",
    "compare_plans",
    "benchmark",
]

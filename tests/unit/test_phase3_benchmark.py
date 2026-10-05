"""Phase 3 — Benchmark aggregation over recorded traces (spec §26-§27).

Aggregates a list of schema.Trace into a BenchmarkResult: task success rate,
failure distribution, recovery success rate, average steps / recovery count,
and step success rate (metadata).
"""

import pytest

from mio_cua.evaluation.benchmark import benchmark
from mio_cua.evaluation.schema import FailureAttribution, Trace, TraceEvent


def _ev(event_type, step, payload):
    return TraceEvent(event_type=event_type, step=step, payload=payload)


def _trace(success, category=None, recoveries=0, idx="1", action_success=True):
    events = [
        _ev("task_started", 0, {"goal": "g"}),
        _ev("observation", 0, {"observation": {"active_window": "WeChat",
                                               "scene": {"nodes": [{"id": 1, "text": "x"}]}}}),
        _ev("action_completed", 0, {"action": {"tool": "click", "success": action_success}}),
    ]
    if success:
        events.append(_ev("task_completed", 1, {"status": "SUCCESS"}))
    else:
        events.append(_ev("task_failed", 1, {"status": "FAIL"}))
    for i in range(recoveries):
        events.append(_ev("recovery_completed", 2 + i, {"recovery": {"success": True}}))
    t = Trace(trace_id=f"T{idx}", goal="g", events=events,
              metadata={"target_context": {}})
    if not success and category:
        t.failure = FailureAttribution(category=category, confidence=0.9,
                                       reason="r", evidence=[])
    return t


class TestBenchmark:
    def test_empty(self):
        b = benchmark([])
        assert b.total_tasks == 0
        assert b.success_rate == 0.0

    def test_aggregates_success_rate(self):
        traces = [_trace(True, idx="1"), _trace(True, idx="2"),
                  _trace(False, category="planner", idx="3")]
        b = benchmark(traces)
        assert b.total_tasks == 3
        assert b.success_tasks == 2
        assert b.failed_tasks == 1
        assert b.success_rate == round(2 / 3, 4)
        assert b.failure_distribution == {"planner": 1}

    def test_recovery_accounting(self):
        traces = [_trace(True, recoveries=2, idx="1"), _trace(True, recoveries=1, idx="2")]
        b = benchmark(traces)
        assert b.average_recovery_count == pytest.approx(3 / 2)
        assert b.recovery_success_rate == pytest.approx(1.0)

    def test_step_success_rate_in_metadata(self):
        traces = [_trace(True, action_success=True, idx="1"),
                  _trace(False, category="action", action_success=False, idx="2")]
        b = benchmark(traces)
        assert "step_success_rate" in b.metadata
        assert b.metadata["step_success_rate"] == pytest.approx(0.5)

    def test_average_steps(self):
        traces = [_trace(True, idx="1"), _trace(False, category="env", idx="2")]
        b = benchmark(traces)
        # each trace has 4 events -> average steps == 4.0
        assert b.average_steps == pytest.approx(4.0)

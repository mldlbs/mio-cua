"""Phase 3 — ReplayEngine (deterministic + planner) and plan comparison (spec §23-§25).

Key acceptance criteria:
  * AC3 — replay never triggers real input (triggered_real_action is always False;
    "live" mode is explicitly disabled).
  * Same trace -> same state transitions (deterministic).
  * Modified planner -> divergence detected via compare_plans.
"""

import pytest

from mio_cua.evaluation.replay import ReplayEngine, compare_plans
from mio_cua.evaluation.schema import PlanComparison, Trace, TraceEvent


def _ev(event_type, step, payload):
    return TraceEvent(event_type=event_type, step=step, payload=payload)


def _sample_trace(status="SUCCESS"):
    return Trace(trace_id="RT", goal="g",
                 metadata={"target_context": {"keyword": "兴蓉", "app": "WeChat"}},
                 events=[
                     _ev("task_started", 0, {"goal": "g",
                         "target_context": {"keyword": "兴蓉", "app": "WeChat"}}),
                     _ev("observation", 0, {"observation": {"active_window": "WeChat",
                          "scene": {"nodes": [{"id": 1, "text": "兴蓉项目群"}]}}}),
                     _ev("plan_created", 0, {"plan": {"action_type": "click",
                          "target": "兴蓉项目群"}}),
                     _ev("action_completed", 0, {"action": {"tool": "click", "success": True}}),
                     _ev("task_completed" if status == "SUCCESS" else "task_failed", 1,
                         {"status": status}),
                 ])


class TestComparePlans:
    def test_identical(self):
        a = {"action_type": "click", "target": "t", "parameters": {"element_id": 3}}
        c = compare_plans(a, dict(a))
        assert c.same_action is True
        assert c.same_target is True
        assert c.semantic_match == 1.0
        assert c.parameter_delta == {}

    def test_divergent_action(self):
        c = compare_plans({"action_type": "click", "target": "t", "parameters": {}},
                          {"action_type": "scroll", "target": "t", "parameters": {}})
        assert c.same_action is False
        assert c.semantic_match == 0.0

    def test_same_action_diff_target(self):
        c = compare_plans({"action_type": "click", "target": "a", "parameters": {}},
                          {"action_type": "click", "target": "b", "parameters": {}})
        assert c.same_action is True
        assert c.same_target is False
        assert c.semantic_match == 0.5

    def test_parameter_delta(self):
        c = compare_plans({"action_type": "click", "target": "t", "parameters": {"x": 1}},
                          {"action_type": "click", "target": "t", "parameters": {"x": 2}})
        assert c.parameter_delta == {"x": {"recorded": 1, "replayed": 2}}


class TestReplayEngine:
    def test_deterministic_no_real_action(self):
        out = ReplayEngine().replay(_sample_trace(), "deterministic")
        assert out.triggered_real_action is False
        assert out.reproduced_steps == 5
        assert out.reproduced_status == "SUCCESS"
        assert out.attribution is not None

    def test_deterministic_reproducible(self):
        e1 = ReplayEngine().replay(_sample_trace(), "deterministic")
        e2 = ReplayEngine().replay(_sample_trace(), "deterministic")
        assert e1.state_transitions == e2.state_transitions

    def test_state_transitions_capture_plan_and_action(self):
        out = ReplayEngine().replay(_sample_trace(), "deterministic")
        types = [t["event_type"] for t in out.state_transitions]
        assert "plan_created" in types
        assert "action_completed" in types
        plan_tr = [t for t in out.state_transitions if t["event_type"] == "plan_created"][0]
        assert plan_tr["action_type"] == "click"

    def test_planner_mode_divergence(self):
        def planner(obs, recorded):
            return {"action_type": "scroll", "target": None, "parameters": {}}

        out = ReplayEngine().replay(_sample_trace(), "planner", planner=planner)
        assert len(out.plan_comparisons) >= 1
        diverged = [c for c in out.plan_comparisons if not c.same_action]
        assert len(diverged) >= 1
        assert out.triggered_real_action is False

    def test_planner_mode_no_divergence(self):
        def planner(obs, recorded):
            return recorded

        out = ReplayEngine().replay(_sample_trace(), "planner", planner=planner)
        diverged = [c for c in out.plan_comparisons if not c.same_action]
        assert len(diverged) == 0

    def test_live_mode_disabled(self):
        with pytest.raises(RuntimeError):
            ReplayEngine().replay(_sample_trace(), "live")

    def test_failed_trace_attribution_in_outcome(self):
        out = ReplayEngine().replay(_sample_trace("FAIL"), "deterministic")
        assert out.reproduced_status == "FAIL"
        assert out.attribution is not None

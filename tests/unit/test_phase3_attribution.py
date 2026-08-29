"""Phase 3 — rule-based failure attribution across all categories (spec §14-§17).

The attributor reconstructs the Observation -> Plan -> Action -> Verification
chain and assigns a failure to PERCEPTION / PLANNER / ACTION / ENVIRONMENT /
VERIFICATION / UNKNOWN, never defaulting to "last exception = root cause".

Each category has >= 2 cases; every attribution carries evidence + confidence.
"""

import pytest

from mio_cua.evaluation.attribution import FailureAttributor
from mio_cua.evaluation.schema import FailureCategory, Trace, TraceEvent


def _ev(event_type, step, payload):
    return TraceEvent(event_type=event_type, step=step, payload=payload)


def _trace(events, keyword="兴蓉", app="WeChat"):
    return Trace(
        trace_id="t", goal=f"find {keyword}",
        events=events,
        metadata={"target_context": {"keyword": keyword, "app": app, "window": ""}},
    )


# ---- PERCEPTION ------------------------------------------------------------


class TestPerception:
    def test_no_search_box_target_not_visible(self):
        trace = _trace([
            _ev("task_started", 0, {}),
            _ev("observation", 0, {"observation": {"active_window": "WeChat",
                 "scene": {"nodes": [{"id": 1, "text": "文件传输助手"}]}}}),
            _ev("plan_created", 0, {"plan": {"action_type": "click", "target": "文件传输助手"}}),
            _ev("task_failed", 1, {"status": "FAIL"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.PERCEPTION.value
        assert a.evidence

    def test_exploration_chosen_but_target_not_found(self):
        trace = _trace([
            _ev("observation", 0, {"observation": {"active_window": "WeChat",
                 "scene": {"nodes": [{"id": 5, "type": "input", "semantic": "SearchBox",
                                      "text": "搜索"}]}}}),
            _ev("plan_created", 0, {"plan": {"action_type": "search", "target": None}}),
            _ev("action_completed", 0, {"action": {"tool": "search", "success": True}}),
            _ev("verification", 0, {"verification": {"expected_state": "found",
                 "observed_state": "not found", "success": False}}),
            _ev("task_failed", 1, {"status": "FAIL"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.PERCEPTION.value

    def test_observation_insufficient_no_signals(self):
        # no action/verify failure, no search box, target not visible -> PERCEPTION (Rule 4)
        trace = _trace([
            _ev("observation", 0, {"observation": {"active_window": "WeChat",
                 "scene": {"nodes": [{"id": 1, "text": "sherry"}]}}}),
            _ev("task_failed", 1, {"status": "FAIL"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.PERCEPTION.value


# ---- PLANNER ---------------------------------------------------------------


class TestPlanner:
    def test_search_box_present_but_clicked_wrong_target(self):
        trace = _trace([
            _ev("observation", 0, {"observation": {"active_window": "WeChat",
                 "scene": {"nodes": [{"id": 5, "type": "input", "semantic": "SearchBox",
                                      "text": "搜索"},
                                     {"id": 1, "text": "家庭群"}]}}}),
            _ev("plan_created", 0, {"plan": {"action_type": "click", "target": "家庭群"}}),
            _ev("task_failed", 1, {"status": "FAIL"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.PLANNER.value

    def test_verification_failed_wrong_plan_target(self):
        trace = _trace([
            _ev("observation", 0, {"observation": {"active_window": "WeChat",
                 "scene": {"nodes": [{"id": 5, "type": "input", "semantic": "SearchBox",
                                      "text": "搜索"},
                                     {"id": 1, "text": "家庭群"}]}}}),
            _ev("plan_created", 0, {"plan": {"action_type": "click", "target": "家庭群"}}),
            _ev("action_completed", 0, {"action": {"tool": "click", "success": True}}),
            _ev("verification", 0, {"verification": {"expected_state": "x",
                 "observed_state": "y", "success": False}}),
            _ev("task_failed", 1, {"status": "FAIL"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.PLANNER.value

    def test_wrong_plan_target_with_error(self):
        trace = _trace([
            _ev("observation", 0, {"observation": {"active_window": "WeChat",
                 "scene": {"nodes": [{"id": 5, "type": "input", "semantic": "SearchBox",
                                      "text": "搜索"},
                                     {"id": 1, "text": "同事群"}]}}}),
            _ev("plan_created", 0, {"plan": {"action_type": "click", "target": "同事群"}}),
            _ev("task_failed", 1, {"status": "FAIL"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.PLANNER.value
        assert a.confidence >= 0.9


# ---- ACTION ----------------------------------------------------------------


class TestAction:
    def test_action_failed(self):
        trace = _trace([
            _ev("observation", 0, {"observation": {"active_window": "WeChat",
                 "scene": {"nodes": [{"id": 1, "text": "兴蓉项目群"}]}}}),
            _ev("plan_created", 0, {"plan": {"action_type": "click", "target": "兴蓉项目群"}}),
            _ev("action_completed", 0, {"action": {"tool": "click", "success": False,
                 "error": "element not found"}}),
            _ev("task_failed", 1, {"status": "FAIL"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.ACTION.value
        assert a.confidence >= 0.9

    def test_action_failed_with_error(self):
        trace = _trace([
            _ev("plan_created", 0, {"plan": {"action_type": "click", "target": "t"}}),
            _ev("action_completed", 0, {"action": {"tool": "click", "success": False,
                 "error": "click timeout"}}),
            _ev("task_failed", 1, {"status": "FAIL"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.ACTION.value


# ---- ENVIRONMENT -----------------------------------------------------------


class TestEnvironment:
    def test_verification_failed_context_lost(self):
        # active_window Chrome != target WeChat -> context lost
        trace = _trace([
            _ev("observation", 0, {"observation": {"active_window": "Chrome",
                 "scene": {"nodes": [{"id": 1, "text": "兴蓉项目群"}]}}}),
            _ev("plan_created", 0, {"plan": {"action_type": "click", "target": "兴蓉项目群"}}),
            _ev("action_completed", 0, {"action": {"tool": "click", "success": True}}),
            _ev("verification", 0, {"verification": {"expected_state": "x",
                 "observed_state": "y", "success": False}}),
            _ev("task_failed", 1, {"status": "FAIL"}),
        ], app="WeChat")
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.ENVIRONMENT.value

    def test_error_indicates_environment(self):
        trace = _trace([
            _ev("error", 0, {"error": "window lost focus"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.ENVIRONMENT.value

    def test_error_indicates_action(self):
        trace = _trace([
            _ev("error", 0, {"error": "element not found on screen"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.ACTION.value


# ---- VERIFICATION ----------------------------------------------------------


class TestVerification:
    def test_verification_failed_target_visible(self):
        trace = _trace([
            _ev("observation", 0, {"observation": {"active_window": "WeChat",
                 "scene": {"nodes": [{"id": 1, "text": "兴蓉项目群"}]}}}),
            _ev("plan_created", 0, {"plan": {"action_type": "click", "target": "兴蓉项目群"}}),
            _ev("action_completed", 0, {"action": {"tool": "click", "success": True}}),
            _ev("verification", 0, {"verification": {"expected_state": "opened",
                 "observed_state": "still closed", "success": False}}),
            _ev("task_failed", 1, {"status": "FAIL"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.VERIFICATION.value


# ---- UNKNOWN ---------------------------------------------------------------


class TestUnknown:
    def test_no_failure_signal(self):
        # task succeeded -> no failing event -> UNKNOWN (conf 0.0)
        trace = _trace([
            _ev("task_started", 0, {}),
            _ev("observation", 0, {"observation": {"active_window": "WeChat",
                 "scene": {"nodes": [{"id": 1, "text": "兴蓉项目群"}]}}}),
            _ev("task_completed", 1, {"status": "SUCCESS"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.UNKNOWN.value
        assert a.confidence == 0.0

    def test_fallback_insufficient_evidence(self):
        # context matches, target visible, no action/verify fail, no search box
        trace = _trace([
            _ev("observation", 0, {"observation": {"active_window": "WeChat",
                 "scene": {"nodes": [{"id": 1, "text": "兴蓉项目群"}]}}}),
            _ev("plan_created", 0, {"plan": {"action_type": "scroll", "target": None}}),
            _ev("task_failed", 1, {"status": "FAIL"}),
        ])
        a = FailureAttributor().classify(trace)
        assert a.category == FailureCategory.UNKNOWN.value

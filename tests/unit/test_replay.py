"""Unit tests for Replay/Mock Benchmark (Phase 1).

Tests MockPerception, MockInputController, Evaluator, and full
ReplayBenchmark against 3 scenarios without LLM.
"""

import json
import os

import pytest

from mio_cua.evaluation.replay import (
    Evaluator,
    MockInputController,
    MockPerception,
    ReplayBenchmark,
    ReplayResult,
    _build_obs,
)
from mio_cua.models.action import Action
from mio_cua.scene.graph import SceneNode

SCENARIO_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "mio_cua", "evaluation", "scenarios"
)


def _load_scenario(name: str) -> dict:
    path = os.path.join(SCENARIO_DIR, f"{name}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---- MockPerception ----


class TestMockPerception:

    def test_serves_observations_in_order(self):
        obs_a = _build_obs(
            {"id": 0, "active_window": "W", "scene_nodes": [{"id": 1, "text": "A"}]}
        )
        obs_b = _build_obs(
            {"id": 1, "active_window": "W", "scene_nodes": [{"id": 2, "text": "B"}]}
        )
        pm = MockPerception([obs_a, obs_b])

        r1 = pm.observe()
        assert r1.scene.nodes[0].text == "A"

        r2 = pm.observe()
        assert r2.scene.nodes[0].text == "B"

    def test_clamps_at_end(self):
        obs = _build_obs(
            {"id": 0, "active_window": "W", "scene_nodes": [{"id": 1, "text": "X"}]}
        )
        pm = MockPerception([obs])
        pm.observe()
        r = pm.observe()
        assert r.scene.nodes[0].text == "X"

    def test_observe_light_returns_same(self):
        obs = _build_obs(
            {"id": 0, "active_window": "W", "scene_nodes": [{"id": 1, "text": "L"}]}
        )
        pm = MockPerception([obs])
        assert pm.observe_light().scene.nodes[0].text == "L"


# ---- MockInputController ----


class TestMockInputController:

    def test_captures_action(self):
        ctrl = MockInputController()
        act = Action(id="a1", type="click", params={"element_id": 3})
        result = ctrl.execute(act)
        assert result.sent is True
        assert len(ctrl.actions) == 1
        assert ctrl.actions[0]["type"] == "click"
        assert ctrl.actions[0]["params"]["element_id"] == 3

    def test_resolve_keeps_element_id(self):
        ctrl = MockInputController()
        act = Action(id="a2", type="click", params={"element_id": 5})
        ctrl.resolve(act)
        assert act.params.get("element_id") == 5

    def test_multiple_actions(self):
        ctrl = MockInputController()
        ctrl.execute(Action(id="a1", type="click", params={"element_id": 1}))
        ctrl.execute(Action(id="a2", type="scroll", params={"direction": "down", "amount": 5}))
        assert len(ctrl.actions) == 2
        assert ctrl.actions[1]["type"] == "scroll"


# ---- _build_obs ----


class TestBuildObs:

    def test_builds_scene_graph(self):
        data = {
            "id": 0,
            "active_window": "WeChat",
            "scene_nodes": [
                {"id": 1, "type": "text", "text": "hello", "bbox": [10, 20, 100, 30]},
                {"id": 2, "type": "group", "semantic": "Frame", "bbox": [0, 0, 500, 500]},
            ],
        }
        obs = _build_obs(data)
        assert obs.active_window == "WeChat"
        assert len(obs.scene.nodes) == 2
        assert obs.scene.nodes[0].text == "hello"
        assert obs.scene.nodes[1].semantic == "Frame"
        assert obs.screenshot_path is None


# ---- Evaluator ----


class TestEvaluator:

    def test_allowed_action_passes(self):
        gt = [{"obs_id": 0, "target_visible": True, "context_matches": True, "forbidden_patterns": []}]
        tg = {"edges": [{"from": 0, "action_type": "click", "action_params_match": {"element_id": 3}, "to": 1, "preconditions": {}}]}
        goal = {"type": "action_type", "action_type": "success"}
        ev = Evaluator(gt, tg, goal)
        result = ev.evaluate_step(0, {"type": "click", "params": {"element_id": 3}})
        assert result["action_allowed"] is True

    def test_disallowed_action_fails(self):
        gt = [{"obs_id": 0, "target_visible": False, "context_matches": True, "forbidden_patterns": []}]
        tg = {"edges": [{"from": 0, "action_type": "scroll", "action_params_match": {}, "to": 1, "preconditions": {}}]}
        goal = {"type": "action_type", "action_type": "success"}
        ev = Evaluator(gt, tg, goal)
        result = ev.evaluate_step(0, {"type": "click", "params": {"element_id": 3}})
        assert result["action_allowed"] is False

    def test_forbidden_pattern_click_frame(self):
        gt = [{"obs_id": 0, "target_visible": False, "context_matches": True, "forbidden_patterns": ["click_frame_node"]}]
        tg = {"edges": []}
        goal = {"type": "action_type", "action_type": "success"}
        ev = Evaluator(gt, tg, goal)
        result = ev.evaluate_step(0, {"type": "click", "params": {"element_id": 0}})
        assert result["safety_invariant"] is False

    def test_context_mismatch_detected(self):
        gt = [{"obs_id": 0, "target_visible": False, "context_matches": False, "forbidden_patterns": []}]
        tg = {"edges": []}
        goal = {"type": "action_type", "action_type": "success"}
        ev = Evaluator(gt, tg, goal)
        result = ev.evaluate_step(0, {"type": "focus_window", "params": {"app": "WeChat"}})
        assert result["context_valid"] is False

    def test_progress_detected(self):
        gt = [
            {"obs_id": 0, "target_visible": False, "context_matches": True, "forbidden_patterns": []},
            {"obs_id": 1, "target_visible": True, "context_matches": True, "forbidden_patterns": []},
        ]
        tg = {"edges": [{"from": 0, "action_type": "scroll", "to": 1, "preconditions": {}}]}
        goal = {"type": "target_visible_then_click", "keyword": "兴蓉"}
        ev = Evaluator(gt, tg, goal)
        ev.evaluate_step(0, {"type": "scroll", "params": {"direction": "down"}})
        result = ev.evaluate_step(1, {"type": "click", "params": {"element_id": 7}})
        assert result["progress"] is True

    def test_evaluate_final_goal_reached(self):
        gt = [{"obs_id": 0, "target_visible": True, "context_matches": True, "forbidden_patterns": []}]
        tg = {"edges": [{"from": 0, "action_type": "click", "action_params_match": {"element_id": 3}, "to": 1, "preconditions": {}}]}
        goal = {"type": "action_type", "action_type": "click"}
        ev = Evaluator(gt, tg, goal)
        ev.evaluate_step(0, {"type": "click", "params": {"element_id": 3}})
        final = ev.evaluate_final(0, [{"type": "click", "params": {"element_id": 3}}])
        assert final["goal_reached"] is True
        assert final["invalid_action_count"] == 0

    def test_evaluate_final_goal_not_reached(self):
        gt = [{"obs_id": 0, "target_visible": True, "context_matches": True, "forbidden_patterns": []}]
        tg = {"edges": []}
        goal = {"type": "action_type", "action_type": "success"}
        ev = Evaluator(gt, tg, goal)
        ev.evaluate_step(0, {"type": "scroll", "params": {"direction": "down"}})
        final = ev.evaluate_final(0, [{"type": "scroll", "params": {"direction": "down"}}])
        assert final["goal_reached"] is False


# ---- ReplayBenchmark: scenario integration ----


class TestReplayBenchmark:

    @pytest.mark.parametrize(
        "scenario_name,expect_goal",
        [
            ("target_visible_click", True),
            ("scroll_discovery", True),
            ("context_recovery", True),
        ],
    )
    def test_scenarios_load_and_run(self, scenario_name, expect_goal):
        path = os.path.join(SCENARIO_DIR, f"{scenario_name}.json")
        if not os.path.exists(path):
            pytest.skip(f"scenario {scenario_name}.json not found")
        bench = ReplayBenchmark(path)
        result = bench.run()
        assert isinstance(result, ReplayResult)
        assert result.scenario_id == scenario_name
        assert result.steps >= 0
        assert result.invalid_action_count >= 0

    def test_target_visible_click_direct(self):
        path = os.path.join(SCENARIO_DIR, "target_visible_click.json")
        if not os.path.exists(path):
            pytest.skip("scenario not found")
        bench = ReplayBenchmark(path)
        result = bench.run()
        assert result.scenario_id == "target_visible_click"

    def test_scroll_discovery(self):
        path = os.path.join(SCENARIO_DIR, "scroll_discovery.json")
        if not os.path.exists(path):
            pytest.skip("scenario not found")
        bench = ReplayBenchmark(path)
        result = bench.run()
        assert result.scenario_id == "scroll_discovery"

    def test_context_recovery(self):
        path = os.path.join(SCENARIO_DIR, "context_recovery.json")
        if not os.path.exists(path):
            pytest.skip("scenario not found")
        bench = ReplayBenchmark(path)
        result = bench.run()
        assert result.scenario_id == "context_recovery"

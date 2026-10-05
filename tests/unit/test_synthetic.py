"""Tests for Phase 2 Synthetic Planner Benchmark.

Evaluates the Evaluator logic with mocked actions (no LLM required).
Optional real-LLM smoke test gated by RUN_LLM_TESTS=1.
"""

import json
import os

import pytest

from mio_cua.evaluation.synthetic import (
    Scenario,
    SyntheticBenchmark,
    SyntheticEvaluator,
    _build_obs,
)

SCENARIO_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "mio_cua", "evaluation", "scenarios"
)


def _load_scenarios():
    path = os.path.join(SCENARIO_DIR, "synthetic_planner_v1.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _make_action(action_type: str, params: dict = None):
    from mio_cua.models.action import Action
    return Action(id="test-001", type=action_type, params=params or {})


# ---- SyntheticEvaluator ----


class TestSyntheticEvaluator:

    def _scenario(self, idx: int = 0) -> Scenario:
        data = _load_scenarios()
        s = data["scenarios"][idx]
        return Scenario(
            id=s["id"],
            description=s["description"],
            observation=s["observation"],
            expected_action_type=s["expected_action_type"],
            goal=s.get("goal", {}),
            notes=s.get("notes", ""),
        )

    def test_valid_action_passes(self):
        sc = self._scenario(0)  # target_visible_click, expected: click
        ev = SyntheticEvaluator()
        action = _make_action("click", {"element_id": 3})
        result = ev.evaluate(sc, action, "I see the target")
        assert result["valid"] is True
        assert result["unsafe"] is False

    def test_wrong_action_type_fails(self):
        sc = self._scenario(0)  # expected: click
        ev = SyntheticEvaluator()
        action = _make_action("scroll", {"direction": "down"})
        result = ev.evaluate(sc, action, "Scrolling")
        assert result["valid"] is False
        assert result["actual"] == "scroll"

    def test_no_action_fails(self):
        sc = self._scenario(0)
        ev = SyntheticEvaluator()
        result = ev.evaluate(sc, None, "I have no tool calls")
        assert result["valid"] is False
        assert result["actual"] is None

    def test_click_frame_node_is_unsafe(self):
        sc = self._scenario(0)
        ev = SyntheticEvaluator()
        action = _make_action("click", {"element_id": 0})
        result = ev.evaluate(sc, action, "Clicking frame")
        assert result["unsafe"] is True

    def test_raw_xy_is_unsafe(self):
        sc = self._scenario(0)
        ev = SyntheticEvaluator()
        action = _make_action("click", {"x": 500, "y": 300})
        result = ev.evaluate(sc, action, "Clicking by coordinates")
        assert result["unsafe"] is True

    def test_progress_detected_for_click(self):
        sc = self._scenario(0)  # goal type: target_visible
        ev = SyntheticEvaluator()
        action = _make_action("click", {"element_id": 3})
        result = ev.evaluate(sc, action, "Clicking target")
        assert result["progress"] is True

    def test_progress_detected_for_focus(self):
        sc = self._scenario(3)  # context_mismatch, expected: focus_window
        ev = SyntheticEvaluator()
        action = _make_action("focus_window", {"app": "WeChat"})
        result = ev.evaluate(sc, action, "Focusing WeChat")
        assert result["progress"] is True

    def test_search_is_valid_when_expected(self):
        sc = self._scenario(1)  # target_invisible_search, expected: search
        ev = SyntheticEvaluator()
        action = _make_action("search", {"query": "兴蓉"})
        result = ev.evaluate(sc, action, "Using search")
        assert result["valid"] is True

    def test_scroll_is_valid_when_expected(self):
        sc = self._scenario(2)  # target_invisible_scroll, expected: scroll
        ev = SyntheticEvaluator()
        action = _make_action("scroll", {"direction": "down", "amount": 5})
        result = ev.evaluate(sc, action, "Scrolling down")
        assert result["valid"] is True

    def test_focus_window_is_valid_when_expected(self):
        sc = self._scenario(3)  # context_mismatch, expected: focus_window
        ev = SyntheticEvaluator()
        action = _make_action("focus_window", {"app": "WeChat"})
        result = ev.evaluate(sc, action, "Focusing WeChat")
        assert result["valid"] is True

    def test_summary_calculation(self):
        ev = SyntheticEvaluator()
        sc = self._scenario(0)  # expected: click
        ev.evaluate(sc, _make_action("click", {"element_id": 3}), "ok")        # valid, safe
        ev.evaluate(sc, _make_action("scroll", {"direction": "down"}), "wrong") # invalid
        ev.evaluate(sc, _make_action("wait", {}), "idle")                       # invalid
        s = ev.summary()
        assert s["total"] == 3
        assert s["valid_action_rate"] == pytest.approx(1 / 3, abs=0.01)
        assert s["unsafe_action_rate"] == pytest.approx(0.0, abs=0.01)


# ---- Scenario loading ----


class TestScenarioLoading:

    def test_loads_all_scenarios(self):
        data = _load_scenarios()
        assert len(data["scenarios"]) == 5

    def test_scenario_fields(self):
        data = _load_scenarios()
        for s in data["scenarios"]:
            assert "id" in s
            assert "observation" in s
            assert "expected_action_type" in s
            assert "goal" in s

    def test_build_obs_from_scenario(self):
        data = _load_scenarios()
        obs_data = data["scenarios"][0]["observation"]
        obs = _build_obs(obs_data)
        assert obs.active_window == "WeChat"
        assert len(obs.scene.nodes) > 0


# ---- SyntheticBenchmark (mocked provider, no LLM) ----


class TestSyntheticBenchmarkMocked:

    def test_load_scenarios(self):
        from unittest.mock import MagicMock
        provider = MagicMock()
        tool_defs = [{"type": "function", "function": {"name": "click", "parameters": {}}}]
        bench = SyntheticBenchmark(provider, "test prompt", tool_defs)
        scenarios = bench.load_scenarios(
            os.path.join(SCENARIO_DIR, "synthetic_planner_v1.json")
        )
        assert len(scenarios) == 5
        assert scenarios[0].id == "target_visible_click"


# ---- Real LLM smoke test (gated) ----


@pytest.mark.skipif(
    not os.environ.get("RUN_LLM_TESTS"),
    reason="Set RUN_LLM_TESTS=1 to run real LLM tests",
)
class TestRealLLMSmoke:

    def test_planner_produces_valid_action(self):
        from mio_cua.providers.openai_compat import OpenAICompatProvider
        from mio_cua.tools.builtin import register_builtin_tools
        from mio_cua.tools.registry import ToolRegistry

        provider = OpenAICompatProvider(
            base_url=os.environ.get("MIO_BASE_URL", "https://ai.crlkcloud.cyou/v1"),
            api_key=os.environ.get("MIO_API_KEY", ""),
            model=os.environ.get("MIO_MODEL", "default"),
        )
        registry = ToolRegistry()
        register_builtin_tools(registry)
        tool_defs = registry.schemas()

        bench = SyntheticBenchmark(
            provider,
            "You are a desktop automation agent. Use the provided tools.",
            tool_defs,
        )
        results = bench.run(os.path.join(SCENARIO_DIR, "synthetic_planner_v1.json"))

        for r in results:
            print(f"[{'PASS' if r.valid else 'FAIL'}] {r.scenario_id}: "
                  f"expected={r.expected} actual={r.actual} "
                  f"progress={r.progress} unsafe={r.unsafe}")

        valid_count = sum(1 for r in results if r.valid)
        # Baseline: 3/5 valid (60%). Key failures: LLM clicks non-matching
        # candidates when target is invisible. Threshold allows regression detection.
        assert valid_count >= 3, f"Expected at least 3/5 valid (baseline 60%), got {valid_count}/5"

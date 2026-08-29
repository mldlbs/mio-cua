"""Tests for trace recording, failure classification, and comparison.

FailureClassifier uses evidence chain:
  1. Observation 是否包含足够信息？ (context / target visibility / affordances)
  2. Action 是否符合 Observation + Goal？
  3. Action 执行是否达到预期？
"""

import pytest

from mio_cua.evaluation.recorder import ActionRecord, ObsFrame, PlannerRecord, Trace, TraceEntry
from mio_cua.evaluation.trace import FailureClassifier


# ---- FailureClassifier ----


class TestFailureClassifier:

    def _frame(self, nodes, window="WeChat"):
        return ObsFrame(id=1, timestamp=100.0, active_window=window, scene_nodes=nodes)

    def _action(self, action_type="click", params=None, success=True):
        return ActionRecord(
            id="a1", type=action_type, params=params or {},
            result={"sent": True, "success": success},
        )

    # ── Layer 1a: Environment ──

    def test_environment_error_context_mismatch(self):
        fc = FailureClassifier()
        obs = self._frame([{"id": 3, "text": "兴蓉项目群", "bbox": [0, 0, 100, 30]}], window="Chrome")
        result = fc.classify(obs, self._action(), "兴蓉", "WeChat", context_matches=False)
        assert result["category"] == FailureClassifier.ENVIRONMENT
        assert "Chrome" in result["detail"]

    # ── Layer 1b: Target not visible — with alternatives → Planner ──

    def test_target_not_visible_clicked_alternative(self):
        fc = FailureClassifier()
        obs = self._frame([
            {"id": 2, "text": "sherry", "bbox": [0, 0, 100, 30]},
            {"id": 3, "text": "家庭群", "bbox": [0, 40, 100, 30]},
        ])
        result = fc.classify(obs, self._action("click", {"element_id": 2}), "兴蓉", "WeChat")
        assert result["category"] == FailureClassifier.PLANNER
        assert "non-matching candidate" in result["detail"]

    def test_target_not_visible_no_action_with_candidates(self):
        fc = FailureClassifier()
        obs = self._frame([
            {"id": 2, "text": "sherry", "bbox": [0, 0, 100, 30]},
            {"id": 3, "text": "家庭群", "bbox": [0, 40, 100, 30]},
        ])
        result = fc.classify(obs, None, "兴蓉", "WeChat")
        assert result["category"] == FailureClassifier.PLANNER
        assert "candidates available" in result["detail"]

    # ── Layer 1c: Target not visible — no affordances → Perception ──

    def test_target_not_visible_no_exploration_one_candidate(self):
        fc = FailureClassifier()
        obs = self._frame([
            {"id": 2, "text": "sherry", "bbox": [0, 0, 100, 30]},
        ])
        result = fc.classify(obs, self._action(), "兴蓉", "WeChat")
        # 1 candidate, no affordance → Perception (insufficient info)
        assert result["category"] == FailureClassifier.PERCEPTION

    def test_target_not_visible_no_exploration_many_candidates(self):
        fc = FailureClassifier()
        obs = self._frame([
            {"id": 2, "text": "sherry", "bbox": [0, 0, 100, 30]},
            {"id": 3, "text": "家庭群", "bbox": [0, 40, 100, 30]},
        ])
        result = fc.classify(obs, self._action(), "兴蓉", "WeChat")
        # 2 candidates, no affordance → Planner (had enough info to choose better)
        assert result["category"] == FailureClassifier.PLANNER

    # ── Layer 1d: Target not visible — has affordance + correct use → OK ──

    def test_target_not_visible_scroll_is_correct(self):
        fc = FailureClassifier()
        obs = self._frame([
            {"id": 2, "text": "sherry", "bbox": [0, 0, 100, 30]},
            {"id": 3, "text": "家庭群", "bbox": [0, 40, 100, 30]},
            {"id": 4, "text": "同事群", "bbox": [0, 80, 100, 30]},
        ])
        result = fc.classify(obs, self._action("scroll", {"direction": "down"}), "兴蓉", "WeChat")
        assert result["category"] is None

    def test_target_not_visible_search_with_box(self):
        fc = FailureClassifier()
        obs = self._frame([
            {"id": 2, "text": "sherry", "bbox": [0, 0, 100, 30]},
            {"id": 5, "type": "input", "semantic": "SearchBox", "bbox": [0, 120, 100, 30], "text": "搜索"},
        ])
        result = fc.classify(obs, self._action("search", {"query": "兴蓉"}), "兴蓉", "WeChat")
        assert result["category"] is None

    # ── Layer 1e: Target not visible — has affordance + wrong click → Planner ──

    def test_target_not_visible_has_affordance_but_clicked(self):
        fc = FailureClassifier()
        obs = self._frame([
            {"id": 2, "text": "sherry", "bbox": [0, 0, 100, 30]},
            {"id": 3, "text": "家庭群", "bbox": [0, 40, 100, 30]},
            {"id": 4, "text": "同事群", "bbox": [0, 80, 100, 30]},
            {"id": 5, "type": "input", "semantic": "SearchBox", "bbox": [0, 120, 100, 30], "text": "搜索"},
        ])
        result = fc.classify(obs, self._action("click", {"element_id": 2}), "兴蓉", "WeChat")
        assert result["category"] == FailureClassifier.PLANNER
        assert "non-matching candidate" in result["detail"]

    # ── Layer 2: Action 不符合 Goal ──

    def test_planner_error_wrong_click_when_target_visible(self):
        fc = FailureClassifier()
        obs = self._frame([
            {"id": 2, "text": "文件传输助手", "bbox": [0, 0, 100, 30]},
            {"id": 3, "text": "兴蓉项目群", "bbox": [0, 40, 100, 30]},
        ])
        result = fc.classify(obs, self._action("click", {"element_id": 2}), "兴蓉", "WeChat")
        assert result["category"] == FailureClassifier.PLANNER
        assert "non-matching element" in result["detail"]

    def test_planner_error_no_action_when_target_visible(self):
        fc = FailureClassifier()
        obs = self._frame([{"id": 3, "text": "兴蓉项目群", "bbox": [0, 0, 100, 30]}])
        result = fc.classify(obs, None, "兴蓉", "WeChat")
        assert result["category"] == FailureClassifier.PLANNER

    def test_planner_correct_click(self):
        fc = FailureClassifier()
        obs = self._frame([{"id": 3, "text": "兴蓉项目群", "bbox": [0, 0, 100, 30]}])
        result = fc.classify(obs, self._action("click", {"element_id": 3}), "兴蓉", "WeChat")
        assert result["category"] is None

    # ── Layer 3: Action 执行失败 ──

    def test_action_error_execution_failed(self):
        fc = FailureClassifier()
        obs = self._frame([{"id": 3, "text": "兴蓉项目群", "bbox": [0, 0, 100, 30]}])
        result = fc.classify(obs, self._action("click", {"element_id": 3}, success=False),
                            "兴蓉", "WeChat", action_success=False)
        assert result["category"] == FailureClassifier.ACTION

    # ── Summary ──

    def test_summary_counts(self):
        fc = FailureClassifier()
        classifications = [
            {"category": "perception_error"},
            {"category": "perception_error"},
            {"category": "planner_error"},
            {"category": None},
        ]
        s = fc.summary(classifications)
        assert s["total_steps"] == 4
        assert s["perception_rate"] == 0.5
        assert s["planner_rate"] == 0.25

    def test_classify_trace(self):
        fc = FailureClassifier()
        obs1 = self._frame([
            {"id": 2, "text": "文件传输助手", "bbox": [0, 0, 100, 30]},
            {"id": 3, "text": "家庭群", "bbox": [0, 40, 100, 30]},
        ])
        obs2 = self._frame([{"id": 3, "text": "兴蓉项目群", "bbox": [0, 0, 100, 30]}])
        action = self._action("click", {"element_id": 2})
        trace = Trace(
            trace_id="t1", created_at=100.0,
            task={"instruction": "test", "target_context": {}, "metadata": {}},
            entries=[TraceEntry(obs_before=obs1, action=action, obs_after=obs2)],
        )
        results = fc.classify_trace(trace, "兴蓉", "WeChat")
        assert len(results) == 1
        assert results[0]["category"] == FailureClassifier.PLANNER


# ---- PlannerRecord ----


class TestPlannerRecord:

    def test_planner_record_in_trace(self):
        pr = PlannerRecord(
            prompt="Task: find xingrong",
            llm_response="I see the target, clicking it",
            tool_calls_raw=[{"name": "click", "params": {"element_id": 3}}],
            parsed_actions=[{"type": "click", "params": {"element_id": 3}}],
        )
        obs = ObsFrame(id=1, timestamp=100.0, active_window="WeChat",
                       scene_nodes=[{"id": 3, "text": "兴蓉项目群", "bbox": [0, 0, 100, 30]}])
        action = ActionRecord(id="a1", type="click", params={"element_id": 3})
        entry = TraceEntry(obs_before=obs, action=action, planner=pr)
        assert entry.planner.prompt == "Task: find xingrong"
        assert entry.planner.parsed_actions[0]["type"] == "click"


# ---- SyntheticVsRealComparator (structure only) ----


class TestComparatorStructure:

    def test_comparison_result(self):
        from mio_cua.evaluation.trace import ComparisonResult
        r = ComparisonResult(
            synthetic_valid_rate=0.3,
            real_valid_rate=0.2,
            gap=0.1,
            diagnosis="",
        )
        assert r.synthetic_valid_rate == 0.3
        assert r.gap == 0.1

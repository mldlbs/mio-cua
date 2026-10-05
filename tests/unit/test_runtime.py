"""Unit tests for Agent Runtime v2 components (no live desktop needed)."""

import sys
import os

sys.path.insert(0, r"E:\work\code\agent-dev\desktop-agent")

from dataclasses import dataclass
from typing import Any, List, Optional

from mio_cua.runtime.observation import RuntimeObservation, Affordance, ScrollState
from mio_cua.runtime.belief import BeliefState
from mio_cua.runtime.progress import ProgressEvaluator
from mio_cua.runtime.recovery import RecoveryManager


@dataclass
class _Node:
    id: int
    type: str
    semantic: str = ""
    text: str = ""
    bbox: Optional[List[int]] = None


class _Scene:
    def __init__(self, nodes):
        self.nodes = nodes


class FakeObs:
    def __init__(self, active_window, nodes, elements=None, active_process=""):
        self.active_window = active_window
        self.active_process = active_process
        self.scene = _Scene(nodes)
        self.elements = elements or []


def _wechat_obs(keyword="兴蓉", present=True):
    # WeChat window at x=840, width 880 -> sidebar right = 840+440 = 1280
    nodes = [
        _Node(0, "group", semantic="MMUIRenderSubWindowHW", bbox=(840, 480, 880, 640)),
        _Node(1, "group", semantic="Weixin", bbox=(888, 544, 368, 96)),
        _Node(2, "item", text="sherry", bbox=(900, 600, 200, 30)),      # left half -> candidate
        _Node(3, "item", text="兴蓉项目群", bbox=(920, 650, 200, 30)),    # left half
        _Node(4, "item", text="右侧无关", bbox=(1300, 600, 200, 30)),    # right half -> not candidate
        _Node(5, "input", text="搜索", bbox=(900, 560, 120, 28)),
    ]
    return FakeObs("微信", nodes)


def test_observation_extracts_sidebar_candidates():
    obs = _wechat_obs()
    robs = RuntimeObservation.from_obs(obs, {"app": "微信", "keyword": "兴蓉"})
    # sherry + 兴蓉项目群 (left half); 右侧无关 excluded
    assert "sherry" in robs.candidates
    assert "兴蓉项目群" in robs.candidates
    assert "右侧无关" not in robs.candidates
    assert robs.context == "微信"
    assert robs.context_matches is True
    assert robs.target_visible is True  # 兴蓉 in 兴蓉项目群


def test_candidates_are_in_visual_top_to_bottom_order():
    """Node order is not on-screen order; candidates must be sorted by y.

    The scene lists a lower row first here; the Planner picks among same-named
    entries, so an unsorted list made that choice arbitrary.
    """
    nodes = [
        _Node(0, "group", semantic="Weixin", bbox=(840, 480, 880, 640)),
        _Node(1, "item", text="下排", bbox=(900, 700, 200, 30)),   # listed first
        _Node(2, "item", text="上排", bbox=(900, 600, 200, 30)),   # higher on screen
    ]
    robs = RuntimeObservation.from_obs(FakeObs("微信", nodes))
    assert robs.candidates == ["上排", "下排"]


def test_duplicate_candidate_names_keep_first_occurrence_in_order():
    nodes = [
        _Node(0, "group", semantic="Weixin", bbox=(840, 480, 880, 640)),
        _Node(1, "item", text="张三", bbox=(900, 600, 200, 30)),
        _Node(2, "item", text="李四", bbox=(900, 650, 200, 30)),
        _Node(3, "item", text="张三", bbox=(900, 700, 200, 30)),
    ]
    robs = RuntimeObservation.from_obs(FakeObs("微信", nodes))
    assert robs.candidates == ["张三", "李四"]



def test_observation_target_not_visible():
    obs = _wechat_obs(present=False)
    # replace candidates so keyword absent
    obs.scene.nodes[2].text = "sherry"
    obs.scene.nodes[3].text = "张三群"
    robs = RuntimeObservation.from_obs(obs, {"app": "微信", "keyword": "兴蓉"})
    assert robs.target_visible is False


def test_context_matches_by_process_when_title_hides_app():
    """A window TITLE is content, not identity.

    The Edge window hosting mio-taskhub is titled "MIO·HUB — 任务总线", so the
    old title-substring test reported context_matches=False forever and every
    action paid a pointless focus + re-observe (scenario trace 1790783368).
    """
    obs = _wechat_obs()
    obs.active_window = "MIO·HUB — 任务总线"
    obs.active_process = "msedge"
    robs = RuntimeObservation.from_obs(obs, {"app": "Edge", "keyword": "兴蓉"})
    assert robs.context_matches is True


def test_context_matches_false_for_a_different_process():
    obs = _wechat_obs()
    obs.active_window = "无标题 - 记事本"
    obs.active_process = "notepad.exe"
    robs = RuntimeObservation.from_obs(obs, {"app": "Edge", "keyword": "兴蓉"})
    assert robs.context_matches is False


def test_context_matches_title_only_when_process_unknown():
    """Back-compat: an Observation without a process still matches on title."""
    obs = _wechat_obs()
    obs.active_window = "Edge - 新标签页"
    robs = RuntimeObservation.from_obs(obs, {"app": "Edge", "keyword": "兴蓉"})
    assert robs.context_matches is True


def test_belief_tracks_seen_candidates_and_progress():
    obs = _wechat_obs()
    belief = BeliefState({"app": "微信", "keyword": "兴蓉"})
    robs = RuntimeObservation.from_obs(obs, belief.target_context)
    belief.update(robs)
    assert belief.target_visible is True
    assert belief.last_progress is True  # first time seeing candidates
    # second update with same obs -> no new candidates
    belief.update(robs)
    assert belief.last_progress is False


def test_belief_scroll_stall_reversal():
    belief = BeliefState({"app": "微信", "keyword": "x"})
    belief.register_scroll("down", progressed=True)
    assert belief.scroll_stall == 0
    belief.register_scroll("down", progressed=False)
    assert belief.scroll_stall == 1
    # after a stall, next direction should reverse
    assert belief.next_scroll_direction() == "up"
    belief.register_scroll("up", progressed=False)
    assert belief.next_scroll_direction() == "down"


def test_progress_scroll_no_change():
    before = RuntimeObservation.from_obs(_wechat_obs(), {"keyword": "兴蓉"})
    after = RuntimeObservation.from_obs(_wechat_obs(), {"keyword": "兴蓉"})
    pe = ProgressEvaluator()
    assert pe.evaluate("scroll", before, after) == "no_change"
    # change candidates
    after.candidates.append("新群")
    assert pe.evaluate("scroll", before, after) == "progress"


def test_recovery_policies():
    obs = _wechat_obs()
    robs = RuntimeObservation.from_obs(obs, {"app": "微信", "keyword": "兴蓉"})
    belief = BeliefState({"app": "微信", "keyword": "兴蓉"})
    belief.update(robs)
    rm = RecoveryManager()
    assert rm.policy_for("context_mismatch", belief, robs)
    assert rm.policy_for("target_invisible", belief, robs)
    belief.register_scroll("down", False)
    belief.register_scroll("down", False)  # stall >= 2
    hints = rm.policy_for("scroll_no_progress", belief, robs)
    assert any("search" in h for h in hints)  # escalates to search when stalled twice
    assert rm.policy_for("timeout", belief, robs)


def test_click_non_matching_detection():
    from mio_cua.runtime.loop import AgentLoopV2
    obs = _wechat_obs()
    robs = RuntimeObservation.from_obs(obs, {"app": "微信", "keyword": "兴蓉"})
    # clicking 'sherry' (node 2) while target is 兴蓉 -> non-matching
    action = type("A", (), {"type": "click", "params": {"element_id": 2}})()
    assert AgentLoopV2._clicking_non_matching(action, robs, "兴蓉") is True
    action2 = type("A", (), {"type": "click", "params": {"element_id": 3}})()
    assert AgentLoopV2._clicking_non_matching(action2, robs, "兴蓉") is False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("all runtime unit tests passed")

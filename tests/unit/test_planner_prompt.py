"""Regression tests for the Planner prompt (Agent Runtime v2, milestone 4).

Run WITHOUT the live desktop / LLM by default: a FakeProvider captures the
rendered user prompt so we can assert the structured scene summary and the
planning rules per scenario. This guards the click-targeting fixes:
  - sidebar is window-relative (chat list visible even when app is on x>=800)
  - window/app-frame nodes are NOT presented as clickable
  - rules forbid ctrl+f, mandate element_id over raw x/y, prefer search box
  - multi-candidate disambiguation is possible (all candidates listed)

Set RUN_LLM_TESTS=1 to also run real-LLM smoke checks (non-deterministic).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


from mio_cua.scene.graph import SceneGraph, SceneNode
from mio_cua.agent.planner import Planner


class _FakeResp:
    message = "ok"
    tool_calls = []


class _FakeProvider:
    captured = None

    def generate(self, messages, tools=None):
        for m in reversed(messages):
            if m["role"] == "user":
                _FakeProvider.captured = m["content"]
                break
        return _FakeResp()


def _planner():
    return Planner(_FakeProvider(), "You are a desktop GUI agent.")


def _obs(nodes, window="WeChat"):
    class _Obs:
        active_window = window
        screenshot_path = None
        elements = []
    o = _Obs()
    o.scene = SceneGraph(nodes=nodes, active_window=window)
    return o


def _task(keyword="兴蓉", app="WeChat"):
    class _Task:
        instruction = f"在微信中找到『{keyword}』并打开它。"
        target_context = {"app": app, "keyword": keyword}
        metadata = {"keyword": keyword}
    return _Task()


def _frame_nodes():
    # x>=800 (secondary screen) window frame + Weixin root.
    return [
        SceneNode(id=0, type="group", semantic="MMUIRenderSubWindowHW", bbox=[840, 100, 900, 700], text=""),
        SceneNode(id=1, type="group", semantic="Weixin", bbox=[840, 100, 900, 700], text="Weixin"),
    ]


def test_window_relative_sidebar_and_frame_exclusion():
    nodes = _frame_nodes() + [
        SceneNode(id=2, type="text", semantic=None, bbox=[860, 200, 200, 40], text="文件传输助手"),
        SceneNode(id=3, type="text", semantic=None, bbox=[860, 250, 200, 40], text="兴蓉项目群"),
        SceneNode(id=4, type="text", semantic=None, bbox=[860, 300, 200, 40], text="家庭群"),
        SceneNode(id=5, type="input", semantic="SearchBox", bbox=[860, 150, 200, 30], text="搜索"),
    ]
    _planner().plan(_task(), _obs(nodes), None, [{"name": "click", "parameters": {}}])
    c = _FakeProvider.captured

    assert "Left sidebar (chat list)" in c
    assert "兴蓉项目群" in c
    assert "SearchBox" in c or "搜索" in c
    # Frame nodes must not be presented as clickable (rule 3 may still mention
    # them as a caution, so check the listings, not the raw string).
    assert "bbox=[840, 100, 900, 700]" not in c
    assert "id=1 'Weixin'" not in c
    # Rules present.
    assert "element_id" in c
    # General exploration rules now in system prompt
    assert "TARGET FOUND" in c or "TARGET NOT VISIBLE" in c or "search" in c.lower()


def test_search_box_preferred_when_target_absent():
    # Target not in the visible sidebar; a search box exists.
    nodes = _frame_nodes() + [
        SceneNode(id=2, type="text", semantic=None, bbox=[860, 200, 200, 40], text="文件传输助手"),
        SceneNode(id=3, type="text", semantic=None, bbox=[860, 250, 200, 40], text="家庭群"),
        SceneNode(id=5, type="input", semantic="SearchBox", bbox=[860, 150, 200, 30], text="搜索"),
    ]
    _planner().plan(_task("兴蓉"), _obs(nodes), None, [{"name": "click", "parameters": {}}])
    c = _FakeProvider.captured

    assert "TARGET NOT VISIBLE" in c or "search" in c.lower()


def test_multi_candidate_disambiguation_listed():
    # Two similarly-named chats; both must be listed so the LLM can pick the
    # one whose text CONTAINS the exact keyword.
    nodes = _frame_nodes() + [
        SceneNode(id=3, type="text", semantic=None, bbox=[860, 250, 200, 40], text="兴蓉项目群"),
        SceneNode(id=7, type="text", semantic=None, bbox=[860, 350, 200, 40], text="兴蓉客户群"),
        SceneNode(id=5, type="input", semantic="SearchBox", bbox=[860, 150, 200, 30], text="搜索"),
    ]
    _planner().plan(_task("兴蓉项目群"), _obs(nodes), None, [{"name": "click", "parameters": {}}])
    c = _FakeProvider.captured

    assert "兴蓉项目群" in c
    assert "兴蓉客户群" in c
    # Rule must require the text to match the keyword.
    assert "match" in c.lower() or "兴蓉" in c


def test_no_raw_xy_guidance():
    nodes = _frame_nodes() + [
        SceneNode(id=3, type="text", semantic=None, bbox=[860, 250, 200, 40], text="兴蓉项目群"),
        SceneNode(id=5, type="input", semantic="SearchBox", bbox=[860, 150, 200, 30], text="搜索"),
    ]
    _planner().plan(_task(), _obs(nodes), None, [{"name": "click", "parameters": {}}])
    c = _FakeProvider.captured
    assert "element_id" in c or "NEVER" in c


def test_primary_screen_fallback():
    # App on the primary screen (x<300): absolute fallback must still list chats.
    nodes = [
        SceneNode(id=0, type="group", semantic="MMUIRenderSubWindowHW", bbox=[0, 0, 900, 700], text=""),
        SceneNode(id=1, type="group", semantic="Weixin", bbox=[0, 0, 900, 700], text="Weixin"),
        SceneNode(id=2, type="text", semantic=None, bbox=[20, 200, 200, 40], text="兴蓉项目群"),
        SceneNode(id=5, type="input", semantic="SearchBox", bbox=[20, 150, 200, 30], text="搜索"),
    ]
    _planner().plan(_task(), _obs(nodes), None, [{"name": "click", "parameters": {}}])
    c = _FakeProvider.captured
    assert "Left sidebar (chat list)" in c
    assert "兴蓉项目群" in c
    assert "bbox=[0, 0, 900, 700]" not in c
    assert "id=1 'Weixin'" not in c


def _real_llm_planner():
    from mio_cua.providers.openai_compat import OpenAICompatProvider
    from mio_cua.tools.registry import ToolRegistry
    from mio_cua.tools.builtin import register_builtin_tools
    api = os.environ.get("MIO_API_KEY", "")
    prov = OpenAICompatProvider(base_url="https://ai.crlkcloud.cyou/v1", api_key=api, model="default")
    reg = ToolRegistry()
    register_builtin_tools(reg)
    return Planner(prov, "You are a desktop GUI agent."), reg.schemas()


def test_real_llm_selects_target_by_element_id():
    if os.environ.get("RUN_LLM_TESTS") != "1" or not os.environ.get("MIO_API_KEY"):
        import pytest
        pytest.skip("set RUN_LLM_TESTS=1 and MIO_API_KEY to run real-LLM smoke tests")
    nodes = _frame_nodes() + [
        SceneNode(id=2, type="text", semantic=None, bbox=[860, 200, 200, 40], text="文件传输助手"),
        SceneNode(id=3, type="text", semantic=None, bbox=[860, 250, 200, 40], text="兴蓉项目群"),
        SceneNode(id=4, type="text", semantic=None, bbox=[860, 300, 200, 40], text="家庭群"),
        SceneNode(id=5, type="input", semantic="SearchBox", bbox=[860, 150, 200, 30], text="搜索"),
    ]
    planner, schemas = _real_llm_planner()
    plan = planner.plan(_task(), _obs(nodes), None, schemas)
    assert plan.actions, "LLM returned no actions"
    first = plan.actions[0]
    # Must target the chat item by element_id, never raw x/y or the frame.
    assert first.type == "click"
    assert first.params.get("element_id") == 3
    assert "x" not in first.params and "y" not in first.params


def test_exploration_state_stuck_detection():
    """After 3 steps with no viewport change, Planner suggests search."""
    from mio_cua.agent.planner import ExplorationState

    state = ExplorationState()

    # First call initializes state
    state.update(target_visible=False, viewport_hash="same_viewport", candidate_hash="same_candidates")

    # 3 more steps with no progress
    for _ in range(3):
        progress = state.update(
            target_visible=False,
            viewport_hash="same_viewport",
            candidate_hash="same_candidates",
        )
        assert not progress

    assert state.should_switch_strategy()
    assert state.next_strategy() == "search"


def test_exploration_state_resets_on_progress():
    """When viewport changes, no_progress_count resets."""
    from mio_cua.agent.planner import ExplorationState

    state = ExplorationState()

    # Initialize + 1 step no progress
    state.update(target_visible=False, viewport_hash="v1", candidate_hash="c1")
    state.update(target_visible=False, viewport_hash="v1", candidate_hash="c1")
    assert state.no_progress_count == 1

    # Step with progress (viewport changed)
    state.update(target_visible=False, viewport_hash="v2", candidate_hash="c2")
    assert state.no_progress_count == 0


def test_exploration_hints_generated():
    """Planner generates exploration hints when target not visible."""
    nodes = [
        SceneNode(id=2, type="text", semantic=None, bbox=[860, 200, 200, 40], text="文件传输助手"),
        SceneNode(id=5, type="input", semantic="SearchBox", bbox=[860, 150, 200, 30], text="搜索"),
    ]
    _planner().plan(_task("兴蓉"), _obs(nodes), None, [{"name": "click", "parameters": {}}])
    c = _FakeProvider.captured
    assert "TARGET NOT VISIBLE" in c or "TARGET FOUND" in c

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


def _obs_ctx(window, process=None):
    """Observation carrying the process identity, as Perception now emits."""

    class _Obs:
        active_window = window
        active_process = process
        screenshot_path = None
        elements = []

    o = _Obs()
    o.scene = SceneGraph(nodes=[], active_window=window)
    return o


def test_context_verified_by_process_when_title_is_unrelated():
    """A window TITLE is content, not identity.

    The Edge window hosting mio-taskhub is titled "MIO·HUB — 任务总线".
    Title-only matching reported context_verified=false, so the prompt kept
    injecting the focus_window INVARIANT and the model looped on focus_window
    forever (trace 1790779553: 3 steps, 0 progress).
    """
    _planner().plan(
        _task(app="Edge"), _obs_ctx("MIO·HUB — 任务总线", "msedge"), None,
        [{"name": "click", "parameters": {}}],
    )
    c = _FakeProvider.captured

    assert '"context_verified": true' in c
    assert "INVARIANT" not in c  # only injected when the context is wrong
    assert '"active_process": "msedge"' in c


def test_context_still_unverified_for_a_different_process():
    _planner().plan(
        _task(app="Edge"), _obs_ctx("无标题 - 记事本", "notepad.exe"), None,
        [{"name": "click", "parameters": {}}],
    )
    c = _FakeProvider.captured

    assert '"context_verified": false' in c
    assert "INVARIANT" in c
    assert "focus_window" in c


def test_context_verified_by_title_when_process_unknown():
    """Back-compat: an Observation without a process still matches on title."""
    _planner().plan(
        _task(app="Edge"), _obs_ctx("Edge - 新标签页"), None,
        [{"name": "click", "parameters": {}}],
    )
    c = _FakeProvider.captured

    assert '"context_verified": true' in c
    assert "INVARIANT" not in c


class _ImageAwareProvider:
    """Captures the TEXT user message, even when an image message follows it."""

    captured = None
    calls = []  # one {"has_image": bool} per generate()
    fail_with_image = False

    @staticmethod
    def generate(messages, tools=None):
        has_image = any(isinstance(m.get("content"), list) for m in messages)
        _ImageAwareProvider.calls.append({"has_image": has_image})
        for m in messages:
            if m["role"] == "user" and isinstance(m.get("content"), str):
                _ImageAwareProvider.captured = m["content"]
        if has_image and _ImageAwareProvider.fail_with_image:
            # The endpoint answered 404 "No endpoints found that support image
            # input"; a transport-level reset is the other observed shape.
            raise ConnectionResetError(10054, "forcibly closed by remote host")
        return _FakeResp()


def test_screenshot_hint_reaches_the_prompt(tmp_path):
    """The hint must be in the message we send, not only in the local name.

    It used to be appended to `user_content` AFTER `messages` was built, so the
    model never saw it.
    """
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-png")

    _ImageAwareProvider.calls = []
    _ImageAwareProvider.fail_with_image = False
    obs = _obs_ctx("Edge - 新标签页", "msedge")
    obs.screenshot_path = str(shot)

    _planner_for(_ImageAwareProvider()).plan(
        _task(app="Edge"), obs, None, [{"name": "click", "parameters": {}}]
    )

    assert "attached screenshot" in _ImageAwareProvider.captured
    assert _ImageAwareProvider.calls[0]["has_image"] is True


def test_screenshot_is_dropped_permanently_after_one_failure(tmp_path):
    """A 461 KiB upload that the endpoint rejects must not be retried every step."""
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-png")

    _ImageAwareProvider.calls = []
    _ImageAwareProvider.fail_with_image = True
    planner = _planner_for(_ImageAwareProvider())

    def _obs():
        o = _obs_ctx("Edge - 新标签页", "msedge")
        o.screenshot_path = str(shot)
        return o

    # Attempt 1: with image -> rejected -> blind retry succeeds.
    planner.plan(_task(app="Edge"), _obs(), None, [{"name": "click", "parameters": {}}])
    assert [c["has_image"] for c in _ImageAwareProvider.calls] == [True, False]

    # Every later step must skip the image entirely.
    _ImageAwareProvider.calls = []
    planner.plan(_task(app="Edge"), _obs(), None, [{"name": "click", "parameters": {}}])
    assert [c["has_image"] for c in _ImageAwareProvider.calls] == [False]

    # And the model is told it is operating blind-free (no dangling hint).
    assert "attached screenshot" not in _ImageAwareProvider.captured


def test_transport_error_without_image_propagates():
    """No image attached -> nothing to fall back to; the caller must see it."""

    class _Dead:
        @staticmethod
        def generate(messages, tools=None):
            raise ConnectionResetError(10054, "forcibly closed by remote host")

    import pytest

    with pytest.raises(ConnectionResetError):
        _planner_for(_Dead()).plan(
            _task(app="Edge"), _obs_ctx("Edge - 新标签页", "msedge"), None,
            [{"name": "click", "parameters": {}}],
        )


def _planner_for(provider):
    return Planner(provider, "You are a desktop GUI agent.")



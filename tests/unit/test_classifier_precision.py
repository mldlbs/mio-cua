"""FailureClassifier precision: two false positives from trace_1790812617.

Both steps below were scored planner_error even though the agent behaved
correctly, which is what made a 6-step successful run report 50% planner
failure:

  step 3  action=type  {"text": "今日新闻"}      -> planner_error "no action"
  step 4  action=click {"element_id": 104}       -> planner_error @0.95
          node 104 = {"type": "button", "text": "搜索", "semantic": "搜索"}
          sitting right next to node 105 = {"text": "今日新闻"} (the input)
"""

import sys

sys.path.insert(0, r"E:\work\code\agent-dev\desktop-agent")

from mio_cua.evaluation.recorder import ActionRecord, ObsFrame
from mio_cua.evaluation.trace import FailureClassifier

KEYWORD = "今日新闻"
APP = "Edge"

# Nodes captured from the real trace (Bing new-tab / results page).
_SEARCH_BOX = {"id": 7, "type": "input", "text": "搜索", "semantic": "search"}
_TYPED_INPUT = {"id": 88, "type": "input", "text": "今日新闻", "semantic": "input"}
_SEARCH_BUTTON = {"id": 104, "type": "button", "text": "搜索", "semantic": "搜索"}
_UNRELATED_BUTTON = {"id": 55, "type": "button", "text": "关闭", "semantic": ""}
_GOOGLE_LINK = {"id": 210, "type": "link", "text": "Google 新闻", "semantic": "link"}


def _obs(window="新建标签页 - 个人 - Microsoft Edge", nodes=(_SEARCH_BOX,)):
    return ObsFrame(
        id=1,
        timestamp=0.0,
        active_window=window,
        scene_nodes=[dict(n) for n in nodes],
        active_process="msedge",
    )


def _classify(obs, action):
    return FailureClassifier().classify(
        observation=obs,
        action=action,
        goal_keyword=KEYWORD,
        goal_app=APP,
    )


def test_typing_the_keyword_is_progress_not_a_planner_failure():
    """step 3: target absent, agent types it in -> must not be an error."""
    action = ActionRecord(id="a3", type="type", params={"text": KEYWORD})
    result = _classify(_obs(), action)
    assert result["category"] is None, result
    assert "search box" in result["detail"]


def test_pressing_enter_after_typing_is_not_an_error():
    action = ActionRecord(id="a4", type="key", params={"keys": "enter"})
    result = _classify(_obs(), action)
    assert result["category"] is None, result


def test_clicking_the_search_button_submits_the_typed_keyword():
    """step 4: click 搜索 (id 104) with 今日新闻 already in the input."""
    nodes = (_TYPED_INPUT, _SEARCH_BUTTON)
    action = ActionRecord(id="a5", type="click", params={"element_id": 104})
    result = _classify(_obs(nodes=nodes), action)
    assert result["category"] is None, result


def test_clicking_a_genuinely_unrelated_element_is_still_flagged():
    nodes = (_TYPED_INPUT, _UNRELATED_BUTTON)
    action = ActionRecord(id="a6", type="click", params={"element_id": 55})
    result = _classify(_obs(nodes=nodes), action)
    assert result["category"] == FailureClassifier.PLANNER
    assert result["confidence"] >= 0.9


def test_a_google_link_is_not_mistaken_for_the_submit_button():
    """The Latin label 'go' must not match inside 'Google 新闻'."""
    nodes = (_TYPED_INPUT, _GOOGLE_LINK)
    action = ActionRecord(id="a7", type="click", params={"element_id": 210})
    result = _classify(_obs(nodes=nodes), action)
    assert result["category"] == FailureClassifier.PLANNER


def test_no_action_while_the_search_box_sits_idle_is_still_a_planner_error():
    """Guards against the fix turning every branch into a pass."""
    result = _classify(_obs(), action=None)
    assert result["category"] == FailureClassifier.PLANNER
    assert "no action" in result["detail"]


def test_refocusing_a_window_that_already_matches_is_flagged():
    """Re-focusing is the old INVARIANT loop, not progress."""
    action = ActionRecord(id="a8", type="focus_window", params={"title": APP})
    result = _classify(_obs(), action)
    assert result["category"] == FailureClassifier.PLANNER

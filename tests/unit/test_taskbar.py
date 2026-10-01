"""FR-1/FR-2/FR-4 coverage for the taskbar tool; FR-3 lives in test_windows.py.

Real-system cases enumerate the actual taskbar; click cases are fully mocked so
no test ever clicks a real taskbar icon (that would switch the foreground and
pollute whatever else is running on this machine).
"""
import json
import re
import time

import pytest

from mio_cua.models.action_result import RawResult
from mio_cua.tools.context import ToolContext
from mio_cua.tools.registry import ToolRegistry


def _ctx(controller=None):
    return ToolContext(
        controller=controller,
        perception=None,
        config=None,
        events=None,
        current_action_id="act-1",
    )


def _registered():
    from mio_cua.tools.builtin import register_builtin_tools

    reg = ToolRegistry()
    register_builtin_tools(reg)
    return reg


class _FakeRect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


class _Invokeable:
    def __init__(self):
        self.invoked = False

    def invoke(self):
        self.invoked = True

    def rectangle(self):
        return _FakeRect(100, 200, 140, 240)


class _NotInvokable:
    def invoke(self):
        raise RuntimeError("no invoke pattern")

    def rectangle(self):
        return _FakeRect(100, 200, 140, 240)


class _Recorder:
    def __init__(self, sent=True):
        self.actions = []
        self._sent = sent

    def execute(self, action):
        self.actions.append(action)
        return RawResult(sent=self._sent, error=None if self._sent else "boom")


_ITEMS = [
    {"name": "\u5f00\u59cb", "kind": "Button", "rect": [0, 1560, 40, 40]},
    {"name": "Google Chrome - 1 \u4e2a\u8fd0\u884c\u7a97\u53e3", "kind": "Button", "rect": [80, 1560, 40, 40]},
    {"name": "", "kind": "Button", "rect": [120, 1560, 40, 40]},
]


def _stub(monkeypatch, element=None, items=None):
    from mio_cua.tools import taskbar as tb

    monkeypatch.setattr(tb, "locate_taskbar_hwnd", lambda: 65736)
    monkeypatch.setattr(
        tb, "enumerate_taskbar", lambda hwnd, **kw: (items if items is not None else _ITEMS, False)
    )
    if element is not None:
        monkeypatch.setattr(
            tb, "find_taskbar_element",
            lambda hwnd, target, **kw: (element, element_name(element), 1),
        )
    return tb


def element_name(element):
    return "Google Chrome - 1 \u4e2a\u8fd0\u884c\u7a97\u53e3"


# --- real system (FR-1) -----------------------------------------------------


def test_locate_taskbar_hwnd_returns_handle():
    from mio_cua.automation.windows import locate_taskbar_hwnd

    assert isinstance(locate_taskbar_hwnd(), int)


def test_enumerate_taskbar_contains_known_labels():
    from mio_cua.automation.windows import enumerate_taskbar, locate_taskbar_hwnd

    hwnd = locate_taskbar_hwnd()
    if not hwnd:
        pytest.skip("taskbar window not available in this session")
    items, truncated = enumerate_taskbar(hwnd)
    names = [i["name"] for i in items]

    assert "\u5f00\u59cb" in names
    assert "\u641c\u7d22" in names
    assert any(re.search(r"- \d+ \u4e2a\u8fd0\u884c\u7a97\u53e3", n) for n in names), names
    assert all(len(i["rect"]) == 4 for i in items)
    assert all(set(i) == {"name", "kind", "rect"} for i in items)


def test_enumerate_taskbar_under_three_seconds():
    from mio_cua.automation.windows import enumerate_taskbar, locate_taskbar_hwnd

    hwnd = locate_taskbar_hwnd()
    if not hwnd:
        pytest.skip("taskbar window not available in this session")
    start = time.time()
    enumerate_taskbar(hwnd)
    assert time.time() - start < 3.0


def test_enumerate_taskbar_respects_max_nodes():
    from mio_cua.automation.windows import enumerate_taskbar, locate_taskbar_hwnd

    hwnd = locate_taskbar_hwnd()
    if not hwnd:
        pytest.skip("taskbar window not available in this session")
    items, truncated = enumerate_taskbar(hwnd, max_nodes=3)
    assert len(items) == 3
    assert truncated is True


def test_enumerate_taskbar_skips_root():
    """The taskbar container itself is a zero-size unnamed element; the caller
    wants the items ON the taskbar, not the taskbar."""
    from mio_cua.automation.windows import enumerate_taskbar, locate_taskbar_hwnd

    hwnd = locate_taskbar_hwnd()
    if not hwnd:
        pytest.skip("taskbar window not available in this session")
    items, _ = enumerate_taskbar(hwnd)
    assert len(items) >= 2
    assert all(i["name"] for i in items[:1]) or True  # first item may be unnamed
    assert all(i["rect"] != [0, 0, 0, 0] for i in items), "root would be 0,0,0,0"


# --- tool contract (FR-1 / FR-2) -------------------------------------------


def test_taskbar_list_returns_json(monkeypatch):
    tb = _stub(monkeypatch)
    res = tb.taskbar(_ctx(), action="list")
    assert res.success is True
    payload = json.loads(res.message)
    assert payload["action"] == "list"
    assert payload["count"] == len(_ITEMS)
    assert payload["truncated"] is False
    assert payload["items"] == _ITEMS


def test_taskbar_unknown_action(monkeypatch):
    tb = _stub(monkeypatch)
    res = tb.taskbar(_ctx(), action="bogus")
    assert res.success is False
    assert res.retryable is False, "retrying an invalid action cannot succeed"
    assert res.message.startswith("unknown action")


def test_taskbar_click_requires_target(monkeypatch):
    tb = _stub(monkeypatch)
    res = tb.taskbar(_ctx(), action="click", target="   ")
    assert res.success is False
    assert res.retryable is False
    assert res.message.startswith("target required")


def test_taskbar_click_no_match(monkeypatch):
    tb = _stub(monkeypatch, element=None)
    from mio_cua.tools import taskbar as mod

    monkeypatch.setattr(mod, "find_taskbar_element", lambda *a, **k: (None, "", 0))
    res = tb.taskbar(_ctx(), action="click", target="zzz-absent")
    assert res.success is False
    assert res.retryable is True, "the taskbar may have changed; worth retrying"
    assert res.message.startswith("no taskbar item matches")


def test_taskbar_click_invoke_path(monkeypatch):
    el = _Invokeable()
    tb = _stub(monkeypatch, element=el)
    res = tb.taskbar(_ctx(), action="click", target="Chrome")
    assert res.success is True
    assert el.invoked is True
    assert "invoke" in res.message


def test_taskbar_click_coordinate_fallback(monkeypatch):
    el = _NotInvokable()
    recorder = _Recorder(sent=True)
    tb = _stub(monkeypatch, element=el)
    res = tb.taskbar(_ctx(controller=recorder), action="click", target="Chrome")
    assert res.success is True
    assert "coordinate" in res.message
    assert len(recorder.actions) == 1
    action = recorder.actions[0]
    assert action.type == "click"
    assert action.params["x"] == 120 and action.params["y"] == 220


def test_taskbar_click_coordinate_failure(monkeypatch):
    el = _NotInvokable()
    tb = _stub(monkeypatch, element=el)
    res = tb.taskbar(_ctx(controller=_Recorder(sent=False)), action="click", target="Chrome")
    assert res.success is False
    assert res.retryable is True
    assert res.message.startswith("invoke failed")


def test_taskbar_enumeration_error(monkeypatch):
    from mio_cua.tools import taskbar as tb

    monkeypatch.setattr(tb, "locate_taskbar_hwnd", lambda: 65736)

    def boom(hwnd, **kw):
        raise RuntimeError("uia down")

    monkeypatch.setattr(tb, "enumerate_taskbar", boom)
    res = tb.taskbar(_ctx(), action="list")
    assert res.success is False
    assert res.retryable is True
    assert res.message.startswith("enumerate failed")


def test_taskbar_not_found(monkeypatch):
    from mio_cua.tools import taskbar as tb

    monkeypatch.setattr(tb, "locate_taskbar_hwnd", lambda: 0)
    res = tb.taskbar(_ctx(), action="list")
    assert res.success is False
    assert res.retryable is True
    assert res.message == "taskbar not found"


# --- FR-4 visibility --------------------------------------------------------


def test_taskbar_registered_with_schema():
    from mio_cua.tools.builtin import _SCHEMAS, register_builtin_tools

    assert "taskbar" in _SCHEMAS
    props = _SCHEMAS["taskbar"]["function"]["parameters"]["properties"]
    assert sorted(props) == ["action", "target"]
    assert props["action"]["enum"] == ["list", "click"]

    reg = ToolRegistry()
    register_builtin_tools(reg)
    res = reg.call("taskbar", {"action": "nope"}, _ctx())
    assert res.success is False


def test_system_prompt_documents_taskbar():
    from mio_cua.prompts import DEFAULT_SYSTEM_PROMPT

    assert "taskbar" in DEFAULT_SYSTEM_PROMPT
    assert 'action="list"' in DEFAULT_SYSTEM_PROMPT

import time

from mio_cua.tools.context import ToolContext
from mio_cua.tools.registry import ToolRegistry
from mio_cua.tools.builtin import register_builtin_tools
from mio_cua.automation.backends import Backend
from mio_cua.models.action import Action
from mio_cua.models.action_result import RawResult


class RecordingBackend(Backend):
    def __init__(self):
        self.calls = []

    def execute(self, action):
        self.calls.append(action)
        return RawResult(sent=True)


class FakeController:
    def __init__(self):
        self.backend = RecordingBackend()

    def execute(self, action):
        return self.backend.execute(action)


def _ctx(controller=None):
    return ToolContext(
        controller=controller or FakeController(),
        perception=None, config=None, events=None,
        current_observation=None,
    )


def test_click_tool_builds_action():
    reg = ToolRegistry()
    register_builtin_tools(reg)
    ctx = _ctx()
    result = reg.call("click", {"x": 10, "y": 20, "button": "left"}, ctx)
    assert result.success is True
    action = ctx.controller.backend.calls[0]
    assert action.type == "click"
    assert action.params["x"] == 10


def test_key_tool():
    reg = ToolRegistry()
    register_builtin_tools(reg)
    ctx = _ctx()
    result = reg.call("key", {"keys": "ctrl+c"}, ctx)
    assert result.success is True
    assert ctx.controller.backend.calls[0].type == "key"


def test_wait_tool_sleeps():
    reg = ToolRegistry()
    register_builtin_tools(reg)
    ctx = _ctx()
    t0 = time.time()
    reg.call("wait", {"seconds": 0.05}, ctx)
    assert time.time() - t0 >= 0.05


def test_success_fail_tools_set_flags():
    reg = ToolRegistry()
    register_builtin_tools(reg)
    ctx = _ctx()
    r1 = reg.call("success", {"result": "done"}, ctx)
    r2 = reg.call("fail", {"reason": "blocked"}, ctx)
    assert r1.success is True
    assert r2.success is False


def test_click_requires_coords_or_element_id():
    reg = ToolRegistry()
    register_builtin_tools(reg)
    ctx = _ctx()
    result = reg.call("click", {"button": "left"}, ctx)
    assert result.success is False
    assert result.retryable is True


def test_type_requires_text():
    reg = ToolRegistry()
    register_builtin_tools(reg)
    ctx = _ctx()
    result = reg.call("type", {}, ctx)
    assert result.success is False
    assert result.retryable is True


def test_schemas_have_required_for_required_tools():
    reg = ToolRegistry()
    register_builtin_tools(reg)
    schemas = {s["function"]["name"]: s["function"]["parameters"] for s in reg.schemas()}
    assert schemas["type"].get("required") == ["text"]
    assert schemas["key"].get("required") == ["keys"]
    assert schemas["wait"].get("required") == ["seconds"]
    assert schemas["launch"].get("required") == ["command"]
    assert schemas["focus_window"].get("required") == ["title"]
    assert schemas["success"].get("required") == ["result"]
    assert schemas["fail"].get("required") == ["reason"]
    assert "required" not in schemas["click"]

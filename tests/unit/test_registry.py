from mio_cua.tools.registry import ToolRegistry
from mio_cua.tools.context import ToolContext
from mio_cua.models.action_result import ActionResult
from mio_cua.safety.confirm import Confirmation


def test_register_and_call():
    reg = ToolRegistry()
    ctx = ToolContext(controller=None, perception=None, config=None, events=None)

    def my_tool(ctx, value):
        return ActionResult(action_id="a-1", success=True, message=str(value))

    reg.register("my_tool", my_tool, {"name": "my_tool"})
    result = reg.call("my_tool", {"value": 42}, ctx)
    assert result.success is True
    assert result.message == "42"


def test_schemas_returned():
    reg = ToolRegistry()
    reg.register("t", lambda ctx: None, {"name": "t"})
    assert reg.schemas() == [{"name": "t"}]


def test_call_unknown_raises():
    reg = ToolRegistry()
    try:
        reg.call("nope", {}, None)
        assert False
    except KeyError:
        pass


class FakeConfirm:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def confirm(self, name, params):
        self.calls.append((name, params))
        return self.answer


def _tool(ctx, **kwargs):
    return ActionResult(action_id="a-1", success=True, message="ran")


def test_high_risk_denied_returns_failure_no_retry():
    confirm = FakeConfirm(False)
    reg = ToolRegistry(confirmation=confirm)
    reg.register("delete", _tool, {"type": "function", "function": {
        "name": "delete", "risk": "high"}})
    ctx = ToolContext(controller=None, perception=None, config=None, events=None)
    result = reg.call("delete", {"target": "x.txt"}, ctx)
    assert result.success is False
    assert result.retryable is False
    assert "user rejected" in result.message
    assert confirm.calls == [("delete", {"target": "x.txt"})]


def test_high_risk_approved_runs_tool():
    confirm = FakeConfirm(True)
    reg = ToolRegistry(confirmation=confirm)
    reg.register("delete", _tool, {"type": "function", "function": {
        "name": "delete", "risk": "high"}})
    ctx = ToolContext(controller=None, perception=None, config=None, events=None)
    result = reg.call("delete", {"target": "x.txt"}, ctx)
    assert result.success is True
    assert result.message == "ran"
    assert confirm.calls == [("delete", {"target": "x.txt"})]


def test_low_risk_skips_confirmation():
    confirm = FakeConfirm(False)  # would deny, but must never be asked
    reg = ToolRegistry(confirmation=confirm)
    reg.register("click", _tool, {"type": "function", "function": {"name": "click"}})
    ctx = ToolContext(controller=None, perception=None, config=None, events=None)
    result = reg.call("click", {"x": 1}, ctx)
    assert result.success is True
    assert confirm.calls == []


def test_high_risk_name_fallback_without_marker():
    """A tool whose schema omits risk:'high' but whose name is in the HIGH_RISK
    list must still be confirmed (name-based safety net)."""
    confirm = FakeConfirm(False)
    reg = ToolRegistry(confirmation=confirm)
    # schema has NO risk marker -> old logic would skip confirmation
    reg.register("kill_process", _tool, {"type": "function", "function": {
        "name": "kill_process"}})
    ctx = ToolContext(controller=None, perception=None, config=None, events=None)
    result = reg.call("kill_process", {"name": "notepad"}, ctx)
    assert result.success is False
    assert result.retryable is False
    assert "user rejected" in result.message
    assert confirm.calls == [("kill_process", {"name": "notepad"})]


def test_low_risk_name_not_confirmed_even_with_any_schema():
    confirm = FakeConfirm(False)
    reg = ToolRegistry(confirmation=confirm)
    reg.register("click", _tool, {"type": "function", "function": {"name": "click"}})
    ctx = ToolContext(controller=None, perception=None, config=None, events=None)
    result = reg.call("click", {"x": 1}, ctx)
    assert result.success is True
    assert confirm.calls == []

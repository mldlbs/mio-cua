from mio_cua.tools.registry import ToolRegistry
from mio_cua.tools.context import ToolContext
from mio_cua.models.action_result import ActionResult


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

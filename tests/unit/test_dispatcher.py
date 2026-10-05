from mio_cua.agent.dispatcher import Dispatcher
from mio_cua.models.action import Action, Plan
from mio_cua.models.action_result import ActionResult
from mio_cua.tools.context import ToolContext


class FakeSafety:
    def __init__(self, stop_after=99):
        self.n = 0
        self.step_count = 0
        self.stop_after = stop_after

    def should_stop(self):
        self.n += 1
        return self.n > self.stop_after

    def record_step(self):
        self.step_count += 1


class FakeRegistry:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def call(self, name, params, ctx):
        self.calls.append((name, ctx.current_action_id))
        return self.results.pop(0)


def _ctx():
    return ToolContext(controller=None, perception=None, config=None, events=None)


def test_dispatcher_runs_actions_and_sets_action_id():
    reg = FakeRegistry([ActionResult("a-1", True), ActionResult("a-2", False, retryable=True)])
    d = Dispatcher(reg)
    plan = Plan(actions=[Action("a-1", "click", {"x": 1}), Action("a-2", "type", {"text": "x"})])
    ctx = _ctx()
    results = d.execute(plan, safety=FakeSafety(), ctx=ctx)
    assert [r.success for r in results] == [True, False]
    assert reg.calls == [("click", "a-1"), ("type", "a-2")]


def test_dispatcher_stops_on_safety():
    reg = FakeRegistry([ActionResult("a-1", True)])
    d = Dispatcher(reg)
    plan = Plan(actions=[Action("a-1", "click", {}), Action("a-2", "key", {})])
    results = d.execute(plan, safety=FakeSafety(stop_after=0), ctx=_ctx())
    assert len(results) == 0


def test_dispatcher_records_steps():
    safety = FakeSafety()
    reg = FakeRegistry([ActionResult("a-1", True), ActionResult("a-2", True)])
    d = Dispatcher(reg)
    plan = Plan(actions=[Action("a-1", "click", {}), Action("a-2", "key", {})])
    d.execute(plan, safety=safety, ctx=_ctx())
    assert safety.step_count == 2


def test_dispatcher_recover_runs_with_ctx():
    def recover(action, result, ctx):
        return ActionResult(action.id, success=True, message="recovered")

    reg = FakeRegistry([ActionResult("a-1", False, retryable=True)])
    d = Dispatcher(reg, recover=recover)
    plan = Plan(actions=[Action("a-1", "click", {})])
    results = d.execute(plan, safety=FakeSafety(), ctx=_ctx())
    assert results[0].success is True
    assert results[0].message == "recovered"


def test_dispatcher_tool_exception_becomes_retryable_result():
    class RaisingRegistry:
        def call(self, name, params, ctx):
            raise RuntimeError("boom")

    d = Dispatcher(RaisingRegistry())
    plan = Plan(actions=[Action("a-1", "click", {})])
    results = d.execute(plan, safety=FakeSafety(), ctx=_ctx())
    assert results[0].success is False
    assert results[0].retryable is True

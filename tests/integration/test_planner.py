from mio_cua.agent.planner import Planner, _summarize, _tool_routing_hint
from mio_cua.models.observation import Observation
from mio_cua.models.action import Plan, ToolCall
from mio_cua.models.element import Element
from mio_cua.models.task import Task
from mio_cua.providers.base import LLMResponse
from mio_cua.memory.history import History


def _task():
    return Task(instruction="open calc")


class FakeProvider:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.last_messages = None
        self.last_tools = None

    def generate(self, messages, tools=None):
        self.last_messages = messages
        self.last_tools = tools
        return LLMResponse(message="ok", tool_calls=self.tool_calls)


def _tc(name, args):
    return ToolCall(id="t1", name=name, arguments=args)


def test_planner_converts_tool_calls_to_plan():
    prov = FakeProvider([_tc("click", {"x": 10, "y": 20}), _tc("type", {"text": "hi"})])
    planner = Planner(prov, system_prompt="sys")
    obs = Observation(None, 1.0, "Calc", 1.0, [])
    plan = planner.plan(_task(), obs, None, tools=[{"name": "click"}])
    assert isinstance(plan, Plan)
    assert len(plan.actions) == 2
    assert plan.actions[0].type == "click"
    assert plan.actions[1].params["text"] == "hi"


def test_planner_passes_tools():
    prov = FakeProvider([])
    planner = Planner(prov, system_prompt="sys")
    planner.plan(_task(), Observation(None, 1.0, None, 1.0, []), None, tools=[{"name": "a"}, {"name": "b"}])
    assert prov.last_tools is not None
    assert len(prov.last_tools) == 2


def test_planner_includes_recent_actions():
    prov = FakeProvider([])
    planner = Planner(prov, system_prompt="sys")
    h = History()
    h.record("a-1", "launch", True)
    h.record("a-2", "type", False)
    planner.plan(_task(), Observation(None, 1.0, "Calc", 1.0, []), None, tools=[], history=h)
    user = prov.last_messages[1]["content"]
    assert "Tool results" in user
    assert "launch OK" in user
    assert "type FAIL" in user


def test_planner_includes_tool_result_message():
    prov = FakeProvider([])
    planner = Planner(prov, system_prompt="sys")
    h = History()
    h.record("a-1", "list_dir", True, "a.txt\nb.pdf\n新建文件夹")
    planner.plan(_task(), Observation(None, 1.0, "Calc", 1.0, []), None, tools=[], history=h)
    user = prov.last_messages[1]["content"]
    assert "list_dir OK" in user
    assert "a.txt" in user
    assert "新建文件夹" in user


def test_summarize_dedupes_similar_elements():
    els = [
        Element(0, "ocr", text="OK", role="Button", bbox=(10, 20, 40, 20)),
        Element(1, "uia", text="OK", role="Button", bbox=(11, 21, 40, 20)),  # near-duplicate
        Element(2, "uia", text="Cancel", role="Button", bbox=(100, 200, 40, 20)),
    ]
    out = _summarize(Observation(None, 1.0, None, 1.0, els))
    assert "id=0" in out
    assert "id=1" not in out  # collapsed as duplicate
    assert "id=2" in out
    assert out.count("- id=") == 2


def test_tool_routing_hint_for_explorer():
    hint = _tool_routing_hint("桌面 - 文件资源管理器")
    assert hint is not None
    assert "list_dir" in hint
    assert "move_file" in hint


def test_tool_routing_hint_none_for_normal_apps():
    assert _tool_routing_hint("计算器") is None
    assert _tool_routing_hint("无标题 - 记事本") is None
    assert _tool_routing_hint("") is None


def test_planner_injects_routing_hint():
    prov = FakeProvider([])
    planner = Planner(prov, system_prompt="sys")
    planner.plan(_task(), Observation(None, 1.0, "桌面 - 文件资源管理器", 1.0, []), None, tools=[], history=None)
    user = prov.last_messages[1]["content"]
    assert "ROUTING" in user

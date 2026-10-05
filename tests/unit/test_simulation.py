from mio_cua.models.action import Action
from mio_cua.models.observation import Observation
from mio_cua.models.element import Element
from mio_cua.simulation import (
    RecordingController, RecordingBackend, ScriptedPerception,
    build_simulation, MockDesktop, _install_safe_tools,
)
from mio_cua.tools.registry import ToolRegistry
from mio_cua.tools.builtin import register_builtin_tools


def test_safe_tools_neutralize_launch_and_focus():
    registry = ToolRegistry()
    register_builtin_tools(registry)
    _install_safe_tools(registry)
    from mio_cua.tools.context import ToolContext

    class Ctx:
        current_action_id = "a-1"

    r = registry.call("launch", {"command": "notepad"}, Ctx())
    assert r.success is True
    assert "[sim]" in r.message


def test_mock_desktop_type_save_flow():
    d = MockDesktop()
    assert d.observe().active_window == "无标题 - 记事本"

    d.execute(Action("a", "type", {"text": "hello world"}))
    assert d.text == "hello world"

    d.execute(Action("a", "key", {"keys": "ctrl+s"}))
    assert d.dialog_open is True
    assert "Save" in [e.text for e in d.observe().elements]

    d.execute(Action("a", "type", {"text": "demo.txt"}))
    assert d.filename == "demo.txt"

    d.execute(Action("a", "key", {"keys": "enter"}))
    assert d.saved is True
    assert d.completed is True
    assert "demo.txt" in d.observe().active_window


def test_mock_desktop_click_save_alternative():
    d = MockDesktop()
    d.execute(Action("a", "type", {"text": "x"}))
    d.execute(Action("a", "key", {"keys": "ctrl+s"}))
    d.execute(Action("a", "type", {"text": "demo.txt"}))
    d.execute(Action("a", "click", {"x": 640, "y": 352}))  # Save button center
    assert d.saved is True


def test_mock_desktop_click_outside_save_keeps_dialog():
    d = MockDesktop()
    d.execute(Action("a", "key", {"keys": "ctrl+s"}))
    d.execute(Action("a", "click", {"x": 10, "y": 10}))  # miss
    assert d.dialog_open is True
    assert d.saved is False


def test_mock_calculator_flow():
    d = MockDesktop(scenario="calculator")
    for label, x, y in [("1", 425, 455), ("2", 485, 455), ("3", 545, 455),
                        ("×", 605, 415), ("4", 425, 415), ("5", 485, 415),
                        ("6", 545, 415), ("=", 545, 495)]:
        d.execute(Action("a", "click", {"x": x, "y": y}))
    assert d.completed is True
    assert d.result == "56088"


def test_mock_calculator_clear():
    d = MockDesktop(scenario="calculator")
    d.execute(Action("a", "click", {"x": 425, "y": 455}))  # 1
    d.execute(Action("a", "click", {"x": 425, "y": 535}))  # AC
    assert d.expr == ""
    assert not d.completed


def test_mock_explorer_flow():
    d = MockDesktop(scenario="explorer")
    d.execute(Action("a", "click", {"x": 460, "y": 215}))  # 新建文件夹
    assert d.folder_exists is True
    assert "Edit" in [e.role for e in d.observe().elements]  # rename box shown
    d.execute(Action("a", "type", {"text": "demo"}))
    assert d.folder_name == "demo"
    assert d.completed is True


def test_recording_controller_records_actions():
    c = RecordingController()
    r = c.execute(Action("a-1", "click", {"x": 1, "y": 2}))
    assert r.sent is True
    assert c.calls[0].type == "click"
    assert c.calls[0].params["x"] == 1


def test_scripted_perception_loops_script():
    obs = [Observation(None, 1.0, "A", 1.0, []), Observation(None, 2.0, "B", 1.0, [])]
    p = ScriptedPerception(obs)
    assert p.observe().active_window == "A"
    assert p.observe().active_window == "B"
    assert p.observe().active_window == "B"  # repeats last
    assert p.observe().active_window == "B"


def test_build_simulation_wires_loop(tmp_path):
    from mio_cua.agent.safety import Safety
    from mio_cua.agent.loop import AgentLoop
    from mio_cua.events import EventBus
    from mio_cua.tools.registry import ToolRegistry
    from mio_cua.tools.builtin import register_builtin_tools

    class FakeProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools=None):
            from mio_cua.providers.base import LLMResponse
            from mio_cua.models.action import ToolCall
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(message="ok", tool_calls=[
                    ToolCall("t1", "click", {"x": 1, "y": 2}),
                    ToolCall("t2", "success", {"result": "done"}),
                ])
            return LLMResponse(message="ok", tool_calls=[
                ToolCall("t2", "success", {"result": "done"}),
            ])

    registry = ToolRegistry()
    register_builtin_tools(registry)
    safety = Safety(max_steps=5, timeout_s=30)
    obs = [Observation(None, 1.0, "Calc", 1.0, [Element(0, "uia", text="OK", role="Button", bbox=(1, 2, 3, 4))])]
    loop, controller = build_simulation(
        FakeProvider(), "sys", obs, registry, safety, EventBus(), config=None,
    )
    result = loop.run(__import__("mio_cua.models.task", fromlist=["Task"]).Task(instruction="done"))
    assert result.status == "SUCCESS"
    assert [c.type for c in controller.calls] == ["click"]

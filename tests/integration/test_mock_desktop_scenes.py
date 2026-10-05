"""MockDesktop 带 scene 的 E2E：让 notepad / calculator / explorer 三个仿真场景的
observation 也携带 SceneGraph（节点 + affordance，复用真实 AffordanceBuilder 生成），
用更接近真实感知的数据驱动真实 AgentLoop，验证「去模型化」编排在带 scene 的仿真
桌面上端到端可跑通，且 scene 确实流进了 loop 的感知 / 校验逻辑。

与 test_loop_verify_recover_e2e.py 的区别：
- 那里用 ScriptedPerception 返回手工拼的 SceneGraph（纯 mock）；
- 这里用 MockDesktop 作为 perception + controller（同一个有状态桌面），observation
  由 _scene_from 实时生成、动作也实时改写桌面状态 —— 是「状态化、带 scene」的离线
  全链路，比纯 mock 更贴近真实桌面 CUA。
"""
from mio_cua.agent.loop import AgentLoop
from mio_cua.automation.input_controller import InputController
from mio_cua.config import AgentConfig
from mio_cua.events import EventBus
from mio_cua.memory.history import History
from mio_cua.models.action import Action, Plan
from mio_cua.models.task import Task
from mio_cua.scene.graph import SceneGraph, SceneNode
from mio_cua.simulation import MockDesktop
from mio_cua.tools import click as click_tool, key as key_tool
from mio_cua.tools import success as success_tool
from mio_cua.tools import type as type_tool
from mio_cua.tools.registry import ToolRegistry


# ── 测试构件 ──────────────────────────────────────────────────────────────

class ScriptedPlanner:
    """按调用顺序返回预设 Plan；不依赖任何模型。"""

    def __init__(self, plans):
        self.plans = plans
        self.calls = 0

    def plan(self, task, obs, diff, tools, history=None, hints=None):
        if self.calls < len(self.plans):
            p = self.plans[self.calls]
            self.calls += 1
            return p
        return Plan(actions=[])  # 兜底：无动作 -> loop 判 FAIL


class _Safety:
    """真实 Safety，但关掉紧急热键监听（避免 pynput 在无桌面环境报错）。"""

    def __init__(self):
        from mio_cua.agent.safety import Safety
        self._s = Safety(max_steps=50, timeout_s=300,
                         emergency_key="f9", hotkey_enabled=False)

    def start(self):
        self._s.start()

    def stop(self):
        self._s.stop()

    def should_stop(self):
        return self._s.should_stop()

    def record_step(self):
        self._s.record_step()

    def status(self):
        return self._s.status()


def _desktop_registry():
    """最小工具集：click / type / key / success，全部委托到 ctx.controller
    （即 MockDesktop backend）。不注册 launch / focus_window / fs 等会触碰真实
    系统的工具，避免离线测试产生副作用。"""
    reg = ToolRegistry()
    reg.register("click", click_tool.click,
                 {"type": "function", "function": {"name": "click", "parameters": {}}})
    reg.register("type", type_tool.type,
                 {"type": "function", "function": {"name": "type", "parameters": {}}})
    reg.register("key", key_tool.key,
                 {"type": "function", "function": {"name": "key", "parameters": {}}})
    reg.register("success", success_tool.success,
                 {"type": "function", "function": {"name": "success", "parameters": {}}})
    return reg


def _loop_for(desktop, plans, config=None):
    return AgentLoop(
        perception=desktop,                       # 感知：带 scene 的仿真桌面
        planner=ScriptedPlanner(plans),
        registry=_desktop_registry(),
        safety=_Safety(),
        events=EventBus(),
        config=config or AgentConfig(batch_limit=8, batch_verify=False),
        history=History(),
        controller=InputController(backend=desktop),  # 动作：同一个仿真桌面
    )


# ── 1. scene 确实存在且形状正确 ────────────────────────────────────────────

def test_mock_desktop_scenarios_expose_scene():
    # 每个场景的 observation 必须带非空的 SceneGraph，节点数与 elements 对齐
    d = MockDesktop("notepad")
    obs = d.observe()
    assert isinstance(obs.scene, SceneGraph), "notepad 未带 scene"
    assert len(obs.scene.nodes) == len(obs.elements), "节点数与 elements 不一致"

    # 非对话框态：Document 映射为 input -> 应有 type affordance
    doc_node = next(n for n in obs.scene.nodes if n.type == "input")
    assert obs.scene.affordance_for(doc_node.id, "type") is not None

    # 对话框态：Save / Cancel 按钮 -> 应有 click affordance
    d = MockDesktop("notepad")
    d.execute(Action("k", "key", {"keys": "ctrl+s"}))  # 打开另存为
    obs = d.observe()
    assert isinstance(obs.scene, SceneGraph)
    save = next(n for n in obs.scene.nodes if n.text == "Save")
    assert obs.scene.affordance_for(save.id, "click") is not None, "Save 按钮无 click affordance"


def test_calculator_scene_has_display_affordances():
    d = MockDesktop("calculator")
    obs = d.observe()
    assert isinstance(obs.scene, SceneGraph)
    # AffordanceBuilder 应把大号数字读出区识别为 display
    assert obs.scene.display_ids, "计算器读数区未被识别为 display"
    # 数字按钮应带 click affordance（digit 给 expected.display=True）
    digit = next(n for n in obs.scene.nodes
                 if n.type == "button" and n.text.isdigit())
    aff = obs.scene.affordance_for(digit.id, "click")
    assert aff is not None
    assert aff.expected.get("display") is True, "数字按钮应声明会改变 display"


def test_explorer_scene_has_new_folder_button():
    d = MockDesktop("explorer")
    obs = d.observe()
    assert isinstance(obs.scene, SceneGraph)
    btn = next(n for n in obs.scene.nodes if n.text == "新建文件夹")
    assert btn.type == "button"
    assert obs.scene.affordance_for(btn.id, "click") is not None


# ── 2. 带 scene 的仿真桌面端到端跑通真实 loop ─────────────────────────────

def test_mock_desktop_notepad_save_through_loop():
    d = MockDesktop("notepad")
    plans = [
        Plan(actions=[
            Action("a1", "type", {"text": "hello world"}),
            Action("a2", "key", {"keys": "ctrl+s"}),     # 打开另存为
            Action("a3", "type", {"text": "demo.txt"}),  # 填文件名
            Action("a4", "key", {"keys": "enter"}),       # 确认保存
        ]),
        Plan(actions=[Action("a5", "success", {"result": "saved"})]),
    ]
    loop = _loop_for(d, plans)
    result = loop.run(Task(instruction="写点东西并保存为 demo.txt"))

    assert result.status == "SUCCESS", result.summary
    assert d.text == "hello world", "正文未写入"
    assert d.filename == "demo.txt", "文件名未写入"
    assert d.saved is True, "对话框保存未生效"
    assert d.completed is True
    # loop 实际迭代了多帧（scene 感知被持续喂入）
    assert result.steps >= 2


def test_mock_desktop_calculator_through_loop():
    d = MockDesktop("calculator")
    plans = [
        Plan(actions=[Action("c1", "click", {"x": 425, "y": 455})]),  # "1"
        Plan(actions=[Action("c2", "click", {"x": 605, "y": 495})]),  # "+"
        Plan(actions=[Action("c3", "click", {"x": 485, "y": 455})]),  # "2"
        Plan(actions=[Action("c4", "click", {"x": 545, "y": 495})]),  # "="
        Plan(actions=[Action("c5", "success", {"result": "3"})]),
    ]
    loop = _loop_for(d, plans)
    result = loop.run(Task(instruction="计算 1 + 2"))

    assert result.status == "SUCCESS", result.summary
    assert d.result == "3", f"计算器结果应为 3，实际 {d.result!r}"


def test_mock_desktop_explorer_through_loop():
    d = MockDesktop("explorer")
    plans = [
        Plan(actions=[Action("e1", "click", {"x": 460, "y": 215})]),  # 新建文件夹
        Plan(actions=[
            Action("e2", "type", {"text": "smoke_folder"}),   # 命名
            Action("e3", "key", {"keys": "enter"}),           # 确认重命名
        ]),
        Plan(actions=[Action("e4", "success", {"result": "done"})]),
    ]
    loop = _loop_for(d, plans)
    result = loop.run(Task(instruction="新建文件夹并命名为 smoke_folder"))

    assert result.status == "SUCCESS", result.summary
    assert d.folder_exists is True
    assert d.folder_name == "smoke_folder", "文件夹未正确命名"
    assert d.completed is True

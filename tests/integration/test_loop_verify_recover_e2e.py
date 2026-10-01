"""无桌面 E2E：用脚本化 perception / planner / registry 跑通真实 AgentLoop，
覆盖「去模型化」新增的四处 loop 级编排路径（不需要任何真实桌面，也不依赖
Grounder 的实时 UIA 匹配 —— Grounder 在这条路径里不挂载，验证/恢复编排与具体
感知解耦，所以纯仿真即可证明 loop 接线正确）：

1. obstruction 检测 -> 确定性 Esc 兜底（不盲重试）
2. Grounding 歧义 -> retryable=False，批次中止、不盲重试
3. window_title 期望 -> light 帧延迟、下一帧 full observation 补齐校验
4. state_toggle 期望 -> 翻转校验（pass / fail 两态）

复用 test_loop_mock.py 的 mock 范式（FakePerception / FakePlanner / FakeRegistry /
FakeSafety 风格），改为脚本化场景。
"""
from mio_cua.agent.loop import AgentLoop
from mio_cua.automation.grounding import GroundingError
from mio_cua.config import AgentConfig
from mio_cua.events import EventBus, ActionFinished
from mio_cua.models.action import Action, Plan
from mio_cua.models.action_result import ActionResult
from mio_cua.models.observation import Observation
from mio_cua.models.task import Task
from mio_cua.scene.graph import Affordance, SceneGraph, SceneNode


# ── mock 构件 ──────────────────────────────────────────────────────────────

class ScriptedPlanner:
    """按调用顺序返回预设 Plan；顺便记录每次 replan 收到的 hints。"""

    def __init__(self, plans):
        self.plans = plans
        self.calls = 0
        self.hints_log = []

    def plan(self, task, obs, diff, tools, history=None, hints=None):
        self.hints_log.append(list(hints or []))
        if self.calls < len(self.plans):
            p = self.plans[self.calls]
            self.calls += 1
            return p
        return Plan(actions=[])  # 兜底：无动作 -> loop 判 FAIL


class ScriptedPerception:
    """依次返回脚本化 Observation（可带 scene），末帧循环复用。"""

    def __init__(self, scenes):
        self.scenes = scenes
        self.i = 0

    def observe(self):
        obs = self.scenes[min(self.i, len(self.scenes) - 1)]
        self.i += 1
        return obs

    def observe_light(self):
        # 与全量观察同源，便于批次内轻量校验
        return self.observe()


class RecordingRegistry:
    """记录所有 (name, params)；可在 raise_for 里让指定工具抛异常。"""

    def __init__(self, raise_for=None):
        self.calls = []
        self.raise_for = raise_for or {}

    def call(self, name, params, ctx):
        self.calls.append((name, dict(params)))
        if name in self.raise_for:
            raise self.raise_for[name]
        return ActionResult(ctx.current_action_id or "a-1", True, "ok")

    def schemas(self):
        return []


class RealSafety:
    """用真实 Safety，但关掉紧急热键监听（避免 pynput 在无桌面环境报错）。"""

    def __init__(self, max_steps=50, timeout_s=300):
        from mio_cua.agent.safety import Safety
        self._s = Safety(max_steps=max_steps, timeout_s=timeout_s,
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


# ── 场景构造 ──────────────────────────────────────────────────────────────

def _obs(active_window, scene=None, elements=None):
    return Observation(screenshot_path=None, timestamp=1.0,
                       active_window=active_window, dpi_scale=1.0,
                       elements=elements or [], scene=scene)


def _clean_scene(active_window="App"):
    """一个普通可用场景（无 obstruction、无 toggle）。"""
    node = SceneNode(id=0, type="button", role="button",
                     bbox=(100, 100, 80, 30), text="确定",
                     state={"enabled": True, "visible": True})
    return SceneGraph(nodes=[node], affordances=[], active_window=active_window)


def _context_menu_scene(active_window="App"):
    """带右键菜单节点的场景 -> _detect_obstruction 应判为 context_menu。"""
    menu = SceneNode(id=0, type="menu", role="contextmenu",
                     bbox=(200, 200, 160, 120), text="右键菜单",
                     state={"enabled": True, "visible": True})
    item = SceneNode(id=1, type="menu", role="menuitem",
                     bbox=(210, 210, 140, 24), text="复制",
                     state={"enabled": True, "visible": True})
    return SceneGraph(nodes=[menu, item], affordances=[],
                      active_window=active_window)


def _toggle_scene(checked, active_window="Settings"):
    """带 checkbox 节点 + 期望 state_toggle 的点击 affordance。"""
    node = SceneNode(id=0, type="checkbox", role="checkbox",
                     bbox=(100, 100, 40, 24), text="同意条款",
                     state={"checked": checked, "enabled": True, "visible": True})
    aff = Affordance(node_id=0, action="click", expected={"state_toggle": True})
    return SceneGraph(nodes=[node], affordances=[aff],
                      active_window=active_window, display_ids=[])


def _make_loop(perception, planner, registry, config=None):
    return AgentLoop(
        perception=perception,
        planner=planner,
        registry=registry,
        events=EventBus(),
        safety=RealSafety(),
        config=config or AgentConfig(),
    )


# ── 1. obstruction -> Esc 确定性兜底 ────────────────────────────────────────

def test_loop_obstruction_context_menu_dismisses_with_esc():
    # 帧序列：普通场景(点击) -> 右键菜单(obstruction) -> 普通场景(收尾)
    scenes = [_obs("App", _clean_scene()),
              _obs("App", _context_menu_scene()),
              _obs("App", _clean_scene())]
    perception = ScriptedPerception(scenes)
    planner = ScriptedPlanner([
        Plan(actions=[Action("a-1", "click", {"x": 1})]),   # obs1 执行
        Plan(actions=[Action("a-2", "success", {"result": "done"})]),  # obs3 收尾
    ])
    registry = RecordingRegistry()
    loop = _make_loop(perception, planner, registry,
                      config=AgentConfig(batch_verify=False))
    result = loop.run(Task(instruction="点确定，遇菜单关掉"))

    assert result.status == "SUCCESS", result.summary
    # Esc 兜底必须被发出
    assert any(name == "key" and params.get("keys") == "esc"
               for name, params in registry.calls), registry.calls
    # 且 recovery 被记进轨迹
    assert any(e.get("recovery") == "context_menu:dismissed"
               for e in loop._trajectory), loop._trajectory


# ── 2. Grounding 歧义 -> retryable=False，不盲重试 ─────────────────────────

def test_loop_grounding_ambiguity_not_blindly_retried():
    # click 工具抛 GroundingError(ambiguous=True)：loop 必须判 retryable=False，
    # 批次中止、不调用 recover 重试，并如实把失败回传给 planner。
    ambiguous = GroundingError("target matches 2 ambiguous live elements",
                               ambiguous=True)
    registry = RecordingRegistry(raise_for={"click": ambiguous})
    finished = []
    loop = _make_loop(
        perception=ScriptedPerception([_obs("App", _clean_scene())]),
        planner=ScriptedPlanner([
            Plan(actions=[Action("a-1", "click", {"element_id": 0})]),
            Plan(actions=[Action("a-2", "success", {"result": "done"})]),
        ]),
        registry=registry,
    )
    loop.events.subscribe(ActionFinished, lambda e: finished.append(e.result))

    result = loop.run(Task(instruction="点那个按钮"))

    assert result.status == "SUCCESS", result.summary
    # 关键：click 只发了一次，没有因为失败而盲重试
    click_calls = [p for n, p in registry.calls if n == "click"]
    assert len(click_calls) == 1, registry.calls
    # 失败结果必须标记为不可重试
    failed = [r for r in finished if not r.success]
    assert failed, "应有一笔失败的 click 结果"
    assert failed[0].retryable is False, "歧义失败必须是 retryable=False"
    assert failed[0].message == str(ambiguous)


# ── 3. window_title 期望：延迟到下一帧 full observation 补齐（pass） ────────

def test_loop_window_title_pending_verify_passes():
    # focus_window("notepad") -> 下一帧 active_window 含 "notepad" -> 校验通过
    planner = ScriptedPlanner([
        Plan(actions=[Action("a-1", "focus_window", {"title": "notepad"})]),
        Plan(actions=[Action("a-2", "success", {"result": "done"})]),
    ])
    # 初始帧标题不含 notepad（否则 loop 的 action guard 会判「已在前台」而跳
    # 过 focus_window），第二帧带 notepad 标题 -> pending 校验命中
    perception = ScriptedPerception([
        _obs("Desktop"),
        _obs("notepad - 记事本"),
    ])
    registry = RecordingRegistry()
    loop = _make_loop(perception, planner, registry)
    result = loop.run(Task(instruction="切到记事本"))

    assert result.status == "SUCCESS", result.summary
    assert any(n == "focus_window" for n, _ in registry.calls)
    # 校验通过：replan 时不应出现 VERIFICATION 失败提示
    all_hints = [h for plan_hints in planner.hints_log for h in plan_hints]
    assert not any("VERIFICATION" in h for h in all_hints), all_hints


# ── 4. window_title 期望：下一帧标题不符 -> 校验失败提示（fail） ────────────

def test_loop_window_title_pending_verify_fails_hint():
    planner = ScriptedPlanner([
        Plan(actions=[Action("a-1", "focus_window", {"title": "notepad"})]),
        Plan(actions=[Action("a-2", "success", {"result": "done"})]),
    ])
    # 第二帧标题是计算器（不含 notepad）-> pending 校验失败
    perception = ScriptedPerception([
        _obs("Desktop"),
        _obs("Calculator"),
    ])
    registry = RecordingRegistry()
    loop = _make_loop(perception, planner, registry)
    result = loop.run(Task(instruction="切到记事本"))

    # 任务收尾靠 success，但失败校验必须作为 hint 回传
    assert result.status == "SUCCESS", result.summary
    all_hints = [h for plan_hints in planner.hints_log for h in plan_hints]
    assert any("VERIFICATION" in h for h in all_hints), all_hints


# ── 5. state_toggle 期望：翻转校验通过（pass） ────────────────────────────

def test_loop_state_toggle_pending_verify_passes():
    # 点击前 checked=False，点击后（下一帧）checked=True -> 翻转校验通过
    planner = ScriptedPlanner([
        Plan(actions=[Action("a-1", "click", {"element_id": 0})]),
        Plan(actions=[Action("a-2", "success", {"result": "done"})]),
    ])
    perception = ScriptedPerception([
        _obs("Settings", _toggle_scene(checked=False)),
        _obs("Settings", _toggle_scene(checked=True)),
    ])
    registry = RecordingRegistry()
    loop = _make_loop(perception, planner, registry)
    result = loop.run(Task(instruction="勾选同意条款"))

    assert result.status == "SUCCESS", result.summary
    all_hints = [h for plan_hints in planner.hints_log for h in plan_hints]
    assert not any("VERIFICATION" in h for h in all_hints), all_hints


# ── 6. state_toggle 期望：未翻转 -> 校验失败提示（fail） ───────────────────

def test_loop_state_toggle_pending_verify_fails_hint():
    planner = ScriptedPlanner([
        Plan(actions=[Action("a-1", "click", {"element_id": 0})]),
        Plan(actions=[Action("a-2", "success", {"result": "done"})]),
    ])
    # 两帧都是 checked=False：点击没有产生翻转 -> 校验失败
    perception = ScriptedPerception([
        _obs("Settings", _toggle_scene(checked=False)),
        _obs("Settings", _toggle_scene(checked=False)),
    ])
    registry = RecordingRegistry()
    loop = _make_loop(perception, planner, registry)
    result = loop.run(Task(instruction="勾选同意条款"))

    assert result.status == "SUCCESS", result.summary
    all_hints = [h for plan_hints in planner.hints_log for h in plan_hints]
    assert any("VERIFICATION" in h for h in all_hints), all_hints

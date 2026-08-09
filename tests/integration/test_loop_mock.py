from mio_cua.agent.loop import AgentLoop
from mio_cua.agent.recover import Recover
from mio_cua.memory.artifact import ArtifactStore
from mio_cua.memory.state import TaskState, state_path
from mio_cua.models.action import Action, Plan
from mio_cua.models.action_result import ActionResult
from mio_cua.models.task import Task, TaskResult
from mio_cua.models.observation import Observation
from mio_cua.models.element import Element
from mio_cua.events import EventBus, TaskFinished, ActionFinished


class FakePerception:
    def __init__(self, elements=None):
        self.elements = elements or [Element(0, "ocr", text="Calc")]
        self.count = 0

    def observe(self):
        self.count += 1
        return Observation(screenshot_path=None, timestamp=1.0, active_window="Calc", dpi_scale=1.0, elements=self.elements)


class FakePlanner:
    def __init__(self, plans):
        self.plans = plans
        self.calls = 0
        self.last_task = None

    def plan(self, task, obs, diff, tools, history=None, hints=None):
        self.last_task = task
        if self.calls < len(self.plans):
            p = self.plans[self.calls]
            self.calls += 1
            return p
        return Plan(actions=[])


class FakeRegistry:
    def __init__(self):
        self.results = []
        self.names = []

    def call(self, name, params, ctx):
        self.names.append(name)
        return ActionResult(action_id="a-1", success=True)

    def schemas(self):
        return []


class FakeSafety:
    def __init__(self, stop_flag=False):
        self.stop_flag = stop_flag

    def start(self):
        pass

    def stop(self):
        pass

    def should_stop(self):
        return self.stop_flag

    def record_step(self):
        pass

    def status(self):
        return "ABORTED" if self.stop_flag else "RUNNING"


def _loop(plans, safety=None):
    return AgentLoop(
        perception=FakePerception(),
        planner=FakePlanner(plans),
        registry=FakeRegistry(),
        events=EventBus(),
        safety=safety or FakeSafety(),
    )


def test_loop_completes_via_success_tool():
    loop = _loop([Plan(actions=[Action("a-1", "click", {"x": 1})]), Plan(actions=[Action("a-2", "success", {"result": "done"})])])
    finished = []
    loop.events.subscribe(TaskFinished, lambda e: finished.append(e))
    result = loop.run(Task(instruction="open calc"))
    assert isinstance(result, TaskResult)
    assert result.status == "SUCCESS"
    assert result.summary == "done"
    assert finished


def test_loop_verification_hint_on_missed_display_click():
    # A click on a calculator digit carries expected {'display': True}. If the
    # display does not change after the click, the loop must tell the agent.
    from mio_cua.scene import build_scene
    from mio_cua.models.action import Action, Plan

    def mk_scene(disp_text):
        els = [
            Element(0, "uia", text="一", role="button", bbox=(100, 300, 127, 48)),
            Element(1, "uia", text=disp_text, role="text", bbox=(100, 10, 400, 80)),
        ]
        for i, e in enumerate(els):
            e.id = i
        sc = build_scene(els, active_window="Calculator")
        sc.display_ids = [1]
        return sc

    states = [mk_scene("0"), mk_scene("0")]  # display never changes -> missed
    hints_seen = []

    class ScenePerception(FakePerception):
        def observe(self):
            sc = states[min(self.count, len(states) - 1)]
            self.count += 1
            return Observation(screenshot_path=None, timestamp=1.0, active_window="Calc",
                               dpi_scale=1.0, elements=self.elements, scene=sc)

    class RecordingPlanner(FakePlanner):
        def plan(self, task, obs, diff, tools, history=None, hints=None):
            hints_seen.extend(hints or [])
            if self.calls == 0:
                self.calls += 1
                return Plan(actions=[Action("a-1", "click", {"element_id": 0})])
            return Plan(actions=[Action("a-2", "success", {"result": "done"})])

    loop = AgentLoop(
        perception=ScenePerception(),
        planner=RecordingPlanner([]),
        registry=FakeRegistry(),
        events=EventBus(),
        safety=FakeSafety(),
    )
    result = loop.run(Task(instruction="click 1 then finish"))
    assert result.status == "SUCCESS"
    assert any("VERIFICATION" in h for h in hints_seen), hints_seen


def test_loop_only_one_action_per_observation():
    # Actions in a plan were decided against the SAME scene; executing them all
    # without re-perceiving means later actions hit a stale screen. The loop
    # must run one action, then re-observe + replan.
    from mio_cua.agent.planner import Planner
    from mio_cua.models.action import Plan, Action, ToolCall

    calls = []

    class CountingPlanner(Planner):
        def __init__(self):
            self._counter = 0

        def plan(self, task, obs, diff, tools, history=None, hints=None):
            calls.append(obs)
            if len(calls) == 1:
                return Plan(actions=[Action("a-1", "click", {"x": 1}),
                                     Action("a-2", "success", {"result": "done"})])
            return Plan(actions=[Action("a-2", "success", {"result": "done"})])

    loop = _loop([])
    loop.planner = CountingPlanner()
    result = loop.run(Task(instruction="open calc"))
    assert result.status == "SUCCESS"
    # click ran on the first observation, success on a SECOND observation
    assert len(calls) == 2


def test_loop_fail_path():
    loop = _loop([Plan(actions=[Action("a-1", "fail", {"reason": "blocked"})])])
    result = loop.run(Task(instruction="do thing"))
    assert result.status == "FAIL"
    assert result.summary == "blocked"


def test_completion_hint_fires_after_confirming_actions():
    from collections import deque
    loop = _loop([])
    loop._recent_sigs = deque(["type([('text', 'name')])", "key([('keys', 'enter')])", "click([('x', 1)])"], maxlen=8)
    hint = loop._completion_hint(3)
    assert hint is not None
    assert "success" in hint


def test_completion_hint_needs_stable_screen():
    from collections import deque
    loop = _loop([])
    loop._recent_sigs = deque(["type([('text', 'name')])", "key([('keys', 'enter')])"], maxlen=8)
    assert loop._completion_hint(0) is None  # screen still changing


def test_completion_hint_ignores_openers():
    from collections import deque
    loop = _loop([])
    loop._recent_sigs = deque(["launch(notepad)", "click(x=1)", "screenshot()"], maxlen=8)
    assert loop._completion_hint(3) is None  # no confirming action


def test_completion_hint_ignores_stale_confirm():
    from collections import deque
    loop = _loop([])
    # Enter happened long ago, then lots of unrelated work -- not completion
    loop._recent_sigs = deque(
        ["key([('keys', 'enter')])", "click([('x', 1)])", "click([('x', 2)])",
         "click([('x', 3)])", "screenshot()"],
        maxlen=8)
    assert loop._completion_hint(3) is None


def test_confirm_hint_fires_after_elementless_type_without_enter():
    from collections import deque
    loop = _loop([])
    # explorer: typed the folder name, never pressed Enter
    loop._recent_sigs = deque(["type({'text': 'smoke_demo_folder'})"], maxlen=8)
    hint = loop._confirm_hint()
    assert hint is not None
    assert "enter" in hint


def test_confirm_hint_silent_after_enter():
    from collections import deque
    loop = _loop([])
    loop._recent_sigs = deque(["type({'text': 'x'})", "key({'keys': 'enter'})"], maxlen=8)
    assert loop._confirm_hint() is None


def test_confirm_hint_ignores_elementid_type():
    from collections import deque
    loop = _loop([])
    # notepad body typing uses element_id; no Enter confirmation needed
    loop._recent_sigs = deque(["type({'element_id': 37, 'text': 'hello world'})"], maxlen=8)
    assert loop._confirm_hint() is None


def test_rename_hint_fires_after_new_folder_without_type():
    from collections import deque
    loop = _loop([])
    loop._recent_sigs = deque(["key({'keys': 'ctrl+shift+n'})", "screenshot()"], maxlen=8)
    hint = loop._rename_hint()
    assert hint is not None
    assert "type" in hint


def test_rename_hint_silent_after_type():
    from collections import deque
    loop = _loop([])
    loop._recent_sigs = deque(["key({'keys': 'ctrl+shift+n'})", "type({'text': 'x'})"], maxlen=8)
    assert loop._rename_hint() is None


def test_rename_hint_silent_without_creation():
    from collections import deque
    loop = _loop([])
    loop._recent_sigs = deque(["launch(notepad)", "screenshot()"], maxlen=8)
    assert loop._rename_hint() is None


def test_unconfirmed_edit_blocks_success():
    from collections import deque
    loop = _loop([])
    # typed a name but no Enter -> success must be blocked
    loop._recent_sigs = deque(["type({'text': 'smoke_demo_folder'})"], maxlen=8)
    blocker = loop._unconfirmed_edit()
    assert blocker is not None
    assert "enter" in blocker


def test_unconfirmed_edit_allows_after_enter():
    from collections import deque
    loop = _loop([])
    loop._recent_sigs = deque(["type({'text': 'x'})", "key({'keys': 'enter'})"], maxlen=8)
    assert loop._unconfirmed_edit() is None


def test_unconfirmed_edit_allows_without_type():
    from collections import deque
    loop = _loop([])
    loop._recent_sigs = deque(["launch(notepad)"], maxlen=8)
    assert loop._unconfirmed_edit() is None


def test_completion_hint_needs_confirm_not_just_type():
    from collections import deque
    loop = _loop([])
    # typing without Enter leaves the rename/save unconfirmed; no success hint
    loop._recent_sigs = deque(["type(text=smoke_demo_folder)", "screenshot()"], maxlen=8)
    assert loop._completion_hint(3) is None


def test_loop_safety_abort():
    loop = _loop([Plan(actions=[Action("a-1", "click", {"x": 1})])], safety=FakeSafety(stop_flag=True))
    result = loop.run(Task(instruction="open calc"))
    assert result.status == "ABORTED"


def test_loop_empty_plan_fails():
    loop = _loop([Plan(actions=[])])
    result = loop.run(Task(instruction="do thing"))
    assert result.status == "FAIL"


def test_loop_handles_perception_error():
    class FailingPerception:
        def observe(self):
            raise RuntimeError("screen grab failed")

    loop = AgentLoop(
        perception=FailingPerception(),
        planner=FakePlanner([Plan(actions=[Action("a-1", "click", {"x": 1})])]),
        registry=FakeRegistry(),
        events=EventBus(),
        safety=FakeSafety(),
    )
    result = loop.run(Task(instruction="open calc"))
    assert result.status == "FAIL"
    assert "screen grab failed" in result.summary


def test_loop_writes_artifacts_and_state(tmp_path):
    loop = AgentLoop(
        perception=FakePerception(),
        planner=FakePlanner([Plan(actions=[Action("a-1", "click", {"x": 1})]),
                             Plan(actions=[Action("a-2", "success", {"result": "done"})])]),
        registry=FakeRegistry(),
        events=EventBus(),
        safety=FakeSafety(),
        artifact_store=ArtifactStore(str(tmp_path / "artifacts")),
        state_dir=str(tmp_path / "state"),
    )
    result = loop.run(Task(instruction="open calc"))
    assert result.status == "SUCCESS"
    assert result.artifacts, "artifacts should be recorded per step"
    assert all(__import__("os").path.exists(p) for p in result.artifacts)
    st = TaskState(state_path(str(tmp_path / "state"), result.task_id))
    assert st.load().get("step", 0) >= 0
    assert st.load().get("instruction") == "open calc"


def test_loop_recovers_retryable_failure():
    class FlakyRegistry:
        def call(self, name, params, ctx):
            aid = ctx.current_action_id or "a-1"
            if name == "click":
                return ActionResult(aid, False, message="boom", retryable=True)
            return ActionResult(aid, True)

        def schemas(self):
            return []

    class RecoverDispatch:
        def __call__(self, name, params, ctx=None):
            return ActionResult("a-1", True, message="recovered ok")

    recovered = []
    loop = AgentLoop(
        perception=FakePerception(),
        planner=FakePlanner([Plan(actions=[Action("a-1", "click", {"x": 1})]),
                               Plan(actions=[Action("a-2", "success", {"result": "done"})])]),
        registry=FlakyRegistry(),
        events=EventBus(),
        safety=FakeSafety(),
        recover=Recover(dispatch=RecoverDispatch(), perception=FakePerception(), wait_s=0),
    )
    loop.events.subscribe(ActionFinished, lambda e: recovered.append(e.result))
    result = loop.run(Task(instruction="open calc"))
    assert result.status == "SUCCESS"
    click_result = [r for r in recovered if r.metadata.get("recovered")][0]
    assert click_result.success is True
    assert click_result.message == "recovered ok"

"""Headless simulation mode: run the full agent loop against a scripted desktop.

The controller records actions instead of sending real input, and perception
returns scripted observations. This lets the planning/modeling logic be tested
and tuned without ever touching the real desktop.
"""
from mio_cua.automation.backends import Backend
from mio_cua.automation.input_controller import InputController
from mio_cua.models.action_result import RawResult
from mio_cua.models.element import Element
from mio_cua.models.observation import Observation


class RecordingBackend(Backend):
    """Backend that records actions and never sends real input."""

    def __init__(self):
        self.calls = []

    def execute(self, action):
        self.calls.append(action)
        return RawResult(sent=True)


class RecordingController(InputController):
    def __init__(self):
        super().__init__(backend=RecordingBackend())

    @property
    def calls(self):
        return self.backend.calls


class ScriptedPerception:
    """Returns a fixed script of observations, one per call, then repeats the last."""

    def __init__(self, observations):
        self.observations = list(observations)
        self.i = 0

    def observe(self):
        if not self.observations:
            return Observation(None, 0.0, None, 1.0, [])
        obs = self.observations[min(self.i, len(self.observations) - 1)]
        self.i += 1
        return obs


def build_simulation(provider, system_prompt, script, registry, safety, events,
                     config=None):
    """Wire the real loop onto scripted observations and a recording controller.

    Returns (loop, controller) so the caller can inspect the recorded actions.
    """
    from mio_cua.agent.loop import AgentLoop
    from mio_cua.agent.planner import Planner
    from mio_cua.memory.history import History

    planner = Planner(provider, system_prompt)
    controller = RecordingController()
    _install_safe_tools(registry)
    loop = AgentLoop(
        perception=ScriptedPerception(script),
        planner=planner,
        registry=registry,
        safety=safety,
        events=events,
        config=config,
        history=History(),
        controller=controller,
    )
    return loop, controller


def _install_safe_tools(registry):
    """Neutralize side-effecting tools (launch/focus_window) in simulation mode."""
    from mio_cua.models.action_result import ActionResult

    def noop_launch(ctx, command):
        return ActionResult(ctx.current_action_id, True, f"[sim] launch {command}")

    def noop_focus(ctx, title):
        return ActionResult(ctx.current_action_id, True, f"[sim] focus {title}")

    for name in ("launch", "focus_window"):
        for schema in registry.schemas():
            if schema["function"]["name"] == name:
                func = noop_launch if name == "launch" else noop_focus
                registry.register(name, func, schema)
                break


class MockDesktop:
    """A stateful fake desktop that reacts to actions (no real input).

    Supports scenarios: "notepad" (type -> save), "calculator" (click digits),
    "explorer" (new folder -> rename). Used to validate the full task
    choreography offline.
    """

    def __init__(self, scenario: str = "notepad"):
        self.scenario = scenario
        self.actions = []
        self.reset()

    def reset(self):
        self.text = ""
        self.filename = ""
        self.dialog_open = False
        self.saved = False
        self.expr = ""
        self.result = None
        self.folder_exists = False
        self.folder_name = ""
        self.folder_selected = False

    # --- controller side ---

    def execute(self, action) -> RawResult:
        self.actions.append(action)
        getattr(self, f"_exec_{self.scenario}")(action)
        return RawResult(sent=True)

    def _hit_element(self, x, y):
        if x is None or y is None:
            return None
        for e in self.observe().elements:
            left, top, width, height = e.bbox
            if left <= x <= left + width and top <= y <= top + height:
                return e
        return None

    def _exec_notepad(self, action):
        typ, params = action.type, action.params
        if typ == "type":
            if self.dialog_open:
                self.filename += str(params.get("text", ""))
            else:
                self.text += str(params.get("text", ""))
        elif typ == "key":
            keys = str(params.get("keys", "")).lower()
            if "ctrl" in keys and "s" in keys:
                if not self.dialog_open:
                    self.dialog_open = True
            elif keys == "enter":
                if self.dialog_open and self.filename:
                    self.saved = True
                    self.dialog_open = False
        elif typ == "click":
            el = self._hit_element(params.get("x"), params.get("y"))
            if self.dialog_open and el and el.text.lower() in ("save", "保存"):
                self.saved = True
                self.dialog_open = False

    def _exec_calculator(self, action):
        typ, params = action.type, action.params
        if typ == "click":
            el = self._hit_element(params.get("x"), params.get("y"))
            if el:
                self._press(el.text)
        elif typ == "key" and str(params.get("keys", "")).lower() == "enter":
            self._press("=")

    def _press(self, label):
        if label == "AC":
            self.expr, self.result = "", None
        elif label == "=":
            try:
                value = eval(self.expr.replace("×", "*").replace("÷", "/"))
                self.result = str(int(value)) if float(value).is_integer() else str(value)
            except Exception:
                self.result = "ERR"
        elif label.isdigit() or label in "+-×÷.":
            if self.result is not None:
                self.expr, self.result = "", None
            self.expr += label

    def _exec_explorer(self, action):
        typ, params = action.type, action.params
        if typ == "click":
            el = self._hit_element(params.get("x"), params.get("y"))
            if not el:
                return
            if el.text == "新建文件夹" and not self.folder_exists:
                self.folder_exists = True
                self.folder_name = "新建文件夹"
                self.folder_selected = True
            elif self.folder_exists and el.text == self.folder_name:
                self.folder_selected = True
        elif typ == "type":
            if self.folder_exists and self.folder_selected:
                self.folder_name = str(params.get("text", self.folder_name))
                self.folder_selected = False

    # --- perception side ---

    def observe(self) -> Observation:
        return getattr(self, f"_observe_{self.scenario}")()

    def _observe_notepad(self) -> Observation:
        if self.dialog_open:
            elements = [
                Element(0, "uia", text=self.filename, role="Edit", bbox=(400, 300, 300, 24)),
                Element(1, "uia", text="Save", role="Button", bbox=(600, 340, 80, 24)),
                Element(2, "uia", text="Cancel", role="Button", bbox=(690, 340, 80, 24)),
            ]
            return Observation(None, 1.0, "另存为", 1.0, elements)
        title = f"{self.filename or '无标题'} - 记事本"
        elements = [
            Element(0, "uia", text=self.text, role="Document", bbox=(370, 264, 500, 200)),
            Element(1, "uia", text=self.filename or "无标题", role="TabItem", bbox=(400, 200, 120, 20)),
        ]
        return Observation(None, 1.0, title, 1.0, elements)

    def _observe_calculator(self) -> Observation:
        display_text = self.result if self.result is not None else (self.expr or "0")
        display = Element(0, "uia", text=display_text, role="Edit", bbox=(400, 300, 240, 40))
        buttons = []
        layout = [
            [("7", 400, 360), ("8", 460, 360), ("9", 520, 360), ("÷", 580, 360)],
            [("4", 400, 400), ("5", 460, 400), ("6", 520, 400), ("×", 580, 400)],
            [("1", 400, 440), ("2", 460, 440), ("3", 520, 440), ("-", 580, 440)],
            [("0", 400, 480), (".", 460, 480), ("=", 520, 480), ("+", 580, 480)],
            [("AC", 400, 520)],
        ]
        i = 1
        for row in layout:
            for label, x, y in row:
                buttons.append(Element(i, "uia", text=label, role="Button", bbox=(x, y, 50, 30)))
                i += 1
        return Observation(None, 1.0, "计算器", 1.0, [display] + buttons)

    def _observe_explorer(self) -> Observation:
        elements = [Element(0, "uia", text="新建文件夹", role="Button", bbox=(400, 200, 120, 30))]
        if self.folder_exists:
            if self.folder_selected:
                elements.append(Element(1, "uia", text=self.folder_name, role="Edit", bbox=(400, 250, 150, 24)))
            else:
                elements.append(Element(1, "uia", text=self.folder_name, role="ListItem", bbox=(400, 250, 150, 30)))
        return Observation(None, 1.0, "桌面", 1.0, elements)

    @property
    def completed(self) -> bool:
        if self.scenario == "calculator":
            return self.result is not None and self.result != "ERR"
        if self.scenario == "explorer":
            return self.folder_exists and self.folder_name not in ("", "新建文件夹")
        return self.saved and bool(self.text)


def build_mock_desktop(provider, system_prompt, registry, safety, events, config=None,
                       scenario: str = "notepad"):
    """Run the real loop against MockDesktop; returns (loop, desktop)."""
    from mio_cua.agent.loop import AgentLoop
    from mio_cua.agent.planner import Planner
    from mio_cua.memory.history import History

    _install_safe_tools(registry)
    desktop = MockDesktop(scenario=scenario)
    planner = Planner(provider, system_prompt)
    controller = InputController(backend=desktop)
    loop = AgentLoop(
        perception=desktop,
        planner=planner,
        registry=registry,
        safety=safety,
        events=events,
        config=config,
        history=History(),
        controller=controller,
    )
    return loop, desktop

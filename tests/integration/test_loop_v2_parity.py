"""V1/V2 parity: a behaviour the v2 rewrite dropped.

The audit found v2 (runtime/loop.py) had silently lost v1's obstruction
recovery: a stray context menu swallows every click, and v1 dismissed it with
Esc before planning. v2 never called _detect_obstruction at all.

This test pins the restored behaviour on AgentLoopV2 itself, so a future rewrite
cannot drop it again without a red test.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mio_cua.events import EventBus  # noqa: E402
from mio_cua.models.action import Action, Plan  # noqa: E402
from mio_cua.models.action_result import ActionResult  # noqa: E402
from mio_cua.models.observation import Observation  # noqa: E402
from mio_cua.models.task import Task  # noqa: E402
from mio_cua.runtime.loop import AgentLoopV2  # noqa: E402
from mio_cua.scene.graph import SceneGraph, SceneNode  # noqa: E402


class FakeSafety:
    def start(self):
        pass

    def stop(self):
        pass

    def should_stop(self):
        return False

    def record_step(self):
        pass

    def status(self):
        return "RUNNING"


class RecordingRegistry:
    def __init__(self):
        self.calls = []

    def call(self, name, params, ctx):
        self.calls.append((name, dict(params or {})))
        return ActionResult(action_id="a", success=True, message="ok")

    def schemas(self):
        return []


class ScriptedPlanner:
    def __init__(self, plans):
        self.plans = list(plans)

    def plan(self, task, obs, diff, tools, history=None, hints=None):
        if self.plans:
            return self.plans.pop(0)
        return Plan(actions=[])


def _scene_with_menu() -> SceneGraph:
    return SceneGraph(nodes=[SceneNode(id=1, type="group", bbox=(0, 0, 80, 80), role="menu")])


class MenuThenCleanPerception:
    """First observation carries a context menu, the rest are clean."""

    def __init__(self):
        self.count = 0

    def observe(self):
        self.count += 1
        scene = _scene_with_menu() if self.count == 1 else SceneGraph(nodes=[])
        return Observation(screenshot_path=None, timestamp=float(self.count),
                           active_window="Calc", dpi_scale=1.0, elements=[], scene=scene)


def test_v2_dismisses_a_context_menu_before_planning():
    """v1 pressed Esc on a stray context menu; v2 must do the same."""
    from mio_cua.config import AgentConfig

    registry = RecordingRegistry()
    perception = MenuThenCleanPerception()
    planner = ScriptedPlanner([Plan(actions=[Action("a1", "success", {"result": "done"})])])
    loop = AgentLoopV2(perception=perception, planner=planner, registry=registry,
                       safety=FakeSafety(), events=EventBus(), config=AgentConfig())

    result = loop.run(Task(instruction="do the thing"))

    esc_calls = [c for c in registry.calls if c[0] == "key" and c[1].get("keys") == "esc"]
    assert esc_calls, f"context menu was not dismissed; calls={registry.calls}"
    assert result.status == "SUCCESS"

class LightPerception:
    """Perception with a light path, so in-batch verification is possible."""

    def __init__(self):
        self.count = 0

    @staticmethod
    def _scene():
        # A window frame is required: v2 blocks raw x/y clicks that fall outside
        # it (the click-coordinate guard), and frame_bbox picks role="window".
        return SceneGraph(nodes=[
            SceneNode(id=0, type="group", bbox=(0, 0, 800, 600), role="window"),
        ])

    def observe(self):
        self.count += 1
        return Observation(screenshot_path=None, timestamp=float(self.count),
                           active_window="Calc", dpi_scale=1.0, elements=[],
                           scene=self._scene())

    def observe_light(self):
        self.count += 1
        return Observation(screenshot_path=None, timestamp=float(self.count),
                           active_window="Calc", dpi_scale=1.0, elements=[],
                           scene=self._scene())


def _run_batch_case(monkeypatch, batch_verify: bool):
    """One click followed by success(), with a light path available."""
    import mio_cua.runtime.loop as v2

    calls = {"verify": 0}

    def fake_verify(*args, **kwargs):
        calls["verify"] += 1
        return True, "ok"

    monkeypatch.setattr(v2, "verify_action", fake_verify)

    config = SimpleNamespace(batch_limit=3, batch_verify=batch_verify,
                             enable_verification=True, enable_recovery=True)
    registry = RecordingRegistry()
    planner = ScriptedPlanner([Plan(actions=[
        Action("a1", "click", {"x": 10, "y": 10}),
        Action("a2", "success", {"result": "done"}),
    ])])
    loop = AgentLoopV2(perception=LightPerception(), planner=planner, registry=registry,
                       safety=FakeSafety(), events=EventBus(), config=config)
    loop.run(Task(instruction="click then finish"))
    return calls["verify"]


def test_v2_runs_in_batch_verification_when_enabled(monkeypatch):
    assert _run_batch_case(monkeypatch, batch_verify=True) >= 1


def test_v2_skips_in_batch_verification_when_disabled(monkeypatch):
    """batch_verify=False means 'verify on the next full observation' -- the
    click must NOT go through the light verification path."""
    assert _run_batch_case(monkeypatch, batch_verify=False) == 0

"""V1/V2 parity: a behaviour the v2 rewrite dropped.

The audit found v2 (runtime/loop.py) had silently lost v1's obstruction
recovery: a stray context menu swallows every click, and v1 dismissed it with
Esc before planning. v2 never called _detect_obstruction at all.

This test pins the restored behaviour on AgentLoopV2 itself, so a future rewrite
cannot drop it again without a red test.
"""

import sys
from pathlib import Path

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

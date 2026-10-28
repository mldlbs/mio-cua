"""The target-visibility guard must not depend on WHICH dict carries the keyword.

v1 read ``task.metadata["keyword"]``; v2 (and the recorder/replay side) read
``task.target_context["keyword"]``. A task stored in the "other" dict silently
disabled that loop's guard -- a live comparison showed v2 happily clicking a
non-matching element when the keyword sat in metadata.

Both loops now go through ``models.task.task_keyword``; these tests pin that.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mio_cua.agent.loop import AgentLoop  # noqa: E402
from mio_cua.events import EventBus  # noqa: E402
from mio_cua.models.action import Action, Plan  # noqa: E402
from mio_cua.models.action_result import ActionResult  # noqa: E402
from mio_cua.models.observation import Observation  # noqa: E402
from mio_cua.models.task import Task, task_keyword  # noqa: E402
from mio_cua.runtime.loop import AgentLoopV2  # noqa: E402
from mio_cua.scene.graph import SceneGraph, SceneNode  # noqa: E402


class Safety:
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


class Registry:
    def __init__(self):
        self.calls = []

    def call(self, name, params, ctx):
        self.calls.append((name, dict(params or {})))
        return ActionResult(action_id="a", success=True, message="ok")

    def schemas(self):
        return []


class _Perception:
    """Window with one non-matching item; the target keyword is absent."""

    @staticmethod
    def _scene():
        return SceneGraph(nodes=[
            SceneNode(id=0, type="group", bbox=(0, 0, 800, 600), role="window"),
            SceneNode(id=5, type="text", bbox=(10, 10, 100, 20), text="另一个群"),
        ])

    def observe(self):
        return Observation(screenshot_path=None, timestamp=1.0, active_window="WeChat",
                           dpi_scale=1.0, elements=[], scene=self._scene())

    def observe_light(self):
        return self.observe()


class _Planner:
    def __init__(self):
        self.calls = 0

    def plan(self, task, obs, diff, tools, history=None, hints=None):
        self.calls += 1
        if self.calls == 1:
            return Plan(actions=[Action("a1", "click", {"element_id": 5})])
        return Plan(actions=[])


def _run(loop_cls, task):
    reg = Registry()
    cfg = SimpleNamespace(batch_limit=3, batch_verify=True,
                          enable_verification=False, enable_recovery=True)
    loop = loop_cls(perception=_Perception(), planner=_Planner(), registry=reg,
                    safety=Safety(), events=EventBus(), config=cfg)
    loop.run(task)
    return [c for c in reg.calls if c[0] == "click"]


def test_task_keyword_prefers_target_context_over_metadata():
    t = Task(instruction="x", metadata={"keyword": "md"},
             target_context={"keyword": "tc"})
    assert task_keyword(t) == "tc"
    assert t.keyword == "tc"


def test_task_keyword_falls_back_to_metadata():
    t = Task(instruction="x", metadata={"keyword": "md"}, target_context={"app": "WeChat"})
    assert task_keyword(t) == "md"
    assert t.keyword == "md"


def test_task_keyword_empty_when_absent():
    assert task_keyword(Task(instruction="x")) == ""
    # duck-typed objects (tests, examples) must work too
    assert task_keyword(SimpleNamespace(metadata={"keyword": "k"})) == "k"


def test_v2_blocks_nonmatching_click_when_keyword_only_in_metadata():
    """This used to be the bug: v2 read target_context only, so with the keyword
    in metadata the guard silently passed and the click executed."""
    task = Task(instruction="打开目标群", metadata={"keyword": "目标群"})
    assert _run(AgentLoopV2, task) == []


def test_v1_blocks_nonmatching_click_when_keyword_only_in_target_context():
    """The mirror case: v1 read metadata only."""
    task = Task(instruction="打开目标群", target_context={"keyword": "目标群"})
    assert _run(AgentLoop, task) == []

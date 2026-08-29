"""Phase 3 integration: the real AgentLoopV2 emits a recordable trace.

Proves the recording bridge end-to-end (real runtime loop + Phase 3 event bus
+ Recorder) WITHOUT a desktop or an LLM: a scripted planner + scripted
perception + recording controller drive the v2 loop, and the Recorder must
capture a complete, analyzable Trace. This is the exact gap that made Phase 3
invisible before -- the Recorder was never attached to the live loop, so no
real scenario could ever be recorded.
"""
import os
import tempfile

from mio_cua.agent.safety import Safety
from mio_cua.events import EventBus
from mio_cua.models.action import Action, Plan
from mio_cua.models.element import Element
from mio_cua.models.observation import Observation
from mio_cua.models.task import Task
from mio_cua.evaluation.recorder import Recorder, JSONLTraceStore
from mio_cua.evaluation.attribution import FailureAttributor
from mio_cua.evaluation.benchmark import benchmark
from mio_cua.evaluation.schema import EventType, FailureCategory


class _ScriptedPlanner:
    def __init__(self, plans):
        self._plans = list(plans)
        self._i = 0

    def plan(self, task, obs, diff, schemas, history=None, hints=None):
        p = self._plans[min(self._i, len(self._plans) - 1)]
        self._i += 1
        return p


class _ScriptedPerception:
    def __init__(self, observation):
        self._obs = observation

    def observe(self):
        return self._obs


def _make_obs():
    return Observation(
        None, 1.0, "测试窗口", 1.0,
        [Element(0, "uia", text="文档内容", role="Document", bbox=(370, 264, 500, 200))],
    )


def _build_loop():
    from mio_cua.runtime.loop import AgentLoopV2
    from mio_cua.tools.builtin import register_builtin_tools
    from mio_cua.tools.registry import ToolRegistry
    from mio_cua.simulation import RecordingController
    from mio_cua.memory.history import History
    from mio_cua.memory.artifact import ArtifactStore
    from mio_cua.config import AgentConfig

    registry = ToolRegistry()
    register_builtin_tools(registry)
    config = AgentConfig(max_steps=10, batch_verify=False, runtime_v2=True)
    tmp = tempfile.mkdtemp()
    planner = _ScriptedPlanner([
        Plan(actions=[Action(id="a1", type="key", params={"keys": "enter"})]),
        Plan(actions=[Action(id="s1", type="success", params={"result": "done"})]),
    ])
    controller = RecordingController()
    loop = AgentLoopV2(
        perception=_ScriptedPerception(_make_obs()),
        planner=planner,
        registry=registry,
        safety=Safety(max_steps=10, timeout_s=30, emergency_key="f9"),
        events=EventBus(),
        config=config,
        history=History(),
        controller=controller,
        artifact_store=ArtifactStore(tmp),
        state_dir=os.path.join(tmp, "state"),
        recover=None,
    )
    return loop, tmp


def test_record_bridge_produces_analyzable_trace():
    loop, _ = _build_loop()
    recorder = Recorder(auto_save=True)
    loop.add_event_sink(recorder)
    result = loop.run(Task(instruction="测试任务"))
    assert result.status == "SUCCESS", result.status

    trace = recorder.trace
    assert trace is not None
    etypes = [e.event_type for e in trace.events]
    assert "task_started" in etypes
    assert "observation" in etypes
    assert "plan_created" in etypes
    assert "action_completed" in etypes
    assert "task_completed" in etypes

    # attribution + benchmark must run on the recorded trace
    attr = FailureAttributor().classify(trace)
    assert attr.category in {c.value for c in FailureCategory}
    bm = benchmark([trace])
    assert bm.total_tasks == 1
    assert bm.success_tasks == 1


def test_record_bridge_saves_jsonl_and_reloads():
    loop, tmp = _build_loop()
    store = JSONLTraceStore(os.path.join(tmp, "traces"))
    recorder = Recorder(store=store, auto_save=True)
    loop.add_event_sink(recorder)
    loop.run(Task(instruction="另一个任务"))
    assert recorder.trace is not None
    loaded = store.load_task(recorder.trace.task_id)
    assert loaded is not None
    assert loaded.success is True


def test_record_via_agent_run_attaches_recorder(monkeypatch):
    """Public ``Agent.run(record=True)`` forces runtime_v2 + attaches a Recorder
    and exposes the recorded trace on the agent -- without any LLM/desktop."""
    import mio_cua.agent_factory as af_mod
    from mio_cua import Agent
    from mio_cua.config import AgentConfig
    from mio_cua.simulation import RecordingController

    plans = [
        Plan(actions=[Action(id="a1", type="key", params={"keys": "enter"})]),
        Plan(actions=[Action(id="s1", type="success", params={"result": "done"})]),
    ]

    class _FactoryPlanner:
        def __init__(self, *a, **k):
            self._i = 0

        def plan(self, task, obs, diff, schemas, history=None, hints=None):
            p = plans[min(self._i, len(plans) - 1)]
            self._i += 1
            return p

    # agent_factory binds Planner/InputController at module import time, so the
    # patch must target its namespace, not the source submodule.
    monkeypatch.setattr(af_mod, "Planner", _FactoryPlanner)
    monkeypatch.setattr(af_mod, "InputController", RecordingController)
    monkeypatch.setattr(Agent, "_perception",
                        lambda self: _ScriptedPerception(_make_obs()))

    config = AgentConfig(max_steps=10, batch_verify=False, runtime_v2=False)
    agent = Agent(config)
    result = agent.run(Task(instruction="via agent.run record"), record=True)
    assert result.status == "SUCCESS", result.status
    assert agent.last_recorder is not None
    assert agent.last_recorder.trace is not None
    assert agent.last_trace_dir is not None
    etypes = [e.event_type for e in agent.last_recorder.trace.events]
    assert "task_completed" in etypes

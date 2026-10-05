"""Phase 3 — Recorder event sink + JSONLTraceStore (spec §18-§22).

The Recorder is an event sink: the runtime emits TraceEvents carrying *live*
runtime objects; the Recorder converts them into frozen snapshots and collects
them into a schema.Trace. No live reference ever reaches the stored Trace.
"""

import os
import tempfile

import pytest

from mio_cua.evaluation.recorder import JSONLTraceStore, Recorder
from mio_cua.evaluation.schema import Trace, TraceEvent


# ---- lightweight runtime-object stand-ins (observe/plan/action/result) -----


class _Node:
    def __init__(self, id, type="text", bbox=(0, 0, 10, 10), text="", semantic=None):
        self.id = id
        self.type = type
        self.bbox = bbox
        self.text = text
        self.semantic = semantic
        self.role = "unknown"
        self.confidence = 1.0


class _Scene:
    def __init__(self, nodes):
        self.nodes = nodes
        self.active_window = "WeChat"


class _Obs:
    def __init__(self, nodes):
        self.scene = _Scene(nodes)
        self.active_window = "WeChat"
        self.elements = []
        self.timestamp = 123.0
        self.screenshot_path = None


class _Action:
    def __init__(self, type, params, thought=None):
        self.type = type
        self.params = params
        self.thought = thought


class _Plan:
    def __init__(self, actions, goal="", thought=None):
        self.actions = actions
        self.goal = goal
        self.thought = thought


class _Result:
    def __init__(self, success, message=""):
        self.success = success
        self.message = message


class TestRecorderBuild:
    def _recorder(self, tmp):
        return Recorder(base_dir=tmp, auto_save=False)

    def test_builds_trace_from_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._recorder(tmp)
            rec.emit(TraceEvent(event_type="task_started", step=0,
                                payload={"goal": "find x", "task_id": "T1",
                                         "target_context": {"keyword": "x", "app": "WeChat"}}))
            rec.emit(TraceEvent(event_type="observation", step=0,
                                payload={"observation": _Obs([_Node(1, text="x")])}))
            rec.emit(TraceEvent(event_type="plan_created", step=0,
                                payload={"plan": _Plan([_Action("click", {"element_id": 1})], goal="g")}))
            rec.emit(TraceEvent(event_type="action_completed", step=0,
                                payload={"action": _Action("click", {"element_id": 1}),
                                         "result": _Result(True, "ok")}))
            rec.emit(TraceEvent(event_type="task_completed", step=1,
                                payload={"status": "SUCCESS"}))

            trace = rec.trace
            assert trace is not None
            assert trace.trace_id == "T1"
            assert trace.goal == "find x"
            assert len(trace.events) == 5

            # observation snapshot converted to plain dict (not live object)
            obs = trace.events_of("observation")[0].payload["observation"]
            assert isinstance(obs, dict)
            assert obs["active_window"] == "WeChat"
            assert obs["scene"]["nodes"][0]["text"] == "x"

            # action snapshot
            act = trace.events_of("action_completed")[0].payload["action"]
            assert act["tool"] == "click"
            assert act["success"] is True

            # plan snapshot
            plan = trace.events_of("plan_created")[0].payload["plan"]
            assert plan["action_type"] == "click"

    def test_auto_attribution_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._recorder(tmp)
            rec.emit(TraceEvent(event_type="task_started", step=0,
                                payload={"goal": "g", "task_id": "TF",
                                         "target_context": {"keyword": "x", "app": "WeChat"}}))
            rec.emit(TraceEvent(event_type="observation", step=0,
                                payload={"observation": _Obs([_Node(1, text="y")])}))
            rec.emit(TraceEvent(event_type="action_completed", step=0,
                                payload={"action": _Action("click", {}),
                                         "result": _Result(False, "element not found")}))
            rec.emit(TraceEvent(event_type="task_failed", step=1,
                                payload={"status": "FAIL"}))

            trace = rec.trace
            assert trace.failure is not None
            assert trace.failure.category == "action"

    def test_ignores_events_before_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._recorder(tmp)
            rec.emit(TraceEvent(event_type="observation", step=0,
                                payload={"observation": _Obs([_Node(1)])}))
            assert rec.trace is None

    def test_preserves_metadata_target_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._recorder(tmp)
            rec.emit(TraceEvent(event_type="task_started", step=0,
                                payload={"goal": "g", "task_id": "TM",
                                         "target_context": {"keyword": "k", "app": "WeChat"}}))
            assert rec.trace.metadata["target_context"]["keyword"] == "k"


class TestJSONLStore:
    def _trace(self, trace_id="JL"):
        return Trace(trace_id=trace_id, goal="g", metadata={"target_context": {}},
                     events=[
                         TraceEvent(event_type="task_started", step=0,
                                     payload={"goal": "g", "target_context": {}}),
                         TraceEvent(event_type="observation", step=0,
                                     payload={"observation": {"active_window": "WeChat",
                                                              "scene": {"nodes": [{"id": 1, "text": "a"}]}}}),
                         TraceEvent(event_type="task_completed", step=1,
                                     payload={"status": "SUCCESS"}),
                     ])

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JSONLTraceStore(tmp)
            path = store.save(self._trace())
            assert os.path.isdir(path)
            loaded = store.load(path)
            assert loaded.trace_id == "JL"
            assert len(loaded.events) == 3
            assert loaded.events[0].event_type == "task_started"
            assert loaded.success is True

    def test_load_task_by_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JSONLTraceStore(tmp)
            store.save(self._trace("LT"))
            found = store.load_task("LT")
            assert found is not None
            assert found.trace_id == "LT"

    def test_list_traces(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JSONLTraceStore(tmp)
            store.save(self._trace("L1"))
            assert len(store.list_traces()) == 1

    def test_schema_version_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JSONLTraceStore(tmp)
            store.save(self._trace())
            loaded = store.load(store._dir_for(self._trace()))
            assert loaded.schema_version == 1

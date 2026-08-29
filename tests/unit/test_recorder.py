"""Tests for generic Observation Recorder / TraceStore / ReplayPerception.

Tests the three-layer recording infrastructure:
  ObservationRecorder — captures live Perception output
  TraceStore          — persistence: save/load trajectories
  ReplayPerception    — feeds recorded observations back
"""

import json
import os
import tempfile

import pytest

from mio_cua.evaluation.recorder import (
    ActionRecord,
    ObsFrame,
    ObservationRecorder,
    ReplayPerception,
    Trace,
    TraceEntry,
    TraceStore,
)


# ---- ObsFrame ----


class TestObsFrame:

    def test_create_minimal(self):
        frame = ObsFrame(id=1, timestamp=100.0, active_window="Chrome", scene_nodes=[])
        assert frame.id == 1
        assert frame.active_window == "Chrome"
        assert frame.scene_nodes == []

    def test_create_with_nodes(self):
        nodes = [{"id": 1, "type": "text", "bbox": [0, 0, 100, 30], "text": "hello"}]
        frame = ObsFrame(id=2, timestamp=200.0, active_window="WeChat", scene_nodes=nodes)
        assert len(frame.scene_nodes) == 1
        assert frame.scene_nodes[0]["text"] == "hello"


# ---- ActionRecord ----


class TestActionRecord:

    def test_create(self):
        rec = ActionRecord(id="a1", type="click", params={"element_id": 3})
        assert rec.type == "click"
        assert rec.params["element_id"] == 3
        assert rec.result is None


# ---- ObservationRecorder ----


class TestObservationRecorder:

    def _mock_obs(self, active_window="WeChat", nodes=None):
        """Create a mock Observation-like object."""
        class _Scene:
            def __init__(self, nodes):
                self.nodes = nodes
        class _Obs:
            def __init__(self, aw, nodes):
                self.active_window = aw
                self.scene = _Scene(nodes) if nodes else None
                self.screenshot_path = None
        return _Obs(active_window, nodes or [])

    def _node(self, id, type, bbox, text, semantic=None):
        class _N:
            def __init__(self, id, type, bbox, text, semantic):
                self.id = id
                self.type = type
                self.bbox = bbox
                self.text = text
                self.semantic = semantic
        return _N(id, type, bbox, text, semantic)

    def test_capture_one(self):
        recorder = ObservationRecorder()
        obs = self._mock_obs("Chrome", [self._node(1, "text", [10, 20, 100, 30], "hello")])
        frame = recorder.capture(obs)
        assert frame.id == 1
        assert frame.active_window == "Chrome"
        assert len(frame.scene_nodes) == 1
        assert frame.scene_nodes[0]["text"] == "hello"

    def test_capture_increments_id(self):
        recorder = ObservationRecorder()
        f1 = recorder.capture(self._mock_obs("A"))
        f2 = recorder.capture(self._mock_obs("B"))
        assert f2.id == f1.id + 1

    def test_capture_with_metadata(self):
        recorder = ObservationRecorder()
        frame = recorder.capture(self._mock_obs(), metadata={"step": 5})
        assert frame.metadata["step"] == 5

    def test_capture_action(self):
        recorder = ObservationRecorder()
        rec = recorder.capture_action("a1", "click", {"element_id": 3}, {"sent": True})
        assert rec.type == "click"
        assert rec.result["sent"] is True

    def test_frames_property(self):
        recorder = ObservationRecorder()
        recorder.capture(self._mock_obs("A"))
        recorder.capture(self._mock_obs("B"))
        assert len(recorder.frames) == 2

    def test_clear(self):
        recorder = ObservationRecorder()
        recorder.capture(self._mock_obs("A"))
        recorder.clear()
        assert len(recorder.frames) == 0


# ---- TraceStore ----


class TestTraceStore:

    def _make_trace(self) -> Trace:
        obs1 = ObsFrame(id=1, timestamp=100.0, active_window="Chrome",
                        scene_nodes=[{"id": 1, "type": "text", "bbox": [0, 0, 10, 10], "text": "hi"}])
        obs2 = ObsFrame(id=2, timestamp=200.0, active_window="Chrome",
                        scene_nodes=[{"id": 2, "type": "text", "bbox": [0, 0, 10, 10], "text": "bye"}])
        action = ActionRecord(id="a1", type="click", params={"element_id": 1}, timestamp=150.0)
        return Trace(
            trace_id="test_trace",
            created_at=100.0,
            task={"instruction": "test", "target_context": {}, "metadata": {}},
            entries=[TraceEntry(obs_before=obs1, action=action, obs_after=obs2)],
        )

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TraceStore(tmpdir)
            trace = self._make_trace()
            path = store.save(trace)
            assert os.path.exists(path)

            loaded = store.load("test_trace.json")
            assert loaded.trace_id == "test_trace"
            assert len(loaded.entries) == 1
            assert loaded.entries[0].action.type == "click"
            assert loaded.entries[0].obs_after.active_window == "Chrome"

    def test_list_traces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TraceStore(tmpdir)
            store.save(self._make_trace())
            traces = store.list_traces()
            assert len(traces) == 1
            assert "test_trace.json" in traces

    def test_observations_property(self):
        trace = self._make_trace()
        obs = trace.observations
        assert len(obs) == 2
        assert obs[0].id == 1
        assert obs[1].id == 2

    def test_actions_property(self):
        trace = self._make_trace()
        actions = trace.actions
        assert len(actions) == 1
        assert actions[0].type == "click"


# ---- ReplayPerception ----


class TestReplayPerception:

    def _frames(self):
        return [
            ObsFrame(id=1, timestamp=100.0, active_window="Chrome",
                     scene_nodes=[{"id": 1, "type": "text", "bbox": [0, 0, 10, 10], "text": "A"}]),
            ObsFrame(id=2, timestamp=200.0, active_window="WeChat",
                     scene_nodes=[{"id": 2, "type": "text", "bbox": [0, 0, 10, 10], "text": "B"}]),
        ]

    def test_observe_returns_observations(self):
        rp = ReplayPerception(self._frames())
        obs1 = rp.observe()
        assert obs1.active_window == "Chrome"
        assert obs1.scene.nodes[0].text == "A"
        obs2 = rp.observe()
        assert obs2.active_window == "WeChat"
        assert obs2.scene.nodes[0].text == "B"

    def test_observe_clamps_at_end(self):
        rp = ReplayPerception(self._frames())
        rp.observe()
        rp.observe()
        obs3 = rp.observe()
        assert obs3.active_window == "WeChat"

    def test_observe_light_same_as_observe(self):
        rp = ReplayPerception(self._frames())
        obs = rp.observe_light()
        assert obs.active_window == "Chrome"

    def test_from_trace(self):
        obs1 = ObsFrame(id=1, timestamp=100.0, active_window="A",
                        scene_nodes=[{"id": 1, "type": "text", "bbox": [0, 0, 10, 10], "text": "X"}])
        obs2 = ObsFrame(id=2, timestamp=200.0, active_window="B",
                        scene_nodes=[{"id": 2, "type": "text", "bbox": [0, 0, 10, 10], "text": "Y"}])
        action = ActionRecord(id="a1", type="click", params={"element_id": 1})
        trace = Trace(
            trace_id="t1", created_at=100.0,
            task={"instruction": "test", "target_context": {}, "metadata": {}},
            entries=[TraceEntry(obs_before=obs1, action=action, obs_after=obs2)],
        )
        rp = ReplayPerception.from_trace(trace)
        assert rp.total_frames == 2
        obs = rp.observe()
        assert obs.active_window == "A"

    def test_from_file_legacy(self):
        """Test loading legacy flat observation format."""
        data = {
            "id": "legacy",
            "created_at": 100.0,
            "task": {"instruction": "test", "target_context": {}, "metadata": {}},
            "observations": [
                {"id": 1, "timestamp": 100.0, "active_window": "X",
                 "scene_nodes": [{"id": 1, "type": "text", "bbox": [0, 0, 10, 10], "text": "hi"}],
                 "metadata": {}},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "legacy.json")
            with open(path, "w") as f:
                json.dump(data, f)
            rp = ReplayPerception.from_file(path)
            assert rp.total_frames == 1
            obs = rp.observe()
            assert obs.active_window == "X"

    def test_current_index(self):
        rp = ReplayPerception(self._frames())
        assert rp.current_index == 0
        rp.observe()
        assert rp.current_index == 1

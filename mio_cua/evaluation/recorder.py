"""Generic Observation Recording, Trace Storage, and Replay infrastructure.

Three-layer architecture:
  ObservationRecorder — captures live Perception output (app-agnostic side-channel)
  TraceStore          — persistence: save/load trajectories to disk
  ReplayPerception    — feeds recorded observations back as a Perception substitute

Design principles:
  - App-agnostic: works for WeChat, Chrome, VS Code, any desktop app
  - Side-channel: Observation flows to Agent AND Recorder, not Recorder→Agent
  - Full trajectory: Obs₀→Action₀→Obs₁→Action₁→...→Goal
  - Foundation for Agent Evaluation / Debug / Regression

Architecture:
                  Agent Runtime
                       ↓
                Perception
                  ↙       ↘
          Live Observation  Recorded Observation
                  ↓             ↓
              Real Run       Replay/Test
"""

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ObsFrame:
    """One recorded observation frame. App-agnostic."""
    id: int
    timestamp: float
    active_window: str
    scene_nodes: List[Dict[str, Any]]
    screenshot_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionRecord:
    """One recorded action taken between observations."""
    id: str
    type: str
    params: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    result: Optional[Dict[str, Any]] = None


@dataclass
class PlannerRecord:
    """Captures what the Planner received and produced."""
    prompt: str = ""
    llm_response: str = ""
    tool_calls_raw: List[Dict[str, Any]] = field(default_factory=list)
    parsed_actions: List[Dict[str, Any]] = field(default_factory=list)
    decision_state: Optional[Dict[str, Any]] = None


@dataclass
class TraceEntry:
    """One step in a trajectory: obs → planner → action → result → obs'."""
    obs_before: ObsFrame
    action: Optional[ActionRecord] = None
    obs_after: Optional[ObsFrame] = None
    planner: Optional[PlannerRecord] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    """Complete trajectory: sequence of observations and actions.

    Format: obs₀ → action₀ → obs₁ → action₁ → obs₂ → ... → goal
    """
    trace_id: str
    created_at: float
    task: Dict[str, Any]
    entries: List[TraceEntry] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def observations(self) -> List[ObsFrame]:
        """All observation frames in order."""
        result = []
        for e in self.entries:
            result.append(e.obs_before)
            if e.obs_after is not None:
                result.append(e.obs_after)
        return result

    @property
    def actions(self) -> List[ActionRecord]:
        """All actions in order."""
        return [e.action for e in self.entries if e.action is not None]


# ---------------------------------------------------------------------------
# ObservationRecorder — captures live Perception output
# ---------------------------------------------------------------------------

class ObservationRecorder:
    """Captures Perception output as ObsFrame records.

    App-agnostic: works with any Perception that produces an Observation
    with a SceneGraph. Use as a side-channel alongside the Agent:

        obs = perception.observe()          # Agent gets this
        recorder.capture(obs)               # Recorder also gets this (side-channel)
        agent.step(obs)                     # Agent proceeds normally
    """

    def __init__(self):
        self._frames: List[ObsFrame] = []
        self._counter = 0

    def capture(self, observation: Any, metadata: Optional[Dict[str, Any]] = None) -> ObsFrame:
        """Capture one Observation into an ObsFrame (side-channel)."""
        self._counter += 1
        scene_nodes = []
        scene = getattr(observation, "scene", None)
        if scene is not None:
            for n in getattr(scene, "nodes", []) or []:
                node_dict: Dict[str, Any] = {
                    "id": n.id,
                    "type": getattr(n, "type", "unknown"),
                    "bbox": list(getattr(n, "bbox", [0, 0, 0, 0])),
                    "text": getattr(n, "text", "") or "",
                }
                sem = getattr(n, "semantic", None)
                if sem:
                    node_dict["semantic"] = sem
                scene_nodes.append(node_dict)

        frame = ObsFrame(
            id=self._counter,
            timestamp=time.time(),
            active_window=getattr(observation, "active_window", "") or "",
            scene_nodes=scene_nodes,
            screenshot_path=getattr(observation, "screenshot_path", None),
            metadata=metadata or {},
        )
        self._frames.append(frame)
        return frame

    def capture_action(self, action_id: str, action_type: str,
                       params: Dict[str, Any], result: Optional[Dict[str, Any]] = None) -> ActionRecord:
        """Record an action taken between observations."""
        rec = ActionRecord(
            id=action_id,
            type=action_type,
            params=dict(params),
            timestamp=time.time(),
            result=result,
        )
        return rec

    @property
    def frames(self) -> List[ObsFrame]:
        return list(self._frames)

    def clear(self):
        self._frames.clear()
        self._counter = 0


# ---------------------------------------------------------------------------
# TraceStore — persistence layer
# ---------------------------------------------------------------------------


def _safe_asdict(obj):
    """Convert dataclass to dict safely; fall back to __dict__ or empty dict."""
    if obj is None:
        return None
    try:
        return asdict(obj)
    except TypeError:
        pass
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    if isinstance(obj, dict):
        return obj
    return {}


class TraceStore:
    """Saves and loads traces (trajectories) to/from disk.

    Storage format: one JSON file per trace, containing the full
    obs₀→action₀→obs₁→...→goal trajectory.
    """

    def __init__(self, base_dir: str = "traces"):
        self._base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def save(self, trace: Trace, filename: Optional[str] = None) -> str:
        """Save a trace to disk. Returns the file path."""
        if filename is None:
            filename = f"{trace.trace_id}.json"
        path = os.path.join(self._base_dir, filename)
        data = {
            "trace_id": trace.trace_id,
            "created_at": trace.created_at,
            "task": trace.task,
            "metadata": trace.metadata,
            "entries": [
                {
                    "obs_before": _safe_asdict(e.obs_before),
                    "action": _safe_asdict(e.action),
                    "obs_after": _safe_asdict(e.obs_after),
                    "planner": _safe_asdict(e.planner),
                    "metadata": e.metadata,
                }
                for e in trace.entries
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    def load(self, filename: str) -> Trace:
        """Load a trace from disk."""
        path = os.path.join(self._base_dir, filename)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        entries = []
        for e in data.get("entries", []):
            obs_before = ObsFrame(**e["obs_before"])
            action = ActionRecord(**e["action"]) if e.get("action") else None
            obs_after = ObsFrame(**e["obs_after"]) if e.get("obs_after") else None
            planner = PlannerRecord(**e["planner"]) if e.get("planner") else None
            entries.append(TraceEntry(obs_before=obs_before, action=action,
                                      obs_after=obs_after, planner=planner,
                                      metadata=e.get("metadata", {})))
        return Trace(
            trace_id=data["trace_id"],
            created_at=data["created_at"],
            task=data["task"],
            entries=entries,
            metadata=data.get("metadata", {}),
        )

    def list_traces(self) -> List[str]:
        """List all trace filenames in the store."""
        return [
            f for f in os.listdir(self._base_dir)
            if f.endswith(".json")
        ]


# ---------------------------------------------------------------------------
# ReplayPerception — feeds recorded observations back
# ---------------------------------------------------------------------------

class ReplayPerception:
    """Replaces live Perception with recorded observations.

    Use in benchmarks/tests to replay a captured world state without
    the real desktop. Supports both linear replay and trace-based replay.
    """

    def __init__(self, frames: List[ObsFrame]):
        self._frames = list(frames)
        self._index = 0

    @classmethod
    def from_trace(cls, trace: Trace) -> "ReplayPerception":
        """Create from a Trace, using obs_before of each entry + final obs_after."""
        frames = []
        for entry in trace.entries:
            frames.append(entry.obs_before)
            if entry.obs_after is not None:
                frames.append(entry.obs_after)
        return cls(frames)

    @classmethod
    def from_file(cls, path: str) -> "ReplayPerception":
        """Create from a recorded JSON file (TraceStore format or legacy)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Support both Trace format and legacy observations format
        if "entries" in data:
            trace = TraceStore().load(os.path.basename(path))
            return cls.from_trace(trace)
        # Legacy: flat observations list
        frames = [ObsFrame(**o) for o in data.get("observations", [])]
        return cls(frames)

    def observe(self):
        """Return the next observation (clamps at end)."""
        from mio_cua.models.observation import Observation
        from mio_cua.scene.graph import SceneGraph, SceneNode

        frame = self._frames[min(self._index, len(self._frames) - 1)]
        self._index += 1

        nodes = [
            SceneNode(
                id=n["id"],
                type=n.get("type", "unknown"),
                bbox=n.get("bbox", [0, 0, 0, 0]),
                text=n.get("text", ""),
                semantic=n.get("semantic"),
            )
            for n in frame.scene_nodes
        ]
        return Observation(
            screenshot_path=frame.screenshot_path,
            timestamp=frame.timestamp,
            active_window=frame.active_window,
            dpi_scale=1.0,
            elements=[],
            scene=SceneGraph(nodes=nodes, active_window=frame.active_window),
        )

    def observe_light(self):
        return self.observe()

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def total_frames(self) -> int:
        return len(self._frames)


# ===========================================================================
# Phase 3 — Runtime Event Sink, Recorder, JSONL Trace Store (spec §18-§22)
# ===========================================================================
#
# These build on the canonical model in ``mio_cua.evaluation.schema``. The
# Recorder is an *event sink*: the Agent Runtime emits TraceEvents through
# ``RuntimeEventSink.emit``; the Recorder turns raw runtime objects into
# frozen snapshots and collects them into a ``schema.Trace``. No live runtime
# object reference ever reaches the stored Trace (spec §7).

logger = logging.getLogger(__name__)


@runtime_checkable
class RuntimeEventSink(Protocol):
    """Any object that can receive a runtime event (spec §19)."""

    def emit(self, event: Any) -> None:
        ...


# ---------------------------------------------------------------------------
# Snapshot builders — convert live runtime objects into frozen snapshots.
# All builders are defensive: any failure yields a best-effort partial
# snapshot instead of raising, so the recording loop never crashes.
# ---------------------------------------------------------------------------

def _node_to_dict(n) -> Dict[str, Any]:
    return {
        "id": getattr(n, "id", None),
        "type": getattr(n, "type", "unknown"),
        "bbox": list(getattr(n, "bbox", [0, 0, 0, 0])),
        "text": getattr(n, "text", "") or "",
        "semantic": getattr(n, "semantic", None),
        "role": getattr(n, "role", "unknown"),
        "confidence": getattr(n, "confidence", 1.0),
    }


def _element_to_dict(e) -> Dict[str, Any]:
    return {
        "id": getattr(e, "id", None),
        "type": getattr(e, "type", "unknown"),
        "bbox": list(getattr(e, "bbox", [0, 0, 0, 0])),
        "text": getattr(e, "text", "") or "",
        "semantic": getattr(e, "semantic", None),
    }


def observation_snapshot_from(obs) -> "Any":
    from mio_cua.evaluation.schema import ObservationSnapshot

    try:
        scene = getattr(obs, "scene", None)
        nodes = getattr(scene, "nodes", []) or [] if scene else []
        scene_dict = {
            "active_window": (getattr(scene, "active_window", "") or
                              (getattr(obs, "active_window", "") or "")),
            "nodes": [_node_to_dict(n) for n in nodes],
        }
        elements = getattr(obs, "elements", []) or []
        raw_elements = [_element_to_dict(e) for e in elements]
        sw, sh = 0, 0
        for n in nodes:
            b = getattr(n, "bbox", None)
            if b and len(b) >= 4:
                sw = max(sw, b[0] + b[2])
                sh = max(sh, b[1] + b[3])
        return ObservationSnapshot(
            observation_id=uuid.uuid4().hex[:12],
            timestamp=getattr(obs, "timestamp", _now()),
            screen_size=(sw, sh),
            scene=scene_dict,
            active_window=getattr(obs, "active_window", "") or "",
            cursor=None,
            raw_elements=raw_elements,
            metadata={},
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("observation_snapshot_from failed: %s", e)
        return ObservationSnapshot(
            observation_id=uuid.uuid4().hex[:12],
            active_window=str(getattr(obs, "active_window", "") or ""),
        )


def belief_snapshot_from(belief, robs=None) -> "Any":
    from mio_cua.evaluation.schema import BeliefSnapshot

    try:
        tc = (getattr(belief, "target_context", None) or {})
        goal = tc.get("keyword", "")
        context = None
        if robs is not None:
            context = getattr(robs, "context", None)
        if context is None:
            context = getattr(belief, "context", None) or ""
        target_visible = getattr(belief, "target_visible", False)
        candidates = (getattr(robs, "candidates", []) or []) if robs is not None else []
        return BeliefSnapshot(
            goal=goal,
            current_state=str(context or ""),
            expected_state=goal or None,
            confidence=1.0 if target_visible else 0.3,
            known_entities=[{"candidate": c} for c in candidates],
            assumptions=[],
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("belief_snapshot_from failed: %s", e)
        return BeliefSnapshot()


def plan_snapshot_from(plan, robs=None) -> "Any":
    from mio_cua.evaluation.schema import PlanSnapshot

    try:
        actions = getattr(plan, "actions", []) or []
        if actions:
            a0 = actions[0]
            atype = getattr(a0, "type", "")
            params = dict(getattr(a0, "params", {}) or {})
            target = params.get("element_id") or params.get("text")
        else:
            atype, params, target = "", {}, None
        kw = (getattr(robs, "target_keyword", "") if robs is not None else "") or ""
        if not target and kw:
            target = kw
        return PlanSnapshot(
            intent=getattr(plan, "goal", "") or "",
            action_type=atype,
            target=target,
            parameters=params,
            reasoning_summary=getattr(plan, "thought", None),
            confidence=None,
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("plan_snapshot_from failed: %s", e)
        return PlanSnapshot()


def action_record_from(action, result, started_at=None, finished_at=None) -> "Any":
    from mio_cua.evaluation.schema import ActionRecord

    try:
        tool = getattr(action, "type", getattr(action, "tool", ""))
        params = dict(getattr(action, "params", {}) or {})
        aid = getattr(action, "id", None) or uuid.uuid4().hex[:8]
        success = True
        error = None
        if result is not None:
            success = getattr(result, "success", True)
            error = getattr(result, "message", None) or getattr(result, "error", None)
        return ActionRecord(
            action_id=str(aid),
            tool=str(tool),
            parameters=params,
            started_at=started_at or _now(),
            finished_at=finished_at or _now(),
            success=bool(success),
            error=str(error) if error else None,
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("action_record_from failed: %s", e)
        return ActionRecord(action_id=uuid.uuid4().hex[:8], tool="unknown")


def verification_record_from(v) -> "Any":
    from mio_cua.evaluation.schema import VerificationRecord

    try:
        if isinstance(v, dict):
            return VerificationRecord(
                expected_state=v.get("expected_state", ""),
                observed_state=v.get("observed_state"),
                success=bool(v.get("success", False)),
                confidence=v.get("confidence"),
                evidence=v.get("evidence", {}) or {},
            )
        if hasattr(v, "__dataclass_fields__"):
            return v
        return VerificationRecord(
            expected_state=getattr(v, "expected_state", "") or "",
            observed_state=getattr(v, "observed_state", None),
            success=bool(getattr(v, "success", False)),
            confidence=getattr(v, "confidence", None),
            evidence=getattr(v, "evidence", {}) or {},
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("verification_record_from failed: %s", e)
        return VerificationRecord()


def progress_record_from(progress, before=None, after=None) -> "Any":
    from mio_cua.evaluation.schema import ProgressRecord

    try:
        if isinstance(progress, dict):
            return ProgressRecord(
                previous_state=progress.get("previous_state", ""),
                current_state=progress.get("current_state", ""),
                progress=float(progress.get("progress", 0.0)),
                changed=bool(progress.get("changed", False)),
                blocked=bool(progress.get("blocked", False)),
            )
        if hasattr(progress, "__dataclass_fields__"):
            return progress
        verdict = str(progress)
        changed = verdict == "progress"
        return ProgressRecord(
            previous_state=str(getattr(before, "context", "") or ""),
            current_state=str(getattr(after, "context", "") or ""),
            progress=1.0 if changed else 0.0,
            changed=changed,
            blocked=(verdict == "regression"),
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("progress_record_from failed: %s", e)
        return ProgressRecord()


def recovery_record_from(r) -> "Any":
    from mio_cua.evaluation.schema import RecoveryRecord

    try:
        if isinstance(r, dict):
            return RecoveryRecord(
                reason=r.get("reason", ""),
                strategy=r.get("strategy", ""),
                previous_action=r.get("previous_action", ""),
                recovery_action=r.get("recovery_action", ""),
                success=bool(r.get("success", False)),
            )
        if hasattr(r, "__dataclass_fields__"):
            return r
        return RecoveryRecord(
            reason=getattr(r, "reason", ""),
            strategy=getattr(r, "strategy", ""),
            previous_action=getattr(r, "previous_action", ""),
            recovery_action=getattr(r, "recovery_action", ""),
            success=bool(getattr(r, "success", False)),
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("recovery_record_from failed: %s", e)
        return RecoveryRecord()


def _is_snapshot(v) -> bool:
    """True if ``v`` is already a serialized snapshot (dict) or a schema dataclass."""
    if isinstance(v, dict):
        return True
    if hasattr(v, "__dataclass_fields__") and type(v).__module__ == "mio_cua.evaluation.schema":
        return True
    return False


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# Recorder — event-driven sink that builds a schema.Trace (spec §18)
# ---------------------------------------------------------------------------

class Recorder:
    """Collects runtime TraceEvents into a ``schema.Trace``.

    Lifecycle (driven entirely by events, so the loop only emits):
      TASK_STARTED      -> create Trace
      OBSERVATION/...   -> convert payload to snapshot, append TraceEvent
      TASK_COMPLETED/
      TASK_FAILED       -> set result, run attribution, optionally auto-save
    """

    def __init__(self, store=None, base_dir: str = "traces",
                 auto_save: bool = False, attributor=None):
        self._store = store or JSONLTraceStore(base_dir)
        self._auto_save = auto_save
        # Imported lazily to avoid a hard dependency at construction time.
        from mio_cua.evaluation.attribution import FailureAttributor
        self._attributor = attributor or FailureAttributor()
        self._trace = None

    # -- RuntimeEventSink interface -----------------------------------

    def emit(self, event: Any) -> None:
        if isinstance(event, dict):
            et = event.get("event_type")
            step = event.get("step", 0)
            payload = dict(event.get("payload", {}))
            trace_id = event.get("trace_id")
            ts = event.get("timestamp")
            event_id = event.get("event_id")
        else:
            et = getattr(event, "event_type", None)
            step = getattr(event, "step", 0)
            payload = dict(getattr(event, "payload", {}) or {})
            trace_id = getattr(event, "trace_id", None)
            ts = getattr(event, "timestamp", None)
            event_id = getattr(event, "event_id", None)

        if et in ("task_started",):
            self._start(payload, trace_id, ts)
            return
        if et in ("task_completed", "task_failed"):
            self._finish(et, payload, trace_id, ts)
            return
        if self._trace is None:
            return  # events before TASK_STARTED are ignored

        conv = self._convert(et, payload)
        from mio_cua.evaluation.schema import TraceEvent
        self._trace.events.append(TraceEvent(
            event_type=et, step=step, payload=conv,
            trace_id=self._trace.trace_id, timestamp=ts, event_id=event_id,
        ))

    # -- helpers --------------------------------------------------------

    def _convert(self, et: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(payload)
        try:
            if "observation" in out and not _is_snapshot(out["observation"]):
                out["observation"] = observation_snapshot_from(out["observation"]).to_dict()
            if "belief" in out and not _is_snapshot(out["belief"]):
                out["belief"] = belief_snapshot_from(
                    out.get("belief"), out.get("runtime_obs")).to_dict()
            if "plan" in out and not _is_snapshot(out["plan"]):
                out["plan"] = plan_snapshot_from(
                    out.get("plan"), out.get("runtime_obs")).to_dict()
            if "action" in out and not _is_snapshot(out["action"]):
                out["action"] = action_record_from(
                    out.get("action"), out.get("result"),
                    out.get("started_at"), out.get("finished_at")).to_dict()
            if "verification" in out and not _is_snapshot(out["verification"]):
                out["verification"] = verification_record_from(out["verification"]).to_dict()
            if "progress" in out and not _is_snapshot(out["progress"]):
                out["progress"] = progress_record_from(
                    out.get("progress"), out.get("before"), out.get("after")).to_dict()
            if "recovery" in out and not _is_snapshot(out["recovery"]):
                out["recovery"] = recovery_record_from(out["recovery"]).to_dict()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("recorder payload conversion failed: %s", e)
        # Drop transient helper keys that are not part of the snapshot.
        for k in ("runtime_obs", "result", "started_at", "finished_at", "before", "after"):
            out.pop(k, None)
        return out

    def _start(self, payload: Dict[str, Any], trace_id, ts) -> None:
        from mio_cua.evaluation.schema import Trace, TraceEvent

        goal = payload.get("goal", "")
        tctx = payload.get("target_context", {})
        task = payload.get("task")
        if isinstance(task, dict):
            goal = goal or task.get("instruction", "")
            tctx = task.get("target_context", tctx)
        tid = payload.get("task_id") or trace_id or (goal[:24] or "task")
        self._trace = Trace(
            trace_id=str(tid),
            task_id=str(tid),
            goal=goal,
            started_at=ts or _now(),
            metadata={"target_context": tctx},
        )
        self._trace.events.append(TraceEvent(
            event_type="task_started", step=0,
            payload={"goal": goal, "target_context": tctx},
            timestamp=self._trace.started_at, trace_id=self._trace.trace_id,
        ))

    def _finish(self, et: str, payload: Dict[str, Any], trace_id, ts) -> None:
        from mio_cua.evaluation.schema import TraceEvent

        if self._trace is None:
            return
        status = str(payload.get("status") or
                     ("SUCCESS" if et == "task_completed" else "FAIL")).upper()
        summary = payload.get("summary", "")
        self._trace.finished_at = ts or _now()
        self._trace.result = {"status": status, "summary": summary}
        self._trace.events.append(TraceEvent(
            event_type=et, step=self._trace.steps,
            payload={"status": status, "summary": summary},
            timestamp=self._trace.finished_at, trace_id=self._trace.trace_id,
        ))
        if status != "SUCCESS":
            try:
                self._trace.failure = self._attributor.classify(self._trace)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("auto-attribution failed: %s", e)
        if self._auto_save:
            try:
                self._store.save(self._trace)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("auto-save failed: %s", e)

    # -- accessors ------------------------------------------------------

    @property
    def trace(self):
        return self._trace

    def save(self, trace=None, base_dir: str = None):
        t = trace or self._trace
        if t is None:
            return None
        store = self._store if not base_dir else JSONLTraceStore(base_dir)
        return store.save(t)


# ---------------------------------------------------------------------------
# JSONLTraceStore — append-friendly, git-friendly, schema_versioned (§21-§22)
# ---------------------------------------------------------------------------

class JSONLTraceStore:
    """Stores traces as ``<base>/<date>/<task>/trace.jsonl`` + ``metadata.json``.

    Structure::

        traces/
          2026-08-26/
            task-001/
              trace.jsonl      # one TraceEvent per line
              metadata.json    # everything except the events
    """

    def __init__(self, base_dir: str = "traces"):
        self._base = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _dir_for(self, trace) -> str:
        started = getattr(trace, "started_at", None)
        if hasattr(started, "date"):
            date = started.date().isoformat()
        else:
            date = _now_date()
        tid = getattr(trace, "task_id", None) or getattr(trace, "trace_id", "task")
        return os.path.join(self._base, date, str(tid))

    def save(self, trace) -> str:
        from mio_cua.evaluation.schema import Trace, TraceEvent

        if not isinstance(trace, Trace):
            raise TypeError("JSONLTraceStore.save expects a schema.Trace")
        d = self._dir_for(trace)
        os.makedirs(d, exist_ok=True)
        meta = {k: v for k, v in trace.to_dict().items() if k != "events"}
        with open(os.path.join(d, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        with open(os.path.join(d, "trace.jsonl"), "w", encoding="utf-8") as f:
            for e in trace.events:
                f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        return d

    def load(self, path: str):
        from mio_cua.evaluation.schema import Trace

        if os.path.isdir(path):
            return self._load_dir(path)
        with open(path, encoding="utf-8") as f:
            return Trace.from_dict(json.load(f))

    def _load_dir(self, d: str):
        from mio_cua.evaluation.schema import Trace, TraceEvent

        with open(os.path.join(d, "metadata.json"), encoding="utf-8") as f:
            meta = json.load(f)
        events = []
        jl = os.path.join(d, "trace.jsonl")
        if os.path.exists(jl):
            with open(jl, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
        meta["events"] = events
        return Trace.from_dict(meta)

    def load_task(self, task_id: str, date: str = None):
        if date:
            cand = os.path.join(self._base, date, task_id)
            if os.path.isdir(cand) and os.path.exists(os.path.join(cand, "metadata.json")):
                return self._load_dir(cand)
        for root, _dirs, files in os.walk(self._base):
            if "metadata.json" in files:
                try:
                    with open(os.path.join(root, "metadata.json"), encoding="utf-8") as f:
                        m = json.load(f)
                except Exception:
                    continue
                if m.get("task_id") == task_id or m.get("trace_id") == task_id:
                    return self._load_dir(root)
        return None

    def list_traces(self) -> List[str]:
        out = []
        for root, _dirs, files in os.walk(self._base):
            if "metadata.json" in files:
                out.append(root)
        return out


def _now_date() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()

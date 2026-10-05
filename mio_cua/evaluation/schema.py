"""Canonical Phase 3 trace data model (spec §5-§27, §30).

This module is the authoritative, serializable model for Agent Runtime v2
Phase 3: real-trajectory recording, deterministic replay, and failure
attribution.

Design constraints
-------------------
* **stdlib-only** — this module must NOT import any other ``mio_cua`` module.
  That keeps it import-safe from core runtime code (e.g. ``agent/loop.py`` can
  ``from mio_cua.evaluation.schema import TraceEvent`` lazily without creating
  an import cycle).
* **serializable** — every dataclass round-trips through ``to_dict`` /
  ``from_dict`` and the JSONL store, carrying ``schema_version`` (spec §22) for
  forward migration.
* **snapshot, not reference** — a Trace never holds live runtime objects; it
  stores frozen snapshots (spec §7).

Event flow
----------
    Goal -> Observation -> Belief -> Plan -> Action -> Verification
         -> Progress -> Recovery -> (loop)  ->  Trace  ->  Replay
         ->  Evaluation  ->  Failure Attribution  ->  Runtime improvement
"""

from __future__ import annotations

import datetime as _dt
import json
import types
import typing as _t
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Helpers: time + recursive (de)serialization
# ---------------------------------------------------------------------------

def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(ts: Any) -> Any:
    if isinstance(ts, _dt.datetime):
        return ts.isoformat()
    if isinstance(ts, (int, float)):
        try:
            return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat()
        except Exception:
            return ts
    return ts


def _parse_ts(ts: Any) -> Any:
    if ts is None:
        return None
    if isinstance(ts, _dt.datetime):
        return ts
    if isinstance(ts, (int, float)):
        try:
            return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc)
        except Exception:
            return ts
    if isinstance(ts, str):
        try:
            return _dt.datetime.fromisoformat(ts)
        except Exception:
            return ts
    return ts


def _deep_to_dict(o: Any) -> Any:
    """Recursively convert dataclasses / containers / datetimes to JSON-native."""
    if hasattr(o, "__dataclass_fields__"):
        return {k: _deep_to_dict(v) for k, v in o.__dict__.items()}
    if isinstance(o, dict):
        return {k: _deep_to_dict(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_deep_to_dict(x) for x in o]
    if isinstance(o, set):
        return [_deep_to_dict(x) for x in o]
    if isinstance(o, _dt.datetime):
        return o.isoformat()
    if isinstance(o, Enum):
        return o.value
    return o


def _dc_from_dict(cls: type, d: Dict[str, Any]) -> Any:
    """Reconstruct a dataclass from a dict, rebuilding nested dataclasses."""
    import dataclasses as _dc

    hints = _t.get_type_hints(cls)
    kwargs: Dict[str, Any] = {}
    for f in _dc.fields(cls):
        if f.name not in d:
            continue
        kwargs[f.name] = _from_value(hints.get(f.name), d[f.name])
    return cls(**kwargs)


def _from_value(hint: Any, value: Any) -> Any:
    import dataclasses as _dc

    if value is None:
        return None
    if _dc.is_dataclass(hint) and isinstance(value, dict):
        return _dc_from_dict(hint, value)
    # Restore tuples: JSON round-trips them as lists, but the model declares
    # ``tuple`` (e.g. ObservationSnapshot.screen_size).
    if hint is tuple or _t.get_origin(hint) is tuple:
        if isinstance(value, list):
            return tuple(value)
        return value
    origin = _t.get_origin(hint)
    if origin is _dc.is_dataclass.__class__:  # pragma: no cover - defensive
        origin = None
    if origin in (list, List):
        args = _t.get_args(hint)
        item_hint = args[0] if args else None
        return [_from_value(item_hint, v) for v in value]
    if origin is _t.Union or type(hint) is types.UnionType:
        for arg in _t.get_args(hint):
            if arg is type(None):
                continue
            if _dc.is_dataclass(arg) and isinstance(value, dict):
                return _dc_from_dict(arg, value)
        return value
    return value


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    TASK_STARTED = "task_started"
    OBSERVATION = "observation"
    BELIEF_UPDATED = "belief_updated"
    PLAN_CREATED = "plan_created"
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    VERIFICATION = "verification"
    PROGRESS = "progress"
    RECOVERY_STARTED = "recovery_started"
    RECOVERY_COMPLETED = "recovery_completed"
    ERROR = "error"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"


class FailureCategory(str, Enum):
    PERCEPTION = "perception"
    PLANNER = "planner"
    ACTION = "action"
    ENVIRONMENT = "environment"
    VERIFICATION = "verification"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# TraceEvent (spec §6)
# ---------------------------------------------------------------------------

@dataclass
class TraceEvent:
    event_type: str
    step: int = 0
    timestamp: Any = field(default_factory=_now)
    payload: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace_id: Optional[str] = None
    duration_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "step": self.step,
            "timestamp": _iso(self.timestamp),
            "event_type": self.event_type,
            "payload": _deep_to_dict(self.payload),
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TraceEvent":
        return cls(
            event_id=d.get("event_id", uuid.uuid4().hex[:12]),
            trace_id=d.get("trace_id"),
            step=d.get("step", 0),
            timestamp=_parse_ts(d.get("timestamp")),
            event_type=d.get("event_type", "unknown"),
            payload=d.get("payload", {}) or {},
            duration_ms=d.get("duration_ms"),
        )


# ---------------------------------------------------------------------------
# Snapshot dataclasses (spec §7-§13)
# ---------------------------------------------------------------------------

@dataclass
class ObservationSnapshot:
    observation_id: str
    timestamp: Any = field(default_factory=_now)
    screen_size: tuple = (0, 0)
    scene: Optional[Dict[str, Any]] = None
    active_window: Optional[str] = None
    cursor: Optional[Dict[str, Any]] = None
    raw_elements: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _deep_to_dict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ObservationSnapshot":
        return _dc_from_dict(cls, d)


@dataclass
class BeliefSnapshot:
    goal: str = ""
    current_state: str = ""
    expected_state: Optional[str] = None
    confidence: float = 0.0
    known_entities: List[Dict[str, Any]] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _deep_to_dict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BeliefSnapshot":
        return _dc_from_dict(cls, d)


@dataclass
class PlanSnapshot:
    intent: str = ""
    action_type: str = ""
    target: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    reasoning_summary: Optional[str] = None
    confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return _deep_to_dict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PlanSnapshot":
        return _dc_from_dict(cls, d)


@dataclass
class ActionRecord:
    action_id: str
    tool: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    started_at: Any = field(default_factory=_now)
    finished_at: Any = field(default_factory=_now)
    success: bool = False
    error: Optional[str] = None
    actual_effect: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _deep_to_dict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ActionRecord":
        return _dc_from_dict(cls, d)


@dataclass
class VerificationRecord:
    expected_state: str = ""
    observed_state: Optional[str] = None
    success: bool = False
    confidence: Optional[float] = None
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _deep_to_dict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "VerificationRecord":
        return _dc_from_dict(cls, d)


@dataclass
class ProgressRecord:
    previous_state: str = ""
    current_state: str = ""
    progress: float = 0.0
    changed: bool = False
    blocked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return _deep_to_dict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProgressRecord":
        return _dc_from_dict(cls, d)


@dataclass
class RecoveryRecord:
    reason: str = ""
    strategy: str = ""
    previous_action: str = ""
    recovery_action: str = ""
    success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return _deep_to_dict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RecoveryRecord":
        return _dc_from_dict(cls, d)


# ---------------------------------------------------------------------------
# Failure attribution (spec §14-§17)
# ---------------------------------------------------------------------------

@dataclass
class FailureCandidate:
    category: str = ""
    confidence: float = 0.0
    reason: str = ""


@dataclass
class FailureAttribution:
    category: str = FailureCategory.UNKNOWN.value
    confidence: float = 0.0
    step: Optional[int] = None
    event_id: Optional[str] = None
    reason: str = ""
    evidence: List[str] = field(default_factory=list)
    candidates: List[FailureCandidate] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _deep_to_dict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FailureAttribution":
        return _dc_from_dict(cls, d)


# ---------------------------------------------------------------------------
# Plan comparison (spec §25)
# ---------------------------------------------------------------------------

@dataclass
class PlanComparison:
    same_action: bool = False
    same_target: bool = False
    parameter_delta: Dict[str, Any] = field(default_factory=dict)
    semantic_match: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return _deep_to_dict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PlanComparison":
        return _dc_from_dict(cls, d)


# ---------------------------------------------------------------------------
# Benchmark result (spec §26-§27)
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkResult:
    total_tasks: int = 0
    success_tasks: int = 0
    failed_tasks: int = 0
    success_rate: float = 0.0
    failure_distribution: Dict[str, int] = field(default_factory=dict)
    recovery_success_rate: float = 0.0
    average_steps: float = 0.0
    average_recovery_count: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _deep_to_dict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BenchmarkResult":
        return _dc_from_dict(cls, d)


# ---------------------------------------------------------------------------
# Trace (spec §5) + JSONL (spec §21-§22)
# ---------------------------------------------------------------------------

@dataclass
class Trace:
    trace_id: str
    task_id: str = ""
    goal: str = ""
    started_at: Any = field(default_factory=_now)
    finished_at: Any = None
    events: List[TraceEvent] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    failure: Optional[FailureAttribution] = None
    schema_version: int = SCHEMA_VERSION
    metadata: Dict[str, Any] = field(default_factory=dict)

    # -- serialization ----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "goal": self.goal,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at) if self.finished_at else None,
            "events": [e.to_dict() for e in self.events],
            "result": _deep_to_dict(self.result) if self.result else None,
            "failure": self.failure.to_dict() if self.failure else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Trace":
        return cls(
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            trace_id=d["trace_id"],
            task_id=d.get("task_id", ""),
            goal=d.get("goal", ""),
            started_at=_parse_ts(d.get("started_at")),
            finished_at=_parse_ts(d.get("finished_at")) if d.get("finished_at") else None,
            events=[TraceEvent.from_dict(e) for e in d.get("events", [])],
            result=d.get("result"),
            failure=FailureAttribution.from_dict(d["failure"]) if d.get("failure") else None,
            metadata=d.get("metadata", {}),
        )

    def to_json(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def from_json(cls, path: str) -> "Trace":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    # -- convenience accessors -------------------------------------------

    @property
    def steps(self) -> int:
        return len(self.events)

    def events_of(self, event_type: str) -> List[TraceEvent]:
        return [e for e in self.events if e.event_type == event_type]

    @property
    def success(self) -> bool:
        for e in self.events:
            if e.event_type in (EventType.TASK_COMPLETED.value,):
                return (e.payload or {}).get("status", "").upper() == "SUCCESS"
        if self.result:
            return str(self.result.get("status", "")).upper() == "SUCCESS"
        return False

    def recovery_events(self) -> List[TraceEvent]:
        return [e for e in self.events
                if e.event_type in (EventType.RECOVERY_STARTED.value,
                                    EventType.RECOVERY_COMPLETED.value)]


# ---------------------------------------------------------------------------
# TraceRedactor (spec §30) — privacy by default, never uploads
# ---------------------------------------------------------------------------

class TraceRedactor:
    """Redacts sensitive content from a Trace before storage/sharing.

    Defaults are conservative: nothing is stripped unless explicitly enabled.
    Traces are never uploaded by this module.
    """

    def __init__(self, patterns: Optional[List[str]] = None,
                 sensitive_keywords: Optional[List[str]] = None):
        self.patterns = list(patterns or [])
        self.sensitive_keywords = list(sensitive_keywords or [])
        self._disable_raw = False

    def disable_raw_observation(self) -> "TraceRedactor":
        self._disable_raw = True
        return self

    def redact_text(self, text: str) -> str:
        if not text:
            return text
        out = text
        for pat in self.patterns:
            out = out.replace(pat, "***")
        return out

    def redact_sensitive_elements(self, trace: Trace) -> Trace:
        if not self.sensitive_keywords:
            return trace
        red = self.redact(trace)
        return red

    def redact(self, trace: Trace) -> Trace:
        """Return a redacted copy of ``trace`` (no mutation of the original)."""
        events = []
        for e in trace.events:
            payload = dict(e.payload or {})
            obs = payload.get("observation")
            if isinstance(obs, dict):
                obs = self._redact_observation(obs)
                payload["observation"] = obs
            events.append(TraceEvent(
                event_type=e.event_type, step=e.step, timestamp=e.timestamp,
                payload=payload, event_id=e.event_id, trace_id=e.trace_id,
                duration_ms=e.duration_ms,
            ))
        return Trace(
            trace_id=trace.trace_id, task_id=trace.task_id, goal=self.redact_text(trace.goal),
            started_at=trace.started_at, finished_at=trace.finished_at,
            events=events, result=trace.result, failure=trace.failure,
            schema_version=trace.schema_version,
            metadata=dict(trace.metadata or {}),
        )

    def _redact_observation(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(obs)
        if self._disable_raw:
            out.pop("raw_elements", None)
            scene = out.get("scene")
            if isinstance(scene, dict):
                scene = dict(scene)
                scene.pop("nodes", None)
                out["scene"] = scene
        else:
            nodes = (out.get("scene") or {}).get("nodes") if isinstance(out.get("scene"), dict) else None
            if isinstance(nodes, list):
                new_nodes = []
                for n in nodes:
                    nn = dict(n)
                    text = nn.get("text", "")
                    if any(kw in (text or "") for kw in self.sensitive_keywords):
                        nn["text"] = "***"
                    new_nodes.append(nn)
                scene = dict(out.get("scene") or {})
                scene["nodes"] = new_nodes
                out["scene"] = scene
            raw = out.get("raw_elements")
            if isinstance(raw, list):
                new_raw = []
                for n in raw:
                    nn = dict(n)
                    text = nn.get("text", "")
                    if any(kw in (text or "") for kw in self.sensitive_keywords):
                        nn["text"] = "***"
                    new_raw.append(nn)
                out["raw_elements"] = new_raw
        return out

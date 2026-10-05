"""Deterministic Replay/Mock Benchmark for Agent Runtime v2.

Phase 1: tests the Runtime loop (belief, progress, recovery, safety invariants)
without LLM. Agent receives pre-recorded observations, Evaluator checks
invariants against ground truth that the Agent never sees.

Data flow isolation:
  Agent:   Observation + Task + Belief
  Evaluator: Observation + Action + GroundTruth
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from mio_cua.models.action import Action
from mio_cua.models.action_result import RawResult
from mio_cua.models.observation import Observation
from mio_cua.scene.graph import SceneGraph, SceneNode


# ---------------------------------------------------------------------------
# MockPerception: feeds pre-recorded observations
# ---------------------------------------------------------------------------

class MockPerception:
    """Replaces real Perception with pre-recorded observations."""

    def __init__(self, observations: List[Observation]):
        self._observations = list(observations)
        self._index = 0

    def observe(self):
        obs = self._observations[min(self._index, len(self._observations) - 1)]
        self._index += 1
        return obs

    def observe_light(self):
        return self.observe()


# ---------------------------------------------------------------------------
# MockInputController: captures actions, no real input
# ---------------------------------------------------------------------------

class MockInputController:
    """Captures actions without sending real input. Resolves element_id
    by falling back to scene nodes so the loop doesn't crash, but keeps
    element_id in params for evaluation (does NOT replace with x/y)."""

    def __init__(self):
        self.current_observation = None
        self.actions: List[Dict[str, Any]] = []

    def resolve(self, action: Action):
        element_id = action.params.get("element_id")
        if element_id is None:
            return
        if self.current_observation is not None:
            for e in getattr(self.current_observation, "elements", []) or []:
                if e.id == element_id or str(e.id) == str(element_id):
                    return
            scene = getattr(self.current_observation, "scene", None)
            if scene is not None:
                for n in getattr(scene, "nodes", []) or []:
                    if n.id == element_id or str(n.id) == str(element_id):
                        return

    def execute(self, action: Action) -> RawResult:
        self.resolve(action)
        self.actions.append({"type": action.type, "params": dict(action.params)})
        return RawResult(sent=True)


# ---------------------------------------------------------------------------
# Observation builder: JSON dict → Observation
# ---------------------------------------------------------------------------

def _build_obs(data: dict) -> Observation:
    nodes = [
        SceneNode(
            id=n["id"],
            type=n.get("type", "unknown"),
            bbox=n.get("bbox", [0, 0, 0, 0]),
            text=n.get("text", ""),
            semantic=n.get("semantic"),
        )
        for n in data.get("scene_nodes", [])
    ]
    return Observation(
        screenshot_path=None,
        timestamp=0.0,
        active_window=data.get("active_window", ""),
        dpi_scale=1.0,
        elements=[],
        scene=SceneGraph(nodes=nodes, active_window=data.get("active_window", "")),
    )


# ---------------------------------------------------------------------------
# Evaluator: checks invariants against ground truth (Agent不可见)
# ---------------------------------------------------------------------------

class Evaluator:
    """Validates Agent behavior against ground truth and transition graph.
    ground_truth is NEVER injected into the Agent context."""

    def __init__(self, ground_truth: List[dict], transition_graph: dict, goal: dict):
        self._gt = {g["obs_id"]: g for g in ground_truth}
        self._edges = transition_graph.get("edges", [])
        self._goal = goal
        self._step_results: List[dict] = []
        self._prev_obs_id: Optional[int] = None

    def evaluate_step(self, obs_id: int, action: dict) -> dict:
        gt = self._gt.get(obs_id, {})
        result = {
            "obs_id": obs_id,
            "action_type": action.get("type"),
            "context_valid": gt.get("context_matches", True),
            "target_visible": gt.get("target_visible", False),
            "action_allowed": self._check_action_allowed(obs_id, action),
            "safety_invariant": self._check_safety(action),
            "progress": self._check_progress(obs_id, gt),
        }
        self._step_results.append(result)
        self._prev_obs_id = obs_id
        return result

    def _check_action_allowed(self, obs_id: int, action: dict) -> bool:
        action_type = action.get("type")
        for edge in self._edges:
            if edge["from"] != obs_id:
                continue
            if edge["action_type"] != action_type:
                continue
            params_match = edge.get("action_params_match", {})
            action_params = action.get("params", {})
            if all(action_params.get(k) == v for k, v in params_match.items()):
                return True
        return False

    def _check_safety(self, action: dict) -> bool:
        for pat in self._gt.get(0, {}).get("forbidden_patterns", []):
            if pat == "click_frame_node":
                if action.get("type") in ("click", "select_element"):
                    eid = action.get("params", {}).get("element_id")
                    if eid in (0, 1):
                        return False
            if pat == "raw_xy_outside_window":
                if action.get("type") == "click" and "element_id" not in action.get("params", {}):
                    if "x" in action.get("params", {}) and "y" in action.get("params", {}):
                        return False
        return True

    def _check_progress(self, obs_id: int, gt: dict) -> bool:
        if self._prev_obs_id is None:
            return True
        goal_type = self._goal.get("type")
        if goal_type == "target_visible_then_click":
            prev_gt = self._gt.get(self._prev_obs_id, {})
            was_visible = prev_gt.get("target_visible", False)
            now_visible = gt.get("target_visible", False)
            return (not was_visible) and now_visible
        return True

    def evaluate_final(self, last_obs_id: int, actions: list) -> dict:
        goal_reached = False
        goal_type = self._goal.get("type")
        if goal_type == "action_type":
            goal_reached = any(
                a.get("type") == self._goal.get("action_type") for a in actions
            )
        elif goal_type == "target_visible_then_click":
            keyword = self._goal.get("keyword", "")
            for a in actions:
                if a.get("type") in ("click", "select_element"):
                    params = a.get("params", {})
                    if "text" in params and keyword in params.get("text", ""):
                        goal_reached = True
                        break
                    if keyword and params.get("element_id"):
                        goal_reached = True
                        break

        invalid = sum(1 for s in self._step_results if not s["action_allowed"])
        inv_viol = sum(1 for s in self._step_results if not s["safety_invariant"])
        progress_steps = sum(1 for s in self._step_results if s["progress"])

        return {
            "goal_reached": goal_reached,
            "steps": len(actions),
            "invalid_action_count": invalid,
            "invariant_violation_count": inv_viol,
            "progress_steps": progress_steps,
            "step_results": self._step_results,
        }


# ---------------------------------------------------------------------------
# ReplayBenchmark: orchestrates replay
# ---------------------------------------------------------------------------

@dataclass
class ReplayResult:
    scenario_id: str
    goal_reached: bool
    steps: int
    invalid_action_count: int
    invariant_violation_count: int
    progress_steps: int
    actions: List[dict] = field(default_factory=list)
    step_results: List[dict] = field(default_factory=list)
    summary: str = ""


class ReplayBenchmark:
    """Runs a scenario through AgentLoopV2 with mock perception and controller.
    Evaluator checks ground truth that is never injected into the Agent."""

    def __init__(self, scenario_path: str):
        with open(scenario_path, encoding="utf-8") as f:
            self._scenario = json.load(f)
        self._observations = [_build_obs(o) for o in self._scenario["observations"]]

    def run(self) -> ReplayResult:
        sc = self._scenario
        task_data = sc["task"]

        from mio_cua.models.task import Task
        task = Task(
            instruction=task_data["instruction"],
            target_context=task_data.get("target_context", {}),
            metadata=task_data.get("metadata", {}),
        )

        perception = MockPerception(self._observations)
        controller = MockInputController()
        evaluator = Evaluator(
            sc["ground_truth"], sc["transition_graph"], sc["goal"]
        )

        from mio_cua.agent.planner import Planner
        from mio_cua.memory.history import History
        from mio_cua.agent.recover import Recover
        from mio_cua.agent.safety import Safety
        from mio_cua.events import EventBus
        from mio_cua.config import AgentConfig
        from mio_cua.tools.registry import ToolRegistry
        from mio_cua.tools.builtin import register_builtin_tools

        class _FakeProvider:
            def generate(self, messages, tools=None):
                from dataclasses import dataclass
                @dataclass
                class _Resp:
                    message = ""
                    tool_calls = []
                return _Resp()

        config = AgentConfig(
            base_url="", api_key_env="MOCK", model="mock",
            max_steps=sc["goal"].get("max_steps", 10),
            task_timeout_s=60,
            artifact_dir="C:/Temp/mio_cua_replay/artifacts",
            runtime_v2=True,
        )

        registry = ToolRegistry()
        register_builtin_tools(registry)

        from mio_cua.runtime.loop import AgentLoopV2
        loop = AgentLoopV2(
            perception=perception,
            planner=Planner(_FakeProvider(), "You are a mock agent."),
            registry=registry,
            safety=Safety(max_steps=config.max_steps, timeout_s=config.task_timeout_s),
            events=EventBus(),
            config=config,
            history=History(),
            controller=controller,
            artifact_store=None,
            state_dir=None,
            recover=Recover(lambda d: None, perception),
        )

        result = loop.run(task)

        actions = controller.actions
        eval_result = evaluator.evaluate_final(
            self._observations[-1].get("id", len(self._observations) - 1) if isinstance(self._observations[-1], dict) else len(self._observations) - 1,
            actions,
        )

        goal_type = sc["goal"].get("type")
        goal_label = sc["goal"].get("action_type", sc["goal"].get("keyword", ""))
        steps = eval_result["steps"]
        invalid = eval_result["invalid_action_count"]
        inv_viol = eval_result["invariant_violation_count"]
        progress = eval_result["progress_steps"]
        goal_ok = eval_result["goal_reached"]

        summary = (
            f"goal={'OK' if goal_ok else 'FAIL'}({goal_label}) "
            f"steps={steps} invalid={invalid} violations={inv_viol} progress={progress}"
        )

        return ReplayResult(
            scenario_id=sc["id"],
            goal_reached=goal_ok,
            steps=steps,
            invalid_action_count=invalid,
            invariant_violation_count=inv_viol,
            progress_steps=progress,
            actions=actions,
            step_results=eval_result["step_results"],
            summary=summary,
        )


# ===========================================================================
# Phase 3 — ReplayEngine (spec §23-§25)
# ===========================================================================
#
# Two offline modes (no real desktop, no real mouse/keyboard — AC3):
#   * deterministic : re-walk the recorded event chain, rebuild state
#                     transitions, and run failure attribution.
#   * planner       : feed each recorded Observation to a (real LLM) Planner
#                     and compare its decision with the recorded plan.
#
# Live replay (Mode 3) is intentionally disabled in Phase 3: Replay must
# never trigger real input (spec §31).
# ---------------------------------------------------------------------------

class ReplayOutcome:
    """Result of replaying a trace (offline, no real actions)."""

    def __init__(self, trace_id: str, mode: str):
        self.trace_id = trace_id
        self.mode = mode
        self.reproduced_steps = 0
        self.reproduced_status = ""
        self.state_transitions: List[dict] = []
        self.attribution = None
        self.plan_comparisons: List[Any] = []
        self.triggered_real_action = False
        self.summary = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "mode": self.mode,
            "reproduced_steps": self.reproduced_steps,
            "reproduced_status": self.reproduced_status,
            "state_transitions": self.state_transitions,
            "attribution": self.attribution.to_dict() if self.attribution else None,
            "plan_comparisons": [c.to_dict() for c in self.plan_comparisons],
            "triggered_real_action": self.triggered_real_action,
            "summary": self.summary,
        }


def compare_plans(recorded: Any, replayed: Any) -> "Any":
    """Compare a recorded PlanSnapshot with a replayed one (spec §25)."""
    from mio_cua.evaluation.schema import PlanComparison

    rec = recorded if isinstance(recorded, dict) else (
        recorded.__dict__ if hasattr(recorded, "__dataclass_fields__") else {})
    rep = replayed if isinstance(replayed, dict) else (
        replayed.__dict__ if hasattr(replayed, "__dataclass_fields__") else {})

    rec_action = (rec.get("action_type") if isinstance(rec, dict) else getattr(rec, "action_type", "")) or ""
    rep_action = (rep.get("action_type") if isinstance(rep, dict) else getattr(rep, "action_type", "")) or ""
    rec_target = (rec.get("target") if isinstance(rec, dict) else getattr(rec, "target", None))
    rep_target = (rep.get("target") if isinstance(rep, dict) else getattr(rep, "target", None))
    rec_params = (rec.get("parameters") if isinstance(rec, dict) else getattr(rec, "parameters", None)) or {}
    rep_params = (rep.get("parameters") if isinstance(rep, dict) else getattr(rep, "parameters", None)) or {}

    same_action = (rec_action or "") == (rep_action or "")
    same_target = _eq_target(rec_target, rep_target)

    delta: Dict[str, Any] = {}
    for k in set(rec_params) | set(rep_params):
        if rec_params.get(k) != rep_params.get(k):
            delta[k] = {"recorded": rec_params.get(k), "replayed": rep_params.get(k)}

    if same_action and same_target:
        semantic = 1.0
    elif same_action:
        semantic = 0.5
    else:
        semantic = 0.0

    return PlanComparison(
        same_action=same_action, same_target=same_target,
        parameter_delta=delta, semantic_match=semantic,
    )


def _eq_target(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if str(a).isdigit() and str(b).isdigit():
        return int(a) == int(b)
    return str(a).lower() == str(b).lower()


class ReplayEngine:
    """Replays recorded traces offline for debugging and evaluation."""

    def __init__(self, attributor=None):
        from mio_cua.evaluation.attribution import FailureAttributor
        self._attributor = attributor or FailureAttributor()

    # -- loading --------------------------------------------------------

    def load(self, trace_path: str):
        """Load a Trace from a directory, a .json file, or a .jsonl file."""
        from mio_cua.evaluation.recorder import JSONLTraceStore
        from mio_cua.evaluation.schema import Trace, TraceEvent

        if os.path.isdir(trace_path):
            return JSONLTraceStore(trace_path).load(trace_path)
        if trace_path.endswith(".jsonl"):
            events = []
            with open(trace_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(TraceEvent.from_dict(json.loads(line)))
            tid = events[0].trace_id if events else "trace"
            return Trace(trace_id=tid, events=events)
        return Trace.from_json(trace_path)

    # -- replay ---------------------------------------------------------

    def replay(self, trace, mode: str = "deterministic", planner=None) -> ReplayOutcome:
        if mode == "live":
            raise RuntimeError(
                "Live replay is disabled in Phase 3: it would trigger real "
                "mouse/keyboard input. Use deterministic or planner mode."
            )
        if mode == "planner":
            return self._replay_planner(trace, planner)
        return self._replay_deterministic(trace)

    def _replay_deterministic(self, trace) -> ReplayOutcome:
        outcome = ReplayOutcome(trace.trace_id, "deterministic")
        outcome.reproduced_steps = len(trace.events)

        status = ""
        for e in trace.events:
            if e.event_type in ("task_completed", "task_failed"):
                status = str((e.payload or {}).get("status", e.event_type)).upper()
        if not status:
            status = str((trace.result or {}).get("status", "UNKNOWN")).upper()
        outcome.reproduced_status = status

        transitions = []
        for e in trace.events:
            p = e.payload or {}
            entry = {"step": e.step, "event_type": e.event_type}
            if e.event_type == "observation":
                obs = p.get("observation") or {}
                entry["active_window"] = obs.get("active_window")
                entry["node_count"] = len((obs.get("scene") or {}).get("nodes", []) or [])
            elif e.event_type == "plan_created":
                plan = p.get("plan") or {}
                entry["action_type"] = plan.get("action_type")
                entry["target"] = plan.get("target")
            elif e.event_type in ("action_completed", "action_started"):
                act = p.get("action") or {}
                entry["tool"] = act.get("tool") or act.get("action_type")
                entry["success"] = act.get("success")
            elif e.event_type in ("recovery_started", "recovery_completed"):
                rec = p.get("recovery") or {}
                entry["recovery_action"] = rec.get("recovery_action")
            transitions.append(entry)
        outcome.state_transitions = transitions

        try:
            outcome.attribution = self._attributor.classify(trace)
        except Exception:  # pragma: no cover - defensive
            outcome.attribution = None

        outcome.triggered_real_action = False
        outcome.summary = (f"deterministic replay: {outcome.reproduced_steps} events, "
                           f"status={outcome.reproduced_status}")
        return outcome

    def _replay_planner(self, trace, planner) -> ReplayOutcome:
        outcome = ReplayOutcome(trace.trace_id, "planner")
        if planner is None:
            outcome.summary = "planner replay requires a planner callable"
            return outcome

        comparisons = []
        for e in trace.events:
            if e.event_type != "observation":
                continue
            obs = (e.payload or {}).get("observation")
            recorded_plan = None
            for pe in trace.events:
                if pe.event_type == "plan_created" and pe.step == e.step:
                    recorded_plan = (pe.payload or {}).get("plan")
                    break
            try:
                replayed = planner(obs, recorded_plan)
            except Exception:
                replayed = None
            if recorded_plan is not None and replayed is not None:
                comparisons.append(compare_plans(recorded_plan, replayed))

        outcome.plan_comparisons = comparisons
        outcome.reproduced_steps = len(trace.events)
        outcome.triggered_real_action = False
        diverged = sum(1 for c in comparisons if not c.same_action)
        outcome.summary = (f"planner replay: {len(comparisons)} plans compared, "
                           f"{diverged} diverged")
        return outcome

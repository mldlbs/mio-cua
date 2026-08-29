"""Phase 2: Synthetic Planner Benchmark.

Fixed Observation → Real LLM Planner → Action → Evaluator.
Tests whether the LLM can做出正确类别的下一步动作, without real desktop.

Data flow:
  Observation (fixed) → Planner (real LLM) → Action → Evaluator (valid/invalid/progress)
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from mio_cua.models.action import Action, Plan
from mio_cua.models.observation import Observation
from mio_cua.scene.graph import SceneGraph, SceneNode


# ---------------------------------------------------------------------------
# Observation builder
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
# MockPerception: feeds one observation then clamps
# ---------------------------------------------------------------------------

class _SingleObsPerception:
    def __init__(self, obs: Observation):
        self._obs = obs
        self._called = False

    def observe(self):
        self._called = True
        return self._obs

    def observe_light(self):
        return self._obs


# ---------------------------------------------------------------------------
# Scenario definition
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    id: str
    description: str
    observation: dict
    expected_action_type: str
    goal: Dict[str, Any]
    notes: str = ""


# ---------------------------------------------------------------------------
# Evaluator: checks action category + invariants
# ---------------------------------------------------------------------------

class SyntheticEvaluator:
    """Evaluates Planner output against expected action type and invariants.

    Does NOT use transition_graph — only checks single-step action validity.
    """

    def __init__(self):
        self._results: List[dict] = []

    def evaluate(self, scenario: Scenario, action: Optional[Action], thought: str) -> dict:
        if action is None:
            result = {
                "scenario_id": scenario.id,
                "valid": False,
                "expected": scenario.expected_action_type,
                "actual": None,
                "progress": False,
                "unsafe": False,
                "thought": thought[:200],
                "notes": "no action produced",
            }
        else:
            valid = action.type == scenario.expected_action_type
            unsafe = self._check_unsafe(action)
            progress = self._check_progress(scenario, action)
            result = {
                "scenario_id": scenario.id,
                "valid": valid,
                "expected": scenario.expected_action_type,
                "actual": action.type,
                "actual_params": dict(action.params),
                "progress": progress,
                "unsafe": unsafe,
                "thought": thought[:200],
                "notes": "" if valid else f"expected {scenario.expected_action_type}, got {action.type}",
            }
        self._results.append(result)
        return result

    def _check_unsafe(self, action: Action) -> bool:
        if action.type in ("click", "select_element"):
            eid = action.params.get("element_id")
            if eid in (0, 1):
                return True
        if action.type == "click" and "element_id" not in action.params:
            if "x" in action.params and "y" in action.params:
                return True
        return False

    def _check_progress(self, scenario: Scenario, action: Action) -> bool:
        goal = scenario.goal
        if goal.get("type") == "target_visible_then_click":
            return action.type in ("click", "select_element")
        if goal.get("type") == "context_mismatch":
            return action.type == "focus_window"
        if goal.get("type") == "target_visible":
            return action.type in ("click", "select_element")
        return action.type != "wait"

    def summary(self) -> dict:
        if not self._results:
            return {"total": 0}
        total = len(self._results)
        valid = sum(1 for r in self._results if r["valid"])
        unsafe = sum(1 for r in self._results if r["unsafe"])
        progress = sum(1 for r in self._results if r["progress"])
        return {
            "total": total,
            "valid_action_rate": round(valid / total, 3),
            "goal_progress_rate": round(progress / total, 3),
            "unsafe_action_rate": round(unsafe / total, 3),
        }


# ---------------------------------------------------------------------------
# SyntheticBenchmark: orchestrates LLM + evaluator
# ---------------------------------------------------------------------------

@dataclass
class SyntheticResult:
    scenario_id: str
    valid: bool
    actual: Optional[str]
    expected: str
    progress: bool
    unsafe: bool
    thought: str
    notes: str


class SyntheticBenchmark:
    """Runs fixed observations through real LLM Planner and evaluates output.

    Usage:
        bench = SyntheticBenchmark(provider, system_prompt, tool_defs)
        results = bench.run("path/to/scenarios.json")
    """

    def __init__(self, provider, system_prompt: str, tool_defs: list):
        self._provider = provider
        self._system_prompt = system_prompt
        self._tool_defs = tool_defs

    def load_scenarios(self, path: str) -> List[Scenario]:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [
            Scenario(
                id=s["id"],
                description=s["description"],
                observation=s["observation"],
                expected_action_type=s["expected_action_type"],
                goal=s.get("goal", {}),
                notes=s.get("notes", ""),
            )
            for s in data["scenarios"]
        ]

    def run(self, scenarios_path: str) -> List[SyntheticResult]:
        scenarios = self.load_scenarios(scenarios_path)
        evaluator = SyntheticEvaluator()
        results = []

        from mio_cua.agent.planner import Planner
        from mio_cua.memory.history import History

        planner = Planner(self._provider, self._system_prompt)

        for sc in scenarios:
            obs = _build_obs(sc.observation)
            perception = _SingleObsPerception(obs)
            history = History()

            from mio_cua.models.task import Task
            task = Task(
                instruction=sc.goal.get("instruction", "Complete the task"),
                target_context=sc.goal.get("target_context", {}),
                metadata=sc.goal.get("metadata", {}),
            )

            plan = planner.plan(task, obs, None, self._tool_defs, history=history)

            action = plan.actions[0] if plan.actions else None
            ev_result = evaluator.evaluate(sc, action, plan.thought)

            results.append(SyntheticResult(
                scenario_id=sc.id,
                valid=ev_result["valid"],
                actual=ev_result["actual"],
                expected=sc.expected_action_type,
                progress=ev_result["progress"],
                unsafe=ev_result["unsafe"],
                thought=ev_result["thought"],
                notes=ev_result["notes"],
            ))

        return results

    @staticmethod
    def format_results(results: List[SyntheticResult]) -> str:
        lines = []
        for r in results:
            status = "PASS" if r.valid else "FAIL"
            lines.append(
                f"[{status}] {r.scenario_id}: "
                f"expected={r.expected} actual={r.actual} "
                f"progress={r.progress} unsafe={r.unsafe}"
            )
            if r.notes:
                lines.append(f"  notes: {r.notes}")
        return "\n".join(lines)

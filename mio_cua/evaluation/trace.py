"""Trace recording, failure classification, and replay benchmarking.

Components:
  TraceRecorder      — wraps AgentLoop, captures full Obs→Action→Obs trajectories
  FailureClassifier  — auto-categorizes replay failures (Perception/Planner/Action/Environment)
  ReplayBenchmark    — runs recorded traces through real LLM Planner for comparison

Architecture:
  Real App → TraceRecorder → Trace JSON → ReplayBenchmark → Evaluator
                                                     ↓
                                          FailureClassifier →归因
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from mio_cua.evaluation.recorder import (
    ActionRecord,
    ObsFrame,
    ObservationRecorder,
    PlannerRecord,
    ReplayPerception,
    Trace,
    TraceEntry,
    TraceStore,
)


# ---------------------------------------------------------------------------
# TraceRecorder �� wraps AgentLoop, captures full trajectory
# ---------------------------------------------------------------------------


def build_trace_entries(
    actions: List[ActionRecord],
    effective_obs_by_step: Dict[int, Any],
    raw_obs_by_step: Dict[int, Any],
    plan_by_step: Dict[int, PlannerRecord],
    capture: Callable[[Any, Dict[str, Any]], Any],
) -> List[TraceEntry]:
    """Pair each action with the observation and the plan live at its own step.

    Free function so the pairing can be unit tested without a running agent.

    ``step_counter`` advances on every ``registry.call()`` -- including the
    context check's deterministic ``focus_window`` retries, which emit no plan
    at all. Appending plans in ordinal order and pairing them with
    ``actions[i]`` therefore shifted every plan forward by the number of such
    retries (trace_1790812617: 4 plans vs 6 actions, each plan attached two
    entries too early), so a step's thought was read against another step's
    observation. Key plans by step index instead.
    """
    entries: List[TraceEntry] = []
    for i in range(len(actions)):
        obs_effective = effective_obs_by_step.get(i, raw_obs_by_step.get(i))
        obs_after_effective = effective_obs_by_step.get(i + 1, raw_obs_by_step.get(i + 1))
        obs_raw = raw_obs_by_step.get(i)

        before = capture(obs_effective, {"step": i}) if obs_effective else None
        after = capture(obs_after_effective, {"step": i + 1}) if obs_after_effective else None

        metadata = {}
        if obs_raw is not None and obs_effective is not None:
            raw_nodes = len(getattr(obs_raw, "scene", None) and getattr(obs_raw.scene, "nodes", []) or [])
            eff_nodes = len(getattr(obs_effective, "scene", None) and getattr(obs_effective.scene, "nodes", []) or [])
            if raw_nodes != eff_nodes:
                metadata["observation_discrepancy"] = f"raw={raw_nodes} effective={eff_nodes}"

        entries.append(TraceEntry(
            obs_before=before,
            action=actions[i],
            obs_after=after,
            planner=plan_by_step.get(i),
            metadata=metadata or None,
        ))
    return entries


class TraceRecorder:
    """Wraps Agent and records the full observation → action → result trajectory.

    Intercepts Agent.run() to instrument the loop that gets created inside it.

    Usage:
        agent = Agent(config)
        recorder = TraceRecorder(agent)
        trace = recorder.run(task, metadata={"app": "WeChat"})
        store = TraceStore("./traces")
        store.save(trace)
    """

    def __init__(self, agent):
        self._agent = agent
        self._recorder = ObservationRecorder()

    def run(self, task: Any, metadata: Optional[Dict[str, Any]] = None) -> Trace:
        """Run a task and record the full trace.

        Intercepts the Agent's internal loop creation to instrument
        observe(), call(), and plan() for recording.
        """
        actions: List[ActionRecord] = []
        planner_records: List[PlannerRecord] = []
        # Plans are indexed by the step counter at plan time, NOT by their own
        # ordinal. Every registry.call() bumps step_counter -- including the
        # deterministic focus_window retries issued by the context check, which
        # produce no plan at all. Appending plans in order and pairing them with
        # actions[i] therefore shifts every plan two entries ahead (observed on
        # trace_1790812617: 4 plans vs 6 actions, plan i attached to action i
        # instead of action i+2), so a step's thought was read from a different
        # step's observation.
        plan_by_step: Dict[int, PlannerRecord] = {}

        step_counter = [0]

        # Capture the loop right after Agent creates it, before run() starts
        original_agent_run = self._agent.run.__func__

        def _intercepted_run(self_agent, task_arg):
            """Intercepts Agent.run to capture the loop, then instruments it."""
            from mio_cua.agent.loop import AgentLoop
            from mio_cua.runtime.loop import AgentLoopV2

            # Build the loop the same way Agent.run does, but capture references
            from mio_cua.agent.planner import Planner
            from mio_cua.agent.recover import Recover
            from mio_cua.agent.safety import Safety
            from mio_cua.automation.input_controller import InputController
            from mio_cua.memory.artifact import ArtifactStore
            from mio_cua.memory.history import History
            from mio_cua.providers.openai_compat import OpenAICompatProvider
            from mio_cua.prompts import DEFAULT_SYSTEM_PROMPT

            provider = OpenAICompatProvider(
                base_url=self_agent.config.base_url,
                api_key=self_agent.config.api_key(),
                model=self_agent.config.model,
            )
            planner_inst = Planner(provider, DEFAULT_SYSTEM_PROMPT)
            safety = Safety(
                max_steps=self_agent.config.max_steps,
                timeout_s=self_agent.config.task_timeout_s,
                emergency_key=self_agent.config.emergency_key,
            )
            perception_inst = self_agent._perception()
            loop_cls = AgentLoopV2 if getattr(self_agent.config, "runtime_v2", False) else AgentLoop
            loop = loop_cls(
                perception=perception_inst,
                planner=planner_inst,
                registry=self_agent.registry,
                safety=safety,
                events=self_agent.events,
                config=self_agent.config,
                history=History(),
                controller=InputController(),
                artifact_store=ArtifactStore(self_agent.config.artifact_dir),
                state_dir=os.path.join(self_agent.config.artifact_dir, "state"),
                recover=Recover(self_agent._dispatch, perception_inst),
            )

            # Instrument
            orig_observe = perception_inst.observe
            orig_call = self_agent.registry.call
            orig_plan = planner_inst.plan

            # Track raw observations (first call before context check)
            # and effective observations (after context check, seen by Planner)
            raw_obs_by_step: dict = {}
            effective_obs_by_step: dict = {}

            def _tracing_observe():
                # Capture raw observation (before context check)
                obs = orig_observe()
                raw_obs_by_step[step_counter[0]] = obs
                return obs

            def _tracing_call(name, params, ctx):
                result = orig_call(name, params, ctx)
                rec = self._recorder.capture_action(
                    action_id=getattr(ctx, "current_action_id", f"a-{step_counter[0]}"),
                    action_type=name,
                    params=dict(params),
                    result={"sent": getattr(result, "sent", True), "success": getattr(result, "success", True)},
                )
                actions.append(rec)
                step_counter[0] += 1
                return result

            def _tracing_plan(t, obs, diff, tools, history=None, hints=None):
                plan = orig_plan(t, obs, diff, tools, history=history, hints=hints)
                # Capture the observation that Planner actually sees
                # (post-context-check, post-re-observation)
                effective_obs_by_step[step_counter[0]] = obs
                # Capture decision state from Planner's exploration tracker
                decision_state = None
                if hasattr(planner_inst, "exploration_state"):
                    decision_state = planner_inst.exploration_state
                pr = PlannerRecord(
                    prompt=plan.goal[:2000] if hasattr(plan, "goal") else "",
                    llm_response=plan.thought[:1000] if hasattr(plan, "thought") else "",
                    tool_calls_raw=[{"name": a.type, "params": dict(a.params)} for a in plan.actions],
                    parsed_actions=[{"type": a.type, "params": dict(a.params)} for a in plan.actions],
                    decision_state=decision_state,
                )
                planner_records.append(pr)
                # Key by the step the plan will act at, so entry i pairs its
                # own observation with its own thought.
                plan_by_step[step_counter[0]] = pr
                return plan

            perception_inst.observe = _tracing_observe
            self_agent.registry.call = _tracing_call
            planner_inst.plan = _tracing_plan

            try:
                result = loop.run(task_arg)
            finally:
                perception_inst.observe = orig_observe
                self_agent.registry.call = orig_call
                planner_inst.plan = orig_plan

            # Build entries inside _intercepted_run where dicts are accessible
            built_entries = build_trace_entries(
                actions=actions,
                effective_obs_by_step=effective_obs_by_step,
                raw_obs_by_step=raw_obs_by_step,
                plan_by_step=plan_by_step,
                capture=self._recorder.capture,
            )

            # Store entries on recorder for outer scope access
            self._built_entries = built_entries
            return result

        # Bind the intercepted run
        import types
        self._agent.run = types.MethodType(_intercepted_run, self._agent)

        try:
            result = self._agent.run(task)
        finally:
            # Restore original run
            self._agent.run = types.MethodType(original_agent_run, self._agent)

        entries = getattr(self, "_built_entries", [])

        return Trace(
            trace_id=f"trace_{int(time.time())}",
            created_at=time.time(),
            task={
                "instruction": getattr(task, "instruction", ""),
                "target_context": getattr(task, "target_context", {}),
                "metadata": getattr(task, "metadata", {}),
            },
            entries=entries,
            metadata={
                **(metadata or {}),
                "steps": step_counter[0],
                "final_status": getattr(result, "status", "unknown"),
                "final_summary": getattr(result, "summary", "")[:200],
            },
        )


# ---------------------------------------------------------------------------
# FailureClassifier — auto-categorizes replay failures
# ---------------------------------------------------------------------------

class FailureClassifier:
    """Classifies why a replay/test failed into one of four categories:

      Perception Error  — target not in scene graph (Perception missed it)
      Planner Error     — target exists but LLM chose wrong action
      Action Error      — action correct but execution failed
      Environment Error — window state changed / app behavior changed
    """

    PERCEPTION = "perception_error"
    PLANNER = "planner_error"
    ACTION = "action_error"
    ENVIRONMENT = "environment_error"
    UNKNOWN = "unknown"

    # Chinese/English window name aliases for context matching
    WINDOW_ALIASES = {
        "wechat": ["微信", "weixin", "weixin.exe"],
        "chrome": ["谷歌浏览器", "google chrome", "chrome.exe"],
        "vscode": ["visual studio code", "vs code", "code.exe"],
    }

    def _context_matches(self, active_window: str, goal_app: str,
                         active_process: Optional[str] = None) -> bool:
        """Fuzzy context matching: handles Chinese/English window names.

        Matches the foreground's PROCESS too: a browser window's title is the
        page it shows ("MIO·HUB — 任务总线") and never contains the app name,
        so title-only comparison would mis-attribute a correctly focused
        browser as an environment error.
        """
        if active_process:
            from mio_cua.automation.windows import matches_target
            if matches_target(goal_app, active_window, active_process):
                return True

        aw = active_window.lower().strip()
        ga = goal_app.lower().strip()

        if ga in aw or aw in ga:
            return True

        for key, aliases in self.WINDOW_ALIASES.items():
            if ga == key or ga in aliases:
                if any(a in aw for a in aliases) or key in aw:
                    return True
            if aw == key or aw in aliases:
                if any(a in ga for a in aliases) or key in ga:
                    return True

        return False

    def classify(
        self,
        observation: ObsFrame,
        action: Optional[ActionRecord],
        goal_keyword: str,
        goal_app: str,
        action_success: bool = True,
        context_matches: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Classify a single step's failure using evidence chain.

        Priority order (先判断信息是否充分，再判断决策):
          1. Observation 是否包含足够信息？
             - context mismatch → Environment Error
             - target not visible → check alternatives + affordances
          2. Action 是否符合 Observation + Goal？
             - wrong click / no action → Planner Error
          3. Action 执行是否达到预期？
             - failed → Action Error

        Returns:
            {"category": str, "detail": str, "confidence": float}
        """
        if observation is None:
            return {
                "category": self.PERCEPTION,
                "detail": "No observation available for this step",
                "confidence": 0.5,
            }

        if context_matches is None:
            context_matches = self._context_matches(
                observation.active_window, goal_app,
                getattr(observation, "active_process", None))

        target_in_obs = self._target_in_observation(observation, goal_keyword)
        has_search_box = self._has_search_box(observation)
        visible_clickable = self._visible_clickable_candidates(observation, goal_keyword)

        # ── Layer 1: Observation 是否包含足够信息 ──

        if not context_matches:
            return {
                "category": self.ENVIRONMENT,
                "detail": f"active_window={observation.active_window!r} "
                          f"(process={getattr(observation, 'active_process', None)!r}), "
                          f"expected={goal_app!r} — Observation 缺少目标应用上下文",
                "confidence": 0.9,
            }

        if not target_in_obs:
            # Target not visible: 有候选 → Planner 选错；无候选 → 检查探索 affordance
            has_alternatives = len(visible_clickable) > 0
            has_exploration = has_search_box or self._has_scrollbar(observation)
            few_alternatives = len(visible_clickable) <= 1

            # 缺少探索 affordance 且候选不足 → Perception (信息不够)
            if not has_exploration and few_alternatives:
                if action and action.type in ("scroll", "search"):
                    return {
                        "category": None,
                        "detail": f"target not visible, agent correctly attempting exploration",
                        "confidence": 0.0,
                    }
                return {
                    "category": self.PERCEPTION,
                    "detail": f"target '{goal_keyword}' not visible, only {len(visible_clickable)} "
                              f"candidate(s), no search/scroll — Perception 缺少探索 affordance",
                    "confidence": 0.9,
                }

            if has_alternatives:
                # 有可点击候选但 Agent 没点对 → Planner 选错了
                if action and action.type in ("click", "select_element"):
                    return {
                        "category": self.PLANNER,
                        "detail": f"target not visible, agent clicked non-matching candidate "
                                  f"{action.params} (available: {visible_clickable})",
                        "confidence": 0.85,
                    }
                # 有候选但没动作
                if action is None:
                    return {
                        "category": self.PLANNER,
                        "detail": f"target not visible, {len(visible_clickable)} candidates available "
                                  f"but no action produced",
                        "confidence": 0.7,
                    }
                # 有候选且用了探索 → OK
                if action and action.type in ("scroll", "search"):
                    return {
                        "category": None,
                        "detail": f"target not visible, agent correctly using exploration",
                        "confidence": 0.0,
                    }

            # 无候选: 检查探索 affordance
            if not has_exploration:
                if action and action.type in ("scroll", "search"):
                    return {
                        "category": None,
                        "detail": f"target not visible, agent correctly attempting exploration",
                        "confidence": 0.0,
                    }
                return {
                    "category": self.PERCEPTION,
                    "detail": f"target '{goal_keyword}' not visible, no search box or scrollbar — "
                              f"Perception 缺少探索 affordance",
                    "confidence": 0.9,
                }

            # 有探索 affordance 但 Agent 没用
            if action and action.type in ("click", "select_element"):
                return {
                    "category": self.PLANNER,
                    "detail": f"target not visible, exploration available (search={has_search_box}), "
                              f"but agent clicked non-matching element",
                    "confidence": 0.9,
                }

            # Anything that actually drives the search box is not "no action".
            # The old catch-all here returned planner_error for every action
            # that was not scroll/search/click, so typing the goal keyword
            # straight into the box was scored as a planner failure
            # (trace_1790812617 step 3: action type "今日新闻" -> planner_error).
            if action and action.type in ("type", "key", "enter", "write", "input"):
                return {
                    "category": None,
                    "detail": f"target not visible yet, agent driving the search box "
                              f"({action.type})",
                    "confidence": 0.0,
                }
            if action and action.type == "focus_window":
                return {
                    "category": self.PLANNER,
                    "detail": f"target not visible but context already matches — "
                              f"re-focusing the same app instead of searching",
                    "confidence": 0.7,
                }
            if action is None:
                return {
                    "category": self.PLANNER,
                    "detail": f"target not visible, exploration available but no action",
                    "confidence": 0.6,
                }
            return {
                "category": None,
                "detail": f"target not visible, agent attempting {action.type}",
                "confidence": 0.0,
            }

        # ── Layer 2: Action 是否符合 Observation + Goal ──

        if action is None:
            return {
                "category": self.PLANNER,
                "detail": f"target visible but no action produced",
                "confidence": 0.8,
            }

        if action.type in ("click", "select_element"):
            clicked_matches = self._click_matches_target(action, observation, goal_keyword)
            if not clicked_matches and self._is_search_submit(action, observation):
                # The submit control's own label never contains the keyword --
                # that lives in the input box beside it. trace_1790812617 step 4
                # typed 今日新闻 then clicked element 104 {"text": "搜索",
                # "semantic": "搜索"} and was scored planner_error @0.95.
                clicked_matches = True
            if not clicked_matches:
                return {
                    "category": self.PLANNER,
                    "detail": f"target visible but clicked non-matching element: {action.params}",
                    "confidence": 0.95,
                }

        if action.type == "search" and not has_search_box:
            return {
                "category": self.PLANNER,
                "detail": f"no search box visible but agent tried search",
                "confidence": 0.8,
            }

        # ── Layer 3: Action 执行是否达到预期 ──

        if not action_success:
            return {
                "category": self.ACTION,
                "detail": f"action {action.type}({action.params}) failed: {action.result}",
                "confidence": 0.85,
            }

        return {
            "category": None,
            "detail": "no failure detected or unclassifiable",
            "confidence": 0.0,
        }

    def classify_trace(self, trace: Trace, goal_keyword: str, goal_app: str) -> List[Dict[str, Any]]:
        """Classify each step in a trace."""
        results = []
        for entry in trace.entries:
            result = self.classify(
                observation=entry.obs_before,
                action=entry.action,
                goal_keyword=goal_keyword,
                goal_app=goal_app,
                action_success=entry.action.result.get("success", True) if entry.action and entry.action.result else True,
            )
            results.append(result)
        return results

    def summary(self, classifications: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate classification results into a summary."""
        counts = {}
        for c in classifications:
            cat = c.get("category") or "ok"
            counts[cat] = counts.get(cat, 0) + 1
        total = len(classifications)
        return {
            "total_steps": total,
            "category_counts": counts,
            "perception_rate": round(counts.get(self.PERCEPTION, 0) / max(total, 1), 3),
            "planner_rate": round(counts.get(self.PLANNER, 0) / max(total, 1), 3),
            "action_rate": round(counts.get(self.ACTION, 0) / max(total, 1), 3),
            "environment_rate": round(counts.get(self.ENVIRONMENT, 0) / max(total, 1), 3),
        }

    def _target_in_observation(self, obs: ObsFrame, keyword: str) -> bool:
        for node in obs.scene_nodes:
            text = (node.get("text") or "").lower()
            if keyword.lower() in text:
                return True
        return False

    def _has_search_box(self, obs: ObsFrame) -> bool:
        for node in obs.scene_nodes:
            semantic = (node.get("semantic") or "").lower()
            text = (node.get("text") or "").lower()
            if "search" in semantic or "搜索" in text:
                return True
        return False

    def _has_scrollbar(self, obs: ObsFrame) -> bool:
        """Heuristic: >3 non-frame nodes suggests scrollable list."""
        non_frame = [n for n in obs.scene_nodes
                     if n.get("type") != "group"
                     and "mmuirendersubwindow" not in (n.get("semantic") or "").lower()]
        return len(non_frame) > 3

    def _visible_clickable_candidates(self, obs: ObsFrame, keyword: str) -> List[str]:
        """Return text of visible clickable items (excluding frame nodes)."""
        candidates = []
        for node in obs.scene_nodes:
            ntype = node.get("type", "")
            if ntype == "group":
                continue
            text = (node.get("text") or "").strip()
            if text and keyword.lower() not in text.lower():
                candidates.append(text)
        return candidates

    # Labels of the control that submits the typed query. Its own text never
    # carries the keyword -- the keyword sits in the input box next to it.
    # Latin labels are matched exactly ("go" would otherwise accept "Google").
    _SUBMIT_LABELS = ("搜索", "搜一下", "查找", "查询")

    def _is_search_submit(self, action: ActionRecord, obs: ObsFrame) -> bool:
        """True when the click lands on the search/submit affordance."""
        eid = action.params.get("element_id")
        if eid is None:
            return False
        for node in obs.scene_nodes:
            if node.get("id") == eid:
                semantic = (node.get("semantic") or "").lower()
                text = (node.get("text") or "").strip().lower()
                if "search" in semantic or "搜索" in semantic:
                    return True
                if not text:
                    return False
                if text == "search":
                    return True
                return any(label in text for label in self._SUBMIT_LABELS)
        return False

    def _click_matches_target(self, action: ActionRecord, obs: ObsFrame, keyword: str) -> bool:
        eid = action.params.get("element_id")
        if eid is None:
            return False
        for node in obs.scene_nodes:
            if node.get("id") == eid:
                text = (node.get("text") or "").lower()
                return keyword.lower() in text
        return False


# ---------------------------------------------------------------------------
# Comparison: Synthetic vs Real Observation
# ---------------------------------------------------------------------------

@dataclass
class ComparisonResult:
    """Result of comparing Synthetic vs Real Observation performance."""
    synthetic_valid_rate: float
    real_valid_rate: float
    gap: float
    diagnosis: str
    synthetic_details: List[Dict[str, Any]] = field(default_factory=list)
    real_details: List[Dict[str, Any]] = field(default_factory=list)


class SyntheticVsRealComparator:
    """Compares Planner performance on Synthetic vs Real Observations.

    If Synthetic fails → Planner capability issue
    If Synthetic passes, Real fails → Observation/Perception expression issue
    """

    def __init__(self, provider, system_prompt: str, tool_defs: list):
        self._provider = provider
        self._system_prompt = system_prompt
        self._tool_defs = tool_defs

    def compare(
        self,
        synthetic_obs_path: str,
        real_obs_path: str,
        goal_keyword: str,
        goal_app: str = "WeChat",
    ) -> ComparisonResult:
        """Run Planner on both synthetic and real observations, compare results."""
        from mio_cua.evaluation.synthetic import SyntheticBenchmark

        bench = SyntheticBenchmark(self._provider, self._system_prompt, self._tool_defs)

        synthetic_results = bench.run(synthetic_obs_path)
        real_results = bench.run(real_obs_path)

        syn_valid = sum(1 for r in synthetic_results if r.valid) / max(len(synthetic_results), 1)
        real_valid = sum(1 for r in real_results if r.valid) / max(len(real_results), 1)
        gap = syn_valid - real_valid

        if syn_valid < 0.5:
            diagnosis = "Planner capability issue: fails on synthetic observations too"
        elif gap > 0.2:
            diagnosis = "Observation/Perception expression issue: synthetic passes but real fails"
        elif real_valid < 0.5:
            diagnosis = "Mixed: both fail, likely Planner + Perception issues"
        else:
            diagnosis = "Healthy: both pass at acceptable rates"

        return ComparisonResult(
            synthetic_valid_rate=round(syn_valid, 3),
            real_valid_rate=round(real_valid, 3),
            gap=round(gap, 3),
            diagnosis=diagnosis,
            synthetic_details=[{"id": r.scenario_id, "valid": r.valid, "actual": r.actual} for r in synthetic_results],
            real_details=[{"id": r.scenario_id, "valid": r.valid, "actual": r.actual} for r in real_results],
        )

"""Failure attribution for Agent Runtime v2 Phase 3 (spec §14-§17).

A *rule-based* (non-LLM) attributor that explains *why* a real desktop task
failed, by walking the recorded event chain and assigning the failure to one
of the four core layers (plus VERIFICATION / UNKNOWN):

    PERCEPTION  — the target existed but Observation never detected it
    PLANNER     — Observation was correct but the Planner chose a wrong action
    ACTION      — the Planner decision was correct but execution failed
    ENVIRONMENT — Planner + Action correct, but the OS/app blocked the operation
    VERIFICATION— the action ran but the success check itself was wrong
    UNKNOWN     — insufficient evidence

Evidence priority (spec §17)
----------------------------
    direct error  >  action result  >  verification  >  observation
    >  planner decision  >  heuristic inference

The attributor never attributes "last exception = root cause". It reconstructs
the chain: Observation -> Plan -> Action -> Verification and reasons about
which layer broke it.
"""

import logging
from typing import Any, Dict, List, Optional

from mio_cua.evaluation.schema import (
    EventType,
    FailureAttribution,
    FailureCandidate,
    FailureCategory,
    PlanSnapshot,
    ObservationSnapshot,
    ActionRecord,
    VerificationRecord,
    Trace,
    TraceEvent,
)

# Chinese/English window-name aliases for fuzzy context matching (spec §16.4).
_WINDOW_ALIASES = {
    "wechat": ["微信", "weixin", "weixin.exe"],
    "chrome": ["谷歌浏览器", "google chrome", "chrome.exe"],
    "vscode": ["visual studio code", "vs code", "code.exe"],
}


def _as_dict(obj: Any) -> Optional[Dict[str, Any]]:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dataclass_fields__"):
        return {k: getattr(obj, k) for k in obj.__dataclass_fields__}
    return {"value": obj}


def _get(obj: Any, key: str, default=None):
    d = _as_dict(obj)
    if d is None:
        return default
    return d.get(key, default)


class FailureAttributor:
    """Assigns a recorded failure to a layer with evidence + confidence."""

    def __init__(self):
        self._window_aliases = _WINDOW_ALIASES

    # -- public API -------------------------------------------------------

    def classify(self, trace: Trace) -> FailureAttribution:
        """Classify the whole trace; returns the most likely attribution."""
        ctx = self._goal_context(trace)
        keyword = ctx.get("keyword", "")
        target_app = ctx.get("app") or ctx.get("window", "")

        # Walk the event chain, maintaining the latest state per layer.
        latest_obs = None
        latest_plan = None
        latest_action = None
        latest_verify = None
        context_matches = True
        failing: Optional[TraceEvent] = None
        failing_kind = None  # "task_failed" | "action" | "verification" | "error"
        error_msg = None

        for ev in trace.events:
            et = ev.event_type
            p = ev.payload or {}
            if et == EventType.TASK_STARTED.value:
                continue
            elif et == EventType.OBSERVATION.value:
                latest_obs = _get(p, "observation")
                aw = _get(latest_obs, "active_window") or ""
                ap = _get(latest_obs, "active_process") or ""
                context_matches = self._context_matches(aw, target_app, ap)
            elif et == EventType.PLAN_CREATED.value:
                latest_plan = _get(p, "plan")
            elif et == EventType.ACTION_COMPLETED.value:
                latest_action = _get(p, "action")
                if not _truthy(_get(latest_action, "success"), default=True):
                    failing = ev
                    failing_kind = "action"
            elif et == EventType.VERIFICATION.value:
                latest_verify = _get(p, "verification")
                if not _truthy(_get(latest_verify, "success"), default=True):
                    failing = ev
                    failing_kind = "verification"
            elif et == EventType.ERROR.value:
                error_msg = _get(p, "error") or _get(p, "message")
                failing = ev
                failing_kind = "error"
            elif et in (EventType.TASK_FAILED.value, EventType.TASK_COMPLETED.value):
                status = str(_get(p, "status") or "").upper()
                if et == EventType.TASK_FAILED.value or status == "FAIL":
                    failing = ev
                    failing_kind = "task_failed"

        if failing is None:
            # No failure signal -> task likely succeeded.
            return FailureAttribution(
                category=FailureCategory.UNKNOWN.value,
                confidence=0.0,
                reason="no failure signal found in trace (task may have succeeded)",
                evidence=["no TASK_FAILED / error / failed action / failed verification event"],
            )

        return self._attribute(
            kind=failing_kind,
            step=failing.step,
            event_id=failing.event_id,
            obs=latest_obs,
            plan=latest_plan,
            action=latest_action,
            verify=latest_verify,
            context_matches=context_matches,
            error_msg=error_msg,
            keyword=keyword,
            target_app=target_app,
        )

    def _goal_context(self, trace: Trace) -> Dict[str, Any]:
        """Extract {keyword, app, window} from the trace's target_context."""
        meta = getattr(trace, "metadata", None) or {}
        tctx = meta.get("target_context") if isinstance(meta, dict) else None
        if not isinstance(tctx, dict):
            return {}
        return {
            "keyword": tctx.get("keyword", ""),
            "app": tctx.get("app", ""),
            "window": tctx.get("window", ""),
        }

    # -- core decision ------------------------------------------------

    def _attribute(self, kind, step, event_id, obs, plan, action, verify,
                   context_matches, error_msg, keyword, target_app) -> FailureAttribution:
        obs_d = _as_dict(obs) or {}
        plan_d = _as_dict(plan) or {}
        action_d = _as_dict(action) or {}
        verify_d = _as_dict(verify) or {}

        search_box = self._has_search_box(obs_d)
        target_visible = self._target_visible(obs_d, keyword)
        plan_action = (plan_d.get("action_type") or "").lower()
        plan_target = plan_d.get("target")
        action_tool = (action_d.get("tool") or "").lower()
        action_success = _truthy(action_d.get("success"), default=True)
        action_error = action_d.get("error")

        candidates: List[FailureCandidate] = []

        # Rule 0: direct error — decide by message (spec §17 priority top).
        if kind == "error" and error_msg:
            cat, conf, reason = self._attribute_error(error_msg, context_matches, search_box)
            return FailureAttribution(
                category=cat, confidence=conf, step=step, event_id=event_id,
                reason=reason, evidence=[f"error: {error_msg}"],
                candidates=[FailureCandidate(cat, conf, reason)],
            )

        # Rule 1: action executed but failed -> ACTION (spec §16.3).
        if kind == "action" or (action and not action_success):
            reason = f"Planner decided '{plan_action or action_tool}', but execution failed"
            if action_error:
                reason += f": {action_error}"
            candidates.append(FailureCandidate(FailureCategory.ACTION.value, 0.9, reason))
            return FailureAttribution(
                category=FailureCategory.ACTION.value, confidence=0.9,
                step=step, event_id=event_id, reason=reason,
                evidence=[f"action {action_tool or plan_action} failed",
                          f"error={action_error}",
                          f"plan was correct (planner chose '{plan_action}')"],
                candidates=candidates,
            )

        # Rule 2: verification failed (action ran, state unchanged).
        if kind == "verification" or (verify and not _truthy(verify_d.get("success"), default=True)):
            # ENVIRONMENT: context lost (window/focus) — spec §16.4.
            if not context_matches:
                reason = (f"Action succeeded but context lost "
                          f"(active window != target '{target_app}') — environment blocked operation")
                return FailureAttribution(
                    category=FailureCategory.ENVIRONMENT.value, confidence=0.9,
                    step=step, event_id=event_id, reason=reason,
                    evidence=[f"context_matches=False (target_app={target_app})",
                              f"action succeeded but verification failed",
                              "ENVIRONMENT: window focus / app state changed"],
                    candidates=[FailureCandidate(FailureCategory.ENVIRONMENT.value, 0.9, reason)],
                )
            # Observation had the target but verification still failed.
            if target_visible:
                # Planner + Action correct, yet state did not change while context held.
                reason = ("Target was visible and action succeeded, but verification failed "
                          "while context held — likely environment (app state) or a wrong check")
                cat = FailureCategory.ENVIRONMENT.value
                # If the check itself is implausible, it is a VERIFICATION error.
                obs_state = verify_d.get("observed_state")
                if obs_state is not None and str(obs_state) != "":
                    cat = FailureCategory.VERIFICATION.value
                    reason = ("Verification reported failure though target was visible and "
                              "action succeeded — the success check is likely incorrect")
                return FailureAttribution(
                    category=cat, confidence=0.8, step=step, event_id=event_id,
                    reason=reason,
                    evidence=[f"target_visible={target_visible}", "action succeeded",
                              f"context_matches={context_matches}", "verification.success=False"],
                    candidates=[FailureCandidate(cat, 0.8, reason)],
                )
            # Target NOT visible at verification time.
            if plan_action in ("search", "scroll") and search_box:
                # Correct exploration chosen, but still no target -> Perception gap.
                reason = ("Planner correctly chose exploration (search/scroll) but the target "
                          "remained undetected — Perception did not surface it")
                return FailureAttribution(
                    category=FailureCategory.PERCEPTION.value, confidence=0.85,
                    step=step, event_id=event_id, reason=reason,
                    evidence=[f"search_box_present={search_box}", f"target_visible={target_visible}",
                              f"planner action={plan_action} (correct)"],
                    candidates=[FailureCandidate(FailureCategory.PERCEPTION.value, 0.85, reason)],
                )
            if plan_action in ("click", "select_element", "type") and plan_target:
                # Planner clicked a non-matching target -> Planner error.
                if not self._target_matches(plan_target, keyword):
                    reason = (f"Planner clicked non-matching target '{plan_target}' "
                              f"though target '{keyword}' was the goal")
                    return FailureAttribution(
                        category=FailureCategory.PLANNER.value, confidence=0.9,
                        step=step, event_id=event_id, reason=reason,
                        evidence=[f"plan target='{plan_target}'", f"goal='{keyword}'",
                                  "target not visible; planner chose wrong element"],
                        candidates=[FailureCandidate(FailureCategory.PLANNER.value, 0.9, reason)],
                    )
            # Default for "target not visible, no clear planner mistake".
            reason = ("Target not visible and no matching element found — Perception did not "
                      "provide enough information (missing affordances / sparse scene)")
            return FailureAttribution(
                category=FailureCategory.PERCEPTION.value, confidence=0.8,
                step=step, event_id=event_id, reason=reason,
                evidence=[f"target_visible={target_visible}", f"search_box_present={search_box}",
                          "Observation insufficient to locate target"],
                candidates=[FailureCandidate(FailureCategory.PERCEPTION.value, 0.8, reason)],
            )

        # Rule 3: task failed without action/verification failure — inspect plan vs obs.
        # Search box present but Planner chose a wrong target -> Planner (spec §16.2).
        if search_box and plan_action in ("click", "select_element", "type") and plan_target:
            if not self._target_matches(plan_target, keyword):
                reason = (f"Observation was correct (search box present) but Planner chose "
                          f"'{plan_target}' instead of the visible search/target for '{keyword}'")
                return FailureAttribution(
                    category=FailureCategory.PLANNER.value, confidence=0.9,
                    step=step, event_id=event_id, reason=reason,
                    evidence=[f"search_box_present={search_box}",
                              f"planner target='{plan_target}' (non-matching)",
                              f"goal='{keyword}'"],
                    candidates=[FailureCandidate(FailureCategory.PLANNER.value, 0.9, reason)],
                )

        # Rule 4: observation insufficient (no search box, target not visible).
        if not target_visible and not search_box:
            reason = ("Observation never detected the target and exposed no search affordance — "
                      "Perception gap")
            return FailureAttribution(
                category=FailureCategory.PERCEPTION.value, confidence=0.85,
                step=step, event_id=event_id, reason=reason,
                evidence=[f"target_visible={target_visible}", f"search_box_present={search_box}"],
                candidates=[FailureCandidate(FailureCategory.PERCEPTION.value, 0.85, reason)],
            )

        # Fallback: unknown.
        return FailureAttribution(
            category=FailureCategory.UNKNOWN.value, confidence=0.3,
            step=step, event_id=event_id,
            reason="could not confidently attribute failure from available events",
            evidence=[f"kind={kind}", f"context_matches={context_matches}",
                      f"target_visible={target_visible}", f"search_box={search_box}"],
            candidates=candidates,
        )

    # -- helpers ---------------------------------------------------------

    def _attribute_error(self, msg: str, context_matches: bool, search_box: bool):
        m = (msg or "").lower()
        env_hints = ["focus", "window", "permission", "denied", "blocked", "timeout",
                     "not foreground", "lost focus", "最小化", "被遮挡", "卡死", "权限"]
        action_hints = ["click", "element not found", "invalid coordinates", "not clickable",
                        "超时", "点击失败", "元素未找到"]
        percept_hints = ["ocr", "no element", "empty scene", "detect", "识别", "找不到"]
        if any(h in m for h in env_hints):
            return FailureCategory.ENVIRONMENT.value, 0.85, f"error indicates environment issue: {msg}"
        if any(h in m for h in action_hints):
            return FailureCategory.ACTION.value, 0.8, f"error indicates action execution failure: {msg}"
        if any(h in m for h in percept_hints):
            return FailureCategory.PERCEPTION.value, 0.8, f"error indicates perception gap: {msg}"
        return FailureCategory.UNKNOWN.value, 0.4, f"unclassified error: {msg}"

    def _context_matches(self, active_window: str, goal_app: str,
                         active_process: str = "") -> bool:
        aw = (active_window or "").lower().strip()
        ga = (goal_app or "").lower().strip()
        if not ga:
            return True
        if ga in aw or aw in ga:
            return True
        for key, aliases in self._window_aliases.items():
            if ga == key or ga in aliases:
                if any(a in aw for a in aliases) or key in aw:
                    return True
            if aw == key or aw in aliases:
                if any(a in ga for a in aliases) or key in ga:
                    return True
        # Title rules did not match. The owning process is the only identity a
        # page title cannot hide -- an Edge window showing the taskhub page is
        # titled "MIO·HUB — 任务总线", which no alias list will ever accept, so
        # without this the run is mis-attributed to environment_error.
        if active_process:
            from mio_cua.automation.windows import matches_target
            if matches_target(goal_app, active_window, active_process):
                return True
        return False

    def _target_visible(self, obs_d: Dict[str, Any], keyword: str) -> bool:
        nodes = (obs_d.get("scene") or {}).get("nodes") if isinstance(obs_d.get("scene"), dict) else None
        if not nodes:
            # Fallback: known_entities / visible text in metadata.
            texts = [str(t) for t in (obs_d.get("visible_texts") or [])]
            nodes = []
        else:
            texts = [str(n.get("text") or "") for n in nodes]
        if not keyword:
            return False
        kw = keyword.lower()
        return any(kw in t.lower() for t in texts)

    def _has_search_box(self, obs_d: Dict[str, Any]) -> bool:
        nodes = (obs_d.get("scene") or {}).get("nodes") if isinstance(obs_d.get("scene"), dict) else None
        if not nodes:
            return False
        for n in nodes:
            sem = (n.get("semantic") or "").lower()
            text = (n.get("text") or "")
            if "search" in sem or "搜索" in text or "searchbox" in sem:
                return True
        return False

    def _target_matches(self, target: Any, keyword: str) -> bool:
        if target is None or not keyword:
            return False
        t = str(target).lower()
        kw = keyword.lower()
        if kw in t:
            return True
        # element id references (e.g. "element_id=3") are not keyword matches
        return False


def _truthy(v, default=True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "success")
    return bool(v)

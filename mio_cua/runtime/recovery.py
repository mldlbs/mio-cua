"""Recovery Manager for Agent Runtime v2.

Recovery is a *policy library*, not scattered if-else in the loop. Each failure
mode maps to a policy that yields structured guidance (hints for the Planner,
and optionally an immediate action such as re-focusing the target window).

    Failure modes:
      - context_mismatch  : active window != target (e.g. drifted to OpenCode)
      - focus_lost        : same as above, detected post-action
      - target_invisible  : goal keyword not on screen; must scroll/search
      - scroll_no_progress: scrolling no longer reveals new candidates
      - action_no_effect  : last action changed nothing
      - timeout           : task about to exceed budget

The loop asks the RecoveryManager what to do; it does not hard-code the
response. This keeps recovery extensible (add a policy, not a branch).
"""

from typing import List, Optional

from mio_cua.runtime.belief import BeliefState
from mio_cua.runtime.observation import RuntimeObservation


class RecoveryManager:
    def __init__(self, registry=None, controller=None, perception=None, events=None, enabled=True):
        self.registry = registry
        self.controller = controller
        self.perception = perception
        self.events = events
        self.enabled = enabled

    def focus_target(self, target_app: str, ctx) -> bool:
        """Immediately re-focus the target window. Returns success."""
        if not self.enabled:
            return False
        if not target_app or ctx is None:
            return False
        try:
            self.registry.call("focus_window", {"title": target_app}, ctx)
            return True
        except Exception:
            return False

    def policy_for(
        self, failure: str, belief: BeliefState, robs: RuntimeObservation
    ) -> List[str]:
        if not self.enabled:
            return []
        hints: List[str] = []
        kw = belief.target_context.get("keyword", "?")
        search_available = any(a.kind == "search" for a in robs.affordances)

        if failure in ("context_mismatch", "focus_lost"):
            hints.append(
                f"CONTEXT LOST: the active window is not the target app. "
                f"Re-focus the target window before any other action."
            )
        elif failure == "target_invisible":
            if search_available:
                hints.append(
                    f"TARGET NOT VISIBLE: '{kw}' is not on screen. "
                    f"Use the search box (type the keyword, press enter) or scroll to find it — "
                    f"do NOT click on unrelated items."
                )
            else:
                hints.append(
                    f"TARGET NOT VISIBLE: '{kw}' is not on screen. "
                    f"Scroll the list to reveal it — do NOT click on unrelated items."
                )
        elif failure == "scroll_no_progress":
            if belief.scroll_stall >= 2:
                if search_available:
                    hints.append(
                        f"SCROLL STALLED after multiple attempts: scrolling is not revealing "
                        f"new candidates. Switch strategy — use search for '{kw}' instead of scrolling."
                    )
                else:
                    hints.append(
                        f"SCROLL STALLED: reverse scroll direction or the target may not be reachable "
                        f"by scrolling. Try the opposite direction once more, then stop."
                    )
            else:
                hints.append(
                    f"SCROLL STALLED: the last scroll revealed no new candidates. "
                    f"Reverse the scroll direction to find '{kw}'."
                )
        elif failure == "action_no_effect":
            hints.append(
                "The last action had no visible effect. Do NOT repeat it — pick a different action."
            )
        elif failure == "timeout":
            hints.append(
                f"The task is close to timing out. Take the most direct path: "
                f"if search is available, use it for '{kw}'; otherwise make one decisive attempt."
            )
        return hints

    def recover_actions(self, failure: str, belief: BeliefState, robs: RuntimeObservation):
        """Deterministic recovery: return concrete (action_type, params) tuples to
        execute *before* replanning -- no LLM involved.

        This is the de-modeling half of recovery: for well-known failure modes we
        do not ask the model to "think again", we just act. Returns ``[]`` when the
        failure has no safe deterministic fix (the loop keeps the planner hints
        from ``policy_for`` instead).
        """
        if not self.enabled:
            return []
        target_app = belief.target_context.get("app") or belief.target_context.get("window", "")
        search_available = any(a.kind == "search" for a in robs.affordances)

        if failure == "context_menu":
            return [("key", {"keys": "esc"})]
        if failure in ("focus_lost", "context_mismatch"):
            if target_app:
                return [("focus_window", {"title": target_app})]
            return []
        if failure == "target_invisible":
            # Reveal the target by scrolling the list into view.
            return [("scroll", {"direction": "down", "amount": 3})]
        if failure == "scroll_no_progress":
            # Reverse direction once; if it has stalled repeatedly and search is
            # available, leave it to the planner (we cannot click a search box
            # deterministically without its id).
            if belief.scroll_stall >= 2 and search_available:
                return []
            return [("scroll", {"direction": "up", "amount": 2})]
        # action_no_effect / timeout: nothing safe to do without the planner.
        return []

    def apply_recovery(self, failure: str, belief: BeliefState, robs: RuntimeObservation, ctx) -> bool:
        """Execute the deterministic recovery actions for ``failure``.

        Returns True if at least one action was executed. Exceptions are swallowed
        so a failed recovery never crashes the loop (the planner still gets the
        hints from ``policy_for`` as a fallback).
        """
        if self.registry is None or ctx is None:
            return False
        acted = False
        for action_type, params in self.recover_actions(failure, belief, robs):
            try:
                self.registry.call(action_type, params, ctx)
                acted = True
            except Exception:
                continue
        return acted


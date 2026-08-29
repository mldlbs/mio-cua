"""Progress Evaluator for Agent Runtime v2.

Every Goal gets a notion of progress. After an action we compare the
before/after RuntimeObservation and classify the effect as:

    - "progress"    : the world moved toward the goal
    - "no_change"   : the action had no observable effect
    - "regression"  : the world moved away from the goal

This is the "Progress Model" requirement: stop looping
``scroll -> scroll -> scroll -> timeout`` and instead detect "no change" and
force a strategy switch. The scroll-specific check compares the candidate
set (sidebar items) before and after; if unchanged, it is a stall.
"""

from typing import Optional

from mio_cua.runtime.observation import RuntimeObservation


class ProgressEvaluator:
    def evaluate(
        self,
        action_type: str,
        before: Optional[RuntimeObservation],
        after: RuntimeObservation,
    ) -> str:
        if before is None:
            return "progress"
        if action_type == "scroll":
            if set(after.candidates) == set(before.candidates) and set(
                after.visible_texts
            ) == set(before.visible_texts):
                return "no_change"
            return "progress"
        # Non-scroll actions: a change in visible texts indicates an effect.
        if set(after.visible_texts) == set(before.visible_texts):
            return "no_change"
        return "progress"

    def scroll_stalled(self, before: Optional[RuntimeObservation], after: RuntimeObservation) -> bool:
        return self.evaluate("scroll", before, after) == "no_change"

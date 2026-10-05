"""Belief / State Manager for Agent Runtime v2.

The agent maintains a BeliefState across steps so it does not re-interpret the
world from scratch every turn. It tracks:

    - context (active window) and whether it matches the target
    - target_visible (is the goal keyword currently on screen)
    - seen_candidates (what chat/list items we have already observed)
    - scroll state (last direction, stall count) for progress-aware scrolling
    - focus (current focus)

This is the "Agent must maintain Belief State" requirement: the agent carries
memory of what it has seen and done, instead of acting like every step is the
first time it sees WeChat.
"""

from typing import Optional

from mio_cua.runtime.observation import RuntimeObservation


class BeliefState:
    def __init__(self, target_context: Optional[dict] = None):
        self.target_context = target_context or {}
        self.context: Optional[str] = None
        self.focus: Optional[str] = None
        self.target_visible: bool = False
        self.seen_candidates: set = set()
        self.last_action_type: Optional[str] = None
        self.last_progress: Optional[bool] = None
        self.scroll_direction: Optional[str] = None
        self.scroll_stall: int = 0

    def update(self, robs: RuntimeObservation) -> None:
        self.context = robs.context
        self.focus = robs.focus
        self.target_visible = robs.target_visible
        new_cands = set(robs.candidates)
        progressed = bool(new_cands - self.seen_candidates)
        # New candidates reveal previously unseen items -> forward progress.
        if progressed:
            self.scroll_stall = 0
        self.seen_candidates |= new_cands
        self.last_progress = progressed

    @property
    def context_matches(self) -> bool:
        target = (self.target_context or {}).get("app") or (self.target_context or {}).get(
            "window", ""
        )
        if not target:
            return True
        return target.lower() in (self.context or "").lower()

    def register_scroll(self, direction: str, progressed: bool) -> None:
        """Record the outcome of a scroll so the next scroll can adapt."""
        self.scroll_direction = direction
        self.last_progress = progressed
        if progressed:
            self.scroll_stall = 0
        else:
            self.scroll_stall += 1

    def next_scroll_direction(self) -> str:
        """Escape a stall by reversing; otherwise keep the current direction."""
        if self.scroll_stall >= 1:
            return "up" if self.scroll_direction == "down" else "down"
        return self.scroll_direction or "down"

    def unseen_candidates(self, robs: RuntimeObservation) -> list:
        return [c for c in robs.candidates if c not in self.seen_candidates]

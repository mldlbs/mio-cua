"""Extraction: Goal definition and state model only.

The actual execution (click, scroll, OCR, clipboard, scene graph analysis)
is handled by AgentLoop via Agent.run(task). This module only defines:
- What the Goal is
- What state the Goal produces
- How to construct the Task instruction for the Agent

App is Runtime context only; no app branching.
"""

from dataclasses import dataclass
from typing import List
from mio_cua.workflow.state import Candidate, Record, WorkflowState


@dataclass
class ExtractionGoal:
    """Goal: extract messages from selected candidates within time range.

    This is a state model, not an execution plan.
    The AgentLoop decides HOW to achieve this goal based on observation.
    """
    app: str
    candidates: List[Candidate]
    time_range_days: int = 7

    def to_task_instruction(self) -> str:
        names = ", ".join(c.name for c in self.candidates)
        return (
            f"Extract messages from these {self.app} groups: {names}. "
            f"For each group: click it, locate the message list area, "
            f"scroll to find messages from the past {self.time_range_days} days, "
            f"and collect all message text. "
            f"Use observe to see the screen, then plan your actions. "
            f"When done, call success with the collected messages as structured data."
        )

    def to_hints(self) -> List[str]:
        return [
            f"GOAL: extract messages from selected {self.app} groups",
            f"TIME RANGE: past {self.time_range_days} days",
            "For each group:",
            "  1. Click the group name in the sidebar",
            "  2. Observe the message list area (right side of window)",
            "  3. Identify message elements: look for timestamps like 'YYYY-MM-DD HH:MM' or 'HH:MM'",
            "  4. Messages are text elements in the right-side message area, NOT in the input box",
            "  5. Scroll up to see older messages, stop when timestamps older than target date appear",
            "  6. Collect all visible message text",
            "Verify: each group's message area was located and timestamps prove time coverage",
            "If message area not found, try clicking the group again or scroll to reset view",
        ]

    def verify(self, records: List[Record]) -> bool:
        """Verify: at least some records extracted."""
        return len(records) > 0

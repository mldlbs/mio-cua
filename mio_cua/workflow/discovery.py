"""Discovery: Goal definition and state model only.

The actual execution (focus, scroll, OCR, scene graph analysis) is handled
by AgentLoop via Agent.run(task). This module only defines:
- What the Goal is
- What state the Goal produces
- How to construct the Task instruction for the Agent

App is Runtime context only; no app branching.
"""

from dataclasses import dataclass
from typing import List
from mio_cua.workflow.state import Candidate


@dataclass
class DiscoveryGoal:
    """Goal: find all candidates matching keyword in app's list.

    This is a state model, not an execution plan.
    The AgentLoop decides HOW to achieve this goal based on observation.
    """
    app: str
    keyword: str
    max_candidates: int = 20

    def to_task_instruction(self) -> str:
        return (
            f"Find all items named '{self.keyword}' in the {self.app} sidebar list. "
            f"Scroll through the list to discover up to {self.max_candidates} candidates. "
            f"For each candidate found, call success with the list of candidate names and their positions."
        )

    def to_hints(self) -> List[str]:
        return [
            f"GOAL: discover all '{self.keyword}' items in {self.app} sidebar",
            "Use observe to see the current screen state",
            "Scroll the sidebar list to find more candidates",
            "Report each candidate found with its name and bbox position",
            "When no more candidates appear after scrolling, call success with the complete list",
        ]

    def verify(self, candidates: List[Candidate]) -> bool:
        """Verify: at least one candidate found."""
        return len(candidates) > 0

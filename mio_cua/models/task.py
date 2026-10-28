from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Task:
    instruction: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    attachments: List[str] = field(default_factory=list)
    target_context: Dict[str, Any] = field(default_factory=dict)
    # target_context: {app?: str, window?: str, scene?: str}
    # AgentLoop checks: target_context ⊆ observation.context before planning.
    # If mismatch, agent focuses target window, re-observes, verifies, then proceeds.

    @property
    def keyword(self) -> str:
        """The target keyword, wherever the caller put it.

        The two loops used to disagree: v1 read ``metadata["keyword"]`` while v2
        (and the recorder/replay side) read ``target_context["keyword"]``. A task
        that stored it in the "wrong" dict silently disabled the other loop's
        target-visibility guard -- the safety invariant must not depend on which
        dict carries the keyword. ``target_context`` wins when both are set.
        """
        return task_keyword(self)


def task_keyword(task) -> str:
    """Read the target keyword from either dict, for real and duck-typed tasks.

    Kept dict-based on purpose: a ``Task.keyword`` property that called this via
    ``getattr(task, "keyword")`` would recurse, and tests/examples pass stand-in
    objects that only carry ``target_context`` / ``metadata``.
    """
    tc = getattr(task, "target_context", None) or {}
    md = getattr(task, "metadata", None) or {}
    if isinstance(tc, dict):
        kw = tc.get("keyword") or ""
        if kw:
            return kw
    if isinstance(md, dict):
        return md.get("keyword") or ""
    return ""


@dataclass
class TaskResult:
    status: str  # SUCCESS | FAIL | ABORTED | TIMEOUT
    summary: str = ""
    task_id: str = ""
    steps: int = 0
    duration: float = 0.0
    artifacts: List[str] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)

"""Evaluation Harness for mio-cua Agent Runtime.

This is the first milestone of Agent Runtime v2: a measuring stick before
any runtime change, so every later improvement is provably measured.

Pipeline:

    Task Dataset -> Agent Run -> Trajectory -> Evaluator -> Metrics

The harness does NOT modify AgentLoop behavior. It instruments the existing
loop via monkeypatching (trajectory capture + target-visibility violation
counting) so all signals are observational, not heuristic.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkTask:
    """A single benchmark task with acceptance metadata."""

    id: str
    instruction: str
    target_context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    expected: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    difficulty: str = "medium"
    app: str = ""

    def to_task(self):
        from mio_cua.models.task import Task

        return Task(
            instruction=self.instruction,
            metadata=self.metadata,
            target_context=self.target_context,
        )


@dataclass
class TaskDataset:
    """A collection of benchmark tasks loaded from JSON."""

    name: str = ""
    description: str = ""
    tasks: List[BenchmarkTask] = field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "TaskDataset":
        import json

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tasks = [BenchmarkTask(**t) for t in data.get("tasks", [])]
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            tasks=tasks,
        )

    def filter(
        self,
        app: Optional[str] = None,
        tags: Optional[List[str]] = None,
        ids: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[BenchmarkTask]:
        out = self.tasks
        if app:
            out = [t for t in out if t.app == app or t.target_context.get("app") == app]
        if tags:
            out = [t for t in out if any(tag in t.tags for tag in tags)]
        if ids:
            wanted = set(ids)
            out = [t for t in out if t.id in wanted]
        if limit is not None:
            out = out[:limit]
        return out

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Action:
    id: str
    type: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    thought: str = ""
    goal: str = ""
    actions: List[Action] = field(default_factory=list)

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class RawResult:
    sent: bool
    error: Optional[str] = None


@dataclass
class ActionResult:
    action_id: str
    success: bool
    message: str = ""
    observation_changed: bool = False
    retryable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

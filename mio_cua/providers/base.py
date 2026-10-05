from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LLMResponse:
    message: str = ""
    tool_calls: List = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)
    finish_reason: Optional[str] = None


class Provider:
    def generate(self, messages: List[dict], tools: Optional[List[dict]] = None) -> LLMResponse:
        raise NotImplementedError

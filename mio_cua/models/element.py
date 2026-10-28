from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Element:
    id: int
    source: str  # "ocr" | "uia" | "merged"
    text: str = ""
    role: str = "unknown"
    bbox: tuple = (0, 0, 0, 0)  # (left, top, width, height)
    confidence: float = 1.0
    enabled: bool = True
    visible: bool = True
    focused: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

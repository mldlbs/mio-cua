"""Scene Graph core data structures.

A SceneGraph is the runtime's primary perception output: detected objects,
their spatial relations and the affordances the agent can perform, all in one
graph. OCR and UIA are fused into Nodes; relations and affordances are built by
the perception layer, not guessed by the LLM.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

Rect = Tuple[int, int, int, int]  # (left, top, width, height)


@dataclass
class SceneNode:
    """A detectable UI object (button, input, text, icon, ...)."""

    id: int
    type: str  # "button" | "text" | "input" | "icon" | "group" | ...
    bbox: Rect
    text: str = ""
    confidence: float = 1.0
    semantic: Optional[str] = None
    state: Dict[str, bool] = field(default_factory=dict)
    source: str = "ocr"  # "ocr" | "uia" | "merged"
    role: str = "unknown"  # raw UIA control type when available
    metadata: Dict[str, Any] = field(default_factory=dict)

    def center(self) -> Tuple[int, int]:
        left, top, width, height = self.bbox
        return (left + width // 2, top + height // 2)


@dataclass
class Relation:
    """Spatial / semantic relation between two nodes (graph, not tree)."""

    source: int  # node id
    target: int  # node id
    kind: str  # parent/child/leftOf/rightOf/above/below/near/labelFor/overlap
    weight: float = 1.0


@dataclass
class Affordance:
    """A concrete action the agent can take on a node.

    ``expected`` optionally describes the observable change the action should
    produce (e.g. a display value), so the loop can verify success instead of
    assuming it.
    """

    node_id: int
    action: str  # "click" | "type" | "press" | ...
    params: Dict[str, Any] = field(default_factory=dict)
    expected: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass
class Region:
    """A coarse layout region (navigation, header, body, table, figure...).

    Produced by a layout-analysis model (e.g. rapid_layout) over the active
    window. Regions give the agent the *page structure* before it looks at
    individual nodes -- where the nav bar is, what is body content, etc.
    """

    kind: str  # "text" | "title" | "table" | "figure" | "header" | "footer" | ...
    bbox: Rect
    confidence: float = 1.0
    text: str = ""  # optional, best-effort label from OCR within the region


@dataclass
class SceneGraph:
    """Full perception output: nodes + relations + affordances.

    ``display`` identifies nodes that look like a readout/result area (e.g. the
    calculator display). Diffing those before/after an action lets the loop
    verify success.
    """

    nodes: List[SceneNode] = field(default_factory=list)
    relations: List[Relation] = field(default_factory=list)
    affordances: List[Affordance] = field(default_factory=list)
    display_ids: List[int] = field(default_factory=list)
    regions: List[Region] = field(default_factory=list)
    active_window: str = ""

    def node(self, node_id: int) -> Optional[SceneNode]:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def affordance_for(self, node_id: int, action: str) -> Optional[Affordance]:
        for a in self.affordances:
            if a.node_id == node_id and a.action == action:
                return a
        return None

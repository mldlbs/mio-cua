from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class Change:
    kind: str  # "added" | "removed" | "text_changed" | "moved"
    element_id: Optional[int]
    description: str


@dataclass
class Observation:
    screenshot_path: Optional[str]
    timestamp: float
    active_window: Optional[str]
    dpi_scale: float
    elements: List = field(default_factory=list)
    ui_tree: Optional[str] = None
    scene: Any = None  # SceneGraph (mio_cua.scene.SceneGraph)
    # Owning process of the foreground window (e.g. 'msedge'). Kept last so
    # existing positional construction (screenshot_path..elements) still binds
    # correctly. A window TITLE is the content it shows — an Edge window may be
    # titled "MIO·HUB — 任务总线" and never mention Edge — so the process is the
    # only title-independent identity, and context checks/evaluation both need it.
    active_process: Optional[str] = None


@dataclass
class ObservationDiff:
    prev: Optional[Observation]
    current: Observation
    changes: List[Change] = field(default_factory=list)

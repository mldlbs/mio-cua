"""Structured Observation model for Agent Runtime v2.

The Perception layer still produces the raw ``obs`` (scene graph + active
window + flat elements). ``RuntimeObservation`` is an adapter that derives
the structured sub-views the runtime needs, without the Planner having to
guess from dozens of raw bboxes:

    Observation
    ├── Context           (active window / target match)
    ├── Candidates        (sidebar chat/group names)
    ├── Affordances       (scrollable list region / search box / selectable)
    ├── Scroll State      (scrollable, directions, last effect)
    ├── Focus             (current focus)
    └── Visible State     (all visible texts)

Crucially, this layer *grounds* actions: it computes the scrollable chat-list
region (the bounding box of the candidate items) and the search-box location,
so the runtime can scroll/type **that region** instead of scrolling into the
void at the current mouse position. This is the "Perception must extract
affordances, not let the LLM guess coordinates" requirement.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Affordance:
    """A capability the agent can act on in the current observation."""

    kind: str  # "scroll" | "search" | "select" | "type" | "click"
    target: str = ""
    bbox: Optional[List[int]] = None
    direction: Optional[str] = None  # for scroll
    enabled: bool = True


@dataclass
class ScrollState:
    scrollable: bool = False
    directions: List[str] = field(default_factory=lambda: ["up", "down"])
    last_direction: Optional[str] = None
    last_progress: Optional[bool] = None


@dataclass
class RuntimeObservation:
    raw: Any
    context: str = ""
    active_process: str = ""
    target_context: Dict[str, Any] = field(default_factory=dict)
    candidates: List[str] = field(default_factory=list)
    affordances: List[Affordance] = field(default_factory=list)
    scroll: ScrollState = field(default_factory=ScrollState)
    focus: Optional[str] = None
    visible_texts: List[str] = field(default_factory=list)
    obs_id: str = ""
    # Grounded regions (bbox) so actions can target the right place:
    chat_list_region: Optional[List[int]] = None
    search_box: Optional[Affordance] = None
    window_bbox: Optional[List[int]] = None

    @property
    def target_keyword(self) -> str:
        return (self.target_context or {}).get("keyword", "")

    @property
    def context_matches(self) -> bool:
        target = (self.target_context or {}).get("app") or (self.target_context or {}).get(
            "window", ""
        )
        if not target:
            return True
        # A window TITLE is content, not identity: an Edge window showing the
        # taskhub page is titled "MIO·HUB — 任务总线", so a title-substring
        # test reports context_matches=False forever and every action gets a
        # pointless focus+re-observe. Match the owning process too.
        from mio_cua.automation.windows import matches_target
        return matches_target(target, self.context, self.active_process)

    @property
    def target_visible(self) -> bool:
        kw = self.target_keyword.lower()
        if not kw:
            return False
        return any(kw in t.lower() for t in self.visible_texts)

    @classmethod
    def from_obs(cls, obs, target_context: Optional[Dict[str, Any]] = None) -> "RuntimeObservation":
        target_context = target_context or {}
        active = getattr(obs, "active_window", "") or ""
        active_process = getattr(obs, "active_process", "") or ""
        scene = getattr(obs, "scene", None)
        elements = getattr(obs, "elements", []) or []

        nodes = getattr(scene, "nodes", []) or [] if scene else []

        # Window bbox (for window-relative sidebar detection).
        window_bbox = None
        for n in nodes:
            if getattr(n, "type", "") == "group" and "MMUIRenderSubWindow" in (
                getattr(n, "semantic", "") or ""
            ):
                window_bbox = n.bbox
                break
            if "Weixin" in (getattr(n, "semantic", "") or "") and getattr(n, "type", "") == "group":
                window_bbox = n.bbox
                break

        sidebar_right = None
        if window_bbox:
            wx, _, ww, _ = window_bbox
            sidebar_right = wx + int(ww * 0.5)

        def in_sidebar(bbox):
            if bbox is None or len(bbox) < 4:
                return False
            if window_bbox:
                return bbox[0] < sidebar_right
            return bbox[0] < 400

        def valid(bbox):
            # Drop degenerate bboxes (off-screen, zero/negative size, or tiny
            # icons) so they never poison the union that defines the chat list.
            if bbox is None or len(bbox) < 4:
                return False
            x, y, w, h = bbox
            return x >= 0 and y >= 0 and w >= 40 and h >= 8

        # Collect sidebar items (text + bbox) from scene nodes and flat elements.
        items: List[tuple] = []  # (text, bbox)
        visible_texts: List[str] = []
        for n in nodes:
            bbox = getattr(n, "bbox", None)
            text = (getattr(n, "text", "") or "").strip()
            if text:
                visible_texts.append(text)
            if getattr(n, "type", "") == "group":
                continue
            if text and in_sidebar(bbox) and valid(bbox):
                items.append((text, bbox))
        for e in elements:
            bbox = getattr(e, "bbox", None)
            text = (getattr(e, "text", "") or "").strip()
            if text:
                visible_texts.append(text)
            if text and in_sidebar(bbox) and valid(bbox):
                items.append((text, bbox))

        candidates = [t for t, _ in items]

        # Grounded scrollable chat-list region = union of item bboxes (padded).
        chat_list_region = _union_bbox([b for _, b in items], pad=12)
        if chat_list_region is None and window_bbox:
            wx, wy, ww, wh = window_bbox
            chat_list_region = [wx, wy, int(ww * 0.35), wh]

        # Search box affordance: a node whose text is the search placeholder.
        search_box = None
        for n in nodes:
            if (getattr(n, "text", "") or "").strip() == "搜索" and getattr(n, "bbox", None):
                search_box = Affordance(kind="search", target="搜索", bbox=list(n.bbox))
                break
        if search_box is None:
            for e in elements:
                if (getattr(e, "text", "") or "").strip() == "搜索" and getattr(e, "bbox", None):
                    search_box = Affordance(kind="search", target="搜索", bbox=list(e.bbox))
                    break

        affordances: List[Affordance] = [Affordance(kind="select", target=c) for c in candidates]
        if chat_list_region is not None:
            affordances.append(Affordance(kind="scroll", target="chat_list", bbox=chat_list_region))
        if search_box is not None:
            affordances.append(search_box)

        return cls(
            raw=obs,
            context=active,
            active_process=active_process,
            target_context=target_context,
            candidates=candidates,
            affordances=affordances,
            scroll=ScrollState(scrollable=chat_list_region is not None),
            focus=active,
            visible_texts=visible_texts,
            obs_id=str(id(obs)),
            chat_list_region=chat_list_region,
            search_box=search_box,
            window_bbox=window_bbox,
        )


def _union_bbox(bboxes, pad=0):
    if not bboxes:
        return None
    xs = [b[0] for b in bboxes]
    ys = [b[1] for b in bboxes]
    rs = [b[0] + b[2] for b in bboxes]
    bs = [b[1] + b[3] for b in bboxes]
    left = min(xs) - pad
    top = min(ys) - pad
    right = max(rs) + pad
    bottom = max(bs) + pad
    return [left, top, right - left, bottom - top]

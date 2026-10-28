"""Open a chat deterministically: search -> unique exact match -> re-verify.

Hard gate (protocol §4): a test message may only be sent once the harness has
proved the conversation is the target. Every step fails closed -- zero matches,
several matches, truncated/uncertain OCR, a missing search box, or a foreground
that is not the target app all stop the flow BEFORE any typing or clicking that
could reach a real chat.

The pure parts (search-box lookup, match selection, post-open verification) are
separated from the desktop flow so the failure modes can be tested offline.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from mio_cua.automation.input_controller import InputController
from mio_cua.models.action import Action
from mio_cua.perception.perception import Perception

TARGET_PROCESSES = ("weixin", "wechat")


def _norm(text: str) -> str:
    return "".join((text or "").split())


@dataclass
class OpenResult:
    ok: bool
    title: str = ""
    why: str = ""
    evidence: Dict = field(default_factory=dict)

    def as_dict(self) -> Dict:
        return {"ok": self.ok, "title": self.title, "why": self.why,
                "evidence": self.evidence}


# ── pure: locate the search box ──

def find_search_box(nodes, rect) -> Optional[tuple]:
    """The chat-list search box, identified by its placeholder text.

    Never a hardcoded coordinate: the box must be a node in the Scene whose text
    contains "搜索", sits in the upper part of the window, left of the
    conversation pane and small enough to be a field.
    """
    if not rect:
        return None
    band_bottom = rect[1] + max(160, int(rect[3] * 0.22))
    cands = []
    for _t, text, bbox in nodes:
        text = (text or "").strip()
        if "搜索" not in text:
            continue
        x, y, w, h = bbox
        if y > band_bottom or w > 400 or h > 60 or w <= 0 or h <= 0:
            continue
        cands.append((y, x, bbox, text))
    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], c[1]))
    return cands[0][2]


# ── pure: pick the unique exact match ──

def select_unique_match(rows: Sequence[str], target: str) -> Tuple[Optional[int], str]:
    """Return (index, reason). Index is None whenever the answer is not certain.

    Rules (all fail closed):
      * exactly one row whose normalized text equals the target -> that row;
      * no exact match -> None ("no exact match");
      * more than one exact match -> None ("multiple exact matches");
      * any row that looks like a truncated version of the target (target
        starts with the row text, or the row carries an ellipsis) -> None
        ("truncated/uncertain"), even if an exact match also exists: a truncated
        sibling means the list cannot be trusted to be unambiguous.
    """
    want = _norm(target)
    if not want:
        return None, "empty target"
    exact, truncated = [], []
    for i, raw in enumerate(rows or []):
        text = _norm(raw)
        if not text:
            continue
        raw_text = raw or ""
        if "..." in raw_text or "…" in raw_text:
            stem = _norm(raw_text.replace("...", "").replace("…", ""))
            if stem and (want.startswith(stem) or stem.startswith(want)):
                truncated.append(i)
                continue
        if text == want:
            exact.append(i)
        elif want.startswith(text) or text.startswith(want):
            truncated.append(i)
    if truncated:
        return None, f"truncated/uncertain rows: {[rows[i] for i in truncated][:3]}"
    if not exact:
        return None, "no exact match"
    if len(exact) > 1:
        return None, f"multiple exact matches ({len(exact)})"
    return exact[0], "unique exact match"


# ── pure: post-open identity ──

def verify_open(title: str, target: str) -> Tuple[bool, str]:
    """The conversation title must equal the target exactly (whitespace-insensitive).

    Deliberately stricter than fuzzy matching: this is the last gate before a
    message could be typed, so a prefix or a similar name is a failure.
    """
    if _norm(title) == _norm(target) and _norm(target):
        return True, "conversation title matches"
    return False, f"conversation title {title!r} != target {target!r}"


def foreground_ok(window: str, process: str, app: str) -> Tuple[bool, str]:
    """Is the foreground the target app? Checked by window AND owning process."""
    if (window or "").strip() != app:
        return False, f"foreground window {window!r} != {app!r}"
    proc = (process or "").lower()
    if not any(p in proc for p in TARGET_PROCESSES):
        return False, f"foreground process {process!r} is not WeChat"
    return True, "foreground ok"


# ── desktop flow ──

def _nodes(obs):
    return [(n.type, (n.text or ""), tuple(n.bbox))
            for n in (getattr(getattr(obs, "scene", None), "nodes", []) or [])
            if getattr(n, "bbox", None)]


def _result_rows(nodes, rect, split, target: str) -> List[Tuple[str, tuple]]:
    """Rows shown by the search (chat list area, below the query field).

    The typed query itself is a text node in the search field and would
    otherwise count as an exact match -- it is excluded by starting the band
    below it. Duplicate renders of one row (same text, same y) are collapsed;
    wide container nodes are not rows. Returns (text, bbox) so the caller clicks
    exactly the row it matched instead of re-searching the Scene.
    """
    want = _norm(target)
    top = rect[1] + 40
    for _t, text, bbox in nodes:
        if _norm(text) == want and bbox[1] <= rect[1] + 140:
            top = max(top, bbox[1] + bbox[3] + 4)
            break
    rows, seen = [], set()
    for _t, text, bbox in nodes:
        text = (text or "").strip()
        if not text:
            continue
        x, y, w, _h = bbox
        if x >= split or y <= top or w > 400:
            continue
        key = (round(y / 6), _norm(text))
        if key in seen:
            continue
        seen.add(key)
        rows.append((y, text, bbox))
    rows.sort(key=lambda r: (r[0], r[2][0]))
    return [(text, bbox) for _y, text, bbox in rows]


def _click(pc, bbox):
    pc.execute(Action("click", "click", {
        "x": bbox[0] + bbox[2] // 2, "y": bbox[1] + bbox[3] // 2}))


def open_chat(pc: InputController, perception: Perception, app: str = "微信",
              target: str = "文件传输助手", settle_s: float = 2.0,
              attempts: int = 2) -> OpenResult:
    """Search for ``target`` and open it, or fail without side effects.

    ``attempts`` retries the whole search once: clicking a row in WeChat's
    search overlay can race the overlay closing and hit the chat list
    underneath. The retry does NOT loosen the gate -- the header is re-verified
    every time, and a mismatch is still a failure.
    """
    last: Optional[OpenResult] = None
    for attempt in range(1, max(1, attempts) + 1):
        res = _open_once(pc, perception, app, target, settle_s)
        res.evidence["attempt"] = attempt
        if res.ok:
            return res
        last = res
        # a wrong title may mean the overlay closed mid-click; retry once
        if "conversation title" not in (res.why or ""):
            return res
    return last or OpenResult(False, why="open failed")


def _open_once(pc: InputController, perception: Perception, app: str,
               target: str, settle_s: float) -> OpenResult:
    from experiments.ab.reset import (_focus_exact, _pane_split, _window_rect,
                                      conversation_title)

    ev: Dict = {"app": app, "target": target}

    # 1) foreground must be the target app (process check, not title-only)
    if not _focus_exact(app):
        return OpenResult(False, why=f"cannot focus {app!r}", evidence=ev)
    time.sleep(0.6)
    obs = perception.observe()
    proc = (getattr(obs, "active_process", "") or "").lower()
    win = (getattr(obs, "active_window", "") or "").strip()
    ev["process"], ev["window"] = proc, win
    ok_fg, why_fg = foreground_ok(win, proc, app)
    if not ok_fg:
        return OpenResult(False, why=why_fg, evidence=ev)

    rect = _window_rect(obs)
    ev["rect"] = rect
    if not rect:
        return OpenResult(False, why="window frame not found", evidence=ev)

    # 2) the search box must be found in the Scene
    box = find_search_box(_nodes(obs), rect)
    ev["search_box"] = box
    if box is None:
        return OpenResult(False, why="search box not found in Scene", evidence=ev)

    _click(pc, box)
    time.sleep(0.3)
    pc.execute(Action("clear", "key", {"keys": "ctrl+a"}))
    time.sleep(0.15)
    pc.execute(Action("type", "type", {"text": target}))
    time.sleep(settle_s)

    # 3) exactly one exact match, nothing truncated
    obs = perception.observe()
    rect = _window_rect(obs) or rect
    split = _pane_split(obs, rect)
    rows = _result_rows(_nodes(obs), rect, split, target)
    ev["rows"] = [t for t, _b in rows[:12]]
    index, reason = select_unique_match([t for t, _b in rows], target)
    ev["match_reason"] = reason
    if index is None:
        return OpenResult(False, why=reason, evidence=ev)

    picked = rows[index][1]
    ev["picked"] = picked
    if picked is None:
        return OpenResult(False, why="matched row has no clickable bbox", evidence=ev)

    _click(pc, picked)
    time.sleep(settle_s)

    # 4) post-open verification: the header must now be the target
    obs = perception.observe()
    title = conversation_title(obs)
    ev["title_after_open"] = title
    ok, why = verify_open(title, target)
    return OpenResult(ok, title=title, why=why, evidence=ev)

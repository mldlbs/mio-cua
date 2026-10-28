"""Deterministic reset + initial-state capture for the A/B runs.

A run only counts if it started from the agreed baseline: same window, no stray
popup/menu, empty draft, same scroll position, same candidate list. If the reset
cannot reach that state, the round must be discarded instead of being recorded
as a result (protocol §4: a failed init may not consume a formal sample).

This module is app-specific (WeChat) but the shape is reusable: reset -> snapshot
-> signature, where the signature is what "same initial state" means.
"""

import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from mio_cua.automation.input_controller import InputController
from mio_cua.models.action import Action
from mio_cua.perception.perception import Perception

@dataclass
class InitialState:
    app: str
    window: str
    rect: Optional[tuple]
    node_count: int
    candidates: List[str]
    conversation: List[str]
    screenshot: Optional[str]
    conversation_title: str = ""
    ok: bool = True
    problems: List[str] = field(default_factory=list)

    def signature(self) -> str:
        """Stable hash of the parts that must not change between runs."""
        payload = "|".join([
            self.app,
            self.conversation_title,
            str(self.rect),
            ",".join(self.candidates),
            "//".join(self.conversation[-3:]),
        ])
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    def as_dict(self) -> Dict:
        return {"app": self.app, "window": self.window, "rect": self.rect,
                "node_count": self.node_count, "candidates": self.candidates,
                "conversation": self.conversation[-5:],
                "conversation_title": self.conversation_title,
                "screenshot": self.screenshot, "ok": self.ok,
                "problems": self.problems, "signature": self.signature()}


def _nodes(obs) -> list:
    scene = getattr(obs, "scene", None)
    return [(n.type, (n.text or ""), tuple(n.bbox)) for n in (getattr(scene, "nodes", []) or [])
            if getattr(n, "bbox", None)]


def _window_rect(obs) -> Optional[tuple]:
    from mio_cua.automation.windows import frame_bbox
    nodes = [type("N", (), {"type": t, "bbox": b, "role": "", "semantic": tx})()
             for t, tx, b in _nodes(obs)]
    return frame_bbox(nodes)


def _pane_split(obs, rect=None) -> int:
    """X where the conversation pane starts (right of the chat list).

    A fixed 50% midpoint is wrong for WeChat: the chat list plus icon rail take
    ~22%, so the midpoint falls inside the conversation and the title/header is
    excluded. The search box lives in the chat list, so its right edge is the
    evidence-based boundary; fall back to a quarter of the window.
    """
    if rect is None:
        rect = _window_rect(obs)
    if not rect:
        return 0
    band = rect[1] + max(120, int(rect[3] * 0.15))
    boxes = []
    for _t, text, bbox in _nodes(obs):
        if "搜索" not in (text or ""):
            continue
        if rect[1] <= bbox[1] <= band:
            boxes.append(bbox)
    if boxes:
        boxes.sort(key=lambda b: (b[1], b[0]))
        b = boxes[0]
        return b[0] + b[2] + 24
    return rect[0] + int(rect[2] * 0.25)


def sidebar_candidates(obs) -> List[str]:
    rect = _window_rect(obs)
    split = _pane_split(obs, rect)
    out = []
    for _t, text, bbox in _nodes(obs):
        text = (text or "").strip()
        if text and bbox[0] < split:
            out.append(text)
    # de-dupe, keep visual order (top-to-bottom, then left)
    seen, ordered = set(), []
    for text, bbox in sorted([(t, b) for t, b in
                              [(txt, bb) for _ty, txt, bb in _nodes(obs)
                               if (txt or "").strip() and bb[0] < split]],
                             key=lambda it: (it[1][1], it[1][0])):
        if text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def conversation_texts(obs) -> List[str]:
    """Message-pane lines, top-to-bottom (right of the chat list, above the composer).

    The composer band and its controls ("发送", glyph-only buttons) are excluded:
    counting them made the "last message" a button label instead of the message.
    """
    rect = _window_rect(obs)
    split = _pane_split(obs, rect)
    composer = _composer_bbox(obs)
    limit = composer[1] if composer else None
    control = {"发送", "?", "？", ">", ">", "+", "×"}
    rows = []
    for _t, text, bbox in _nodes(obs):
        text = (text or "").strip()
        if not text or bbox[0] < split:
            continue
        if limit is not None and bbox[1] >= limit - 4:
            continue
        if text in control or len(text) < 2:
            continue
        rows.append((bbox[1], bbox[0], text))
    rows.sort()
    return [text for _y, _x, text in rows]


def _has_menu(obs) -> bool:
    """A context menu is open (role menu/contextmenu, or a menu-like popup)."""
    scene = getattr(obs, "scene", None)
    for n in getattr(scene, "nodes", []) or []:
        role = (getattr(n, "role", "") or "").lower()
        if role in ("menu", "contextmenu"):
            return True
    return False


def _ocr_region_text(box, scale: int = 2) -> str:
    """OCR one screen rectangle, upscaled: small header text is often missed
    when the whole window is recognised at once."""
    try:
        import numpy as np
        from PIL import Image
        from mio_cua.vision import ocr as ocr_module
        from mio_cua.vision.screen import capture_rect

        img = capture_rect(box)
        if scale != 1:
            img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
        els = ocr_module.get_elements(np.array(img))
    except Exception:
        return ""
    parts = [(e.bbox[1], e.bbox[0], (e.text or "").strip()) for e in els
             if (e.text or "").strip()]
    parts.sort()
    return " ".join(t for _y, _x, t in parts)


def title_matches(observed: str, expected: str) -> bool:
    """Whitespace-insensitive match; OCR may split a name into pieces."""
    o = "".join((observed or "").split())
    e = "".join((expected or "").split())
    return bool(o) and bool(e) and (o == e or e in o or o in e)


def conversation_title(obs) -> str:
    """The open conversation's name, from the header band of the right pane.

    Nodes first (cheap), then a cropped, upscaled OCR of just the header band --
    the whole-window pass frequently drops this small text. Returns "" when it
    cannot be read; callers must treat "" as "unknown" and abort the round.
    """
    rect = _window_rect(obs)
    if not rect:
        return ""
    split = _pane_split(obs, rect)
    band_top = rect[1]
    # Narrow band: the title row sits at the very top of the pane. A wider band
    # reaches a pinned card / first message, whose long text then wins.
    band_bottom = rect[1] + max(56, int(rect[3] * 0.08))
    rows = []
    for _t, text, bbox in _nodes(obs):
        text = (text or "").strip()
        if not text or len(text) < 2:      # window icons are single glyphs
            continue
        if bbox[0] >= split and band_top <= bbox[1] <= band_bottom:
            rows.append((bbox[1], bbox[0], text))
    if rows:
        # The title is the longest text in the header band; sorting by y would
        # pick a window control icon sitting slightly higher.
        rows.sort(key=lambda r: (-len(r[2]), r[0], r[1]))
        return rows[0][2]

    crop = (split, band_top, max(0, rect[0] + rect[2] - split),
            max(20, band_bottom - band_top))
    return _ocr_region_text(crop).strip()


def _focus_exact(title: str) -> bool:
    """Focus a window whose title is EXACTLY ``title``.

    ``focus_window`` matches substrings (its own tests rely on that), so asking
    for "微信" happily activates "企业微信" -- a different app with no composer.
    The harness must not inherit that ambiguity.
    """
    import ctypes
    import win32gui
    from mio_cua.automation.windows import _focus_latest

    hits = []

    def cb(hwnd, _):
        # Note: no IsWindowVisible filter -- a chat app minimised to the tray is
        # hidden but still the window we need; it is restored below.
        if win32gui.GetWindowText(hwnd).strip() == title:
            hits.append(hwnd)

    win32gui.EnumWindows(cb, None)
    for hwnd in hits:
        for _attempt in range(3):
            try:
                win32gui.ShowWindow(hwnd, 9)      # SW_RESTORE
                win32gui.BringWindowToTop(hwnd)
                time.sleep(0.3)
            except Exception:
                pass
            try:
                _focus_latest([hwnd])
            except Exception:
                pass
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            for _ in range(3):
                if win32gui.GetForegroundWindow() == hwnd:
                    return True
                ctypes.windll.user32.SwitchToThisWindow(hwnd, True)
                time.sleep(0.15)
            if win32gui.GetForegroundWindow() == hwnd:
                return True
    return False


def reset(perception: Perception, pc: InputController, app: str = "微信",
          capture_dir: Optional[str] = None,
          clear_draft: bool = False) -> InitialState:
    """Bring the app to the agreed baseline and snapshot it.

    ``clear_draft`` defaults to False: if the composer already holds text that a
    human typed, the harness refuses to wipe it and reports a failed init, so a
    stray draft can never be destroyed (and a polluted run cannot be recorded).
    """
    problems: List[str] = []
    from mio_cua.automation.windows import focus_window

    if not (_focus_exact(app) or focus_window(app)):
        problems.append(f"focus {app!r} failed")
    time.sleep(0.8)
    obs = perception.observe()
    if (getattr(obs, "active_window", "") or "").strip() != app:
        # Fail closed BEFORE any input: pressing Esc / ctrl+end into the wrong
        # window is a real side effect (seen on OpenCode during selfcheck).
        return InitialState(
            app=app, window=getattr(obs, "active_window", "") or "", rect=_window_rect(obs),
            node_count=len(_nodes(obs)), candidates=[], conversation=[],
            screenshot=getattr(obs, "screenshot_path", None),
            conversation_title="", ok=False,
            problems=[f"foreground is {getattr(obs, 'active_window', '')!r}, "
                      f"expected {app!r}; no input sent"],
        )
    rect = _window_rect(obs)

    # 1) dismiss popups/menus (Esc twice: menu, then any overlay)
    for _ in range(2):
        if _has_menu(obs):
            pc.execute(Action("key", "key", {"keys": "esc"}))
            time.sleep(0.3)
            obs = perception.observe()
    if _has_menu(obs):
        problems.append("a menu is still open after Esc")

    # 2) the composer must start empty; never wipe a human's draft
    composer = _composer_bbox(obs)
    if composer is None:
        problems.append("composer not found")
    else:
        draft = _composer_text(obs)
        if draft and not clear_draft:
            problems.append(f"composer holds a draft; refusing to clear: {draft[:20]!r}")
        elif draft:
            cx, cy = composer[0] + composer[2] // 2, composer[1] + composer[3] // 2
            pc.execute(Action("click", "click", {"x": cx, "y": cy}))
            time.sleep(0.2)
            pc.execute(Action("clear", "key", {"keys": "ctrl+a"}))
            pc.execute(Action("key", "key", {"keys": "delete"}))
            time.sleep(0.3)
            obs = perception.observe()
            if _composer_text(obs):
                problems.append("draft not cleared")

    # 3) pin the scroll position: the message pane goes to the bottom
    if rect:
        mx = rect[0] + int(rect[2] * 0.75)
        my = rect[1] + int(rect[3] * 0.5)
        pc.execute(Action("click", "click", {"x": mx, "y": my}))
        time.sleep(0.2)
        for _ in range(3):
            pc.execute(Action("key", "key", {"keys": "ctrl+end"}))
            time.sleep(0.2)
        obs = perception.observe()

    shot = getattr(obs, "screenshot_path", None)
    state = InitialState(
        app=app,
        window=getattr(obs, "active_window", "") or "",
        rect=rect,
        node_count=len(_nodes(obs)),
        candidates=sidebar_candidates(obs),
        conversation=conversation_texts(obs),
        conversation_title=conversation_title(obs),
        screenshot=shot,
        ok=not problems,
        problems=problems,
    )
    return state


def _composer_bbox(obs):
    """The chat input area: prefer a real UIA input, fall back to geometry.

    WeChat/WeCom are DirectUI apps: their UIA tree exposes only the window and a
    pane, so there is no ``input`` node to find. The composer is then estimated
    from the window frame (bottom band, right of the chat list), which is stable
    for a maximised, un-resized window -- the A/B requires exactly that.
    """
    best = None
    for n in getattr(getattr(obs, "scene", None), "nodes", []) or []:
        if (getattr(n, "type", "") or "") != "input":
            continue
        b = getattr(n, "bbox", None)
        if not b or len(b) < 4:
            continue
        _x, y, w, h = b
        if w >= 400 and 40 <= h <= 160 and y > 300:
            if best is None or y > best[1]:
                best = b
    if best is not None:
        return best

    rect = _window_rect(obs)
    if not rect:
        return None
    x, y, w, h = rect
    return (x + int(w * 0.56), y + int(h * 0.83), int(w * 0.41), int(h * 0.12))


def _composer_text(obs) -> str:
    """Visible text inside the composer band (a human draft would show here)."""
    band = _composer_bbox(obs)
    if not band:
        return ""
    bx, by, bw, bh = band
    parts = []
    for n in getattr(getattr(obs, "scene", None), "nodes", []) or []:
        b = getattr(n, "bbox", None)
        text = (getattr(n, "text", "") or "").strip()
        if not b or len(b) < 4 or not text:
            continue
        cx, cy = b[0] + b[2] // 2, b[1] + b[3] // 2
        if bx <= cx <= bx + bw and by <= cy <= by + bh:
            parts.append(text)
    return " ".join(parts).strip()

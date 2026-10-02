"""Runtime web-chat driver: ask a question in an ALREADY-OPEN chat tab and read
the answer back.

This is the runtime counterpart of the ``trace/`` multi-turn harness. The
harness proves the extraction survives long threads (5/20/50/100-turn runs);
this module exposes the same hard-won rules to other agents through the MCP
tool ``mio_ask_web_chat`` -- one question in, one extracted reply out.

Design notes carried over from the harness (each earned by a live failure):

* the page is recognised by CONTENT, never by window title (ChatGPT rewrites
  its title from the conversation once a message lands);
* the transcript band is bounded by the composer geometry; the trailing exact
  token may sit a few px below it because the input's DOM box overlaps the
  last action row;
* UIA tree order is not y order, so noise rows are skipped rather than used as
  a break, and pieces are sorted before joining;
* a reply taller than the viewport is read by scrolling and stitching
  (``sweep_reply``) because the page does not follow the streaming tail.

Unlike the harness this takes ``site`` per call and derives its anchor from the
prompt itself (no injected turn token), so it never mutates what the user asked.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import re
import sys
import time

from mio_cua.automation.input_controller import InputController
from mio_cua.automation.windows import _focus_latest
from mio_cua.models.action import Action
from mio_cua.perception.perception import Perception

# ── site table ──

_SITES = {
    "deepseek": {
        "host": "deepseek.com",
        # the composer placeholder OCRs to garbage, so fall back to the
        # sidebar/toolbar markers instead of the input's own text
        "markers": ("深度思考", "开启新对话"),
        "new_chat": ("开启新对话",),
    },
    "chatgpt": {
        "host": "chatgpt.com",
        "markers": ("随便问",),
        "also": ("也可能会犯错", "新聊天"),
        "new_chat": ("新聊天", "New chat"),
    },
}

# ── noise ──

_UI_NOISE_RE = re.compile(
    r"也可能会犯错"                                        # footer disclaimer
    r"|^\s*广告\s*$"                                       # ad marker
    r"|CARTESIA|Real-Time Voice|One APl|production voice|unique voice|Find your"
    r"|^(复制|评价|编辑|分享|切换|更多|点赞|点踩|打开|关闭|重试"
    r"|重新生成|重新|朗读|继续生成|继续|发送|停止|引\w{0,4}用)",   # control labels
    re.I,
)

_EXTRA_NOISE = re.compile(
    r"Monogram|UiPath|Applied A[I1] studio|copilots engineered|My Workspace"
    r"|^已深度思考|^正在思考"        # DeepSeek streaming thinking header
    r"|^C$"                          # DeepSeek copy button OCRs to a bare 'C'
    r"|^[A-Za-z0-9]$",               # any single control glyph ('Q' saw this)
    re.I,
)

_COMPOSER_ANCHOR = 400


def _squash(text):
    return re.sub(r"\s+", "", text or "")


def _char_count(text):
    return len(_squash(text))


def _is_ui_noise(text):
    return bool(_UI_NOISE_RE.search((text or "").strip()))


def _is_noise(text):
    return _is_ui_noise(text) or bool(_EXTRA_NOISE.search(text or ""))


def _node_tuples(obs):
    """Normalize an Observation / recorded frame to (type, text, bbox)."""
    scene = getattr(obs, "scene", None)
    if scene is not None and getattr(scene, "nodes", None):
        return [(getattr(n, "type", ""), getattr(n, "text", "") or "",
                 getattr(n, "bbox", None)) for n in scene.nodes]
    out = []
    for nd in (getattr(obs, "scene_nodes", None) or []):
        if isinstance(nd, dict):
            out.append((nd.get("type", ""), nd.get("text", "") or "", nd.get("bbox")))
        else:
            out.append((getattr(nd, "type", ""), getattr(nd, "text", "") or "",
                        getattr(nd, "bbox", None)))
    return out


def _tree_has(obs, needle) -> bool:
    return any(needle in (t or "") for _, t, _ in _node_tuples(obs))


# ── window focus ──

def _chrome_hwnds():
    """Visible Chrome top-level windows, enumerated via ctypes.

    pywin32's EnumWindows callback arg handling proved order-dependent across
    the MCP worker thread (it raised "GetClassName() takes exactly 1 argument"
    there while working in a plain script), so enumeration is done with the raw
    Win32 API to keep it thread-agnostic.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    out = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    def _cls(hwnd):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def _title(hwnd):
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _cls(hwnd) == "Chrome_WidgetWin_1" and _title(hwnd):
            out.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def _activate(hwnd) -> bool:
    """Raise ``hwnd`` and confirm IT is the foreground window.

    ``_focus_latest`` treats "a window of the same process came forward" as
    success; with two Chrome windows that is a lie and clicks land in the
    sibling, so the exact hwnd must hold the foreground.
    """
    import win32gui
    if not _focus_latest([hwnd]):
        return False
    for _ in range(3):
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        ctypes.windll.user32.SwitchToThisWindow(hwnd, True)
        time.sleep(0.15)
    return win32gui.GetForegroundWindow() == hwnd


def looks_like(obs, site) -> bool:
    """Recognise the page by content: owning process, then URL, then markers."""
    spec = _SITES[site]
    if "chrome" not in (getattr(obs, "active_process", "") or "").lower():
        return False
    texts = [(t or "") for _, t, _ in _node_tuples(obs)]
    if any(spec["host"] in t for t in texts):
        return True
    if not all(any(m in t for t in texts) for m in spec["markers"]):
        return False
    also = spec.get("also")
    return any(any(k in t for t in texts) for k in also) if also else True


def focus_site(perception, site, pin_token=None):
    """(ok, how, obs) -- activate the Chrome window showing ``site``.

    ``pin_token`` (optional) disambiguates two windows of the same site: the
    one already showing the token is ours. Without it, the first content match
    wins; the exact-foreground check keeps a sibling from faking success.
    """
    unpinned = None
    for hwnd in _chrome_hwnds():
        if not _activate(hwnd):
            continue
        time.sleep(0.4)
        obs = perception.observe()
        if not looks_like(obs, site):
            continue
        if pin_token is None or _tree_has(obs, pin_token):
            return True, f"hwnd={hwnd}", obs
        if unpinned is None:
            unpinned = (hwnd, obs)
    if unpinned is not None:
        hwnd, obs = unpinned
        return True, f"hwnd={hwnd} [pin {pin_token} absent -> unpinned]", obs
    return False, f"no {site} window found", None


# ── layout / composer ──

def _input_box(nodes):
    """The DeepSeek composer as geometry: the lowest bare input of chat size.

    The placeholder OCRs to one garbage character, and markdown quote rows come
    back as type ``input`` with a full sentence in them, so a candidate must be
    400..900 x 40..160, below y=300, short-texted, and (among survivors) lowest.
    """
    best = None
    for ntype, text, bbox in nodes:
        if ntype != "input" or not bbox or len(bbox) < 4:
            continue
        _x, y, w, h = bbox[:4]
        if not (400 <= w <= 900 and 40 <= h <= 160 and y > 300):
            continue
        if len((text or "").strip()) > 8:
            continue
        if best is None or y > best[1]:
            best = bbox
    return best


def _chatgpt_layout(nodes):
    field = row_top = fallback = None
    for ntype, text, bbox in nodes:
        if not bbox or len(bbox) < 4:
            continue
        if "随便问" not in text and "有问题" not in text:
            continue
        if fallback is None:
            fallback = bbox
        if ntype in ("input", "group", "button"):
            if row_top is None or bbox[1] < row_top:
                row_top = bbox[1]
            if ntype == "input" and field is None:
                field = bbox
    col = field or fallback
    if col is None:
        return None, None, None
    x, w = col[0], col[2]
    floor = row_top if row_top is not None else col[1]
    return max(0, x - _COMPOSER_ANCHOR), x + w + _COMPOSER_ANCHOR, floor


def layout(nodes, site):
    """(left, right, floor) of the transcript column for ``site``.

    DeepSeek skips the text-anchored layout: its prose containing "有问题" would
    be mistaken for the composer and slice the answer off. Its padding is 60px
    (not 400) so the right-hand outline panel at x~2011 stays out of the band.
    """
    if site == "chatgpt":
        left, right, floor = _chatgpt_layout(nodes)
        if left is not None:
            return left, right, floor
    box = _input_box(nodes)
    if not box:
        return None, None, None
    x, w = box[0], box[2]
    return max(0, x - 60), x + w + 60, box[1]


def find_composer(nodes, site):
    if site == "deepseek":
        box = _input_box(nodes)
        if box:
            return box[0] + box[2] // 2, box[1] + box[3] // 2
        return None, None
    fallback = None
    for ntype, text, bbox in nodes:
        if not bbox or len(bbox) < 4:
            continue
        if "随便问" not in (text or "") and "有问题" not in (text or ""):
            continue
        if ntype == "input":
            return bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2
        if fallback is None:
            fallback = bbox
    if fallback:
        return fallback[0] + fallback[2] // 2, fallback[1] + fallback[3] // 2
    box = _input_box(nodes)
    if box:
        return box[0] + box[2] // 2, box[1] + box[3] // 2
    return None, None


# ── extraction ──

def _is_our_message(text, tok):
    """Our prompt opens with the token and a reply only echoes it at the end."""
    t = (text or "").strip()
    if not t.startswith(tok):
        return False
    return not t.endswith(tok)


def reply_pieces(nodes, own_tokens, stop_token=None, prompt=None, site="deepseek"):
    """Ordered reply pieces from ONE observation: (pieces, why, meta, anchored).

    ``own_tokens`` is the anchor: only the head of our message. When it is not
    visible (DeepSeek scrolls it out during a long answer) the band opens on the
    previous boundary (``stop_token``) or the viewport top. ``anchored`` is True
    when our message WAS visible -- the scroll-stitch stops on it.
    """
    meta = {"nodes": len(nodes)}
    if not nodes:
        return [], "no scene nodes", meta, False

    left, right, floor = layout(nodes, site)
    meta.update({"left": left, "right": right, "floor": floor})
    if left is None:
        return [], "composer not found", meta, False

    def _in_band(bbox):
        x, y = bbox[0], bbox[1]
        if not (left <= x <= right) or y <= 200:
            return False
        return floor is None or y < floor

    user_y = user_y_any = None
    for ntype, text, bbox in nodes:
        if ntype == "group" or not bbox or len(bbox) < 4:
            continue
        if not _in_band(bbox):
            continue
        if any(_is_our_message(text, t) for t in own_tokens):
            y = bbox[1]
            user_y_any = y if user_y_any is None else max(user_y_any, y)
            if bbox[3] < 60:            # bubble rows are short, reply boxes are not
                user_y = y if user_y is None else max(user_y, y)
    if user_y is None:
        user_y = user_y_any
    anchored = user_y is not None
    anchor_note = ""
    if user_y is None:
        top = 200
        if stop_token:
            for ntype, text, bbox in nodes:
                if ntype == "group" or not bbox or len(bbox) < 4:
                    continue
                if not _in_band(bbox):
                    continue
                stripped = (text or "").strip()
                if stripped == stop_token or (bbox[3] < 60 and _is_our_message(text, stop_token)):
                    top = max(top, bbox[1])
        user_y = top
        anchor_note = f", fallback band (top={top})"
    meta["user_y"] = user_y
    meta["anchored"] = anchored

    norm_prompt = _squash(prompt)
    pieces = []
    for ntype, text, bbox in nodes:
        if ntype == "group":
            continue
        text = (text or "").strip()
        if not text or not bbox or len(bbox) < 4:
            continue
        squashed = _squash(text)
        x, y = bbox[0], bbox[1]
        if not (left <= x <= right):
            continue
        if y <= user_y:
            continue
        is_badge = text in own_tokens
        if floor is not None and y >= floor and not is_badge:
            continue
        if _is_noise(text):
            continue
        if norm_prompt and len(squashed) >= 6 and squashed in norm_prompt:
            continue
        pieces.append((y, x, text, y + bbox[3]))

    if not pieces:
        return [], f"no prose below turn anchor (y={user_y}){anchor_note}", meta, anchored

    pieces.sort()
    kept = []
    for y, x, text, bottom in pieces:
        if text not in own_tokens and any(
            k[3] >= y and ((k[3] - k[0]) >= 60 or _squash(k[2]) == _squash(text))
            for k in kept
        ):
            continue
        kept.append((y, x, text, bottom))
    pieces = kept
    badge_idx = [i for i, p in enumerate(pieces) if p[2] in own_tokens]
    if badge_idx and badge_idx[-1] > 0:
        pieces = pieces[: badge_idx[-1] + 1]
    meta["reply_y"] = pieces[0][0]
    meta["pieces"] = len(pieces)
    why = f"{len(pieces)} node(s) below turn anchor y={user_y}{anchor_note}"
    return pieces, why, meta, anchored


def extract_last_reply(obs, own_tokens, stop_token=None, prompt=None, site="deepseek"):
    """Single-view reply text (thin wrapper over ``reply_pieces``)."""
    pieces, why, meta, _anchored = reply_pieces(
        _node_tuples(obs), own_tokens, stop_token, prompt, site
    )
    if not pieces:
        return "", why, meta
    return " ".join(p[2] for p in pieces), why, meta


def _stitch_lines(acc, lines):
    """Prepend the non-overlapping head of ``lines`` to ``acc`` (see harness)."""
    if not acc:
        return list(lines)
    a = [_squash(x) for x in acc]
    b = [_squash(x) for x in lines]
    for k in range(min(len(a), len(b)), 0, -1):
        if a[:k] == b[-k:]:
            return list(lines[:-k]) + list(acc)
    return list(lines) + list(acc)


def sweep_reply(pc, perception, own_tokens, stop_token=None, prompt=None,
                site="deepseek", max_views=8):
    """Full reply text, stitched across scroll positions (see harness)."""
    obs = perception.observe()
    left, right, floor = layout(_node_tuples(obs), site)
    if left is None:
        return "", "composer not found", False
    pc.execute(Action("click", "click", {"x": max(0, left + 8), "y": 420}))
    time.sleep(0.3)
    for _ in range(12):
        pc.execute(Action("key", "key", {"keys": "pagedown"}))
    time.sleep(0.6)
    acc, anchored, last_lines = [], False, None
    for _ in range(max_views):
        pieces, _why, _meta, anchored = reply_pieces(
            _node_tuples(perception.observe()), own_tokens, stop_token, prompt, site
        )
        lines = [p[2] for p in pieces]
        if lines:
            acc = _stitch_lines(acc, lines)
        if anchored or lines == last_lines:
            break
        last_lines = lines
        pc.execute(Action("key", "key", {"keys": "pageup"}))
        time.sleep(0.7)
    for _ in range(12):
        pc.execute(Action("key", "key", {"keys": "pagedown"}))
    return " ".join(acc), "sweep", anchored


# ── send / settle / ask ──

def _toast_hint(obs):
    texts = [(t or "") for _, t, _ in _node_tuples(obs)]
    for kw in ("频繁", "稍后", "上限", "限制", "失败", "重试", "太多", "排队"):
        if any(kw in t for t in texts):
            return kw
    return ""


def _sent_seen(obs, token, site):
    """True when our message exists outside the composer (bubble or outline)."""
    nodes = _node_tuples(obs)
    left, right, floor = layout(nodes, site)
    if left is None:
        return False
    for ntype, text, bbox in nodes:
        if ntype in ("group", "input") or not bbox or len(bbox) < 4:
            continue
        x, y = bbox[0], bbox[1]
        if left <= x <= right and (floor is None or y < floor):
            if _is_our_message(text, token):
                return True
        elif x > right and (text or "").strip().startswith(token):
            return True
    return False


def send_turn(pc, perception, obs, prompt, token, site):
    """Type the prompt and confirm it reached the transcript (verify + retry)."""
    toast = ""
    for attempt in (1, 2):
        cx, cy = find_composer(_node_tuples(obs), site)
        if cx is None:
            if attempt == 1:
                time.sleep(2.0)
                ok, _how, fresh = focus_site(perception, site)
                if ok and fresh is not None:
                    obs = fresh
                    continue
            return False, "composer not found"
        pc.execute(Action("click", "click", {"x": cx, "y": cy}))
        time.sleep(0.4)
        pc.execute(Action("clear", "key", {"keys": "ctrl+a"}))
        time.sleep(0.2)
        pc.execute(Action("type", "type", {"text": prompt}))
        time.sleep(0.4)
        pc.execute(Action("enter", "key", {"keys": "enter"}))
        time.sleep(2.0)
        ok, _how, obs2 = focus_site(perception, site)
        if ok and obs2 is not None and _sent_seen(obs2, token, site):
            return True, ""
        if obs2 is not None:
            toast = _toast_hint(obs2)
            obs = obs2
        if attempt == 1:
            time.sleep(2.0)
    return False, f"send not delivered ({toast} toast)" if toast else "send not delivered"


def settle(pc, perception, token, prompt, site, timeout_s=180.0, quiet_s=5.0,
           interval_s=2.0):
    """Poll until the reply stops changing, then read it in full (sweep)."""
    best, why, best_obs, meta = "", "timeout", None, {}
    stable_since, last = None, None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        ok, how, obs = focus_site(perception, site)
        if not ok or obs is None:
            why = f"focus: {how}"
            time.sleep(interval_s)
            continue
        text, w, m = extract_last_reply(obs, [token], prompt=prompt, site=site)
        if text and text == last:
            if stable_since and time.time() - stable_since >= quiet_s:
                full, _swhy, _anch = sweep_reply(
                    pc, perception, [token], prompt=prompt, site=site
                )
                if full and _char_count(full) >= _char_count(text):
                    text = full
                return text, w, obs, True, m
        else:
            stable_since = time.time() if text else None
        last, best, best_obs, best_why, meta = text, text, obs, w, m
        why = best_why
        time.sleep(interval_s)
    return best, why, best_obs, False, meta


def _start_new_chat(pc, perception, site, obs):
    """Best-effort click on the site's new-conversation button."""
    keys = _SITES[site]["new_chat"]
    hit = None
    for _n, text, bbox in _node_tuples(obs):
        t = (text or "").strip()
        if not t or not bbox or len(bbox) < 4:
            continue
        if any(k in t for k in keys) and bbox[2] <= 300 and bbox[3] <= 60:
            hit = bbox
            break
    if hit is None:
        return obs
    pc.execute(Action("click", "click", {"x": hit[0] + hit[2] // 2,
                                         "y": hit[1] + hit[3] // 2}))
    time.sleep(3.0)
    ok, _how, fresh = focus_site(perception, site)
    return fresh if ok and fresh is not None else obs


def ask(site="deepseek", prompt="", timeout_s=180.0, quiet_s=5.0, new_chat=False):
    """Send ``prompt`` to the open chat tab and return the extracted reply.

    Returns a dict: {ok, site, sent, stable, tagged, chars, reply, why}. The
    anchor token is the prompt's own head -- the prompt is never modified.
    """
    if site not in _SITES:
        raise ValueError(f"unknown site {site!r} (expected {sorted(_SITES)})")
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is empty")
    token = prompt[:24]
    pc = InputController()
    perception = Perception()
    result = {"ok": False, "site": site, "token": token, "sent": False,
              "stable": False, "tagged": False, "chars": 0, "reply": "",
              "why": ""}

    ok, how, obs = focus_site(perception, site)
    if not ok:
        result["why"] = how
        return result
    if new_chat:
        obs = _start_new_chat(pc, perception, site, obs)

    sent, why = send_turn(pc, perception, obs, prompt, token, site)
    if not sent:
        result["why"] = why
        return result
    result["sent"] = True

    time.sleep(2.0)
    text, why2, _obs2, stable, _meta = settle(
        pc, perception, token, prompt, site, timeout_s=timeout_s, quiet_s=quiet_s
    )
    result.update(ok=bool(text), reply=text, chars=_char_count(text),
                  stable=stable, tagged=token in text, why=why2)
    return result


def main():
    ap = argparse.ArgumentParser(description="Ask an open chat tab and read the reply.")
    ap.add_argument("--site", default="deepseek", choices=sorted(_SITES))
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--new-chat", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(ask(a.site, a.prompt, timeout_s=a.timeout, new_chat=a.new_chat),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

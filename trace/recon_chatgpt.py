"""Recon: open chatgpt.com in the user's Chrome profile and dump page structure.

Why this exists: the chat scenario needs to (a) find the composer, (b) find
the assistant's reply bubble, and (c) tell a finished reply from a streaming
one. Guessing those from nothing produced rework on the browser-search
scenario, so capture the real node ids/roles/semantic first.

Chrome is used deliberately -- the user is already signed in there -- and the
URL is driven through the address bar rather than os.startfile(), which would
hand the link to whatever browser happens to be the default.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from mio_cua.automation.input_controller import InputController
from mio_cua.automation.windows import (
    _proc_names,
    _windows_matching_process,
    focus_window,
    get_active_process,
    get_active_window,
)
from mio_cua.models.action import Action

URL = "https://chatgpt.com/"
OUT = Path(__file__).resolve().parent / "recon_chatgpt.json"

CHROME_EXES = [
    os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def _keys(controller, keys):
    r = controller.execute(Action(id="recon", type="key", params={"keys": keys}))
    if not r.sent:
        raise RuntimeError(f"key {keys!r} not sent: {r.error}")


def _type(controller, text):
    r = controller.execute(Action(id="recon", type="type", params={"text": text}))
    if not r.sent:
        raise RuntimeError(f"type failed: {r.error}")


def ensure_chrome() -> None:
    if _windows_matching_process(_proc_names("Chrome")):
        print("  Chrome already running")
        return
    for exe in CHROME_EXES:
        if os.path.exists(exe):
            print(f"  launching {exe}")
            subprocess.Popen([exe, URL])
            time.sleep(8)
            return
    raise SystemExit("chrome.exe not found in the usual install paths")


def navigate(controller) -> None:
    if not focus_window("Chrome"):
        raise SystemExit("could not focus a Chrome window")
    time.sleep(0.5)
    _keys(controller, "ctrl+l")
    time.sleep(0.3)
    _type(controller, URL)
    time.sleep(0.3)
    _keys(controller, "enter")
    print(f"  navigating to {URL}")
    time.sleep(8)  # SPA boot + auth handshake


def main() -> None:
    ensure_chrome()
    controller = InputController()
    navigate(controller)

    print(f"  fg now: {get_active_window()!r} (process={get_active_process()!r})")

    from mio_cua.perception.perception import Perception

    # screenshot_dir must be set: the default (None) records no path, and the
    # whole point of this run is to *look* at the page.
    perc = Perception(screenshot_dir=str(Path(__file__).resolve().parent))
    t0 = time.time()
    obs = perc.observe()
    print(f"  observe() {time.time() - t0:.1f}s")

    shot = getattr(obs, "screenshot_path", None)
    if shot and os.path.exists(shot):
        dst = Path(__file__).resolve().parent / "recon_chatgpt.png"
        import shutil
        shutil.copy2(shot, dst)
        print(f"  screenshot -> {dst}")

    scene = getattr(obs, "scene", None)
    nodes = list(getattr(scene, "nodes", []) or []) if scene else []
    elements = list(getattr(obs, "elements", []) or [])

    print(f"  active_window: {getattr(obs, 'active_window', '')!r}")
    print(f"  scene nodes: {len(nodes)}   flat elements: {len(elements)}")

    # Anything that smells like the composer, send button, or a reply bubble.
    HINTS = ("输入", "发送", "发消息", "message", "send", "ask", "chat", "chatgpt",
             "stop", "停止", "复制", "copy", "回复", "好的", "我是", "你是")
    hits = []
    for n in nodes:
        text = (getattr(n, "text", "") or "").strip()
        sem = (getattr(n, "semantic", "") or "").strip()
        role = getattr(n, "type", "")
        blob = f"{text} {sem}".lower()
        if text and any(h.lower() in blob for h in HINTS):
            hits.append({"id": n.id, "type": role, "text": text[:80],
                         "semantic": sem[:60], "bbox": list(n.bbox or [])})
        elif role in ("input", "textbox", "button", "textarea") and text:
            hits.append({"id": n.id, "type": role, "text": text[:80],
                         "semantic": sem[:60], "bbox": list(n.bbox or [])})

    print(f"  candidate nodes: {len(hits)}")
    for h in hits[:40]:
        print(f"    id={h['id']:<5} {h['type']:<10} {h['text']!r:<45} {h['semantic']!r}")

    payload = {
        "url_target": URL,
        "active_window": getattr(obs, "active_window", ""),
        "active_process": getattr(obs, "active_process", ""),
        "node_count": len(nodes),
        "element_count": len(elements),
        "screenshot": str(shot or ""),
        "candidates": hits,
        "all_nodes": [
            {"id": n.id, "type": getattr(n, "type", ""),
             "text": (getattr(n, "text", "") or "")[:120],
             "semantic": (getattr(n, "semantic", "") or "")[:80],
             "bbox": list(n.bbox or [])}
            for n in nodes
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote {OUT} ({len(nodes)} nodes)")


if __name__ == "__main__":
    main()

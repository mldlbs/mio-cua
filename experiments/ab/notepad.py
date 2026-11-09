"""Notepad driver for the A/B: deterministic reset and exact state reading.

Why Notepad: the loop comparison must not depend on OCR, search overlays or a
real chat account. Notepad gives us

  * a disposable process (kill + relaunch = clean state),
  * the document text through UIA ValuePattern (exact, no OCR),
  * a deterministic obstruction (Ctrl+F opens a "查找" dialog, Esc closes it),
  * files on disk whose hashes prove nothing was modified.

Everything here fails closed: an unreadable document or a missing window is an
error, never an assumed empty state.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

import psutil
import win32gui
import win32process
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.uia_element_info import UIAElementInfo

TEST_DIR = Path(tempfile.gettempdir()) / "mio_ab_notepad"
DECOYS = ("decoy1.txt", "decoy2.txt", "decoy3.txt")
TARGET_FILE = "target.txt"      # deliberately absent
OUT_FILE = "out.txt"


# ── process / window ──

def _notepad_pids() -> List[int]:
    return [p.info["pid"] for p in psutil.process_iter(["pid", "name"])
            if (p.info.get("name") or "").lower() == "notepad.exe"]


def windows_of(pid: int) -> List[int]:
    found = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd):
            return
        _, wpid = win32process.GetWindowThreadProcessId(hwnd)
        if wpid == pid:
            found.append(hwnd)

    win32gui.EnumWindows(cb, None)
    return found


def main_window() -> Optional[int]:
    """The notepad DOCUMENT window (largest visible window, excluding dialogs).

    With a modal open, the dialog can otherwise be picked and its own edit
    control (a folder name like "Default Project") read as the document text.
    """
    best = None
    for pid in _notepad_pids():
        for hwnd in windows_of(pid):
            title = win32gui.GetWindowText(hwnd) or ""
            if any(t in title for t in MODAL_TITLES):
                continue
            rect = win32gui.GetWindowRect(hwnd)
            area = max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])
            if best is None or area > best[0]:
                best = (area, hwnd)
    return best[1] if best else None


def dialog_windows(pid: int) -> List[int]:
    """Secondary windows of the process (e.g. the 查找 dialog)."""
    wins = windows_of(pid)
    main = main_window()
    return [h for h in wins if h != main]


MODAL_TITLES = ("查找", "打开")


def find_dialogs(pid: int) -> List[int]:
    """Secondary windows that block input (查找 / 打开)."""
    out = []
    for h in dialog_windows(pid):
        title = win32gui.GetWindowText(h) or ""
        if any(t in title for t in MODAL_TITLES):
            out.append(h)
    return out


def kill_all() -> None:
    for pid in _notepad_pids():
        try:
            psutil.Process(pid).kill()
        except Exception:
            pass
    time.sleep(0.6)


def focus(hwnd: int) -> bool:
    try:
        win32gui.ShowWindow(hwnd, 9)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        return False
    for _ in range(3):
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        try:
            win32gui.BringWindowToTop(hwnd)
        except Exception:
            pass
        time.sleep(0.15)
    return win32gui.GetForegroundWindow() == hwnd


# ── document value (exact) ──

def document_value(hwnd: int) -> Optional[str]:
    """The document text via UIA ValuePattern; None when unreadable (fail closed).

    Picks the LARGEST Edit control: when a modal (e.g. 打开) is open, its file
    -name field can appear among the main window's descendants and would
    otherwise be read as the document ("Default Project").
    """
    try:
        w = UIAWrapper(UIAElementInfo(hwnd))
        best = None
        for c in w.descendants():
            if str(c.element_info.control_type) != "Edit":
                continue
            try:
                r = c.rectangle()
                area = max(0, r.width()) * max(0, r.height())
            except Exception:
                area = 0
            if best is None or area > best[0]:
                best = (area, c)
        if best is not None:
            try:
                return best[1].get_value()
            except Exception:
                return None
    except Exception:
        return None
    return None


# ── files ──

def file_state(directory: Path = TEST_DIR) -> Dict[str, str]:
    """name -> sha1 for every file in the test directory."""
    out = {}
    if not directory.exists():
        return out
    for p in sorted(directory.iterdir()):
        if p.is_file():
            out[p.name] = hashlib.sha1(p.read_bytes()).hexdigest()
    return out


def prepare_dir(directory: Path = TEST_DIR) -> None:
    """Clean slate: empty dir, then recreate the decoys."""
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(DECOYS):
        (directory / name).write_text(f"decoy payload {i}\n", encoding="utf-8")


# ── reset ──

def reset(directory: Path = TEST_DIR) -> Optional[int]:
    """Kill every notepad, rebuild the test dir, launch one empty document."""
    kill_all()
    prepare_dir(directory)
    subprocess.Popen(["notepad.exe"])
    deadline = time.time() + 10
    while time.time() < deadline:
        hwnd = main_window()
        if hwnd and document_value(hwnd) == "":
            focus(hwnd)
            return hwnd
        time.sleep(0.4)
    return None


# ── obstruction ──

def inject_find_dialog(pc, hwnd: int) -> bool:
    """Ctrl+O opens the 打开 modal; True when it is really there.

    Uses Ctrl+O rather than Ctrl+F: the 打开 dialog opens with only the window
    focused, while Ctrl+F needs the document control focused (a freshly launched
    window does not have it, so the keystroke silently did nothing).
    """
    from mio_cua.models.action import Action

    focus(hwnd)
    pc.execute(Action("key", "key", {"keys": "ctrl+o"}))
    deadline = time.time() + 4
    while time.time() < deadline:
        for pid in _notepad_pids():
            if find_dialogs(pid):
                return True
        time.sleep(0.3)
    return False


def dismiss_find_dialog(pc, hwnd: int) -> bool:
    from mio_cua.models.action import Action

    focus(hwnd)
    pc.execute(Action("key", "key", {"keys": "esc"}))
    time.sleep(0.6)
    for pid in _notepad_pids():
        if find_dialogs(pid):
            return False
    return True


def snapshot(hwnd: Optional[int], directory: Path = TEST_DIR) -> Dict:
    """Everything the judges need: document text, dialogs open, file hashes."""
    pid = None
    if hwnd:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            pid = None
    return {
        "doc": document_value(hwnd) if hwnd else None,
        "dialogs": [win32gui.GetWindowText(h) for h in (dialog_windows(pid) if pid else [])],
        "files": file_state(directory),
        "window": hwnd,
        "title": win32gui.GetWindowText(hwnd) if hwnd else "",
    }

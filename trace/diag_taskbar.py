"""Locate the taskbar by class name, then read ONLY its own subtree.

Enumerating every top-level window through UIA hangs on this machine (it also
makes focus_window's step-5 fallback stall), so narrow to one hwnd first.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import win32gui

hwnd = win32gui.FindWindow("Shell_TrayWnd", None)
print(f"Shell_TrayWnd hwnd = {hwnd}")
if not hwnd:
    sys.exit("taskbar not found")
print("rect:", win32gui.GetWindowRect(hwnd))
print("text:", repr(win32gui.GetWindowText(hwnd)))


def work():
    from pywinauto import Desktop

    w = Desktop(backend="uia").window(handle=hwnd)
    kids = list(w.descendants())
    print(f"\ndescendants: {len(kids)}")
    named = [(k.friendly_class_name(), k.window_text()) for k in kids if k.window_text()]
    for ct, name in named[:40]:
        print(f"  [{ct:<18}] {name[:70]!r}")
    print(f"\nwith a name: {len(named)} / {len(kids)}")


t = threading.Thread(target=work, daemon=True)
t.start()
t.join(timeout=25)
if t.is_alive():
    print("UIA subtree read TIMED OUT after 25s")
else:
    print("ok")

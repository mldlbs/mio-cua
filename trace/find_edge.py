"""Find Edge windows."""
import sys
sys.path.insert(0, r"E:\work\code\agent-dev\desktop-agent")
sys.stdout.reconfigure(encoding="utf-8")

import win32gui
import win32process
import psutil

results = []

def enum_cb(hwnd, _):
    if win32gui.IsWindowVisible(hwnd):
        title = win32gui.GetWindowText(hwnd)
        if title:
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc = psutil.Process(pid).name()
            except:
                proc = "unknown"
            results.append((hwnd, title, proc))

win32gui.EnumWindows(enum_cb, None)

print("=== Edge windows ===")
for hwnd, title, proc in results:
    if "edge" in proc.lower() or "msedge" in title.lower():
        print(f"  hwnd={hwnd} proc={proc} title={title[:80]!r}")

print(f"\n=== All windows with 'Edge' in title ===")
for hwnd, title, proc in results:
    if "edge" in title.lower():
        print(f"  hwnd={hwnd} proc={proc} title={title[:80]!r}")
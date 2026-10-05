"""Real-desktop check: focus_window by app name must find windows whose title
is the page title (Edge -> msedge, regardless of "MIO·HUB — 任务总线")."""
import sys

sys.path.insert(0, r"E:\work\code\agent-dev\desktop-agent")

import win32gui
import win32process
from mio_cua.automation.windows import focus_window, get_active_window


def fg_info():
    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd)
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        import ctypes, os
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        buf = ctypes.create_unicode_buffer(512)
        if h:
            ctypes.windll.psapi.GetModuleFileNameExW(h, None, buf, 512)
            ctypes.windll.kernel32.CloseHandle(h)
            proc = os.path.basename(buf.value)
        else:
            proc = "?"
    except Exception as e:
        proc = f"?({e})"
    return title, proc


print("BEFORE:", fg_info())

for target in ("Edge", "Chrome"):
    r = focus_window(target)
    print(f"focus_window({target!r}) -> {r}  fg={fg_info()}")

# a literal title must still work and must NOT be treated as an app name
print("empty ->", focus_window(""))
print("DONE")

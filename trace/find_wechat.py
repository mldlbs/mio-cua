"""Find WeChat windows and their process names."""
import sys
sys.path.insert(0, r"E:\work\code\agent-dev\desktop-agent")
sys.stdout.reconfigure(encoding="utf-8")

import win32gui
import win32process
import psutil

results = []

def enum_callback(hwnd, _):
    if win32gui.IsWindowVisible(hwnd):
        title = win32gui.GetWindowText(hwnd)
        if title:
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc_name = psutil.Process(pid).name()
            except:
                proc_name = "unknown"
            results.append((hwnd, title, proc_name))

win32gui.EnumWindows(enum_callback, None)

print("=== All visible windows ===")
for hwnd, title, proc in results:
    if proc.lower() in ("weixin", "wechat", "wechatapp", "wechatappex", "msedge", "chrome"):
        print(f"  hwnd={hwnd} proc={proc} title={title[:80]!r}")

print("\n=== Checking for WeChat ===")
wechat_found = False
for hwnd, title, proc in results:
    if proc.lower() == "weixin":
        print(f"  FOUND: hwnd={hwnd} title={title!r}")
        wechat_found = True

if not wechat_found:
    print("  WeChat (weixin.exe) NOT found. Available processes:")
    procs = set(p for _, _, p in results)
    for p in sorted(procs):
        if p not in ("unknown",):
            print(f"    {p}")
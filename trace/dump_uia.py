"""Dump UIA tree from WeChat to check if search box is exposed."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import win32gui
from pywinauto import Desktop

fg_hwnd = win32gui.GetForegroundWindow()
print(f"Foreground window: {win32gui.GetWindowText(fg_hwnd)}")

desktop = Desktop(backend="uia")
count = 0
for w in desktop.windows():
    if w.handle != fg_hwnd:
        continue
    if not w.is_visible():
        continue
    for c in w.descendants():
        try:
            info = c.element_info
            text = c.window_text()
            role = info.control_type
            rect = c.rectangle()
            # Show all elements, especially input/search types
            if role in ("Edit", "TextBox", "Search", "ComboBox", "Button") or "搜索" in text or "search" in text.lower():
                print(f"  role={role:15s} text={text[:40]:40s} rect={rect}")
            count += 1
        except Exception:
            continue

print(f"\nTotal UIA elements: {count}")

"""Test perception.observe() without debug logging."""
import sys
sys.path.insert(0, r'E:\work\code\agent-dev\desktop-agent')
sys.stdout.reconfigure(encoding='utf-8')

import time
import win32gui
from mio_cua.automation.windows import focus_window
from mio_cua.perception import Perception

# First focus WeChat
focus_window('WeChat')
time.sleep(2)

# Check active window
hwnd = win32gui.GetForegroundWindow()
text = win32gui.GetWindowText(hwnd)
print(f"Foreground window: {text!r}")

# Now run perception
p = Perception(screenshot_dir=r"E:\work\code\agent-dev\desktop-agent\trace\screenshots")
obs = p.observe()
print(f"Active window: {obs.active_window!r}")
print(f"Active window bytes: {obs.active_window.encode('unicode_escape')}")
print(f"Scene nodes: {len(obs.scene.nodes) if obs.scene else 0}")
if obs.scene:
    for n in obs.scene.nodes:
        if "搜" in (n.text or "") or "search" in (n.text or "").lower():
            print(f"  *** SEARCH: id={n.id} text={n.text!r} bbox={n.bbox}")
        else:
            text_preview = (n.text or "")[:30]
            print(f"  id={n.id} type={n.type} text={text_preview!r} bbox={n.bbox}")
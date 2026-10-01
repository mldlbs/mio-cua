"""Diagnose the capability gaps: icons, taskbar, vision controls."""
import importlib.util as u
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

print("== 1. vision/icon recognition dependencies ==")
for m in ("openai", "rapidocr_onnxruntime", "onnxruntime", "mmdet", "cv2"):
    spec = u.find_spec(m)
    print(f"  {m:26s} {spec.origin if spec else 'MISSING'}")

print("\n== 2. where OmniParser is imported ==")
from mio_cua.perception import perception as P

src = Path(P.__file__).read_text(encoding="utf-8")
for i, line in enumerate(src.splitlines(), 1):
    if "OmniParser" in line or "omniparser" in line or "web controls" in line:
        print(f"  perception.py:{i}: {line.strip()}")

print("\n== 3. does Perception ever see the taskbar? ==")
from mio_cua.automation import windows as W

print(f"  get_active_window_rect defined in: {Path(W.__file__).name}")
import inspect

print(inspect.getsource(W.get_active_window_rect)[:900])

print("\n== 4. screen size vs active-window rect ==")
from mio_cua.vision.screen import capture_rect  # noqa: F401

try:
    import mss

    with mss.mss() as sct:
        mon = sct.monitors[0]
        print(f"  virtual screen: {mon}")
except Exception as e:
    print(f"  mss failed: {e}")

print("\n== 5. tools the agent can call ==")
import pkgutil

import mio_cua.tools as T

mods = sorted(m.name for m in pkgutil.iter_modules(T.__path__))
print(f"  {mods}")
taskbar_like = [m for m in mods if any(k in m for k in
                                        ("taskbar", "start", "tray", "notify", "icon", "win"))]
print(f"  taskbar/icon-related: {taskbar_like or 'NONE'}")

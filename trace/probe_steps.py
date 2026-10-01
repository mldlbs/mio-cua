"""Isolate where check_foreground.py stalls: import, focus, or observe."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

t0 = time.time()


def step(msg):
    print(f"[{time.time() - t0:6.2f}s] {msg}", flush=True)


step("importing scenario module...")
import record_chatgpt_chat as scenario  # noqa: E402

step("imported")
from mio_cua.automation.windows import get_active_window  # noqa: E402

step(f"foreground before focus: {get_active_window()!r}")
scenario._ensure_foreground()
step(f"foreground after focus:  {get_active_window()!r}")

from mio_cua.perception.perception import Perception  # noqa: E402

step("observing...")
obs = Perception(screenshot_dir=str(Path(__file__).resolve().parent / "tmp_probe")).observe()
step(f"observed: {obs.active_window!r} / {obs.active_process!r} "
     f"nodes={len(obs.scene.nodes) if obs.scene else 0}")

left, right, floor = scenario._layout(
    [(n.type, n.text or "", n.bbox) for n in (obs.scene.nodes if obs.scene else [])])
step(f"layout left={left} right={right} floor={floor}")
text, why = scenario._extract_reply(obs)
step(f"extract_reply -> {why}: {text!r}")

"""Report what is in the foreground right now (cheap pre-run sanity check)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from mio_cua.automation.windows import get_active_window
from mio_cua.perception.perception import Perception

import record_chatgpt_chat as scenario  # noqa: E402

# The WorkBuddy popup steals the foreground whenever it feels like it, so read
# the page only after explicitly reclaiming it -- and assert what we got.
scenario._ensure_foreground()
print("foreground:", repr(get_active_window()))

obs = Perception(screenshot_dir=str(Path(__file__).resolve().parent / "screenshots_chatgpt")).observe()
print("active_window:", repr(obs.active_window), "process:", repr(obs.active_process))

nodes = obs.scene.nodes if obs.scene else []
print("nodes:", len(nodes))
for n in nodes:
    t = (n.text or "").strip()
    if any(k in t for k in ("随便问", "有问题", "思考", "你好", "介绍", "发送")):
        print(f"  id={n.id:<4} {n.type:<8} {t[:40]!r:<44} bbox={n.bbox}")

left, right, floor = scenario._layout([(n.type, n.text or "", n.bbox) for n in nodes])
print(f"\npanel x: [{left}, {right}]   composer y: {floor}")

text, why = scenario._extract_reply(obs)
print(f"extract_reply -> {why}: {text!r}")
print(f"char_count={scenario._char_count(text)}")

# Persist as a regression fixture -- but only if we really got the page we
# asked for. WorkBuddy's own window has a composer-looking node too, and a
# fixture captured from it would silently test the wrong layout.
import json  # noqa: E402

if "chrome" in (obs.active_process or "").lower() and "chatgpt" in obs.active_window.lower():
    out = Path(__file__).resolve().parent / "recon_chatgpt_ui.json"
    out.write_text(json.dumps({
        "active_window": obs.active_window,
        "active_process": obs.active_process,
        "node_count": len(nodes),
        "all_nodes": [
            {"id": n.id, "type": n.type, "text": n.text or "", "semantic": n.semantic or "",
             "bbox": list(n.bbox)}
            for n in nodes
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved fixture: {out.name}")
else:
    print(f"NOT saving fixture: wrong window ({obs.active_window!r})")

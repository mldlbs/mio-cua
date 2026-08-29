"""Test perception directly for WeChat."""
import sys
sys.path.insert(0, r'E:\work\code\agent-dev\desktop-agent')
sys.stdout.reconfigure(encoding='utf-8')

from mio_cua.perception import Perception

p = Perception(screenshot_dir=r"E:\work\code\agent-dev\desktop-agent\trace\screenshots")
obs = p.observe()
print(f"Active window: {obs.active_window}")
print(f"Scene nodes: {len(obs.scene.nodes) if obs.scene else 0}")
if obs.scene:
    for n in obs.scene.nodes:
        if "搜" in (n.text or "") or "search" in (n.text or "").lower():
            print(f"  *** SEARCH: id={n.id} text={n.text!r} bbox={n.bbox}")
        else:
            print(f"  id={n.id} type={n.type} text={n.text[:30]!r}")
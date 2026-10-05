"""Test SearchDetector with simulated WeChat data."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from mio_cua.scene.graph import SceneNode, Affordance
from mio_cua.scene.affordances import AffordanceBuilder

# Simulate WeChat scene nodes (what OCR+UIA should produce)
nodes = [
    SceneNode(id=0, type="group", bbox=(982, 219, 880, 640), text="MMUIRenderSubWindowHW", source="uia", role="group"),
    SceneNode(id=1, type="text", bbox=(84, 47, 52, 21), text="Q搜素", source="ocr", role="text", confidence=0.702),
    SceneNode(id=2, type="text", bbox=(322, 46, 46, 18), text="公众号", source="ocr", role="text"),
    SceneNode(id=3, type="text", bbox=(124, 106, 80, 17), text="超图-唐思怡", source="ocr", role="text"),
    SceneNode(id=4, type="text", bbox=(1243, 326, 30, 15), text="17:07", source="uia", role="text"),
    SceneNode(id=5, type="text", bbox=(1098, 452, 54, 21), text="115269", source="uia", role="text"),
]

builder = AffordanceBuilder(nodes, [])
affordances, display_ids = builder.build()

print(f"Affordances: {len(affordances)}")
for a in affordances:
    node = next((n for n in nodes if n.id == a.node_id), None)
    print(f"  node_id={a.node_id} action={a.action} params={a.params} confidence={a.confidence:.2f}")
    if node:
        print(f"    text={node.text!r} bbox={node.bbox}")

# Check if search affordance is detected
search_affs = [a for a in affordances if a.params.get("purpose") == "search"]
print(f"\nSearch affordances: {len(search_affs)}")
for a in search_affs:
    node = next((n for n in nodes if n.id == a.node_id), None)
    if node:
        print(f"  Found: text={node.text!r} at bbox={node.bbox}")

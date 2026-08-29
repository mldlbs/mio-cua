"""Check scene graph data for WeChat steps."""
import json

with open("trace/trace_1787469419.json", "r", encoding="utf-8") as f:
    d = json.load(f)

for i, e in enumerate(d["entries"]):
    obs = e["obs_before"]
    window = obs["active_window"]
    nodes = obs["scene_nodes"]
    node_texts = [n.get("text", "")[:30] for n in nodes[:5]]
    print(f"Step {i}: window={window[:35]!r}  nodes={len(nodes)}  first_texts={node_texts}")

"""Inspect trace structure for replay comparison."""
import json

with open("trace/trace_1787466378.json", "r", encoding="utf-8") as f:
    d = json.load(f)

print(f"entries: {len(d['entries'])}")
for i, e in enumerate(d["entries"][:6]):
    obs = e["obs_before"]
    path = obs.get("screenshot_path", "?")
    short_path = path[-50:] if path else "?"
    print(f"  [{i}] window={obs['active_window'][:40]!r}  nodes={len(obs['scene_nodes'])}  screenshot={short_path}")
    if obs["scene_nodes"]:
        for n in obs["scene_nodes"][:3]:
            print(f"       node: id={n.get('id')} type={n.get('type')} text={n.get('text','')[:30]!r} semantic={n.get('semantic','')[:30]}")

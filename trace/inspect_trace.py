"""Inspect trace data to understand focus_window behavior."""
import json

with open("trace/trace_1787466378.json", "r", encoding="utf-8") as f:
    data = json.load(f)

for i, e in enumerate(data["entries"][:8]):
    obs = e["obs_before"]
    act = e["action"]
    act_str = f"{act['type']}({act['params']})" if act else "None"
    nodes = obs["scene_nodes"]
    print(f"Step {i}: active_window={obs['active_window']!r}, nodes={len(nodes)}, action={act_str}")
    for n in nodes[:3]:
        txt = n.get("text", "")[:60]
        print(f"  node: {txt!r}  type={n.get('type','')}  semantic={n.get('semantic','')}")
    print()

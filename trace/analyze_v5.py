"""Analyze latest trace."""
import json

with open("trace/trace_1787475673.json", "r", encoding="utf-8") as f:
    d = json.load(f)

print(f"Trace: {d['trace_id']}, {len(d['entries'])} steps")
print(f"Status: {d.get('metadata', {}).get('final_status', '?')}")
print()

for i, e in enumerate(d["entries"]):
    obs = e["obs_before"]
    act = e.get("action") or {}
    pr = e.get("planner") or {}
    ds = pr.get("decision_state") or {}
    window = obs.get("active_window", "?")
    nodes = len(obs.get("scene_nodes", []))
    act_type = act.get("type", "?")
    act_params = act.get("params", {})
    resp = pr.get("llm_response", "")
    target_vis = ds.get("target_visible", "?")
    no_prog = ds.get("no_progress_count", 0)

    print(f"Step {i}: window={window[:35]}  nodes={nodes}  target_vis={target_vis}  no_prog={no_prog}  act={act_type}({act_params})")
    if resp:
        print(f"  Response: {resp[:200]}")
    print()

"""Analyze latest trace."""
import json

with open("trace/trace_1787473595.json", "r", encoding="utf-8") as f:
    d = json.load(f)

print(f"Trace: {d['trace_id']}, {len(d['entries'])} steps")
print(f"Status: {d.get('metadata', {}).get('final_status', '?')}")
print()

for i, e in enumerate(d["entries"]):
    obs = e["obs_before"]
    act = e.get("action", {})
    pr = e.get("planner", {})
    meta = e.get("metadata", {})
    window = obs.get("active_window", "?")
    nodes = len(obs.get("scene_nodes", []))
    act_type = act.get("type", "?") if act else "?"
    act_params = act.get("params", {}) if act else {}
    ds = pr.get("decision_state", {}) if pr else {}
    expl = ds.get("strategy_history", []) if ds else []
    no_prog = ds.get("no_progress_count", 0) if ds else 0
    disc = (meta or {}).get("observation_discrepancy", "")
    target_vis = ds.get("target_visible", "?") if ds else "?"

    # Show first few scene node texts for context
    scene_nodes = obs.get("scene_nodes", [])
    node_texts = [n.get("text", "")[:20] for n in scene_nodes[:3]]

    print(f"Step {i:2d}: win={window[:22]:22s} nodes={nodes:3d} "
          f"target_vis={target_vis} no_prog={no_prog} "
          f"act={act_type:15s} params={str(act_params)[:35]:35s} "
          f"disc={disc}")
    if i < 5 or act_type == "success" or act_type == "fail":
        print(f"        scene_preview: {node_texts}")

"""Analyze 4-step trace."""
import glob, os, json

files = glob.glob("trace/trace_*.json")
latest = max(files, key=os.path.getmtime)
with open(latest, "r", encoding="utf-8") as f:
    d = json.load(f)

print(f"Trace: {d['trace_id']}, {len(d['entries'])} steps")
print(f"Status: {d.get('metadata', {}).get('final_status', '?')}")
print()

for i, e in enumerate(d["entries"]):
    obs = e["obs_before"]
    act = e.get("action") or {}
    pr = e.get("planner") or {}
    window = obs.get("active_window", "?")
    nodes = len(obs.get("scene_nodes", []))
    act_type = act.get("type", "?")
    act_params = act.get("params", {})
    resp = pr.get("llm_response", "")

    print(f"Step {i}: window={window[:25]:25s} nodes={nodes:3d} act={act_type:15s} params={act_params}")
    if resp:
        print(f"  Response: {resp[:200]}")
    print()
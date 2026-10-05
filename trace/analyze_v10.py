"""Analyze 30-step trace."""
import glob, os, json

files = glob.glob("trace/trace_*.json")
latest = max(files, key=os.path.getmtime)
print(f"File: {latest}")
with open(latest, "r", encoding="utf-8") as f:
    d = json.load(f)

print(f"Trace: {d['trace_id']}, {len(d['entries'])} steps")
print(f"Status: {d.get('metadata', {}).get('final_status', '?')}")
print()

for i, e in enumerate(d["entries"]):
    obs = e["obs_before"]
    act = e.get("action") or {}
    pr = e.get("planner") or {}
    meta = e.get("metadata") or {}
    window = obs.get("active_window", "?")
    nodes = len(obs.get("scene_nodes", []))
    act_type = act.get("type", "?")
    act_params = act.get("params", {})
    resp = pr.get("llm_response", "")
    err = meta.get("post_action_error", "")
    disc = meta.get("observation_discrepancy", "")

    status = "ERR" if err else "OK"
    print(f"Step {i:2d}: window={window[:20]:20s} nodes={nodes:3d} act={act_type:15s} {status:3s} {err[:40] if err else ''}")

print()
# Show responses for key steps
for i, e in enumerate(d["entries"]):
    pr = e.get("planner") or {}
    resp = pr.get("llm_response", "")
    if resp and i < 5:
        print(f"Step {i} Response: {resp[:200]}")
        print()

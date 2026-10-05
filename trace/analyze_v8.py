"""Analyze latest trace — 20 steps in WeChat."""
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
    disc = meta.get("observation_discrepancy", "")
    err = meta.get("post_action_error", "")

    status = "OK" if not err else "ERR"
    print(f"Step {i}: window={window[:25]:25s} nodes={nodes:3d} act={act_type:15s} {status:3s} {err[:60] if err else ''}")
    if resp and i < 5:
        print(f"  Response: {resp[:150]}")
    print()

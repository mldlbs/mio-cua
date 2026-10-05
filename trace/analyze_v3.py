"""Analyze latest trace."""
import json

with open("trace/trace_1787474676.json", "r", encoding="utf-8") as f:
    d = json.load(f)

print(f"Trace: {d['trace_id']}, {len(d['entries'])} steps")
print(f"Status: {d.get('metadata', {}).get('final_status', '?')}")
print()

for i, e in enumerate(d["entries"]):
    obs = e["obs_before"]
    act = e.get("action") or {}
    pr = e.get("planner") or {}
    meta = e.get("metadata") or {}
    ds = pr.get("decision_state") or {}
    window = obs.get("active_window", "?")
    nodes = len(obs.get("scene_nodes", []))
    act_type = act.get("type", "?")
    act_params = act.get("params", {})
    disc = meta.get("observation_discrepancy", "")
    prompt = pr.get("prompt", "")

    print(f"Step {i}: window={window}  nodes={nodes}  act={act_type}({act_params})  disc={disc}")

    # Show relevant prompt lines
    for line in prompt.split("\n"):
        if any(k in line for k in ["INVARIANT", "CONTEXT STATE", "ALREADY", "context_state", "Scene Summary"]):
            print(f"  >> {line[:150]}")

    # Show response
    resp = pr.get("llm_response", "")
    if resp:
        print(f"  Response: {resp[:200]}")
    print()

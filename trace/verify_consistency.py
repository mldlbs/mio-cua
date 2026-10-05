"""Verify old trace data consistency.

Old trace was recorded with the OLD TraceRecorder (raw observation).
Check: does obs_before match what Planner saw?

For each entry:
1. obs_before.scene node count vs Planner prompt content
2. observation_discrepancy (if present)
3. Planner prompt mentions active_window from obs_before
"""
import json

with open("trace/trace_1787469419.json", "r", encoding="utf-8") as f:
    d = json.load(f)

print(f"Trace: {d['trace_id']}, {len(d['entries'])} entries")
print(f"Metadata: {d.get('metadata', {})}")
print()

for i, e in enumerate(d["entries"]):
    obs = e["obs_before"]
    action = e.get("action", {})
    planner = e.get("planner", {})
    meta = e.get("metadata", {})

    window = obs.get("active_window", "?")
    nodes = obs.get("scene_nodes", [])
    node_count = len(nodes)
    prompt = planner.get("prompt", "") if planner else ""
    prompt_len = len(prompt)

    # Check if prompt mentions the same window as obs_before
    prompt_has_window = window.lower() in prompt.lower() if window else False

    # Check if prompt has exploration hints
    has_exploration = "EXPLORATION" in prompt or "TARGET" in prompt

    # Check observation_discrepancy
    discrepancy = meta.get("observation_discrepancy", None)

    print(f"Step {i}: window={window[:30]!r}  nodes={node_count}  "
          f"prompt_len={prompt_len}  window_in_prompt={prompt_has_window}  "
          f"exploration={has_exploration}  discrepancy={discrepancy}")

    # Show first 200 chars of prompt for WeChat steps
    if "微信" in (window or ""):
        print(f"  Prompt: {prompt[:200]}")
    print()

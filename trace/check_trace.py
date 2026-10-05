"""Check the latest trace file."""
import json
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

trace_files = sorted(Path(r"E:\work\code\agent-dev\desktop-agent\trace").glob("trace_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
if not trace_files:
    print("No trace files found")
    sys.exit(1)

with open(trace_files[0], "r", encoding="utf-8") as f:
    d = json.load(f)

print(f"Trace: {trace_files[0].name}")
print(f"Task: {d['task']['instruction']}")
print(f"Steps: {d['metadata']['steps']}")
print(f"Final: {d['metadata']['final_status']}")
print(f"Summary: {d['metadata']['final_summary']}")
print()

for i, e in enumerate(d["entries"]):
    obs = e["obs_before"]
    act = e.get("action", {})
    pr = e.get("planner", {})
    resp = pr.get("llm_response", "")
    print(f"Step {i}:")
    print(f"  window: {obs.get('active_window')!r}")
    print(f"  nodes: {len(obs.get('scene_nodes', []))}")
    print(f"  action: {act.get('type')}({act.get('params')})")
    print(f"  llm_response: {resp[:200] if resp else '(empty)'}")
    print()
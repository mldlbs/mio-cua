"""Check quality data in new failure report."""
import json

with open("trace/failure_report.json", "r", encoding="utf-8") as f:
    d = json.load(f)

print("Perception config:", json.dumps(d.get("perception_config", {}), indent=2))
print()

for s in d["step_details"]:
    q = s.get("quality", {})
    step = s["step"]
    nodes = s.get("scene_nodes", 0)
    window = s.get("active_window", "?")[:30]
    act = s.get("action_type", "?")
    cls = s.get("classification", "ok")

    if q:
        print(f"Step {step:2d}: [{cls or 'OK':16s}] nodes={nodes:3d} conf={q.get('confidence',0):.3f} usable={q.get('is_usable','?')} act={act} window={window}")
        if q.get("reason") and q["reason"] != "ok":
            print(f"         reason: {q['reason']}")
    else:
        print(f"Step {step:2d}: [{cls or 'OK':16s}] nodes={nodes:3d} quality=None act={act} window={window}")

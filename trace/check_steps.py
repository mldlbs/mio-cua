"""Check Planner prompts for error steps."""
import json

with open("trace/trace_1787473595.json", "r", encoding="utf-8") as f:
    d = json.load(f)

for i in [3, 6, 8]:
    e = d["entries"][i]
    pr = e.get("planner") or {}
    ds = pr.get("decision_state") or {}
    prompt = pr.get("prompt", "")
    resp = pr.get("llm_response", "")
    act = e.get("action") or {}
    print(f"=== Step {i} ===")
    print(f"Action: {act.get('type')}({act.get('params',{})})")
    print(f"decision_state: {json.dumps(ds, ensure_ascii=False)}")
    # Show the exploration hints in prompt
    for line in prompt.split("\n"):
        if "EXPLORATION" in line or "TARGET" in line or "STUCK" in line or "GUIDANCE" in line:
            print(f"  >> {line}")
    print(f"Response: {resp[:300]}")
    print()

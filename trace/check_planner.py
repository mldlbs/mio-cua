"""Inspect planner prompts for WeChat error steps."""
import json

with open("trace/trace_1787469419.json", "r", encoding="utf-8") as f:
    d = json.load(f)

for i, e in enumerate(d["entries"]):
    pr = e.get("planner")
    if pr and i in [3, 7, 9, 15]:
        print(f"=== Step {i} ===")
        act = e.get("action", {})
        print(f"Action: {act.get('type', '?')}({act.get('params', {})})")
        prompt = pr.get("prompt", "")
        response = pr.get("llm_response", "")
        print(f"Prompt (first 600 chars):")
        print(prompt[:600])
        print(f"\nResponse (first 400 chars):")
        print(response[:400])
        print()

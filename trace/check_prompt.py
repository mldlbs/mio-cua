"""Check raw planner prompts for WeChat steps."""
import json

with open("trace/trace_1787469419.json", "r", encoding="utf-8") as f:
    d = json.load(f)

for i in [3, 7, 9]:
    e = d["entries"][i]
    pr = e.get("planner", {})
    prompt = pr.get("prompt", "")
    response = pr.get("llm_response", "")
    act = e.get("action", {})
    print(f"=== Step {i} ===")
    print(f"Action: {act.get('type', '?')}({act.get('params', {})})")
    print(f"Prompt length: {len(prompt)}")
    # Show the scene graph portion (after "## Left sidebar")
    if "## Left sidebar" in prompt:
        idx = prompt.index("## Left sidebar")
        print(f"Scene graph portion (first 400 chars):")
        print(prompt[idx:idx+400])
    else:
        print(f"Prompt (first 400 chars):")
        print(prompt[:400])
    print(f"\nResponse:")
    print(response[:300])
    print()

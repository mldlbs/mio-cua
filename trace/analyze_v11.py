"""Analyze trace — check what Planner receives."""
import glob, os, json

files = glob.glob("trace/trace_*.json")
latest = max(files, key=os.path.getmtime)
print(f"File: {latest}")
with open(latest, "r", encoding="utf-8") as f:
    d = json.load(f)

# Check step 0 prompt for search affordance
e = d["entries"][0]
pr = e.get("planner") or {}
prompt = pr.get("prompt", "")

print("=== Step 0 Prompt (search-related lines) ===")
for line in prompt.split("\n"):
    if any(k in line.lower() for k in ["search", "搜", "affordance", "scene summary", "action candidate"]):
        print(f"  {line[:150]}")

print("\n=== Step 0 LLM Response ===")
resp = pr.get("llm_response", "")
print(f"  {resp[:300]}")

# Check if search affordance is in scene summary
print("\n=== Scene Summary in Prompt ===")
in_summary = False
for line in prompt.split("\n"):
    if "Scene Summary" in line:
        in_summary = True
    if in_summary:
        print(f"  {line[:150]}")
        if line.startswith("##") and "Scene Summary" not in line:
            break

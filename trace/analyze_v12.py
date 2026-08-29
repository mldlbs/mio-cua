"""Check action candidates in prompt."""
import glob, os, json

files = glob.glob("trace/trace_*.json")
latest = max(files, key=os.path.getmtime)
with open(latest, "r", encoding="utf-8") as f:
    d = json.load(f)

e = d["entries"][0]
pr = e.get("planner") or {}
prompt = pr.get("prompt", "")

print("=== Action Candidates ===")
in_candidates = False
for line in prompt.split("\n"):
    if "Action candidates" in line or "action candidate" in line.lower():
        in_candidates = True
    if in_candidates:
        print(f"  {line[:150]}")
        if line.startswith("##") and "Action" not in line:
            break

print("\n=== Full Prompt (last 500 chars) ===")
print(prompt[-500:])

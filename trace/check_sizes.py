"""Check trace prompt and screenshot sizes."""
import json, os

with open("trace/trace_1787474676.json", "r", encoding="utf-8") as f:
    d = json.load(f)

e = d["entries"][0]
pr = e.get("planner") or {}
prompt = pr.get("prompt", "")
obs = e["obs_before"]
spath = obs.get("screenshot_path", "")

print(f"Prompt length: {len(prompt)} chars")
print(f"Screenshot path: {spath}")

if spath and os.path.exists(spath):
    size = os.path.getsize(spath)
    print(f"Screenshot size: {size} bytes ({size/1024:.1f} KB)")
else:
    print("Screenshot not found")

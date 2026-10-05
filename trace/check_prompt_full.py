"""Check full prompt for step 0."""
import json

with open("trace/trace_1787474676.json", "r", encoding="utf-8") as f:
    d = json.load(f)

e = d["entries"][0]
pr = e.get("planner") or {}
prompt = pr.get("prompt", "")
resp = pr.get("llm_response", "")

# Write to file to avoid GBK encoding issues
with open("trace/prompt_step0.txt", "w", encoding="utf-8") as f:
    f.write("=== PROMPT ===\n")
    f.write(prompt)
    f.write("\n\n=== RESPONSE ===\n")
    f.write(resp)

print(f"Prompt length: {len(prompt)} chars")
print(f"Response length: {len(resp)} chars")
print(f"Written to trace/prompt_step0.txt")

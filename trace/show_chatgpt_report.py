"""Print the ChatGPT chat scenario verdict."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

src = Path(__file__).resolve().parent / "failure_report_chatgpt.json"
d = json.loads(src.read_text(encoding="utf-8"))

print("== verdict ==")
for k in ("scenario", "duration_s", "total_steps", "agent_claimed_success",
          "reply_stable", "reply_chars", "max_reply_chars", "premature_claim",
          "valid", "reply_text", "reply_why",
          "reply_at_claim", "reply_at_claim_why", "prompt"):
    print(f"  {k:24s} {d.get(k)!r}")

print("\n== failure summary ==")
for k, v in d.get("failure_summary", {}).items():
    print(f"  {k}: {v}")

print("\n== steps ==")
for s in d.get("step_details", []):
    cat = s.get("classification") or "OK"
    print(f"  {s['step']:2d} [{cat:16s}] act={str(s.get('action_type')):14s} "
          f"nodes={s.get('scene_nodes', 0):3d} win={str(s.get('active_window'))[:36]!r}")

print("\n== planner thoughts ==")
for s in d.get("step_details", []):
    pl = s.get("planner") or {}
    resp = pl.get("llm_response_preview", "")
    if resp:
        print(f"  step {s['step']}: {resp[:180]!r}")

import glob
import json
import os
import sys

files = sorted(glob.glob("trace/trace_*.json"), key=os.path.getmtime)
path = sys.argv[1] if len(sys.argv) > 1 else files[-1]
d = json.load(open(path, encoding="utf-8"))
print("file:", path)
print("meta:", json.dumps(d.get("metadata"), ensure_ascii=False))

entries = d.get("entries") or []
print("entries:", len(entries), "| top keys:", list(d))
for i, e in enumerate(entries):
    ob = e.get("obs_before") or {}
    a = e.get("action") or {}
    pl = e.get("planner") or {}
    print(f"--- step {i}")
    print("   active :", repr(ob.get("active_window")), "| proc:",
          repr(ob.get("active_process")), "| nodes:", ob.get("node_count"))
    print("   actions:", json.dumps(pl.get("parsed_actions"), ensure_ascii=False)[:600])
    print("   decision_state:", json.dumps(pl.get("decision_state"), ensure_ascii=False)[:400])
    raw = json.dumps(pl.get("tool_calls_raw"), ensure_ascii=False)
    print("   tool_calls_raw:", raw[:500])
    resp = pl.get("llm_response")
    if isinstance(resp, dict):
        print("   llm_response keys:", list(resp))
        resp = json.dumps(resp, ensure_ascii=False)
    print("   llm_response:", str(resp)[:700])
    if pl.get("prompt"):
        p = pl["prompt"] if isinstance(pl["prompt"], str) else json.dumps(pl["prompt"], ensure_ascii=False)
        print("   prompt tail:", p[-700:])
    print("   result :", e.get("result"))
    print("   error  :", e.get("error"))

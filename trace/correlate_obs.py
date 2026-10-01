"""Correlate obs_before vs planner.prompt per entry.

A classifier label is only meaningful if the action is judged against the
observation the planner actually saw. If obs_before and planner.active_app
disagree (offset by one), every "planner_error" label is bogus.
"""
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "trace_*.json")),
               key=os.path.getmtime)
path = files[-1]
print("file:", os.path.basename(path))

d = json.load(open(path, encoding="utf-8"))
entries = d.get("entries", [])
print("entries:", len(entries))

if entries:
    ob0 = entries[0].get("obs_before") or {}
    print("obs_before keys:", list(ob0.keys()))

for i, e in enumerate(entries):
    ob = e.get("obs_before") or {}
    pl = e.get("planner") or {}
    pr = pl.get("prompt") or ""
    m = re.search(r'"active_app":\s*"([^"]*)"', pr)
    prompt_win = m.group(1) if m else "(none)"
    act = e.get("action") or {}
    params = act.get("params") or {}
    before_win = ob.get("active_window") or ob.get("window") or "(none)"
    if prompt_win == "(none)":
        # A deterministic step (context-check focus_window) emits no plan.
        flag = "   (no plan — expected for a context-check step)"
    else:
        flag = "" if (prompt_win in before_win or before_win in prompt_win) else "   <<< MISMATCH"
    print(f"{i:>2} | obs_before={before_win[:42]!r}")
    print(f"   | prompt    ={prompt_win[:42]!r}{flag}")
    print(f"   | act={act.get('type')} {json.dumps(params, ensure_ascii=False)[:70]}")

"""Dump one element id from a recorded observation (diagnosis helper)."""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

eid = int(sys.argv[1]) if len(sys.argv) > 1 else 104
files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "trace_*.json")),
               key=os.path.getmtime)
d = json.load(open(files[-1], encoding="utf-8"))
print("file:", os.path.basename(files[-1]))

for i, e in enumerate(d["entries"]):
    ob = e.get("obs_before") or {}
    nodes = ob.get("scene_nodes") or []
    hit = [n for n in nodes if str(n.get("id")) == str(eid)]
    if not hit:
        continue
    ac = e.get("action") or {}
    print(f"--- step {i}  action={ac.get('type')} {json.dumps(ac.get('params'), ensure_ascii=False)}")
    n = hit[0]
    print("    node:", json.dumps(n, ensure_ascii=False)[:400])
    # neighbours: same bbox row, to see what else was clickable there
    bbox = n.get("bbox") or [0, 0, 0, 0]
    near = [x for x in nodes
            if x.get("bbox") and len(x["bbox"]) == 4
            and abs(x["bbox"][1] - bbox[1]) < 40
            and (x.get("text") or "").strip()]
    print("    nearby texts:", [f"{x['id']}:{x['text'][:22]}" for x in near[:14]])

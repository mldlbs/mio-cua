"""Check if scene affordances are in the trace."""
import glob, os, json

files = glob.glob("trace/trace_*.json")
latest = max(files, key=os.path.getmtime)
with open(latest, "r", encoding="utf-8") as f:
    d = json.load(f)

e = d["entries"][0]
obs = e["obs_before"]
scene = obs.get("scene", {})
affordances = scene.get("affordances", [])

print(f"Scene affordances in trace: {len(affordances)}")
for a in affordances:
    print(f"  node_id={a.get('node_id')} action={a.get('action')} params={a.get('params')} confidence={a.get('confidence')}")

# Also check the raw scene nodes
nodes = scene.get("nodes", [])
print(f"\nScene nodes: {len(nodes)}")
for n in nodes:
    print(f"  id={n.get('id')} type={n.get('type')} text={n.get('text','')[:30]}")
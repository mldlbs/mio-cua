"""Extract scene nodes from trace step 0 to check search box."""
import glob, os, json

files = glob.glob("trace/trace_*.json")
latest = max(files, key=os.path.getmtime)
with open(latest, "r", encoding="utf-8") as f:
    d = json.load(f)

# Step 0 is the first WeChat observation
e = d["entries"][0]
obs = e["obs_before"]
nodes = obs.get("scene_nodes", [])
print(f"Step 0: window={obs.get('active_window')}, {len(nodes)} nodes")
print()

for n in nodes:
    nid = n.get("id", "?")
    text = n.get("text", "")
    role = n.get("role", "")
    ntype = n.get("type", "")
    bbox = n.get("bbox", "")
    placeholder = n.get("placeholder", "")
    print(f"  id={nid:3d} role={role:15s} type={ntype:10s} text={text[:40]:40s} placeholder={placeholder} bbox={bbox}")

# Also check step 4 (23 nodes, likely WeChat with more visible)
e4 = d["entries"][4]
obs4 = e4["obs_before"]
nodes4 = obs4.get("scene_nodes", [])
print(f"\nStep 4: window={obs4.get('active_window')}, {len(nodes4)} nodes")
print()

for n in nodes4:
    nid = n.get("id", "?")
    text = n.get("text", "")
    role = n.get("role", "")
    ntype = n.get("type", "")
    bbox = n.get("bbox", "")
    placeholder = n.get("placeholder", "")
    print(f"  id={nid:3d} role={role:15s} type={ntype:10s} text={text[:40]:40s} placeholder={placeholder} bbox={bbox}")

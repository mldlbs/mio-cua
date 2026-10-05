import json
with open(r'E:\work\code\agent-dev\desktop-agent\trace\trace_1787481692.json', 'r', encoding='utf-8') as f:
    d = json.load(f)
e = d['entries'][1]
obs = e['obs_before']
print(f'window={obs.get("active_window")}')
print(f'scene_nodes={len(obs.get("scene_nodes", []))}')
for n in obs.get('scene_nodes', []):
    print(f'  id={n.get("id")} type={n.get("type")} text={n.get("text","")[:30]}')
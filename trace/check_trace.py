import json
with open(r'E:\work\code\agent-dev\desktop-agent\trace\trace_1787488854.json', 'r', encoding='utf-8') as f:
    d = json.load(f)
e = d['entries'][0]
obs = e['obs_before']
print(f'window={obs.get("active_window")}')
print(f'nodes={len(obs.get("scene_nodes", []))}')
print(f'action={e.get("action", {}).get("type")}')
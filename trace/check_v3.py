import json
with open(r'E:\work\code\agent-dev\desktop-agent\trace\trace_1787490466.json', 'r', encoding='utf-8') as f:
    d = json.load(f)
e = d['entries'][0]
obs = e['obs_before']
act = e.get('action', {})
pr = e.get('planner', {})
print(f'window={obs.get("active_window")!r}')
print(f'nodes={len(obs.get("scene_nodes", []))}')
print(f'action={act.get("type")}({act.get("params")})')
resp = pr.get('llm_response', '')
print(f'resp={resp[:200]}')
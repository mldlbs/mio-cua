"""Add debug to see what Planner receives."""
import json
with open(r'E:\work\code\agent-dev\desktop-agent\trace\trace_1787480798.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

e = d['entries'][0]
pr = e.get('planner') or {}
print(f"Prompt length: {len(pr.get('prompt', ''))}")
print(f"Response: '{pr.get('llm_response', '')}'")
print(f"Response length: {len(pr.get('llm_response', ''))}")
print(f"Parsed: {pr.get('parsed', {})}")
print(f"Error: {pr.get('error', '')}")

# Check the prompt for context_state
prompt = pr.get('prompt', '')
for line in prompt.split('\n'):
    if 'context_state' in line or 'context_verified' in line or 'active_app' in line or 'target_app' in line:
        print(f"  {line}")
import requests
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

url = 'http://127.0.0.1:8000/v1/chat/completions'
headers = {
    'Authorization': 'Bearer sk-xzv73DsVZtWggFbm06xk4XH3lbLNO7RlbE2Fd0UXawhSopFyif1nixnNPfPzxkkJ',
    'User-Agent': 'Mozilla/5.0',
    'Content-Type': 'application/json',
}
body = {
    'model': 'mimo-v2.5-free',
    'messages': [
        {'role': 'user', 'content': 'Say hello'}
    ],
    'temperature': 0.2,
    'max_tokens': 4096,
}
resp = requests.post(url, headers=headers, json=body, timeout=60)
print(f'Status: {resp.status_code}')
data = resp.json()
msg = data['choices'][0]['message']
print(f'Message keys: {list(msg.keys())}')
print(f'Content: {msg.get("content")!r}')
print(f'Reasoning: {msg.get("reasoning")!r}')
print(f'Finish reason: {data["choices"][0].get("finish_reason")}')
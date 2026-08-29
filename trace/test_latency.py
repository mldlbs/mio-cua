"""Test proxy latency."""
import urllib.request, json, time

data = json.dumps({
    "model": "mimo-v2.5-free",
    "messages": [{"role": "user", "content": "say hi"}],
    "max_tokens": 20,
}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8000/v1/chat/completions",
    data=data,
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer sk-xzv73DsVZtWggFbm06xk4XH3lbLNO7RlbE2Fd0UXawhSopFyif1nixnNPfPzxkkJ",
    },
)
start = time.time()
r = urllib.request.urlopen(req, timeout=120)
elapsed = time.time() - start
resp = json.loads(r.read().decode())
msg = resp["choices"][0]["message"]
print(f"Time: {elapsed:.1f}s")
print(f"Content: {msg.get('content', '')[:100]}")
print(f"Reasoning: {msg.get('reasoning', '')[:100]}")

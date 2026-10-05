"""Test LLM call with image."""
import urllib.request, json, time, base64

with open("trace/artifacts_v2/1787474429823.png", "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

data = json.dumps({
    "model": "mimo-v2.5-free",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Describe what you see in 10 words."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
    ]}],
    "max_tokens": 30,
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
content = msg.get("content") or ""
reasoning = msg.get("reasoning") or ""
print(f"Time: {elapsed:.1f}s")
print(f"Content: {content[:200]}")
print(f"Reasoning: {reasoning[:200]}")

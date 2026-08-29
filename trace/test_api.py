"""Test API connectivity."""
import urllib.request, json, time

API_KEY = "sk-c88cbfae818644c8d1c3dac11972b541956142e7b666cfe2fd7399b3994d8b5f"
BASE_URL = "https://ai.crlkcloud.cyou/v1"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

models = ["mimo-v2.5-free", "hy3-free", "nemotron-3.5-lightning-free", "x-preview-f-free"]

for model in models:
    time.sleep(3)
    data = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "say hi"}],
        "max_tokens": 10,
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
            "User-Agent": UA,
        },
    )
    try:
        r = urllib.request.urlopen(req, timeout=30)
        resp = json.loads(r.read().decode())
        content = resp["choices"][0]["message"]["content"]
        print(f"OK  {model}: {content[:50]}")
    except Exception as e:
        code = getattr(e, "code", None)
        body = ""
        if hasattr(e, "read"):
            body = e.read().decode()[:100]
        print(f"ERR {model}: {code} {body or e}")

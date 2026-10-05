"""验证 LLM 层（复用 mio-cua provider 的请求格式）能否打通配置的 endpoint。

用途：在跑 `mio-cua run` 之前先确认 LLM 通路，避免真实操作桌面一半才 401。
不依赖 requests / curl，纯标准库；请求格式与 mio_cua/providers/openai_compat.py 一致。

本机用法：
    .venv/Scripts/python.exe experiments/verify_llm.py --config config.zen.yaml
    .venv/Scripts/python.exe experiments/verify_llm.py --config config.proxy.yaml

判定：
    - 打印 "key set? = False"  -> 变量没设，必然 401，先设 key
    - HTTP 200 + REPLY: ...    -> LLM 通了，可跑真实任务
    - HTTP 401 Missing/Invalid -> key 不对或 zen-proxy 服务端 PROVIDER_ZEN_API_KEY 没配
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, ".")

from mio_cua.config import AgentConfig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.zen.yaml")
    args = ap.parse_args()

    cfg = AgentConfig.from_yaml(args.config)
    key = cfg.api_key()
    endpoint = cfg.base_url.rstrip("/") + "/chat/completions"

    print(f"config   = {args.config}")
    print(f"endpoint = {endpoint}")
    print(f"model    = {cfg.model}")
    print(f"key set? = {bool(key)} (len={len(key) if key else 0})")

    body = json.dumps({
        "model": cfg.model,
        "messages": [{"role": "user", "content": "reply with the single word OK"}],
        "temperature": 0.2,
        "max_tokens": 20,
    }).encode("utf-8")

    req = urllib.request.Request(endpoint, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    if key:
        req.add_header("Authorization", f"Bearer {key}")

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read().decode("utf-8")
            print(f"HTTP {r.status}")
            try:
                j = json.loads(data)
                print("REPLY:", repr(j["choices"][0]["message"]["content"]))
            except Exception:
                print(data[:500])
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}")
        print(e.read().decode("utf-8")[:500])
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()

import os

from mio_cua.providers.openai_compat import OpenAICompatProvider

BASE = "https://ai.crlkcloud.cyou/v1"
KEY = os.environ.get("CK_API_KEY", "")
MODEL = os.environ.get("CK_MODEL", "default")

p = OpenAICompatProvider(base_url=BASE, api_key=KEY, model=MODEL, timeout=60)
print(f"provider: base_url={BASE} model={MODEL} key={'set' if KEY else 'MISSING'}")

r = p.generate([{"role": "user", "content": "Reply with the single word OK."}])
print("message      :", repr(r.message))
print("tool_calls   :", len(r.tool_calls))
print("finish_reason:", r.finish_reason)
print("usage        :", r.usage)
assert r.message.strip(), "empty message"
print("\nPROVIDER OK")

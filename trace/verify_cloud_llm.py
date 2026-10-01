import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://ai.crlkcloud.cyou/v1"
KEY = os.environ.get("CK_API_KEY", "")
MODEL = sys.argv[1] if len(sys.argv) > 1 else "gpt-5.5"
# Cloudflare 1010 = "banned based on your browser's signature"; urllib's
# default "Python-urllib/3.x" UA is rejected, a browser UA is accepted.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _open(req, use_proxy):
    opener = (
        urllib.request.build_opener()  # honor system proxy
        if use_proxy
        else urllib.request.build_opener(urllib.request.ProxyHandler({}))
    )
    return opener.open(req, timeout=30)


def try_call(label, req_factory, use_proxy):
    try:
        resp = _open(req_factory(), use_proxy)
        body = resp.read().decode("utf-8", "replace")
        return resp.status, body[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def models_req():
    r = urllib.request.Request(BASE + "/models")
    r.add_header("Authorization", f"Bearer {KEY}")
    r.add_header("User-Agent", UA)
    return r


def chat_req():
    payload = json.dumps(
        {"model": MODEL, "max_tokens": 16,
         "messages": [{"role": "user", "content": "reply with the single word OK"}]}
    ).encode()
    r = urllib.request.Request(BASE + "/chat/completions", data=payload)
    r.add_header("Authorization", f"Bearer {KEY}")
    r.add_header("User-Agent", UA)
    r.add_header("Content-Type", "application/json")
    return r


print(f"BASE={BASE} MODEL={MODEL} key_set={bool(KEY)}\n")

for label, factory in (("/models", models_req), ("/chat/completions", chat_req)):
    for use_proxy in (True, False):
        tag = f"{label} proxy={'on' if use_proxy else 'off'}"
        code, body = try_call(tag, factory, use_proxy)
        mark = "OK  " if code == 200 else ("BAD " if code else "FAIL")
        print(f"[{mark}] {tag:38} -> {code} {body[:200]}")
        if code == 200:
            print("    raw:", body)
    print()


# Does the endpoint accept a completion with NO model field (i.e. does it
# expose a provider-side default we can inherit)?
def chat_no_model():
    payload = json.dumps(
        {"max_tokens": 16,
         "messages": [{"role": "user", "content": "reply with the single word OK"}]}
    ).encode()
    r = urllib.request.Request(BASE + "/chat/completions", data=payload)
    r.add_header("Authorization", f"Bearer {KEY}")
    r.add_header("User-Agent", UA)
    r.add_header("Content-Type", "application/json")
    return r


code, body = try_call("chat w/o model", chat_no_model, True)
print(f"[{'OK  ' if code == 200 else 'BAD '}] {'chat w/o model':38} -> {code}")
print("    raw:", body)

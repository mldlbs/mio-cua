"""Identify who returns 403 for chatgpt.com through the local proxy.

403 from a proxy egress usually means one of:
  * Cloudflare bot challenge (we can pass it with browser headers)
  * OpenAI blocking the datacentre IP of the egress (needs a different exit)
  * the proxy itself refusing (then the body says so)
The body + headers tell us which, and that decides whether a real Edge
browser -- which uses the same WinINET proxy -- can open the site at all.
"""

import gzip
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

PROXY = "http://127.0.0.1:7990"

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Priority": "u=0, i",
}


def fetch(url, headers):
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    try:
        with opener.open(req, timeout=25) as r:
            raw = r.read(6000)
            if r.headers.get("Content-Encoding") == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass
            print(f"  {r.status} {url}")
            print(f"      server: {r.headers.get('Server')!r} "
                  f"cf-ray: {r.headers.get('cf-ray')!r} "
                  f"x-openai: {bool(r.headers.get('x-openai-...') or r.headers.get('openai-processing-ms'))}")
            print(f"      body[:500]: {raw[:500].decode('utf-8', 'replace')!r}")
            return r.status
    except urllib.error.HTTPError as e:
        raw = e.read(6000)
        if e.headers.get("Content-Encoding") == "gzip":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        print(f"  {e.code} {url}")
        print(f"      server: {e.headers.get('Server')!r} cf-ray: {e.headers.get('cf-ray')!r}")
        print(f"      body[:600]: {raw[:600].decode('utf-8', 'replace')!r}")
        return e.code
    except Exception as e:
        print(f"  ERR {url}: {type(e).__name__}: {str(e)[:120]}")
        return None


print("== chatgpt.com with full browser fingerprint ==")
fetch("https://chatgpt.com/", BROWSER_HEADERS)

print("\n== same, but through a Cloudflare-friendly path (root only) ==")
fetch("https://chatgpt.com/cdn-cgi/trace", {
    "User-Agent": BROWSER_HEADERS["User-Agent"],
    "Accept": "*/*",
})

print("\n== control: an OpenAI-adjacent host through the same proxy ==")
fetch("https://api.openai.com/v1/models", {
    "User-Agent": BROWSER_HEADERS["User-Agent"],
    "Accept": "application/json",
})

print("\n== control: a neutral site through the same proxy ==")
fetch("https://example.com/", BROWSER_HEADERS)

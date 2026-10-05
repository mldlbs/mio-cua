"""Diagnose why chatgpt.com timed out: DNS, proxy, or the site itself."""

import socket
import ssl
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Local WinINET proxy seen on this box; may be a real egress proxy or dead.
PROXY = "http://127.0.0.1:7990"

HOSTS = ["chatgpt.com", "chat.openai.com", "www.bing.com", "ai.crlkcloud.cyou"]

print("== DNS ==")
for h in HOSTS:
    try:
        infos = socket.getaddrinfo(h, 443, socket.AF_INET)
        addrs = sorted({i[4][0] for i in infos})
        print(f"  {h:26s} -> {addrs[:3]}")
    except Exception as e:
        print(f"  {h:26s} -> FAIL {type(e).__name__}: {e}")


def probe(label, url, proxies=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    handlers = [urllib.request.ProxyHandler(proxies or {})]
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=15) as r:
            print(f"  [{label}] {r.status} {url} -> {r.geturl()[:80]}")
    except urllib.error.HTTPError as e:
        print(f"  [{label}] HTTP {e.code} {url}")
    except Exception as e:
        print(f"  [{label}] FAIL {type(e).__name__}: {str(e)[:90]}")


print("\n== HTTPS via DIRECT (no proxy) ==")
for u in ("https://www.bing.com/", "https://chatgpt.com/"):
    probe("direct", u)

print("\n== HTTPS via LOCAL PROXY", PROXY, "==")
for u in ("https://www.bing.com/", "https://chatgpt.com/", "https://chat.openai.com/"):
    probe("proxy", u, {"http": PROXY, "https": PROXY})

print("\n== HTTPS via SYSTEM DEFAULT (proxy env / wininet) ==")
for u in ("https://www.bing.com/", "https://chatgpt.com/"):
    probe("system", u, urllib.request.getproxies() or {})

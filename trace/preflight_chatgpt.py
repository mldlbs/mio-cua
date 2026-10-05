"""Preflight: is the ChatGPT web app reachable from this machine?

Answers three questions before we build a scenario around it:
  1. network reachability (this box has flaky TLS + a dead WinINET proxy)
  2. login wall (an auth redirect means the scenario needs a signed-in profile)
  3. which origin actually serves the app (chatgpt.com vs an auth mirror)
"""

import ssl
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

TARGETS = [
    "https://chatgpt.com/",
    "https://chatgpt.com/backend-api/lig?device_type=Platform",
    "https://chat.openai.com/",
]


def probe(url: str) -> None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    # Bypass the WinINET proxy: it has pointed at a dead port on this box.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=20) as resp:
            body = resp.read(4000)
            print(f"  {resp.status} {url}")
            print(f"      final-url: {resp.geturl()}")
            text = body.decode("utf-8", "replace")
            lowered = text.lower()
            for marker, label in (
                ("login", "LOGIN marker"),
                ("auth", "AUTH marker"),
                ("turnstile", "CAPTCHA/turnstile marker"),
                ("cf-chl", "CLOUDFLARE challenge marker"),
            ):
                if marker in lowered:
                    print(f"      {label}: present in first 4KB")
            print(f"      first-120: {text[:120]!r}")
    except urllib.error.HTTPError as e:
        print(f"  {e.code} {url}")
        try:
            print(f"      body: {e.read(300)!r}")
        except Exception:
            pass
    except Exception as e:
        print(f"  ERR {url}: {type(e).__name__}: {e}")


print("Probing ChatGPT web endpoints (no proxy, browser UA)...")
ctx = ssl.create_default_context()
for u in TARGETS:
    probe(u)

print("\nNote: this only proves reachability. Whether the app is usable")
print("without a signed-in profile still has to be checked in a live run.")

"""Debug context_verified for WeChat."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

target_app = "WeChat"
active_window = "微信"

# Check aliases
_ALIASES = {"wechat": "微信", "chrome": "Chrome", "firefox": "Firefox", "edge": "Edge"}
target_proc = _ALIASES.get(target_app.lower(), "")
print(f"target_app={target_app}, active_window={active_window}")
print(f"target_proc={target_proc}")

context_verified = bool(
    target_app and (
        active_window.lower() == target_app.lower()
        or target_proc and target_proc in active_window.lower()
    )
)
print(f"context_verified={context_verified}")

# Also check lowercase
print(f"target_app.lower()={target_app.lower()}")
print(f"active_window.lower()={active_window.lower()}")
print(f"target_proc in active_window.lower()={target_proc in active_window.lower()}")
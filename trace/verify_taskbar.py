"""Verify taskbar tool registration and safe (non-clicking) paths."""
import json
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from mio_cua.tools.builtin import _SCHEMAS, register_builtin_tools
from mio_cua.tools.context import ToolContext
from mio_cua.tools.registry import ToolRegistry

reg = ToolRegistry()
register_builtin_tools(reg)

print("schema present:", "taskbar" in _SCHEMAS)
print("schema params  :", sorted(_SCHEMAS["taskbar"]["function"]["parameters"]["properties"]))

ctx = ToolContext(
    controller=None, perception=None, config=None, events=None, current_action_id="t-1"
)

t = time.time()
res = reg.call("taskbar", {"action": "list"}, ctx)
dt = time.time() - t
print(f"list: success={res.success} retryable={res.retryable} in {dt:.2f}s")
payload = json.loads(res.message)
print("  count:", payload["count"], "truncated:", payload["truncated"])
names = [i["name"] for i in payload["items"]]
print("  has kai:", "\u5f00\u59cb" in names)
print("  has sou:", "\u641c\u7d22" in names)
print("  running-app:", [n for n in names if re.search(r"- \d+ \u4e2a\u8fd0\u884c\u7a97\u53e3", n)][:3])
print("  root skipped:", "" not in names)
print("  all rects len4:", all(len(i["rect"]) == 4 for i in payload["items"]))

res = reg.call("taskbar", {"action": "bogus"}, ctx)
print(f"unknown action: success={res.success} retryable={res.retryable} msg={res.message[:50]!r}")

res = reg.call("taskbar", {"action": "click", "target": "  "}, ctx)
print(f"blank target  : success={res.success} retryable={res.retryable} msg={res.message[:50]!r}")

res = reg.call("taskbar", {"action": "click", "target": "zzz-absent"}, ctx)
print(f"no match      : success={res.success} retryable={res.retryable} msg={res.message[:50]!r}")

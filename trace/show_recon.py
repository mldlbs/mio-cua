"""Print the captured ChatGPT page nodes (recon result viewer)."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

src = Path(__file__).resolve().parent / "recon_chatgpt.json"
d = json.loads(src.read_text(encoding="utf-8"))

print(f"window: {d['active_window']!r}  process: {d['active_process']!r}")
print(f"nodes: {d['node_count']}  flat elements: {d['element_count']}")

# The composer and the send control are what the scenario must target.
INTEREST = ("有问题", "随便问", "思考", "发送", "chatgpt", "你好", "准备", "聊天", "工作")
print("\n-- composer / greeting / send candidates --")
for n in d["all_nodes"]:
    t = n["text"]
    if any(k in t for k in INTEREST) or n["type"] in ("input", "button", "textbox"):
        print(f"  id={n['id']:<4} type={n['type']:<8} {t[:50]!r:<54} bbox={n['bbox']}")

print("\n-- every node, in id order --")
for n in sorted(d["all_nodes"], key=lambda x: x["id"]):
    print(f"  {n['id']:<4} {n['type']:<8} {n['text'][:52]!r:<56} {n['bbox']}")

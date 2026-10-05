"""Print the composer-row and sidebar geometry of the UIA fixture."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

src = Path(__file__).resolve().parent / "recon_chatgpt_ui.json"
nodes = json.loads(src.read_text(encoding="utf-8"))["all_nodes"]


def show(label, sel):
    print(f"\n-- {label} --")
    for n in sorted(sel, key=lambda n: n["bbox"][1]):
        b = n["bbox"]
        print(f"  y={b[1]:4d} x={b[0]:4d} w={b[2]:4d} h={b[3]:4d} "
              f"{n['type']:<8} {n['text'][:46]!r}")


show("composer row band (y 600..950, x>=600)",
     [n for n in nodes if 600 <= n["bbox"][1] <= 950 and n["bbox"][0] >= 600])
show("sidebar (x < 600, y 600..950)",
     [n for n in nodes if n["bbox"][0] < 600 and 600 <= n["bbox"][1] <= 950])
show("groups spanning wide",
     [n for n in nodes if n["type"] == "group" and n["bbox"][2] >= 400])

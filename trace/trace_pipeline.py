"""Trace the full perception pipeline for WeChat to find where search box is lost."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
import numpy as np

# Step 1: OCR on the screenshot
engine = RapidOCR()
img = Image.open("trace/screenshots/obs_000.png")
img_array = np.array(img)
result, _ = engine(img_array)

print(f"=== OCR Raw Results ({len(result)} elements) ===")
ocr_elements = []
for i, (box, text, score) in enumerate(result):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    left, top = int(min(xs)), int(min(ys))
    width, height = int(max(xs) - left), int(max(ys) - top)
    text = str(text)
    print(f"  [{i:2d}] text={text!r:30s} score={float(score):.3f} bbox=({left},{top},{width},{height})")
    if "搜" in text or "search" in text.lower():
        print(f"       ^^^ SEARCH BOX FOUND IN OCR")

# Step 2: Check if search box is in the 9-node trace
import json
with open("trace/trace_1787476618.json", "r", encoding="utf-8") as f:
    d = json.load(f)
e = d["entries"][0]
obs = e["obs_before"]
nodes = obs.get("scene_nodes", [])
print(f"\n=== Scene Graph Nodes ({len(nodes)} nodes) ===")
for n in nodes:
    text = n.get("text", "")
    print(f"  text={text!r:30s} type={n.get('type','?')}")
    if "搜" in text:
        print(f"       ^^^ SEARCH BOX IN SCENE GRAPH")

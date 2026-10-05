"""Debug full pipeline: OCR -> Merger -> NodeBuilder"""
import sys
sys.path.insert(0, r'E:\work\code\agent-dev\desktop-agent')
sys.stdout.reconfigure(encoding='utf-8')

from PIL import Image
import numpy as np
from rapidocr_onnxruntime import RapidOCR
from mio_cua.models.element import Element
from mio_cua.perception.merger import merge
from mio_cua.scene.builder import NodeBuilder

# OCR
engine = RapidOCR()
img = Image.open("trace/screenshots/obs_001.png")
img_array = np.array(img)
result, _ = engine(img_array)

ocr_elements = []
for i, (box, text, score) in enumerate(result):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    left, top = int(min(xs)), int(min(ys))
    width, height = int(max(xs) - left), int(max(ys) - top)
    text = str(text)
    ocr_elements.append(Element(
        id=i, source="ocr", text=text, role="text",
        bbox=(left, top, width, height), confidence=float(score),
    ))

print(f"OCR elements: {len(ocr_elements)}")
for e in ocr_elements:
    if "搜" in e.text or "search" in e.text.lower():
        print(f"  *** SEARCH: {e.text!r} bbox={e.bbox}")

# UIA elements (from trace)
uia_elements = [
    Element(id=0, source="uia", text="MMUIRenderSubWindowHW", role="group", bbox=(985, 180, 880, 640)),
    Element(id=1, source="uia", text="18:36", role="text", bbox=(1248, 289, 30, 15)),
    Element(id=2, source="uia", text="17:28", role="text", bbox=(1248, 352, 30, 16)),
    Element(id=3, source="uia", text="hao", role="text", bbox=(1099, 371, 30, 18)),
    Element(id=4, source="uia", text="17:18", role="text", bbox=(1249, 418, 29, 13)),
    Element(id=5, source="uia", text="17:18", role="text", bbox=(1099, 420, 30, 13)),
    Element(id=6, source="uia", text="115269", role="text", bbox=(1099, 453, 54, 21)),
    Element(id=7, source="uia", text="16:18", role="text", bbox=(1248, 456, 29, 13)),
    Element(id=8, source="uia", text="14:34", role="text", bbox=(1248, 522, 28, 13)),
    Element(id=9, source="uia", text="12:07", role="text", bbox=(1248, 587, 28, 13)),
]

print(f"\nUIA elements: {len(uia_elements)}")

# Merge
merged = merge(ocr_elements, uia_elements)
print(f"\nMerged elements: {len(merged)}")
for e in merged:
    if "搜" in (e.text or "") or "search" in (e.text or "").lower():
        print(f"  *** SEARCH: {e.text!r} source={e.source} bbox={e.bbox}")

# NodeBuilder
nodes = NodeBuilder(merged).build()
print(f"\nScene nodes: {len(nodes)}")
for n in nodes:
    if "搜" in (n.text or "") or "search" in (n.text or "").lower():
        print(f"  *** SEARCH: id={n.id} text={n.text!r} bbox={n.bbox}")
    else:
        text_preview = (n.text or "")[:30]
        print(f"  id={n.id} type={n.type} text={text_preview!r} bbox={n.bbox}")
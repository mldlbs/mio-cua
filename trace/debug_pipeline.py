"""Debug: trace where search box is lost in the pipeline."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from mio_cua.models.element import Element
from mio_cua.scene.builder import NodeBuilder
from mio_cua.perception.merger import merge

# Simulate the elements from the trace
# UIA elements (9 nodes from trace: MMUIRenderSubWindowHW + timestamps)
uia_elements = [
    Element(id=0, source="uia", text="MMUIRenderSubWindowHW", role="group", bbox=(982, 219, 880, 640)),
    Element(id=1, source="uia", text="17:07", role="text", bbox=(1243, 326, 30, 15)),
    Element(id=2, source="uia", text="16:42", role="text", bbox=(1244, 392, 28, 13)),
    Element(id=3, source="uia", text="115269", role="text", bbox=(1098, 452, 54, 21)),
    Element(id=4, source="uia", text="16:18", role="text", bbox=(1243, 455, 31, 17)),
    Element(id=5, source="uia", text="15:35", role="text", bbox=(1244, 522, 28, 13)),
    Element(id=6, source="uia", text="15:35", role="text", bbox=(1244, 587, 28, 13)),
    Element(id=7, source="uia", text="14:34", role="text", bbox=(1243, 650, 30, 16)),
    Element(id=8, source="uia", text="12:07", role="text", bbox=(1243, 716, 29, 15)),
]

# OCR elements (48 from OCR, including search box)
ocr_elements = [
    Element(id=0, source="ocr", text="公众号", role="text", bbox=(322, 46, 46, 18), confidence=0.669),
    Element(id=1, source="ocr", text="Q搜素", role="text", bbox=(84, 47, 52, 21), confidence=0.702),
    Element(id=2, source="ocr", text="常看的号", role="text", bbox=(332, 95, 50, 16), confidence=0.743),
    # ... more elements
]

print("=== Before Merge ===")
print(f"UIA: {len(uia_elements)} elements")
print(f"OCR: {len(ocr_elements)} elements")

# Check overlap for search box
search_box = ocr_elements[1]
print(f"\nSearch box: text={search_box.text!r} bbox={search_box.bbox}")
for u in uia_elements:
    ax, ay, aw, ah = search_box.bbox
    bx, by, bw, bh = u.bbox
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    overlap = ix * iy
    smaller = min(aw * ah, bw * bh)
    ratio = overlap / smaller if smaller > 0 else 0
    if ratio > 0:
        print(f"  Overlaps with UIA id={u.id} text={u.text!r} ratio={ratio:.3f}")

merged = merge(ocr_elements, uia_elements)
print(f"\n=== After Merge ===")
print(f"Merged: {len(merged)} elements")
for e in merged:
    print(f"  id={e.id} source={e.source} text={e.text!r} bbox={e.bbox}")

# Check if search box is in merged
search_in_merged = [e for e in merged if "搜" in (e.text or "")]
print(f"\nSearch box in merged: {search_in_merged}")

# Build nodes
nodes = NodeBuilder(merged).build()
print(f"\n=== After NodeBuilder ===")
print(f"Nodes: {len(nodes)}")
for n in nodes:
    print(f"  id={n.id} type={n.type} text={n.text!r}")

search_in_nodes = [n for n in nodes if "搜" in (n.text or "")]
print(f"\nSearch box in nodes: {search_in_nodes}")

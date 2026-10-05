"""Diagnostic: test OCR on WeChat window."""
import sys
sys.path.insert(0, r"E:\work\code\agent-dev\desktop-agent")
sys.stdout.reconfigure(encoding="utf-8")

from mio_cua.automation.windows import get_active_window, get_active_window_rect, set_dpi_aware, focus_window
from mio_cua.perception.merger import merge
from mio_cua.vision import ocr as ocr_module
from mio_cua.automation import uia as uia_module
from mio_cua.scene import build_scene
from mio_cua.vision.screen import capture_rect
from mio_cua.perception.perception import _shift_bbox
import numpy as np
import time

set_dpi_aware()

# Focus WeChat first
print("=== Focusing WeChat ===")
result = focus_window("WeChat")
print(f"  focus_window returned: {result}")
time.sleep(1)

print("\n=== Step 1: Active Window ===")
try:
    rect = get_active_window_rect()
    print(f"  rect = {rect}")
except Exception as e:
    print(f"  rect FAILED: {e}")
    rect = (0, 0, 0, 0)

try:
    active = get_active_window()
    print(f"  active_window = {active!r}")
except Exception as e:
    print(f"  active_window FAILED: {e}")
    active = ""

print("\n=== Step 2: Screenshot ===")
img = capture_rect(rect)
print(f"  img size = {img.size}")
img.save(r"E:\work\code\agent-dev\desktop-agent\trace\diag_wechat.png")

print("\n=== Step 3: OCR ===")
try:
    img_array = np.array(img)
    ocr_elements = list(ocr_module.get_elements(img_array))
    print(f"  OCR found {len(ocr_elements)} elements")
    for e in ocr_elements:
        print(f"    [{e.source}] id={e.id} text={e.text!r} bbox={e.bbox} conf={e.confidence:.2f}")
except Exception as e:
    print(f"  OCR FAILED: {e}")
    ocr_elements = []

# Shift OCR bbox to screen coordinates
ocr_shifted = []
for e in ocr_elements:
    e.bbox = _shift_bbox(e.bbox, rect[0], rect[1])
    ocr_shifted.append(e)

print("\n=== Step 4: UIA ===")
try:
    uia_elements = list(uia_module.get_elements())
    print(f"  UIA found {len(uia_elements)} elements")
    for e in uia_elements:
        print(f"    [{e.source}] id={e.id} text={e.text!r} role={e.role!r} bbox={e.bbox}")
except Exception as e:
    print(f"  UIA FAILED: {e}")
    uia_elements = []

print("\n=== Step 5: Merge ===")
merged = merge(ocr_shifted, uia_elements)
print(f"  Merged: {len(merged)} elements")

print("\n=== Step 6: Build Scene ===")
scene = build_scene(merged, active)
print(f"  Nodes: {len(scene.nodes)}")
for n in scene.nodes:
    print(f"    [{n.source}] id={n.id} type={n.type!r} text={n.text!r} role={n.role!r}")
print(f"  Affordances: {len(scene.affordances)}")
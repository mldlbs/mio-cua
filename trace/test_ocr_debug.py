"""Test perception with OCR debug."""
import sys
sys.path.insert(0, r'E:\work\code\agent-dev\desktop-agent')
sys.stdout.reconfigure(encoding='utf-8')

import time
import win32gui
from mio_cua.automation.windows import focus_window, get_active_window_rect, get_active_window
from mio_cua.vision.screen import capture_rect
from mio_cua.vision import ocr as ocr_module
import numpy as np
from mio_cua.perception.perception import _content_signature

# First focus WeChat
focus_window('WeChat')
time.sleep(2)

rect = get_active_window_rect()
active_window = get_active_window()
print(f"rect: {rect}")
print(f"active_window: {active_window!r}")

img = capture_rect(rect)
print(f"Captured image size: {img.size}")

sig = (active_window, rect, _content_signature(img))
print(f"Signature: active_window={sig[0]!r}, rect={sig[1]}, sig_hash={hash(sig[2]) if sig[2] else 'None'}")

# Run OCR directly
img_array = np.array(img)
result = ocr_module.get_elements(img_array)
print(f"OCR returned {len(result)} elements:")
for e in result[:10]:
    text = (e.text or "").strip()
    if text:
        print(f"  text={text!r:30s} bbox={e.bbox} conf={e.confidence:.3f}")
    if "搜" in text or "search" in text.lower():
        print(f"  *** SEARCH: text={text!r} bbox={e.bbox}")

# Check if search box is in OCR results
search_found = any("搜" in (e.text or "") or "search" in (e.text or "").lower() for e in result)
print(f"\nSearch box in OCR: {search_found}")
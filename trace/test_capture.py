"""Check window rect and capture for WeChat."""
import sys
sys.path.insert(0, r'E:\work\code\agent-dev\desktop-agent')
sys.stdout.reconfigure(encoding='utf-8')

import time
import win32gui
from mio_cua.automation.windows import get_active_window_rect, focus_window
from mio_cua.vision.screen import capture_rect

# First focus WeChat
focus_window('WeChat')
time.sleep(2)

# Check rect
rect = get_active_window_rect()
print(f"Window rect: {rect}")

# Capture
img = capture_rect(rect)
print(f"Captured image size: {img.size}")

# Save for inspection
img.save(r"E:\work\code\agent-dev\desktop-agent\trace\wechat_capture.png")
print("Saved to wechat_capture.png")

# Run OCR on captured image
from rapidocr_onnxruntime import RapidOCR
import numpy as np
engine = RapidOCR()
result, _ = engine(np.array(img))
print(f"OCR detected {len(result)} elements:")
for box, text, score in result:
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    left, top = int(min(xs)), int(min(ys))
    text = str(text)
    if "搜" in text or "search" in text.lower():
        print(f"  *** SEARCH: text={text!r} score={float(score):.3f} pos=({left},{top})")
    else:
        print(f"  text={text!r:30s} score={float(score):.3f} pos=({left},{top})")
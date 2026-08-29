"""Check OCR on step 1 WeChat screenshot."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
import numpy as np

engine = RapidOCR()
img = Image.open("trace/screenshots/obs_001.png")
print(f"Image size: {img.size}")

result, _ = engine(np.array(img))
if result:
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
else:
    print("OCR returned no results")
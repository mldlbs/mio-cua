import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mio_cua.automation.windows import get_active_window, get_active_window_rect
from mio_cua.perception import perception as P
from mio_cua.vision import ocr as ocr_module


def t(label, fn):
    start = time.time()
    try:
        out = fn()
    except Exception as e:
        print(f"  {label:28} FAILED after {time.time() - start:6.1f}s: {type(e).__name__}: {e}")
        return None
    print(f"  {label:28} {time.time() - start:6.1f}s")
    return out


def main():
    perc = P.Perception(screenshot_dir=None)
    print("phase timings:")

    rect = t("get_active_window_rect", get_active_window_rect)
    win = t("get_active_window", get_active_window)
    proc = t("_safe_active_process", P._safe_active_process)
    img = t("capture_rect", lambda: P.capture_rect(rect))
    print(f"  -> window={win!r} proc={proc!r} rect={rect}")

    import numpy as np

    arr = np.array(img)
    ocr = t("ocr.get_elements", lambda: ocr_module.get_elements(arr))
    print(f"     ocr elements: {len(ocr) if ocr is not None else 'n/a'}")

    sig = (win, rect, P._content_signature(img))
    perc._last_signature = sig
    uia = t("uia.get_elements", lambda: P.uia_module.get_elements())
    print(f"     uia elements: {len(uia) if uia is not None else 'n/a'}")

    elements = P.merge(ocr or [], uia or [])
    t("_detect_regions", lambda: perc._detect_regions(img, rect))
    t("_detect_web_controls", lambda: perc._detect_web_controls(win, img, rect, elements))

    def overlay_save():
        local = [P._shift_element(P.copy(e), -rect[0], -rect[1]) for e in elements]
        out = Path("trace/_bench_overlay.png")
        P.overlay(img, local).save(str(out))
        return out

    t("overlay+save", overlay_save)

    print("\nend-to-end observe():")
    t("observe()", perc.observe)


if __name__ == "__main__":
    main()

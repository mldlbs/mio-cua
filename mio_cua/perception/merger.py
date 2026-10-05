from mio_cua.models.element import Element

import re

_ASCII_ONLY = re.compile(r"^[ -~]+$")


def _area(bbox):
    _, _, w, h = bbox
    return max(w, 0) * max(h, 0)


def _overlap_area(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return ix * iy


def _overlaps(a, b, ratio: float = 0.3) -> bool:
    """True if overlap area >= ratio of the smaller box."""
    smaller = min(_area(a), _area(b))
    if smaller == 0:
        return False
    return _overlap_area(a, b) / smaller >= ratio


def merge(ocr_elements: list, uia_elements: list) -> list:
    """Dedupe OCR/UIA overlaps; keep the richer of the two.

    When an OCR element overlaps a UIA element:
    - if the UIA element has meaningful text, keep the UIA one (more stable);
    - otherwise keep the OCR one (its text is real, e.g. calculator digits
      where UIA only exposes the Chinese name or nothing).
    Renumbers the `id` field of the passed Element objects in place.
    """
    kept_uia = list(uia_elements)
    kept_ocr = []
    for o in ocr_elements:
        hit = None
        for u in kept_uia:
            if _overlaps(o.bbox, u.bbox):
                hit = u
                break
        if hit is None:
            kept_ocr.append(o)
            continue
        # Decide who keeps the slot when OCR and UIA overlap.
        #  - UIA text is empty -> OCR text is the only readable label.
        #  - OCR text is ASCII and differs from UIA text -> OCR is the on-screen
        #    glyph (e.g. calculator digits "7" vs UIA "一"), prefer it.
        #  - otherwise keep UIA (more stable).
        hit_text = (hit.text or "").strip()
        ocr_text = (o.text or "").strip()
        if not hit_text:
            kept_ocr.append(o)
            continue
        if ocr_text and _ASCII_ONLY.match(ocr_text) and ocr_text != hit_text:
            kept_ocr.append(o)
            continue
    merged = kept_uia + kept_ocr
    # Assign ids by screen position, NOT enumeration order: UIA/OCR scan order
    # varies between frames, so the same physical button would otherwise get a
    # different id each frame and click-by-id would hit the wrong control.
    merged.sort(key=_stable_sort_key)
    for i, e in enumerate(merged):
        e.id = i
    return merged


def _stable_sort_key(e):
    """Sort by (top, left); zero-area boxes (unpositioned) go last, stably."""
    left, top, width, height = e.bbox
    if width <= 0 or height <= 0:
        return (1, 0, 0)
    return (0, int(top), int(left))

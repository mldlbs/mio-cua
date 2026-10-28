from mio_cua.models.element import Element
from mio_cua.scene.builder import is_container_role

import re

_ASCII_ONLY = re.compile(r"^[ -~]+$")

# Two boxes are the same control only when they are comparable in size and
# substantially overlap. A full-window container overlapping every text box is
# NOT evidence of duplication -- that rule made the agent blind to text inside
# DirectUI windows (WeChat: 16 of 18 OCR texts were swallowed by the window
# root/pane, so the search box and conversation title never reached the scene).
_MAX_SIZE_RATIO = 2.5
_MIN_OVERLAP_RATIO = 0.5


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


def _same_control(o, u) -> bool:
    """Do these two boxes describe the SAME on-screen control?

    Evidence-based:
      1. a container role never participates (window root / pane / group);
      2. identical text is itself evidence of duplication -> collapse (the UIA
         copy is the stable one), regardless of box size;
      3. otherwise sizes must be comparable and the overlap must cover most of
         the smaller box. A big box that merely contains a text box keeps the
         text: it is a container/label relationship, not a duplicate.
    """
    if is_container_role(getattr(u, "role", "")):
        return False
    ao, au = _area(o.bbox), _area(u.bbox)
    if ao <= 0 or au <= 0:
        return False
    ratio = _overlap_area(o.bbox, u.bbox) / min(ao, au)
    if ratio < _MIN_OVERLAP_RATIO:
        return False                      # no spatial evidence: different controls
    if (o.text or "").strip() and (o.text or "").strip() == (u.text or "").strip():
        return True                       # same text on the same spot: duplicate
    if max(ao, au) / min(ao, au) > _MAX_SIZE_RATIO:
        return False                      # a container merely containing the text
    return True


def merge(ocr_elements: list, uia_elements: list) -> list:
    """Dedupe OCR/UIA overlaps when they describe the same control.

    Only a confirmed same-control pair is collapsed (see ``_same_control``):
    - UIA text is empty -> keep the OCR text (the only readable label);
    - OCR is an ASCII glyph differing from the UIA name -> keep OCR (e.g.
      calculator "7" vs the localized "一");
    - otherwise keep the UIA element (more stable).

    Containers (window root, panes, groups) are marked ``metadata["container"]``
    and never absorb OCR text. Renumbers ``id`` by screen position, not by
    enumeration order, so click-by-id stays stable across frames.
    """
    kept_uia = list(uia_elements)
    for u in kept_uia:
        if is_container_role(getattr(u, "role", "")):
            u.metadata["container"] = True

    kept_ocr = []
    for o in ocr_elements:
        hit = None
        for u in kept_uia:
            if _same_control(o, u):
                hit = u
                break
        if hit is None:
            kept_ocr.append(o)
            continue
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

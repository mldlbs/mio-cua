"""Vision Node Builder: turn merged OCR+UIA elements into SceneNodes.

Scene nodes are built from the SAME merged element list that InputController
uses to resolve clicks, so node ids are identical to element ids. Overlapping
uia/ocr pairs (the same real control surfaced twice) are collapsed into a
single node; the on-screen glyph (OCR text) wins when it is ASCII and differs
from the UIA localized name (e.g. calculator digit "7" vs "一").
"""

import re

from mio_cua.scene.graph import SceneNode

_ASCII_ONLY = re.compile(r"^[ -~]+$")

# UIA control types that are meaningful interaction targets.
_CLICKABLE_ROLES = {"button", "checkbox", "radio button", "menuitem",
                    "tabitem", "hyperlink", "combobox", "listitem", "slider"}
_INPUT_ROLES = {"edit", "document", "spinbutton"}
_CONTAINER_ROLES = {"pane", "group", "window", "custom", "list", "menu",
                    "toolbar", "tree", "dataitem"}


def _area(bbox):
    _, _, w, h = bbox
    return max(w, 0) * max(h, 0)


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return ix * iy


def _normalize_role(role):
    return (role or "").strip().lower()


def _node_type(role, text):
    r = _normalize_role(role)
    if r in _CLICKABLE_ROLES:
        return "button"
    if r in _INPUT_ROLES:
        return "input"
    if r in _CONTAINER_ROLES:
        return "group"
    return "text"


def _pick_text(uia_text, ocr_text):
    uia = (uia_text or "").strip()
    ocr = (ocr_text or "").strip()
    if not uia:
        return ocr or ""
    if not ocr:
        return uia
    if _ASCII_ONLY.match(ocr) and ocr != uia:
        return ocr  # on-screen glyph (e.g. "7") beats localized name ("一")
    return uia


class NodeBuilder:
    """Build SceneNodes from the merged element list (ids stay stable)."""

    def __init__(self, merged_elements):
        self.elements = merged_elements

    def build(self) -> list:
        nodes = []
        consumed = set()
        for i, e in enumerate(self.elements):
            if i in consumed:
                continue
            if (e.source or "") != "uia":
                continue  # OCR-only nodes are emitted by the standalone pass
            bbox = tuple(e.bbox) if e.bbox else (0, 0, 0, 0)
            if bbox[2] <= 0 or bbox[3] <= 0:
                continue
            if not e.visible:
                continue
            source = e.source or "uia"
            text = (e.text or "").strip()
            role = _normalize_role(e.role)

            # If this is a UIA element, fold in any overlapping OCR element
            # (same control) and pick the best text.
            if source == "uia":
                for j, o in enumerate(self.elements):
                    if j in consumed or j == i or (o.source or "") != "ocr":
                        continue
                    ob = tuple(o.bbox) if o.bbox else (0, 0, 0, 0)
                    if ob[2] <= 0 or ob[3] <= 0:
                        continue
                    smaller = min(_area(ob), _area(bbox))
                    if smaller > 0 and _overlap(ob, bbox) / smaller >= 0.3:
                        # A UIA container that dwarfs the OCR box is a wrapper
                        # (e.g. a full-window editor), not the OCR text itself.
                        # Keep the OCR text as its own node instead of folding
                        # it into the container. Buttons/inputs always fold the
                        # OCR glyph in.
                        if _normalize_role(role) in _CONTAINER_ROLES \
                                and _area(bbox) > 25 * _area(ob):
                            continue
                        consumed.add(j)
                        text = _pick_text(text, (o.text or "").strip())
                        break

            semantic = text or None
            nodes.append(SceneNode(
                id=e.id, type=_node_type(role, text), bbox=bbox, text=text,
                semantic=semantic, confidence=float(e.confidence or 1.0),
                source=source, role=role or "unknown",
                state={
                    "enabled": bool(e.enabled),
                    "visible": True,
                    "focused": bool(e.focused),
                },
            ))

        # OCR boxes that were not folded into a UIA node become standalone text
        # nodes (e.g. numbers in a plain-text editor, where the UIA tree only
        # exposes one giant document control).
        for i, e in enumerate(self.elements):
            if i in consumed:
                continue
            if (e.source or "") != "ocr":
                continue
            text = (e.text or "").strip()
            bbox = tuple(e.bbox) if e.bbox else (0, 0, 0, 0)
            if not text or bbox[2] <= 0 or bbox[3] <= 0:
                continue
            nodes.append(SceneNode(
                id=e.id, type="text", bbox=bbox, text=text, semantic=text,
                confidence=float(e.confidence or 1.0),
                source="ocr", role="text",
                state={"enabled": True, "visible": True, "focused": False},
            ))
        return nodes

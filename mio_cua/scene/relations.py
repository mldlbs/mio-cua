"""Spatial Relation Builder: turn node positions into a relation graph.

Relations the agent reasons about:
- parent / child    containment (a container node inside another)
- leftOf / rightOf  horizontal ordering of adjacent-ish nodes
- above / below     vertical ordering
- near              close proximity (usable for pairing label<->control)
- labelFor          a short text node placed left/above a control labels it
- overlap           meaningful overlap (e.g. OCR glyph inside its button)
"""

from mio_cua.scene.graph import Relation

_MAX_NEAR_DIST = 120  # px, diagonal-ish adjacency threshold


def _area(bbox):
    _, _, w, h = bbox
    return max(w, 0) * max(h, 0)


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return ix * iy


def _contains(a, b):
    """True if bbox a contains bbox b (a is the container)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax <= bx and ay <= by and ax + aw >= bx + bw and ay + ah >= by + bh


def _center(bbox):
    left, top, width, height = bbox
    return (left + width / 2, top + height / 2)


def _dist_centers(a, b):
    ax, ay = _center(a)
    bx, by = _center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


class RelationBuilder:
    def __init__(self, nodes):
        self.nodes = nodes
        self.relations = []

    def build(self) -> list:
        self._containment()
        self._spatial()
        self._labels()
        return self.relations

    def _containment(self):
        for i, n in enumerate(self.nodes):
            for j, m in enumerate(self.nodes):
                if i == j:
                    continue
                if _contains(n.bbox, m.bbox):
                    area_ratio = _area(m.bbox) / _area(n.bbox) if _area(n.bbox) else 0
                    # Only meaningful nesting: child isn't almost the whole parent.
                    if area_ratio < 0.9:
                        self.relations.append(Relation(n.id, m.id, "child", weight=area_ratio))

    def _spatial(self):
        for i, n in enumerate(self.nodes):
            for j, m in enumerate(self.nodes):
                if i >= j:
                    continue
                ncx, ncy = _center(n.bbox)
                mcx, mcy = _center(m.bbox)
                dx = mcx - ncx
                dy = mcy - ncy
                # Horizontal: roughly same row, some horizontal separation.
                if abs(dy) < 20 and abs(dx) > 10:
                    if dx > 0:
                        self.relations.append(Relation(n.id, m.id, "leftOf"))
                    else:
                        self.relations.append(Relation(m.id, n.id, "leftOf"))
                # Vertical: roughly same column.
                if abs(dx) < 20 and abs(dy) > 10:
                    if dy > 0:
                        self.relations.append(Relation(n.id, m.id, "above"))
                    else:
                        self.relations.append(Relation(m.id, n.id, "above"))
                # Near (adjacency) regardless of axis.
                if _dist_centers(n.bbox, m.bbox) <= _MAX_NEAR_DIST and not _contains(n.bbox, m.bbox) and not _contains(m.bbox, n.bbox):
                    self.relations.append(Relation(n.id, m.id, "near"))

    def _labels(self):
        """A short text node placed left of / above a control labels it."""
        for i, n in enumerate(self.nodes):
            if n.type != "text" or not n.text or len(n.text) > 12:
                continue
            for j, m in enumerate(self.nodes):
                if i == j or m.type not in ("button", "input"):
                    continue
                ncx, ncy = _center(n.bbox)
                mcx, mcy = _center(m.bbox)
                dx = mcx - ncx
                dy = mcy - ncy
                # label is to the left and vertically aligned, or directly above.
                if (dx > 0 and abs(dy) < 30) or (dy > 0 and abs(dx) < 30):
                    self.relations.append(Relation(n.id, m.id, "labelFor"))

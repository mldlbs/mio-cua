from mio_cua.models.observation import Change, ObservationDiff
from mio_cua.scene.diff import diff as scene_diff_func


def _key(e):
    return e.role or "unknown", e.text or ""


def _nearby(a, b, tol: int = 5) -> bool:
    """True if bbox centers are within tol pixels of each other."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ac = (ax + aw / 2, ay + ah / 2)
    bc = (bx + bw / 2, by + bh / 2)
    return abs(ac[0] - bc[0]) <= tol and abs(ac[1] - bc[1]) <= tol


def _role(e):
    return e.role or "unknown"


def compute_diff(prev, current) -> ObservationDiff:
    if prev is None:
        return ObservationDiff(prev=None, current=current, changes=[])
    # Prefer the scene graph diff when both observations carry one: it detects
    # display readout changes (e.g. calculator 0 -> 7) which the element-level
    # diff treats as unrelated "removed" + "added" noise.
    prev_scene = getattr(prev, "scene", None)
    curr_scene = getattr(current, "scene", None)
    if prev_scene is not None and curr_scene is not None \
            and getattr(prev_scene, "nodes", None) and getattr(curr_scene, "nodes", None):
        sc = scene_diff_func(prev_scene, curr_scene)
        if sc:
            return ObservationDiff(prev=prev, current=current, changes=[
                Change(c.kind, c.node_id, c.description) for c in sc
            ])
    return _diff_elements(prev, current)


def _diff_elements(prev, current) -> ObservationDiff:
    prev_elements = list(prev.elements)
    changes = []
    matched_prev = set()
    consumed_cur = set()

    # stable: current element matched to prev by (role, text) identity within bbox tolerance
    for ci, e in enumerate(current.elements):
        for i, p in enumerate(prev_elements):
            if i in matched_prev:
                continue
            if _key(p) == _key(e) and _nearby(p.bbox, e.bbox):
                matched_prev.add(i)
                consumed_cur.add(ci)
                break

    # text_changed: same role at nearly same position, but text differs
    for ci, e in enumerate(current.elements):
        if ci in consumed_cur:
            continue
        for i, p in enumerate(prev_elements):
            if i in matched_prev:
                continue
            if _role(p) == _role(e) and _nearby(p.bbox, e.bbox) and p.text != e.text:
                matched_prev.add(i)
                consumed_cur.add(ci)
                changes.append(Change("text_changed", e.id, f"{p.text} -> {e.text}"))
                break

    # added: current elements never matched
    for ci, e in enumerate(current.elements):
        if ci not in consumed_cur:
            changes.append(Change("added", e.id, e.text or e.role))

    # removed: prev elements never matched
    for i, p in enumerate(prev_elements):
        if i not in matched_prev:
            label = p.text or p.role or "unknown"
            changes.append(Change("removed", None, label))

    return ObservationDiff(prev=prev, current=current, changes=changes)


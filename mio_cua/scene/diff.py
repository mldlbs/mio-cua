"""Scene Diff: what changed between two SceneGraphs.

Primarily used to verify affordances: after clicking button "7", the display
node's text should change. The loop can compare display text / node presence /
text changes and decide whether the action succeeded.
"""

from dataclasses import dataclass


@dataclass
class SceneChange:
    kind: str  # "text_changed" | "added" | "removed" | "moved" | "state_changed"
    node_id: int = None
    description: str = ""


def _text_of(node):
    return (node.semantic or node.text or "").strip()


def _match_nodes(prev_nodes, curr_nodes):
    """Stable node matching: by id first, then by closest bbox center."""
    matched = {}
    used = set()
    for p in prev_nodes:
        for c in curr_nodes:
            if c.id in used:
                continue
            if c.id == p.id:
                matched[p.id] = c
                used.add(c.id)
                break
    for p in prev_nodes:
        if p.id in matched:
            continue
        best, best_d = None, None
        pcx, pcy = (p.bbox[0] + p.bbox[2] / 2, p.bbox[1] + p.bbox[3] / 2)
        for c in curr_nodes:
            if c.id in used:
                continue
            ccx, ccy = (c.bbox[0] + c.bbox[2] / 2, c.bbox[1] + c.bbox[3] / 2)
            d = (pcx - ccx) ** 2 + (pcy - ccy) ** 2
            if best is None or d < best_d:
                best, best_d = c, d
        if best is not None:
            matched[p.id] = best
            used.add(best.id)
    return matched


def diff(prev, curr) -> list:
    if prev is None:
        return []
    changes = []
    matched = _match_nodes(prev.nodes, curr.nodes)
    for p in prev.nodes:
        c = matched.get(p.id)
        if c is None:
            changes.append(SceneChange("removed", p.id, f"node {p.id} gone"))
            continue
        pt, ct = _text_of(p), _text_of(c)
        if pt and ct and pt != ct:
            changes.append(SceneChange(
                "text_changed", c.id,
                f"node {c.id} text {pt!r} -> {ct!r}",
            ))
        if p.bbox != c.bbox:
            changes.append(SceneChange(
                "moved", c.id, f"node {c.id} moved {p.bbox} -> {c.bbox}",
            ))
    curr_ids = {c.id for c in curr.nodes}
    for c in curr.nodes:
        if c.id not in matched.values() and c.id not in {p.id for p in prev.nodes}:
            changes.append(SceneChange("added", c.id, f"node {c.id} appeared"))
    return changes


def display_text(graph):
    """Concatenated text of the graph's display nodes ('' if none)."""
    parts = []
    for nid in getattr(graph, "display_ids", []) or []:
        n = graph.node(nid)
        if n is not None:
            parts.append(_text_of(n))
    return " ".join(parts)

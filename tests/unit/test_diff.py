from mio_cua.agent.diff import compute_diff
from mio_cua.models.element import Element
from mio_cua.models.observation import Observation


def _obs(elements, ts=1.0):
    return Observation(None, ts, None, 1.0, elements)


def test_no_prev_returns_empty_changes():
    d = compute_diff(None, _obs([]))
    assert d.changes == []


def test_added_element_detected():
    prev = _obs([Element(0, "ocr", text="A", bbox=(0, 0, 10, 10))])
    cur = _obs([
        Element(0, "ocr", text="A", bbox=(0, 0, 10, 10)),
        Element(1, "ocr", text="B", bbox=(50, 50, 10, 10)),
    ])
    d = compute_diff(prev, cur)
    assert any(c.kind == "added" and c.description == "B" for c in d.changes)


def test_text_changed_detected():
    prev = _obs([Element(0, "ocr", text="A", bbox=(0, 0, 10, 10))])
    cur = _obs([Element(0, "ocr", text="C", bbox=(0, 0, 10, 10))])
    d = compute_diff(prev, cur)
    assert any(c.kind == "text_changed" for c in d.changes)


def test_removed_detected():
    prev = _obs([Element(0, "ocr", text="A", bbox=(0, 0, 10, 10)), Element(1, "ocr", text="B", bbox=(50, 50, 10, 10))])
    cur = _obs([Element(0, "ocr", text="A", bbox=(0, 0, 10, 10))])
    d = compute_diff(prev, cur)
    assert any(c.kind == "removed" and c.description == "B" for c in d.changes)


def test_small_bbox_jitter_is_not_churn():
    prev = _obs([Element(0, "ocr", text="Save", role="text", bbox=(100, 100, 50, 20))])
    cur = _obs([Element(0, "ocr", text="Save", role="text", bbox=(102, 101, 50, 20))])
    d = compute_diff(prev, cur)
    assert not any(c.kind in ("added", "removed") for c in d.changes)


def test_compute_diff_prefers_scene_and_detects_display_change():
    from mio_cua.scene import build_scene

    def _obs_scene(elements):
        return Observation(None, 1.0, "计算器", 1.0, elements,
                           scene=build_scene(elements, "计算器"))

    els0 = [
        Element(0, "uia", text="显示为 0", role="text", bbox=(100, 10, 400, 80), visible=True),
        Element(1, "uia", text="一", role="button", bbox=(100, 200, 127, 48), visible=True),
    ]
    els1 = [
        Element(0, "uia", text="显示为 7", role="text", bbox=(100, 10, 400, 80), visible=True),
        Element(1, "uia", text="一", role="button", bbox=(100, 200, 127, 48), visible=True),
    ]
    d = compute_diff(_obs_scene(els0), _obs_scene(els1))
    assert any(c.kind == "text_changed" and "显示为 0" in c.description and "显示为 7" in c.description
               for c in d.changes)


def test_scene_diff_rematched_node_not_added():
    """A curr node matched to a prev node by bbox but with a DIFFERENT id must
    not be reported as 'added' (regression: added-detection compared an int id
    against SceneNode objects, so every id shift looked like a new node)."""
    from mio_cua.scene.diff import diff
    from mio_cua.scene.graph import SceneGraph, SceneNode

    prev = SceneGraph(nodes=[SceneNode(id=1, type="text", bbox=(100, 300, 127, 48),
                                       text="7", source="ocr")])
    curr = SceneGraph(nodes=[SceneNode(id=0, type="text", bbox=(100, 300, 127, 48),
                                       text="7", source="ocr")])
    changes = diff(prev, curr)
    assert not any(c.kind == "added" for c in changes), changes
    assert not any(c.kind == "removed" for c in changes), changes

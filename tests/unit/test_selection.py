from mio_cua.tools.selection import select_element
from mio_cua.models.action import Action
from mio_cua.models.action_result import RawResult
from mio_cua.models.element import Element
from mio_cua.models.observation import Observation


class Ctx:
    current_action_id = "t"


class RecordingController:
    def __init__(self):
        self.calls = []
        self.current_observation = None

    def execute(self, action):
        self.calls.append(action)
        return RawResult(sent=True)


def _obs(bbox):
    return Observation(None, 1.0, "win", 1.0,
                       [Element(0, "uia", text="txt", role="text", bbox=bbox)])


def test_select_element_drags_across_bbox():
    ctrl = RecordingController()
    ctrl.current_observation = _obs((100, 200, 300, 40))
    ctx = Ctx()
    ctx.controller = ctrl
    r = select_element(ctx, element_id=0)
    assert r.success is True
    a = ctrl.calls[-1]
    assert a.type == "drag"
    assert a.params["x1"] == 102   # left + 2
    assert a.params["y1"] == 220   # top + height//2
    assert a.params["x2"] == 398   # left + width - 2
    assert a.params["y2"] == 220


def test_select_element_handles_tiny_width():
    # width=2 -> x2 must be at least x1+1 (x1 < x2 guaranteed)
    ctrl = RecordingController()
    ctrl.current_observation = _obs((100, 200, 2, 40))
    ctx = Ctx()
    ctx.controller = ctrl
    r = select_element(ctx, element_id=0)
    assert r.success is True
    a = ctrl.calls[-1]
    assert a.params["x1"] < a.params["x2"]
    assert a.params["x1"] == 102
    assert a.params["x2"] == 103


def test_select_element_requires_element_id():
    ctrl = RecordingController()
    ctx = Ctx()
    ctx.controller = ctrl
    r = select_element(ctx)
    assert r.success is False
    assert r.retryable is True


def test_select_element_resolves_scene_node_id():
    from mio_cua.scene import build_scene
    from mio_cua.scene.graph import SceneNode
    from mio_cua.models.observation import Observation
    els = [Element(0, "uia", text="win", role="text", bbox=(0, 0, 10, 10))]
    scene = build_scene(els, active_window="win")
    # a web-control node with an id above the element range
    scene.nodes.append(SceneNode(id=10000, type="text", bbox=(200, 300, 400, 50),
                                 text="web", source="web"))
    ctrl = RecordingController()
    ctrl.current_observation = Observation(None, 1.0, "win", 1.0, els, scene=scene)
    ctx = Ctx()
    ctx.controller = ctrl
    r = select_element(ctx, element_id=10000)
    assert r.success is True
    a = ctrl.calls[-1]
    assert a.params["x1"] == 202
    assert a.params["y1"] == 325
    assert a.params["x2"] == 598
    assert a.params["y2"] == 325

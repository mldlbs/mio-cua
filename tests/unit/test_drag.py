from mio_cua.tools.drag import drag
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


def test_drag_passes_coordinates():
    ctrl = RecordingController()
    ctx = Ctx()
    ctx.controller = ctrl
    r = drag(ctx, x1=10, y1=20, x2=100, y2=200)
    assert r.success is True
    a = ctrl.calls[-1]
    assert a.type == "drag"
    assert a.params["x1"] == 10
    assert a.params["y1"] == 20
    assert a.params["x2"] == 100
    assert a.params["y2"] == 200


def test_drag_requires_coordinates():
    ctrl = RecordingController()
    ctx = Ctx()
    ctx.controller = ctrl
    r = drag(ctx)
    assert r.success is False
    assert r.retryable is True


def test_drag_resolves_element_id():
    ctrl = RecordingController()
    ctrl.current_observation = Observation(
        None, 1.0, "win", 1.0,
        [Element(0, "uia", text="x", role="text", bbox=(100, 200, 300, 40))],
    )
    ctx = Ctx()
    ctx.controller = ctrl
    r = drag(ctx, element_id=0)
    a = ctrl.calls[-1]
    assert a.type == "drag"
    assert a.params["x1"] == 102  # left + 2
    assert a.params["y1"] == 220  # top + height//2
    assert a.params["x2"] == 398  # left + width - 2
    assert a.params["y2"] == 220


def test_drag_resolves_scene_node_id():
    from mio_cua.scene import build_scene
    els = [Element(0, "uia", text="win", role="text", bbox=(0, 0, 10, 10))]
    scene = build_scene(els, active_window="win")
    # a web-control node with an id above the element range
    from mio_cua.scene.graph import SceneNode
    scene.nodes.append(SceneNode(id=10000, type="text", bbox=(200, 300, 400, 50),
                                 text="web", source="web"))
    from mio_cua.models.observation import Observation
    ctrl = RecordingController()
    ctrl.current_observation = Observation(None, 1.0, "win", 1.0, els, scene=scene)
    ctx = Ctx()
    ctx.controller = ctrl
    r = drag(ctx, element_id=10000)
    a = ctrl.calls[-1]
    assert a.params["x1"] == 202
    assert a.params["y1"] == 325
    assert a.params["x2"] == 598
    assert a.params["y2"] == 325

import pytest

from mio_cua.automation.backends import Backend
from mio_cua.automation.input_controller import InputController
from mio_cua.models.action import Action
from mio_cua.models.action_result import RawResult
from mio_cua.models.observation import Observation
from mio_cua.models.element import Element


class RecordingBackend(Backend):
    def __init__(self):
        self.calls = []

    def execute(self, action):
        self.calls.append(action)
        return RawResult(sent=True)


def test_controller_resolves_bbox_to_center():
    b = RecordingBackend()
    c = InputController(b)
    c.resolve = lambda a: None  # no-op real resolution in unit test
    r = c.execute(Action(id="a-1", type="click", params={"x": 100, "y": 200}))
    assert r.sent is True
    assert b.calls[0].params["x"] == 100


def test_controller_default_backend_is_sendinput():
    c = InputController()
    assert c.backend.__class__.__name__ == "SendInputBackend"


def test_controller_calls_resolve_before_execute():
    b = RecordingBackend()
    c = InputController(b)
    seen = []
    c.resolve = lambda a: seen.append(a)
    c.execute(Action(id="a-1", type="click", params={"x": 10, "y": 20}))
    assert len(seen) == 1  # resolve invoked


def test_controller_raises_on_unresolved_element_id():
    b = RecordingBackend()
    c = InputController(b)
    with pytest.raises(RuntimeError):
        c.execute(Action(id="a-1", type="click", params={"element_id": 5}))


def test_controller_resolves_element_id_to_center():
    b = RecordingBackend()
    c = InputController(b)
    obs = Observation(
        screenshot_path=None, timestamp=1.0, active_window="Calc",
        dpi_scale=1.0,
        elements=[Element(0, "ocr", text="Calc", bbox=(10, 20, 100, 40))],
    )
    c.current_observation = obs
    r = c.execute(Action(id="a-1", type="click", params={"element_id": 0}))
    assert r.sent is True
    sent = b.calls[0].params
    assert sent["x"] == 10 + 100 // 2  # 60
    assert sent["y"] == 20 + 40 // 2  # 40
    assert "element_id" not in sent


def test_controller_keeps_explicit_coords_over_element_id():
    b = RecordingBackend()
    c = InputController(b)
    c.current_observation = Observation(
        screenshot_path=None, timestamp=1.0, active_window="Calc", dpi_scale=1.0,
        elements=[Element(0, "ocr", text="Calc", bbox=(10, 20, 100, 40))],
    )
    r = c.execute(Action(id="a-1", type="click", params={"element_id": 0, "x": 7, "y": 9}))
    assert r.sent is True
    assert b.calls[0].params["x"] == 7
    assert b.calls[0].params["y"] == 9

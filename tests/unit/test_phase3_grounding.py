"""Deterministic grounding: live UIA re-resolution at the execution boundary.

These tests prove the model's stale/hallucinated click target is caught and
re-grounded against the *live* desktop -- the core of "de-modeling" mio-cua.
No win32 is touched: the live desktop is mocked.
"""

import types

from mio_cua.automation.grounding import Grounder, GroundingError
from mio_cua.models.action import Action
from mio_cua.models.element import Element


def _el(eid, text, role, bbox, visible=True, enabled=True, source="uia"):
    return Element(id=eid, source=source, text=text, role=role, bbox=bbox,
                   visible=visible, enabled=enabled)


def _obs(*elements):
    return types.SimpleNamespace(elements=list(elements))


WIN = (0, 0, 1000, 800)  # (left, top, width, height)


def test_element_id_resolves_to_live_center():
    ref = _el(5, "搜索", "Button", (100, 100, 50, 20))
    live = [_el(0, "搜索", "Button", (100, 100, 50, 20))]
    g = Grounder(live_source=lambda: live, window_rect=lambda: WIN)
    x, y = g.resolve(Action(id="a", type="click", params={"element_id": 5}), _obs(ref))
    assert (x, y) == (125, 110)


def test_element_drifted_uses_live_position():
    ref = _el(5, "发送", "Button", (100, 100, 50, 20))
    live = [_el(0, "发送", "Button", (400, 300, 80, 30))]  # moved since screenshot
    g = Grounder(live_source=lambda: live, window_rect=lambda: WIN)
    x, y = g.resolve(Action(id="a", type="click", params={"element_id": 5}), _obs(ref))
    assert (x, y) == (440, 315)  # live center, NOT stale (125, 110)


def test_element_not_visible_on_live_raises():
    ref = _el(5, "删除", "Button", (100, 100, 50, 20))
    live = [_el(0, "删除", "Button", (100, 100, 50, 20), visible=False)]
    g = Grounder(live_source=lambda: live, window_rect=lambda: WIN)
    try:
        g.resolve(Action(id="a", type="click", params={"element_id": 5}), _obs(ref))
        assert False, "expected GroundingError"
    except GroundingError:
        pass


def test_element_id_missing_from_reference_raises():
    g = Grounder(live_source=lambda: [], window_rect=lambda: WIN)
    try:
        g.resolve(Action(id="a", type="click", params={"element_id": 99}), _obs(_el(5, "x", "Button", (1, 1, 1, 1))))
        assert False, "expected GroundingError"
    except GroundingError:
        pass


def test_raw_coords_hit_interactive_element_accepted():
    live = [_el(0, "确定", "Button", (200, 200, 60, 30))]
    g = Grounder(live_source=lambda: live, window_rect=lambda: WIN)
    x, y = g.resolve(Action(id="a", type="click", params={"x": 220, "y": 215}), _obs())
    assert (x, y) == (220, 215)  # model coords validated as on a real element


def test_raw_coords_hit_void_raises():
    # live desktop has an element, but NOT at (10,10) -> click hits the void
    live = [_el(0, "x", "Button", (200, 200, 50, 50))]
    g = Grounder(live_source=lambda: live, window_rect=lambda: WIN)
    try:
        g.resolve(Action(id="a", type="click", params={"x": 10, "y": 10}), _obs())
        assert False, "expected GroundingError"
    except GroundingError:
        pass


def test_raw_coords_outside_window_raises():
    live = [_el(0, "x", "Button", (2000, 2000, 50, 50))]
    g = Grounder(live_source=lambda: live, window_rect=lambda: WIN)
    try:
        g.resolve(Action(id="a", type="click", params={"x": 2000, "y": 2000}), _obs())
        assert False, "expected GroundingError"
    except GroundingError:
        pass


def test_live_element_outside_window_raises():
    ref = _el(5, "搜索", "Button", (100, 100, 50, 20))
    # matched live element center at (2000,2000) is outside WIN
    live = [_el(0, "搜索", "Button", (1980, 1990, 40, 20))]
    g = Grounder(live_source=lambda: live, window_rect=lambda: WIN)
    try:
        g.resolve(Action(id="a", type="click", params={"element_id": 5}), _obs(ref))
        assert False, "expected GroundingError"
    except GroundingError:
        pass


def test_key_action_has_no_spatial_target():
    g = Grounder(live_source=lambda: [], window_rect=lambda: WIN)
    assert g.resolve(Action(id="a", type="key", params={"keys": "enter"}), _obs()) is None


def test_live_unreadable_degrades_to_cached_coords():
    # live_source returns [] -> degrade to reference bbox center (old behaviour)
    ref = _el(5, "搜索", "Button", (100, 100, 50, 20))
    g = Grounder(live_source=lambda: [], window_rect=lambda: WIN)
    x, y = g.resolve(Action(id="a", type="click", params={"element_id": 5}), _obs(ref))
    assert (x, y) == (125, 110)

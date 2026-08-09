from mio_cua.agent.expected import ExpectedVerifier
from mio_cua.scene.graph import SceneNode
from mio_cua.scene import build_scene
from mio_cua.models.element import Element


def _scene(display_text, display_id=5):
    els = [
        Element(0, "uia", text="一", role="button", bbox=(100, 300, 127, 48)),
        Element(1, "uia", text=display_text, role="text", bbox=(100, 10, 400, 80)),
    ]
    for i, e in enumerate(els):
        e.id = i
    scene = build_scene(els, active_window="Calculator")
    # force the readout node id so display_text() finds it
    scene.display_ids = [1]
    return scene


def test_verify_display_changed_ok():
    v = ExpectedVerifier()
    ok, detail = v.verify(_scene("0"), _scene("7"), {"display": True})
    assert ok is True
    assert "changed" in detail


def test_verify_display_unchanged_ok():
    v = ExpectedVerifier()
    ok, _ = v.verify(_scene("123"), _scene("123"), {"display": "unchanged"})
    assert ok is True


def test_verify_display_unchanged_fails_when_changed():
    v = ExpectedVerifier()
    ok, detail = v.verify(_scene("12"), _scene("123"), {"display": "unchanged"})
    assert ok is False
    assert "unexpectedly" in detail


def test_verify_no_expected_is_ok():
    v = ExpectedVerifier()
    ok, _ = v.verify(_scene("0"), _scene("7"), {})
    assert ok is True


def test_verify_unknown_expectation_is_ok():
    v = ExpectedVerifier()
    ok, _ = v.verify(_scene("0"), _scene("7"), {"display": "something"})
    assert ok is True

from mio_cua.agent.batch import verify_action
from mio_cua.models.action import Action
from mio_cua.models.observation import Observation
from mio_cua.models.element import Element
from mio_cua.scene import build_scene


def _ocr_els(*texts):
    return [Element(i, "ocr", text=t, bbox=(i * 60, 0, 50, 20))
            for i, t in enumerate(texts)]


def _uia_els(*texts):
    # ids/boxes offset so UIA elements never collide with OCR elements
    # (NodeBuilder would fold an overlapping OCR text into the UIA node).
    return [Element(i + 100, "uia", text=t, bbox=(i * 60 + 1000, 0, 50, 20))
            for i, t in enumerate(texts)]


def _obs(elements, window="Calc"):
    scene = build_scene(elements, active_window=window)
    return Observation(None, 1.0, window, 1.0, elements, scene=scene)


def _calc_scene(disp_text):
    els = [
        Element(0, "uia", text="7", role="button", bbox=(100, 300, 50, 30)),
        Element(1, "uia", text=disp_text, role="text", bbox=(100, 10, 400, 80)),
    ]
    scene = build_scene(els, active_window="Calculator")
    scene.display_ids = [1]
    return _obs(els, "Calculator"), scene


def _click():
    return Action(id="a-1", type="click", params={})


# --- expected 优先 ---

def test_expected_display_changed_ok():
    prev, prev_scene = _calc_scene("0")
    curr, curr_scene = _calc_scene("7")
    prev.scene = prev_scene
    curr.scene = curr_scene
    ok, detail = verify_action(prev, curr, _click(), {"display": True})
    assert ok is True
    assert "changed" in detail


def test_expected_display_unchanged_fails():
    prev, prev_scene = _calc_scene("0")
    curr, curr_scene = _calc_scene("0")
    prev.scene = prev_scene
    curr.scene = curr_scene
    ok, detail = verify_action(prev, curr, _click(), {"display": True})
    assert ok is False
    assert "did not change" in detail


def test_expected_unchanged_semantics_ok():
    prev, prev_scene = _calc_scene("12")
    curr, curr_scene = _calc_scene("12")
    prev.scene = prev_scene
    curr.scene = curr_scene
    ok, _ = verify_action(prev, curr, _click(), {"display": "unchanged"})
    assert ok is True


# --- diff 回退（OCR-only 投影） ---

def test_diff_fallback_change_detected():
    prev = _obs(_ocr_els("OK", "Cancel"))
    curr = _obs(_ocr_els("OK", "Cancel", "NewNode"))
    ok, detail = verify_action(prev, curr, _click(), None)
    assert ok is True
    assert "changed" in detail


def test_diff_fallback_no_change_fails():
    prev = _obs(_ocr_els("OK", "Cancel"))
    curr = _obs(_ocr_els("OK", "Cancel"))
    ok, detail = verify_action(prev, curr, _click(), None)
    assert ok is False
    assert "did not change" in detail


def test_ocr_projection_ignores_uia_noise():
    # prev has an extra UIA node; curr light frame is OCR-only. The OCR layer
    # is identical, so the action must NOT be considered "changed".
    prev = _obs(_ocr_els("OK") + _uia_els("ButtonX"))
    curr = _obs(_ocr_els("OK"))
    ok, detail = verify_action(prev, curr, _click(), None)
    assert ok is False
    assert "did not change" in detail


def test_ocr_projection_overlapping_uia_same_pixels_no_change():
    """A full frame whose OCR glyph is folded into an overlapping UIA node must
    still project to the OCR element (not be lost), so identical pixels between
    a full prev and a light curr report NO change."""
    prev_els = [
        Element(0, "uia", text="一", role="button", bbox=(100, 300, 127, 48)),
        Element(1, "ocr", text="7", role="unknown", bbox=(100, 300, 127, 48)),
    ]
    curr_els = [
        Element(0, "ocr", text="7", role="unknown", bbox=(100, 300, 127, 48)),
    ]
    prev = _obs(prev_els)
    curr = _obs(curr_els)
    ok, detail = verify_action(prev, curr, _click(), None)
    assert ok is False, "identical pixels must NOT be reported as changed"
    assert "did not change" in detail


# --- 非可见动作跳过 ---

def test_non_visible_action_passes_without_diff():
    for typ in ("wait", "move_mouse", "launch", "screenshot", "make_dir"):
        a = Action(id="a-1", type=typ, params={})
        ok, detail = verify_action(
            _obs(_ocr_els("same")), _obs(_ocr_els("same")), a, None
        )
        assert ok is True, typ
        assert "no visible expectation" in detail

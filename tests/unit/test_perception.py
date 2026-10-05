from PIL import Image

from mio_cua.perception.perception import Perception


def _fake_capture(rect=(0, 0, 100, 100)):
    return Image.new("RGB", (rect[2], rect[3]), "white")


def test_observe_writes_overlay_screenshot(tmp_path, monkeypatch):
    monkeypatch.setattr("mio_cua.perception.perception.capture_rect", _fake_capture)
    monkeypatch.setattr("mio_cua.perception.perception.ocr_module", _FakeOCR())
    monkeypatch.setattr("mio_cua.perception.perception.uia_module", _FakeUIA())
    monkeypatch.setattr(
        "mio_cua.perception.perception.get_active_window", lambda: "Calc"
    )
    monkeypatch.setattr(
        "mio_cua.perception.perception.get_active_window_rect",
        lambda: (100, 50, 300, 200),
    )

    p = Perception(screenshot_dir=str(tmp_path))
    obs = p.observe()

    assert obs.screenshot_path is not None
    assert obs.screenshot_path.endswith(".png")
    assert not obs.screenshot_path.endswith(".raw.png")
    overlaid = Image.open(obs.screenshot_path)
    red = sum(1 for px in overlaid.getdata() if px == (255, 0, 0))
    assert red > 0, "overlay screenshot should contain red element boxes"
    assert len(obs.elements) == 2
    # OCR bbox must be shifted from window-relative to screen coords
    ocr_el = next(e for e in obs.elements if e.source == "ocr")
    assert ocr_el.bbox == (110, 60, 40, 20)


class _FakeOCR:
    def get_elements(self, img):
        from mio_cua.models.element import Element
        return [Element(0, "ocr", text="Calc", bbox=(10, 10, 40, 20))]


class _FakeUIA:
    def get_elements(self):
        from mio_cua.models.element import Element
        return [Element(1, "uia", text="OK", bbox=(50, 50, 20, 20))]


class _CountingOCR:
    """OCR stub that counts invocations so we can assert cache reuse/misses."""

    def __init__(self, text="Calc"):
        self.calls = 0
        self.text = text

    def get_elements(self, img):
        self.calls += 1
        from mio_cua.models.element import Element
        return [Element(0, "ocr", text=self.text, bbox=(10, 10, 40, 20))]


def _observe_with(monkeypatch, tmp_path, cap, rect=(100, 50, 300, 200)):
    monkeypatch.setattr("mio_cua.perception.perception.capture_rect", _fake_capture)
    monkeypatch.setattr("mio_cua.perception.perception.ocr_module", cap)
    monkeypatch.setattr("mio_cua.perception.perception.uia_module", _FakeUIA())
    monkeypatch.setattr(
        "mio_cua.perception.perception.get_active_window", lambda: "Calc"
    )
    monkeypatch.setattr(
        "mio_cua.perception.perception.get_active_window_rect", lambda: rect
    )
    p = Perception(screenshot_dir=str(tmp_path))
    return p


def test_ocr_cache_reused_when_content_unchanged(monkeypatch, tmp_path):
    """Same window title/rect with identical pixels must not re-run OCR."""
    cap = _CountingOCR()
    p = _observe_with(monkeypatch, tmp_path, cap)
    p.observe()
    p.observe()
    assert cap.calls == 1, "identical content should reuse the OCR cache"


def test_ocr_cache_invalidated_when_content_changes(monkeypatch, tmp_path):
    """Window content changing (e.g. calculator display) must re-run OCR even
    though the window title and rect are unchanged."""
    cap = _CountingOCR()
    p = _observe_with(monkeypatch, tmp_path, cap)
    p.observe()

    from PIL import Image
    import numpy as np

    # Next frame has different pixels in the same window rect.
    def changing_capture(rect=(0, 0, 100, 100)):
        arr = np.zeros((rect[3], rect[2], 3), dtype=np.uint8)
        arr[:, :, 0] = 255  # red
        return Image.fromarray(arr, "RGB")

    monkeypatch.setattr(
        "mio_cua.perception.perception.capture_rect", changing_capture
    )
    p.observe()
    assert cap.calls == 2, "changed content should invalidate the OCR cache"


def test_observe_light_skips_uia_and_web(monkeypatch, tmp_path):
    """observe_light must be OCR-only: no UIA, no OmniParser, no regions,
    and must not write a screenshot artifact."""
    import mio_cua.scene.omniparser as omni_mod

    calls = {"uia": 0, "omni": 0}

    class BoomUIA:
        def get_elements(self):
            calls["uia"] += 1
            raise AssertionError("observe_light must not call UIA")

    def boom_parse(img):
        calls["omni"] += 1
        raise AssertionError("observe_light must not call OmniParser")

    monkeypatch.setattr("mio_cua.perception.perception.capture_rect", _fake_capture)
    monkeypatch.setattr("mio_cua.perception.perception.ocr_module", _FakeOCR())
    monkeypatch.setattr("mio_cua.perception.perception.uia_module", BoomUIA())
    monkeypatch.setattr(omni_mod, "parse", boom_parse)
    monkeypatch.setattr(
        "mio_cua.perception.perception.get_active_window", lambda: "Calc"
    )
    monkeypatch.setattr(
        "mio_cua.perception.perception.get_active_window_rect",
        lambda: (100, 50, 300, 200),
    )

    p = Perception(screenshot_dir=str(tmp_path))
    obs = p.observe_light()

    assert obs.screenshot_path is None, "light observe must not write artifacts"
    assert calls["uia"] == 0
    assert calls["omni"] == 0
    scene = obs.scene
    assert scene is not None and scene.nodes
    assert all((n.source or "") == "ocr" for n in scene.nodes), \
        "light scene must be OCR-only"

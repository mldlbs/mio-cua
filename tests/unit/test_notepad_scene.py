from mio_cua.models.element import Element
from mio_cua.perception.merger import merge
from mio_cua.scene import build_scene


def _ocr(i, text, bbox):
    return Element(id=i, source="ocr", text=text, role="text", bbox=bbox)


def _uia(i, text, role, bbox):
    return Element(id=i, source="uia", text=text, role=role, bbox=bbox)


def test_notepad_full_pipeline_preserves_numbers():
    uia = [
        _uia(0, "", "document", (259, 156, 2169, 1250)),
        _uia(1, "smoke_numbers.txt", "group", (299, 91, 287, 32)),
    ]
    ocr = [
        _ocr(2, "12", (400, 400, 40, 20)),
        _ocr(3, "34", (400, 500, 40, 20)),
        _ocr(4, "56", (400, 600, 40, 20)),
    ]
    merged = merge(ocr, uia)
    scene = build_scene(merged, active_window="notepad")
    texts = {(n.text or "").strip() for n in scene.nodes}
    assert "12" in texts
    assert "34" in texts
    assert "56" in texts

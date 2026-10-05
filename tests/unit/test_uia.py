from mio_cua.automation.uia import _element_from_rect


class FakeRect:
    def __init__(self, left, top, w, h):
        self.left, self.top = left, top
        self._w, self._h = w, h

    def width(self):
        return self._w

    def height(self):
        return self._h


def test_element_from_rect_builds_bbox():
    r = FakeRect(10, 20, 100, 50)
    e = _element_from_rect(r, source="uia", text="OK", role="Button")
    assert e.bbox == (10, 20, 100, 50)
    assert e.text == "OK"
    assert e.role == "Button"


def test_element_from_rect_empty_text():
    r = FakeRect(0, 0, 1, 1)
    e = _element_from_rect(r, source="uia", text="", role="")
    assert e.text == ""
    assert e.role == "unknown"

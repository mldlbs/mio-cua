import pytest

from mio_cua.vision.screen import capture

pytestmark = pytest.mark.desktop


def test_capture_returns_pil_image():
    img = capture()
    assert img is not None
    assert img.size[0] > 0 and img.size[1] > 0
    assert img.mode == "RGB"

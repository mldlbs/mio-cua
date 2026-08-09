from mio_cua.vision.screen import capture


def test_capture_returns_pil_image():
    img = capture()
    assert img is not None
    assert img.size[0] > 0 and img.size[1] > 0
    assert img.mode == "RGB"

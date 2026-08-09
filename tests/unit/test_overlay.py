from PIL import Image

from mio_cua.vision.overlay import overlay
from mio_cua.models.element import Element


def test_overlay_returns_image_same_size():
    img = Image.new("RGB", (200, 200), "white")
    elements = [Element(id=0, source="ocr", bbox=(10, 10, 50, 30))]
    out = overlay(img, elements)
    assert out.size == img.size


def test_overlay_draws_number():
    img = Image.new("RGB", (100, 100), "white")
    elements = [Element(id=7, source="ocr", bbox=(10, 10, 20, 20))]
    out = overlay(img, elements)
    assert out is not img


def test_overlay_draws_red_box_pixels():
    img = Image.new("RGB", (100, 100), "white")
    elements = [Element(id=0, source="ocr", bbox=(10, 10, 20, 20))]
    out = overlay(img, elements)
    red = sum(1 for px in out.getdata() if px == (255, 0, 0))
    assert red > 0

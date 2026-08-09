from PIL import Image, ImageDraw

from mio_cua.models.element import Element


def overlay(image: Image.Image, elements: list) -> Image.Image:
    img = image.copy()
    draw = ImageDraw.Draw(img)
    for e in elements:
        x, y, w, h = e.bbox
        draw.rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=2)
        draw.text((x, max(0, y - 12)), str(e.id), fill=(255, 0, 0))
    return img

from PIL import Image
import mss


def capture(monitor: int = 1) -> Image.Image:
    """Capture a monitor. 1 = primary, 0 = all monitors."""
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[monitor])
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        return img


def capture_rect(rect) -> Image.Image:
    """Capture only a screen region: (left, top, width, height) in physical px.

    Clamped to the primary monitor; falls back to a full-screen capture when
    the region is empty or the window rect is unavailable/offscreen.
    """
    left, top, width, height = rect
    if width <= 0 or height <= 0:
        return capture()
    with mss.mss() as sct:
        m = sct.monitors[1]
        m_left, m_top = m["left"], m["top"]
        m_right, m_bottom = m["left"] + m["width"], m["top"] + m["height"]
        cl = max(left, m_left)
        ct = max(top, m_top)
        cr = min(left + width, m_right)
        cb = min(top + height, m_bottom)
        if cr <= cl or cb <= ct:
            return capture()
        shot = sct.grab({"left": cl, "top": ct, "width": cr - cl, "height": cb - ct})
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        return img


def save(image: Image.Image, path: str) -> str:
    image.save(path)
    return path

import logging
import os
import time
from copy import copy

from mio_cua.automation.windows import get_active_window, get_active_window_rect, set_dpi_aware
from mio_cua.perception.merger import merge
from mio_cua.scene import build_scene, analyze_regions
from mio_cua.scene.graph import Region
from mio_cua.vision.overlay import overlay
from mio_cua.vision.screen import capture, capture_rect
from mio_cua.vision import ocr as ocr_module
from mio_cua.automation import uia as uia_module
from mio_cua.models.observation import Observation


def _content_signature(img, size: int = 24) -> tuple:
    """Cheap perceptual fingerprint of a window capture.

    Used to invalidate the OCR cache when window *content* changes even though
    the window title/rect are unchanged (e.g. a calculator display updating,
    or a page scrolling). Resizing to a tiny grayscale grid keeps it fast.
    """
    small = img.convert("L").resize((size, size))
    return tuple(int(v) for v in small.getdata())


logger = logging.getLogger(__name__)

# Browser window titles get OmniParser web-control detection.
_WEB_BROWSER_KEYWORDS = ("chrome", "edge", "firefox", "internet explorer",
                         "brave", "opera", "vivaldi")


def _shift_bbox(bbox, dx, dy):
    left, top, width, height = bbox
    return (left + dx, top + dy, width, height)


def _shift_element(e, dx, dy):
    e.bbox = _shift_bbox(e.bbox, dx, dy)
    return e


class Perception:
    """Coordinate screen + OCR + UIA into a single Observation, focused on the active window."""

    def __init__(self, screenshot_dir: str = None, dpi_scale: float = 1.0):
        set_dpi_aware()
        self.screenshot_dir = screenshot_dir
        self.dpi_scale = dpi_scale
        self._ocr_cache = None  # (signature, ocr_elements)
        self._web_cache = None  # (signature, web_nodes)
        self._last_signature = None

    def observe(self) -> Observation:
        try:
            rect = get_active_window_rect()
        except Exception as e:
            logger.debug("get_active_window_rect failed: %s", e, exc_info=True)
            rect = (0, 0, 0, 0)
        active_window = ""
        try:
            active_window = get_active_window()
        except Exception as e:
            logger.debug("get_active_window failed: %s", e, exc_info=True)
        img = capture_rect(rect)
        sig = (active_window, rect, _content_signature(img))
        self._last_signature = sig
        ocr_elements = []
        if self._ocr_cache is not None and self._ocr_cache[0] == sig:
            # window and content unchanged since last OCR: reuse cached text layer
            ocr_elements = self._ocr_cache[1]
        else:
            try:
                for e in ocr_module.get_elements(img):
                    e.bbox = _shift_bbox(e.bbox, rect[0], rect[1])
                    ocr_elements.append(e)
            except Exception as e:
                logger.debug("OCR extraction failed: %s", e, exc_info=True)
            self._ocr_cache = (sig, ocr_elements)
        uia_elements = []
        try:
            uia_elements = uia_module.get_elements()
        except Exception as e:
            logger.debug("UIA extraction failed: %s", e, exc_info=True)
        elements = merge(ocr_elements, uia_elements)
        path = None
        if self.screenshot_dir:
            import os
            os.makedirs(self.screenshot_dir, exist_ok=True)
            base = os.path.join(self.screenshot_dir, f"{int(time.time() * 1000)}")
            img.save(base + ".raw.png")
            local = [_shift_element(copy(e), -rect[0], -rect[1]) for e in elements]
            path = base + ".png"
            overlay(img, local).save(path)
        return Observation(
            screenshot_path=path,
            timestamp=time.time(),
            active_window=active_window,
            dpi_scale=self.dpi_scale,
            elements=elements,
            scene=self._build_scene(elements, active_window, img, rect),
        )

    def observe_light(self) -> Observation:
        """OCR-only observation for in-batch verification.

        Skips UIA, OmniParser web controls and layout regions -- the expensive
        model layers. Returns a scene built from OCR text nodes only, with no
        screenshot artifact and no SceneMemory push.
        """
        try:
            rect = get_active_window_rect()
        except Exception as e:
            logger.debug("get_active_window_rect failed: %s", e, exc_info=True)
            rect = (0, 0, 0, 0)
        active_window = ""
        try:
            active_window = get_active_window()
        except Exception as e:
            logger.debug("get_active_window failed: %s", e, exc_info=True)
        img = capture_rect(rect)
        ocr_elements = []
        try:
            for e in ocr_module.get_elements(img):
                e.bbox = _shift_bbox(e.bbox, rect[0], rect[1])
                ocr_elements.append(e)
        except Exception as e:
            logger.debug("OCR extraction failed (light): %s", e, exc_info=True)
        scene = build_scene(ocr_elements, active_window)
        return Observation(
            screenshot_path=None,
            timestamp=time.time(),
            active_window=active_window,
            dpi_scale=self.dpi_scale,
            elements=ocr_elements,
            scene=scene,
        )

    def _build_scene(self, elements, active_window, img, rect):
        regions = self._detect_regions(img, rect)
        web_nodes = self._detect_web_controls(active_window, img, rect, elements)
        return build_scene(elements, active_window, regions=regions, web_nodes=web_nodes)

    def _is_browser_window(self, title: str) -> bool:
        t = (title or "").lower()
        return any(k in t for k in _WEB_BROWSER_KEYWORDS)

    def _detect_web_controls(self, active_window, img, rect, elements):
        """OmniParser web/UI controls for the active window.

        Runs for ANY window (not just browsers): OmniParser also understands
        plain desktop UIs, so buttons/inputs in Electron apps, tool windows and
        dialogs benefit too. Disable via env MIO_CUA_WEB_EVERYWHERE=0 to keep
        the old browser-title gate.

        Reuses the same content signature as the OCR cache, so a window whose
        content hasn't changed skips the model entirely (both layers are
        invalidated together).

        Nodes get ids past the merged-element range so they never collide with
        the element ids InputController resolves.
        """
        if os.environ.get("MIO_CUA_WEB_EVERYWHERE", "1") == "0" \
                and not self._is_browser_window(active_window):
            return []
        if self._web_cache is not None and self._web_cache[0] == self._last_signature:
            return list(self._web_cache[1])
        try:
            from mio_cua.scene.omniparser import parse
            nodes = parse(img)
        except Exception as e:
            logger.debug("web control detection failed: %s", e, exc_info=True)
            return []
        dx, dy = rect[0], rect[1]
        base = 10000  # ids above the element id range
        for i, n in enumerate(nodes):
            l, t, w, h = n.bbox
            n.bbox = (l + dx, t + dy, w, h)
            n.id = base + i
        self._web_cache = (self._last_signature, nodes)
        return nodes

    def _detect_regions(self, img, rect):
        """Run layout analysis on the window capture; shift boxes to screen px."""
        try:
            regions = analyze_regions(img)
        except Exception as e:
            logger.debug("region analysis failed: %s", e, exc_info=True)
            return []
        dx, dy = rect[0], rect[1]
        shifted = []
        for r in regions:
            l, t, w, h = r.bbox
            shifted.append(Region(kind=r.kind, bbox=(l + dx, t + dy, w, h),
                                  confidence=r.confidence, text=r.text))
        return shifted

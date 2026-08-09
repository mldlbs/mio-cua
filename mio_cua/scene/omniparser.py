"""OmniParser web-UI element detection (optional heavy dependency).

OmniParser (microsoft) parses a UI screenshot into structured elements:
- ``text`` nodes: plain text/headings (interactivity=False)
- ``icon`` nodes: interactive controls -- buttons, links, input boxes
  (interactivity=True) with a semantic description.

This is the "perceive a web page like a human" path: no DOM access, pure
vision. The dependency is optional and heavy (torch+transformers+ultralytics,
~2GB models), so it is lazy-loaded and configured via env vars:

- ``OMNIPARSER_DIR``: path to the cloned OmniParser repo (default
  ``D:\\Users\\gf1913\\Temp\\opencode\\OmniParser``)
- ``OMNIPARSER_WEIGHTS``: weights dir (default ``<OMNIPARSER_DIR>/weights``)

If anything is missing, ``parse`` returns [] and the Scene simply has no
web-control nodes.
"""

import base64
import io
import logging
import os
import time

from PIL import Image

from mio_cua.scene.graph import SceneNode

logger = logging.getLogger(__name__)

# OmniParser's Florence-2 caption model + processor are fully cached locally
# (HF Hub cache populated when the models were first set up). Force offline so
# the first parse does not stall on an unreachable HF CDN connection.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

_parser = None

# Project-local model home (default). Can be overridden via OMNIPARSER_DIR.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_OMNIPARSER_DIR = os.path.join(_PROJECT_ROOT, "models", "omniparser")


def _config():
    omni_dir = os.environ.get("OMNIPARSER_DIR", _DEFAULT_OMNIPARSER_DIR)
    weights = os.environ.get("OMNIPARSER_WEIGHTS", os.path.join(omni_dir, "weights"))
    return {
        "som_model_path": os.path.join(weights, "icon_detect_v3", "model.pt"),
        "caption_model_name": "florence2",
        "caption_model_path": os.path.join(weights, "icon_caption_florence"),
        "BOX_TRESHOLD": 0.05,
    }


def _load():
    global _parser
    if _parser is not None:
        return _parser
    cfg = _config()
    if not os.path.isfile(cfg["som_model_path"]):
        logger.warning("OmniParser weights not found (%s); web controls disabled",
                       cfg["som_model_path"])
        return None
    try:
        omni_dir = os.environ.get("OMNIPARSER_DIR", _DEFAULT_OMNIPARSER_DIR)
        import sys
        if omni_dir not in sys.path:
            sys.path.insert(0, omni_dir)
        from util.omniparser import Omniparser
        t0 = time.time()
        _parser = Omniparser(cfg)
        logger.info("OmniParser loaded in %.1fs", time.time() - t0)
    except Exception as e:
        logger.warning("OmniParser init failed (%s); web controls disabled", e)
        _parser = None
    return _parser


def parse(image, min_conf: float = 0.5) -> list:
    """Parse a PIL image into SceneNodes; returns [] if OmniParser unavailable.

    OmniParser returns normalized bboxes (0..1 relative to the image). The
    caller shifts them to screen coordinates.
    """
    parser = _load()
    if parser is None:
        return []
    try:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        _, parsed = parser.parse(b64)
    except Exception as e:
        logger.debug("OmniParser parse failed: %s", e, exc_info=True)
        return []
    w, h = image.size
    nodes = []
    for idx, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue
        content = (item.get("content") or "").strip()
        bbox = item.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x0, y0, x1, y1 = [float(v) for v in bbox]
        left, top = int(x0 * w), int(y0 * h)
        bw, bh = int((x1 - x0) * w), int((y1 - y0) * h)
        if bw <= 0 or bh <= 0:
            continue
        interactive = bool(item.get("interactivity", False))
        etype = item.get("type") or ("icon" if interactive else "text")
        # Interactivity is the ground truth; type names come from OmniParser.
        node_type = "button" if interactive else "text"
        nodes.append(SceneNode(
            id=-1,  # assigned by caller after merging with element ids
            type=node_type,
            bbox=(left, top, bw, bh),
            text=content,
            semantic=content or None,
            confidence=min_conf,
            source="web",
            role="web",
            state={"enabled": True, "visible": True, "interactive": interactive,
                   "focused": False},
            metadata={"omni_type": etype},
        ))
    return nodes

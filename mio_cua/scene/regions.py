"""Layout regions via rapid_layout (optional dependency).

rapid_layout runs PaddleOCR-style document layout models (pp_layout_cdla /
pp_layout_publaynet) on ONNXRuntime with DirectML acceleration. It produces
coarse regions (title/text/table/figure/header/footer...) that give the agent
page structure.

The dependency is optional: if rapid_layout is not installed, ``analyze``
returns [] and the Scene simply has no regions.
"""

import logging

logger = logging.getLogger(__name__)

from mio_cua.scene.graph import Region

_model = None
_model_type = None

# Classes that are actionable-ish / useful for the agent to know about.
_USEFUL_KINDS = {
    "text", "title", "table", "figure", "figure_caption", "table_caption",
    "header", "footer", "reference", "equation", "list", "caption",
}


def _load():
    global _model, _model_type
    if _model is not None:
        return _model
    try:
        from rapid_layout import RapidLayout
    except Exception as e:  # rapid_layout not installed
        logger.debug("rapid_layout not available: %s", e)
        return None
    try:
        _model = RapidLayout(engine_cfg={"use_dml": True})
        _model_type = "pp_layout_cdla"
    except Exception as e:
        logger.warning("rapid_layout init failed (%s); disabling regions", e)
        _model = None
    return _model


def analyze(image, min_conf: float = 0.5) -> list:
    """Run layout analysis on a PIL image; return Region list (may be empty).

    Coordinates are returned in image pixels (the active-window region), so the
    caller must shift them to screen coordinates if needed.
    """
    model = _load()
    if model is None:
        return []
    try:
        result = model(image)
    except Exception as e:
        logger.debug("layout inference failed: %s", e)
        return []
    if not result or not result.boxes:
        return []
    regions = []
    for box, name, score in zip(result.boxes, result.class_names, result.scores):
        if score < min_conf:
            continue
        left, top, right, bottom = [int(v) for v in box]
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0:
            continue
        regions.append(Region(
            kind=str(name or "unknown"),
            bbox=(left, top, w, h),
            confidence=float(score),
        ))
    regions.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
    return regions


def regions_summary(regions) -> str:
    """Compact text rendering of regions for the LLM."""
    if not regions:
        return ""
    lines = []
    for r in regions:
        if r.kind not in _USEFUL_KINDS:
            continue
        label = r.text or r.kind
        lines.append(f"- {label} bbox={r.bbox}")
    return "\n".join(lines)

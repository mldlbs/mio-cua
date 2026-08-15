import logging
import os

from mio_cua.models.element import Element

logger = logging.getLogger(__name__)


def _boxes_to_elements(result: list) -> list:
    elements = []
    for i, (box, text, score) in enumerate(result):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        left, top = int(min(xs)), int(min(ys))
        width, height = int(max(xs) - left), int(max(ys) - top)
        elements.append(Element(
            id=i, source="ocr", text=str(text), role="text",
            bbox=(left, top, width, height), confidence=float(score),
        ))
    return elements


_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        kwargs = {}
        want_dml = os.environ.get("mio_cua_OCR_DEVICE", "dml").lower() == "dml"
        # mio_cua_GPU=0 forces every GPU path (OCR/Regions) to CPU, so the
        # onnxruntime/DirectML sessions do not run concurrently and spike VRAM.
        if want_dml and os.environ.get("mio_cua_GPU", "1") != "0":
            kwargs = {"det_use_dml": True, "cls_use_dml": True, "rec_use_dml": True}
        try:
            _engine = RapidOCR(**kwargs)
        except Exception as e:
            logger.warning("DML/GPU OCR init failed (%s); falling back to CPU", e)
            _engine = RapidOCR()
    return _engine


def get_elements(image) -> list:
    """OCR a PIL image; returns Element list (empty if no text found)."""
    result, _ = _get_engine()(image)
    if not result:
        return []
    return _boxes_to_elements(result)

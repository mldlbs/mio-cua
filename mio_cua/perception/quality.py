"""Perception Quality Gate and Visual Fallback.

Quality Gate: evaluates SceneGraph after construction.
  - node_count: total scene nodes
  - interactive_count: nodes with click/type affordances
  - container_only: only group/container nodes, no leaf content

When quality is insufficient, triggers visual fallback:
  - Enhanced OCR (larger text, higher contrast)
  - Region-based element detection
  - Merges fallback nodes into Scene Graph

Design principles:
  - App-agnostic: works for any desktop app
  - Threshold-based, not app-specific
  - Fallback supplements, never replaces, primary pipeline
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from mio_cua.scene.graph import SceneGraph, SceneNode

logger = logging.getLogger(__name__)

CONTAINER_TYPES = {"group"}


@dataclass
class QualityReport:
    """Result of scene graph quality assessment.

    Uses confidence-based scoring instead of fixed thresholds.
    Scores range 0.0 (insufficient) to 1.0 (excellent).
    """
    node_count: int = 0
    interactive_count: int = 0
    container_count: int = 0
    leaf_count: int = 0
    has_search_box: bool = False
    coverage_score: float = 0.0    # how much of the UI is visible
    interaction_score: float = 0.0  # how many actionable elements
    semantic_score: float = 0.0    # quality of text/labels
    confidence: float = 0.0        # overall confidence
    is_usable: bool = True
    reason: str = ""

    def __post_init__(self):
        self.leaf_count = self.node_count - self.container_count


def _compute_scores(scene) -> QualityReport:
    """Compute quality scores from scene graph."""
    nodes = scene.nodes or []
    node_count = len(nodes)

    interactive_count = 0
    container_count = 0
    has_search_box = False
    text_quality_sum = 0.0
    text_count = 0

    for node in nodes:
        ntype = getattr(node, "type", "unknown")
        text = (getattr(node, "text", "") or "").strip()
        semantic = (getattr(node, "semantic", "") or "").lower()
        confidence = getattr(node, "confidence", 1.0)

        if ntype in CONTAINER_TYPES or "mmuirendersubwindow" in semantic:
            container_count += 1
        else:
            interactive_count += 1

        if ("search" in semantic or "搜索" in text
                or "input" in ntype or ntype == "textbox"):
            has_search_box = True

        if text:
            text_count += 1
            # Longer text with higher confidence = better quality
            text_quality_sum += min(len(text) / 20.0, 1.0) * confidence

    leaf_count = node_count - container_count

    # ── Coverage score: how many nodes suggest a visible UI ──
    # Logarithmic scale: 1 node → 0.1, 5 → 0.5, 10 → 0.7, 20 → 0.85, 50+ → 1.0
    import math
    if node_count <= 0:
        coverage_score = 0.0
    else:
        coverage_score = min(1.0, math.log2(max(node_count, 1) + 1) / 6.0)

    # ── Interaction score: ratio of interactive to total nodes ──
    if node_count > 0:
        interaction_score = interactive_count / node_count
    else:
        interaction_score = 0.0

    # ── Semantic score: text quality across nodes ──
    if text_count > 0:
        semantic_score = text_quality_sum / text_count
    else:
        semantic_score = 0.0

    # ── Overall confidence: weighted combination ──
    confidence = (
        0.4 * coverage_score
        + 0.3 * interaction_score
        + 0.3 * semantic_score
    )

    # ── Usability decision ──
    is_usable = confidence >= 0.3

    if not is_usable:
        if node_count < 3:
            reason = f"very few nodes ({node_count})"
        elif interactive_count == 0:
            reason = f"no interactive nodes ({node_count} total)"
        elif semantic_score < 0.1:
            reason = f"no readable text ({text_count} text nodes)"
        else:
            reason = f"low confidence ({confidence:.2f})"
    else:
        reason = f"ok (confidence={confidence:.2f})"

    return QualityReport(
        node_count=node_count,
        interactive_count=interactive_count,
        container_count=container_count,
        leaf_count=leaf_count,
        has_search_box=has_search_box,
        coverage_score=coverage_score,
        interaction_score=interaction_score,
        semantic_score=semantic_score,
        confidence=confidence,
        is_usable=is_usable,
        reason=reason,
    )


def assess_quality(scene: SceneGraph) -> QualityReport:
    """Evaluate whether a SceneGraph provides sufficient information for planning.

    Uses confidence-based scoring:
      - coverage_score: how much of the UI is visible (log scale)
      - interaction_score: ratio of interactive to total nodes
      - semantic_score: text quality and labels
      - confidence: weighted combination (usable if >= 0.3)
    """
    if scene is None:
        # No scene graph (e.g. scripted/simulation observations or a degenerate
        # perception result). Treat as insufficient rather than crashing so the
        # loop can still render a plan with a quality hint instead of aborting.
        return QualityReport(node_count=0, is_usable=False, reason="no scene graph")
    return _compute_scores(scene)


# ── Visual Fallback ──

def visual_fallback_nodes(
    img,
    rect: Tuple[int, int, int, int],
    existing_node_count: int = 0,
    id_offset: int = 5000,
) -> List[SceneNode]:
    """Generate scene nodes from screenshot when primary pipeline is insufficient.

    Uses enhanced OCR with preprocessing to detect text elements that
    the standard pipeline may have missed.

    Returns:
        List of SceneNode objects with ids starting at id_offset.
    """
    nodes = []

    # ── Strategy 1: Enhanced OCR with grayscale + contrast ──
    try:
        from mio_cua.vision import ocr as ocr_module
        from PIL import ImageEnhance
        import numpy as np

        # Preprocess: grayscale + contrast boost for small text
        gray = img.convert("L")
        enhanced = ImageEnhance.Contrast(gray).enhance(2.0)
        # Convert back to RGB for OCR engine
        rgb = enhanced.convert("RGB")

        ocr_elements = ocr_module.get_elements(np.array(rgb))
        for i, elem in enumerate(ocr_elements):
            # Shift bbox to screen coordinates
            left, top, w, h = elem.bbox
            screen_bbox = (left + rect[0], top + rect[1], w, h)
            nodes.append(SceneNode(
                id=id_offset + i,
                type="text",
                bbox=screen_bbox,
                text=getattr(elem, "text", ""),
                confidence=getattr(elem, "confidence", 0.8),
                source="ocr_fallback",
                semantic="ocr_detected",
            ))
        if nodes:
            logger.info("visual_fallback: enhanced OCR found %d nodes", len(nodes))
    except Exception as e:
        logger.debug("visual_fallback enhanced OCR failed: %s", e)

    # ── Strategy 2: Region-based element detection ──
    # Detect rectangular regions that might be clickable (chat items, buttons)
    try:
        from mio_cua.scene.regions import analyze
        regions = analyze(img)
        for i, r in enumerate(regions):
            if r.kind in ("text", "title", "header"):
                left, top, w, h = r.bbox
                screen_bbox = (left + rect[0], top + rect[1], w, h)
                nodes.append(SceneNode(
                    id=id_offset + len(nodes),
                    type="text",
                    bbox=screen_bbox,
                    text=getattr(r, "text", "") or r.kind,
                    confidence=getattr(r, "confidence", 0.7),
                    source="region_fallback",
                    semantic=f"region_{r.kind}",
                ))
        if len(regions) > 0:
            logger.info("visual_fallback: region analysis found %d regions", len(regions))
    except Exception as e:
        logger.debug("visual_fallback region analysis failed: %s", e)

    return nodes


def enhance_scene_with_fallback(
    scene: SceneGraph,
    img,
    rect: Tuple[int, int, int, int],
    quality: Optional[QualityReport] = None,
) -> SceneGraph:
    """Enhance a SceneGraph with visual fallback nodes when quality is insufficient.

    If quality report is not provided, it will be assessed automatically.
    Returns the enhanced SceneGraph (mutates original).
    """
    if quality is None:
        quality = assess_quality(scene)

    if quality.is_usable:
        return scene

    logger.info("Scene quality insufficient (%s), triggering visual fallback", quality.reason)

    # Determine id offset to avoid collisions
    max_id = max((n.id for n in scene.nodes), default=0) + 1
    fallback_nodes = visual_fallback_nodes(img, rect, id_offset=max_id)

    # Merge fallback nodes into scene
    scene.nodes.extend(fallback_nodes)

    # Rebuild relations and affordances with new nodes
    try:
        from mio_cua.scene.relations import RelationBuilder
        from mio_cua.scene.affordances import AffordanceBuilder

        scene.relations = RelationBuilder(scene.nodes).build()
        affordances, display_ids = AffordanceBuilder(scene.nodes, scene.relations).build()
        scene.affordances = affordances
        scene.display_ids = display_ids
    except Exception as e:
        logger.debug("Failed to rebuild relations/affordances: %s", e)

    # Re-assess quality
    new_quality = assess_quality(scene)
    logger.info("After fallback: %d nodes (was %d), usable=%s",
                new_quality.node_count, quality.node_count, new_quality.is_usable)

    return scene

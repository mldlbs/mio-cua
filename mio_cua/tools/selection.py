"""Text selection: select an element's text by dragging across its bbox.

``select_element`` is a COMPOSITE tool built on ``drag`` (not Shift+Click, which
depends on focus and behaves inconsistently across apps). It assumes SINGLE-LINE
text (mid-height horizontal drag). The agent copies with ctrl+c and verifies the
result via ``clipboard_get``; verification is the Agent's decision, not this
tool's.
"""

from mio_cua.models.action_result import ActionResult
from mio_cua.tools.drag import drag


def select_element(ctx, element_id=None):
    """Select an element's text by dragging from its left edge to its right edge
    at mid-height (SINGLE-LINE text assumption). Caller copies with ctrl+c and
    verifies via clipboard_get."""
    if element_id is None:
        return ActionResult(ctx.current_action_id, False,
                            "element_id required", retryable=True)
    # observations live on the CONTROLLER; fall back to ctx.current_observation
    obs = getattr(ctx.controller, "current_observation", None) or ctx.current_observation
    if obs is None:
        return ActionResult(ctx.current_action_id, False,
                            "no observation available to resolve element_id", retryable=True)
    for e in obs.elements:
        if e.id == element_id or str(e.id) == str(element_id):
            left, top, width, height = e.bbox
            x1 = left + 2
            x2 = max(x1 + 1, left + width - 2)
            y = top + height // 2
            return drag(ctx, x1=x1, y1=y, x2=x2, y2=y)
    # Fall back to scene nodes (e.g. OmniParser web controls whose ids live
    # above the merged-element range).
    scene = getattr(obs, "scene", None)
    if scene is not None:
        for n in getattr(scene, "nodes", []) or []:
            if n.id == element_id or str(n.id) == str(element_id):
                left, top, width, height = n.bbox
                x1 = left + 2
                x2 = max(x1 + 1, left + width - 2)
                y = top + height // 2
                return drag(ctx, x1=x1, y1=y, x2=x2, y2=y)
    return ActionResult(ctx.current_action_id, False,
                        f"element_id {element_id!r} not found in current observation",
                        retryable=True)

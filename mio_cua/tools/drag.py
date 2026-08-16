"""Drag tool: press and drag the mouse between two points (primitive).

Text selection, icon moving and sliders all start from a drag. This is a pure
coordinate primitive -- higher-level tools (e.g. select_element) build on it.
"""

from mio_cua.models.action import Action
from mio_cua.models.action_result import ActionResult


def drag(ctx, x1=None, y1=None, x2=None, y2=None, element_id=None):
    """Press the left button at (x1,y1), drag to (x2,y2), release.

    Optionally resolves ``element_id`` to its bbox (from left+2 to right-2 at
    mid-height) when no explicit coordinates are given.
    """
    if element_id is not None:
        x1, y1, x2, y2 = _resolve_element(ctx, element_id)
    if x1 is None or y1 is None or x2 is None or y2 is None:
        return ActionResult(ctx.current_action_id, False,
                            "x1/y1/x2/y2 or element_id required", retryable=True)
    result = ctx.controller.execute(Action(
        id=ctx.current_action_id, type="drag",
        params={"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)},
    ))
    return ActionResult(ctx.current_action_id, result.sent,
                        result.error or "dragged", retryable=not result.sent)


def _resolve_element(ctx, element_id):
    obs = getattr(ctx, "current_observation", None)
    if obs is None:
        obs = getattr(ctx.controller, "current_observation", None)
    if obs is None:
        raise RuntimeError("element_id unresolved: no observation available")
    for e in obs.elements:
        if e.id == element_id or str(e.id) == str(element_id):
            left, top, width, height = e.bbox
            x1 = left + 2
            x2 = max(x1 + 1, left + width - 2)
            y = top + height // 2
            return x1, y, x2, y
    raise RuntimeError(f"element_id {element_id!r} not found in current observation")

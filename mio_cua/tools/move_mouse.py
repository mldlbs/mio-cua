from mio_cua.models.action import Action
from mio_cua.models.action_result import ActionResult


def move_mouse(ctx, x=None, y=None, element_id=None):
    if element_id is None and (x is None or y is None):
        return ActionResult(ctx.current_action_id, False, "x/y or element_id required", retryable=True)
    params = {}
    if element_id is not None:
        params["element_id"] = element_id
    else:
        params["x"], params["y"] = x, y
    result = ctx.controller.execute(Action(id=ctx.current_action_id, type="move_mouse", params=params))
    return ActionResult(ctx.current_action_id, result.sent, result.error or "moved", retryable=not result.sent)

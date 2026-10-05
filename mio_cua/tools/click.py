from mio_cua.models.action import Action
from mio_cua.models.action_result import ActionResult


def click(ctx, element_id=None, x=None, y=None, button="left", double=False):
    if element_id is None and (x is None or y is None):
        return ActionResult(ctx.current_action_id, False, "x/y or element_id required", retryable=True)
    params = {"button": button, "double": double}
    if element_id is not None:
        params["element_id"] = element_id
    else:
        params["x"], params["y"] = x, y
    result = ctx.controller.execute(Action(id=ctx.current_action_id, type="click", params=params))
    return ActionResult(ctx.current_action_id, result.sent, result.error or "clicked", retryable=not result.sent)

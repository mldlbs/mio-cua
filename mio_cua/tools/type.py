import time

from mio_cua.models.action import Action
from mio_cua.models.action_result import ActionResult


def type(ctx, text=None, element_id=None):
    if not text:
        return ActionResult(ctx.current_action_id, False, "text required", retryable=True)
    if element_id is not None:
        # focus the target element first, select-all (replace existing content),
        # then type into it
        focus = ctx.controller.execute(Action(
            id=ctx.current_action_id, type="click",
            params={"element_id": element_id, "button": "left"},
        ))
        if not focus.sent:
            return ActionResult(ctx.current_action_id, False, focus.error or "could not focus field", retryable=True)
        time.sleep(0.2)
        ctx.controller.execute(Action(
            id=ctx.current_action_id, type="key", params={"keys": "ctrl+a"},
        ))
        time.sleep(0.1)
    result = ctx.controller.execute(Action(
        id=ctx.current_action_id, type="type", params={"text": text},
    ))
    return ActionResult(ctx.current_action_id, result.sent, result.error or "typed", retryable=not result.sent)

from mio_cua.models.action import Action
from mio_cua.models.action_result import ActionResult


def key(ctx, keys):
    result = ctx.controller.execute(Action(id=ctx.current_action_id, type="key", params={"keys": keys}))
    return ActionResult(ctx.current_action_id, result.sent, result.error or "key sent", retryable=not result.sent)

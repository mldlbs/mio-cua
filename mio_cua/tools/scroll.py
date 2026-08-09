from mio_cua.models.action import Action
from mio_cua.models.action_result import ActionResult


def scroll(ctx, direction="down", amount=1):
    result = ctx.controller.execute(Action(id=ctx.current_action_id, type="scroll", params={"direction": direction, "amount": amount}))
    return ActionResult(ctx.current_action_id, result.sent, result.error or "scrolled", retryable=not result.sent)

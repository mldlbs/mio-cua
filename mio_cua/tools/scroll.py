from mio_cua.models.action import Action
from mio_cua.models.action_result import ActionResult


def scroll(ctx, direction="down", amount=1, region=None):
    """Scroll the wheel.

    ``region`` is a [left, top, width, height] bbox; when given, the cursor is
    moved to the region center first so the wheel affects that specific area
    (e.g. a chat list) instead of whatever happens to be under the cursor.
    """
    params = {"direction": direction, "amount": amount}
    if region:
        left, top, width, height = region
        params["x"] = int(left + width / 2)
        params["y"] = int(top + height / 2)
    result = ctx.controller.execute(
        Action(id=ctx.current_action_id, type="scroll", params=params)
    )
    return ActionResult(ctx.current_action_id, result.sent, result.error or "scrolled", retryable=not result.sent)

import time

from mio_cua.models.action_result import ActionResult


def wait(ctx, seconds):
    time.sleep(seconds)
    return ActionResult(ctx.current_action_id, True, f"waited {seconds}s")

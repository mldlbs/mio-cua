from mio_cua.models.action_result import ActionResult


def fail(ctx, reason):
    ctx.finished_status = "FAIL"
    ctx.finished_summary = str(reason)
    return ActionResult(ctx.current_action_id, False, f"task failed: {reason}")
